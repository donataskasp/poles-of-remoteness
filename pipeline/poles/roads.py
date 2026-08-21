"""Spatial access to the road layers (issue #16).

GDAL cannot read back a FlatGeobuf whose packed R-tree is large (measured 2026-08-21 by doubling one
file: 42.6 M indexed features still read their first feature and answer a spatial query with the
expected count, 63.9 M returned no features at all, so the ceiling is about 40 M per indexed
FlatGeobuf), so the 101 M highways stay as unindexed chunks behind `highways.vrt` in stage 1 and this
module re-tiles them into indexed FlatGeobufs of TILE_DEG degrees, each a few million features, built
by one `ogr2ogr -spat` pass per tile. Every pass rescans the whole source, so the build costs the tile
count times one scan: measured on a continent-sized source of 101 M ways, 220 tiles at ten parallel
passes took 49 minutes and produced 116 non-empty tiles, the largest 8.7 M features. A query opens
the tiles that intersect the bbox, reads each through its index, and deduplicates by osm_id because a
way crossing a seam is stored in every tile it touches (63,646 duplicates over that same 101 M, so
the tiles hold 0.06 percent more rows than the source).
"""
from __future__ import annotations

import json
import logging
import math
import os
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
# The ceiling from the measurement in the module docstring, rounded down to a round number. A tile
# above it writes without complaint and then reads back empty, so build_tiles refuses to ship one.
INDEX_LIMIT = 40_000_000
MARKER = ".ok"
EMPTY_MARKER = ".empty"


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


def _bounds(src: Path, layer: str, info: dict) -> tuple[float, float, float, float]:
    """Extent of the source layer. A union VRT answers this from the chunk headers, in well under a
    second even over the 141 chunks of the 101 M highways, so there is no cheaper path to take."""
    total = info["total_bounds"]
    if total is None or not all(math.isfinite(float(v)) for v in total):
        raise PolesError(f"roads: layer {layer} in {src} reports no extent; cannot lay out tiles")
    return tuple(float(v) for v in total)


def _source_count(src: Path, layer: str, info: dict) -> int:
    """Feature count of the source layer. A missing count, or the -1 GDAL reports when it does not know,
    would make the coverage check at the end of build_tiles vacuous, so refuse it the way _bounds does."""
    n = info["features"]
    if n is None or int(n) < 0:
        raise PolesError(f"roads: layer {layer} in {src} reports no feature count; cannot check coverage")
    return int(n)


def _within_index_limit(tile: Tile, n: int, tile_deg: float) -> int:
    """A FlatGeobuf past INDEX_LIMIT still writes, still reports its header count, and then answers every
    spatial query with nothing. _count reads that header, which knows nothing about the packed R-tree, so
    an oversized tile would pass the coverage check and go silently blind. Stop the build instead."""
    if n > INDEX_LIMIT:
        raise PolesError(f"roads: tile {tile.name} holds {n} features, past the {INDEX_LIMIT} feature index "
                         f"limit, so its spatial index would read back empty; use a smaller tile_deg "
                         f"than {tile_deg}")
    return n


def _worker_count(workers: int | None) -> int:
    """An explicit argument wins, then $POLES_WORKERS (0 means auto, as in the grid stage), then the machine.

    A pass is a full scan at about 50 MB RSS, so cores and page cache set the limit, not memory: measured
    2026-08-21 on 12 cores, ten parallel passes finished 31 percent more tiles per minute than six, and the
    six-way cap the memory-bound extract stage needs does not apply here.
    """
    if workers is None:
        workers = int(os.environ.get("POLES_WORKERS", "0")) or max(1, (os.cpu_count() or 4) - 2)
    if workers < 1:
        raise ValueError(f"roads: workers must be at least 1, got {workers}")
    return workers


def build_tiles(src: Path, layer: str, out_dir: Path, log: logging.Logger, *, tile_deg: float = TILE_DEG,
                workers: int | None = None) -> dict:
    """One `ogr2ogr -spat` pass per tile over the unindexed source; every non-empty tile becomes an indexed
    FlatGeobuf guarded by a `.ok` marker, so a rerun skips finished tiles. Writes tiles.json last."""
    require_tools(["ogr2ogr"])
    out_dir.mkdir(parents=True, exist_ok=True)
    info = read_info(str(src), layer=layer, force_feature_count=True)
    bounds = _bounds(src, layer, info)
    source_features = _source_count(src, layer, info)
    grid = tile_grid(bounds, tile_deg)
    workers = _worker_count(workers)
    log.info("roads: %d tiles of %s deg over %s with %d workers", len(grid), tile_deg, bounds, workers)
    tools_log = out_dir / "tools.log"

    def one(tile: Tile) -> tuple[Tile, int]:
        fgb = out_dir / f"{tile.name}.fgb"
        marker = fgb.with_name(fgb.name + MARKER)
        empty = fgb.with_name(fgb.name + EMPTY_MARKER)
        if empty.exists():
            return tile, 0
        if fgb.exists() and marker.exists():
            return tile, _within_index_limit(tile, _count(fgb), tile_deg)
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
        _within_index_limit(tile, n, tile_deg)  # raises before the marker, so a rerun redoes the tile
        marker.touch()
        return tile, n

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, grid))
    tiles = [{"name": t.name, "west": t.west, "south": t.south, "east": t.east, "north": t.north, "features": n}
             for t, n in results if n > 0]
    meta = {"tile_deg": tile_deg, "layer": layer, "source_features": source_features, "tiles": tiles}
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
        """Roads intersecting the bbox, in lon/lat, deduplicated by osm_id across the tile seams.

        osm_id is what the dedup keys on, so it is always read; it comes back in attrs only if asked for.
        """
        wanted = tuple(columns)
        columns = wanted if "osm_id" in wanted else ("osm_id",) + wanted
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
            return RoadSet.empty(wanted)
        all_geoms = np.concatenate(geoms)
        all_attrs = {c: np.concatenate(attrs[c]) for c in columns}
        _, first = np.unique(all_attrs["osm_id"].astype(np.int64), return_index=True)
        first.sort()
        return RoadSet(all_geoms[first], {c: all_attrs[c][first] for c in wanted})
