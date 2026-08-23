#!/usr/bin/env python3
"""Site JSON for local development from a finished local publish run, no R2 needed.

Mirrors the site-document step of the publish stage (poles/publish/__init__.py, step 4) with a local
r2_base and a placeholder verification block. Output goes to dev/out/site/ (gitignored); the dev server
serves it under /data/. Never point --out at site/data: that directory is written by the pipeline only.

Usage (from the repository root):
  pipeline/.venv/bin/python dev/site-json.py --region europe --snapshot 2026-08-19
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from poles.classes import ClassTable
from poles.config import load_region
from poles.publish import sitedata, tiles
from poles.validate import load_poles
from poles.workspace import Workspace, write_text_atomic

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ("A", "B")
# regions.schema.json requires an https r2_base, and rightly so: the published site is https and a
# plain-http base would be blocked as mixed content. Development needs the http dev server, so the
# documents are built and validated with this production-shaped placeholder and the local base is
# substituted afterwards. The pipeline stays untouched; nothing under dev/out/ is ever published.
PLACEHOLDER_R2_BASE = "https://dev.invalid/r2"


def set_r2_base(path: Path, base: str) -> None:
    """Rewrite r2_base on every region entry of a written regions.json (a list) or manifest.json (a map).

    Every entry under dev/out/ was written by this script, so they all point at the same dev server.
    """
    doc = json.loads(path.read_text(encoding="utf-8"))
    entries = doc["regions"]
    for entry in entries if isinstance(entries, list) else entries.values():
        entry["r2_base"] = base
    write_text_atomic(path, json.dumps(doc, ensure_ascii=False, indent=1) + "\n")


def archive_info(pub: Path, scenario: str, log: logging.Logger) -> dict:
    p = pub / f"{scenario}.pmtiles"
    show = p.parent / (p.name + ".show.txt")
    info = tiles.parse_show(show.read_text(encoding="utf-8")) if show.exists() else tiles.pmtiles_info(p, log)
    return {"key_name": p.name, "bytes": p.stat().st_size, "tiles": info["tiles"],
            "min_zoom": info["min_zoom"], "max_zoom": info["max_zoom"]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", required=True)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--work", type=Path, default=ROOT / "work")
    ap.add_argument("--r2-base", default="http://localhost:8000/r2")
    ap.add_argument("--out", type=Path, default=ROOT / "dev" / "out" / "site")
    a = ap.parse_args()
    if a.out.resolve() == (ROOT / "site" / "data").resolve():
        raise SystemExit("refusing to write into site/data: the pipeline owns it")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger("dev")

    cfg = load_region(ROOT / "pipeline" / "regions" / f"{a.region}.yaml")
    ws = Workspace(a.work, a.region, a.snapshot)
    pub = ws.dir("publish")
    report = json.loads((ws.dir("validate") / "report.json").read_text(encoding="utf-8"))
    published = sitedata.apply_exclusions(load_poles(ws.dir("poles"), cfg.top_n), report["excluded"])
    table = ClassTable(cfg.class_table) if cfg.class_table else ClassTable()
    archives = {s: archive_info(pub, s, log) for s in SCENARIOS}
    pngs = sorted((pub / "detail").rglob("*.png"))
    detail_meta = {"count": len(pngs), "bytes": sum(p.stat().st_size for p in pngs)}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    verify_meta = {"at": now, "keys": 0, "range_ok": 0}
    snapshot = json.loads((ws.dir("fetch") / "snapshot.json").read_text(encoding="utf-8"))
    units_meta = json.loads((ws.dir("poles") / "units.json").read_text(encoding="utf-8"))["units"]
    region = {"id": cfg.id, "name": cfg.name, "names": cfg.names, "snapshot": ws.snapshot,
              "unit_level": cfg.unit_admin_level, "r2_base": PLACEHOLDER_R2_BASE,
              "max_distance_m": cfg.max_distance_m, "edge_mask_m": cfg.edge_mask_m,
              "detail_res_m": cfg.detail_res_m, "detail_window_m": cfg.detail_window_m}
    site = sitedata.build(region, units_meta, published, table, archives, detail_meta, verify_meta,
                          snapshot["sources"], now, None)
    # write_site merges with, and revalidates, whatever is already there, so a previous run's substituted
    # base has to go back to the placeholder before the merge and forward to the dev base after it.
    regions_json = a.out / "regions.json"
    if regions_json.exists():
        set_r2_base(regions_json, PLACEHOLDER_R2_BASE)
    written = sitedata.write_site(site, a.out, cfg.id, now)
    set_r2_base(regions_json, a.r2_base)
    set_r2_base(a.out / "manifest.json", a.r2_base)
    log.info("wrote %d files under %s", len(written), a.out)


if __name__ == "__main__":
    main()
