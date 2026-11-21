"""Explicit Revan configuration, input lineage and isolated native settings."""

from dataclasses import replace
import json
from pathlib import Path
import shutil

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
             dependencies, hash_limit, isolate_settings):
    original = attempt.root / "inputs/original.revan.cfg"
    original.write_bytes(config.read_bytes())
    content = original.read_bytes()
    if not content:
        raise ValueError("Revan configuration file must not be empty")
    executed = attempt.root / "inputs/executed.revan.cfg"
    executed.write_bytes(content)
    declared = set(dependencies) | {geometry}
    records = []
    for index, path in enumerate(sorted(declared)):
        record = file_record(path, hash_limit=hash_limit)
        if record["sha256"] is not None:
            snapshot = attempt.root / "inputs" / f"dependency-{index:04d}{path.suffix}"
            shutil.copyfile(path, snapshot)
            if sha256(snapshot) != record["sha256"]:
                raise RuntimeError(f"Dependency changed during snapshot: {path}")
            record["snapshot"] = str(snapshot.relative_to(attempt.root))
        records.append(record)
    home = attempt.root / "logs/native-home"
    if isolate_settings:
        home.mkdir()
    product = attempt.root / "products" / ("events.tra.gz" if compressed else "events.tra")
    command = (executable, "-g", str(geometry), "-c", str(executed),
               "-f", str(source), "-o", str(product), "-n", "-a")
    return ExecutionPlan(command, config.parent, {"tra": product.name}, {
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
        "geometry": str(geometry), "dependencies": records,
        "dependency_capture": {"complete": False, "scope": "top_level_geometry_and_explicit_files",
                               "hash_limit_bytes": hash_limit,
                               "limitations": "Configuration contents are not inspected. Geometry include trees, "
                               "configuration resources, runtime-expanded paths and native "
                               "event-file continuations are not recursively archived. External inputs remain live."},
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

    def reconstruct(self, source, *, config_file, geometry, workspace=None, output_dir=None,
                    task="default", compressed=True, timeout=None, dependencies=(),
                    hash_limit_bytes=64 * 1024 * 1024, isolate_settings=True):
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
        geometry : str or pathlib.Path
            Required existing geometry setup file. Relative paths resolve from
            the calling Python directory. Passed with ``-g``, overriding the cfg.
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
        dependencies : iterable of str or pathlib.Path, optional
            Extra resource files to archive; relative paths use the cfg directory.
        hash_limit_bytes : int or None, optional
            Dependency hash/copy threshold in bytes, default 64 MiB. None archives
            all declared resources. Event input contents are not read or copied;
            their path, size and mtime are recorded.
        isolate_settings : bool, optional
            Default true gives native Revan a private HOME after setup, protecting
            the caller's ``.revan.cfg``. Configuration text is never rewritten:
            HOME-based paths then refer to that private HOME. Use absolute or
            other runtime-variable paths, or explicitly set false to retain the
            original HOME and permit Revan to read/write its usual settings.

        Returns
        -------
        ExecutionResult
            ``outputs["tra"]`` contains the reconstructed file. The execution
            manifest records configuration hashes, geometry, runtime and selected
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
            Configuration/geometry preparation, launch, execution, timeout or
            nonempty-output checks fail after an attempt record is established.
        KeyboardInterrupt
            Execution is interrupted; diagnostics are retained.

        Notes
        -----
        By default, native settings are isolated under ``logs/native-home``.
        HOME changes only for the tool after setup; the parent's environment is
        unchanged. Disabling isolation allows native writes to usual settings.
        No configuration syntax or settings semantics are checked by Python;
        native Revan may diagnose errors or fall back to defaults. Inspect logs. A zero exit status plus nonempty output is not a scientific
        check. Dependency capture is incomplete; external files must stay stable.
        """
        if workspace is not None and output_dir is not None:
            raise ValueError("workspace and output_dir are mutually exclusive")
        if not isinstance(isolate_settings, bool):
            raise ValueError("isolate_settings must be bool")
        if not isinstance(compressed, bool):
            raise ValueError("compressed must be bool")
        if hash_limit_bytes is not None and hash_limit_bytes < 0:
            raise ValueError("hash_limit_bytes must be nonnegative or None")
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be positive")
        path, reference, inherited = _input(source)
        if not path.name.endswith((".sim", ".sim.gz", ".evta", ".evta.gz")):
            raise ValueError("Selected product is not a Revan sim/evta input")
        config = Path(config_file).expanduser().resolve()
        massmodel = Path(geometry).expanduser().resolve()
        files = tuple((config.parent / Path(p).expanduser()).resolve() for p in dependencies)

        def execute(target):
            return Executor(self.runtime).execute(
                "revan", target,
                lambda attempt: _prepare(attempt, path, massmodel, config, self.executable,
                                         compressed, reference, files, hash_limit_bytes, isolate_settings),
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
