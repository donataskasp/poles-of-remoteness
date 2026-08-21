"""Spatial access to the road layers (issue #16).

GDAL cannot read back a FlatGeobuf whose packed R-tree is large (measured 2026-08-21 by doubling one
file: 42.6 M indexed features still read their first feature and answer a spatial query with the
expected count, 63.9 M returned no features at all, so the ceiling is about 40 M per indexed
FlatGeobuf), so the 101 M highways stay as unindexed chunks behind `highways.vrt` in stage 1 and this
module re-tiles them into indexed FlatGeobufs of TILE_DEG degrees, each a few million features, built
by one `ogr2ogr -spat` pass per tile (about 39 s per pass, six in parallel). A query opens the tiles
that intersect the bbox, reads each through its index, and deduplicates by osm_id because a way
crossing a seam is stored in every tile it touches.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import shapely
from pyogrio import read_info
from pyogrio.raw import read

from .errors import PolesError
from .shell import require_tools, run_cmd

# 5 degrees keeps the densest tile near 10 M features, a quarter of the measured index ceiling.
TILE_DEG = 5.0
MARKER = ".ok"

_EXTENT = re.compile(r"Extent:\s*\(([-\d.eE+]+),\s*([-\d.eE+]+)\)\s*-\s*\(([-\d.eE+]+),\s*([-\d.eE+]+)\)")


@dataclass(frozen=True)
class Tile:
    name: str
    west: float
    south: float
    east: float
    north: float

    def intersects(self, west: float, south: float, east: float, north: float) -> bool:
        return not (east < self.west or west > self.east or north < self.south or south > self.north)


@dataclass
class RoadSet:
    geoms: np.ndarray
    attrs: dict[str, np.ndarray]

    def __len__(self) -> int:
        return len(self.geoms)

    @classmethod
    def empty(cls, columns) -> "RoadSet":
        return cls(np.array([], dtype=object), {c: np.array([], dtype=object) for c in columns})


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def tile_grid(bounds: tuple[float, float, float, float], tile_deg: float) -> list[Tile]:
    """Tiles of tile_deg anchored at multiples of tile_deg, covering bounds (west, south, east, north)."""
    w0 = math.floor(bounds[0] / tile_deg) * tile_deg
    s0 = math.floor(bounds[1] / tile_deg) * tile_deg
    tiles = []
    south = s0
    while south < bounds[3]:
        west = w0
        while west < bounds[2]:
            tiles.append(Tile(f"t_{_fmt(west)}_{_fmt(south)}", west, south, west + tile_deg, south + tile_deg))
            west += tile_deg
        south += tile_deg
    return tiles


def _count(path: Path) -> int:
    return int(read_info(str(path), force_feature_count=True)["features"])


def _bounds(src: Path, layer: str, info: dict, out_dir: Path, log: logging.Logger) -> tuple[float, float, float, float]:
    """Extent of the source layer. A union VRT reports total_bounds as None, so fall back to
    `ogrinfo -so`, which reports the union extent from the chunk headers."""
    total = info.get("total_bounds")
    if total is not None and all(math.isfinite(float(v)) for v in total):
        return tuple(float(v) for v in total)
    require_tools(["ogrinfo"])
    text = out_dir / "extent.txt"
    run_cmd(["ogrinfo", "-so", src, layer], log, stdout_path=text, stderr_path=out_dir / "tools.log")
    match = _EXTENT.search(text.read_text(encoding="utf-8", errors="replace"))
    if match is None:
        raise PolesError(f"roads: no extent for layer {layer} in {src}; cannot lay out tiles")
    west, south, east, north = (float(g) for g in match.groups())
    return west, south, east, north


def build_tiles(src: Path, layer: str, out_dir: Path, log: logging.Logger, *, tile_deg: float = TILE_DEG,
                workers: int | None = None) -> dict:
    """One `ogr2ogr -spat` pass per tile over the unindexed source; every non-empty tile becomes an indexed
    FlatGeobuf guarded by a `.ok` marker, so a rerun skips finished tiles. Writes tiles.json last."""
    require_tools(["ogr2ogr"])
    out_dir.mkdir(parents=True, exist_ok=True)
    info = read_info(str(src), layer=layer, force_feature_count=True)
    bounds = _bounds(src, layer, info, out_dir, log)
    grid = tile_grid(bounds, tile_deg)
    workers = workers or min(6, max(1, (os.cpu_count() or 3) - 2))
    log.info("roads: %d tiles of %s deg over %s with %d workers", len(grid), tile_deg, bounds, workers)
    tools_log = out_dir / "tools.log"

    def one(tile: Tile) -> tuple[Tile, int]:
        fgb = out_dir / f"{tile.name}.fgb"
        marker = fgb.with_name(fgb.name + MARKER)
        empty = fgb.with_name(fgb.name + ".empty")
        if empty.exists():
            return tile, 0
        if fgb.exists() and marker.exists():
            return tile, _count(fgb)
        marker.unlink(missing_ok=True)
        fgb.unlink(missing_ok=True)
        run_cmd(["ogr2ogr", "-f", "FlatGeobuf", fgb, src, "-nln", layer, "-spat", tile.west, tile.south, tile.east,
                 tile.north, "-lco", "SPATIAL_INDEX=YES", "-lco", f"TEMPORARY_DIR={out_dir}"],
                log, stderr_path=tools_log)
        n = _count(fgb) if fgb.exists() else 0
        if n == 0:
            fgb.unlink(missing_ok=True)
            empty.touch()
            return tile, 0
        marker.touch()
        return tile, n

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, grid))
    tiles = [{"name": t.name, "west": t.west, "south": t.south, "east": t.east, "north": t.north, "features": n}
             for t, n in results if n > 0]
    meta = {"tile_deg": tile_deg, "layer": layer, "source_features": int(info["features"]), "tiles": tiles}
    total = sum(t["features"] for t in tiles)
    if total < meta["source_features"]:
        raise PolesError(f"roads: tiles hold {total} features but the source has {meta['source_features']}")
    (out_dir / "tiles.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    log.info("roads: %d non-empty tiles, %d features (%d in the source)", len(tiles), total, meta["source_features"])
    return meta


class RoadTiles:
    """Read side of build_tiles: the tile index from tiles.json plus bbox queries across it."""

    def __init__(self, out_dir: Path):
        self.dir = Path(out_dir)
        meta = json.loads((self.dir / "tiles.json").read_text(encoding="utf-8"))
        self.layer = meta["layer"]
        self.tiles = [Tile(t["name"], t["west"], t["south"], t["east"], t["north"]) for t in meta["tiles"]]

    def query(self, west: float, south: float, east: float, north: float, where: str | None = None,
              columns=("osm_id", "highway", "name", "ref")) -> RoadSet:
        """Roads intersecting the bbox, in lon/lat, deduplicated by osm_id across the tile seams."""
        columns = tuple(columns)
        geoms: list[np.ndarray] = []
        attrs: dict[str, list[np.ndarray]] = {c: [] for c in columns}
        for tile in self.tiles:
            if not tile.intersects(west, south, east, north):
                continue
            meta, _, wkb, fields = read(str(self.dir / f"{tile.name}.fgb"), layer=self.layer, columns=list(columns),
                                        bbox=(west, south, east, north), where=where)
            if len(wkb) == 0:
                continue
            by_name = dict(zip(meta["fields"], fields))
            geoms.append(shapely.from_wkb(wkb))
            for c in columns:
                attrs[c].append(np.asarray(by_name[c], dtype=object))
        if not geoms:
            return RoadSet.empty(columns)
        all_geoms = np.concatenate(geoms)
        all_attrs = {c: np.concatenate(attrs[c]) for c in columns}
        _, first = np.unique(all_attrs["osm_id"].astype(np.int64), return_index=True)
        first.sort()
        return RoadSet(all_geoms[first], {c: all_attrs[c][first] for c in columns})
