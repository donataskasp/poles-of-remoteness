"""Stage validate (spec 6): every published pole is re-derived by an independent path; any blocking failure stops the run.

The seven checks live in `checks.py` and know nothing about each other. This module runs them in order,
decides what blocks, and writes the three files an owner reads: `report.json`, `report.html` and
`contact-sheet.html`.

One class of failure is a fact about the data rather than a bug: a pole whose nearest road may simply be
outside the extract (an island in the Alboran Sea, with Morocco beyond the data edge). Check 3 finds those,
and the stage excludes them instead of stopping: they are listed in `report.json` under `excluded`, marked
on the contact sheet, and skipped by every stage after this one. Everything else that blocks still stops
the run, after the three files are written.
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import replace
from pathlib import Path

import rasterio
from shapely.ops import unary_union

from ..config import RegionConfig
from ..errors import PolesError
from ..extract import MARKER
from ..grid import TILE, Frame, build_land_mask, create_raster, rasterize, tiled_edt, write_float_tif
from ..poles import MIN_WATER_M2, SCENARIOS, Prepared, UnitJob, prepare, search_unit, validate_poles_json
from ..poly import parse_poly
from ..roads import RoadTiles
from ..units import rasterize_units
from ..workspace import Workspace
from . import checks
from .report import write_contact_sheet, write_report_html, write_report_json

STAGE = "validate"
# Check 4 only compares the winner, but the shifted grid can promote a different candidate, so the rerun
# keeps a few: enough to see what moved, far cheaper than repeating a full top_n search.
SHIFT_TOP_N = 3


class ValidationFailed(PolesError):
    """A blocking check failed. The report files are written before this is raised."""


def _done(path: Path) -> bool:
    return path.exists() and path.with_name(path.name + MARKER).exists()


def _mark(path: Path) -> None:
    path.with_name(path.name + MARKER).touch()


def _clear_markers(out: Path, log: logging.Logger) -> None:
    """A forced run recomputes: drop the sub-step markers, the way the poles stage drops its result cache."""
    gone = [p for p in out.glob(f"*{MARKER}")]
    for p in gone:
        p.unlink()
    if gone:
        log.info("validate: forced, cleared %d sub-step marker(s)", len(gone))


def load_poles(poles_dir: Path, top_n: int) -> dict[str, list[dict]]:
    """A.json and B.json, checked for shape before any check reads them: a malformed record must name its
    file here rather than surface as a KeyError from inside check 3."""
    out = {}
    for scenario in SCENARIOS:
        path = poles_dir / f"{scenario}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PolesError(f"{path}: unreadable ({exc}); rerun the poles stage") from exc
        try:
            validate_poles_json(data, top_n)
        except (ValueError, KeyError, TypeError) as exc:
            raise PolesError(f"{path}: not a valid poles file ({exc}); rerun the poles stage") from exc
        out[scenario] = data
    return out


def edge_exclusions(results: list[checks.CheckResult], poles: dict[str, list[dict]]) -> tuple[list[checks.CheckResult], list[dict]]:
    """Turn every failing check-3 result into an exclusion.

    A pole closer to the edge of the extract than to its nearest road is not a broken search: the road that
    would beat it may be a few kilometres away in a country we did not download. Dropping the pole is the
    honest answer, so the result stays in the report as a warning and the pole travels on in `excluded`."""
    by_rank = {(s, e["unit"], p["rank"]): p for s, entries in poles.items() for e in entries for p in e["poles"]}
    kept: list[checks.CheckResult] = []
    excluded: list[dict] = []
    for r in results:
        if r.check != "edge_bound" or r.passed:
            kept.append(r)
            continue
        pole = by_rank.get((r.scenario, r.unit, r.details.get("rank")))
        if pole is None:
            raise checks.ChecksError(f"edge_bound failed for {r.unit} {r.scenario} #{r.details.get('rank')}, "
                                     "which is not in the published poles")
        excluded.append({"unit": r.unit, "scenario": r.scenario, "rank": pole["rank"], "lat": pole["lat"],
                         "lon": pole["lon"], "dist_m": pole["dist_m"], "details": dict(r.details)})
        kept.append(replace(r, blocking=False, details={**r.details, "excluded": True}))
    return kept, excluded


def shift_results(poles: dict[str, list[dict]], shifted: dict[tuple[str, str], dict | None],
                  excluded: list[dict]) -> list[checks.CheckResult]:
    """Check 4 read off the shifted winners, one result per unit and scenario.

    A unit whose winner was excluded is compared but does not block: the shifted grid re-runs the same
    search over the same incomplete road data, so its winner is the same near-the-edge point, and asking
    the two to agree says nothing about the poles we are actually going to publish."""
    dropped = {(e["scenario"], e["unit"], e["rank"]) for e in excluded}
    out = []
    for scenario in SCENARIOS:
        for entry in poles[scenario]:
            if not entry["poles"]:
                continue
            top = entry["poles"][0]
            r = checks.grid_shift_compare(entry["unit"], scenario, top, shifted.get((scenario, entry["unit"])))
            if (scenario, entry["unit"], top["rank"]) in dropped:
                r = replace(r, blocking=False, details={**r.details, "excluded_winner": True})
            out.append(r)
    return out


def _shift_windows(windows: dict[str, tuple[int, int, int, int]], frame: Frame,
                   pad: int = 1) -> dict[str, tuple[int, int, int, int]]:
    """The poles stage's per-unit raster windows, one cell wider each way.

    Half a cell of shift moves a unit's tight box by at most one cell in each direction, so a cell of the
    unit cannot fall outside the padded window; without the padding a border cell would be dropped, and
    the search would compare two different sets of candidate cells."""
    out = {}
    for code, (row_off, col_off, height, width) in windows.items():
        r0, c0 = max(0, row_off - pad), max(0, col_off - pad)
        r1, c1 = min(frame.height, row_off + height + pad), min(frame.width, col_off + width + pad)
        out[code] = (r0, c0, r1 - r0, c1 - c0)
    return out


def shifted_poles(cfg: RegionConfig, ws: Workspace, prepared: Prepared, log: logging.Logger) -> dict[tuple[str, str], dict | None]:
    """Check 4: recompute the grid half a cell off in both axes and re-run the search for each unit.

    Everything here is stage-1 sized (a full-frame rasterize, a full-frame distance transform, a land mask
    and a unit raster), so every piece is guarded by an `.ok` marker and a crash resumes at the first one
    missing. The finished winners are a marker of their own: a rerun that already has them skips the lot."""
    out, classify_dir = ws.dir(STAGE), ws.dir("classify")
    tools_log = out / "tools.log"
    winners_json = out / "shifted_winners.json"
    if _done(winners_json):
        log.info("shifted grid: reusing %s", winners_json.name)
        stored = json.loads(winners_json.read_text(encoding="utf-8"))
        return {(k.split("/", 1)[0], k.split("/", 1)[1]): v for k, v in stored.items()}
    f = prepared.frame
    shifted = Frame(f.crs, f.res, f.x0 + f.res / 2, f.y1 + f.res / 2, f.width, f.height)
    (out / "frame_shift.json").write_text(json.dumps(shifted.to_dict(), indent=2) + "\n", encoding="utf-8")
    overlap = math.ceil(cfg.max_distance_m / cfg.coarse_res_m)
    workers = int(os.environ.get("POLES_WORKERS", "0")) or None
    for s in SCENARIOS:
        dist_tif = out / f"dist_{s}_shift.tif"
        if _done(dist_tif):
            continue
        t0 = time.monotonic()
        mask_tif = out / f"roads_{s}_shift.tif"
        create_raster(shifted, mask_tif)
        rasterize(classify_dir / f"roads_{s}.fgb", f"roads_{s}", mask_tif, log, tools_log, burn=1, all_touched=True)
        with rasterio.open(mask_tif) as ds:
            mask = ds.read(1).astype(bool)
        dist = tiled_edt(mask, cfg.coarse_res_m, overlap, TILE, workers, max_m=float(cfg.max_distance_m))
        del mask
        write_float_tif(dist_tif, dist, shifted)
        del dist
        _mark(dist_tif)
        log.info("shifted grid: scenario %s distance raster in %.0fs", s, time.monotonic() - t0)
    land_tif, units_tif = out / "land_shift.tif", out / "units_shift.tif"
    if not _done(units_tif):
        t0 = time.monotonic()
        build_land_mask(ws.shared_dir() / "land.vrt", ws.dir("extract") / "water.vrt", shifted, land_tif,
                        MIN_WATER_M2, log, out)
        rasterize_units(ws.dir("poles") / "units.fgb", shifted, land_tif, units_tif, log, out)
        _mark(units_tif)
        # build_land_mask reprojects the water polygons into the stage directory (3.8 GB at the Europe
        # extract) and rebuilds them whenever it runs again, so nothing needs them after this.
        (out / "water_proj.fgb").unlink(missing_ok=True)
        log.info("shifted grid: land and unit rasters in %.0fs", time.monotonic() - t0)
    prep_shift = replace(prepared, units=[], frame=shifted, units_tif=units_tif,
                         windows=_shift_windows(prepared.windows, shifted))
    jobs = [UnitJob(cfg, prep_shift, u, s, out / f"dist_{s}_shift.tif", SHIFT_TOP_N, ws.base / "log.txt")
            for s in SCENARIOS for u in sorted(prepared.units, key=lambda u: -u.cells)]
    pool_workers = int(os.environ.get("POLES_WORKERS", "0")) or 4
    log.info("shifted grid: %d searches on %d workers", len(jobs), pool_workers)
    result: dict[tuple[str, str], dict | None] = {}
    try:
        with ProcessPoolExecutor(max_workers=pool_workers) as pool:
            for r in pool.map(search_unit, jobs):
                result[(r["scenario"], r["unit"])] = r["poles"][0] if r["poles"] else None
                log.info("shifted %s %s: %s", r["unit"], r["scenario"],
                         f"{r['poles'][0]['dist_m']:.0f} m" if r["poles"] else "no pole")
    except BrokenProcessPool as exc:
        raise PolesError(f"a worker process died during the shifted search after {len(result)} of {len(jobs)} "
                         f"jobs; lower POLES_WORKERS (now {pool_workers}) if the machine ran out of memory") from exc
    winners_json.write_text(json.dumps({f"{s}/{u}": p for (s, u), p in result.items()}, indent=1, ensure_ascii=False) + "\n",
                            encoding="utf-8")
    _mark(winners_json)
    return result


def run(cfg: RegionConfig, ws: Workspace, log: logging.Logger) -> dict:
    out, poles_dir, grid_dir, fetch_dir = ws.dir(STAGE), ws.dir("poles"), ws.dir("grid"), ws.dir("fetch")
    if ws.forced:
        _clear_markers(out, log)
    poles = load_poles(poles_dir, cfg.top_n)
    prepared = prepare(cfg, ws, log)
    snapshot = json.loads((fetch_dir / "snapshot.json").read_text(encoding="utf-8"))
    edge = unary_union([parse_poly(fetch_dir / s["poly"]) for s in snapshot["sources"]])
    tiles = RoadTiles(prepared.roads_dir)
    timings: dict[str, float] = {}

    def step(name: str, fn):
        t0 = time.monotonic()
        log.info("-- %s", name)
        value = fn()
        timings[name] = round(time.monotonic() - t0, 1)
        log.info("-- %s done in %.0fs", name, timings[name])
        return value

    results: list[checks.CheckResult] = []
    results += step("check 1: independent geodesic recheck", lambda: checks.recheck(poles, tiles, log=log))
    results += step("check 2: membership", lambda: checks.membership(poles, prepared.units, prepared.land_idx, prepared.water_big))
    results += step("check 3: data-edge bound", lambda: checks.edge_bound(poles, edge))
    results, excluded = edge_exclusions(results, poles)
    if excluded:
        log.info("check 3: %d pole(s) excluded, their nearest road may be outside the extract", len(excluded))
    shifted = step("check 4: half-cell grid shift", lambda: shifted_poles(cfg, ws, prepared, log))
    results += shift_results(poles, shifted, excluded)
    results += step("check 5: hole detection", lambda: checks.holes(
        poles, {s: grid_dir / f"roads_{s}.tif" for s in SCENARIOS}, prepared.units_tif, prepared.frame, prepared.units))
    results += step("check 6: references", lambda: checks.references(poles, checks.load_refs(Path(__file__).with_name("refs.yaml"))))
    results += step("check 7: invariants", lambda: checks.invariants(poles, prepared.units, cfg, ws.meta("grid")))

    title = f"{cfg.name} validation, snapshot {ws.snapshot}"
    summary = write_report_json(results, out / "report.json",
                                {"region": cfg.id, "snapshot": ws.snapshot, "excluded": excluded})
    write_report_html(results, prepared.units, out / "report.html", title, excluded=excluded)
    step("contact sheet: fetching satellite tiles", lambda: write_contact_sheet(
        poles, prepared.units, results, out / "contact-sheet.html", excluded=excluded,
        title=f"{cfg.name} contact sheet, snapshot {ws.snapshot}"))
    log.info("validation: %d blocking failures, %d warnings, %d excluded poles, %d results",
             summary["blocking_failures"], summary["warnings"], len(excluded), len(results))
    meta = {"summary": summary, "results": len(results), "excluded": excluded, "check_seconds": timings}
    if summary["blocking_failures"]:
        failed = [r for r in results if r.blocking and not r.passed]
        raise ValidationFailed(f"{len(failed)} blocking validation failure(s); see {out / 'report.html'}. First: "
                               f"{failed[0].check} {failed[0].unit} {failed[0].scenario} {failed[0].details}")
    return meta
