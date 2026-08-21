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
        country = country_of(area, countries)
        if country is None:
            if area.level == 2 and area.code is None:
                continue  # "land mass" style relations without a code are not countries
            raise UnitsError(f"unit relation {area.osm_id} ({area.name}) has no country")
        if not cfg.is_unit_country(country):
            continue
        if not area.code:
            raise UnitsError(f"unit relation {area.osm_id} ({area.name}) has no {cfg.unit_code_tag} code")
        code = area.code.lower()
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
    write(str(path), geometry=np.array([shapely.to_wkb(u.geometry) for u in units], dtype=object),
          field_data=[np.array([u.code for u in units], dtype=object), np.array([u.name_en for u in units], dtype=object),
                      np.array([u.country for u in units], dtype=object), np.array([u.index for u in units], dtype=np.int32),
                      np.array([int(u.transcontinental) for u in units], dtype=np.int32)],
          fields=["code", "name_en", "country", "idx", "transcontinental"], layer="units", driver="FlatGeobuf",
          geometry_type="MultiPolygon", crs="EPSG:4326")
    return path


def rasterize_units(units_fgb: Path, frame: Frame, land_tif: Path, out_tif: Path, log: logging.Logger,
                    workdir: Path) -> dict[int, int]:
    """int16 unit index per cell (cell-centre rule, later units overwrite earlier ones on shared edges), ANDed with land.

    Returns the land cell count of every index in the layer, zero included: a unit too small to hold a cell
    centre must still show up, so the caller can fall back to `unit_cells`."""
    tools_log = Path(workdir) / "tools.log"
    create_raster(frame, out_tif, dtype="int16")
    run_cmd(["gdal_rasterize", "--config", "GDAL_CACHEMAX", "4096", "-a", "idx", "-l", "units", units_fgb, out_tif],
            log, stderr_path=tools_log)
    _, _, _, fields = read(str(units_fgb), layer="units", columns=["idx"], read_geometry=False)
    counts: dict[int, int] = {int(i): 0 for i in fields[0]}
    with rasterio.open(out_tif, "r+") as units, rasterio.open(land_tif) as land:
        for _, window in units.block_windows(1):
            u = units.read(1, window=window)
            u[land.read(1, window=window) == 0] = 0
            units.write(u, 1, window=window)
            ids, n = np.unique(u[u > 0], return_counts=True)
            for i, c in zip(ids.tolist(), n.tolist()):
                counts[i] = counts.get(i, 0) + c
    return counts


def unit_cells(units_tif: Path, unit: Unit, frame: Frame, log: logging.Logger, workdir: Path,
               window: Window | None = None) -> tuple[np.ndarray, np.ndarray]:
    """(rows, cols) of the unit's cells, in whole-raster coordinates. A unit too small to hold a cell centre
    (a microstate) gets the cells its polygon touches instead, so it still has candidates; its refinement is
    masked to the polygon anyway.

    `window` restricts both the read and the all-touched fallback to that box of the frame, so a caller that
    already knows where the unit sits never pays for the whole raster (1.35 GB at the Europe frame). The
    returned indices stay absolute whatever the window."""
    row_off = int(window.row_off) if window is not None else 0
    col_off = int(window.col_off) if window is not None else 0
    with rasterio.open(units_tif) as ds:
        rows, cols = np.nonzero(ds.read(1, window=window) == unit.index)
    if len(rows):
        return rows + row_off, cols + col_off
    log.warning("unit %s has no cell centre on the %g m grid; using all-touched cells", unit.code, frame.res)
    sub = frame if window is None else Frame(frame.crs, frame.res, frame.x0 + col_off * frame.res,
                                             frame.y1 - row_off * frame.res, int(window.width), int(window.height))
    tmp_fgb = Path(workdir) / f"unit-{unit.code}.fgb"
    tmp_fgb.unlink(missing_ok=True)
    write_units([unit], tmp_fgb)
    tmp_tif = Path(workdir) / f"unit-{unit.code}.tif"
    create_raster(sub, tmp_tif)
    rasterize(tmp_fgb, "units", tmp_tif, log, Path(workdir) / "tools.log", burn=1, all_touched=True)
    with rasterio.open(tmp_tif) as ds:
        rows, cols = np.nonzero(ds.read(1))
    tmp_fgb.unlink(missing_ok=True)
    tmp_tif.unlink(missing_ok=True)
    if not len(rows):
        raise UnitsError(f"unit {unit.code} touches no cell of the frame")
    return rows + row_off, cols + col_off
