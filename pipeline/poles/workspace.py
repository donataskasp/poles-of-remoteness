"""Per-region, per-snapshot working directories and stage done-markers."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

DONE = "done.json"


def write_text_atomic(path: Path, text: str) -> None:
    """Write through a temp file beside the target and rename it over: the target is either the old text or
    the new one, never a short file. Every marker, stamp and sidecar the pipeline reads back as "this is
    finished" goes this way, because a write interrupted part way (a full disk raises after leaving a few
    bytes) would otherwise look complete to the next run."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class Workspace:
    """work/<region>/<snapshot>/<stage>/ plus work/shared/ for region-independent downloads."""

    def __init__(self, root: str | Path, region: str, snapshot: str):
        self.root = Path(root)
        self.region = region
        self.snapshot = snapshot
        self.base = self.root / region / snapshot
        self.shared = self.root / "shared"
        self.forced = False  # set by run_pipeline: a stage with its own sub-caches clears them when forced
        # Set by the CLI: where publish copies the site JSON. None keeps it under the work directory only.
        self.site_dir: Path | None = None

    def dir(self, stage: str) -> Path:
        d = self.base / stage
        d.mkdir(parents=True, exist_ok=True)
        return d

    def shared_dir(self) -> Path:
        self.shared.mkdir(parents=True, exist_ok=True)
        return self.shared

    def is_done(self, stage: str) -> bool:
        return (self.base / stage / DONE).is_file()

    def mark_done(self, stage: str, meta: dict) -> None:
        payload = {
            "stage": stage,
            "region": self.region,
            "snapshot": self.snapshot,
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **meta,
        }
        write_text_atomic(self.dir(stage) / DONE, json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def meta(self, stage: str) -> dict:
        return json.loads((self.base / stage / DONE).read_text(encoding="utf-8"))

    def clear_done(self, stage: str) -> None:
        marker = self.base / stage / DONE
        if marker.exists():
            marker.unlink()
