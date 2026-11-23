"""Thin native Mimrec commands with immutable execution records."""

from dataclasses import replace
from glob import escape
from pathlib import Path
import warnings
import hashlib
import re

from ..execution import ExecutionInput, ExecutionPlan, ExecutionResult, MEGAlibRuntime, SimulationWorkspace
from ..execution.executor import Executor
from ..execution.experiment import _bound_workspace, _workspace_arguments
from ..execution.provenance import configuration_snapshot, decode_content, encode_content, file_record, read_execution, resolve_upstream, sha256


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
             overrides, isolate_settings, config_base=None, original_path=None, config_content=None, revan_analysis_id=None,
             components=None):
    executed, config_record = configuration_snapshot(attempt, config, "mimrec", content=config_content, cwd=config_base, original_path=original_path)
    home = attempt.log_path("native-home")
    if isolate_settings:
        home.mkdir(exist_ok=True)
    product = attempt.products_dir / output_name
    if attempt.owner is not None:
        product = attempt.owner._claim_product(attempt, product)
    native_input = event_file
    component_metadata = {}
    references = () if reference is None else (reference,)
    if components is not None:
        content = ("# Prepared TRA components; native MEGAlib reads the events\n"
                   + "".join(f"IN {path}\n" for path, _ in components) + "END\n").encode("utf-8")
        native_input = attempt.snapshot("components.tra", content)
        references = tuple(ref for _, ref in components if ref is not None)
        component_metadata = {
            "component_inputs": [file_record(path, hash_limit=0) for path, _ in components],
            "include_list": {**encode_content(content),
                             "snapshot": str(native_input.relative_to(attempt.root)) if attempt.archive_inputs else None}}
    command = [executable, "-c", str(executed), "-f", str(native_input), "-o", str(product)]
    if geometry is not None:
        command.extend(("-g", str(geometry)))
    changes = []
    for key, value in overrides.items():
        name = key.replace("_", ".")
        text = ("true" if value else "false") if isinstance(value, bool) else str(value)
        command.extend(("-C", f"{name}={text}"))
        changes.append({"parameter": name, "value": text})
    command.extend(("-n", {"extract_events": "-x", "add_external_components": "-x", "image": "-i", "spectrum": "-s", "arm": "-a"}[operation]))
    return ExecutionPlan(tuple(command), config_base or config.parent, {"tra" if operation in ("extract_events", "add_external_components") else operation: escape(product.name)}, {
        "operation": operation,
        "revan_analysis_id": revan_analysis_id,
        "input_file": file_record(event_file, hash_limit=0),
        "configuration": {**config_record,
                          "settings_home": str(home.relative_to(attempt.root)) if isolate_settings else None},
        "geometry": None if geometry is None else str(geometry),
        "configuration_overrides": changes,
        **component_metadata,
    }, upstream=references, environment={"HOME": str(home)} if isolate_settings else {})


class Mimrec:
    """Run independent native Mimrec operations without importing PyROOT.

    Parameters
    ----------
    runtime : MEGAlibRuntime or None, optional
        Direct or setup-script runtime. None selects direct execution.
    working_space : SimulationWorkspace or str or pathlib.Path or None, optional
        Experiment root, default none. Bind the directory containing the root
        manifest and sibling cosima/, revan/ and mimrec/ directories, never a
        stage, analysis or product directory. Calls can omit working_space;
        explicit results/references must belong to this same root. External
        event-file calls use this root as their destination when output_dir is
        omitted. Construction reads metadata but creates no files or processes.
        Conflicting per-call workspace/output_dir values raise ValueError.
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
    config_file : str or pathlib.Path or None, optional
        Main opaque native configuration, default None. Supplying it enables a
        bound analysis definition and requires working_space and analysis_id
        (the latter may default to revan_analysis_id). Bytes and resource cwd
        are fixed at construction; construction runs no command and writes no
        files. Reopening a bound group may omit this argument to restore its
        recorded bytes even if the original cfg was removed. Different main
        bytes or resource cwd require a new analysis_id.
    geometry : str or pathlib.Path or None, optional
        Baseline literal geometry override. None (default) omits -g for a new
        definition or restores a recorded definition's setting. Never parsed
        or checked as a resource. Changing a bound value requires a new ID.
    input_data : ExecutionResult or ExecutionInput or str or pathlib.Path or None, optional
        Exact primary TRA result/reference or external TRA path. Default None
        resolves the registered primary input or unique specified Revan parent.
        Multiple Revan executions require an explicit result; no latest rule.
        An external path requires working_space and analysis_id. A result can
        supply its workspace when working_space is omitted.
    external_components : iterable or None, optional
        Prepared TRA results/references or file paths, default None. Components
        are bound with the primary input, not interpreted as background/GRB.
        None restores a recorded definition; an empty iterable explicitly means
        no components. Different inputs require a new analysis_id. Call
        extract_events() reads the primary and these components together via
        one native -x command. No separate combination call is required.
    **configuration
        Baseline native overrides. Keys replace underscores with dots for -C;
        values are unchanged except booleans become true/false. Method overrides
        apply only to that command and never replace these baseline defaults.

    Notes
    -----
    Configurations are opaque snapshots. MEGAlib controls event selection,
    configuration semantics, geometry and external resources. Each call runs
    one native operation with an independent execution record in a shared data group.
    A bound analysis_id avoids repeating group selection; actual input data still
    comes from the bound workspace or each call's explicit input. task names an operation output
    folder inside that group. None preserves result-based automatic grouping.
    """

    def __init__(self, runtime=None, *, working_space=None, revan_analysis_id=None, analysis_id=None,
                 config_file=None, geometry=None, external_components=None, input_data=None,
                 executable="mimrec", **configuration):
        for name, value in (("analysis_id", analysis_id), ("revan_analysis_id", revan_analysis_id)):
            if value is not None and (not isinstance(value, str) or
                                      not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value)):
                raise ValueError(f"{name} must contain letters, digits, '_' or '-' and start with a letter/digit")
        self.revan_analysis_id = revan_analysis_id
        self.analysis_id = analysis_id if analysis_id is not None else revan_analysis_id
        self.working_space = _bound_workspace(working_space)
        self.runtime = runtime if runtime is not None else MEGAlibRuntime.direct()
        self.executable = str(executable)
        self._analysis = None
        saved = None
        if self.working_space is not None and self.analysis_id is not None:
            saved = SimulationWorkspace(self.working_space)._read().get("groups", {}).get(
                "mimrec/" + self.analysis_id, {}).get("definition")
        if (saved is not None or config_file is not None or geometry is not None or
                external_components is not None or input_data is not None or configuration):
            from .analysis import BoundAnalysis
            self._analysis = BoundAnalysis(self, config_file, geometry, external_components, input_data, configuration)

    def _run(self, operation, working_space, tra_path, output_dir, config_file,
             geometry, task, output_name, timeout, isolate_settings, configuration, attempt, log_mode):
        if "working_space" in configuration:
            raise TypeError("spectrum() no longer accepts working_space; bind it in Mimrec() and use input_data for a result")
        constructor_options = {"external_components", "analysis_id", "revan_analysis_id", "runtime"}
        misplaced = constructor_options.intersection(configuration)
        if misplaced:
            raise TypeError(f"Bind {', '.join(sorted(misplaced))} in Mimrec(), not in a command")
        if self._analysis is not None:
            return self._analysis.run(operation, working_space, tra_path, output_dir, config_file,
                                      geometry, task, output_name, timeout, isolate_settings,
                                      configuration, attempt, log_mode)
        return self._run_legacy(operation, working_space, tra_path, output_dir, config_file,
                                geometry, task, output_name, timeout, isolate_settings,
                                configuration, attempt, log_mode)

    def add_external_components(self, *, task="components", output_name="combined.tra.gz",
                                timeout=None, isolate_settings=False, log_mode="full", **configuration):
        """Combine the primary and constructor-declared TRA components via native -x.

        Parameters
        ----------
        task : str, optional
            Output directory label within the analysis, default ``"components"``.
            It does not identify data or participate in downstream selection.
        output_name : str, optional
            Native .tra/.tra.gz filename, default ``"combined.tra.gz"``. Existing
            outputs receive a new suffix; previous results are never overwritten.
        timeout : float or None, optional
            Native-command timeout in seconds, default None (no time limit).
        isolate_settings : bool, optional
            False (default) preserves native HOME. True isolates native settings
            for this command only, without modifying the configuration.
        log_mode : str, optional
            Python log capture, currently only ``"full"`` (default).
        **configuration
            Overrides for this combination command only, on top of the bound
            main configuration and baseline overrides. Keys map _ to . for -C.
            They do not inherit time selections from component preparation.

        Returns
        -------
        ExecutionResult
            Native mixed TRA in outputs['tra'], with an independent execution ID
            and every supplied result/reference recorded as a real upstream.
            Raw external paths are recorded separately with size/mtime only.

        Raises
        ------
        ValueError
            No bound definition/components, changed input, invalid output/label,
            or inconsistent analysis definition. A new dataset needs a new ID.
        ExecutionError
            Native preparation/execution fails; the failed record is retained.

        Notes
        -----
        Optional explicit materialization; ordinary analyses call extract_events()
        directly, which already includes the declared components in one -x.
        This method executes mimrec -x on an IN/END list using the main
        configuration plus this call's overrides. Native selections still apply;
        this is not unfiltered byte concatenation. No event parser, time shift,
        exposure/flux scaling or background classification is added. The list
        content is recorded in the manifest and its native file is temporary
        unless archive_inputs=True. The workspace's primary origin is preserved.
        Later operations select a unique successful extraction first, otherwise
        a unique successful combination. Multiple candidates require input_data.

        Examples
        --------
        >>> analysis = Mimrec(working_space="experiment", analysis_id="mixed",
        ...                   input_data="signal.tra.gz", config_file="analysis.cfg",
        ...                   external_components=["prepared-background.tra.gz"])
        >>> selected = analysis.extract_events()  # doctest: +SKIP
        >>> spectrum = analysis.spectrum(input_data=selected)  # doctest: +SKIP
        """
        if self._analysis is None:
            raise ValueError("Declare config_file and external_components in Mimrec() first")
        return self._run("add_external_components", None, None, None, None, None,
                         task, output_name, timeout, isolate_settings, configuration, None, log_mode)

    def _run_legacy(self, operation, working_space, tra_path, output_dir, config_file,
             geometry, task, output_name, timeout, isolate_settings, configuration, attempt, log_mode):
        if self.analysis_id is not None:
            if attempt is not None and attempt != self.analysis_id:
                raise ValueError("attempt conflicts with the Mimrec object's analysis_id")
            attempt = self.analysis_id
        working_space, output_dir = _workspace_arguments(
            self.working_space, working_space, tra_path, output_dir)
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
        if existing_group and experiment._writable()["groups"][group].get("definition"):
            entry = experiment._writable()["groups"][group]
            bound = Mimrec(self.runtime, working_space=experiment, analysis_id=Path(group).name,
                           revan_analysis_id=self.revan_analysis_id or entry.get("revan_analysis_id"),
                           executable=self.executable)
            return bound._analysis.run(operation, working_space, tra_path, None, config_file,
                                       geometry, task, output_name, timeout, isolate_settings,
                                       configuration, attempt, log_mode)
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

    def extract_events(self, working_space=None, *, input_data=None, tra_path=None, output_dir=None,
               config_file=None, geometry=None, task="extract_events", output_name="events.tra.gz",
               timeout=None, isolate_settings=False, attempt=None,
               log_mode="full", **configuration):
        """Execute native Mimrec extract_events (-x) with explicit data provenance.

        Parameters
        ----------
        working_space : SimulationWorkspace or ExecutionResult or ExecutionInput or str or pathlib.Path or None, optional
            Legacy per-command workspace/result entry, default None. Prefer
            binding the root in Mimrec() and selecting results with input_data.
            Must not conflict with input_data or the constructor-bound root.
        input_data : ExecutionResult or ExecutionInput or None, optional
            Exact TRA result/reference for this command, default None. For a
            bound analysis it must belong to that analysis's data chain.
            With declared external_components, None reads the primary and all
            declared components together via one native IN/END list and -x.
            Every such call starts from the declared dataset, not a prior
            extraction. An explicit previous result re-filters only that TRA;
            components are not added again. Without declared components,
            None queries the root manifest (not the filesystem): select this
            group's unique successful extract_events record first, otherwise
            its unique successful add_external_components record, otherwise the
            registered primary input. Multiple successful candidates require an
            explicit result, never latest/mtime or a fixed task folder name.
        tra_path : str or pathlib.Path or None, optional
            Legacy external TRA entry, default None. Requires output_dir or a
            constructor-bound workspace. For the new bound-definition API,
            declare the primary path as input_data in Mimrec(), not here.
        output_dir : str or pathlib.Path or None, optional
            Legacy destination experiment root, default None. Bound definitions
            fix their destination in Mimrec() and reject per-command changes.
        config_file : str or pathlib.Path or None, optional
            Default None uses the constructor-bound main configuration or saved
            group default. In a bound definition an explicit file must have the
            same bytes and resource cwd; a different main cfg requires a new
            analysis_id. Legacy calls require a cfg when creating a new group.
            Native bytes are opaque and are never parsed or edited.
        geometry : str or pathlib.Path or None, optional
            Default None reuses bound geometry, or saved legacy defaults when
            cfg is omitted. A different geometry in a bound definition requires
            a new analysis_id. The literal -g value is never read or rewritten.
        task : str, optional
            Arbitrary output directory label, default "extract_events". Letters,
            digits, underscores and hyphens, starting with a letter/digit.
            inputs/logs are reserved. This is NOT the operation identity and
            does not identify which extracted TRA a downstream command reads.
        output_name : str, optional
            Native output filename, default "events.tra.gz". Existing products
            receive numbered suffixes; no historical product is overwritten.
        timeout : float or None, optional
            Native command timeout in seconds, default None (unlimited).
        isolate_settings : bool, optional
            False (default) preserves native HOME. True gives this native command
            private settings after setup, without modifying cfg contents.
        attempt : str or None, optional
            Legacy explicit group selector, default None. A different value
            conflicts with a constructor-bound analysis_id.
        log_mode : str, optional
            Python log capture, currently "full" (default), not a native flag.
        **configuration
            Native -C overrides: key underscores become dots; booleans become
            true/false, other values use str without further rewriting. With a
            constructor-bound definition these override the baseline for THIS
            COMMAND ONLY. They are recorded in execution_overrides and never
            become later calls' defaults. Legacy groups retain their recorded
            default/variant behavior until explicitly opened as a bound definition.

        Returns
        -------
        ExecutionResult
            Native outputs['tra'], exact upstream references, execution UUID,
            root manifest path and optional nonempty stdout/stderr paths.
            Nonempty products and exit zero establish execution success, not
            scientific correctness. ROOT data extraction is a separate call.

        Raises
        ------
        ValueError
            Input/definition conflict, multiple input candidates, absent prepared
            components, invalid output/settings, or missing required configuration.
        FileNotFoundError
            A bound configuration or selected data file cannot be read.
        ExecutionError
            Native preparation, execution, timeout or output validation fails.
            The independent failed record and nonempty logs remain available.

        Notes
        -----
        Each native command applies its own selections from the main cfg plus
        explicit overrides; reading selected TRA does not inherit the command
        parameters that produced it. task is a label only. Reopening a group
        uses manifest operation/status/UUID/path records, not directory names.
        Setup executes in a child process; the parent environment is unchanged.
        Declared components require no preliminary add_external_components().
        Their include list and all real parent references are recorded in this
        same extract_events execution; no intermediate combined TRA is created.
        No event parsing, time shift or physical scaling is performed.

        Examples
        --------
        >>> result = analysis.extract_events(task="my-extract_events")  # doctest: +SKIP
        >>> print(result.outputs["tra"])  # doctest: +SKIP
        """
        if input_data is not None:
            if working_space is not None:
                raise ValueError("Supply input_data or legacy working_space, not both")
            working_space = input_data
        return self._run("extract_events", working_space, tra_path, output_dir, config_file,
                         geometry, task, output_name, timeout, isolate_settings, configuration, attempt, log_mode)

    def image(self, working_space=None, *, input_data=None, tra_path=None, output_dir=None,
               config_file=None, geometry=None, task="image", output_name="image.root",
               timeout=None, isolate_settings=False, attempt=None,
               log_mode="full", **configuration):
        """Execute native Mimrec image (-i) with explicit data provenance.

        Parameters
        ----------
        working_space : SimulationWorkspace or ExecutionResult or ExecutionInput or str or pathlib.Path or None, optional
            Legacy per-command workspace/result entry, default None. Prefer
            binding the root in Mimrec() and selecting results with input_data.
            Must not conflict with input_data or the constructor-bound root.
        input_data : ExecutionResult or ExecutionInput or None, optional
            Exact TRA result/reference for this command, default None. For a
            bound analysis it must belong to that analysis's data chain.
            None queries the root manifest (not the filesystem): select this
            group's unique successful extract_events record first, otherwise
            its unique successful add_external_components record, otherwise the
            registered primary input. Multiple successful candidates require an
            explicit result, never latest/mtime or a fixed task folder name.
        tra_path : str or pathlib.Path or None, optional
            Legacy external TRA entry, default None. Requires output_dir or a
            constructor-bound workspace. For the new bound-definition API,
            declare the primary path as input_data in Mimrec(), not here.
        output_dir : str or pathlib.Path or None, optional
            Legacy destination experiment root, default None. Bound definitions
            fix their destination in Mimrec() and reject per-command changes.
        config_file : str or pathlib.Path or None, optional
            Default None uses the constructor-bound main configuration or saved
            group default. In a bound definition an explicit file must have the
            same bytes and resource cwd; a different main cfg requires a new
            analysis_id. Legacy calls require a cfg when creating a new group.
            Native bytes are opaque and are never parsed or edited.
        geometry : str or pathlib.Path or None, optional
            Default None reuses bound geometry, or saved legacy defaults when
            cfg is omitted. A different geometry in a bound definition requires
            a new analysis_id. The literal -g value is never read or rewritten.
        task : str, optional
            Arbitrary output directory label, default "image". Letters,
            digits, underscores and hyphens, starting with a letter/digit.
            inputs/logs are reserved. This is NOT the operation identity and
            does not identify which extracted TRA a downstream command reads.
        output_name : str, optional
            Native output filename, default "image.root". Existing products
            receive numbered suffixes; no historical product is overwritten.
        timeout : float or None, optional
            Native command timeout in seconds, default None (unlimited).
        isolate_settings : bool, optional
            False (default) preserves native HOME. True gives this native command
            private settings after setup, without modifying cfg contents.
        attempt : str or None, optional
            Legacy explicit group selector, default None. A different value
            conflicts with a constructor-bound analysis_id.
        log_mode : str, optional
            Python log capture, currently "full" (default), not a native flag.
        **configuration
            Native -C overrides: key underscores become dots; booleans become
            true/false, other values use str without further rewriting. With a
            constructor-bound definition these override the baseline for THIS
            COMMAND ONLY. They are recorded in execution_overrides and never
            become later calls' defaults. Legacy groups retain their recorded
            default/variant behavior until explicitly opened as a bound definition.

        Returns
        -------
        ExecutionResult
            Native outputs['image'], exact upstream references, execution UUID,
            root manifest path and optional nonempty stdout/stderr paths.
            Nonempty products and exit zero establish execution success, not
            scientific correctness. ROOT data extraction is a separate call.

        Raises
        ------
        ValueError
            Input/definition conflict, multiple input candidates, absent prepared
            components, invalid output/settings, or missing required configuration.
        FileNotFoundError
            A bound configuration or selected data file cannot be read.
        ExecutionError
            Native preparation, execution, timeout or output validation fails.
            The independent failed record and nonempty logs remain available.

        Notes
        -----
        Each native command applies its own selections from the main cfg plus
        explicit overrides; reading selected TRA does not inherit the command
        parameters that produced it. task is a label only. Reopening a group
        uses manifest operation/status/UUID/path records, not directory names.
        Setup executes in a child process; the parent environment is unchanged.
        No event parsing, time shift or physical scaling is performed.

        Examples
        --------
        >>> result = analysis.image(task="my-image")  # doctest: +SKIP
        >>> print(result.outputs["image"])  # doctest: +SKIP
        """
        if input_data is not None:
            if working_space is not None:
                raise ValueError("Supply input_data or legacy working_space, not both")
            working_space = input_data
        return self._run("image", working_space, tra_path, output_dir, config_file,
                         geometry, task, output_name, timeout, isolate_settings, configuration, attempt, log_mode)

    def spectrum(self, *, input_data=None, tra_path=None, output_dir=None,
               config_file=None, geometry=None, task="spectrum", output_name="spectrum.root",
               timeout=None, isolate_settings=False, attempt=None,
               log_mode="full", **configuration):
        """Execute native Mimrec spectrum (-s) with explicit data provenance.

        Parameters
        ----------
        input_data : ExecutionResult or ExecutionInput or None, optional
            Exact TRA result/reference for this command, default None. For a
            bound analysis it must belong to that analysis's data chain.
            None queries the root manifest (not the filesystem): select this
            group's unique successful extract_events record first, otherwise
            its unique successful add_external_components record, otherwise the
            registered primary input. Multiple successful candidates require an
            explicit result, never latest/mtime or a fixed task folder name.
        tra_path : str or pathlib.Path or None, optional
            Legacy external TRA entry, default None. Requires output_dir or a
            constructor-bound workspace. For the new bound-definition API,
            declare the primary path as input_data in Mimrec(), not here.
        output_dir : str or pathlib.Path or None, optional
            Legacy destination experiment root, default None. Bound definitions
            fix their destination in Mimrec() and reject per-command changes.
        config_file : str or pathlib.Path or None, optional
            Default None uses the constructor-bound main configuration or saved
            group default. In a bound definition an explicit file must have the
            same bytes and resource cwd; a different main cfg requires a new
            analysis_id. Legacy calls require a cfg when creating a new group.
            Native bytes are opaque and are never parsed or edited.
        geometry : str or pathlib.Path or None, optional
            Default None reuses bound geometry, or saved legacy defaults when
            cfg is omitted. A different geometry in a bound definition requires
            a new analysis_id. The literal -g value is never read or rewritten.
        task : str, optional
            Arbitrary output directory label, default "spectrum". Letters,
            digits, underscores and hyphens, starting with a letter/digit.
            inputs/logs are reserved. This is NOT the operation identity and
            does not identify which extracted TRA a downstream command reads.
        output_name : str, optional
            Native output filename, default "spectrum.root". Existing products
            receive numbered suffixes; no historical product is overwritten.
        timeout : float or None, optional
            Native command timeout in seconds, default None (unlimited).
        isolate_settings : bool, optional
            False (default) preserves native HOME. True gives this native command
            private settings after setup, without modifying cfg contents.
        attempt : str or None, optional
            Legacy explicit group selector, default None. A different value
            conflicts with a constructor-bound analysis_id.
        log_mode : str, optional
            Python log capture, currently "full" (default), not a native flag.
        **configuration
            Native -C overrides: key underscores become dots; booleans become
            true/false, other values use str without further rewriting. With a
            constructor-bound definition these override the baseline for THIS
            COMMAND ONLY. They are recorded in execution_overrides and never
            become later calls' defaults. Legacy groups retain their recorded
            default/variant behavior until explicitly opened as a bound definition.

        Returns
        -------
        ExecutionResult
            Native outputs['spectrum'], exact upstream references, execution UUID,
            root manifest path and optional nonempty stdout/stderr paths.
            Nonempty products and exit zero establish execution success, not
            scientific correctness. ROOT data extraction is a separate call.

        Raises
        ------
        ValueError
            Input/definition conflict, multiple input candidates, absent prepared
            components, invalid output/settings, or missing required configuration.
        TypeError
            spectrum is passed the removed working_space argument or a positional
            input; bind the root in Mimrec() and use input_data for exact results.
        FileNotFoundError
            A bound configuration or selected data file cannot be read.
        ExecutionError
            Native preparation, execution, timeout or output validation fails.
            The independent failed record and nonempty logs remain available.

        Notes
        -----
        Each native command applies its own selections from the main cfg plus
        explicit overrides; reading selected TRA does not inherit the command
        parameters that produced it. task is a label only. Reopening a group
        uses manifest operation/status/UUID/path records, not directory names.
        Setup executes in a child process; the parent environment is unchanged.
        No event parsing, time shift or physical scaling is performed.

        Examples
        --------
        >>> result = analysis.spectrum(task="my-spectrum")  # doctest: +SKIP
        >>> print(result.outputs["spectrum"])  # doctest: +SKIP
        """
        if input_data is not None and not isinstance(input_data, (ExecutionResult, ExecutionInput)):
            raise ValueError("input_data expects an explicit TRA result/reference; bind working_space in Mimrec()")
        return self._run("spectrum", input_data, tra_path, output_dir, config_file,
                         geometry, task, output_name, timeout, isolate_settings, configuration, attempt, log_mode)

    def arm(self, working_space=None, *, input_data=None, tra_path=None, output_dir=None,
               config_file=None, geometry=None, task="arm", output_name="arm.root",
               timeout=None, isolate_settings=False, attempt=None,
               log_mode="full", **configuration):
        """Execute native Mimrec arm (-a) with explicit data provenance.

        Parameters
        ----------
        working_space : SimulationWorkspace or ExecutionResult or ExecutionInput or str or pathlib.Path or None, optional
            Legacy per-command workspace/result entry, default None. Prefer
            binding the root in Mimrec() and selecting results with input_data.
            Must not conflict with input_data or the constructor-bound root.
        input_data : ExecutionResult or ExecutionInput or None, optional
            Exact TRA result/reference for this command, default None. For a
            bound analysis it must belong to that analysis's data chain.
            None queries the root manifest (not the filesystem): select this
            group's unique successful extract_events record first, otherwise
            its unique successful add_external_components record, otherwise the
            registered primary input. Multiple successful candidates require an
            explicit result, never latest/mtime or a fixed task folder name.
        tra_path : str or pathlib.Path or None, optional
            Legacy external TRA entry, default None. Requires output_dir or a
            constructor-bound workspace. For the new bound-definition API,
            declare the primary path as input_data in Mimrec(), not here.
        output_dir : str or pathlib.Path or None, optional
            Legacy destination experiment root, default None. Bound definitions
            fix their destination in Mimrec() and reject per-command changes.
        config_file : str or pathlib.Path or None, optional
            Default None uses the constructor-bound main configuration or saved
            group default. In a bound definition an explicit file must have the
            same bytes and resource cwd; a different main cfg requires a new
            analysis_id. Legacy calls require a cfg when creating a new group.
            Native bytes are opaque and are never parsed or edited.
        geometry : str or pathlib.Path or None, optional
            Default None reuses bound geometry, or saved legacy defaults when
            cfg is omitted. A different geometry in a bound definition requires
            a new analysis_id. The literal -g value is never read or rewritten.
        task : str, optional
            Arbitrary output directory label, default "arm". Letters,
            digits, underscores and hyphens, starting with a letter/digit.
            inputs/logs are reserved. This is NOT the operation identity and
            does not identify which extracted TRA a downstream command reads.
        output_name : str, optional
            Native output filename, default "arm.root". Existing products
            receive numbered suffixes; no historical product is overwritten.
        timeout : float or None, optional
            Native command timeout in seconds, default None (unlimited).
        isolate_settings : bool, optional
            False (default) preserves native HOME. True gives this native command
            private settings after setup, without modifying cfg contents.
        attempt : str or None, optional
            Legacy explicit group selector, default None. A different value
            conflicts with a constructor-bound analysis_id.
        log_mode : str, optional
            Python log capture, currently "full" (default), not a native flag.
        **configuration
            Native -C overrides: key underscores become dots; booleans become
            true/false, other values use str without further rewriting. With a
            constructor-bound definition these override the baseline for THIS
            COMMAND ONLY. They are recorded in execution_overrides and never
            become later calls' defaults. Legacy groups retain their recorded
            default/variant behavior until explicitly opened as a bound definition.

        Returns
        -------
        ExecutionResult
            Native outputs['arm'], exact upstream references, execution UUID,
            root manifest path and optional nonempty stdout/stderr paths.
            Nonempty products and exit zero establish execution success, not
            scientific correctness. ROOT data extraction is a separate call.

        Raises
        ------
        ValueError
            Input/definition conflict, multiple input candidates, absent prepared
            components, invalid output/settings, or missing required configuration.
        FileNotFoundError
            A bound configuration or selected data file cannot be read.
        ExecutionError
            Native preparation, execution, timeout or output validation fails.
            The independent failed record and nonempty logs remain available.

        Notes
        -----
        Each native command applies its own selections from the main cfg plus
        explicit overrides; reading selected TRA does not inherit the command
        parameters that produced it. task is a label only. Reopening a group
        uses manifest operation/status/UUID/path records, not directory names.
        Setup executes in a child process; the parent environment is unchanged.
        No event parsing, time shift or physical scaling is performed.

        Examples
        --------
        >>> result = analysis.arm(task="my-arm")  # doctest: +SKIP
        >>> print(result.outputs["arm"])  # doctest: +SKIP
        """
        if input_data is not None:
            if working_space is not None:
                raise ValueError("Supply input_data or legacy working_space, not both")
            working_space = input_data
        return self._run("arm", working_space, tra_path, output_dir, config_file,
                         geometry, task, output_name, timeout, isolate_settings, configuration, attempt, log_mode)
