"""Stage validate (spec 6): every published pole is re-derived by an independent path; any blocking failure stops the run.

The seven checks live in `checks.py` and know nothing about each other. This module runs them in order,
decides what blocks, and writes the three files an owner reads: `report.json`, `report.html` and
`contact-sheet.html`.

One class of failure is a fact about the data rather than a bug: a pole whose nearest road may simply be
outside the extract, because the country that road belongs to was never downloaded. Check 3 finds those,
and the stage excludes them instead of stopping: they are listed in `report.json` under `excluded` and
marked on the contact sheet, for publication to skip. Everything else that blocks still stops the run,
after the three files are written.
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
from ..grid import TILE, Frame, create_raster, rasterize, tiled_edt, write_float_tif
from ..poles import SCENARIOS, Prepared, UnitJob, prepare, search_unit, validate_poles_json
from ..poly import parse_poly
from ..roads import RoadTiles
from ..units import rasterize_units
from ..workspace import Workspace
from . import checks
from .report import cached_tile_fetcher, write_atomic, write_contact_sheet, write_report_html, write_report_json

STAGE = "validate"
# The fields check 4 reads off a shifted pole. A stored file without them is from an older version of this
# stage and is recomputed rather than read, the way the poles stage checks its cached results.
SHIFT_KEYS = ("rank", "lat", "lon", "dist_m")


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


def load_shifted_winners(path: Path) -> dict[tuple[str, str], list[dict]] | None:
    """The stored shifted poles, or None when the file cannot be read as the current shape.

    The first version of this file kept one pole (or null) per key; reading that as a list would fail deep
    inside check 4, so anything that does not match is recomputed instead."""
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(stored, dict):
        return None
    out: dict[tuple[str, str], list[dict]] = {}
    for key, poles in stored.items():
        if not isinstance(poles, list) or "/" not in str(key):
            return None
        if any(not isinstance(p, dict) or any(f not in p for f in SHIFT_KEYS) for p in poles):
            return None
        scenario, unit = str(key).split("/", 1)
        out[(scenario, unit)] = poles
    return out


def _nearest_shifted(pole: dict, candidates: list[dict]) -> dict | None:
    """The shifted candidate closest to `pole` on the ground.

    Rank is no way to pair them up: half a cell of shift can reorder candidates that are metres apart in
    distance, so the counterpart of the pole under test is the nearest one, not the one of the same rank."""
    if not candidates:
        return None
    return min(candidates, key=lambda c: checks.GEOD.inv(pole["lon"], pole["lat"], c["lon"], c["lat"])[2])


def shift_results(poles: dict[str, list[dict]], shifted: dict[tuple[str, str], list[dict]],
                  excluded: list[dict]) -> list[checks.CheckResult]:
    """Check 4 read off the shifted poles, one result per unit and scenario.

    The pole compared is the first one that was not excluded, because that is the pole publication will
    use. When every pole of the unit and scenario was excluded there is nothing left to publish, so the
    comparison is kept for the record but does not block: the shifted grid re-runs the same search over the
    same incomplete road data, and asking the two to agree says nothing about what we ship."""
    dropped = {(e["scenario"], e["unit"], e["rank"]) for e in excluded}
    out = []
    for scenario in sorted(poles):
        for entry in poles[scenario]:
            if not entry["poles"]:
                continue
            kept = [p for p in entry["poles"] if (scenario, entry["unit"], p["rank"]) not in dropped]
            original = kept[0] if kept else entry["poles"][0]
            candidates = shifted.get((scenario, entry["unit"])) or []
            r = checks.grid_shift_compare(entry["unit"], scenario, original, _nearest_shifted(original, candidates))
            if not kept:
                r = replace(r, blocking=False, details={**r.details, "all_poles_excluded": True})
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


def shifted_poles(cfg: RegionConfig, ws: Workspace, prepared: Prepared, log: logging.Logger) -> dict[tuple[str, str], list[dict]]:
    """Check 4: recompute the grid half a cell off in both axes and re-run the search for each unit.

    Everything here is stage-1 sized (a full-frame rasterize, a full-frame distance transform, and the
    candidate rasters), so every piece is guarded by an `.ok` marker and a crash resumes at the first one
    missing. The finished winners are a marker of their own: a rerun that already has them skips the lot."""
    out, classify_dir = ws.dir(STAGE), ws.dir("classify")
    tools_log = out / "tools.log"
    winners_json = out / "shifted_winners.json"
    if _done(winners_json):
        stored = load_shifted_winners(winners_json)
        if stored is not None:
            log.info("shifted grid: reusing %s", winners_json.name)
            return stored
        log.info("shifted grid: %s is not the shape this version reads, searching again", winners_json.name)
    f = prepared.frame
    shifted = Frame(f.crs, f.res, f.x0 + f.res / 2, f.y1 + f.res / 2, f.width, f.height)
    write_atomic(out / "frame_shift.json", json.dumps(shifted.to_dict(), indent=2) + "\n")
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
    units_tif = out / "units_shift.tif"
    if not _done(units_tif):
        t0 = time.monotonic()
        # The same vector inputs the poles stage used, on the shifted frame: the land and water masks the
        # candidate rule needs are frame-specific, so this frame builds its own beside units_shift.tif.
        rasterize_units(ws.dir("poles") / "units.fgb", shifted, ws.shared_dir() / "land.vrt",
                        ws.dir("poles") / "water_big.fgb", units_tif, log, out)
        _mark(units_tif)
        log.info("shifted grid: unit rasters in %.0fs", time.monotonic() - t0)
    prep_shift = replace(prepared, units=[], frame=shifted, units_tif=units_tif,
                         windows=_shift_windows(prepared.windows, shifted))
    # The full top_n, not a few: check 4 compares the pole that will be published, and with enough excluded
    # poles above it that can be any rank up to top_n, which a shorter shifted list would not reach.
    jobs = [UnitJob(cfg, prep_shift, u, s, out / f"dist_{s}_shift.tif", cfg.top_n, ws.base / "log.txt")
            for s in SCENARIOS for u in sorted(prepared.units, key=lambda u: -u.cells)]
    pool_workers = int(os.environ.get("POLES_WORKERS", "0")) or 4
    log.info("shifted grid: %d searches on %d workers", len(jobs), pool_workers)
    result: dict[tuple[str, str], list[dict]] = {}
    try:
        with ProcessPoolExecutor(max_workers=pool_workers) as pool:
            for r in pool.map(search_unit, jobs):
                result[(r["scenario"], r["unit"])] = r["poles"]
                log.info("shifted %s %s: %s", r["unit"], r["scenario"],
                         f"{r['poles'][0]['dist_m']:.0f} m" if r["poles"] else "no pole")
    except BrokenProcessPool as exc:
        raise PolesError(f"a worker process died during the shifted search after {len(result)} of {len(jobs)} "
                         f"jobs; lower POLES_WORKERS (now {pool_workers}) if the machine ran out of memory") from exc
    write_atomic(winners_json, json.dumps({f"{s}/{u}": p for (s, u), p in result.items()}, indent=1,
                                          ensure_ascii=False) + "\n")
    _mark(winners_json)
    return result


def reference_results(cfg: RegionConfig, poles) -> list[checks.CheckResult]:
    """Check 6, over the reference file the region config names. Reference poles are per region, so a
    region may ship none: that is recorded as a passing, non-blocking result rather than a failure, and
    the report still lists the check."""
    if cfg.references is None:
        return [checks.CheckResult("reference", "*", "*", True, False,
                                   {"reason": "the region config names no reference file"})]
    return checks.references(poles, checks.load_refs(cfg.references))


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
    results += step("check 6: references", lambda: reference_results(cfg, poles))
    results += step("check 7: invariants", lambda: checks.invariants(poles, prepared.units, cfg, ws.meta("grid")))

    title = f"{cfg.name} validation, snapshot {ws.snapshot}"
    summary = write_report_json(results, out / "report.json",
                                {"region": cfg.id, "snapshot": ws.snapshot, "excluded": excluded})
    write_report_html(results, prepared.units, out / "report.html", title, excluded=excluded)
    sheet_error = None
    try:
        step("contact sheet: fetching satellite tiles", lambda: write_contact_sheet(
            poles, prepared.units, results, out / "contact-sheet.html", excluded=excluded,
            fetch_tile=cached_tile_fetcher(out / "tiles"),
            title=f"{cfg.name} contact sheet, snapshot {ws.snapshot}"))
    except Exception as exc:  # noqa: BLE001
        # The sheet is a review aid built from a third-party tile server; the verdict below is the stage's
        # actual job and must be reached whatever the imagery does.
        sheet_error = f"{type(exc).__name__}: {exc}"
        log.error("contact sheet failed (%s); the report files and the verdict still stand", sheet_error)
    log.info("validation: %d blocking failures, %d warnings, %d excluded poles, %d results",
             summary["blocking_failures"], summary["warnings"], len(excluded), len(results))
    meta = {"summary": summary, "results": len(results), "excluded": excluded, "check_seconds": timings,
            "contact_sheet_error": sheet_error}
    if summary["blocking_failures"]:
        failed = [r for r in results if r.blocking and not r.passed]
        raise ValidationFailed(f"{len(failed)} blocking validation failure(s); see {out / 'report.html'}. First: "
                               f"{failed[0].check} {failed[0].unit} {failed[0].scenario} {failed[0].details}")
    return meta
