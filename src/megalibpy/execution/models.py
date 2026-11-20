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
        Path to a successful upstream manifest, including legacy records without
        an execution ID. The executor archives this record before launching.
    output_group : str
        Explicit product group to consume, such as ``"sim"`` or ``"tra"``.
    execution_id : str or None, optional
        Expected upstream identity. Results supply their ID automatically;
        ``None`` allows references to legacy records without an ID.

    Notes
    -----
    This reference records lineage; the tool adapter must also pass these files
    to the native command. Products are referenced, not copied or fully hashed.
    Multiple downstream plans may reference the same upstream execution.
    """

    manifest_path: Path
    output_group: str
    execution_id: str | None = None


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

    Notes
    -----
    This is an executor extension interface. Normal users call ``Cosima``
    rather than constructing plans. Frozen dataclasses prevent field rebinding,
    but do not make nested dictionaries immutable.
    """

    command: tuple[str, ...]
    cwd: Path
    output_patterns: dict[str, str]
    metadata: dict[str, Any] = field(default_factory=dict)
    upstream: tuple[ExecutionInput, ...] = ()


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
        Absolute path to the JSON manifest, whose status is ``"succeeded"``.
    stdout_path : pathlib.Path
        Absolute path to the native program and initialization stdout log.
    stderr_path : pathlib.Path
        Absolute path to the corresponding stderr log.
    returncode : int, optional
        Process return code, zero for results returned by the executor.
        Defaults to zero. Failed attempts raise ``ExecutionError`` instead.
    execution_id : str or None, optional
        Persistent UUID identifying this execution attempt independently of its
        directory name. ``None`` supports manually constructed legacy results.
        This is not a task ID: reruns receive different execution IDs.

    Attributes
    ----------
    output_dir : pathlib.Path
        Execution workspace, containing ``inputs/``, ``logs/``, and ``products/``.
    outputs : dict of str to tuple of pathlib.Path
        Discovered output files, for example ``result.outputs["sim"]``.
    manifest_path : pathlib.Path
        Persistent metadata and validation record.
    stdout_path : pathlib.Path
        Standard-output log, streamed directly to disk.
    stderr_path : pathlib.Path
        Standard-error log, streamed directly to disk.
    returncode : int
        Zero when returned after successful execution and output checks.
    execution_id : str or None
        Execution identity stored in the manifest, or ``None`` for legacy objects.

    Notes
    -----
    A successful result establishes process success and the documented file
    checks, not the scientific validity of the data. It does not load simulation
    products into memory. Read the files only when needed for subsequent steps.
    """

    output_dir: Path
    outputs: dict[str, tuple[Path, ...]]
    manifest_path: Path
    stdout_path: Path
    stderr_path: Path
    returncode: int = 0
    execution_id: str | None = None

    def as_input(self, output_group):
        """Select a product group for a downstream execution plan.

        Parameters
        ----------
        output_group : str
            Product group present in :attr:`outputs`, for example ``"sim"``.

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
        return ExecutionInput(self.manifest_path, output_group, self.execution_id)
