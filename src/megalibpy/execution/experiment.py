"""Data-oriented experiment groups with a single authoritative manifest."""

from contextlib import contextmanager
from dataclasses import replace
import json
import os
from pathlib import Path
import re
from uuid import uuid4

from .models import ExecutionResult
from .provenance import read_execution, resolve_upstream, write_manifest
from .workspace import Workspace


class SimulationWorkspace:
    """Manage a unique Cosima origin and data/configuration analysis groups.

    Parameters
    ----------
    root : str or pathlib.Path
        Experiment root. Construction does not create files. New workspaces use
        one schema-2 ``manifest.json`` containing groups and execution records.

    Notes
    -----
    Cosima executes once at ``cosima/``, including failed executions; a rerun
    requires a new workspace. Revan/Mimrec use ``stage/attempt-NNN`` data groups.
    Each command retains an independent execution ID and logs within that group.
    Legacy workspaces remain readable; use a new destination for new executions.
    Short manifest updates are locked; native processes do not hold the lock.
    """

    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()

    @property
    def index_path(self):
        """pathlib.Path: Root manifest, or a legacy workspace index when present."""
        path = self.root / "manifest.json"
        if path.exists() and json.loads(path.read_text()).get("tool") == "cosima":
            legacy = self.root / "workspace.json"
            if legacy.exists():
                return legacy
        return path

    def _read(self):
        path = self.index_path
        if path.exists():
            data = json.loads(path.read_text())
            if data.get("kind") != "simulation_workspace" and data.get("tool") != "cosima":
                raise ValueError("Not a supported simulation workspace index")
            return data
        for parent in self.root.parents:
            ancestor = parent / "manifest.json"
            if ancestor.is_file():
                owner = json.loads(ancestor.read_text())
                if owner.get("kind") == "simulation_workspace":
                    raise ValueError("Not a supported simulation workspace root: nested inside another workspace")
        return {"kind": "simulation_workspace", "schema_version": 2,
                "workspace_id": str(uuid4()), "groups": {}, "executions": {}}

    def _writable(self):
        data = self._read()
        if data.get("kind") != "simulation_workspace" or data.get("schema_version") != 2:
            raise ValueError("Legacy workspace is read-only; pass a new output_dir for the new layout")
        return data

    @contextmanager
    def _locked(self):
        self.root.mkdir(parents=True, exist_ok=True)
        lock = self.root / ".workspace.lock"
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(fd, str(os.getpid()).encode())
            yield
        finally:
            os.close(fd)
            lock.unlink()

    def _result(self, path, record, root):
        return ExecutionResult(
            root, {k: tuple(root / p for p in v) for k, v in record["outputs"].items()},
            path, root / record["logs"]["stdout"] if record["logs"]["stdout"] else None,
            root / record["logs"]["stderr"] if record["logs"]["stderr"] else None,
            execution_id=record.get("execution_id"), workspace_dir=self.root)

    def _select_legacy(self, data, stage, task):
        candidates = []
        if data.get("tool") == "cosima":
            if stage == "cosima":
                candidates = [(self.root / "manifest.json", None)]
        else:
            for entry in data.get("tasks", {}).values():
                if entry["stage"] == stage and (task is None or entry["name"] == task):
                    candidates.extend((self.root / a["manifest"], a.get("execution_id")) for a in entry["attempts"])
        successful = []
        for path, expected in candidates:
            _, record, root = read_execution(path)
            if expected is not None and record.get("execution_id") != expected:
                raise ValueError("Indexed execution identity changed")
            if record.get("status") == "succeeded":
                successful.append((path, record, root))
        if len(successful) != 1:
            raise ValueError(f"Expected one successful {stage} result; found {len(successful)}")
        return self._result(*successful[0])

    def select(self, stage="cosima", *, task=None, attempt=None, operation=None):
        """Select a unique successful execution, never an implicit latest result.

        Parameters
        ----------
        stage : str, optional
            Stage, default ``"cosima"``.
        task : str or None, optional
            Exact operation/task label; None considers all labels.
        attempt : str or None, optional
            Data group basename, e.g. ``"attempt-001"``. Default none.
        operation : str or None, optional
            Native operation, e.g. ``"extract_events"`` or ``"image"``. Default none.

        Returns
        -------
        ExecutionResult
            Selected record with workspace context and exact execution ID.

        Raises
        ------
        ValueError
            No successful execution exists or the choice is ambiguous. Repeated
            successful operations require an explicit saved result/reference.
        """
        data = self._read()
        if data.get("schema_version") != 2 or data.get("kind") != "simulation_workspace":
            return self._select_legacy(data, stage, task)
        origin = data.get("origin", {})
        if stage == "cosima" and origin.get("kind") == "cosima_reference":
            path = Path(origin["manifest_path"])
            _, record, root = read_execution(path, origin["execution_id"])
            if record.get("status") != "succeeded":
                raise ValueError("Referenced Cosima execution must have succeeded")
            return self._result(path, record, root)
        candidates = []
        for record in data["executions"].values():
            if record.get("tool") != stage or record.get("status") != "succeeded":
                continue
            if task is not None and record["task"] != task:
                continue
            if attempt is not None and Path(record["data_group"]).name != attempt:
                continue
            if operation is not None and record["operation"] != operation:
                continue
            candidates.append(record)
        if len(candidates) != 1:
            raise ValueError(f"Expected one successful {stage} result; found {len(candidates)}. "
                             "Select a task/attempt/operation or an explicit execution reference.")
        record = candidates[0]
        return self._result(self.index_path, record, self.root / record["execution_dir"])

    def attach_cosima(self, result):
        """Attach one existing successful Cosima result without copying products.

        Parameters
        ----------
        result : ExecutionResult
            Exact successful native simulation result, including legacy records.

        Raises
        ------
        ValueError
            A different origin is already registered, or the input is not Cosima.
        """
        resolve_upstream(result.as_input("sim"))
        _, record, _ = read_execution(result.manifest_path, result.execution_id)
        if record.get("tool") != "cosima":
            raise ValueError("The experiment origin must be a Cosima execution")
        if result.workspace_dir == self.root and result.manifest_path == self.index_path:
            return
        origin = {"kind": "cosima_reference", "manifest_path": str(result.manifest_path),
                  "execution_id": result.execution_id}
        with self._locked():
            data = self._writable()
            if data.get("origin", origin) != origin:
                raise ValueError("Workspace already has a different Cosima or external origin")
            data["origin"] = origin
            write_manifest(self.index_path, data)

    @property
    def external_sim_path(self):
        """pathlib.Path or None: Registered external simulation input."""
        data = self._read()
        origin = data.get("origin", data.get("external_input", {}))
        return Path(origin["path"]) if origin.get("kind") == "external_sim" else None

    @property
    def external_tra_path(self):
        """pathlib.Path or None: Registered external TRA input."""
        data = self._read()
        origin = data.get("origin", data.get("external_input", {}))
        return Path(origin["path"]) if origin.get("kind") == "external_tra" else None

    def attach_sim(self, sim_path):
        """Register an external simulation origin without copying data.

        Parameters
        ----------
        sim_path : str or pathlib.Path
            Selected external sim/evta entry file.

        Raises
        ------
        ValueError
            A different origin is already registered.
        """
        origin = {"kind": "external_sim", "path": str(Path(sim_path).expanduser().resolve())}
        with self._locked():
            data = self._writable()
            if data.get("origin", origin) != origin:
                raise ValueError("Workspace already starts from a different external or Cosima origin")
            data["origin"] = origin
            write_manifest(self.index_path, data)

    def attach_tra(self, tra_path):
        """Register a TRA origin for an empty workspace, preserving existing origins.

        Parameters
        ----------
        tra_path : str or pathlib.Path
            External TRA input; additional component inputs remain step metadata.
        """
        with self._locked():
            data = self._writable()
            if not data["executions"] and "origin" not in data:
                data["origin"] = {"kind": "external_tra", "path": str(Path(tra_path).expanduser().resolve())}
            write_manifest(self.index_path, data)

    def group_defaults(self, group):
        """Return saved native configuration defaults for an explicit data group.

        Parameters
        ----------
        group : str
            Stage-relative group, e.g. ``"mimrec/attempt-001"``.

        Returns
        -------
        dict or None
            First prepared configuration, geometry, overrides and original cwd;
            none until a configuration was successfully prepared.
        """
        entry = self._writable()["groups"].get(group)
        if entry is None:
            raise ValueError("Select an existing data group")
        return entry.get("defaults")

    def _save_execution(self, workspace, record):
        with self._locked():
            data = self._writable()
            previous = data["executions"][workspace.execution_id]
            record = {**record, **{k: previous[k] for k in
                      ("task", "operation", "data_group", "execution_dir", "number", "reserved_output")}}
            data["executions"][workspace.execution_id] = record
            group = data["groups"][record["data_group"]]
            if "origin" not in data and record.get("upstream"):
                parent = record["upstream"][0]
                data["origin"] = {"kind": "execution_reference", **{k: parent[k] for k in
                                  ("manifest_path", "execution_id", "output_group", "paths")}}
            if "input_file" in record and "input_file" not in group:
                group["input_file"] = record["input_file"]
                group["input_reference"] = record.get("upstream", [None])[0] if record.get("upstream") else None
            if "configuration" in record and "defaults" not in group:
                group["defaults"] = {"configuration": record["configuration"],
                                     "geometry": record.get("geometry"),
                                     "configuration_overrides": record.get("configuration_overrides", [])}
            write_manifest(self.index_path, data)

    def _claim_product(self, workspace, path):
        with self._locked():
            data = self._writable()
            relative = str(path.relative_to(self.root))
            if path.exists() or any(r.get("reserved_output") == relative
                                    for r in data["executions"].values()):
                raise FileExistsError(f"Output already exists or is reserved: {path}")
            data["executions"][workspace.execution_id]["reserved_output"] = relative
            write_manifest(self.index_path, data)

    def execute(self, stage, task, operation, *, group=None, native_operation=None):
        """Allocate a command in a data group and persist it in the root manifest.

        Parameters
        ----------
        stage : str
            ``cosima``, ``revan`` or ``mimrec``.
        task : str
            Output/task label using letters, digits, underscores and hyphens.
        operation : callable
            Receives a managed Workspace and returns ExecutionResult.
        group : str or None, optional
            Explicit existing stage-relative group; None allocates a new one.
        native_operation : str or None, optional
            Native operation identity; defaults to stage.

        Returns
        -------
        ExecutionResult
            Result carrying workspace context and the independent execution ID.

        Raises
        ------
        ValueError
            Invalid group/label, legacy destination, or a second Cosima call.
        FileExistsError
            Lock contention or occupied output location. Failed runs are retained.
        """
        for label in (stage, task):
            if not isinstance(label, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", label):
                raise ValueError("Stage/task labels must contain only letters, digits, '_' or '-'")
        if stage == "mimrec" and task in ("inputs", "logs"):
            raise ValueError("Mimrec task must not use reserved inputs/logs directories")
        if stage == "cosima" and task != "simulation":
            raise ValueError("Cosima uses the unique simulation task")
        native_operation = native_operation or stage
        with self._locked():
            data = self._writable()
            if stage == "cosima":
                if "origin" in data or data["executions"]:
                    raise ValueError("Workspace already contains an origin; Cosima reruns require a new workspace")
                group = "cosima"
            elif group is None:
                number = 1 + max((int(Path(k).name.split('-')[-1]) for k in data["groups"]
                                  if k.startswith(stage + '/')), default=0)
                group = f"{stage}/attempt-{number:03d}"
            elif group not in data["groups"] or data["groups"][group]["stage"] != stage:
                raise ValueError("Select an existing data group in the requested stage")
            if group not in data["groups"]:
                root = self.root / group
                root.mkdir(parents=True, exist_ok=False)
                for folder in ("inputs", "logs"):
                    (root / folder).mkdir()
                data["groups"][group] = {"stage": stage, "group_id": str(uuid4())}
            root = self.root / group
            number = 1 + sum(r["data_group"] == group and r["operation"] == native_operation
                             for r in data["executions"].values())
            folder = task if stage == "mimrec" else "products"
            product = root / folder
            product.mkdir(exist_ok=True)
            execution_id = str(uuid4())
            data["executions"][execution_id] = {
                "execution_id": execution_id, "tool": stage, "status": "allocated",
                "task": task, "operation": native_operation, "data_group": group,
                "execution_dir": group, "number": number, "reserved_output": None}
            if stage == "cosima":
                data["origin"] = {"kind": "cosima", "execution_id": execution_id}
            write_manifest(self.index_path, data)
        workspace = Workspace(root, self, execution_id, native_operation, number, folder)
        try:
            result = operation(workspace)
            return replace(result, workspace_dir=self.root)
        except BaseException:
            with self._locked():
                data = self._writable()
                record = data["executions"][execution_id]
                if record["status"] == "allocated":
                    record["status"] = "failed"
                    write_manifest(self.index_path, data)
            raise
