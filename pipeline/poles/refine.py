"""Exact refinement of a coarse candidate: the farthest point from any road on a 5 m grid in the
candidate's UTM zone (spec 2.4).

The distance is a true vector distance from a grid point to the nearest road geometry, not a raster
sample, so the published number no longer carries the coarse grid's quantisation. The window is swept
once, at the search step the spec names, and the result is by construction the maximum of that sweep.
One sweep is affordable: the window of a 250 m coarse cell is 5,041 points at 5 m, answered in one
vectorised nearest query in a few milliseconds. A cheaper coarse-then-local search was tried first and
dropped, because it lands below the maximum of the window whenever a second ridge competes with the one
it walked up.

The window is the one the caller names: centred on the point given, reaching floor(half_m / step) steps
each way, axis aligned to the UTM grid. Callers pass the half-diagonal of their coarse cell, so the sweep
covers the frame cell to within half a lattice step whatever the rotation between the frame grid and the
UTM grid (a 250 m cell is swept to 175 m of its 176.78 m half-diagonal, and the 1.8 m left over is inside
the lattice's own 2.5 m half-step), and therefore laps a little into the neighbours. That overlap is
harmless for the branch-and-bound in candidates.py: a point above the bound of the cell it came from only
becomes final sooner, the cell that actually holds the maximum still finds it, and a point found twice
from two cells is rejected by the dedup rule.

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

from .errors import PolesError
from .roads import RoadSet

# Grid points are handed to `allowed` in descending distance order, this many at a time. The winner is
# usually allowed, so the first batch normally answers the whole refinement and the mask never sees the
# other 10,000 points; the batch is still large enough that a mask backed by an index is called in bulk.
MASK_BATCH = 256


def utm_epsg(lon: float, lat: float) -> int:
    """EPSG of the UTM zone holding lon/lat. No Norway or Svalbard exceptions: they widen zones for grid
    conventions, and a distance measured a degree outside the nominal zone is unaffected."""
    zone = min(60, max(1, int(math.floor((lon + 180.0) / 6.0)) + 1))
    return (32600 if lat >= 0 else 32700) + zone


@dataclass
class RefinedPole:
    """One refined pole. `x` and `y` are metres in `utm_epsg`, never in the caller's `src_crs`; `lat` and
    `lon` are the same point in EPSG:4326. `way_id` is the OSM id of the nearest way and `way_index` its
    row in the RoadSet the search ran against, so the index only means anything next to that RoadSet."""

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


def _axis(centre: float, half: float, step: float) -> np.ndarray:
    """Lattice of `step` anchored on `centre` and reaching no farther than `half` either way.

    Anchoring on the centre keeps the centre itself a sample and keeps every sample inside the window,
    whatever ratio of half to step the caller picks."""
    n = int(math.floor(half / step + 1e-9))
    return centre + step * np.arange(-n, n + 1)


def _best_on_grid(cx: float, cy: float, half: float, step: float, roads: UtmRoads,
                  allowed) -> tuple[float, float, float, int] | None:
    """Farthest allowed point from any road on the lattice of `step` filling the window, or None when the
    mask allows no point of it.

    Returns (x, y, distance, road index). Every point is measured, the points are then ranked by distance
    and the mask is applied down that ranking until it accepts one, so the answer is the same as masking
    the whole lattice first. Ties are broken by the first sample in row-major order, and a point exactly
    equidistant from two roads takes whichever the tree reaches first; both are reproducible for the same
    road set, which is what a rerun needs.
    """
    gx, gy = np.meshgrid(_axis(cx, half, step), _axis(cy, half, step))
    px, py = gx.ravel(), gy.ravel()
    pts = shapely.points(px, py)
    idx, dist = roads.tree.query_nearest(pts, return_distance=True, all_matches=False)
    d = np.full(len(pts), -np.inf)
    d[idx[0]] = dist
    nearest = np.full(len(pts), -1)
    nearest[idx[0]] = idx[1]

    def result(k: int) -> tuple[float, float, float, int]:
        if nearest[k] < 0:  # the tree answered nothing for this point; reporting road -1 would be silent nonsense
            raise PolesError(f"refine: no nearest road for the winning point at {px[k]}, {py[k]}")
        return float(px[k]), float(py[k]), float(d[k]), int(nearest[k])

    order = np.argsort(-d, kind="stable")
    if allowed is None:
        return result(int(order[0]))
    for start in range(0, len(order), MASK_BATCH):
        batch = order[start:start + MASK_BATCH]
        lons, lats = roads.to_lonlat.transform(px[batch], py[batch])
        keep = np.asarray(allowed(np.asarray(lons), np.asarray(lats)), dtype=bool)
        if keep.any():
            return result(int(batch[int(np.argmax(keep))]))
    return None


def refine(x: float, y: float, src_crs: str, roads: UtmRoads, half_m: float = 250.0, step: float = 5.0,
           allowed: Callable[[np.ndarray, np.ndarray], np.ndarray] | None = None) -> RefinedPole | None:
    """The exact pole of the window centred on (x, y) in `src_crs`, or None when nothing there qualifies.

    One sweep of the window at `step`, in the zone of `roads`. `allowed(lons, lats)` is the caller's mask
    (in the unit, on land, clear of large water); the search only ever reports a point it accepts. None
    also comes back for an empty road set.
    """
    if roads.tree is None:
        return None
    if src_crs != f"EPSG:{roads.epsg}":
        cx, cy = Transformer.from_crs(src_crs, f"EPSG:{roads.epsg}", always_xy=True).transform(x, y)
    else:
        cx, cy = x, y
    best = _best_on_grid(cx, cy, half_m, step, roads, allowed)
    if best is None:
        return None
    bx, by, dist, i = best
    lon, lat = roads.to_lonlat.transform(bx, by)
    return RefinedPole(float(lat), float(lon), dist, int(roads.roads.attrs["osm_id"][i]), bx, by, roads.epsg, i)


def _lon_inside(cached_west: float, cached_east: float, west: float, east: float) -> bool:
    """Is the span west to east inside the cached span, whichever side of 180 each of them is written on?

    The request's west is brought into the cached window's own turn of the world before the widths are
    compared, so the two spellings of one window match and the cache keeps working near the antimeridian
    (issue #22). Latitude needs none of this: there is no wrap at the poles of a lon/lat bbox.
    """
    if cached_east - cached_west >= 360.0:
        return True
    start = cached_west + ((west - cached_west) % 360.0)
    return start + (east - west) <= cached_east


class RoadCache:
    """Roads for one bbox at a time: refinements of neighbouring cells share one tile query and one projection."""

    def __init__(self, tiles, where: str | None = None, pad_deg: float = 0.2):
        self.tiles, self.where, self.pad_deg = tiles, where, pad_deg
        self._bbox: tuple[float, float, float, float] | None = None
        self._roads: UtmRoads | None = None

    def get(self, west: float, south: float, east: float, north: float, epsg: int) -> UtmRoads:
        b = self._bbox
        if self._roads is not None and self._roads.epsg == epsg and b is not None \
                and b[1] <= south and b[3] >= north and _lon_inside(b[0], b[2], west, east):
            return self._roads
        bbox = (west - self.pad_deg, south - self.pad_deg, east + self.pad_deg, north + self.pad_deg)
        self._roads = UtmRoads(self.tiles.query(*bbox, where=self.where), epsg)
        self._bbox = bbox
        return self._roads
