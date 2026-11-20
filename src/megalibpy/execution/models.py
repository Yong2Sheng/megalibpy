"""Descriptions of commands and completed executions."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExecutionPlan:
    """A command, its working directory, and expected output glob patterns."""

    command: tuple[str, ...]
    cwd: Path
    output_patterns: dict[str, str]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResult:
    """A successful execution and paths to its persistent records."""

    output_dir: Path
    outputs: dict[str, tuple[Path, ...]]
    manifest_path: Path
    stdout_path: Path
    stderr_path: Path
    returncode: int = 0
