"""An exclusive directory for one execution attempt."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Workspace:
    """An execution directory containing inputs, logs, products, and a manifest.

    Parameters
    ----------
    root : pathlib.Path
        Workspace directory. Prefer :meth:`create` to establish its structure.
    """

    root: Path

    @classmethod
    def create(cls, output_dir):
        """Create a new workspace without reusing an existing directory.

        Parameters
        ----------
        output_dir : str or pathlib.Path
            New directory path. ``~`` is expanded and relative paths are
            resolved against the current working directory.

        Returns
        -------
        Workspace
            Workspace with an absolute root and empty input/log/product folders.

        Raises
        ------
        FileExistsError
            The target directory already exists, including an empty directory.
        OSError
            A directory cannot be created. A partially created workspace may
            remain if a filesystem error occurs during initialization.
        """
        root = Path(output_dir).expanduser().resolve()
        # Existing directories are never reused based solely on output existence.
        root.mkdir(parents=True, exist_ok=False)
        for name in ("inputs", "logs", "products"):
            (root / name).mkdir()
        return cls(root)

    @property
    def manifest_path(self):
        """pathlib.Path: Absolute path to ``manifest.json`` in this workspace."""
        return self.root / "manifest.json"
