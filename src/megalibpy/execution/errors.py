"""Execution failures retain the locations of diagnostic records."""

from pathlib import Path


class ExecutionError(RuntimeError):
    """A preparation, process, or output-validation failure.

    Parameters
    ----------
    message : str
        Human-readable failure description. The exception's display text also
        includes the manifest path.
    manifest_path : pathlib.Path
        Path to the execution's persistent JSON record. Standard-output and
        logs are located through the selected execution record.
    returncode : int or None, optional
        Native process return code, or ``None`` if no process was started.
        Zero is possible when process execution succeeded but output validation
        failed. On POSIX, a negative value indicates termination by a signal.

    execution_id : str or None, optional
        Exact failed execution ID in a central workspace manifest; default none.

    Attributes
    ----------
    manifest_path : pathlib.Path
        Record containing the final status, error description, and available
        command and input metadata.
    execution_id : str or None
        ID selecting this failure within the root manifest.
    returncode : int or None
        Process outcome as described above. Defaults to ``None``.

    Notes
    -----
    The original preparation or subprocess exception is available through
    ``error.__cause__``. Argument errors and failures creating the initial
    workspace may be raised directly before a manifest exists.
    """

    def __init__(self, message: str, manifest_path: Path, returncode=None, execution_id=None):
        super().__init__(f"{message} (manifest: {manifest_path}, execution: {execution_id})")
        self.manifest_path = manifest_path
        self.returncode = returncode
        self.execution_id = execution_id
