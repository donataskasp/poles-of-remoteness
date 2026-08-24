"""Osmosis .poly files (Geofabrik extract polygons): sections are rings, a leading '!' marks a hole."""
from __future__ import annotations

from pathlib import Path

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


def parse_poly(path: Path) -> BaseGeometry:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    outers: list[Polygon] = []
    holes: list[Polygon] = []
    i = 1  # line 0 is the name
    while i < len(lines):
        header = lines[i].strip()
        i += 1
        if header == "END" or not header:
            continue
        is_hole = header.startswith("!")
        coords = []
        while i < len(lines) and lines[i].strip() != "END":
            x, y = lines[i].split()
            coords.append((float(x), float(y)))
            i += 1
        i += 1  # the ring's END
        (holes if is_hole else outers).append(Polygon(coords))
    geom = unary_union(outers)
    for hole in holes:
        geom = geom.difference(hole)
    return geom
