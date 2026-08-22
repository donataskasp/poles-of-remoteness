"""Explore tile pyramid: gdal raster tile cuts the warped class raster into z9 PNGs, a packer writes them into
MBTiles and builds z8 down to z0 itself, pmtiles converts the archive. Class values are categories, so z9 is
nearest and every overview pixel is the mode of its four children."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import warnings
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.errors import NotGeoreferencedWarning
from rasterio.io import MemoryFile

from ..classes import NODATA
from ..shell import run_cmd
from .raster import _done, _mark, _unmark

MAX_ZOOM = 9
TILE_PX = 256
LAT_MAX = 85.0511287798066
PNG_END = b"IEND\xaeB`\x82"


def tile_dir(src_3857: Path, out_dir: Path, log: logging.Logger, tools_log: Path) -> Path:
    """Cut the deepest zoom into <z>/<x>/<y>.png. The tiler marks what the raster does not cover with an alpha
    band and never with a class value: asking for --no-alpha instead makes it fill empty space with 0, which
    is a real class (0 to 50 m), so water would publish as "next to a road". The alpha is folded back into
    NODATA by the packer, and the archive still carries single band grey tiles.

    Only z9 is cut here. The tiler's own overviews take the mode of the class band with that same 0 sitting
    under the transparent pixels, and it votes: a block of {class, other class, nothing, nothing} comes out as
    class 0 at alpha 255, which no fold can undo, and a stipple of roadside pixels follows every coastline and
    every lake shore down the pyramid. --nodata-values-pct-threshold is refused for mode. The packer builds
    z8 and below itself instead."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["gdal", "raster", "tile", "--tiling-scheme", "WebMercatorQuad",
           "--min-zoom", str(MAX_ZOOM), "--max-zoom", str(MAX_ZOOM),
           "--resampling", "nearest", "--skip-blank",
           "--convention", "xyz", "--output-format", "PNG", "--webviewer", "none", "--resume", src_3857, out_dir]
    res = run_cmd(cmd, log, stderr_path=tools_log)
    log.info("publish: tiles of %s cut into %s in %.0f s", src_3857.name, out_dir.name, res.duration_s)
    return out_dir


def lonlat_bounds(src_3857: Path) -> tuple[float, float, float, float]:
    with rasterio.open(src_3857) as ds:
        b = ds.bounds
    tr = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    w, s = tr.transform(b.left, b.bottom)
    e, n = tr.transform(b.right, b.top)
    return float(w), float(max(s, -LAT_MAX)), float(e), float(min(n, LAT_MAX))


@contextmanager
def _ungeoreferenced():
    """A tile carries no georeference: its z/x/y path is the georeference, so rasterio's warning about it is noise."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        yield


def _grey_png(cls: np.ndarray) -> bytes:
    """Re-encode one tile as a single band grey PNG, the form the site decodes and the spec's size budget assumes."""
    with _ungeoreferenced(), MemoryFile(filename="tile.png") as mem:
        with mem.open(driver="PNG", width=cls.shape[1], height=cls.shape[0], count=1, dtype="uint8", ZLEVEL=9) as ds:
            ds.write(cls, 1)
        return mem.read()


def _read_tile(png: Path) -> np.ndarray:
    """Class band of one tile, with the tiler's alpha folded into NODATA. A tile a killed run left half written
    is rejected here rather than published: --resume regenerates only missing files, so nothing else in the
    chain would notice it, and a truncated PNG decodes happily with its missing rows filled in as zeros."""
    size = png.stat().st_size
    with png.open("rb") as fh:
        fh.seek(max(0, size - len(PNG_END)))
        trailer = fh.read()
    if trailer != PNG_END:
        raise RuntimeError(f"{png}: truncated tile, the PNG end marker is missing; delete it and rerun")
    with _ungeoreferenced(), rasterio.open(png) as ds:
        bands = ds.read()
    if bands.shape[0] not in (1, 2):
        raise RuntimeError(f"{png}: {bands.shape[0]} bands, expected grey or grey plus alpha")
    if bands.shape[1:] != (TILE_PX, TILE_PX):
        raise RuntimeError(f"{png}: {bands.shape[2]}x{bands.shape[1]} pixels, expected {TILE_PX} square; delete it and rerun")
    cls = bands[0].copy()
    if bands.shape[0] == 2:
        cls[bands[1] == 0] = NODATA
    return cls


def _mode_half(tile: np.ndarray) -> np.ndarray:
    """Halve a tile by taking the mode of every 2x2 block. NODATA votes as an ordinary class, so a block that
    is mostly nothing stays nothing; on a tie a data class beats NODATA, and between data classes the lowest
    class index wins (the nearer road, and the deterministic answer)."""
    h, w = tile.shape[0] // 2, tile.shape[1] // 2
    block = tile.reshape(h, 2, w, 2).transpose(0, 2, 1, 3).reshape(-1, 4).astype(np.int32)
    votes = (block[:, :, None] == block[:, None, :]).sum(axis=2)               # how often each pixel's value repeats
    rank = np.where(block != NODATA, votes * 256 + (NODATA - block), -1)       # most votes first, then lowest class
    rows = np.arange(block.shape[0])
    best = rank.argmax(axis=1)
    wins = (rank[rows, best] >= 0) & (votes[rows, best] >= (block == NODATA).sum(axis=1))
    return np.where(wins, block[rows, best], NODATA).astype(np.uint8).reshape(h, w)


def pack_mbtiles(tiles_dir: Path, mbtiles: Path, name: str, bounds_lonlat: tuple[float, float, float, float]) -> dict:
    """Directory of deepest zoom tiles to a whole MBTiles pyramid (TMS rows). Every tile is decoded and
    re-encoded, so a half written one is caught instead of published. The shallower levels are built here, one
    level at a time from the level just written: a parent is its four children each halved by the mode of every
    2x2 block, a missing child counts as all NODATA, and a tile that comes out entirely NODATA is dropped."""
    if not tiles_dir.is_dir():
        raise RuntimeError(f"{tiles_dir}: no tile directory to pack")
    mbtiles.unlink(missing_ok=True)
    con = sqlite3.connect(mbtiles)
    con.executescript("CREATE TABLE metadata (name TEXT, value TEXT);"
                      "CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB);"
                      "CREATE UNIQUE INDEX tile_index ON tiles (zoom_level, tile_column, tile_row);")
    per_zoom: dict[int, int] = {}
    blank = 0
    try:
        keys: set[tuple[int, int]] = set()
        for png, x, y in _walk(tiles_dir, MAX_ZOOM):
            cls = _read_tile(png)
            if (cls == NODATA).all():
                blank += 1
                continue
            _put(con, MAX_ZOOM, x, y, cls)
            keys.add((x, y))
        con.commit()
        for z in range(MAX_ZOOM, -1, -1):
            if not keys:
                break
            per_zoom[z] = len(keys)
            if z == 0:
                break
            written: set[tuple[int, int]] = set()
            half = TILE_PX // 2
            for px, py in sorted({(x // 2, y // 2) for x, y in keys}):
                parent = np.full((TILE_PX, TILE_PX), NODATA, np.uint8)
                for dy in (0, 1):
                    for dx in (0, 1):
                        child = (px * 2 + dx, py * 2 + dy)
                        if child in keys:
                            quarter = _mode_half(_tile_array(con, z, *child))
                            parent[dy * half:(dy + 1) * half, dx * half:(dx + 1) * half] = quarter
                if (parent == NODATA).all():
                    blank += 1
                    continue
                _put(con, z - 1, px, py, parent)
                written.add((px, py))
            con.commit()
            keys = written
        if not per_zoom:
            raise RuntimeError(f"{tiles_dir}: no non-blank tiles")
        zooms = sorted(per_zoom)
        meta = {"name": name, "format": "png", "type": "overlay", "version": "1",
                "description": f"{name}: distance class index per pixel, 254 edge, 255 nodata",
                "minzoom": str(zooms[0]), "maxzoom": str(zooms[-1]),
                "bounds": ",".join(f"{v:.6f}" for v in bounds_lonlat)}
        con.executemany("INSERT INTO metadata VALUES (?, ?)", list(meta.items()))
        con.commit()
    finally:
        con.close()
    return {"tiles": sum(per_zoom.values()), "per_zoom": per_zoom, "blank_skipped": blank}


def _put(con: sqlite3.Connection, z: int, x: int, y: int, cls: np.ndarray) -> None:
    con.execute("INSERT INTO tiles VALUES (?, ?, ?, ?)", (z, x, (1 << z) - 1 - y, _grey_png(cls)))


def _tile_array(con: sqlite3.Connection, z: int, x: int, y: int) -> np.ndarray:
    blob = con.execute("SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                       (z, x, (1 << z) - 1 - y)).fetchone()[0]
    with _ungeoreferenced(), MemoryFile(blob) as mem, mem.open() as ds:
        return ds.read(1)


def _walk(tiles_dir: Path, z: int):
    """Every <x>/<y>.png of one zoom level, in tile order. Anything that is not a numbered directory is not a
    tile and is ignored, and so is any level an older run of the tiler left behind."""
    z_dir = tiles_dir / str(z)
    if not z_dir.is_dir():
        return
    for x_dir in sorted((p for p in z_dir.iterdir() if p.is_dir() and p.name.isdigit()), key=lambda p: int(p.name)):
        for png in sorted((p for p in x_dir.glob("*.png") if p.stem.isdigit()), key=lambda p: int(p.stem)):
            yield png, int(x_dir.name), int(png.stem)


def convert_pmtiles(mbtiles: Path, pmtiles: Path, log: logging.Logger, tools_log: Path) -> Path:
    pmtiles.unlink(missing_ok=True)
    res = run_cmd(["pmtiles", "convert", mbtiles, pmtiles], log, stderr_path=tools_log)
    log.info("publish: %s converted in %.0f s", pmtiles.name, res.duration_s)
    return pmtiles


def parse_show(text: str) -> dict:
    def grab(label: str, cast=int):
        m = re.search(rf"^{label}:\s*(\S+)", text, re.MULTILINE)
        if not m:
            raise ValueError(f"pmtiles show: no '{label}' line in:\n{text}")
        return cast(m.group(1))
    return {"tiles": grab("addressed tiles count"), "min_zoom": grab("min zoom"), "max_zoom": grab("max zoom"),
            "tile_type": grab("tile type", str)}


def pmtiles_info(pmtiles: Path, log: logging.Logger) -> dict:
    out = pmtiles.parent / (pmtiles.name + ".show.txt")
    run_cmd(["pmtiles", "show", pmtiles], log, stdout_path=out)
    return parse_show(out.read_text(encoding="utf-8"))


def build(src_3857: Path, out_dir: Path, scenario: str, log: logging.Logger, tools_log: Path) -> dict:
    """Class raster to one PMTiles archive, resumable at every step."""
    tiles_path = out_dir / f"tiles_{scenario}"
    mbtiles = out_dir / f"{scenario}.mbtiles"
    pmtiles = out_dir / f"{scenario}.pmtiles"
    stats_path = out_dir / f"{scenario}.mbtiles.json"
    if not _done(tiles_path):
        _unmark(tiles_path)
        tile_dir(src_3857, tiles_path, log, tools_log)
        _mark(tiles_path)
    if not (_done(mbtiles) and stats_path.exists()):
        _unmark(mbtiles)
        stats = pack_mbtiles(tiles_path, mbtiles, scenario, lonlat_bounds(src_3857))
        stats_path.write_text(json.dumps(stats) + "\n", encoding="utf-8")
        _mark(mbtiles)
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    if not _done(pmtiles):
        _unmark(pmtiles)
        convert_pmtiles(mbtiles, pmtiles, log, tools_log)
        _mark(pmtiles)
    info = pmtiles_info(pmtiles, log)
    return {"key_name": pmtiles.name, "bytes": pmtiles.stat().st_size, "tiles": info["tiles"],
            "min_zoom": info["min_zoom"], "max_zoom": info["max_zoom"], "tile_type": info["tile_type"],
            "per_zoom": {int(k): v for k, v in stats["per_zoom"].items()}, "blank_skipped": stats["blank_skipped"]}
