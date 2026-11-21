"""Descriptions of commands and completed executions."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExecutionInput:
    """Select an upstream execution's product group for a tool adapter.

    Parameters
    ----------
    manifest_path : pathlib.Path
        Root workspace manifest, selected by execution_id, or a legacy standalone
        execution manifest. Local upstreams use ID links; external selected records
        are snapshotted before launch.
    output_group : str
        Explicit product group to consume, such as ``"sim"`` or ``"tra"``.
    execution_id : str or None, optional
        Expected upstream identity, mandatory for central workspace manifests.
        Results supply their ID automatically; None supports legacy records.
    paths : tuple of pathlib.Path or None, optional
        Explicit subset of the group's files. ``None`` selects the whole group.
        Relative selections are resolved against the upstream execution root.
    workspace_dir : pathlib.Path or None, optional
        Experiment hint carried by managed results; not part of execution identity.

    Notes
    -----
    This reference records lineage; the tool adapter must also pass these files
    to the native command. Products are referenced, not copied or fully hashed.
    Multiple downstream plans may reference the same upstream execution.
    """

    manifest_path: Path
    output_group: str
    execution_id: str | None = None
    paths: tuple[Path, ...] | None = None
    workspace_dir: Path | None = None


@dataclass(frozen=True)
class ExecutionPlan:
    """Describe a command for the shared executor without starting a process.

    Parameters
    ----------
    command : tuple of str
        Nonempty argument sequence beginning with an executable name or path.
        Each argument is a separate item; shell redirections are not interpreted.
    cwd : pathlib.Path
        Working directory for the child process. Tool-specific preparation
        supplies an absolute path; the parent working directory is unchanged.
    output_patterns : dict of str to str
        Product groups mapped to glob patterns relative to the workspace's
        ``products/`` directory. Every group must match at least one nonempty
        regular file for execution to succeed, for example
        ``{"sim": "events*.sim.gz"}``.
    metadata : dict of str to object, optional
        JSON-serializable tool-specific fields merged into the manifest.
        Defaults to an empty dictionary. Reserved execution-record keys such
        as ``status``, ``execution_id`` and ``upstream`` are rejected.
    upstream : tuple of ExecutionInput, optional
        Explicit upstream product selections, defaulting to no parents. Multiple
        inputs and multiple consumers are allowed; no linear stage order is
        imposed. Each upstream manifest is validated and snapshotted.
    environment : dict of str to str, optional
        Tool-only environment overrides, applied after setup-script execution.
        Recorded in the manifest; do not use for secrets. Defaults to none.

    Notes
    -----
    This is an executor extension interface. Normal users call ``Cosima`` or ``Revan``
    rather than constructing plans. Frozen dataclasses prevent field rebinding,
    but do not make nested dictionaries immutable.
    """

    command: tuple[str, ...]
    cwd: Path
    output_patterns: dict[str, str]
    metadata: dict[str, Any] = field(default_factory=dict)
    upstream: tuple[ExecutionInput, ...] = ()
    environment: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResult:
    """A successful tool execution and paths to its persistent records.

    Parameters
    ----------
    output_dir : pathlib.Path
        Absolute execution workspace directory.
    outputs : dict of str to tuple of pathlib.Path
        Product groups containing sorted absolute file paths. Cosima uses the
        ``"sim"`` group, which may contain multiple files.
    manifest_path : pathlib.Path
        Absolute root manifest path for managed executions, or standalone record.
        Use record to read this execution's status and metadata by ID.
    stdout_path : pathlib.Path or None
        Stdout log path, or None when empty and removed.
    stderr_path : pathlib.Path or None
        Absolute path to the stderr log, or None when empty and removed.
    returncode : int, optional
        Process return code, zero for results returned by the executor.
        Defaults to zero. Failed attempts raise ``ExecutionError`` instead.
    execution_id : str or None, optional
        Persistent UUID identifying this execution attempt independently of its
        directory name. ``None`` supports manually constructed legacy results.
        This is not a task ID: reruns receive different execution IDs.
    workspace_dir : pathlib.Path or None, optional
        Experiment root when managed by ``SimulationWorkspace``; otherwise none.

    Attributes
    ----------
    output_dir : pathlib.Path
        Data group directory with shared inputs/logs and operation products.
    outputs : dict of str to tuple of pathlib.Path
        Discovered output files, for example ``result.outputs["sim"]``.
    manifest_path : pathlib.Path
        Persistent metadata and validation record.
    stdout_path : pathlib.Path or None
        Retained stdout, or None if empty. Capture mode is recorded in logs.capture.
    stderr_path : pathlib.Path or None
        Retained stderr, or None if empty.
    returncode : int
        Zero when returned after successful execution and output checks.
    execution_id : str or None
        Execution identity stored in the manifest, or ``None`` for legacy objects.
    workspace_dir : pathlib.Path or None
        Experiment root for managed executions; ``None`` for standalone attempts.

    Notes
    -----
    A successful result establishes process success and the documented file
    checks, not the scientific validity of the data. It does not load simulation
    products into memory. Read the files only when needed for subsequent steps.
    """

    output_dir: Path
    outputs: dict[str, tuple[Path, ...]]
    manifest_path: Path
    stdout_path: Path | None
    stderr_path: Path | None
    returncode: int = 0
    execution_id: str | None = None
    workspace_dir: Path | None = None

    @property
    def record(self):
        """dict: This execution's record, resolved by ID in a central manifest.

        Returns a newly read dictionary. Other workspace executions do not
        change this result's identity. Legacy standalone manifests are supported.
        """
        from .provenance import read_execution
        return read_execution(self.manifest_path, self.execution_id)[1]

    def as_input(self, output_group, *, paths=None):
        """Select a product group for a downstream execution plan.

        Parameters
        ----------
        output_group : str
            Product group present in :attr:`outputs`, for example ``"sim"``.
        paths : iterable of str or pathlib.Path or None, optional
            Explicit subset, checked against the persisted group by the executor.
            ``None`` selects every file in the group.

        Returns
        -------
        ExecutionInput
            Reference to this manifest and the selected product group. The
            executor validates the persisted record when consuming it.

        Raises
        ------
        KeyError
            The requested group is absent from this result.
        """
        if output_group not in self.outputs:
            raise KeyError(output_group)
        return ExecutionInput(self.manifest_path, output_group, self.execution_id,
                              None if paths is None else tuple(Path(p) for p in paths),
                              self.workspace_dir)
