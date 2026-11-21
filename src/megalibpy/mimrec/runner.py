"""Thin native Mimrec commands with immutable execution records."""

from dataclasses import replace
from glob import escape
from pathlib import Path
import warnings
import hashlib
import re

from ..execution import ExecutionInput, ExecutionPlan, ExecutionResult, MEGAlibRuntime, SimulationWorkspace
from ..execution.executor import Executor
from ..execution.provenance import configuration_snapshot, decode_content, file_record, read_execution, resolve_upstream, sha256


def _event_file(path):
    path = Path(path).expanduser().resolve(strict=True)
    if not path.is_file() or not path.name.endswith((".tra", ".tra.gz")):
        raise ValueError("tra_path requires a .tra or .tra.gz file")
    return path


def _input(input_data, analysis_id=None):
    experiment = None
    if isinstance(input_data, SimulationWorkspace):
        experiment = input_data
        # Existing reconstructed branches take precedence over an external origin.
        # select() rejects ambiguity; it never guesses a latest result.
        if any(t.get("tool", t.get("stage")) == "revan" for t in
               experiment._read().get("executions", experiment._read().get("tasks", {})).values()):
            input_data = experiment.select("revan", analysis_id=analysis_id)
        elif experiment.external_tra_path is not None:
            return _event_file(experiment.external_tra_path), None, experiment
        else:
            input_data = experiment.select("revan", analysis_id=analysis_id)
    if isinstance(input_data, ExecutionResult):
        if input_data.workspace_dir is not None:
            experiment = SimulationWorkspace(input_data.workspace_dir)
        input_data = input_data.as_input("tra")
    if isinstance(input_data, ExecutionInput):
        if input_data.output_group != "tra":
            raise ValueError("Mimrec requires the 'tra' output group")
        _, record = resolve_upstream(input_data)
        if input_data.workspace_dir is not None:
            experiment = SimulationWorkspace(input_data.workspace_dir)
        paths = tuple(Path(p) for p in record["paths"])
        if len(paths) != 1:
            raise ValueError("Mimrec accepts one native input per call; select one file "
                             "with result.as_input('tra', paths=[...])")
        reference = replace(input_data, execution_id=record["execution_id"], paths=paths)
        return _event_file(paths[0]), reference, experiment
    path = Path(input_data).expanduser().resolve(strict=True)
    if path.is_dir():
        return _input(SimulationWorkspace(path), analysis_id=analysis_id)
    raise ValueError("working_space expects an experiment or result; use tra_path with output_dir")


def _revan_analysis(reference):
    """Identify the registered Revan parent; names never replace execution links."""
    if reference is None:
        return None
    _, record, _ = read_execution(reference.manifest_path, reference.execution_id)
    if record.get("tool") == "revan":
        return record.get("analysis_id") or (Path(record["data_group"]).name if record.get("data_group") else None)
    if record.get("revan_analysis_id") is not None:
        return record["revan_analysis_id"]
    # Compatibility with already-created groups whose command records predate
    # named analysis IDs: inspect their registered entry, never a latest file.
    if record.get("tool") == "mimrec" and reference.workspace_dir is not None:
        data = SimulationWorkspace(reference.workspace_dir)._read()
        entry = data.get("groups", {}).get(record.get("data_group"), {})
        if entry.get("revan_analysis_id") is not None:
            return entry["revan_analysis_id"]
        parent = entry.get("input_reference")
        if parent:
            _, previous, _ = read_execution(parent["manifest_path"], parent["execution_id"])
            if previous.get("tool") == "revan":
                return previous.get("analysis_id") or (Path(previous["data_group"]).name if previous.get("data_group") else None)
    return None


def _prepare(attempt, event_file, geometry, config, executable, operation, output_name, reference,
             overrides, isolate_settings, config_base=None, original_path=None, config_content=None, revan_analysis_id=None):
    executed, config_record = configuration_snapshot(attempt, config, "mimrec", content=config_content, cwd=config_base, original_path=original_path)
    home = attempt.log_path("native-home")
    if isolate_settings:
        home.mkdir(exist_ok=True)
    if attempt.owner is not None and attempt.number > 1:
        path = Path(output_name)
        suffix = ".tra.gz" if output_name.endswith(".tra.gz") else path.suffix
        output_name = f"{output_name[:-len(suffix)]}-{attempt.number:03d}{suffix}"
    product = attempt.products_dir / output_name
    if attempt.owner is not None:
        attempt.owner._claim_product(attempt, product)
    command = [executable, "-c", str(executed), "-f", str(event_file), "-o", str(product)]
    if geometry is not None:
        command.extend(("-g", str(geometry)))
    changes = []
    for key, value in overrides.items():
        name = key.replace("_", ".")
        text = ("true" if value else "false") if isinstance(value, bool) else str(value)
        command.extend(("-C", f"{name}={text}"))
        changes.append({"parameter": name, "value": text})
    command.extend(("-n", {"extract_events": "-x", "image": "-i", "spectrum": "-s", "arm": "-a"}[operation]))
    return ExecutionPlan(tuple(command), config_base or config.parent, {"tra" if operation == "extract_events" else operation: escape(product.name)}, {
        "operation": operation,
        "revan_analysis_id": revan_analysis_id,
        "input_file": file_record(event_file, hash_limit=0),
        "configuration": {**config_record,
                          "settings_home": str(home.relative_to(attempt.root)) if isolate_settings else None},
        "geometry": None if geometry is None else str(geometry),
        "configuration_overrides": changes,
    }, upstream=() if reference is None else (reference,), environment={"HOME": str(home)} if isolate_settings else {})


class Mimrec:
    """Run independent native Mimrec operations without importing PyROOT.

    Parameters
    ----------
    runtime : MEGAlibRuntime or None, optional
        Direct or setup-script runtime. None selects direct execution.
    revan_analysis_id : str or None, optional
        Explicit upstream Revan analysis name. Workspace entry selects this
        Revan group when the Mimrec group has no successful extraction or saved
        entry. Default none allows an explicit result or unambiguous legacy input.
        A supplied name must match the actual recorded Revan provenance.
    analysis_id : str or None, optional
        Mimrec's own workspace-local group name. Defaults to revan_analysis_id
        when supplied, otherwise none. A bound name places
        all calls under mimrec/<analysis_id>, reusing that group's defaults.
        A workspace input uses the group's unique successful extraction first,
        then its recorded input, otherwise the explicitly bound revan_analysis_id.
        Explicit input results preserve their exact upstream identity, allowing
        differently named Mimrec branches from one Revan result.
        It identifies data/configuration context, not a command execution or
        configuration hash. Construction creates no files and runs no process.
        Names use letters, digits, underscores or hyphens, starting with a letter
        or digit. The same name can be reused in independent workspaces.
    executable : str or pathlib.Path, optional
        Native executable name or path, default ``"mimrec"``.

    Notes
    -----
    Configurations are opaque snapshots. MEGAlib controls event selection,
    configuration semantics, geometry and external resources. Each call runs
    one native operation with an independent execution record in a shared data group.
    A bound analysis_id avoids repeating group selection; actual input data still
    comes from each call's working_space/tra_path. task names an operation output
    folder inside that group. None preserves result-based automatic grouping.
    """

    def __init__(self, runtime=None, *, revan_analysis_id=None, analysis_id=None, executable="mimrec"):
        for name, value in (("analysis_id", analysis_id), ("revan_analysis_id", revan_analysis_id)):
            if value is not None and (not isinstance(value, str) or
                                      not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value)):
                raise ValueError(f"{name} must contain letters, digits, '_' or '-' and start with a letter/digit")
        self.revan_analysis_id = revan_analysis_id
        self.analysis_id = analysis_id if analysis_id is not None else revan_analysis_id
        self.runtime = runtime if runtime is not None else MEGAlibRuntime.direct()
        self.executable = str(executable)

    def _run(self, operation, working_space, tra_path, output_dir, config_file,
             geometry, task, output_name, timeout, isolate_settings, configuration, attempt, log_mode):
        if self.analysis_id is not None:
            if attempt is not None and attempt != self.analysis_id:
                raise ValueError("attempt conflicts with the Mimrec object's analysis_id")
            attempt = self.analysis_id
        if (working_space is None) == (tra_path is None):
            raise ValueError("Supply exactly one of working_space or tra_path")
        if tra_path is not None and output_dir is None:
            raise ValueError("tra_path requires output_dir for the experiment root")
        if not isinstance(isolate_settings, bool):
            raise ValueError("isolate_settings must be bool")
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be positive")
        if not isinstance(output_name, str) or not output_name or output_name in (".", "..") or Path(output_name).name != output_name:
            raise ValueError("output_name must be a filename inside products, without directories")
        if operation == "extract_events" and not output_name.endswith((".tra", ".tra.gz")):
            raise ValueError("Event extraction output_name must end in .tra or .tra.gz")
        if operation != "extract_events" and not Path(output_name).suffix:
            raise ValueError("Plot output_name requires an explicit native output suffix")
        if tra_path is not None:
            path, reference, inherited = _event_file(tra_path), None, None
        elif attempt is not None and not isinstance(working_space, (ExecutionInput, ExecutionResult)):
            inherited = working_space if isinstance(working_space, SimulationWorkspace) else SimulationWorkspace(working_space)
            group_key = "mimrec/" + attempt
            entry = inherited._writable()["groups"].get(group_key)
            if entry is None:
                if self.analysis_id is None:
                    raise ValueError("Select an existing Mimrec attempt")
                if self.revan_analysis_id is None and any(
                        record.get("tool") == "revan" for record in inherited._read().get("executions", {}).values()):
                    raise ValueError("revan_analysis_id is required to start a named Mimrec analysis from a workspace; "
                                     "or pass an explicit Revan result")
                path, reference, inherited = _input(working_space, analysis_id=self.revan_analysis_id)
            else:
                extractions = [r for r in inherited._read()["executions"].values()
                               if r["data_group"] == group_key and r["operation"] == "extract_events"
                               and r["status"] == "succeeded"]
                if extractions:
                    selected = inherited.select("mimrec", attempt=attempt, operation="extract_events")
                    path, reference, _ = _input(selected)
                elif entry.get("input_reference"):
                    saved = entry["input_reference"]
                    selected = ExecutionInput(Path(saved["manifest_path"]), saved["output_group"],
                                              saved["execution_id"], tuple(Path(p) for p in saved["paths"]),
                                              inherited.root)
                    path, reference, _ = _input(selected)
                elif "input_file" in entry:
                    path, reference = _event_file(entry["input_file"]["path"]), None
                else:
                    if self.analysis_id is None:
                        raise ValueError("Mimrec attempt has no prepared input; pass an explicit input")
                    path, reference, _ = _input(inherited, analysis_id=self.revan_analysis_id)
        else:
            path, reference, inherited = _input(working_space, analysis_id=self.revan_analysis_id)
        experiment = SimulationWorkspace(output_dir) if output_dir is not None else inherited
        if experiment is None:
            raise ValueError("An explicit output_dir is required for this input reference")
        group = None
        if attempt is not None:
            group = "mimrec/" + attempt
        elif reference is not None:
            _, upstream, _ = read_execution(reference.manifest_path, reference.execution_id)
            if upstream.get("tool") == "mimrec" and inherited is not None and experiment.root == inherited.root:
                group = upstream.get("data_group")
        existing_group = group is not None and group in experiment._writable()["groups"]
        defaults = experiment.group_defaults(group) if existing_group else None
        parent_analysis = _revan_analysis(reference)
        if self.revan_analysis_id is not None and parent_analysis != self.revan_analysis_id:
            raise ValueError(f"Revan analysis mismatch: expected {self.revan_analysis_id!r}, "
                             f"received {parent_analysis!r}. Use an explicit matching result; "
                             "external TRA inputs have no Revan analysis provenance.")
        if existing_group:
            entry = experiment._writable()["groups"][group]
            same_group_result = False
            if reference is not None and Path(reference.manifest_path) == experiment.index_path:
                same_group_result = read_execution(reference.manifest_path, reference.execution_id)[1].get("data_group") == group
            if "input_file" in entry and str(path) != entry["input_file"]["path"] and not same_group_result:
                raise ValueError("A different TRA input requires a new Mimrec data group")
        config_base = None
        original_path = None
        config_content = None
        if config_file is None:
            if defaults is None:
                raise ValueError("config_file is required when creating a Mimrec data group")
            saved = defaults["configuration"]
            if saved.get("content") is not None:
                config_content = decode_content(saved)
                config = Path(saved["original_path"])
            else:
                config = experiment.root / group / saved["executed_snapshot"]
            config_base = Path(saved["relative_path_base"])
            original_path = saved["original_path"]
            if geometry is None:
                geometry = defaults["geometry"]
            inherited_overrides = {p["parameter"].replace(".", "_"): p["value"]
                                   for p in defaults["configuration_overrides"]}
            inherited_overrides.update(configuration)
            configuration = inherited_overrides
        else:
            config = Path(config_file).expanduser().resolve()
        if defaults is not None:
            changes = [{"parameter": k.replace("_", "."),
                        "value": ("true" if v else "false") if isinstance(v, bool) else str(v)}
                       for k, v in configuration.items()]
            different = ((hashlib.sha256(config_content).hexdigest() if config_content is not None else sha256(config)) != defaults["configuration"]["executed_sha256"]
                         or (None if geometry is None else str(geometry)) != defaults["geometry"]
                         or changes != defaults["configuration_overrides"]
                         or str(config_base or config.parent) != defaults["configuration"]["relative_path_base"])
            if different:
                warnings.warn("Mimrec settings differ from this data group's defaults; "
                              "the change is recorded without replacing the default configuration. "
                              "MEGAlib controls whether event selections change.", UserWarning, stacklevel=3)
        # External step inputs never replace an existing Cosima/sim/tra origin.
        # For a new experiment this records a real TRA entry, without fake runs.
        if reference is None:
            experiment.attach_tra(path)

        def execute(target):
            return Executor(self.runtime).execute(
                "mimrec", target,
                lambda attempt: _prepare(attempt, path, geometry, config, self.executable,
                                         operation, output_name, reference, configuration,
                                         isolate_settings, config_base, original_path, config_content, parent_analysis), timeout=timeout, log_mode=log_mode,
            )
        return experiment.execute("mimrec", task, execute, group=group, native_operation=operation)

    def extract_events(self, working_space=None, *, tra_path=None, output_dir=None,
               config_file=None, geometry=None, task="extract_events", output_name="events.tra.gz",
               timeout=None, isolate_settings=False, attempt=None,
               log_mode="full", **configuration):
        """Extract selected events into a native TRA file (``-x``).

        Parameters
        ----------
        working_space : SimulationWorkspace or ExecutionResult or ExecutionInput or str or pathlib.Path or None, optional
            Existing experiment directory, selected Revan result, or selected
            Mimrec extraction result/reference. Default none. Supply exactly
            one of this and ``tra_path``. A directory selects its unique successful
            Revan attempt; multiple branches require an explicit selection.
            A TRA-origin experiment without Revan tasks uses its original TRA.
            To use a Mimrec extraction, pass its result explicitly.
        tra_path : str or pathlib.Path or None, optional
            External ``.tra`` or ``.tra.gz`` file, default none. Requires
            ``output_dir``. Data stays in place and is not read, copied or hashed.
            Native include/continuation handling belongs to MEGAlib.
        output_dir : str or pathlib.Path or None, optional
            Destination experiment root, default none continues in the selected
            result's workspace. Required for external TRA or references without
            workspace context. Records go below ``mimrec/attempt-NNN``.
            External step inputs do not replace an existing experiment origin.
        config_file : str or pathlib.Path or None, optional
            None (default) reuses the selected Mimrec group configuration, cwd,
            geometry and overrides. A new group requires a readable nonempty native configuration. Original bytes are
            snapshotted unchanged and passed via ``-c``. The child runs in this
            file's parent directory so relative configuration resources retain
            their base. Python does not parse or repair settings.
        geometry : str or pathlib.Path or None, optional
            With an explicit config_file, None (default) omits ``-g`` and uses
            the configuration's geometry. With an inherited configuration, None
            reuses the group's geometry override. Otherwise forwarded literally via ``-g``; no expansion, resource
            checks or snapshots are performed by Python.
        task : str, optional
            Task label, default ``"extract_events"``. Labels name output directories inside a data group. Repeated
            operations get independent execution IDs and numbered output filenames.
        output_name : str, optional
            Filename inside this group's task output directory, default
            ``"events.tra.gz"``. Extraction requires ``.tra`` or ``.tra.gz``;
            compression follows the suffix. Plot formats are chosen by native
            MEGAlib/ROOT (e.g. ``.root`` or ``.png``); include an explicit suffix.
        timeout : float or None, optional
            Positive process timeout in seconds including setup. None (default)
            waits indefinitely; preparation and final record writing are excluded.
        isolate_settings : bool, optional
            False (default) retains native HOME/settings behavior. True gives
            the tool a private HOME after setup, without editing configuration
            paths or the parent environment.
        attempt : str or None, optional
            Existing Mimrec data group basename, e.g. ``"attempt-001"``.
            Legacy explicit group selector. Omit when the object binds analysis_id;
            a conflicting value is rejected. Without a bound ID, None inherits
            the group from a selected Mimrec TRA result, or creates a new group
            for Revan/external input. Reopening a group
            uses its unique successful extraction, then its recorded entry input,
            otherwise the explicitly bound revan_analysis_id.
        log_mode : str, optional
            "full" (default) streams complete stdout/stderr without a byte cap.
            Summary selection is currently available only for Cosima, whose
            native boundary marker is defined. Empty logs are removed. This
            Python option is never forwarded as a native -C setting.

        **configuration
            Native overrides: keyword underscores become dots, e.g.
            ``EventSelections_TimeMode=1`` becomes a separate
            ``-C EventSelections.TimeMode=1`` pair. Values preserve underscores,
            spaces and equals signs; booleans use lowercase true/false, others
            use str. Native MEGAlib validates parameter paths and values.

        Returns
        -------
        ExecutionResult
            ``outputs["tra"]`` contains native output paths; manifests record
            operation, command, configuration hashes, runtime, input and explicit
            upstream lineage. ROOT outputs remain native files, not Python arrays.

        Raises
        ------
        ValueError
            Conflicting/missing entry arguments, invalid labels or output name,
            unsupported input, missing destination or ambiguous upstream selection.
        FileNotFoundError
            Input/reference cannot be resolved before attempt allocation.
        FileExistsError
            Experiment lock contention or an occupied attempt directory.
        ExecutionError
            Configuration snapshot, launch, native execution, timeout or nonempty
            output checks fail after allocation; logs and manifest are retained.
        KeyboardInterrupt
            Interrupted execution; process-group cleanup and records are retained.

        Warns
        -----
        UserWarning
            Explicit configuration bytes, resource cwd, geometry or overrides
            differ from group defaults. Execution proceeds and records the
            variant without replacing defaults; Python does not interpret settings.

        Notes
        -----
        Each operation applies the native event selections in its own supplied
        configuration. No automatic time alignment, exposure scaling, configuration
        interpretation or scientific validation is performed. Zero exit status
        and a nonempty file only establish execution success. Inspect native logs;
        failed imaging/ARM fits can exit zero while producing no output.

        Examples
        --------
        >>> runner = Mimrec()  # MEGAlib initialized in the current environment
        >>> result = runner.extract_events(  # doctest: +SKIP
        ...     tra_path="selected.tra.gz", output_dir="experiment",
        ...     config_file="analysis.mimrec.cfg", task="extract_events")
        """
        return self._run("extract_events", working_space, tra_path, output_dir, config_file,
                         geometry, task, output_name, timeout, isolate_settings, configuration, attempt, log_mode)

    def image(self, working_space=None, *, tra_path=None, output_dir=None,
               config_file=None, geometry=None, task="image", output_name="image.root",
               timeout=None, isolate_settings=False, attempt=None,
               log_mode="full", **configuration):
        """Reconstruct and save a native image (``-i``).

        Parameters
        ----------
        working_space : SimulationWorkspace or ExecutionResult or ExecutionInput or str or pathlib.Path or None, optional
            Existing experiment directory, selected Revan result, or selected
            Mimrec extraction result/reference. Default none. Supply exactly
            one of this and ``tra_path``. A directory selects its unique successful
            Revan attempt; multiple branches require an explicit selection.
            A TRA-origin experiment without Revan tasks uses its original TRA.
            To use a Mimrec extraction, pass its result explicitly.
        tra_path : str or pathlib.Path or None, optional
            External ``.tra`` or ``.tra.gz`` file, default none. Requires
            ``output_dir``. Data stays in place and is not read, copied or hashed.
            Native include/continuation handling belongs to MEGAlib.
        output_dir : str or pathlib.Path or None, optional
            Destination experiment root, default none continues in the selected
            result's workspace. Required for external TRA or references without
            workspace context. Records go below ``mimrec/attempt-NNN``.
            External step inputs do not replace an existing experiment origin.
        config_file : str or pathlib.Path or None, optional
            None (default) reuses the selected Mimrec group configuration, cwd,
            geometry and overrides. A new group requires a readable nonempty native configuration. Original bytes are
            snapshotted unchanged and passed via ``-c``. The child runs in this
            file's parent directory so relative configuration resources retain
            their base. Python does not parse or repair settings.
        geometry : str or pathlib.Path or None, optional
            With an explicit config_file, None (default) omits ``-g`` and uses
            the configuration's geometry. With an inherited configuration, None
            reuses the group's geometry override. Otherwise forwarded literally via ``-g``; no expansion, resource
            checks or snapshots are performed by Python.
        task : str, optional
            Task label, default ``"image"``. Labels name output directories inside a data group. Repeated
            operations get independent execution IDs and numbered output filenames.
        output_name : str, optional
            Filename inside this group's task output directory, default
            ``"image.root"``. Extraction requires ``.tra`` or ``.tra.gz``;
            compression follows the suffix. Plot formats are chosen by native
            MEGAlib/ROOT (e.g. ``.root`` or ``.png``); include an explicit suffix.
        timeout : float or None, optional
            Positive process timeout in seconds including setup. None (default)
            waits indefinitely; preparation and final record writing are excluded.
        isolate_settings : bool, optional
            False (default) retains native HOME/settings behavior. True gives
            the tool a private HOME after setup, without editing configuration
            paths or the parent environment.
        attempt : str or None, optional
            Existing Mimrec data group basename, e.g. ``"attempt-001"``.
            Legacy explicit group selector. Omit when the object binds analysis_id;
            a conflicting value is rejected. Without a bound ID, None inherits
            the group from a selected Mimrec TRA result, or creates a new group
            for Revan/external input. Reopening a group
            uses its unique successful extraction, then its recorded entry input,
            otherwise the explicitly bound revan_analysis_id.
        log_mode : str, optional
            "full" (default) streams complete stdout/stderr without a byte cap.
            Summary selection is currently available only for Cosima, whose
            native boundary marker is defined. Empty logs are removed. This
            Python option is never forwarded as a native -C setting.

        **configuration
            Native overrides: keyword underscores become dots, e.g.
            ``EventSelections_TimeMode=1`` becomes a separate
            ``-C EventSelections.TimeMode=1`` pair. Values preserve underscores,
            spaces and equals signs; booleans use lowercase true/false, others
            use str. Native MEGAlib validates parameter paths and values.

        Returns
        -------
        ExecutionResult
            ``outputs["image"]`` contains native output paths; manifests record
            operation, command, configuration hashes, runtime, input and explicit
            upstream lineage. ROOT outputs remain native files, not Python arrays.

        Raises
        ------
        ValueError
            Conflicting/missing entry arguments, invalid labels or output name,
            unsupported input, missing destination or ambiguous upstream selection.
        FileNotFoundError
            Input/reference cannot be resolved before attempt allocation.
        FileExistsError
            Experiment lock contention or an occupied attempt directory.
        ExecutionError
            Configuration snapshot, launch, native execution, timeout or nonempty
            output checks fail after allocation; logs and manifest are retained.
        KeyboardInterrupt
            Interrupted execution; process-group cleanup and records are retained.

        Warns
        -----
        UserWarning
            Explicit configuration bytes, resource cwd, geometry or overrides
            differ from group defaults. Execution proceeds and records the
            variant without replacing defaults; Python does not interpret settings.

        Notes
        -----
        Each operation applies the native event selections in its own supplied
        configuration. No automatic time alignment, exposure scaling, configuration
        interpretation or scientific validation is performed. Zero exit status
        and a nonempty file only establish execution success. Inspect native logs;
        failed imaging/ARM fits can exit zero while producing no output.

        Examples
        --------
        >>> runner = Mimrec()  # MEGAlib initialized in the current environment
        >>> result = runner.image(  # doctest: +SKIP
        ...     tra_path="selected.tra.gz", output_dir="experiment",
        ...     config_file="analysis.mimrec.cfg", task="image")
        """
        return self._run("image", working_space, tra_path, output_dir, config_file,
                         geometry, task, output_name, timeout, isolate_settings, configuration, attempt, log_mode)

    def spectrum(self, working_space=None, *, tra_path=None, output_dir=None,
               config_file=None, geometry=None, task="spectrum", output_name="spectrum.root",
               timeout=None, isolate_settings=False, attempt=None,
               log_mode="full", **configuration):
        """Create a native selected-event energy spectrum (``-s``).

        Parameters
        ----------
        working_space : SimulationWorkspace or ExecutionResult or ExecutionInput or str or pathlib.Path or None, optional
            Existing experiment directory, selected Revan result, or selected
            Mimrec extraction result/reference. Default none. Supply exactly
            one of this and ``tra_path``. A directory selects its unique successful
            Revan attempt; multiple branches require an explicit selection.
            A TRA-origin experiment without Revan tasks uses its original TRA.
            To use a Mimrec extraction, pass its result explicitly.
        tra_path : str or pathlib.Path or None, optional
            External ``.tra`` or ``.tra.gz`` file, default none. Requires
            ``output_dir``. Data stays in place and is not read, copied or hashed.
            Native include/continuation handling belongs to MEGAlib.
        output_dir : str or pathlib.Path or None, optional
            Destination experiment root, default none continues in the selected
            result's workspace. Required for external TRA or references without
            workspace context. Records go below ``mimrec/attempt-NNN``.
            External step inputs do not replace an existing experiment origin.
        config_file : str or pathlib.Path or None, optional
            None (default) reuses the selected Mimrec group configuration, cwd,
            geometry and overrides. A new group requires a readable nonempty native configuration. Original bytes are
            snapshotted unchanged and passed via ``-c``. The child runs in this
            file's parent directory so relative configuration resources retain
            their base. Python does not parse or repair settings.
        geometry : str or pathlib.Path or None, optional
            With an explicit config_file, None (default) omits ``-g`` and uses
            the configuration's geometry. With an inherited configuration, None
            reuses the group's geometry override. Otherwise forwarded literally via ``-g``; no expansion, resource
            checks or snapshots are performed by Python.
        task : str, optional
            Task label, default ``"spectrum"``. Labels name output directories inside a data group. Repeated
            operations get independent execution IDs and numbered output filenames.
        output_name : str, optional
            Filename inside this group's task output directory, default
            ``"spectrum.root"``. Extraction requires ``.tra`` or ``.tra.gz``;
            compression follows the suffix. Plot formats are chosen by native
            MEGAlib/ROOT (e.g. ``.root`` or ``.png``); include an explicit suffix.
        timeout : float or None, optional
            Positive process timeout in seconds including setup. None (default)
            waits indefinitely; preparation and final record writing are excluded.
        isolate_settings : bool, optional
            False (default) retains native HOME/settings behavior. True gives
            the tool a private HOME after setup, without editing configuration
            paths or the parent environment.
        attempt : str or None, optional
            Existing Mimrec data group basename, e.g. ``"attempt-001"``.
            Legacy explicit group selector. Omit when the object binds analysis_id;
            a conflicting value is rejected. Without a bound ID, None inherits
            the group from a selected Mimrec TRA result, or creates a new group
            for Revan/external input. Reopening a group
            uses its unique successful extraction, then its recorded entry input,
            otherwise the explicitly bound revan_analysis_id.
        log_mode : str, optional
            "full" (default) streams complete stdout/stderr without a byte cap.
            Summary selection is currently available only for Cosima, whose
            native boundary marker is defined. Empty logs are removed. This
            Python option is never forwarded as a native -C setting.

        **configuration
            Native overrides: keyword underscores become dots, e.g.
            ``EventSelections_TimeMode=1`` becomes a separate
            ``-C EventSelections.TimeMode=1`` pair. Values preserve underscores,
            spaces and equals signs; booleans use lowercase true/false, others
            use str. Native MEGAlib validates parameter paths and values.

        Returns
        -------
        ExecutionResult
            ``outputs["spectrum"]`` contains native output paths; manifests record
            operation, command, configuration hashes, runtime, input and explicit
            upstream lineage. ROOT outputs remain native files, not Python arrays.

        Raises
        ------
        ValueError
            Conflicting/missing entry arguments, invalid labels or output name,
            unsupported input, missing destination or ambiguous upstream selection.
        FileNotFoundError
            Input/reference cannot be resolved before attempt allocation.
        FileExistsError
            Experiment lock contention or an occupied attempt directory.
        ExecutionError
            Configuration snapshot, launch, native execution, timeout or nonempty
            output checks fail after allocation; logs and manifest are retained.
        KeyboardInterrupt
            Interrupted execution; process-group cleanup and records are retained.

        Warns
        -----
        UserWarning
            Explicit configuration bytes, resource cwd, geometry or overrides
            differ from group defaults. Execution proceeds and records the
            variant without replacing defaults; Python does not interpret settings.

        Notes
        -----
        Each operation applies the native event selections in its own supplied
        configuration. No automatic time alignment, exposure scaling, configuration
        interpretation or scientific validation is performed. Zero exit status
        and a nonempty file only establish execution success. Inspect native logs;
        failed imaging/ARM fits can exit zero while producing no output.

        Examples
        --------
        >>> runner = Mimrec()  # MEGAlib initialized in the current environment
        >>> result = runner.spectrum(  # doctest: +SKIP
        ...     tra_path="selected.tra.gz", output_dir="experiment",
        ...     config_file="analysis.mimrec.cfg", task="spectrum")
        """
        return self._run("spectrum", working_space, tra_path, output_dir, config_file,
                         geometry, task, output_name, timeout, isolate_settings, configuration, attempt, log_mode)

    def arm(self, working_space=None, *, tra_path=None, output_dir=None,
               config_file=None, geometry=None, task="arm", output_name="arm.root",
               timeout=None, isolate_settings=False, attempt=None,
               log_mode="full", **configuration):
        """Create the native gamma-ray ARM fit and plot (``-a``).

        Parameters
        ----------
        working_space : SimulationWorkspace or ExecutionResult or ExecutionInput or str or pathlib.Path or None, optional
            Existing experiment directory, selected Revan result, or selected
            Mimrec extraction result/reference. Default none. Supply exactly
            one of this and ``tra_path``. A directory selects its unique successful
            Revan attempt; multiple branches require an explicit selection.
            A TRA-origin experiment without Revan tasks uses its original TRA.
            To use a Mimrec extraction, pass its result explicitly.
        tra_path : str or pathlib.Path or None, optional
            External ``.tra`` or ``.tra.gz`` file, default none. Requires
            ``output_dir``. Data stays in place and is not read, copied or hashed.
            Native include/continuation handling belongs to MEGAlib.
        output_dir : str or pathlib.Path or None, optional
            Destination experiment root, default none continues in the selected
            result's workspace. Required for external TRA or references without
            workspace context. Records go below ``mimrec/attempt-NNN``.
            External step inputs do not replace an existing experiment origin.
        config_file : str or pathlib.Path or None, optional
            None (default) reuses the selected Mimrec group configuration, cwd,
            geometry and overrides. A new group requires a readable nonempty native configuration. Original bytes are
            snapshotted unchanged and passed via ``-c``. The child runs in this
            file's parent directory so relative configuration resources retain
            their base. Python does not parse or repair settings.
        geometry : str or pathlib.Path or None, optional
            With an explicit config_file, None (default) omits ``-g`` and uses
            the configuration's geometry. With an inherited configuration, None
            reuses the group's geometry override. Otherwise forwarded literally via ``-g``; no expansion, resource
            checks or snapshots are performed by Python.
        task : str, optional
            Task label, default ``"arm"``. Labels name output directories inside a data group. Repeated
            operations get independent execution IDs and numbered output filenames.
        output_name : str, optional
            Filename inside this group's task output directory, default
            ``"arm.root"``. Extraction requires ``.tra`` or ``.tra.gz``;
            compression follows the suffix. Plot formats are chosen by native
            MEGAlib/ROOT (e.g. ``.root`` or ``.png``); include an explicit suffix.
        timeout : float or None, optional
            Positive process timeout in seconds including setup. None (default)
            waits indefinitely; preparation and final record writing are excluded.
        isolate_settings : bool, optional
            False (default) retains native HOME/settings behavior. True gives
            the tool a private HOME after setup, without editing configuration
            paths or the parent environment.
        attempt : str or None, optional
            Existing Mimrec data group basename, e.g. ``"attempt-001"``.
            Legacy explicit group selector. Omit when the object binds analysis_id;
            a conflicting value is rejected. Without a bound ID, None inherits
            the group from a selected Mimrec TRA result, or creates a new group
            for Revan/external input. Reopening a group
            uses its unique successful extraction, then its recorded entry input,
            otherwise the explicitly bound revan_analysis_id.
        log_mode : str, optional
            "full" (default) streams complete stdout/stderr without a byte cap.
            Summary selection is currently available only for Cosima, whose
            native boundary marker is defined. Empty logs are removed. This
            Python option is never forwarded as a native -C setting.

        **configuration
            Native overrides: keyword underscores become dots, e.g.
            ``EventSelections_TimeMode=1`` becomes a separate
            ``-C EventSelections.TimeMode=1`` pair. Values preserve underscores,
            spaces and equals signs; booleans use lowercase true/false, others
            use str. Native MEGAlib validates parameter paths and values.

        Returns
        -------
        ExecutionResult
            ``outputs["arm"]`` contains native output paths; manifests record
            operation, command, configuration hashes, runtime, input and explicit
            upstream lineage. ROOT outputs remain native files, not Python arrays.

        Raises
        ------
        ValueError
            Conflicting/missing entry arguments, invalid labels or output name,
            unsupported input, missing destination or ambiguous upstream selection.
        FileNotFoundError
            Input/reference cannot be resolved before attempt allocation.
        FileExistsError
            Experiment lock contention or an occupied attempt directory.
        ExecutionError
            Configuration snapshot, launch, native execution, timeout or nonempty
            output checks fail after allocation; logs and manifest are retained.
        KeyboardInterrupt
            Interrupted execution; process-group cleanup and records are retained.

        Warns
        -----
        UserWarning
            Explicit configuration bytes, resource cwd, geometry or overrides
            differ from group defaults. Execution proceeds and records the
            variant without replacing defaults; Python does not interpret settings.

        Notes
        -----
        Each operation applies the native event selections in its own supplied
        configuration. No automatic time alignment, exposure scaling, configuration
        interpretation or scientific validation is performed. Zero exit status
        and a nonempty file only establish execution success. Inspect native logs;
        failed imaging/ARM fits can exit zero while producing no output.

        Examples
        --------
        >>> runner = Mimrec()  # MEGAlib initialized in the current environment
        >>> result = runner.arm(  # doctest: +SKIP
        ...     tra_path="selected.tra.gz", output_dir="experiment",
        ...     config_file="analysis.mimrec.cfg", task="arm")
        """
        return self._run("arm", working_space, tra_path, output_dir, config_file,
                         geometry, task, output_name, timeout, isolate_settings, configuration, attempt, log_mode)
