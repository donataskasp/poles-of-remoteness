"""Runs stages in order with skip, force, and per-stage resource accounting."""
from __future__ import annotations

import logging
import resource
import time

from .config import RegionConfig
from .shell import dir_size, rss_bytes
from .stages import ORDER
from .workspace import Workspace


def run_pipeline(cfg: RegionConfig, ws: Workspace, log: logging.Logger, *, only: str | None, force: bool, registry: dict) -> list[str]:
    """Returns the names of the stages that actually ran. Stops at the first unimplemented stage."""
    names = [only] if only else list(ORDER)
    executed: list[str] = []
    for name in names:
        fn = registry.get(name)
        if fn is None:
            log.info("stopping: stage '%s' is not implemented yet", name)
            break
        if ws.is_done(name) and not force:
            log.info("skip %s: done at %s", name, ws.meta(name).get("finished_at"))
            continue
        ws.clear_done(name)
        log.info("=== stage %s ===", name)
        t0 = time.monotonic()
        meta = fn(cfg, ws, log) or {}
        meta.update({
            "duration_s": round(time.monotonic() - t0, 1),
            "peak_rss_self_bytes": rss_bytes(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
            "peak_rss_children_cumulative_bytes": rss_bytes(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss),
            "disk_bytes": dir_size(ws.dir(name)),
        })
        ws.mark_done(name, meta)
        executed.append(name)
        log.info("=== %s done in %.0fs, %.2f GB on disk ===", name, meta["duration_s"], meta["disk_bytes"] / 1e9)
    return executed
