"""Publish stage (spec 3.2 stage 7): explore archives, detail rasters, site JSON and manifest, uploaded to R2 and
verified, from the finished grid, poles and validate stages. Every artefact is behind a marker; the stage may be
rerun after any crash or after the R2 configuration appears and continues where it stopped."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import shapely

from ..classes import ClassTable
from ..config import RegionConfig
from ..errors import PolesError
from ..extract import MARKER
from ..grid import Frame
from ..poles import SCENARIOS
from ..shell import require_tools
from ..validate import load_poles
from ..workspace import Workspace
from . import detail, r2, raster, sitedata, tiles

STAGE = "publish"


def _clear_markers(out: Path, log: logging.Logger) -> None:
    gone = [p for p in out.glob(f"*{MARKER}")]
    for p in gone:
        p.unlink()
    if gone:
        log.info("publish: forced, cleared %d sub-step marker(s)", len(gone))


def upload_set(ws: Workspace, region_id: str, snapshot: str) -> list[tuple[Path, str]]:
    """Every object the site fetches from R2, as (local file, immutable key) under the snapshot prefix.

    The site documents are not in here: they are committed to git, and publishing them is the manifest commit."""
    out, prefix = ws.dir(STAGE), f"{region_id}/{snapshot}"
    items = [(out / f"{s}.pmtiles", f"{prefix}/{s}.pmtiles") for s in SCENARIOS]
    # detail/<code>/<file> and nothing else: the one level is the key contract, and it keeps the directory's own
    # published.json bookkeeping out of the bucket.
    for p in sorted((out / "detail").glob("*/*")):
        if p.is_file() and p.suffix in (".png", ".json"):
            items.append((p, f"{prefix}/detail/{p.parent.name}/{p.name}"))
    val = ws.dir("validate")
    for name in ("report.json", "report.html", "contact-sheet.html"):
        items.append((val / name, f"{prefix}/validation/{name}"))
    return items


def _pipeline_commit(log: logging.Logger) -> str | None:
    """The commit that produced this publish, for the manifest. None when the pipeline runs outside a checkout
    (the container), which the manifest schema allows, and None on a dirty tree: a commit hash that does not
    describe the code that ran is worse than no hash at all."""
    def git(*args: str) -> str | None:
        try:
            out = subprocess.run(["git", *args], capture_output=True, text=True, timeout=10,
                                 cwd=Path(__file__).resolve().parent)
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout if out.returncode == 0 else None

    head = git("rev-parse", "HEAD")
    if head is None or not head.strip():
        return None
    dirty = git("status", "--porcelain")
    if dirty is None or dirty.strip():
        log.warning("publish: the working tree is dirty or unreadable, the manifest records no pipeline commit")
        return None
    return head.strip()


def _explore_rasters(cfg: RegionConfig, ws: Workspace, table: ClassTable, log: logging.Logger,
                     tools_log: Path) -> tuple[dict, dict, Path]:
    """One class raster and one PMTiles archive per scenario. Returns (per-scenario quantise stats, archives, and
    the path of the edge band in EPSG:4326, which the detail rasters mask with)."""
    out, grid_dir = ws.dir(STAGE), ws.dir("grid")
    frame = Frame.from_dict(json.loads((grid_dir / "frame.json").read_text(encoding="utf-8")))
    edge = raster.edge_polygon(ws.dir("fetch"))
    inside_tif, band_tif, band_wkb = raster.edge_masks(edge, frame, cfg.edge_mask_m, out, log, tools_log)
    stats, archives = {}, {}
    for s in SCENARIOS:
        cls_tif, stats_path = out / f"explore_{s}.tif", out / f"explore_{s}.json"
        if not (raster._done(cls_tif) and stats_path.exists()):
            raster._unmark(cls_tif)
            counts = raster.quantise(grid_dir / f"dist_{s}.tif", grid_dir / "land.tif", inside_tif, band_tif,
                                     cls_tif, table, log)
            stats_path.write_text(json.dumps(counts) + "\n", encoding="utf-8")
            raster._mark(cls_tif)
        stats[s] = json.loads(stats_path.read_text(encoding="utf-8"))
        merc = raster.warp_to_mercator(cls_tif, out / f"explore_{s}_3857.tif", log, tools_log)
        archives[s] = tiles.build(merc, out, s, log, tools_log)
    return stats, archives, band_wkb


def run(cfg: RegionConfig, ws: Workspace, log: logging.Logger) -> dict:
    if not ws.is_done("validate"):
        raise PolesError("publish needs a finished validate stage (validate/done.json is missing): run it first (#21)")
    require_tools(["gdal_rasterize", "gdalwarp", "gdal", "pmtiles"])
    out = ws.dir(STAGE)
    if ws.forced:
        _clear_markers(out, log)
    tools_log = out / "tools.log"
    t0 = time.monotonic()
    meta: dict = {}

    report = json.loads((ws.dir("validate") / "report.json").read_text(encoding="utf-8"))
    if "excluded" not in report:
        raise PolesError("validate/report.json has no excluded list; rerun validate")
    published = sitedata.apply_exclusions(load_poles(ws.dir("poles"), cfg.top_n), report["excluded"])
    meta["withheld"] = sum(u["withheld"] for s in SCENARIOS for u in published[s])
    table = ClassTable(cfg.class_table) if cfg.class_table else ClassTable()

    # 1. explore class rasters and archives, then 2. one detail raster per published pole. Both are local and
    # resumable, and both run before R2 is looked at, so a machine without the credentials still does the work.
    meta["raster"], meta["archives"], band_wkb = _explore_rasters(cfg, ws, table, log, tools_log)
    meta["detail"] = detail.run_detail(cfg, ws, published, table, shapely.from_wkb(band_wkb.read_bytes()), log)

    # 3. upload and verify
    r2cfg = r2.R2Config.from_env(os.environ)
    base = r2.ensure_bucket(r2cfg, log)
    items = upload_set(ws, cfg.id, ws.snapshot)
    meta["upload"] = r2.upload_tree(r2.s3_client(r2cfg), r2cfg.bucket, items, log)
    keys = [k for _, k in items]
    meta["verify"] = r2.verify_head(base, keys, [f"{cfg.id}/{ws.snapshot}/{s}.pmtiles" for s in SCENARIOS], log)
    meta["r2_base"] = base

    # 4. site documents, merged with what the site already holds
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    snapshot = json.loads((ws.dir("fetch") / "snapshot.json").read_text(encoding="utf-8"))
    units_meta = json.loads((ws.dir("poles") / "units.json").read_text(encoding="utf-8"))["units"]
    region = {"id": cfg.id, "name": cfg.name, "snapshot": ws.snapshot, "unit_level": cfg.unit_admin_level, "r2_base": base,
              "max_distance_m": cfg.max_distance_m, "edge_mask_m": cfg.edge_mask_m, "detail_res_m": cfg.detail_res_m,
              "detail_window_m": cfg.detail_window_m}
    site = sitedata.build(region, units_meta, published, table, meta["archives"], meta["detail"], meta["verify"],
                          snapshot["sources"], generated_at, _pipeline_commit(log))
    targets = [out / "site"] + ([ws.site_dir] if ws.site_dir else [])
    meta["site_files"] = [str(p) for target in targets for p in sitedata.write_site(site, Path(target), cfg.id, generated_at)]
    meta["site_dir"] = str(ws.site_dir) if ws.site_dir else None
    meta["seconds"] = round(time.monotonic() - t0, 1)
    log.info("publish: done in %.0f s, %d withheld, %s", meta["seconds"], meta["withheld"],
             {s: a["bytes"] for s, a in meta["archives"].items()})
    return meta
