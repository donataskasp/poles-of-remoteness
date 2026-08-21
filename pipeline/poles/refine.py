"""Exact refinement of a coarse candidate: the farthest point from any road on a 25 m then 5 m grid in the
candidate's UTM zone (spec 2.4, same method as the Lithuania demo).

The distance is a true vector distance from a grid point to the nearest road geometry, not a raster
sample, so the published number no longer carries the coarse grid's quantisation. Both passes stay
inside the cell the caller names (centre plus half_m): the coarse pass sweeps it at 25 m, the fine pass
re-centres on the coarse winner at 5 m and is clipped back to the same window, because a point outside
the cell belongs to a neighbouring cell that the branch-and-bound in candidates.py bounds separately.

A cell near a zone seam is refined wholly in the zone its centre falls in; UTM stays well behaved a few
hundred metres past its seam (a few parts per million of scale error over a 500 m window), so no cell
needs two zones.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
import shapely
from pyproj import Transformer
from shapely.strtree import STRtree

from .roads import RoadSet


def utm_epsg(lon: float, lat: float) -> int:
    """EPSG of the UTM zone holding lon/lat. No Norway or Svalbard exceptions: they widen zones for grid
    conventions, and a distance measured a degree outside the nominal zone is unaffected."""
    zone = min(60, max(1, int(math.floor((lon + 180.0) / 6.0)) + 1))
    return (32600 if lat >= 0 else 32700) + zone


@dataclass
class RefinedPole:
    lat: float
    lon: float
    dist_m: float
    way_id: int
    x: float
    y: float
    utm_epsg: int
    way_index: int


class UtmRoads:
    """A RoadSet projected to one UTM zone with its STRtree, built once per cached bbox."""

    def __init__(self, roads: RoadSet, epsg: int):
        self.roads = roads
        self.epsg = epsg
        tr = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
        self.geoms = (shapely.transform(roads.geoms, lambda c: np.column_stack(tr.transform(c[:, 0], c[:, 1])))
                      if len(roads) else np.array([], dtype=object))
        self.tree = STRtree(self.geoms) if len(roads) else None
        self.to_lonlat = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)


def _axis(centre: float, half: float, step: float, lo: float, hi: float) -> np.ndarray:
    """Grid axis of `step` around `centre`, clipped to [lo, hi]. The count is taken from the clipped span
    rather than filtering an arange, so no float overshoot can put a sample past `hi`."""
    start = max(centre - half, lo)
    stop = min(centre + half, hi)
    n = int(math.floor((stop - start) / step + 1e-9)) + 1
    return start + step * np.arange(n)


def _best_on_grid(cx: float, cy: float, half: float, step: float, window: tuple[float, float, float, float],
                  roads: UtmRoads, allowed) -> tuple[float, float, float, int] | None:
    """Farthest allowed point from any road on the grid of `step` around (cx, cy), inside `window`.

    Returns (x, y, distance, road index), or None when the mask allows no point. Ties are broken by the
    first sample in row-major order, and a point equidistant from two roads takes whichever the tree
    reaches first; both are reproducible for the same road set, which is what a rerun needs.
    """
    ax = _axis(cx, half, step, window[0], window[2])
    ay = _axis(cy, half, step, window[1], window[3])
    gx, gy = np.meshgrid(ax, ay)
    px, py = gx.ravel(), gy.ravel()
    if allowed is not None:
        lons, lats = roads.to_lonlat.transform(px, py)
        keep = np.asarray(allowed(np.asarray(lons), np.asarray(lats)), dtype=bool)
        px, py = px[keep], py[keep]
        if len(px) == 0:
            return None
    pts = shapely.points(px, py)
    idx, dist = roads.tree.query_nearest(pts, return_distance=True, all_matches=False)
    d = np.full(len(pts), -np.inf)
    d[idx[0]] = dist
    nearest = np.full(len(pts), -1)
    nearest[idx[0]] = idx[1]
    k = int(np.argmax(d))
    return float(px[k]), float(py[k]), float(d[k]), int(nearest[k])


def refine(x: float, y: float, src_crs: str, roads: UtmRoads, half_m: float = 250.0, steps: tuple[float, float] = (25.0, 5.0),
           allowed: Callable[[np.ndarray, np.ndarray], np.ndarray] | None = None) -> RefinedPole | None:
    """The exact pole of the cell centred on (x, y) in `src_crs`, or None when nothing there qualifies.

    `allowed(lons, lats)` is the caller's mask (in the unit, on land, clear of large water); the search
    only ever reports a point it accepts. None also comes back for an empty road set.
    """
    if roads.tree is None:
        return None
    if src_crs != f"EPSG:{roads.epsg}":
        cx, cy = Transformer.from_crs(src_crs, f"EPSG:{roads.epsg}", always_xy=True).transform(x, y)
    else:
        cx, cy = x, y
    coarse_step, fine_step = steps
    window = (cx - half_m, cy - half_m, cx + half_m, cy + half_m)
    best = _best_on_grid(cx, cy, half_m, coarse_step, window, roads, allowed)
    if best is None:
        return None
    bx, by, _, _ = best
    # The fine pass reaches one coarse step around the winner, so it covers every point the coarse grid
    # skipped, and the window keeps it inside the cell. It always resamples the winner itself, so the
    # fallback below only ever fires if the mask is not stable between calls.
    fine = _best_on_grid(bx, by, coarse_step, fine_step, window, roads, allowed) or best
    fx, fy, fd, fi = fine
    lon, lat = roads.to_lonlat.transform(fx, fy)
    return RefinedPole(float(lat), float(lon), fd, int(roads.roads.attrs["osm_id"][fi]), fx, fy, roads.epsg, fi)


class RoadCache:
    """Roads for one bbox at a time: refinements of neighbouring cells share one tile query and one projection."""

    def __init__(self, tiles, where: str | None = None, pad_deg: float = 0.2):
        self.tiles, self.where, self.pad_deg = tiles, where, pad_deg
        self._bbox: tuple[float, float, float, float] | None = None
        self._roads: UtmRoads | None = None

    def get(self, west: float, south: float, east: float, north: float, epsg: int) -> UtmRoads:
        b = self._bbox
        if self._roads is not None and self._roads.epsg == epsg and b is not None \
                and b[0] <= west and b[1] <= south and b[2] >= east and b[3] >= north:
            return self._roads
        bbox = (west - self.pad_deg, south - self.pad_deg, east + self.pad_deg, north + self.pad_deg)
        self._roads = UtmRoads(self.tiles.query(*bbox, where=self.where), epsg)
        self._bbox = bbox
        return self._roads
