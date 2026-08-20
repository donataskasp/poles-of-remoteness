"""Subprocess wrapper: logs the exact command, measures wall time and peak RSS, fails loudly."""
from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path


class ToolError(RuntimeError):
    """A required CLI tool is missing or exited non-zero. The message carries the command."""


@dataclass
class CmdResult:
    argv: list[str]
    returncode: int
    duration_s: float
    max_rss_bytes: int


def rss_bytes(ru_maxrss: int) -> int:
    """ru_maxrss is bytes on macOS and kilobytes on Linux."""
    return ru_maxrss if sys.platform == "darwin" else ru_maxrss * 1024


def require_tools(names: list[str]) -> None:
    missing = [n for n in names if shutil.which(n) is None]
    if missing:
        raise ToolError(f"missing tool(s) on PATH: {', '.join(missing)}")


def run_cmd(argv, log: logging.Logger, *, cwd=None, env=None, stdin_path=None, stdout_path=None, stderr_path=None) -> CmdResult:
    """Run argv to completion. stdout/stderr go to files when given (stderr appended), else stdout is
    discarded and stderr is captured for the error message. Peak RSS comes from wait4 on this child."""
    argv = [str(a) for a in argv]
    redirect = (f" < {stdin_path}" if stdin_path else "") + (f" > {stdout_path}" if stdout_path else "")
    log.info("$ %s%s", shlex.join(argv), redirect)
    t0 = time.monotonic()
    with ExitStack() as stack:
        stdin = stack.enter_context(open(stdin_path, "rb")) if stdin_path else subprocess.DEVNULL
        stdout = stack.enter_context(open(stdout_path, "wb")) if stdout_path else subprocess.DEVNULL
        if stderr_path:
            stderr = stack.enter_context(open(stderr_path, "a+b"))  # a+b, not ab: the failure path reads the tail back
            stderr.write(f"\n$ {shlex.join(argv)}\n".encode())
            stderr.flush()
        else:
            stderr = stack.enter_context(tempfile.TemporaryFile())
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=stdin, stdout=stdout, stderr=stderr)
        _, status, ru = os.wait4(proc.pid, 0)
        proc.returncode = os.waitstatus_to_exitcode(status)
        duration = time.monotonic() - t0
        result = CmdResult(argv, proc.returncode, round(duration, 1), rss_bytes(ru.ru_maxrss))
        if proc.returncode != 0:
            stderr.flush()
            size = stderr.seek(0, os.SEEK_END)
            stderr.seek(max(0, size - 4000))
            tail = stderr.read().decode("utf-8", "replace").strip()
            raise ToolError(f"command failed with exit {proc.returncode}: {shlex.join(argv)}\n{tail}")
    log.info("done in %.0fs, peak RSS %.2f GB: %s", result.duration_s, result.max_rss_bytes / 1e9, argv[0])
    return result


def dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file())
