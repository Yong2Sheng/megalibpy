"""Compatibility imports for the former ``Run`` configuration class."""

from .run_config import RunConfig

# An alias preserves constructor, isinstance, subclass, and legacy import behavior.
Run = RunConfig

__all__ = ["Run", "RunConfig"]
