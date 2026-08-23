"""Longitude helpers for data that crosses the antimeridian (issue #22).

Pure geometry in lon/lat degrees: no I/O, no configuration, and no import from another module of this
package, so any call site can use it without pulling in the stage it belongs to.

Three ideas, and everything here is one of them:

- A ring drawn across 180 is continuous only when its longitudes are unwrapped past the line. OSM stores
  the vertices at 179.9 and at -179.9, and a polygon built from those as they are runs the long way round
  the planet: 356 degrees of arithmetic for 0.2 degrees of ground. `unwrap_polygon` does a shell and its
  holes together, because a hole is only unwrapped correctly relative to the shell it belongs to.
- A geometry stored split at the line has two longitude intervals, not one bounding box 360 degrees wide.
- A bounding box that runs across the line (east above 180, or west below -180) has to be split back into
  one or two ordinary boxes before a file format or a spatial index sees it.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

import shapely
from shapely.affinity import translate
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

# "Touches the antimeridian" tolerance: 1e-6 degrees is about 0.1 m at the equator, far below the
# quantum the poles stage rounds coordinates to and far above the noise of a projection round trip.
TOL_DEG = 1e-6


def _polygons(geom: BaseGeometry) -> list[Polygon]:
    """Every polygon inside a geometry, recursively; lines and points are dropped."""
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        return [p for part in geom.geoms for p in _polygons(part)]
    return []


def _multi(geom: BaseGeometry) -> MultiPolygon:
    if geom.geom_type == "MultiPolygon":
        return geom
    parts = _polygons(geom)
    return MultiPolygon(parts) if parts else MultiPolygon()


def unwrap_ring(coords) -> list[tuple[float, float]]:
    """The ring's coordinates made continuous: a step of more than 180 degrees of longitude between two
    consecutive vertices is the antimeridian, and everything after it is shifted by 360.

    The result is then normalised into a single window: a ring that unwrapped westwards (longitudes below
    -180) is shifted up by 360, so a shell that stepped east and a hole that stepped west are written in
    the same frame and still test as containing one another. Only a crossing ring can leave [-180, 180],
    so a ring that does not cross comes back coordinate for coordinate.
    """
    out: list[tuple[float, float]] = []
    prev: float | None = None
    shift = 0.0
    for point in coords:
        lon, lat = float(point[0]), float(point[1])
        if prev is not None:
            if lon + shift - prev > 180.0:
                shift -= 360.0
            elif lon + shift - prev < -180.0:
                shift += 360.0
        out.append((lon + shift, lat))
        prev = out[-1][0]
    if out and min(x for x, _ in out) < -180.0:
        out = [(x + 360.0, y) for x, y in out]
    return out


def unwrap_polygon(shell: Sequence[tuple[float, float]],
                   holes: Sequence[Sequence[tuple[float, float]]] = ()) -> Polygon:
    """A polygon whose shell and holes are unwrapped into one frame, so the holes are still holes.

    `unwrap_ring` normalises each ring on its own, which is not enough: a lake in the western lobe of a
    unit that straddles 180 is stored at about -179.5 and never steps more than 180 degrees, so it comes
    back where it started while the shell has moved to 178..182. The polygon built from those is invalid
    ("hole lies outside shell") and a later intersection drops the lake without a word. So each unwrapped
    hole is turned by whole 360s until it lands in the shell's longitude window. A hole that no turn can
    put there is a broken input; it is kept as it is and left to `shapely.make_valid`.
    """
    ring = unwrap_ring(shell)
    if not ring:
        return Polygon()
    west = min(x for x, _ in ring)
    east = max(x for x, _ in ring)
    turned: list[list[tuple[float, float]]] = []
    for hole in holes:
        inner = unwrap_ring(hole)
        if not inner:
            continue
        hole_west = min(x for x, _ in inner)
        hole_east = max(x for x, _ in inner)
        first = math.ceil((west - hole_east) / 360.0)      # the first turn that reaches the shell
        last = math.floor((east - hole_west) / 360.0)      # the last one that has not passed it
        if first <= last:
            turn = min(max(round((west + east - hole_west - hole_east) / 720.0), first), last)
            if turn:
                inner = [(x + 360.0 * turn, y) for x, y in inner]
        turned.append(inner)
    return Polygon(ring, turned)


def split_antimeridian(geom: BaseGeometry) -> MultiPolygon:
    """A MultiPolygon whose parts all lie inside [-180, 180], cut at the line where the input crossed it.

    Each polygon is unwrapped first through `unwrap_polygon`, so one drawn across the line becomes one
    continuous polygon with its holes in the same frame; it is then intersected with each 360 degree strip
    it reaches and every piece outside the first strip is translated back. The input need not be inside
    [-180, 180] to begin with: that same strip loop is what normalises it, and a box from 350 to 365 comes
    back as -10 to 5. A geometry that does not cross is returned with its own coordinates, only normalised
    to MultiPolygon. The pieces are dissolved with `unary_union`, so parts that meet once the geometry is
    in one frame come back merged and the result can have fewer parts than the input had.
    """
    polys = _polygons(geom)
    if not polys:
        return MultiPolygon()
    unwrapped, crossed = [], False
    for poly in polys:
        one = unwrap_polygon(poly.exterior.coords, [ring.coords for ring in poly.interiors])
        unwrapped.append(one)
        if max(x for x, _ in one.exterior.coords) > 180.0 + TOL_DEG:
            crossed = True
    if not crossed:
        return _multi(geom)
    pieces: list[Polygon] = []
    for poly in unwrapped:
        west, _, east, _ = poly.bounds
        first = math.floor((west + 180.0) / 360.0)
        last = math.floor((east + 180.0) / 360.0)
        for k in range(first, last + 1):
            strip = shapely.box(-180.0 + 360.0 * k, -90.0, 180.0 + 360.0 * k, 90.0)
            part = poly.intersection(strip)
            if part.is_empty:
                continue
            if k:
                part = translate(part, xoff=-360.0 * k)
            pieces.extend(_polygons(shapely.make_valid(part)))
    return _multi(unary_union(pieces)) if pieces else MultiPolygon()


def lon_intervals(geom: BaseGeometry) -> list[tuple[float, float]]:
    """The longitude spans the parts of a split geometry actually cover, sorted and merged.

    A geometry stored split at the line has two of them (about 172 to 180 and -180 to -130 for a unit on
    the line); its plain bounding box claims the whole planet, and anything that tiles or reads by that
    box does 45 times the work for nothing.
    """
    spans = sorted((p.bounds[0], p.bounds[2]) for p in _polygons(geom))
    merged: list[list[float]] = []
    for west, east in spans:
        if merged and west <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], east)
        else:
            merged.append([west, east])
    return [(w, e) for w, e in merged]


def wrapped_bounds(geom: BaseGeometry) -> tuple[float, float, float, float]:
    """(west, south, east, north) taking the short way round the planet when the geometry straddles 180.

    A geometry stored split at the line has parts touching both 180 and -180, and its plain bounds run the
    whole world. Straddling is exactly that: parts within TOL_DEG of both edges, and a wrapped span
    shorter than the plain one. The result may have east above 180 (a unit on the line comes out as about
    west 172, east 230), which is what `split_bbox` exists to read and what units.json ships to the site.
    """
    spans = lon_intervals(geom)
    if not spans:
        raise ValueError("wrapped_bounds: an empty geometry has no bounds")
    west, south, east, north = geom.bounds
    if len(spans) < 2 or abs(spans[0][0] + 180.0) > TOL_DEG or abs(spans[-1][1] - 180.0) > TOL_DEG:
        return (west, south, east, north)
    # Cut at the widest gap between the parts: everything east of it wraps past 180.
    _, i = max((spans[j + 1][0] - spans[j][1], j) for j in range(len(spans) - 1))
    wrapped_west, wrapped_east = spans[i + 1][0], spans[i][1] + 360.0
    if wrapped_east - wrapped_west >= east - west:
        return (west, south, east, north)
    return (wrapped_west, south, wrapped_east, north)


def split_bbox(west: float, south: float, east: float, north: float) -> list[tuple[float, float, float, float]]:
    """One or two ordinary boxes inside [-180, 180] for a possibly wrapped box.

    Every spatial read goes through this: FlatGeobuf, GeoPackage and the pyogrio bbox filter all take a
    plain box and would silently return nothing for one whose east edge is 230.
    """
    if east < west:
        raise ValueError(f"split_bbox: east {east} is west of west {west}; a wrapped box is written with "
                         f"its east edge past 180 (or its west edge below -180), never inverted")
    if north < south:
        raise ValueError(f"split_bbox: north {north} is below south {south}; latitude does not wrap, so a "
                         f"box is never inverted there either")
    if east - west >= 360.0:
        return [(-180.0, south, 180.0, north)]
    w = (west + 180.0) % 360.0 - 180.0
    e = w + (east - west)
    if e <= 180.0:
        return [(w, south, e, north)]
    return [(w, south, 180.0, north), (-180.0, south, e - 360.0, north)]


def lon_delta(a, b):
    """The signed difference a minus b in degrees of longitude, the short way round: negative when a is
    west of b, positive when a is east of b, wrapped into (-180, 180].

    Scalars or numpy arrays, elementwise either way. The outer minus is what puts the open end at +180
    instead of -180, so half the planet away reads as `lon_delta(0, 180) == 180`, never -180. Without any
    of this a place at -179.9 is 359.8 degrees from a pole at 179.9 instead of 0.2, and any shortlist
    ordered by a plain difference drops the true nearest.
    """
    return -(((b - a) + 180.0) % 360.0 - 180.0)
