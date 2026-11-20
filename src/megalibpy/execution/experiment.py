"""Experiment indexes above the independent per-attempt executor."""

from contextlib import contextmanager
from dataclasses import replace
import json
import os
from pathlib import Path
import re
from uuid import uuid4

from .models import ExecutionInput, ExecutionResult
from .provenance import resolve_upstream, write_manifest


class SimulationWorkspace:
    """Manage stage/task/attempt directories within one experiment.

    Parameters
    ----------
    root : str or pathlib.Path
        Experiment root. Construction does not create files. New experiments use
        ``manifest.json`` as an index. An existing Cosima execution directory is
        accepted unchanged and uses ``workspace.json`` for the additional index.

    Notes
    -----
    A workspace has one Cosima origin, with retry attempts permitted after
    failure. Revan tasks may branch under explicit names. Execution manifests
    remain authoritative; the index records locations and identities, not copies
    of execution metadata. Index writes use a short exclusive lock; contention
    raises ``FileExistsError`` rather than silently losing updates. An abandoned
    lock after a hard process termination needs manual inspection/removal.
    """

    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()

    @property
    def index_path(self):
        """pathlib.Path: Experiment index, preserving a legacy Cosima manifest."""
        manifest = self.root / "manifest.json"
        if manifest.is_file() and json.loads(manifest.read_text()).get("tool") == "cosima":
            return self.root / "workspace.json"
        return manifest

    def _read(self):
        path = self.index_path
        if path.exists():
            data = json.loads(path.read_text())
            if data.get("kind") != "simulation_workspace" or data.get("schema_version") != 1:
                raise ValueError("Not a supported simulation workspace index")
            return data
        data = {"schema_version": 1, "kind": "simulation_workspace",
                "workspace_id": str(uuid4()), "tasks": {}}
        legacy = self.root / "manifest.json"
        if path != legacy:
            record = json.loads(legacy.read_text())
            if record.get("status") != "succeeded":
                raise ValueError("Legacy Cosima execution must have succeeded")
            resolve_upstream(ExecutionInput(legacy, "sim", record.get("execution_id")))
            data["tasks"]["cosima:simulation"] = {
                "task_id": str(uuid4()), "stage": "cosima", "name": "simulation",
                "attempts": [{"number": 1, "manifest": "manifest.json",
                              "execution_id": record.get("execution_id"), "status": "succeeded"}],
            }
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

    def select(self, stage="cosima", *, task=None):
        """Select the single successful attempt in a stage or named task.

        Parameters
        ----------
        stage : str, optional
            Stage name, default ``"cosima"``.
        task : str or None, optional
            Exact task name; ``None`` considers all tasks in the stage.

        Returns
        -------
        ExecutionResult
            Persisted successful result with this experiment root attached.

        Raises
        ------
        ValueError
            No successful result exists or the selection is ambiguous. No file
            modification times or implicit latest-result rules are used.
        """
        data = self._read()
        candidates = []
        for entry in data["tasks"].values():
            if entry["stage"] != stage or (task is not None and entry["name"] != task):
                continue
            for attempt in entry["attempts"]:
                path = (self.root / attempt["manifest"]).resolve()
                if not path.is_file():
                    continue
                record = json.loads(path.read_text())
                if record.get("status") == "succeeded":
                    if record.get("execution_id") != attempt.get("execution_id"):
                        raise ValueError("Indexed execution identity changed")
                    candidates.append((path, record))
        if len(candidates) != 1:
            raise ValueError(f"Expected one successful {stage} result; found {len(candidates)}. "
                             "Select a task or pass an explicit ExecutionResult/ExecutionInput.")
        path, record = candidates[0]
        root = path.parent
        return ExecutionResult(
            root, {key: tuple(root / p for p in paths) for key, paths in record["outputs"].items()},
            path, root / record["logs"]["stdout"], root / record["logs"]["stderr"],
            execution_id=record.get("execution_id"), workspace_dir=self.root,
        )

    def attach_cosima(self, result):
        """Register an existing successful Cosima result without copying products.

        Parameters
        ----------
        result : ExecutionResult
            Existing Cosima execution, including legacy schema-1 results.

        Raises
        ------
        ValueError
            The record is invalid or a different Cosima origin already exists.
        """
        resolve_upstream(result.as_input("sim"))
        record = json.loads(result.manifest_path.read_text())
        if record.get("tool") != "cosima":
            raise ValueError("The experiment origin must be a Cosima execution")
        with self._locked():
            data = self._read()
            key = "cosima:simulation"
            if key in data["tasks"]:
                paths = [(self.root / a["manifest"]).resolve()
                         for a in data["tasks"][key]["attempts"]]
                if result.manifest_path.resolve() not in paths:
                    raise ValueError("Workspace already has a different Cosima origin")
            else:
                data["tasks"][key] = {
                    "task_id": str(uuid4()), "stage": "cosima", "name": "simulation",
                    "attempts": [{"number": 1, "manifest": os.path.relpath(result.manifest_path, self.root),
                                  "execution_id": record.get("execution_id"), "status": "succeeded"}],
                }
            write_manifest(self.index_path, data)

    def execute(self, stage, task, operation):
        """Allocate and index a synchronous tool-adapter execution.

        Parameters
        ----------
        stage : str
            Stage directory name (``cosima``, ``revan`` or a later adapter).
        task : str
            Explicit label containing letters, digits, underscores or hyphens.
            Use a different label for a different configuration. Reusing a label
            creates another attempt and retains all earlier records.
        operation : callable
            Called with a fresh attempt path; must return ``ExecutionResult``.
            The operation owns execution preparation and manifest creation.

        Returns
        -------
        ExecutionResult
            Result with ``workspace_dir`` attached.

        Raises
        ------
        ValueError
            Labels are invalid, or Cosima already succeeded/is in progress.
        FileExistsError
            Index contention or an unexpectedly occupied attempt path.
        Exception
            The adapter's original exception; failed attempts remain indexed.
        """
        for label in (stage, task):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", label):
                raise ValueError("Stage/task labels must contain only letters, digits, '_' or '-'")
        if stage == "cosima" and task != "simulation":
            raise ValueError("Cosima uses the unique 'simulation' task")
        key = f"{stage}:{task}"
        with self._locked():
            data = self._read()
            entry = data["tasks"].setdefault(key, {
                "task_id": str(uuid4()), "stage": stage, "name": task, "attempts": [],
            })
            if stage == "cosima" and any(a["status"] not in ("failed", "interrupted")
                                         for a in entry["attempts"]):
                raise ValueError("Workspace already contains a successful or pending Cosima attempt")
            number = len(entry["attempts"]) + 1
            relative = Path(stage) / task / f"attempt-{number:03d}" / "manifest.json"
            target = self.root / relative
            if target.parent.exists():
                raise FileExistsError(target.parent)
            entry["attempts"].append({"number": number, "manifest": str(relative),
                                      "status": "allocated", "execution_id": None})
            write_manifest(self.index_path, data)
        try:
            result = operation(target.parent)
            return replace(result, workspace_dir=self.root)
        finally:
            with self._locked():
                data = self._read()
                attempt = data["tasks"][key]["attempts"][number - 1]
                if target.is_file():
                    record = json.loads(target.read_text())
                    attempt.update(status=record["status"], execution_id=record.get("execution_id"))
                else:
                    attempt["status"] = "failed"
                write_manifest(self.index_path, data)
