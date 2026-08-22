"""Publish stage (spec 3.2 stage 7): explore archives, detail rasters, site JSON and manifest, uploaded to R2 and
verified, from the finished grid, poles and validate stages. Every artefact is behind a marker; the stage may be
rerun after any crash or after the R2 configuration appears and continues where it stopped."""
from __future__ import annotations

import json
import logging
import os
import shutil
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
from ..workspace import Workspace, write_text_atomic
from . import detail, r2, raster, sitedata, tiles

STAGE = "publish"
INPUTS = "inputs.json"


def _fingerprint(path: Path) -> dict | None:
    """Size and modification time of one input, or None when it is not there. Cheap enough to take on every
    run, and it changes whenever the file is rewritten, which is all the stamp has to notice."""
    try:
        st = path.stat()
    except OSError:
        return None
    return {"bytes": st.st_size, "mtime_ns": st.st_mtime_ns}


def _explore_inputs(cfg: RegionConfig, ws: Workspace, table: ClassTable) -> dict:
    """Everything the explore chain reads, as plain data: the class table and the edge mask width the rasters
    are quantised and banded with, plus every grid raster and source polygon behind them. Paths are relative
    to the work directory so the stamp says the same thing on another machine."""
    grid_dir = ws.dir("grid")
    sources = [grid_dir / f"dist_{s}.tif" for s in SCENARIOS] + [grid_dir / "land.tif"]
    sources += raster.edge_poly_paths(ws.dir("fetch"))
    return {"class_edges": list(table.edges), "edge_mask_m": cfg.edge_mask_m,
            "files": {p.relative_to(ws.base).as_posix(): _fingerprint(p) for p in sources}}


def _stamp_change(old: dict, wanted: dict) -> str | None:
    """The first key of the stamp that no longer matches, or None when the inputs are the ones on record."""
    for key in ("class_edges", "edge_mask_m"):
        if old.get(key) != wanted[key]:
            return key
    old_files = old.get("files") or {}
    for name, fp in wanted["files"].items():
        if old_files.get(name) != fp:
            return name
    gone = sorted(set(old_files) - set(wanted["files"]))
    return gone[0] if gone else None


def _reset_explore(ws: Workspace, log: logging.Logger, why: str) -> None:
    """Take the whole explore layer back to nothing: every sub-step marker and every tile directory.

    The tile directories have to go with the markers. `gdal raster tile --resume` generates only missing
    files, so a directory left standing would hand the packer the previous run's pixels while every archive,
    count and byte total around them was written afresh: an archive that looks new and is not."""
    out = ws.dir(STAGE)
    markers = sorted(out.glob(f"*{MARKER}"))
    dirs = sorted(p for p in out.glob("tiles_*") if p.is_dir())
    for p in markers:
        p.unlink()
    for d in dirs:
        shutil.rmtree(d)
    log.info("publish: %s, cleared %d marker(s) and %d tile directory(ies)", why, len(markers), len(dirs))


def _stamp_explore_inputs(cfg: RegionConfig, ws: Workspace, table: ClassTable, log: logging.Logger) -> None:
    """One reset rule for the explore chain, run before any of it is built.

    No marker records what its artefact was built from, so a changed class table, a wider edge mask or a
    rebuilt grid raster would otherwise leave the rasters and tiles alone while the site documents published
    the new numbers over them. A stamp that is not there at all is adopted rather than distrusted: the
    artefacts of a finished run predate the stamp, and rebuilding them to learn that nothing changed would
    cost a day."""
    out = ws.dir(STAGE)
    stamp, wanted = out / INPUTS, _explore_inputs(cfg, ws, table)
    if ws.forced:
        _reset_explore(ws, log, "forced")
    elif stamp.exists():
        try:
            old = json.loads(stamp.read_text(encoding="utf-8"))
        except ValueError:
            old = {}
        if not isinstance(old, dict):
            old = {}
        changed = _stamp_change(old, wanted)
        if changed:
            _reset_explore(ws, log, f"{changed} changed since the last run")
    elif any(out.glob(f"*{MARKER}")) or any(out.glob("tiles_*")):
        log.info("publish: no %s beside the artefacts already in %s, adopting them as built from the current "
                 "inputs", INPUTS, out.name)
    write_text_atomic(stamp, json.dumps(wanted, indent=1, sort_keys=True) + "\n")


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
        raise PolesError("publish needs a finished validate stage (validate/done.json is missing): run it first")
    require_tools(["gdal_rasterize", "gdalwarp", "gdal", "pmtiles"])
    out = ws.dir(STAGE)
    tools_log = out / "tools.log"
    t0 = time.monotonic()
    meta: dict = {}

    report = json.loads((ws.dir("validate") / "report.json").read_text(encoding="utf-8"))
    if "excluded" not in report:
        raise PolesError("validate/report.json has no excluded list; rerun validate")
    published = sitedata.apply_exclusions(load_poles(ws.dir("poles"), cfg.top_n), report["excluded"])
    meta["withheld"] = sum(u["withheld"] for s in SCENARIOS for u in published[s])
    table = ClassTable(cfg.class_table) if cfg.class_table else ClassTable()
    _stamp_explore_inputs(cfg, ws, table, log)

    # 1. explore class rasters and archives, then 2. one detail raster per published pole. Both are local and
    # resumable, and both run before R2 is looked at, so a machine without the credentials still does the work.
    meta["raster"], meta["archives"], band_wkb = _explore_rasters(cfg, ws, table, log, tools_log)
    meta["detail"] = detail.run_detail(cfg, ws, published, table, shapely.from_wkb(band_wkb.read_bytes()), log)

    # 3. upload and verify
    r2cfg = r2.R2Config.from_env(os.environ)
    base = r2.ensure_bucket(r2cfg, log)
    items = upload_set(ws, cfg.id, ws.snapshot)
    meta["upload"] = r2.upload_tree(r2.s3_client(r2cfg), r2cfg.bucket, items, log, forced=ws.forced)
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
