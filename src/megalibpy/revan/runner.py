"""Explicit Revan configuration, input lineage and isolated native settings."""

from dataclasses import replace
from pathlib import Path
import hashlib
import re
import warnings

from ..execution import ExecutionInput, ExecutionPlan, ExecutionResult, MEGAlibRuntime, SimulationWorkspace
from ..execution.executor import Executor
from ..execution.provenance import configuration_snapshot, decode_content, file_record, read_execution, resolve_upstream, sha256


def _event_file(path):
    path = Path(path).expanduser().resolve(strict=True)
    if not path.is_file() or not path.name.endswith((".sim", ".sim.gz", ".evta", ".evta.gz")):
        raise ValueError("sim_path requires a .sim[.gz] or .evta[.gz] file")
    return path


def _input(input_data):
    """Return one explicit native input, its lineage reference and experiment."""
    experiment = None
    if isinstance(input_data, SimulationWorkspace):
        experiment = input_data
        external = experiment.external_sim_path
        if external is not None:
            return _event_file(external), None, experiment
        input_data = input_data.select("cosima")
    if isinstance(input_data, ExecutionResult):
        if input_data.workspace_dir is not None:
            experiment = SimulationWorkspace(input_data.workspace_dir)
        elif read_execution(input_data.manifest_path, input_data.execution_id)[1].get("tool") == "cosima":
            experiment = SimulationWorkspace(input_data.output_dir)
        input_data = input_data.as_input("sim")
    if isinstance(input_data, ExecutionInput):
        _, record = resolve_upstream(input_data)
        if input_data.workspace_dir is not None:
            experiment = SimulationWorkspace(input_data.workspace_dir)
        elif experiment is None:
            manifest_path = Path(record["manifest_path"])
            if read_execution(manifest_path, input_data.execution_id)[1].get("tool") == "cosima":
                experiment = SimulationWorkspace(manifest_path.parent)
        paths = [Path(p) for p in record["paths"]]
        if len(paths) != 1:
            raise ValueError("Revan accepts one native input per call. Select a file with "
                             "result.as_input('sim', paths=[...]) rather than guessing a shard.")
        reference = replace(input_data, execution_id=record["execution_id"], paths=tuple(paths))
        return paths[0], reference, experiment
    path = Path(input_data).expanduser().resolve(strict=True)
    if path.is_dir():
        experiment = SimulationWorkspace(path)
        return _input(experiment)
    raise ValueError("working_space expects an experiment directory or result; "
                     "use sim_path with output_dir for an external event file")


def _prepare(attempt, event_file, geometry, config, executable, compressed, reference,
             overrides, isolate_settings, config_content=None, config_base=None, original_path=None):
    executed, config_record = configuration_snapshot(attempt, config, "revan", content=config_content, cwd=config_base, original_path=original_path)
    home = attempt.log_path("native-home")
    if isolate_settings:
        home.mkdir(exist_ok=True)
    number = f"-{attempt.number:03d}" if attempt.number > 1 else ""
    product = attempt.products_dir / (f"events{number}.tra.gz" if compressed else f"events{number}.tra")
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
    command.extend(("-n", "-a"))
    return ExecutionPlan(tuple(command), config_base or config.parent, {"tra": product.name}, {
        "input_file": file_record(event_file, hash_limit=0),
        "configuration": {**config_record,
                          "settings_home": str(home.relative_to(attempt.root)) if isolate_settings else None},
        "geometry": None if geometry is None else str(geometry),
        "configuration_overrides": changes,
    }, upstream=() if reference is None else (reference,), environment={"HOME": str(home)} if isolate_settings else {})


class Revan:
    """Reconstruct native event data with an explicit native MEGAlib configuration.

    Parameters
    ----------
    runtime : MEGAlibRuntime or None, optional
        Shared direct/setup-script runtime. ``None`` selects direct execution.
    analysis_id : str or None, optional
        Workspace-local reconstruction analysis name, default none. A bound name
        writes all calls to revan/<analysis_id> and reuses its recorded defaults
        when config_file is omitted. None creates a numbered group per call.
        Names use letters, digits, underscores and hyphens, starting with a
        letter/digit. Construction creates no files and launches no process.
    executable : str or pathlib.Path, optional
        Native executable name or path, default ``"revan"``.

    Notes
    -----
    No PyROOT is imported. Geometry, input and output CLI arguments override
    saved file selections in the supplied configuration. Native configuration
    bytes are passed through unchanged; no configuration parser, serializer or
    fixed Python settings model is used.
    """

    def __init__(self, runtime=None, *, analysis_id=None, executable="revan"):
        if analysis_id is not None and (not isinstance(analysis_id, str) or
                                        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", analysis_id)):
            raise ValueError("analysis_id must contain letters, digits, '_' or '-' and start with a letter/digit")
        self.analysis_id = analysis_id
        self.runtime = runtime if runtime is not None else MEGAlibRuntime.direct()
        self.executable = str(executable)

    def reconstruct(self, working_space=None, *, sim_path=None, output_dir=None,
                    config_file=None, geometry=None,
                    task="default", compressed=True, timeout=None, isolate_settings=False,
                    log_mode="full", **configuration):
        """Reconstruct one native event file into a recorded ``tra`` product.

        Parameters
        ----------
        working_space : ExecutionResult or ExecutionInput or SimulationWorkspace or str or pathlib.Path or None, optional
            Existing experiment/legacy Cosima directory, result, or explicit
            upstream reference. Defaults to none. Supply exactly one of
            ``working_space`` or ``sim_path``. Multiple declared files require
            explicit selection. Externally started experiments can be reopened
            here using their recorded input file.
        sim_path : str or pathlib.Path or None, optional
            External ``.sim[.gz]`` or ``.evta[.gz]`` entry file, default none.
            Requires ``output_dir`` to establish an experiment root. The file
            stays in place; no simulation contents are read, copied or hashed.
            Any native continuation references remain MEGAlib's responsibility.
        config_file : str or pathlib.Path or None, optional
            Readable, nonempty native MEGAlib configuration, required for a new
            analysis. None (default) restores a bound analysis group's saved
            bytes, original cwd, geometry and overrides. Original
            bytes are copied unchanged to the execution snapshot and passed to
            Revan via ``-c``. No syntax, field names or values are interpreted.
            Relative resources resolve from this file's parent directory.
        geometry : str or pathlib.Path or None, optional
            With explicit config_file, None (default) omits -g and uses the cfg
            geometry. With inherited configuration it reuses the bound defaults.
            Otherwise forwarded unchanged to ``-g``; MEGAlib handles path
            expansion, opening and overriding. Python does not inspect the file.
            Relative paths use the child cwd (the configuration directory).
        output_dir : str or pathlib.Path or None, optional
            Destination experiment root, required with ``sim_path``. Creates
            ``manifest.json`` and ``revan/attempt-NNN`` below it; it is
            not an individual attempt directory. Existing matching experiments
            can be reused for new data groups. Legacy inputs require a fresh
            destination; their original directories are read-only. With ``working_space``, omission
            continues in that experiment; an explicit root records the existing
            Cosima origin by reference. Defaults to none.
        task : str, optional
            Named reconstruction task, default ``"default"``. Workspace attempts
            are numbered under ``revan/``. Labels remain queryable metadata,
            without another directory level. With analysis_id bound, repeated
            calls share that group and use numbered non-overwriting output files.
            Without a bound ID, each call creates a new numbered group.
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

        log_mode : str, optional
            "full" (default) streams complete stdout/stderr without a byte cap.
            Summary selection is currently available only for Cosima, whose
            native boundary marker is defined. Empty logs are removed. This
            Python option is never forwarded as a native -C setting.

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
            An attempt path is occupied or the experiment index is locked.
        ExecutionError
            Configuration snapshot preparation, launch, execution, timeout or
            nonempty-output checks fail after an attempt record is established.
        KeyboardInterrupt
            Execution is interrupted; diagnostics are retained.

        Warns
        -----
        UserWarning
            Settings differ from a bound analysis group's defaults. The variant
            is recorded without replacing its saved baseline.

        Notes
        -----
        By default, native Revan uses its usual HOME and settings. Optional
        isolation changes HOME only for the tool after setup, without altering
        the parent's environment or rewriting configuration contents.
        No configuration syntax or settings semantics are checked by Python;
        native Revan may diagnose errors or fall back to defaults. Inspect logs.
        A zero exit status plus nonempty output is not a scientific check. External configuration files are managed by MEGAlib and the caller.
        """
        if (working_space is None) == (sim_path is None):
            raise ValueError("Supply exactly one of working_space or sim_path")
        if sim_path is not None and output_dir is None:
            raise ValueError("sim_path requires output_dir for the experiment root")
        if not isinstance(isolate_settings, bool):
            raise ValueError("isolate_settings must be bool")
        if not isinstance(compressed, bool):
            raise ValueError("compressed must be bool")
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be positive")
        if sim_path is not None:
            path, reference, inherited = _event_file(sim_path), None, None
        else:
            path, reference, inherited = _input(working_space)
        if not path.name.endswith((".sim", ".sim.gz", ".evta", ".evta.gz")):
            raise ValueError("Selected product is not a Revan sim/evta input")
        experiment = SimulationWorkspace(output_dir) if output_dir is not None else inherited
        if experiment is None:
            raise ValueError("An explicit output_dir is required for this input reference")
        group = "revan/" + self.analysis_id if self.analysis_id is not None else None
        existing = group is not None and group in experiment._writable()["groups"]
        defaults = experiment.group_defaults(group) if existing else None
        if existing:
            entry = experiment._writable()["groups"][group]
            if "input_file" in entry and entry["input_file"]["path"] != str(path):
                raise ValueError("A different sim/evta input requires a new Revan analysis_id")
        config_content = None
        config_base = None
        original_path = None
        if config_file is None:
            if defaults is None:
                raise ValueError("config_file is required when creating a Revan analysis group")
            saved = defaults["configuration"]
            config_content = decode_content(saved) if saved.get("content") is not None else None
            config = Path(saved["original_path"]) if config_content is not None else experiment.root/group/saved["executed_snapshot"]
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
                       for k,v in configuration.items()]
            digest = hashlib.sha256(config_content).hexdigest() if config_content is not None else sha256(config)
            if (digest != defaults["configuration"]["executed_sha256"] or
                    (None if geometry is None else str(geometry)) != defaults["geometry"] or
                    changes != defaults["configuration_overrides"] or
                    str(config_base or config.parent) != defaults["configuration"]["relative_path_base"]):
                warnings.warn("Revan settings differ from this analysis group's defaults; "
                              "the variant is recorded without replacing defaults.", UserWarning, stacklevel=2)

        def execute(target):
            return Executor(self.runtime).execute(
                "revan", target,
                lambda attempt: _prepare(attempt, path, geometry, config, self.executable,
                                         compressed, reference, configuration, isolate_settings,
                                         config_content, config_base, original_path),
                timeout=timeout, log_mode=log_mode,
            )
        if reference is None:
            experiment.attach_sim(path)
        if reference is not None:
            _, record, _ = read_execution(reference.manifest_path, reference.execution_id)
            if record.get("tool") == "cosima":
                origin = inherited.select("cosima") if inherited is not None else SimulationWorkspace(Path(reference.manifest_path).parent).select("cosima")
                experiment.attach_cosima(origin)
        return experiment.execute("revan", task, execute, group=group)
