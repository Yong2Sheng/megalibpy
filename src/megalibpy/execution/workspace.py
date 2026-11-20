"""An exclusive directory for one execution attempt."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Workspace:
    root: Path

    @classmethod
    def create(cls, output_dir):
        root = Path(output_dir).expanduser().resolve()
        # Existing directories are never reused based solely on output existence.
        root.mkdir(parents=True, exist_ok=False)
        for name in ("inputs", "logs", "products"):
            (root / name).mkdir()
        return cls(root)

    @property
    def manifest_path(self):
        return self.root / "manifest.json"
