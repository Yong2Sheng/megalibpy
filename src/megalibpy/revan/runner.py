"""Explicit Revan configuration, input lineage and isolated native settings."""

from dataclasses import replace
import json
from pathlib import Path

from ..execution import ExecutionInput, ExecutionPlan, ExecutionResult, MEGAlibRuntime, SimulationWorkspace
from ..execution.executor import Executor
from ..execution.provenance import file_record, resolve_upstream, sha256


def _input(source):
    """Return one explicit native input, its lineage reference and experiment."""
    experiment = None
    if isinstance(source, SimulationWorkspace):
        experiment = source
        source = source.select("cosima")
    if isinstance(source, ExecutionResult):
        if source.workspace_dir is not None:
            experiment = SimulationWorkspace(source.workspace_dir)
        elif json.loads(source.manifest_path.read_text()).get("tool") == "cosima":
            experiment = SimulationWorkspace(source.output_dir)
        source = source.as_input("sim")
    if isinstance(source, ExecutionInput):
        _, record = resolve_upstream(source)
        if source.workspace_dir is not None:
            experiment = SimulationWorkspace(source.workspace_dir)
        elif experiment is None:
            manifest_path = Path(record["manifest_path"])
            if json.loads(manifest_path.read_text()).get("tool") == "cosima":
                experiment = SimulationWorkspace(manifest_path.parent)
        paths = [Path(p) for p in record["paths"]]
        if len(paths) != 1:
            raise ValueError("Revan accepts one native input per call. Select a file with "
                             "result.as_input('sim', paths=[...]) rather than guessing a shard.")
        reference = replace(source, execution_id=record["execution_id"], paths=tuple(paths))
        return paths[0], reference, experiment
    path = Path(source).expanduser().resolve(strict=True)
    if path.is_dir():
        experiment = SimulationWorkspace(path)
        return _input(experiment)
    if not path.is_file() or not path.name.endswith((".sim", ".sim.gz", ".evta", ".evta.gz")):
        raise ValueError("Revan requires a .sim[.gz] or .evta[.gz] file; .tra files belong to Mimrec")
    return path, None, experiment


def _prepare(attempt, source, geometry, config, executable, compressed, reference,
             overrides, isolate_settings):
    original = attempt.root / "inputs/original.revan.cfg"
    original.write_bytes(config.read_bytes())
    content = original.read_bytes()
    if not content:
        raise ValueError("Revan configuration file must not be empty")
    executed = attempt.root / "inputs/executed.revan.cfg"
    executed.write_bytes(content)
    home = attempt.root / "logs/native-home"
    if isolate_settings:
        home.mkdir()
    product = attempt.root / "products" / ("events.tra.gz" if compressed else "events.tra")
    command = [executable, "-c", str(executed), "-f", str(source), "-o", str(product)]
    if geometry is not None:
        command.extend(("-g", str(geometry)))
    changes = []
    for key, value in overrides.items():
        name = key.replace("_", ".")
        text = ("true" if value else "false") if isinstance(value, bool) else str(value)
        command.extend(("-C", f"{name}={text}"))
        changes.append({"parameter": name, "value": text})
    command.extend(("-n", "-a"))
    return ExecutionPlan(tuple(command), config.parent, {"tra": product.name}, {
        "input_file": file_record(source, hash_limit=0),
        "configuration": {"original_path": str(config),
                          "original_snapshot": "inputs/original.revan.cfg",
                          "original_sha256": sha256(original),
                          "executed_snapshot": "inputs/executed.revan.cfg",
                          "executed_sha256": sha256(executed),
                          "relative_path_base": str(config.parent),
                          "settings_home": "logs/native-home" if isolate_settings else None,
                          "format": "native_passthrough",
                          "validation": "readable_nonempty_file; native parser handles configuration"},
        "geometry": None if geometry is None else str(geometry),
        "configuration_overrides": changes,
    }, upstream=() if reference is None else (reference,), environment={"HOME": str(home)} if isolate_settings else {})


class Revan:
    """Reconstruct native event data with an explicit native MEGAlib configuration.

    Parameters
    ----------
    runtime : MEGAlibRuntime or None, optional
        Shared direct/setup-script runtime. ``None`` selects direct execution.
    executable : str or pathlib.Path, optional
        Native executable name or path, default ``"revan"``.

    Notes
    -----
    No PyROOT is imported. Geometry, input and output CLI arguments override
    saved file selections in the supplied configuration. Native configuration
    bytes are passed through unchanged; no configuration parser, serializer or
    fixed Python settings model is used.
    """

    def __init__(self, runtime=None, *, executable="revan"):
        self.runtime = runtime if runtime is not None else MEGAlibRuntime.direct()
        self.executable = str(executable)

    def reconstruct(self, source, *, config_file, geometry=None, workspace=None, output_dir=None,
                    task="default", compressed=True, timeout=None, isolate_settings=False,
                    **configuration):
        """Reconstruct one native event file into a recorded ``tra`` product.

        Parameters
        ----------
        source : ExecutionResult or ExecutionInput or SimulationWorkspace or str or pathlib.Path
            Cosima result, explicit manifest/group/subset reference, experiment or
            legacy Cosima directory, or a standalone ``.sim[.gz]``/``.evta[.gz]``.
            Multiple declared input files require explicit selection. A single
            native file may itself reference continuation files handled by Revan.
        config_file : str or pathlib.Path
            Required readable, nonempty native MEGAlib configuration. Original
            bytes are copied unchanged to the execution snapshot and passed to
            Revan via ``-c``. No syntax, field names or values are interpreted.
            Relative resources resolve from this file's parent directory.
        geometry : str or pathlib.Path or None, optional
            Default none omits ``-g``, using the native configuration's geometry.
            Otherwise forwarded unchanged to ``-g``; MEGAlib handles path
            expansion, opening and overriding. Python does not inspect the file.
            Relative paths use the child cwd (the configuration directory).
        workspace : SimulationWorkspace or str or pathlib.Path or None, optional
            Destination experiment. If omitted, inherit the result's experiment
            or adopt a legacy Cosima directory. For standalone files, create an
            adjacent ``<input-stem>-workspace`` directory. External files remain
            in place. Mutually exclusive with ``output_dir``.
        output_dir : str or pathlib.Path or None, optional
            Opt out of experiment management and use this fresh attempt directory.
            Existing directories are rejected. Defaults to none.
        task : str, optional
            Named reconstruction task, default ``"default"``. Workspace attempts
            are numbered under ``revan/<task>/``. Use a new label for a different
            configuration; records from earlier attempts are never overwritten.
        compressed : bool, optional
            Default true produces ``products/events.tra.gz``; false uses ``.tra``.
            Compression is selected through the output suffix, not Cosima flags.
        timeout : float or None, optional
            Positive child-process timeout in seconds, including setup. None waits
            indefinitely. Preparation/final record writing are excluded.
        isolate_settings : bool, optional
            Default false retains native HOME/settings behavior. Explicit true
            gives the tool a private HOME after setup. Configuration contents
            remain unchanged, so HOME-based paths then use the private HOME.

        **configuration
            Native configuration overrides. Each keyword's underscores become
            dots: ``TotalEnergy_Min=100`` gives ``-C TotalEnergy.Min=100``.
            Values are passed as one argument without path/value rewriting;
            booleans become ``true``/``false``, other values use ``str``. Field
            existence, value validity and external files are MEGAlib's concern.
            CLI ``-g/-f/-o`` selections take precedence according to native rules.

        Returns
        -------
        ExecutionResult
            ``outputs["tra"]`` contains the reconstructed file. The execution
            manifest records configuration hashes, CLI overrides, runtime and selected
            upstream input. Managed results also expose ``workspace_dir``.

        Raises
        ------
        ValueError
            Invalid arguments, unsupported/ambiguous inputs or workspace selection.
        FileNotFoundError
            Input selection cannot be resolved before allocation.
        FileExistsError
            An explicit output directory exists or the workspace index is locked.
        ExecutionError
            Configuration snapshot preparation, launch, execution, timeout or
            nonempty-output checks fail after an attempt record is established.
        KeyboardInterrupt
            Execution is interrupted; diagnostics are retained.

        Notes
        -----
        By default, native Revan uses its usual HOME and settings. Optional
        isolation changes HOME only for the tool after setup, without altering
        the parent's environment or rewriting configuration contents.
        No configuration syntax or settings semantics are checked by Python;
        native Revan may diagnose errors or fall back to defaults. Inspect logs.
        A zero exit status plus nonempty output is not a scientific check. External configuration files are managed by MEGAlib and the caller.
        """
        if workspace is not None and output_dir is not None:
            raise ValueError("workspace and output_dir are mutually exclusive")
        if not isinstance(isolate_settings, bool):
            raise ValueError("isolate_settings must be bool")
        if not isinstance(compressed, bool):
            raise ValueError("compressed must be bool")
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be positive")
        path, reference, inherited = _input(source)
        if not path.name.endswith((".sim", ".sim.gz", ".evta", ".evta.gz")):
            raise ValueError("Selected product is not a Revan sim/evta input")
        config = Path(config_file).expanduser().resolve()

        def execute(target):
            return Executor(self.runtime).execute(
                "revan", target,
                lambda attempt: _prepare(attempt, path, geometry, config, self.executable,
                                         compressed, reference, configuration, isolate_settings),
                timeout=timeout,
            )
        if output_dir is not None:
            return execute(output_dir)
        experiment = workspace if isinstance(workspace, SimulationWorkspace) else (
            SimulationWorkspace(workspace) if workspace is not None else inherited)
        if experiment is None:
            stem = path.name.removesuffix(".gz").rsplit(".", 1)[0]
            experiment = SimulationWorkspace(path.parent / f"{stem}-workspace")
        if reference is not None:
            record = json.loads(Path(reference.manifest_path).read_text())
            if record.get("tool") == "cosima":
                origin = SimulationWorkspace(Path(reference.manifest_path).parent).select("cosima")
                experiment.attach_cosima(origin)
        return experiment.execute("revan", task, execute)
