"""Execution failures retain the locations of diagnostic records."""

from pathlib import Path


class ExecutionError(RuntimeError):
    """A preparation, process, or output-validation failure.

    ``manifest_path`` records the failure; logs are beside it in ``logs/``.
    ``returncode`` is absent when no process was started.
    """

    def __init__(self, message: str, manifest_path: Path, returncode=None):
        super().__init__(f"{message} (manifest: {manifest_path})")
        self.manifest_path = manifest_path
        self.returncode = returncode
