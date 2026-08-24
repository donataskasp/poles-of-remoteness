"""Thin osmium-tool wrapper: the exact command is logged and any failure names it."""
from __future__ import annotations

import logging
from pathlib import Path

from .shell import CmdResult, run_cmd


def osmium(args: list, log: logging.Logger, stderr_path: Path | None = None, stdout_path: Path | None = None) -> CmdResult:
    return run_cmd(["osmium", *args], log, stderr_path=stderr_path, stdout_path=stdout_path)
