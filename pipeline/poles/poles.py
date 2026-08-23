"""Stage poles: units, road tiles, and one branch-and-bound search per unit and scenario (spec 3.2 stage 5).

`prepare` builds everything the searches share and guards each piece with a `.ok` marker, so a crash
resumes at the first missing piece. `search_unit` then runs one unit and one scenario end to end in a
process of its own: the unit's coarse cells, the branch-and-bound of candidates.py, the exact 5 m
refinement of refine.py, and the attribution of attrib.py. `run` fans the jobs out over a process pool
and writes `A.json`, `B.json` and `timing.json`.

Two inputs are large enough that where they are read matters. The unit raster is 1.35 GB at a
continent-sized frame, so `prepare` records each unit's tight row/col window and a worker reads only
that box of the unit raster and of the distance raster. The place layer is 1.8 M points, and the
country outlines are every level-2 relation of the extract, so both are cached per worker process
rather than per job.
"""
from __future__ import annotations

import json
import logging
import math
import os
import shutil
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio
import shapely
from pyogrio.raw import read, write as ogr_write
from pyproj import Transformer
from rasterio.windows import Window
from shapely.ops import unary_union
from shapely.strtree import STRtree

from .antimeridian import split_bbox, wrapped_bounds
from .attrib import Countries, Places, clean_text, nearest_way, pole_record
from .boundaries import AdminArea, load_admin_areas
from .candidates import Refined, Search, half_diag, pad_fn_for
from .classify import where_clause
from .config import RegionConfig
from .errors import PolesError
from .extract import MARKER
from .grid import Frame
from .poly import parse_poly
from .refine import RoadCache, UtmRoads, refine, utm_epsg
from .roads import RoadTiles, build_tiles
from .shell import require_tools, run_cmd
from .units import Unit, low_tif, rasterize_units, select_units, unit_cells, write_units
from .workspace import Workspace

STAGE = "poles"
SCENARIOS = ("A", "B")
DEDUP_M = 10_000.0
MIN_WATER_M2 = 1_000_000.0


def _done(path: Path) -> bool:
    return path.exists() and path.with_name(path.name + MARKER).exists()


def _mark(path: Path) -> None:
    path.with_name(path.name + MARKER).touch()


def _areas_to_fgb(areas: list[AdminArea], path: Path) -> None:
    ogr_write(str(path), geometry=np.array([shapely.to_wkb(a.geometry) for a in areas], dtype=object),
              field_data=[np.array([a.osm_id for a in areas], dtype=np.int64), np.array([a.level for a in areas], dtype=np.int32),
                          np.array([a.code for a in areas], dtype=object), np.array([a.name_en for a in areas], dtype=object),
                          np.array([int(a.complete) for a in areas], dtype=np.int32), np.array([int(a.closed_by_edge) for a in areas], dtype=np.int32)],
              fields=["osm_id", "level", "code", "name_en", "complete", "closed_by_edge"], layer="countries",
              driver="FlatGeobuf", geometry_type="MultiPolygon", crs="EPSG:4326")


def load_countries(path: Path) -> list[AdminArea]:
    meta, _, wkb, fields = read(str(path), layer="countries")
    by = dict(zip(meta["fields"], fields))
    geoms = shapely.from_wkb(wkb)
    return [AdminArea(int(by["osm_id"][i]), int(by["level"][i]), by["code"][i], None, by["name_en"][i], geoms[i],
                      bool(by["complete"][i]), bool(by["closed_by_edge"][i])) for i in range(len(geoms))]


@dataclass
class Prepared:
    frame: Frame
    units: list[Unit]
    countries_fgb: Path
    roads_dir: Path
    units_tif: Path
    land_idx: Path
    water_big: Path
    places: Path
    windows: dict[str, tuple[int, int, int, int]]


def _unit_windows(*units_tifs: Path) -> dict[int, tuple[int, int, int, int]]:
    """One block-wise pass over the unit rasters: the tight (row_off, col_off, height, width) of every index.

    Every raster a unit's cells are read from has to be scanned, or a window can miss a cell the other
    raster holds. Read once in `prepare` so that a worker never opens a whole raster: at a continent-sized
    frame the unit raster is 1.35 GB and the distance rasters are 2.7 GB each, while a single unit's window
    is a few hundred megabytes at worst.
    """
    bounds: dict[int, list[int]] = {}
    for units_tif in units_tifs:
        with rasterio.open(units_tif) as ds:
            for _, win in ds.block_windows(1):
                block = ds.read(1, window=win)
                present = np.unique(block[block > 0])
                if not present.size:
                    continue
                r0, c0 = int(win.row_off), int(win.col_off)
                for idx in present.tolist():
                    rows, cols = np.nonzero(block == idx)
                    box = [r0 + int(rows.min()), c0 + int(cols.min()), r0 + int(rows.max()), c0 + int(cols.max())]
                    have = bounds.get(idx)
                    if have is None:
                        bounds[idx] = box
                    else:
                        have[0], have[1] = min(have[0], box[0]), min(have[1], box[1])
                        have[2], have[3] = max(have[2], box[2]), max(have[3], box[3])
    return {i: (b[0], b[1], b[2] - b[0] + 1, b[3] - b[1] + 1) for i, b in bounds.items()}


def write_water_big(src: Path, dst: Path, min_m2: float, log: logging.Logger, tools_log: Path) -> None:
    """Copy the water polygons of at least `min_m2` to `dst` in lon/lat, for the big-water exclusion."""
    dst.unlink(missing_ok=True)
    # OGR2OGR_USE_ARROW_API NO: GDAL's Arrow copy path silently drops filters on special fields such as
    # OGR_GEOM_AREA and writes an empty layer with no error (seen on 3.13.3, FlatGeobuf to FlatGeobuf).
    # -wrapdateline: a water body straddling 180 is cut into a part on each side of the line on the way to
    # lon/lat. Without it GDAL cuts only a polygon centred on the line; one lying mostly on one side comes back
    # as a single band the long way round the planet (valid when it has no holes, so nothing downstream
    # notices; invalid with holes, which FlatGeobuf then refuses to write). The frame CRS is continuous across
    # the line, so this is the one place the cut can be made (issue #22). PROMOTE_TO_MULTI keeps the layer's
    # declared type for whatever the cut leaves as a single polygon.
    run_cmd(["ogr2ogr", "--config", "OGR2OGR_USE_ARROW_API", "NO",
             "-f", "FlatGeobuf", dst, src, "-t_srs", "EPSG:4326", "-wrapdateline", "-nlt", "PROMOTE_TO_MULTI",
             "-nln", "water", "-sql", f"SELECT * FROM water WHERE OGR_GEOM_AREA >= {min_m2}",
             "-lco", "SPATIAL_INDEX=YES"], log, stderr_path=tools_log)


def _unit_meta(units_json: Path, units: list[Unit]) -> dict[str, tuple[int, int, int, int]]:
    """Fill cells and area_km2 from units.json and return each unit's recorded window.

    A resume reads this file rather than recounting the raster, so every way it can disagree with the unit
    list has to name the file: an older run of different code is the normal cause."""
    try:
        entries = json.loads(units_json.read_text(encoding="utf-8"))["units"]
    except (OSError, ValueError, KeyError) as exc:
        raise PolesError(f"{units_json}: unreadable ({exc}); delete it and units.tif.ok to rebuild the units") from exc
    meta = {m["code"]: m for m in entries}
    windows = {}
    for u in units:
        m = meta.get(u.code)
        if m is None:
            raise PolesError(f"{units_json} has no entry for unit {u.code}; delete it and units.tif.ok to rebuild")
        if "window" not in m:
            raise PolesError(f"{units_json}: unit {u.code} has no window; delete it and units.tif.ok to rebuild")
        u.cells, u.area_km2 = m["cells"], m["area_km2"]
        if m["window"] is not None:
            windows[u.code] = tuple(m["window"])
    return windows


def prepare(cfg: RegionConfig, ws: Workspace, log: logging.Logger) -> Prepared:
    require_tools(["osmium", "ogr2ogr", "gdal_rasterize"])
    fetch_dir, extract_dir, grid_dir, out = ws.dir("fetch"), ws.dir("extract"), ws.dir("grid"), ws.dir(STAGE)
    tools_log = out / "tools.log"
    frame = Frame.from_dict(json.loads((grid_dir / "frame.json").read_text(encoding="utf-8")))
    snapshot = json.loads((fetch_dir / "snapshot.json").read_text(encoding="utf-8"))
    polys = {s["url"]: parse_poly(fetch_dir / s["poly"]) for s in snapshot["sources"]}
    primary = unary_union([polys[s["url"]] for s in snapshot["sources"] if s["role"] == "primary"])
    edge = unary_union(list(polys.values()))

    countries_fgb, units_fgb, units_json = out / "countries.fgb", out / "units.fgb", out / "units.json"
    if not (_done(countries_fgb) and _done(units_fgb)):
        levels = {2, cfg.unit_admin_level}
        areas = load_admin_areas(extract_dir / "boundaries.pbf", levels, edge, out / "boundaries", log,
                                 {2: "ISO3166-1", cfg.unit_admin_level: cfg.unit_code_tag})
        _areas_to_fgb(areas, countries_fgb)
        _mark(countries_fgb)
        units = select_units(areas, cfg, primary, log)
        write_units(units, units_fgb)
        _mark(units_fgb)
        log.info("units: %d (%s)", len(units), " ".join(u.code for u in units))
    else:
        units = _units_from_fgb(units_fgb)

    # water_big is an input to the candidate cells now, so it is built before them, not after.
    water_big = out / "water_big.fgb"
    if not _done(water_big):
        write_water_big(grid_dir / "water_proj.fgb", water_big, MIN_WATER_M2, log, tools_log)
        _mark(water_big)

    units_tif = out / "units.tif"
    if not _done(units_tif):
        counts = rasterize_units(units_fgb, frame, ws.shared_dir() / "land.vrt", water_big, units_tif, log, out)
        windows_by_index = _unit_windows(units_tif, low_tif(units_tif))
        cell_km2 = (frame.res / 1000.0) ** 2
        for u in units:
            u.cells = counts.get(u.index, 0)
            # candidate cells are all-touched, so this runs a hair over the true area at the border
            u.area_km2 = round(u.cells * cell_km2, 1)
        units_json.write_text(json.dumps({"units": [{
            "code": u.code, "name": u.name, "name_en": u.name_en, "osm_id": u.osm_id, "country": u.country, "index": u.index,
            "area_km2": u.area_km2, "cells": u.cells, "transcontinental": u.transcontinental, "closed_by_edge": u.closed_by_edge,
            "bbox": list(wrapped_bounds(u.geometry)), "window": list(windows_by_index[u.index]) if u.index in windows_by_index else None}
            for u in units]}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        _mark(units_tif)
        # A cached job is keyed by unit code alone, so keeping the cache here would republish results
        # searched against the outlines these units just replaced.
        if (out / "results").exists():
            log.info("poles: cleared the result cache, the units were rebuilt")
            shutil.rmtree(out / "results", ignore_errors=True)
    windows = _unit_meta(units_json, units)

    roads_dir = out / "roads"
    if not (roads_dir / "tiles.json").exists():
        build_tiles(extract_dir / "highways.vrt", "highways", roads_dir, log, extent=edge)

    land_idx = out / "land_idx.fgb"
    if not _done(land_idx):
        land_idx.unlink(missing_ok=True)
        run_cmd(["ogr2ogr", "-f", "FlatGeobuf", land_idx, ws.shared_dir() / "land.vrt", "-nln", "land",
                 "-lco", "SPATIAL_INDEX=YES"], log, stderr_path=tools_log)
        _mark(land_idx)
    return Prepared(frame, units, countries_fgb, roads_dir, units_tif, land_idx, water_big,
                    extract_dir / "places.vrt", windows)


def _units_from_fgb(path: Path) -> list[Unit]:
    """The units of a finished units.fgb, back in index order: FlatGeobuf hands features back in the order of
    its packed R-tree, not the order they were written in."""
    meta, _, wkb, fields = read(str(path), layer="units")
    by = dict(zip(meta["fields"], fields))
    geoms = shapely.from_wkb(wkb)
    units = [Unit(by["code"][i], clean_text(by["name"][i]), clean_text(by["name_en"][i]), int(by["osm_id"][i]), by["country"][i],
                  geoms[i], bool(by["transcontinental"][i]), int(by["idx"][i]),
                  closed_by_edge=bool(by["closed_by_edge"][i])) for i in range(len(geoms))]
    units.sort(key=lambda u: u.index)
    return units


@dataclass
class UnitJob:
    cfg: RegionConfig
    prepared: Prepared
    unit: Unit
    scenario: str
    dist_tif: Path
    top_n: int
    log_path: Path


@lru_cache(maxsize=1)
def _places(path: str) -> Places:
    """One place layer per worker process: 1.8 M points are worth loading once, not once per job."""
    return Places(Path(path))


@lru_cache(maxsize=1)
def _countries(path: str) -> Countries:
    """One country index per worker process, for the same reason."""
    return Countries(load_countries(Path(path)))


def _worker_logger(job: UnitJob) -> logging.Logger:
    """Per-unit logger writing to the run's log file. The handler hangs on the shared parent, so a worker
    opens the file once however many jobs it runs; appends of a single line are atomic.

    The records carry the logger name, unlike the run's own format: every worker writes to the one file,
    so a line without its unit and scenario cannot be traced back to the job that wrote it (issue #43)."""
    parent = logging.getLogger("poles.unit")
    if not parent.handlers:
        handler = logging.FileHandler(job.log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"))
        parent.addHandler(handler)
        parent.setLevel(logging.INFO)
        parent.propagate = False
    return logging.getLogger(f"poles.unit.{job.unit.code}.{job.scenario}")


def _bbox_window(unit: Unit, frame: Frame, to_frame: Transformer) -> Window:
    """The frame window covering the unit's lon/lat bbox, one cell wider each way and clamped to the frame.

    The bbox is the wrapped one, so a unit split at the antimeridian gets its own 4 degrees rather than
    the whole world (issue #22). PROJ normalises the longitude relative to the frame's central meridian
    for any lon_0, so 182 and -178 project to the same point and the segmentized ring lands in one
    compact run of columns; the only seam of an azimuthal frame is its antipode, which no region puts
    near a unit.
    """
    ring = shapely.segmentize(shapely.box(*wrapped_bounds(unit.geometry)).exterior, 0.1)
    fx, fy = to_frame.transform(*np.asarray(ring.coords).T)
    col_off = max(0, math.floor((fx.min() - frame.res - frame.x0) / frame.res))
    row_off = max(0, math.floor((frame.y1 - fy.max() - frame.res) / frame.res))
    col_end = min(frame.width, math.ceil((fx.max() + frame.res - frame.x0) / frame.res))
    row_end = min(frame.height, math.ceil((frame.y1 - fy.min() + frame.res) / frame.res))
    return Window(col_off=col_off, row_off=row_off, width=max(1, col_end - col_off), height=max(1, row_end - row_off))


def _allowed_factory(unit: Unit, land_idx: Path, water_big: Path):
    """Point allowed when inside the unit, on a land polygon, and in no water polygon of 1 km2 or more."""
    w, s, e, n = wrapped_bounds(unit.geometry)
    pad = 0.05
    # A unit split at the antimeridian has plain bounds of -180 to 180, so a single read would pull the
    # whole planet's coastline at these latitudes. The wrapped box is the unit's real extent and splits
    # into the one or two boxes the bbox filter understands (issue #22).
    parts = split_bbox(w - pad, s - pad, e + pad, n + pad)
    lwkb = [read(str(land_idx), layer="land", bbox=p)[2] for p in parts]
    wwkb = [read(str(water_big), layer="water", bbox=p)[2] for p in parts]
    land_geoms = [g for chunk in lwkb for g in shapely.from_wkb(chunk)]
    water_geoms = [g for chunk in wwkb for g in shapely.from_wkb(chunk)]
    land_tree = STRtree(land_geoms) if land_geoms else None
    water_tree = STRtree(water_geoms) if water_geoms else None
    geom = unit.geometry
    shapely.prepare(geom)                      # one prepared geometry, then one vectorised call per batch

    def allowed(lons, lats):
        pts = shapely.points(lons, lats)
        if land_tree is None:
            return np.zeros(len(pts), bool)
        ok = shapely.contains_xy(geom, lons, lats)
        on_land = np.zeros(len(pts), bool)
        on_land[np.unique(land_tree.query(pts, predicate="within")[0])] = True
        ok &= on_land
        if water_tree is not None:
            in_water = np.zeros(len(pts), bool)
            in_water[np.unique(water_tree.query(pts, predicate="within")[0])] = True
            ok &= ~in_water
        return ok

    return allowed


def refine_cell(x: float, y: float, frame_crs: str, roads: UtmRoads, half_m: float, allowed, countries: Countries,
                to_frame: Transformer) -> Refined | None:
    """One cell refined and attributed. The payload is the pole and its nearest-way record, never the road
    set: a refined candidate waits in the search's pending list until the search finalises it, and a payload holding
    the UtmRoads would pin that whole window for as long as it waits (issue #43: 20 GB in one worker)."""
    r = refine(x, y, frame_crs, roads, half_m=half_m, allowed=allowed)
    if r is None:
        return None
    fx, fy = to_frame.transform(r.lon, r.lat)
    return Refined(float(fx), float(fy), r.dist_m, (r, nearest_way(roads, r, countries)))


def search_unit(job: UnitJob) -> dict:
    """One unit and one scenario: coarse cells, branch-and-bound, exact refinement, attribution."""
    t0 = time.monotonic()
    cfg, prep_, unit, scenario = job.cfg, job.prepared, job.unit, job.scenario
    frame = prep_.frame
    log = _worker_logger(job)
    to_frame = Transformer.from_crs("EPSG:4326", frame.crs, always_xy=True)
    recorded = prep_.windows.get(unit.code)
    window = (Window(col_off=recorded[1], row_off=recorded[0], width=recorded[3], height=recorded[2])
              if recorded is not None else _bbox_window(unit, frame, to_frame))
    rows, cols = unit_cells(prep_.units_tif, unit, window=window)
    rows, cols = rows - int(window.row_off), cols - int(window.col_off)
    with rasterio.open(job.dist_tif) as dist_ds:
        dist = dist_ds.read(1, window=window)
    coarse = dist[rows, cols].astype(float)   # unit_cells raises UnitsError before this can be empty
    abs_rows, abs_cols = rows + int(window.row_off), cols + int(window.col_off)
    xs = frame.x0 + (abs_cols + 0.5) * frame.res
    ys = frame.y1 - (abs_rows + 0.5) * frame.res
    to_ll = Transformer.from_crs(frame.crs, "EPSG:4326", always_xy=True)
    lons, lats = to_ll.transform(xs, ys)
    top_coarse = float(coarse.max())
    if top_coarse >= cfg.max_distance_m:
        # A cell at the cap is a real "at least max_distance_m" answer that the search cannot rank against
        # the others, so it aborts rather than publish a number it did not measure. The message carries the
        # cell, because the alternative to naming it is rerunning the region to find it.
        k = int(np.argmax(coarse))
        raise PolesError(f"unit {unit.code} scenario {scenario}: top coarse value {top_coarse} m is the "
                         f"saturation cap ({cfg.max_distance_m} m), reached by "
                         f"{int((coarse >= cfg.max_distance_m).sum())} of {len(coarse)} candidate cells; the "
                         f"farthest is the cell centred at lon {lons[k]:.4f}, lat {lats[k]:.4f}. Usually the cell is "
                         f"a rock or an islet that should carry no pole, and the answer is a territory_mask "
                         f"entry covering it in the region config; raising max_distance_m is the other way.")
    pads = pad_fn_for(frame.crs)(np.asarray(lons), np.asarray(lats))

    tiles = RoadTiles(prep_.roads_dir)
    cache = RoadCache(tiles, where=where_clause(scenario))
    allowed = _allowed_factory(unit, prep_.land_idx, prep_.water_big)
    countries = _countries(str(prep_.countries_fgb))
    hd = half_diag(frame.res)

    def refiner(i: int) -> Refined | None:
        # The road window has to hold every road that could be nearest to a point of the cell: the coarse
        # value plus the grid's own half diagonals, with room for projection error and for the refinement
        # finding a point farther out than the coarse value.
        radius_m = coarse_sorted[i] * 1.2 + 1000.0 + 2 * hd
        lon, lat = lon_sorted[i], lat_sorted[i]
        dlat = radius_m / 111_320.0
        dlon = dlat / max(0.05, np.cos(np.radians(lat)))
        epsg = utm_epsg(lon, lat)
        roads = cache.get(lon - dlon, lat - dlat, lon + dlon, lat + dlat, epsg)
        return refine_cell(x_sorted[i], y_sorted[i], frame.crs, roads, half_m=hd, allowed=allowed, countries=countries, to_frame=to_frame)

    search = Search(xs, ys, coarse, pads, frame.res, job.top_n, refiner, DEDUP_M, log=log)
    # `refiner` reads these by name, so they must be bound before search.run(): Search sorts the cells by
    # their upper bound and the refiner is called with indices into that sorted order, not into the raw
    # arrays; the road window still comes from the cell's own coarse value, read as coarse_sorted[i].
    coarse_sorted, x_sorted, y_sorted = search.coarse, search.xs, search.ys
    lon_sorted, lat_sorted = np.asarray(lons)[search.order], np.asarray(lats)[search.order]
    result = search.run()

    places = _places(str(prep_.places))
    poles = []
    for rank, acc in enumerate(result.accepted, start=1):
        refined, way = acc.payload
        poles.append(pole_record(rank, refined, way, places.nearest(refined.lon, refined.lat)))
    reason = None
    if result.exhausted:
        reason = (f"only {len(poles)} pole(s): no further point of the unit is both at least "
                  f"{DEDUP_M / 1000:.0f} km from the accepted poles and on allowed ground"
                  if poles else "no pole: no candidate of the unit refined to an allowed point")
    return {"unit": unit.code, "scenario": scenario, "poles": poles, "reason": reason, "refinements": result.refinements,
            "warnings": result.warnings, "duration_s": round(time.monotonic() - t0, 1), "top_coarse_m": top_coarse}


def validate_poles_json(data: list[dict], top_n: int) -> None:
    for entry in data:
        if set(entry) != {"unit", "poles", "reason"}:
            raise ValueError(f"entry keys {sorted(entry)}")
        if len(entry["poles"]) < top_n and not entry["reason"]:
            raise ValueError(f"unit {entry['unit']}: fewer than {top_n} poles without a reason")
        for i, p in enumerate(entry["poles"], start=1):
            if p["rank"] != i:
                raise ValueError(f"unit {entry['unit']}: rank {p['rank']} at position {i}")
            if not (isinstance(p["dist_m"], (int, float)) and p["dist_m"] >= 0):
                raise ValueError(f"unit {entry['unit']}: bad dist_m {p['dist_m']}")
            if set(p["nearest_way"]) != {"id", "highway", "name", "ref", "country"}:
                raise ValueError(f"unit {entry['unit']}: nearest_way keys")
            if not (-90 <= p["lat"] <= 90 and -180 <= p["lon"] <= 180):
                raise ValueError(f"unit {entry['unit']}: coordinates")


# What `run` reads off every result when it assembles the stage output; a cached file without these is not one.
RESULT_KEYS = ("unit", "scenario", "poles", "reason", "refinements", "warnings", "duration_s", "top_coarse_m")


def _result_path(results_dir: Path, unit_code: str, scenario: str) -> Path:
    return results_dir / f"{unit_code}-{scenario}.json"


def _cache_result(results_dir: Path, result: dict) -> None:
    """One finished job, written then renamed so a crash cannot leave half a result behind."""
    path = _result_path(results_dir, result["unit"], result["scenario"])
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _cached_result(path: Path) -> dict:
    """A finished job read back, or a PolesError naming the file: a foreign or half-written file must not
    reach the published output through a bare KeyError further down."""
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise PolesError(f"{path}: not readable as a cached result ({exc}); delete it to search that unit again") from exc
    missing = [k for k in RESULT_KEYS if k not in result] if isinstance(result, dict) else list(RESULT_KEYS)
    if missing:
        raise PolesError(f"{path}: not a cached result, no {', '.join(missing)}; delete it to search that unit again")
    return result


def _search_pending(pending: list[UnitJob], results_dir: Path, workers: int, log: logging.Logger,
                    executor_factory=ProcessPoolExecutor) -> list[dict]:
    """Search every pending job, caching and logging each result the moment its own job finishes.

    `pool.map` yields in job order, so the results of the jobs that finished early sat in the pool until
    the ones ahead of them were done: on North America run 4 two finished searches were still uncached
    when the run died on the job at the head of the queue, and both were lost (issue #45). The returned
    list is in completion order, which is why `run` sorts what it writes.
    """
    results: list[dict] = []
    with executor_factory(max_workers=workers) as pool:
        futures = [pool.submit(search_unit, job) for job in pending]
        jobs = dict(zip(futures, pending))
        taken: set = set()

        def take(f) -> None:
            taken.add(f)
            r = f.result()
            _cache_result(results_dir, r)
            results.append(r)
            log.info("%s %s: %d poles, best %.0f m, %d refinements, %.0fs%s", r["unit"], r["scenario"], len(r["poles"]),
                     r["poles"][0]["dist_m"] if r["poles"] else 0, r["refinements"], r["duration_s"],
                     f" ({r['reason']})" if r["reason"] else "")

        def drain() -> None:
            """Every job that finished but was not consumed yet, cached and logged: it is paid for."""
            for f in futures:
                if f not in taken and not f.cancelled() and f.exception() is None:
                    take(f)

        try:
            for f in as_completed(futures):
                take(f)
        except PolesError:
            # A worker's own error ends the stage, but the jobs already running are paid for: drop the
            # queue, wait the running ones out and cache what they return, then re-raise the original.
            for f in futures:
                f.cancel()
            drain()
            raise
        except BrokenProcessPool as exc:
            drain()
            # Every job that produced no result: the one the dead worker held plus everything still
            # queued. `f.done()` cannot say which is which, because a pool tearing down marks every
            # remaining future with this same error before the first `result()` call sees it.
            lost = [jobs[f] for f in futures if f not in taken]
            named = ", ".join(f"unit {j.unit.code} scenario {j.scenario}" for j in lost[:5])
            more = f" and {len(lost) - 5} more" if len(lost) > 5 else ""
            raise PolesError(f"a worker process died with {named}{more} in flight; {len(results)} of "
                             f"{len(pending)} searched jobs are cached and a rerun resumes there. Lower "
                             f"POLES_WORKERS (now {workers}) if the machine ran out of memory") from exc
    return results


def run(cfg: RegionConfig, ws: Workspace, log: logging.Logger) -> dict:
    prepared = prepare(cfg, ws, log)
    out, grid_dir = ws.dir(STAGE), ws.dir("grid")
    workers = int(os.environ.get("POLES_WORKERS", "0")) or 4
    # One file per finished job, so a run that dies on job 59 of 104 keeps the 58 it already paid for. This
    # is the `.ok` marker idea at job granularity; a forced run starts from nothing.
    results_dir = out / "results"
    if ws.forced and results_dir.exists():
        shutil.rmtree(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    # Every job is pickled to its worker, so the shared inputs travel once per job: the unit list would
    # carry every unit's outline along with each of them, and no worker ever reads it.
    shared = replace(prepared, units=[])
    jobs = [UnitJob(cfg, shared, u, s, grid_dir / f"dist_{s}.tif", cfg.top_n, ws.base / "log.txt")
            for s in SCENARIOS for u in sorted(prepared.units, key=lambda u: -u.cells)]
    results: list[dict] = []
    pending: list[UnitJob] = []
    for job in jobs:
        path = _result_path(results_dir, job.unit.code, job.scenario)
        if path.is_file():
            results.append(_cached_result(path))
        else:
            pending.append(job)
    log.info("poles: %d jobs (%d units x %d scenarios) on %d workers; %d cached, %d to search", len(jobs),
             len(prepared.units), len(SCENARIOS), workers, len(results), len(pending))
    searched = 0
    if pending:
        fresh = _search_pending(pending, results_dir, workers, log, ProcessPoolExecutor)
        results.extend(fresh)
        searched = len(fresh)
    timing = {}
    for s in SCENARIOS:
        entries = [{"unit": r["unit"], "poles": r["poles"], "reason": r["reason"]} for r in results if r["scenario"] == s]
        entries.sort(key=lambda e: e["unit"])
        validate_poles_json(entries, cfg.top_n)
        (out / f"{s}.json").write_text(json.dumps(entries, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        # Sorted by unit, because the searched results now arrive in completion order.
        timing[s] = {r["unit"]: {"duration_s": r["duration_s"], "refinements": r["refinements"], "top_coarse_m": r["top_coarse_m"],
                                 "warnings": r["warnings"]} for r in sorted(results, key=lambda r: r["unit"]) if r["scenario"] == s}
    (out / "timing.json").write_text(json.dumps(timing, indent=1) + "\n", encoding="utf-8")
    return {"units": len(prepared.units), "jobs": len(jobs), "workers": workers, "cached": len(results) - searched,
            "searched": searched, "total_refinements": sum(r["refinements"] for r in results)}
