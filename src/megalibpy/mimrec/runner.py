"""Thin native Mimrec commands with immutable execution records."""

from dataclasses import replace
from glob import escape
from pathlib import Path

from ..execution import ExecutionInput, ExecutionPlan, ExecutionResult, MEGAlibRuntime, SimulationWorkspace
from ..execution.executor import Executor
from ..execution.provenance import file_record, resolve_upstream, sha256


def _event_file(path):
    path = Path(path).expanduser().resolve(strict=True)
    if not path.is_file() or not path.name.endswith((".tra", ".tra.gz")):
        raise ValueError("tra_path requires a .tra or .tra.gz file")
    return path


def _input(input_data):
    experiment = None
    if isinstance(input_data, SimulationWorkspace):
        experiment = input_data
        # Existing reconstructed branches take precedence over an external origin.
        # select() rejects ambiguity; it never guesses a latest result.
        if any(t["stage"] == "revan" for t in experiment._read()["tasks"].values()):
            input_data = experiment.select("revan")
        elif experiment.external_tra_path is not None:
            return _event_file(experiment.external_tra_path), None, experiment
        else:
            input_data = experiment.select("revan")
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
        return _input(SimulationWorkspace(path))
    raise ValueError("working_space expects an experiment or result; use tra_path with output_dir")


def _prepare(attempt, event_file, geometry, config, executable, operation, output_name, reference,
             overrides, isolate_settings):
    original = attempt.root / "inputs/original.mimrec.cfg"
    original.write_bytes(config.read_bytes())
    content = original.read_bytes()
    if not content:
        raise ValueError("Mimrec configuration file must not be empty")
    executed = attempt.root / "inputs/executed.mimrec.cfg"
    executed.write_bytes(content)
    home = attempt.root / "logs/native-home"
    if isolate_settings:
        home.mkdir()
    product = attempt.root / "products" / output_name
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
    return ExecutionPlan(tuple(command), config.parent, {"tra" if operation == "extract_events" else operation: escape(product.name)}, {
        "operation": operation,
        "input_file": file_record(event_file, hash_limit=0),
        "configuration": {"original_path": str(config),
                          "original_snapshot": "inputs/original.mimrec.cfg",
                          "original_sha256": sha256(original),
                          "executed_snapshot": "inputs/executed.mimrec.cfg",
                          "executed_sha256": sha256(executed),
                          "relative_path_base": str(config.parent),
                          "settings_home": "logs/native-home" if isolate_settings else None,
                          "format": "native_passthrough",
                          "validation": "readable_nonempty_file; native parser handles configuration"},
        "geometry": None if geometry is None else str(geometry),
        "configuration_overrides": changes,
    }, upstream=() if reference is None else (reference,), environment={"HOME": str(home)} if isolate_settings else {})


class Mimrec:
    """Run independent native Mimrec operations without importing PyROOT.

    Parameters
    ----------
    runtime : MEGAlibRuntime or None, optional
        Direct or setup-script runtime. None selects direct execution.
    executable : str or pathlib.Path, optional
        Native executable name or path, default ``"mimrec"``.

    Notes
    -----
    Configurations are opaque snapshots. MEGAlib controls event selection,
    configuration semantics, geometry and external resources. Each call runs
    one native operation and retains its own task/attempt record.
    """

    def __init__(self, runtime=None, *, executable="mimrec"):
        self.runtime = runtime if runtime is not None else MEGAlibRuntime.direct()
        self.executable = str(executable)

    def _run(self, operation, working_space, tra_path, output_dir, config_file,
             geometry, task, output_name, timeout, isolate_settings, configuration):
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
        else:
            path, reference, inherited = _input(working_space)
        config = Path(config_file).expanduser().resolve()
        experiment = SimulationWorkspace(output_dir) if output_dir is not None else inherited
        if experiment is None:
            raise ValueError("An explicit output_dir is required for this input reference")
        # External step inputs never replace an existing Cosima/sim/tra origin.
        # For a new experiment this records a real TRA entry, without fake runs.
        if reference is None:
            experiment.attach_tra(path)

        def execute(target):
            return Executor(self.runtime).execute(
                "mimrec", target,
                lambda attempt: _prepare(attempt, path, geometry, config, self.executable,
                                         operation, output_name, reference, configuration,
                                         isolate_settings), timeout=timeout,
            )
        return experiment.execute("mimrec", task, execute)

    def extract_events(self, working_space=None, *, tra_path=None, output_dir=None,
               config_file, geometry=None, task="extract_events", output_name="events.tra.gz",
               timeout=None, isolate_settings=False, **configuration):
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
            workspace context. Records go below ``mimrec/<task>/attempt-NNN``.
            External step inputs do not replace an existing experiment origin.
        config_file : str or pathlib.Path
            Required readable nonempty native configuration. Original bytes are
            snapshotted unchanged and passed via ``-c``. The child runs in this
            file's parent directory so relative configuration resources retain
            their base. Python does not parse or repair settings.
        geometry : str or pathlib.Path or None, optional
            None (default) omits ``-g`` and uses the configuration's geometry.
            Otherwise forwarded literally via ``-g``; no expansion, resource
            checks or snapshots are performed by Python.
        task : str, optional
            Task label, default ``"extract_events"``. Different settings should use
            different labels. Reusing a label creates a new numbered attempt.
        output_name : str, optional
            Filename inside this attempt's products directory, default
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
                         geometry, task, output_name, timeout, isolate_settings, configuration)

    def image(self, working_space=None, *, tra_path=None, output_dir=None,
               config_file, geometry=None, task="image", output_name="image.root",
               timeout=None, isolate_settings=False, **configuration):
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
            workspace context. Records go below ``mimrec/<task>/attempt-NNN``.
            External step inputs do not replace an existing experiment origin.
        config_file : str or pathlib.Path
            Required readable nonempty native configuration. Original bytes are
            snapshotted unchanged and passed via ``-c``. The child runs in this
            file's parent directory so relative configuration resources retain
            their base. Python does not parse or repair settings.
        geometry : str or pathlib.Path or None, optional
            None (default) omits ``-g`` and uses the configuration's geometry.
            Otherwise forwarded literally via ``-g``; no expansion, resource
            checks or snapshots are performed by Python.
        task : str, optional
            Task label, default ``"image"``. Different settings should use
            different labels. Reusing a label creates a new numbered attempt.
        output_name : str, optional
            Filename inside this attempt's products directory, default
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
                         geometry, task, output_name, timeout, isolate_settings, configuration)

    def spectrum(self, working_space=None, *, tra_path=None, output_dir=None,
               config_file, geometry=None, task="spectrum", output_name="spectrum.root",
               timeout=None, isolate_settings=False, **configuration):
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
            workspace context. Records go below ``mimrec/<task>/attempt-NNN``.
            External step inputs do not replace an existing experiment origin.
        config_file : str or pathlib.Path
            Required readable nonempty native configuration. Original bytes are
            snapshotted unchanged and passed via ``-c``. The child runs in this
            file's parent directory so relative configuration resources retain
            their base. Python does not parse or repair settings.
        geometry : str or pathlib.Path or None, optional
            None (default) omits ``-g`` and uses the configuration's geometry.
            Otherwise forwarded literally via ``-g``; no expansion, resource
            checks or snapshots are performed by Python.
        task : str, optional
            Task label, default ``"spectrum"``. Different settings should use
            different labels. Reusing a label creates a new numbered attempt.
        output_name : str, optional
            Filename inside this attempt's products directory, default
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
                         geometry, task, output_name, timeout, isolate_settings, configuration)

    def arm(self, working_space=None, *, tra_path=None, output_dir=None,
               config_file, geometry=None, task="arm", output_name="arm.root",
               timeout=None, isolate_settings=False, **configuration):
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
            workspace context. Records go below ``mimrec/<task>/attempt-NNN``.
            External step inputs do not replace an existing experiment origin.
        config_file : str or pathlib.Path
            Required readable nonempty native configuration. Original bytes are
            snapshotted unchanged and passed via ``-c``. The child runs in this
            file's parent directory so relative configuration resources retain
            their base. Python does not parse or repair settings.
        geometry : str or pathlib.Path or None, optional
            None (default) omits ``-g`` and uses the configuration's geometry.
            Otherwise forwarded literally via ``-g``; no expansion, resource
            checks or snapshots are performed by Python.
        task : str, optional
            Task label, default ``"arm"``. Different settings should use
            different labels. Reusing a label creates a new numbered attempt.
        output_name : str, optional
            Filename inside this attempt's products directory, default
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
                         geometry, task, output_name, timeout, isolate_settings, configuration)
