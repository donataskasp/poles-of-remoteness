"""Detail rasters: exact vector distances on a 50 m lattice around each published pole (spec 3.5), computed in
the pole's UTM zone from the stage-2 road tiles, classed with the shared table, written as single-band PNGs
with a six-field georeference sidecar.

The lattice is in lon/lat so the site can place it with six numbers and no projection code, but every
distance is measured in the pole's UTM zone: the pixel centres are projected there and asked for their
nearest road with one STRtree query, the same measurement the stage-2 refinement makes, at 50 m instead of
5 m and over a 20 km window instead of a 500 m one.

One job is one unit and one scenario, so the poles of a unit share a road cache and a worker process. The
sidecar is written after the PNG and is therefore the completion marker of the pair: a PNG without its JSON
is half a raster and is redone.
"""
from __future__ import annotations

import json
import logging
import math
import os
import shutil
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import rasterio
import shapely
from pyogrio.raw import read
from pyproj import Transformer
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from ..classes import EDGE, NODATA, ClassTable
from ..classify import where_clause
from ..config import RegionConfig
from ..errors import PolesError
from ..poles import SCENARIOS
from ..refine import RoadCache, UtmRoads, utm_epsg
from ..roads import RoadTiles
from ..workspace import Workspace
from .tiles import _ungeoreferenced

M_PER_DEG = 111_320.0
# Roads are queried for the window grown by the pole's own distance, the window's half diagonal and a
# kilometre of slack: every road that can be nearest to any pixel of the window is inside that box.
QUERY_SLACK_M = 1_000.0
# The land test only has to cover the window itself; a kilometre of margin keeps it clear of rounding.
LAND_SLACK_M = 1_000.0
# How far the nearest land may be from a pole whose window came out empty. A published coordinate is stored
# to six decimals, which can put a pole a few centimetres off the islet it stands on, so the test cannot be
# "on land"; a hundred metres is three orders of magnitude above that rounding and still nowhere near the
# kilometres of open water that a wrong land index would show.
BLANK_LAND_TOL_M = 100.0


@dataclass(frozen=True)
class Georef:
    """The six numbers the site needs to place a detail raster: north-west pixel corner and pixel size in
    degrees, plus the pixel counts. No CRS field: a detail raster is always EPSG:4326."""

    west: float
    north: float
    dlon: float
    dlat: float
    width: int
    height: int

    def to_dict(self) -> dict:
        return asdict(self)


def georef(lat: float, lon: float, res_m: float, window_m: float) -> Georef:
    """A window_m square of res_m pixels centred on the pole, in degrees (spec 3.5).

    dlon widens with the latitude so the pixel stays square on the ground; at 78 N it is nearly five times
    dlat. Both are constant over one window, which is a few kilometres of latitude at most."""
    dlat = res_m / M_PER_DEG
    dlon = dlat / math.cos(math.radians(lat))
    n = int(round(window_m / res_m))
    return Georef(west=lon - dlon * n / 2, north=lat + dlat * n / 2, dlon=dlon, dlat=dlat, width=n, height=n)


def centres(g: Georef) -> tuple[np.ndarray, np.ndarray]:
    """Pixel centre longitudes (width of them) and latitudes (height of them), north to south."""
    lons = g.west + g.dlon * (np.arange(g.width) + 0.5)
    lats = g.north - g.dlat * (np.arange(g.height) + 0.5)
    return lons, lats


def land_test(land_idx: Path, water_big: Path, bbox: tuple[float, float, float, float]):
    """Point on a land polygon and in no water polygon of 1 km2 or more; the unit boundary does not matter here,
    a neighbour's land shows its distances too."""
    _, _, lwkb, _ = read(str(land_idx), layer="land", bbox=bbox)
    _, _, wwkb, _ = read(str(water_big), layer="water", bbox=bbox)
    land_tree = STRtree(shapely.from_wkb(lwkb)) if len(lwkb) else None
    water_tree = STRtree(shapely.from_wkb(wwkb)) if len(wwkb) else None

    def ok(lons, lats):
        lons, lats = np.asarray(lons, dtype=np.float64), np.asarray(lats, dtype=np.float64)
        out = np.zeros(len(lons), bool)
        if land_tree is None:
            return out
        pts = shapely.points(lons, lats)
        out[np.unique(land_tree.query(pts, predicate="within")[0])] = True
        if water_tree is not None:
            wet = np.zeros(len(lons), bool)
            wet[np.unique(water_tree.query(pts, predicate="within")[0])] = True
            out &= ~wet
        return out

    return ok


def classify_window(g: Georef, roads: UtmRoads, land_ok, edge_band: BaseGeometry | None,
                    table: ClassTable) -> np.ndarray:
    """Class index per pixel of the window: distance to the nearest road, then the band, then the mask.

    NODATA off land beats EDGE beats the class, as the explore raster orders them in raster.quantise. An
    empty road set leaves every land pixel in the open-ended top class; `render` refuses that case for a
    published pole, whose own nearest way is inside its window by construction."""
    lons, lats = centres(g)
    glon, glat = np.meshgrid(lons, lats)
    flat_lon, flat_lat = glon.ravel(), glat.ravel()
    if roads.tree is None:
        cls = table.to_class(np.full(flat_lon.size, float(table.edges[-1])))
    else:
        tr = Transformer.from_crs("EPSG:4326", f"EPSG:{roads.epsg}", always_xy=True)
        x, y = tr.transform(flat_lon, flat_lat)
        pts = shapely.points(np.asarray(x), np.asarray(y))
        idx = roads.tree.nearest(pts)
        dist = shapely.distance(pts, roads.geoms[idx])
        # The table's last class is open ended but searchsorted is not: a distance past the last edge would
        # land on EDGE. Clamp it onto the edge itself, which is the top class.
        cls = table.to_class(np.minimum(dist, table.edges[-1]))
    if edge_band is not None and not edge_band.is_empty:
        # The band is one ring around the whole region, so its bounds reject only a window well outside it;
        # the pass that follows is cheap anyway, because contains_xy on a prepared geometry answers the
        # 160,000 pixels of a production window in about 10 ms (measured against a 55,000 vertex band).
        w, s, e, n = edge_band.bounds
        if w <= flat_lon.max() and e >= flat_lon.min() and s <= flat_lat.max() and n >= flat_lat.min():
            shapely.prepare(edge_band)
            cls[shapely.contains_xy(edge_band, flat_lon, flat_lat)] = EDGE
    cls[~land_ok(flat_lon, flat_lat)] = NODATA
    return cls.reshape(g.height, g.width)


def write_detail(out_dir: Path, code: str, scenario: str, rank: int, arr: np.ndarray, g: Georef) -> tuple[Path, Path]:
    """One raster as <out_dir>/<code>/<scenario>-<rank>.png plus its sidecar, the sidecar last: the pair is
    only complete when the JSON is there, so a run killed mid-write is redone rather than published."""
    d = out_dir / code
    d.mkdir(parents=True, exist_ok=True)
    png, js = d / f"{scenario}-{rank}.png", d / f"{scenario}-{rank}.json"
    js.unlink(missing_ok=True)
    with _ungeoreferenced(), rasterio.open(png, "w", driver="PNG", width=g.width, height=g.height, count=1,
                                           dtype="uint8", ZLEVEL=9) as ds:
        ds.write(arr.astype(np.uint8), 1)
    aux = Path(str(png) + ".aux.xml")
    if aux.exists():
        aux.unlink()
    js.write_text(json.dumps(g.to_dict()) + "\n", encoding="utf-8")
    return png, js


@dataclass(frozen=True)
class DetailJob:
    """One unit and one scenario, as plain data: every field pickles to a worker process."""

    roads_dir: str
    land_idx: str
    water_big: str
    out_dir: str
    code: str
    scenario: str
    poles: tuple            # ((rank, lat, lon, dist_m), ...) of one unit and scenario
    res_m: float
    window_m: float
    edge_wkb: bytes
    # The region's class edges travel with the job: a worker that built its own default table would class a
    # region's detail rasters differently from its explore tiles the day a region sets class_table.
    class_edges: tuple


_TILES: dict[str, RoadTiles] = {}


def _tiles(path: str) -> RoadTiles:
    """One tile index per worker process and path: reading tiles.json again per job would be waste."""
    if path not in _TILES:
        _TILES[path] = RoadTiles(Path(path))
    return _TILES[path]


def _pad_bbox(g: Georef, lat: float, pad_m: float) -> tuple[float, float, float, float]:
    """The window grown by pad_m on all four sides, in degrees.

    The longitude pad uses the cosine of the pole's latitude, so a corner of the box is a little short of
    pad_m once the meridians converge across the window; QUERY_SLACK_M (1 km) covers that corner error for
    windows up to 78 N with poles out to 100 km (measured against a geodesic: 966 m of margin left at 71 N,
    406 m at 78 N with a 100 km pole, negative only past 80 N with a 150 km one). A region reaching into the
    high Arctic needs a geodesic pad here, which is tracked as its own issue."""
    dlat = pad_m / M_PER_DEG
    dlon = dlat / math.cos(math.radians(lat))
    return g.west - dlon, g.north - g.dlat * g.height - dlat, g.west + g.dlon * g.width + dlon, g.north + dlat


def _nearest_land_m(land_idx: Path, bbox: tuple[float, float, float, float], lon: float, lat: float) -> float:
    """Distance from the pole to the nearest land polygon of the window's own read, inf when it returns none.

    Degrees are scaled by the metres of one degree of latitude, which overstates any longitude component and
    so is an upper bound on the true distance; the caller's tolerance is far above the rounding it forgives.
    Read again rather than kept from land_test, because this runs only on a window that came out empty."""
    _, _, wkb, _ = read(str(land_idx), layer="land", bbox=bbox)
    if not len(wkb):
        return math.inf
    geoms = shapely.from_wkb(wkb)
    pt = shapely.points([lon], [lat])
    return float(shapely.distance(pt, geoms[STRtree(geoms).nearest(pt)])[0]) * M_PER_DEG


def render(job: DetailJob) -> dict:
    """One unit and scenario: its poles in rank order share the road cache."""
    t0 = time.monotonic()
    table = ClassTable(list(job.class_edges))
    edge_band = shapely.from_wkb(job.edge_wkb) if job.edge_wkb else None
    cache = RoadCache(_tiles(job.roads_dir), where_clause(job.scenario), pad_deg=0.0)
    out_dir = Path(job.out_dir)
    done, warned, total_bytes, skipped = [], [], 0, 0
    for rank, lat, lon, dist_m in job.poles:
        png = out_dir / job.code / f"{job.scenario}-{rank}.png"
        js = out_dir / job.code / f"{job.scenario}-{rank}.json"
        if png.exists() and js.exists():
            skipped += 1
            total_bytes += png.stat().st_size
            continue
        g = georef(lat, lon, job.res_m, job.window_m)
        half_diag = math.hypot(g.width * job.res_m, g.height * job.res_m) / 2
        roads = cache.get(*_pad_bbox(g, lat, dist_m + half_diag + QUERY_SLACK_M), utm_epsg(lon, lat))
        if roads.tree is None:
            raise PolesError(f"detail {job.code} {job.scenario} rank {rank}: no road within "
                             f"{dist_m + half_diag + QUERY_SLACK_M:.0f} m of the pole at lon {lon:.4f}, lat "
                             f"{lat:.4f}, but its own nearest way is {dist_m:.0f} m away and must be in there; "
                             f"the road tiles or the published pole are out of step")
        land_bbox = _pad_bbox(g, lat, LAND_SLACK_M)
        land_ok = land_test(Path(job.land_idx), Path(job.water_big), land_bbox)
        arr = classify_window(g, roads, land_ok, edge_band, table)
        if not (arr != NODATA).any():
            # A window with no land pixel at all is either an islet narrower than one pixel, which is a real
            # top-ten pole in a sea region (Bell Rock is 14 m across), or a land index that does not cover this
            # place, which would blank every raster of the run. The distance from the pole to the nearest land
            # tells the two apart at once, before a thousand empty PNGs are published.
            near_m = _nearest_land_m(Path(job.land_idx), land_bbox, lon, lat)
            if near_m > BLANK_LAND_TOL_M:
                raise PolesError(f"detail {job.code} {job.scenario} rank {rank}: no land pixel in the window "
                                 f"around the pole at lon {lon:.4f}, lat {lat:.4f}, and the nearest land in the "
                                 f"index is {near_m:.0f} m away, though the pole was searched on land; the land "
                                 f"index or the water file is the wrong one, or its bbox went in the wrong order")
            warned.append(f"{job.code} {job.scenario} rank {rank}: no land pixel in the window, the pole at lon "
                            f"{lon:.4f}, lat {lat:.4f} sits on an islet narrower than one pixel")
        png, _ = write_detail(out_dir, job.code, job.scenario, rank, arr, g)
        total_bytes += png.stat().st_size
        done.append(rank)
    return {"code": job.code, "scenario": job.scenario, "rendered": done, "skipped": skipped, "bytes": total_bytes,
            "warnings": warned, "seconds": time.monotonic() - t0}


def _published_set(jobs: list[DetailJob]) -> list[list]:
    """What a complete render covers, as sorted plain data: the fingerprint of the detail directory."""
    return sorted([job.scenario, job.code, rank, lat, lon] for job in jobs for rank, lat, lon, _ in job.poles)


def run_detail(cfg: RegionConfig, ws: Workspace, published: dict[str, list[dict]], table: ClassTable,
               edge_band_4326: BaseGeometry | None, log: logging.Logger) -> dict:
    """A detail raster for every published pole, over a process pool."""
    poles_dir, out_dir = ws.dir("poles"), ws.dir("publish") / "detail"
    edge_wkb = shapely.to_wkb(edge_band_4326) if edge_band_4326 is not None else b""
    jobs = []
    for scenario in SCENARIOS:
        for unit in published.get(scenario, []):
            if not unit["poles"]:
                continue
            jobs.append(DetailJob(str(poles_dir / "roads"), str(poles_dir / "land_idx.fgb"),
                                  str(poles_dir / "water_big.fgb"), str(out_dir), unit["unit"], scenario,
                                  tuple((p["rank"], p["lat"], p["lon"], p["dist_m"]) for p in unit["poles"]),
                                  cfg.detail_res_m, cfg.detail_window_m, edge_wkb, tuple(table.edges)))
    # A raster is named by its rank and kept when the file is already there, so a rerun after validate excluded a
    # different set would leave the old rank 1 image under the new rank 1's name: the right file name over the
    # wrong place, and nothing to raise. The stamp records the set the directory was built for; when it does not
    # match what is about to be rendered, the whole directory goes. It is written after the rmtree and before the
    # render, not after: the files present are always a subset of the stamped set, which a resume completes, while
    # a stamp written only on success would leave a crashed run unstamped and its stale files invisible to the
    # next run with a different set.
    stamp, wanted = out_dir / "published.json", _published_set(jobs)
    stale = stamp.exists() and json.loads(stamp.read_text(encoding="utf-8")) != wanted
    if (ws.forced or stale) and out_dir.exists():
        if stale:
            log.info("publish: the published pole set changed since the last detail run, rebuilding detail/")
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp.write_text(json.dumps(wanted) + "\n", encoding="utf-8")
    workers = int(os.environ.get("POLES_WORKERS", "0")) or 4
    log.info("publish: %d detail jobs on %d workers", len(jobs), workers)
    t0 = time.monotonic()
    count = skipped = total_bytes = blank = 0
    if jobs:
        finished = 0
        try:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                for r in pool.map(render, jobs, chunksize=1):
                    count += len(r["rendered"]) + r["skipped"]
                    skipped += r["skipped"]
                    total_bytes += r["bytes"]
                    finished += 1
                    for w in r["warnings"]:
                        blank += 1
                        log.warning("publish: detail %s", w)
                    log.info("publish: detail %s %s: %d rendered, %d kept, %.0f s", r["code"], r["scenario"],
                             len(r["rendered"]), r["skipped"], r["seconds"])
        except BrokenProcessPool as exc:
            stalled = jobs[min(finished, len(jobs) - 1)]
            raise PolesError(f"a worker process died with unit {stalled.code} scenario {stalled.scenario} in "
                             f"flight; {finished} of {len(jobs)} detail jobs are written and a rerun resumes "
                             f"there. Lower POLES_WORKERS (now {workers}) if the machine ran out of memory") from exc
    if blank:
        log.warning("publish: %d detail rasters are all nodata, their poles sit on sub-pixel islets", blank)
    return {"count": count, "bytes": total_bytes, "seconds": round(time.monotonic() - t0, 1), "skipped": skipped}
