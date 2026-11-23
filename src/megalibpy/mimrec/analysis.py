"""Bound Mimrec data/configuration definitions, separate from command overrides."""

from dataclasses import replace
import hashlib
from pathlib import Path

from ..execution import ExecutionInput, ExecutionResult, SimulationWorkspace
from ..execution.provenance import decode_content, encode_content, file_record, read_execution, write_manifest


def changes(values):
    return [{"parameter": key.replace("_", "."),
             "value": ("true" if value else "false") if isinstance(value, bool) else str(value)}
            for key, value in values.items()]


def _descriptor(path, reference):
    return {"file": file_record(path, hash_limit=0),
            "reference": None if reference is None else {
                "manifest_path": str(reference.manifest_path),
                "execution_id": reference.execution_id, "output_group": reference.output_group,
                "paths": [str(p) for p in reference.paths],
                "workspace_dir": None if reference.workspace_dir is None else str(reference.workspace_dir)}}


def _restore(descriptor):
    from .runner import _event_file
    path = _event_file(descriptor["file"]["path"])
    saved = descriptor["reference"]
    reference = None if saved is None else ExecutionInput(
        Path(saved["manifest_path"]), saved["output_group"], saved["execution_id"],
        tuple(Path(p) for p in saved["paths"]),
        None if saved["workspace_dir"] is None else Path(saved["workspace_dir"]))
    return path, reference


class BoundAnalysis:
    """Internal immutable analysis declaration; construction never writes files."""

    def __init__(self, runner, config_file, geometry, components, input_data, overrides):
        from .runner import _event_file, _input, _revan_analysis
        if runner.working_space is None:
            if isinstance(input_data, (ExecutionResult, ExecutionInput)) and input_data.workspace_dir is not None:
                runner.working_space = Path(input_data.workspace_dir).resolve()
            else:
                raise ValueError("A bound Mimrec definition requires working_space=experiment root")
        if runner.analysis_id is None:
            raise ValueError("A bound Mimrec definition requires analysis_id (or revan_analysis_id)")
        self.runner = runner
        self.analysis_id = runner.analysis_id
        self.revan_analysis_id = runner.revan_analysis_id
        self.experiment = SimulationWorkspace(runner.working_space)
        self.group = "mimrec/" + runner.analysis_id
        entry = self.experiment._writable()["groups"].get(self.group, {})
        saved = entry.get("definition")

        def resolve(value):
            if isinstance(value, (str, Path)):
                path = Path(value).expanduser().resolve()
                if path.is_file():
                    return _event_file(path), None
            path, reference, _ = _input(value)
            return path, reference

        if input_data is not None:
            primary = resolve(input_data)
        elif saved:
            primary = _restore(saved["main_input"])
        elif entry.get("input_reference"):
            ref = entry["input_reference"]
            primary = resolve(ExecutionInput(Path(ref["manifest_path"]), ref["output_group"],
                                             ref["execution_id"], tuple(Path(p) for p in ref["paths"]),
                                             self.experiment.root))
        elif entry.get("input_file"):
            primary = _event_file(entry["input_file"]["path"]), None
        else:
            if runner.revan_analysis_id is None and any(
                    record.get("tool") == "revan" for record in self.experiment._read()["executions"].values()):
                raise ValueError("revan_analysis_id is required for a new named analysis; or pass explicit input_data")
            path, reference, _ = _input(self.experiment, analysis_id=runner.revan_analysis_id)
            primary = path, reference
        if runner.revan_analysis_id is not None and _revan_analysis(primary[1]) != runner.revan_analysis_id:
            raise ValueError("Revan analysis mismatch in the bound Mimrec definition")
        self.primary = primary
        if isinstance(components, (str, Path, ExecutionResult, ExecutionInput)):
            raise ValueError("external_components must be an iterable of prepared TRA inputs")
        self.components = (tuple(_restore(d) for d in saved["external_components"])
                           if components is None and saved else tuple(resolve(v) for v in (components or ())))
        paths = [primary[0], *(p for p, _ in self.components)]
        if len(set(paths)) != len(paths):
            raise ValueError("Main input and external components must select unique TRA paths")
        if any("\n" in str(p) or "\r" in str(p) for p in paths):
            raise ValueError("Native IN paths cannot contain newlines")

        defaults = entry.get("defaults")
        if config_file is not None:
            self.config = Path(config_file).expanduser().resolve()
            self.content = self.config.read_bytes()
            self.cwd = self.config.parent
        elif saved:
            self.config = Path(saved["configuration"]["original_path"])
            self.content = decode_content(saved["configuration"])
            self.cwd = Path(saved["configuration"]["cwd"])
        elif defaults:
            cfg = defaults["configuration"]
            self.config = Path(cfg["original_path"])
            self.content = (decode_content(cfg) if "content" in cfg else
                            (self.experiment.root / self.group / cfg["executed_snapshot"]).read_bytes())
            self.cwd = Path(cfg["relative_path_base"])
        else:
            raise ValueError("config_file is required when defining a new Mimrec analysis")
        if not self.content:
            raise ValueError("Mimrec configuration file must not be empty")
        inherited = saved["geometry"] if saved else defaults.get("geometry") if defaults else None
        self.geometry = inherited if geometry is None else str(geometry)
        baseline_changes = saved["overrides"] if saved else defaults.get("configuration_overrides", []) if defaults else []
        self.overrides = {c["parameter"].replace(".", "_"): c["value"] for c in baseline_changes}
        self.overrides.update(overrides)
        # Bind the native text now; a caller-owned mutable value must not alter
        # the baseline after the constructor's definition has been checked.
        self.overrides = {key: (("true" if value else "false") if isinstance(value, bool) else str(value))
                          for key, value in self.overrides.items()}
        self.definition = {
            "version": 1,
            "main_input": _descriptor(*primary),
            "external_components": [_descriptor(*component) for component in self.components],
            "configuration": {"original_path": str(self.config), "cwd": str(self.cwd),
                              "sha256": hashlib.sha256(self.content).hexdigest(), **encode_content(self.content)},
            "geometry": self.geometry, "overrides": changes(self.overrides),
        }
        self.check(saved)
        if saved is None and defaults:
            previous = defaults["configuration"]
            if (self.definition["configuration"]["sha256"] != previous["executed_sha256"] or
                    str(self.cwd) != previous["relative_path_base"] or
                    self.geometry != defaults.get("geometry") or changes(self.overrides) != baseline_changes):
                raise ValueError("Different baseline settings require a new analysis_id")

    def check(self, saved):
        if saved is None:
            return
        def identity(definition):
            config = definition["configuration"]
            return {**definition, "configuration": {k: config[k] for k in ("sha256", "cwd")}}
        if identity(saved) != identity(self.definition):
            raise ValueError("Mimrec analysis definition differs; use a new analysis_id for different data or baseline settings")

    def bind(self, workspace):
        with self.experiment._locked():
            data = self.experiment._writable()
            group = data["groups"][self.group]
            self.check(group.get("definition"))
            group.setdefault("definition", self.definition)
            # This is the real main input, not the temporary IN list used by -x.
            group.setdefault("input_file", self.definition["main_input"]["file"])
            group.setdefault("input_reference", self.definition["main_input"]["reference"])
            write_manifest(self.experiment.index_path, data)

    def select(self, operation, explicit=None):
        from .runner import _input
        records = self.experiment._writable()["executions"].values()
        if explicit is not None:
            if not isinstance(explicit, (ExecutionInput, ExecutionResult)):
                raise ValueError("input_data must be an explicit ExecutionResult/ExecutionInput")
            path, reference, _ = _input(explicit)
            _, record, _ = read_execution(reference.manifest_path, reference.execution_id)
            same_group = (Path(reference.manifest_path) == self.experiment.index_path
                          and record.get("data_group") == self.group)
            primary = (path == self.primary[0] and reference == self.primary[1] and not self.components)
            if not same_group and not primary:
                raise ValueError("input_data must belong to this Mimrec analysis data chain")
            return path, reference
        for candidate in ("extract_events", "add_external_components"):
            if any(r.get("data_group") == self.group and r.get("operation") == candidate
                   and r.get("status") == "succeeded" for r in records):
                selected = self.experiment.select("mimrec", analysis_id=self.analysis_id, operation=candidate)
                path, reference, _ = _input(selected)
                return path, reference
        if self.components:
            raise ValueError("External components are declared; call add_external_components() before analysis")
        return self.primary

    def run(self, operation, explicit, tra_path, output_dir, config_file, geometry,
            task, output_name, timeout, isolate_settings, overrides, attempt, log_mode):
        from .runner import _prepare
        from ..execution.executor import Executor
        if (self.runner.analysis_id != self.analysis_id or self.runner.revan_analysis_id != self.revan_analysis_id
                or Path(self.runner.working_space).resolve() != self.experiment.root):
            raise ValueError("Construct a new Mimrec object instead of changing bound workspace/analysis identifiers")
        if "working_space" in overrides:
            raise TypeError("spectrum() no longer accepts working_space; bind it in Mimrec() and use input_data for a result")
        if tra_path is not None or output_dir is not None:
            raise ValueError("Bind data and destination in Mimrec(); per-command tra_path/output_dir cannot change an analysis")
        if attempt is not None and attempt != self.analysis_id:
            raise ValueError("attempt conflicts with the bound analysis_id")
        if explicit is not None and not isinstance(explicit, (ExecutionInput, ExecutionResult)):
            if isinstance(explicit, SimulationWorkspace) or Path(explicit).resolve() == self.experiment.root:
                root = explicit.root if isinstance(explicit, SimulationWorkspace) else Path(explicit).resolve()
                if root != self.experiment.root:
                    raise ValueError("Conflicting bound working_space")
                explicit = None
        if config_file is not None:
            config = Path(config_file).expanduser().resolve()
            if config.read_bytes() != self.content or config.parent != self.cwd:
                raise ValueError("Different main configuration requires a new analysis_id")
        if geometry is not None and str(geometry) != self.geometry:
            raise ValueError("Different geometry requires a new analysis_id")
        if not isinstance(isolate_settings, bool):
            raise ValueError("isolate_settings must be bool")
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be positive")
        if not isinstance(output_name, str) or not output_name or Path(output_name).name != output_name or output_name in (".", ".."):
            raise ValueError("output_name must be a filename inside the task output directory")
        if operation in ("extract_events", "add_external_components"):
            if not output_name.endswith((".tra", ".tra.gz")):
                raise ValueError("Event output_name must end in .tra or .tra.gz")
        elif not Path(output_name).suffix:
            raise ValueError("Plot output_name requires an explicit native output suffix")
        self.check(self.experiment._writable()["groups"].get(self.group, {}).get("definition"))
        inputs = None
        if operation == "add_external_components":
            if explicit is not None or not self.components:
                raise ValueError("add_external_components uses the primary and external_components declared in Mimrec()")
            inputs = (self.primary, *self.components)
            path, reference = self.primary
        else:
            path, reference = self.select(operation, explicit)
        effective = {**self.overrides, **overrides}
        if inputs is not None or path == self.primary[0]:
            descriptors = ([self.definition["main_input"], *self.definition["external_components"]]
                           if inputs is not None else [self.definition["main_input"]])
            for descriptor in descriptors:
                current = file_record(Path(descriptor["file"]["path"]), hash_limit=0)
                if current != descriptor["file"]:
                    raise ValueError("Bound TRA input changed on disk; use a new analysis_id")
        if self.primary[1] is None:
            self.experiment.attach_tra(self.primary[0])

        def execute(target):
            self.bind(target)
            def prepare(workspace):
                plan = _prepare(workspace, path, self.geometry, self.config, self.runner.executable,
                                operation, output_name, reference, effective, isolate_settings,
                                self.cwd, str(self.config), self.content, self.revan_analysis_id,
                                components=inputs)
                return replace(plan, metadata={**plan.metadata,
                    "analysis_baseline_overrides": changes(self.overrides),
                    "execution_overrides": changes(overrides)})
            return Executor(self.runner.runtime).execute("mimrec", target, prepare, timeout=timeout, log_mode=log_mode)
        return self.experiment.execute("mimrec", task, execute, group=self.group, native_operation=operation)
