"""Units: the admin areas that get a pole and a rank (spec 2.2), and their raster on the coarse frame."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
import shapely
from pyogrio.raw import read, write
from rasterio.windows import Window
from shapely.geometry import MultiPolygon, box
from shapely.geometry.base import BaseGeometry

from .boundaries import AdminArea
from .config import RegionConfig
from .errors import PolesError
from .grid import Frame, create_raster, rasterize
from .shell import run_cmd

MIN_INSIDE_FRACTION = 0.5  # at least half of a country must lie inside the primary source polygons to be a unit
MAX_UNITS = 32000  # the int16 unit raster carries the unit index, so the index must fit an int16
MARKER = ".ok"

_LOG = logging.getLogger(__name__)


class UnitsError(PolesError):
    pass


@dataclass
class Unit:
    code: str
    name: str | None
    name_en: str | None
    osm_id: int
    country: str
    geometry: MultiPolygon
    transcontinental: bool
    index: int
    area_km2: float = 0.0
    cells: int = 0
    closed_by_edge: bool = False


def _multi(geom: BaseGeometry) -> MultiPolygon:
    if geom.geom_type == "Polygon":
        return MultiPolygon([geom])
    if geom.geom_type == "GeometryCollection":
        return MultiPolygon([p for g in geom.geoms for p in (g.geoms if g.geom_type == "MultiPolygon" else [g]) if p.geom_type == "Polygon"])
    return geom


def apply_territory_mask(geom: BaseGeometry, masks: list[dict]) -> MultiPolygon:
    """The geometry minus every mask bbox, so a country keeps only its main territory (spec 2.2)."""
    for mask in masks:
        w, s, e, n = mask["bbox"]
        geom = geom.difference(box(w, s, e, n))
    return _multi(geom)


def inside_fraction(geom: BaseGeometry, region: BaseGeometry) -> float:
    return 0.0 if geom.area == 0 else geom.intersection(region).area / geom.area


def country_of(area: AdminArea, countries: list[AdminArea]) -> str | None:
    """The lowercase country code the area belongs to: its own at level 2, else the level-2 area holding it."""
    if area.level == 2:
        return area.code.lower() if area.code else None
    point = area.geometry.representative_point()
    for c in countries:
        if c.level == 2 and c.code and c.geometry.contains(point):
            return c.code.lower()
    return None


def select_units(areas: list[AdminArea], cfg: RegionConfig, primary: BaseGeometry,
                 log: logging.Logger | None = None) -> list[Unit]:
    """The areas that become units, sorted by code and numbered from 1.

    A country whose territory is mostly outside the primary source polygons is a supplement country: it
    supplies roads, not units. Codes are lowercased here, so a unit code is `lt` or `us-ak` whatever the
    OSM tag looks like."""
    log = log or _LOG
    countries = [a for a in areas if a.level == 2]
    units: list[Unit] = []
    for area in areas:
        if area.level != cfg.unit_admin_level:
            continue
        if inside_fraction(area.geometry, primary) < MIN_INSIDE_FRACTION:
            continue
        code = area.code.lower() if area.code else None
        country = country_of(area, countries)
        if country is None:
            if area.level == 2 and code is None:
                continue  # "land mass" style relations without a code are not countries
            # A unit whose country is missing from the extract, or whose country outline the assembler
            # could not close, is one unit short, not a dead run: the whole list of orphans is worth
            # more than the first one. expected_units below and validate's check 7 catch the shortfall
            # (issue #22).
            log.warning("units: relation %d (%s, code %s) has no country in the extract; skipped",
                        area.osm_id, area.name, code)
            continue
        if not cfg.is_unit_country(country):
            continue
        if not code:
            raise UnitsError(f"unit relation {area.osm_id} ({area.name}) has no {cfg.unit_code_tag} code")
        geom = apply_territory_mask(area.geometry, cfg.territory_mask)
        if geom.is_empty:
            raise UnitsError(f"unit {code}: the territory mask removed everything")
        if not area.complete:
            log.warning("unit %s: relation %d is missing member ways, so its outline is %s", code, area.osm_id,
                        "closed along the data edge" if area.closed_by_edge else "whatever the present ways enclose")
        units.append(Unit(code, area.name, area.name_en, area.osm_id, country, geom, code in cfg.transcontinental, 0,
                          closed_by_edge=area.closed_by_edge))
    units.sort(key=lambda u: u.code)
    for i, u in enumerate(units, start=1):
        u.index = i
    if cfg.expected_units is not None and len(units) != cfg.expected_units:
        raise UnitsError(f"expected {cfg.expected_units} units, found {len(units)}: {' '.join(u.code for u in units)}")
    if len(units) > MAX_UNITS:
        raise UnitsError(f"more than {MAX_UNITS} units do not fit the int16 unit raster")
    return units


def write_units(units: list[Unit], path: Path) -> Path:
    """Every field a resume needs: a run that finds units.fgb done rebuilds its units from this file alone,
    so anything left out here is null for the rest of that run (cells and area_km2 excepted, since they come
    from the raster)."""
    write(str(path), geometry=np.array([shapely.to_wkb(u.geometry) for u in units], dtype=object),
          field_data=[np.array([u.code for u in units], dtype=object), np.array([u.name for u in units], dtype=object),
                      np.array([u.name_en for u in units], dtype=object), np.array([u.osm_id for u in units], dtype=np.int64),
                      np.array([u.country for u in units], dtype=object), np.array([u.index for u in units], dtype=np.int32),
                      np.array([int(u.transcontinental) for u in units], dtype=np.int32),
                      np.array([int(u.closed_by_edge) for u in units], dtype=np.int32)],
          fields=["code", "name", "name_en", "osm_id", "country", "idx", "transcontinental", "closed_by_edge"],
          layer="units", driver="FlatGeobuf", geometry_type="MultiPolygon", crs="EPSG:4326")
    return path


def low_tif(units_tif: Path) -> Path:
    """The companion raster beside `units_tif`: same cells, lowest unit index instead of highest."""
    return units_tif.with_name(units_tif.stem + "_low" + units_tif.suffix)


def _done(path: Path) -> bool:
    return path.exists() and path.with_name(path.name + MARKER).exists()


def _mark(path: Path) -> None:
    path.with_name(path.name + MARKER).touch()


def _land_touched(land_src: Path, frame: Frame, out_tif: Path, log: logging.Logger, tools_log: Path) -> Path:
    """1 where a land polygon touches the cell at all, not merely where one covers its centre."""
    if _done(out_tif):
        return out_tif
    create_raster(frame, out_tif)
    rasterize(land_src, "land", out_tif, log, tools_log, burn=1, all_touched=True)
    _mark(out_tif)
    return out_tif


def _water_interior(water_src: Path, frame: Frame, out_tif: Path, log: logging.Logger, tools_log: Path) -> Path:
    """1 only where big water fills the cell: the centre rule, minus every cell a water outline touches.

    A cell the shore crosses holds land as well as water, so it stays a candidate; only a cell with nothing
    but water in it is dropped. `-nlt MULTILINESTRING` is GDAL's own polygon-to-boundary conversion (every
    ring, holes included), which keeps this to two rasterize passes and needs no SQL dialect."""
    if _done(out_tif):
        return out_tif
    create_raster(frame, out_tif)
    rasterize(water_src, "water", out_tif, log, tools_log, burn=1)
    lines = out_tif.with_name(out_tif.stem + "_outline.fgb")
    lines.unlink(missing_ok=True)
    run_cmd(["ogr2ogr", "-f", "FlatGeobuf", lines, water_src, "-nln", "water", "-nlt", "MULTILINESTRING"],
            log, stderr_path=tools_log)
    rasterize(lines, "water", out_tif, log, tools_log, burn=0, all_touched=True)
    lines.unlink(missing_ok=True)
    _mark(out_tif)
    return out_tif


def _burn_units(units_fgb: Path, frame: Frame, out_tif: Path, order: str, log: logging.Logger, tools_log: Path) -> Path:
    """The unit index of every cell the unit polygons touch, the last feature burnt winning a shared cell.

    FlatGeobuf hands features back in packed R-tree order, so which unit wins a shared cell would otherwise
    be an accident of the index; ORDER BY makes it the highest or the lowest index, on purpose."""
    create_raster(frame, out_tif, dtype="int16")
    run_cmd(["gdal_rasterize", "--config", "GDAL_CACHEMAX", "4096", "-at", "-a", "idx",
             "-sql", f"SELECT idx FROM units ORDER BY idx {order}", units_fgb, out_tif], log, stderr_path=tools_log)
    return out_tif


def rasterize_units(units_fgb: Path, frame: Frame, land_src: Path, water_src: Path, out_tif: Path,
                    log: logging.Logger, workdir: Path) -> dict[int, int]:
    """The candidate cells of every unit, as two int16 rasters, plus the cell count of every index.

    A candidate cell is every cell the unit's allowed land touches: touched(unit) and touched(land) and not
    interior(big water). A cell is dropped only when big water fills it, so every point of unit land outside
    big water lies in a candidate cell of its unit, whatever the frame's origin: that is what makes the
    search find the same maximum on a grid shifted by half a cell (DECISIONS, check 4). The bound in
    `candidates.py` holds for any point of a searched cell and the refinement is masked to the unit polygon,
    so an over-inclusive cell costs a refinement and cannot produce a pole outside the unit.

    One int16 raster can name one owner per cell, and a border or coastal cell is often touched by two
    units. `out_tif` therefore names the highest index touching a cell and its `low_tif` companion the
    lowest, and `unit_cells` reads a unit's cells as the union of the two: a pair of neighbours both keep a
    cell they share. Only a cell three or more units touch can drop one, at a tri-point.

    The land and water masks are frame-specific intermediates and are kept beside `out_tif` with `.ok`
    markers, so a resume rebuilds neither. Counts are of the union, one entry per index in the layer, zero
    included, and they are what units.json publishes as `cells`."""
    tools_log = Path(workdir) / "tools.log"
    land_tif = _land_touched(land_src, frame, out_tif.with_name(out_tif.stem + "_land.tif"), log, tools_log)
    water_tif = _water_interior(water_src, frame, out_tif.with_name(out_tif.stem + "_water.tif"), log, tools_log)
    _burn_units(units_fgb, frame, out_tif, "ASC", log, tools_log)
    _burn_units(units_fgb, frame, low_tif(out_tif), "DESC", log, tools_log)
    _, _, _, fields = read(str(units_fgb), layer="units", columns=["idx"], read_geometry=False)
    counts: dict[int, int] = {int(i): 0 for i in fields[0]}
    with rasterio.open(out_tif, "r+") as hi, rasterio.open(low_tif(out_tif), "r+") as lo, \
            rasterio.open(land_tif) as land, rasterio.open(water_tif) as water:
        for _, window in hi.block_windows(1):
            keep = (land.read(1, window=window) > 0) & (water.read(1, window=window) == 0)
            high, low = hi.read(1, window=window), lo.read(1, window=window)
            high[~keep] = 0
            low[~keep] = 0
            hi.write(high, 1, window=window)
            lo.write(low, 1, window=window)
            for i in np.unique(np.concatenate((high[high > 0], low[low > 0]))).tolist():
                counts[i] = counts.get(i, 0) + int(((high == i) | (low == i)).sum())
    return counts


def unit_cells(units_tif: Path, unit: Unit, window: Window | None = None) -> tuple[np.ndarray, np.ndarray]:
    """(rows, cols) of the unit's candidate cells, in whole-raster coordinates.

    The union of the two rasters `rasterize_units` writes, so a cell shared with a neighbour belongs to
    both. `window` restricts the read to that box of the frame, so a caller that already knows where the
    unit sits never pays for the whole raster (1.35 GB at a continent-sized frame); the returned indices
    stay absolute whatever the window."""
    row_off = int(window.row_off) if window is not None else 0
    col_off = int(window.col_off) if window is not None else 0
    with rasterio.open(units_tif) as ds:
        mask = ds.read(1, window=window) == unit.index
    with rasterio.open(low_tif(units_tif)) as ds:
        mask |= ds.read(1, window=window) == unit.index
    rows, cols = np.nonzero(mask)
    if not len(rows):
        raise UnitsError(f"unit {unit.code} has no candidate cell in {units_tif.name}"
                         + (f" inside {window}" if window is not None else "")
                         + ": no cell of the frame is touched by both the unit and a land polygon")
    return rows + row_off, cols + col_off
