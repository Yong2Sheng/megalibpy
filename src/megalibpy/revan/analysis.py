"""Opaque construction-bound Revan configuration and immutable group identity."""

import hashlib
from pathlib import Path

from ..execution import SimulationWorkspace
from ..execution.experiment import _deleted_failed_group
from ..execution.provenance import decode_content, encode_content, write_manifest


def changes(values):
    return [{"parameter": key.replace("_", "."),
             "value": ("true" if value else "false") if isinstance(value, bool) else str(value)}
            for key, value in values.items()]


class BoundConfiguration:
    """Freeze native bytes, resource cwd, geometry and baseline -C text."""

    def __init__(self, runner, config_file, geometry, overrides):
        if runner.working_space is None or runner.analysis_id is None:
            raise ValueError("A bound Revan configuration requires working_space and analysis_id")
        self.root = Path(runner.working_space)
        self.analysis_id = runner.analysis_id
        self.experiment = SimulationWorkspace(self.root)
        self.group = "revan/" + runner.analysis_id
        data = self.experiment._writable()
        entry = data["groups"].get(self.group, {})
        recovering = _deleted_failed_group(data, self.root, self.group)
        if recovering and config_file is not None:
            # An explicit main cfg defines the corrected baseline from scratch.
            entry = {}
        saved = entry.get("definition")
        defaults = entry.get("defaults")
        inherited = saved or defaults
        if config_file is not None:
            self.config = Path(config_file).expanduser().resolve()
            self.content = self.config.read_bytes()
            self.cwd = self.config.parent
        elif inherited:
            cfg = inherited["configuration"]
            self.config = Path(cfg["original_path"])
            self.cwd = Path(cfg.get("cwd", cfg.get("relative_path_base")))
            self.content = (decode_content(cfg) if "content" in cfg else
                            (self.root / self.group / cfg["executed_snapshot"]).read_bytes())
        else:
            raise ValueError("config_file is required when defining a new Revan analysis")
        if not self.content:
            raise ValueError("Revan configuration file must not be empty")
        self.geometry = (inherited.get("geometry") if inherited else None) if geometry is None else str(geometry)
        baseline = inherited.get("overrides", inherited.get("configuration_overrides", [])) if inherited else []
        values = {c["parameter"].replace(".", "_"): c["value"] for c in baseline}
        values.update(overrides)
        self.overrides = {c["parameter"].replace(".", "_"): c["value"] for c in changes(values)}
        self.definition = {
            "version": 1,
            "configuration": {"original_path": str(self.config), "cwd": str(self.cwd),
                              "sha256": hashlib.sha256(self.content).hexdigest(), **encode_content(self.content)},
            "geometry": self.geometry, "overrides": changes(self.overrides),
        }
        if not recovering:
            self.check(saved)
        if not recovering and saved is None and defaults:
            cfg = defaults["configuration"]
            if (self.definition["configuration"]["sha256"] != cfg["executed_sha256"] or
                    str(self.cwd) != cfg["relative_path_base"] or self.geometry != defaults.get("geometry") or
                    changes(self.overrides) != defaults.get("configuration_overrides", [])):
                raise ValueError("Different baseline settings require a new analysis_id")

    def check(self, saved):
        if saved is None:
            return
        def identity(definition):
            cfg = definition["configuration"]
            return {**definition, "configuration": {k: cfg[k] for k in ("sha256", "cwd")}}
        if identity(saved) != identity(self.definition):
            raise ValueError("Different Revan baseline settings require a new analysis_id")

    def validate(self, runner, experiment, config_file, geometry):
        if (runner.analysis_id != self.analysis_id or runner.working_space != self.root or
                experiment.root != self.root):
            raise ValueError("Construct a new Revan object instead of changing bound workspace/analysis identifiers")
        if config_file is not None:
            config = Path(config_file).expanduser().resolve()
            if config.read_bytes() != self.content or config.parent != self.cwd:
                raise ValueError("Different main configuration requires a new analysis_id")
        if geometry is not None and str(geometry) != self.geometry:
            raise ValueError("Different geometry requires a new analysis_id")
        data = experiment._writable()
        if not _deleted_failed_group(data, self.root, self.group):
            self.check(data["groups"].get(self.group, {}).get("definition"))

    def bind(self):
        with self.experiment._locked():
            data = self.experiment._writable()
            entry = data["groups"][self.group]
            self.check(entry.get("definition"))
            entry.setdefault("definition", self.definition)
            write_manifest(self.experiment.index_path, data)
