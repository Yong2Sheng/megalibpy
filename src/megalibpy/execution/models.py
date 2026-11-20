"""Descriptions of commands and completed executions."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
        Defaults to an empty dictionary. Internal callers must avoid reserved
        execution-record keys such as ``status`` or ``returncode``.

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
