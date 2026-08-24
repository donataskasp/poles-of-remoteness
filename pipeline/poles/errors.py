"""Failures a stage raises on purpose. The CLI prints them without a traceback and exits 1."""
from __future__ import annotations


class PolesError(RuntimeError):
    """A stage found a condition that must stop the run (bad data, failed validation, broken invariant)."""
