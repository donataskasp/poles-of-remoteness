"""Per-region, per-snapshot working directories and stage done-markers."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

DONE = "done.json"


class Workspace:
    """work/<region>/<snapshot>/<stage>/ plus work/shared/ for region-independent downloads."""

    def __init__(self, root: str | Path, region: str, snapshot: str):
        self.root = Path(root)
        self.region = region
        self.snapshot = snapshot
        self.base = self.root / region / snapshot
        self.shared = self.root / "shared"

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
        target = self.dir(stage) / DONE
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(target)

    def meta(self, stage: str) -> dict:
        return json.loads((self.base / stage / DONE).read_text(encoding="utf-8"))

    def clear_done(self, stage: str) -> None:
        marker = self.base / stage / DONE
        if marker.exists():
            marker.unlink()
