"""An exclusive directory for one execution attempt."""

from dataclasses import dataclass, field
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
    owner: object = field(default=None, repr=False)
    execution_id: str | None = None
    operation: str | None = None
    number: int = 1
    product_folder: str = "products"

    @property
    def inputs_dir(self):
        return self.root / "inputs"

    @property
    def logs_dir(self):
        return self.root / "logs"

    @property
    def products_dir(self):
        return self.root / self.product_folder

    def log_path(self, name):
        if self.owner is None:
            return self.logs_dir / name
        return self.logs_dir / f"{self.operation}-{self.number:03d}.{name}"

    def snapshot(self, name, content):
        """Reuse byte-identical immutable input snapshots within a data group."""
        from hashlib import sha256
        from contextlib import nullcontext
        with self.owner._locked() if self.owner is not None else nullcontext():
            path = self.inputs_dir / name
            if path.exists() and path.read_bytes() != content:
                path = path.with_name(f"{path.stem}-{sha256(content).hexdigest()}{path.suffix}")
            if not path.exists():
                with path.open("xb") as stream:
                    stream.write(content)
            return path

    def save(self, record):
        from .provenance import write_manifest
        if self.owner is None:
            write_manifest(self.manifest_path, record)
        else:
            self.owner._save_execution(self, record)

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
        return self.root / "manifest.json" if self.owner is None else self.owner.index_path
