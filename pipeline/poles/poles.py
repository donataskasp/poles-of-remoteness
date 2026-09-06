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
from concurrent.futures import Future, ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Callable

import numpy as np
import rasterio
import shapely
from pyogrio.raw import read, write as ogr_write
from pyproj import Transformer
from rasterio.features import shapes
from rasterio.transform import from_origin
from rasterio.windows import Window
from scipy.ndimage import find_objects
from shapely.geometry import shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

from .antimeridian import split_bbox, wrapped_bounds
from .areas import AreaField, LandComponents, col_threshold
from .attrib import GEOD, Countries, Places, clean_text, nearest_way, pole_record
from .boundaries import AdminArea, load_admin_areas
from .candidates import Quota, Refined, Search, Verdict, half_diag, pad_fn_for
from .classify import where_clause
from .config import RegionConfig
from .errors import PolesError
from .extract import MARKER
from .grid import Frame
from .poly import parse_poly
from .refine import RoadCache, UtmRoads, refine, utm_epsg
from .roads import RoadTiles, build_tiles
from .shell import require_tools, run_cmd
from .units import (Unit, land_tif, low_tif, rasterize_units, select_units, unit_cells, water_tif,
                    write_units)
from .workspace import Workspace

STAGE = "poles"
SCENARIOS = ("A", "B")
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


def refined_cell(frame: Frame, to_frame: Transformer, pole) -> tuple[int, int]:
    """Frame row and column of a refined point, from its published coordinates: the six-decimal rounding of
    `pole_record` and the floor division of `validate.checks._pole_cells`, so the search and check 7 name the
    same cell for the same pole."""
    x, y = to_frame.transform(round(pole.lon, 6), round(pole.lat, 6))
    return int((frame.y1 - y) // frame.res), int((x - frame.x0) // frame.res)


def padded_window(window: Window, pad_cells: int, frame: Frame) -> Window:
    """The unit's window grown by `pad_cells` each way and clamped to the frame. Shared with check 7.

    The margin is what the connectivity question needs: a path joining two areas may leave the unit's own
    box. **Stated assumption:** it does not leave it by more than the candidate's own distance to a road,
    which is where `pad_cells` comes from. It is an assumption, not a theorem; it scales itself, being a
    few cells for a microstate and about 1,700 for the largest unit, and the cost of it being wrong is two
    areas called one place, never a pole in the wrong place.
    """
    row_off, col_off = int(window.row_off), int(window.col_off)
    row_end = min(frame.height, row_off + int(window.height) + pad_cells)
    col_end = min(frame.width, col_off + int(window.width) + pad_cells)
    row_off, col_off = max(0, row_off - pad_cells), max(0, col_off - pad_cells)
    return Window(col_off=col_off, row_off=row_off, width=col_end - col_off, height=row_end - row_off)


# A land component whose raster area is under this is measured from the land polygons instead (see
# `vector_component_areas`); above it the all-touched inflation is a percent or two of the island.
VECTOR_AREA_BELOW_KM2 = 5000.0


def vector_component_areas(field: AreaField, comps: LandComponents, labels, land_idx: Path, unit: Unit,
                           frame: Frame, to_frame: Transformer, below_km2: float = VECTOR_AREA_BELOW_KM2) -> dict[int, float]:
    """The land area, in km2, of the small components among `labels`: the land polygons clipped to the
    component's cells, measured in the coarse CRS.

    The raster area of a component is the count of its all-touched cells, and all-touched rasterisation
    turns a reef into an island: the rocks of Les Minquiers sum to 0.1 km2 of land and touch 19 cells, 1.2
    km2, so the raster floor kept a pole on them and the half-shifted grid of check 4 dropped it. The
    component's outline is traced off the label raster and intersected with the land polygons, so a piece
    is counted for exactly the cells it touches, lakes inside it and degree lines through it notwithstanding.
    Only components under `below_km2` of raster area are measured: above it the inflation is a perimeter
    band of a quarter cell against a large area, and tracing a continent for every job would cost more than
    it corrects. A component touching the window's border is not measured either: what lies beyond the
    window was not read, so its land cannot be summed, and the count stands (the District of Columbia's
    window holds 450 km2 of the mainland, and the Vatican's 1.25 km2 of Rome). Areas are planar in the
    coarse CRS, which the region makes equal-area (both regions use LAEA), the same assumption the cell
    count itself rests on.
    """
    lab = comps.labels
    edge = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])).tolist())
    small = sorted(int(v) for v in np.unique(labels) if v and int(v) not in edge and comps.area_km2[int(v)] < below_km2)
    if not small:
        return {}
    out = {v: 0.0 for v in small}
    w, s, e, n = wrapped_bounds(unit.geometry)
    pad = 1.0    # a small island holding a cell of the unit lies within its own size of the unit's box
    parts = split_bbox(w - pad, s - pad, e + pad, n + pad)
    chunks = [read(str(land_idx), layer="land", bbox=p)[2] for p in parts]
    geoms = [g for chunk in chunks for g in shapely.from_wkb(chunk)]
    if not geoms:
        return out
    projected = shapely.transform(np.asarray(geoms, dtype=object),
                                  lambda xy: np.column_stack(to_frame.transform(xy[:, 0], xy[:, 1])))
    tree = STRtree(projected)
    boxes = find_objects(lab)
    for v in small:
        sl = boxes[v - 1]
        if sl is None:
            continue
        crop = lab[sl] == v
        origin_x = frame.x0 + (field.col_off + sl[1].start) * frame.res
        origin_y = frame.y1 - (field.row_off + sl[0].start) * frame.res
        outline = shapely.union_all([shape(g) for g, _ in shapes(crop.astype("uint8"), mask=crop, connectivity=8,
                                                             transform=from_origin(origin_x, origin_y, frame.res, frame.res))])
        hits = tree.query(outline, predicate="intersects")
        if len(hits):
            out[v] = float(shapely.area(shapely.intersection(outline, shapely.union_all(projected[hits]))) / 1e6)
    return out


def _island_cells(field: AreaField, rows: np.ndarray, cols: np.ndarray, min_island_m2: float,
                  measure: Callable[[np.ndarray], dict[int, float]] | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per candidate cell: keep it, the area of its land component, and whether that component is the main one.

    A cell on a land component smaller than `min_island_m2` carries no pole (spec 2.3, issue #30): the whole
    of Kolbeinsey rasterises to one all-touched cell of 0.0625 km2, and a pole there is a pole on a rock.
    The area is the raster's cell count, corrected for the small components by `measure` (the land polygons,
    see `vector_component_areas`) when the caller passes one: the count alone makes an island of a reef.
    The main component is the one holding the most of this unit's kept cells, which is the unit-relative
    reading of "the unit's largest land component": an island unit's own mainland is the main component
    whatever else the padded window happens to contain, which is the point of measuring it here.
    """
    comps = field.land_components()
    wr, wc = field.rowcol(rows, cols)
    comp = comps.labels[wr, wc]
    area = comps.area_km2.astype("float64")
    if measure is not None:
        for label, km2 in measure(comp).items():
            area[label] = km2
    island_km2 = area[comp]
    keep = island_km2.astype("float64") * 1e6 >= float(min_island_m2)
    is_main = np.zeros(comp.shape, dtype=bool)
    if keep.any():
        is_main = comp == int(np.bincount(comp[keep]).argmax())
    return keep, island_km2, is_main


class IslandQuota(Quota):
    """The published superset: `top_n` poles on the unit's main landmass, plus the islands above the last one.

    The search keeps going until it holds `top_n` mainland poles, and takes the island poles it meets on the
    way up to a cap of `top_n`, so a unit and scenario publish at most `2 * top_n` and the site can offer
    both readings out of one document. Ranks are the overall order of that set; nothing is renumbered.

    Island-ness is a property of the candidate's **cell** and so is known before the cell is refined, which
    is what makes the cap's retirement exact: the moment the island count reaches `top_n` every remaining
    island cell is retired in one operation. Without it an archipelago unit would go on refining skerries it
    can no longer take, all the way down to its tenth mainland pole. The count never falls, so retiring on
    it loses nothing, which is the same monotonicity argument the distinct-area rule's retirement rests on.
    """

    def __init__(self, top_n: int, is_island: Callable[[Refined], bool], island_cells: np.ndarray):
        self.top_n = int(top_n)
        self.is_island, self.island_cells = is_island, island_cells
        self.mainland = self.islands = 0

    def wants_more(self) -> bool:
        return self.mainland < self.top_n

    def accepts(self, p: Refined) -> bool:
        return not self.is_island(p) or self.islands < self.top_n

    def taken(self, p: Refined) -> np.ndarray | None:
        if not self.is_island(p):
            self.mainland += 1
            return None
        self.islands += 1
        return self.island_cells if self.islands == self.top_n else None


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

    # The island floor, before anything is searched. The field is built once here and the search's
    # distinct-area rule reads the same window; the pad comes from the farthest cell the unit has, which is
    # the widest a joining path can be under the assumption `padded_window` states. The per-cell island
    # area and the main-component flag are what a published pole's `island_km2` is later read from.
    field = AreaField.read(job.dist_tif, land_tif(prep_.units_tif), water_tif(prep_.units_tif), frame,
                           padded_window(window, int(math.ceil(float(coarse.max()) / frame.res)), frame),
                           float(cfg.max_distance_m))
    keep, cell_island_km2, cell_is_main = _island_cells(
        field, abs_rows, abs_cols, cfg.min_island_m2,
        measure=lambda labels: vector_component_areas(field, field.land_components(), labels, prep_.land_idx, unit, frame, to_frame))
    dropped = len(np.unique(field.land_components().labels[field.rowcol(abs_rows, abs_cols)][~keep]))
    if not keep.any():
        log.info("island floor: none of the %d candidate cells sits on a land component of %.2f km2 or more",
                 keep.size, cfg.min_island_m2 / 1e6)
        return {"unit": unit.code, "scenario": scenario, "poles": [], "refinements": 0, "warnings": [],
                "reason": ("no pole: every candidate cell of the unit lies on a land component smaller than "
                           f"min_island_m2 ({cfg.min_island_m2 / 1e6:.2f} km2)"),
                "duration_s": round(time.monotonic() - t0, 1), "top_coarse_m": float(coarse.max())}
    coarse, xs, ys = coarse[keep], xs[keep], ys[keep]
    abs_rows, abs_cols = abs_rows[keep], abs_cols[keep]
    lons, lats = np.asarray(lons)[keep], np.asarray(lats)[keep]
    cell_island_km2, cell_is_main = cell_island_km2[keep], cell_is_main[keep]
    off_main = ~cell_is_main
    log.info("island floor: %d candidate cells, %d kept, %d land component(s) dropped; %d kept cell(s) lie "
             "off the unit's largest component, the largest of those %.2f km2", keep.size, int(keep.sum()),
             dropped, int(off_main.sum()), float(cell_island_km2[off_main].max()) if off_main.any() else 0.0)

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
        refined = refine_cell(x_sorted[i], y_sorted[i], frame.crs, roads, half_m=hd, allowed=allowed, countries=countries, to_frame=to_frame)
        if refined is not None:
            refined.at = refined_cell(frame, to_frame, refined.payload[0])
        return refined

    fraction = cfg.area_col_fraction
    retired: set[tuple[int, int]] = set()

    def cell_of(p: Refined) -> tuple[int, int]:
        """The cell the rule is asked about: the refined point's own, the one check 7 reads off the published
        coordinates. A refinement can lap out of its candidate cell into a neighbour, and the two can sit on
        opposite sides of the threshold: Andorra's fifth pole at 544 m was refined out of a 250 m cell into a
        559 m one, and read at the candidate cell the rule saw a point joined to nothing. The window holds the
        neighbour whenever it holds the candidate, since the pad is at least a cell; the fallback is for the
        degenerate window a test can build."""
        if p.at is not None:
            wr, wc = p.at[0] - field.row_off, p.at[1] - field.col_off
            if 0 <= wr < field.level.shape[0] and 0 <= wc < field.level.shape[1]:
                return p.at
        return int(row_sorted[p.cell]), int(col_sorted[p.cell])

    def distinct(cand: Refined, accepted: list[Refined]) -> Verdict:
        """The distinct-area rule: is this candidate connected to an accepted pole over high ground?

        Candidates are finalised in globally descending distance, so this one is the nearer of every pair it
        is tested against and `col_threshold` collapses to a single number for the whole accepted set: one
        labelling answers the question for all of them. The retirement of a component is the same mask
        however many candidates of it are finalised at one rung, so it is handed to the search once per
        rung and component: a plateau finalises hundreds of candidates against one component, and Turkey
        asked about 12 M cells each time.
        """
        theta = col_threshold(cand.dist_m, cand.dist_m, fraction)
        comp = field.component_at(*cell_of(cand), theta)
        if comp == 0:
            # Below the threshold or off land: no accepted pole can be joined to it, and nothing to retire.
            return Verdict(True, None)
        same = any(field.component_at(*cell_of(a), theta) == comp for a in accepted)
        key = (field.rung(theta), comp)
        if key in retired:
            return Verdict(not same, None)
        retired.add(key)
        return Verdict(not same, field.dead_mask(comp, theta)[wr_sorted, wc_sorted])

    search = Search(xs, ys, coarse, pads, frame.res, job.top_n, refiner, cfg.dedup_m, distinct=distinct, log=log)
    # `refiner`, `distinct` and the quota read these by name, so they must be bound before search.run():
    # Search sorts the cells by their upper bound and all three are called with indices into that sorted
    # order, not into the raw arrays; the road window still comes from the cell's own coarse value, read as
    # coarse_sorted[i].
    coarse_sorted, x_sorted, y_sorted = search.coarse, search.xs, search.ys
    lon_sorted, lat_sorted = np.asarray(lons)[search.order], np.asarray(lats)[search.order]
    row_sorted, col_sorted = abs_rows[search.order], abs_cols[search.order]
    wr_sorted, wc_sorted = field.rowcol(row_sorted, col_sorted)
    main_sorted, island_km2_sorted = cell_is_main[search.order], cell_island_km2[search.order]
    # The quota needs the same sorted order, and the sort happens inside the constructor, so it is set here
    # rather than passed in; the search reads it only inside run().
    search.quota = IslandQuota(job.top_n, lambda p: not bool(main_sorted[p.cell]), ~main_sorted)
    result = search.run()

    # `nearest_place` stays None here: `run` attributes every result once, in the parent, from the places
    # layer loaded a single time, so the search neither loads 300 MB per worker nor depends on the layer.
    poles = []
    for rank, acc in enumerate(result.accepted, start=1):
        refined, way = acc.payload
        island_km2 = None if main_sorted[acc.cell] else round(float(island_km2_sorted[acc.cell]), 1)
        poles.append(pole_record(rank, refined, way, None, island_km2))
    mainland = sum(1 for p in poles if p["island_km2"] is None)
    log.info("published %d pole(s): %d on the unit's main landmass, %d on smaller components",
             len(poles), mainland, len(poles) - mainland)
    reason = None
    if result.exhausted:
        reason = (f"only {mainland} mainland pole(s): no further point of the unit is a distinct area, at "
                  f"least {cfg.dedup_m / 1000:.0f} km from the accepted poles and on allowed ground"
                  if poles else "no pole: no candidate of the unit refined to an allowed point")
    return {"unit": unit.code, "scenario": scenario, "poles": poles, "reason": reason, "refinements": result.refinements,
            "warnings": result.warnings, "duration_s": round(time.monotonic() - t0, 1), "top_coarse_m": top_coarse}


def validate_poles_json(data: list[dict], top_n: int) -> None:
    """The shape of poles/<scenario>.json, which is a superset: `top_n` mainland poles or a reason, plus the
    island poles the search met above the last of them, at most `top_n` of those and so at most `2 * top_n`
    in all. Ranks are the overall order of that set and run 1..N with no gap. The message names which of
    those failed, because the answer to each is a different bug."""
    for entry in data:
        if set(entry) != {"unit", "poles", "reason"}:
            raise ValueError(f"entry keys {sorted(entry)}")
        mainland = sum(1 for p in entry["poles"] if p["island_km2"] is None)
        islands = len(entry["poles"]) - mainland
        if mainland < top_n and not entry["reason"]:
            raise ValueError(f"unit {entry['unit']}: fewer than {top_n} mainland poles ({mainland}) without a reason")
        if mainland > top_n:
            raise ValueError(f"unit {entry['unit']}: {mainland} mainland poles, more than top_n ({top_n})")
        if islands > top_n:
            raise ValueError(f"unit {entry['unit']}: {islands} island poles, more than the cap of top_n ({top_n})")
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
                    executor_factory=None) -> list[dict]:
    """Search every pending job, caching and logging each result the moment its own job finishes.

    `pool.map` yields in job order, so the results of the jobs that finished early sat in the pool until
    the ones ahead of them were done: on North America run 4 two finished searches were still uncached
    when the run died on the job at the head of the queue, and both were lost (issue #45). The returned
    list is in completion order, which is why `run` sorts what it writes.
    """
    results: list[dict] = []
    with (executor_factory or ProcessPoolExecutor)(max_workers=workers) as pool:
        futures = [pool.submit(search_unit, job) for job in pending]
        jobs = dict(zip(futures, pending))
        stored: set[Future] = set()          # futures whose result reached results_dir, nothing else

        def take(f: Future) -> None:
            r = f.result()
            _cache_result(results_dir, r)
            stored.add(f)
            results.append(r)
            log.info("%s %s: %d poles, best %.0f m, %d refinements, %.0fs%s", r["unit"], r["scenario"], len(r["poles"]),
                     r["poles"][0]["dist_m"] if r["poles"] else 0, r["refinements"], r["duration_s"],
                     f" ({r['reason']})" if r["reason"] else "")

        def drain() -> None:
            """Every job that finished but was not consumed yet, cached and logged: it is paid for.

            The write is guarded because this runs while an error is already on its way out, and the
            failure this whole path exists for is a machine out of memory with swap eating the disk,
            which is exactly when a write fails. An OSError here would replace the error being reported
            and abandon the results still to drain, so it is logged against its job and the drain goes on.
            """
            for f in futures:
                if f not in stored and not f.cancelled() and f.exception() is None:
                    try:
                        take(f)
                    except OSError as exc:
                        job = jobs[f]
                        log.error("unit %s scenario %s finished but its result could not be cached (%s); "
                                  "the rerun searches it again", job.unit.code, job.scenario, exc)

        try:
            for f in as_completed(futures):
                take(f)
        except BrokenProcessPool as exc:
            drain()
            # Every job with no stored result: the one the dead worker held plus everything still queued.
            # `f.done()` cannot say which is which, because a pool tearing down marks every remaining
            # future with this same error before the first `result()` call sees it.
            lost = [jobs[f] for f in futures if f not in stored]
            named = ", ".join(f"unit {j.unit.code} scenario {j.scenario}" for j in lost[:5])
            more = f" and {len(lost) - 5} more" if len(lost) > 5 else ""
            raise PolesError(f"a worker process died with {named}{more} in flight; {len(results)} of "
                             f"{len(pending)} searched jobs are cached and a rerun resumes there. Lower "
                             f"POLES_WORKERS (now {workers}) if the machine ran out of memory") from exc
        except Exception:
            # Any error out of a worker ends the stage, a PolesError and a MemoryError alike, but the jobs
            # already running are paid for: drop the queue, wait the running ones out and cache what they
            # return, then re-raise the original. Without this the queue runs to the end inside
            # `pool.__exit__` before the traceback appears, and a finished result is lost with it.
            for f in futures:
                f.cancel()
            drain()
            raise
    return results


def attribute_places(results: list[dict], places_vrt: Path, results_dir: Path, log: logging.Logger) -> None:
    """Fill `nearest_place` of every pole from the places layer, loaded once.

    This runs in the parent after the searches, so a missing layer costs nothing that was paid for: the
    searched results are cached under `results_dir` and the rerun that follows the layer's return attributes
    them without searching again. The lookup reads the pole's published coordinates (rounded to six
    decimals, under a decimetre), which is what a re-attribution from the cache reads too.
    """
    if not places_vrt.is_file():
        raise PolesError(f"poles: {places_vrt} is missing, so the {len(results)} searched job(s) cannot be attributed "
                         f"to their nearest place; every one of them is cached under {results_dir}, so restore the "
                         "extract stage's places layer and rerun: the attribution then runs on its own")
    places = Places(places_vrt)
    for r in results:
        for p in r["poles"]:
            p["nearest_place"] = places.nearest(p["lon"], p["lat"])
    log.info("attributed %d pole(s) to their nearest place from %s", sum(len(r["poles"]) for r in results), places_vrt.name)


def run(cfg: RegionConfig, ws: Workspace, log: logging.Logger) -> dict:
    prepared = prepare(cfg, ws, log)
    out, grid_dir = ws.dir(STAGE), ws.dir("grid")
    if not prepared.places.is_file():
        log.warning("%s is missing: the searches run and are cached, and the stage stops before writing its "
                    "output; rerun once the places layer is back", prepared.places)
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
        fresh = _search_pending(pending, results_dir, workers, log)
        results.extend(fresh)
        searched = len(fresh)
    attribute_places(results, prepared.places, results_dir, log)
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
