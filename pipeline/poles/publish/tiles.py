"""Explore tile pyramid: gdal raster tile cuts the warped class raster into z0..z9 PNGs, a packer writes them
into MBTiles, pmtiles converts the archive. Class values are categories, so z9 is nearest and the overviews
are the mode of their four children."""
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
LAT_MAX = 85.0511287798066


def tile_dir(src_3857: Path, out_dir: Path, log: logging.Logger, tools_log: Path) -> Path:
    """Cut the pyramid into <z>/<x>/<y>.png. The tiler marks what the raster does not cover with an alpha
    band and never with a class value: asking for --no-alpha instead makes it fill empty space with 0, which
    is a real class (0 to 50 m), so water would publish as "next to a road". The alpha is folded back into
    NODATA by the packer, and the archive still carries single band grey tiles."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["gdal", "raster", "tile", "--tiling-scheme", "WebMercatorQuad", "--min-zoom", "0", "--max-zoom", str(MAX_ZOOM),
           "--resampling", "nearest", "--overview-resampling", "mode", "--skip-blank",
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
        with mem.open(driver="PNG", width=cls.shape[1], height=cls.shape[0], count=1, dtype="uint8") as ds:
            ds.write(cls, 1)
        return mem.read()


def _read_tile(png: Path) -> tuple[np.ndarray, bytes | None]:
    """Class band of one tile, with the tiler's alpha folded into NODATA. The second item is the file's own
    bytes when the tile is already single band and needs no rewrite."""
    with _ungeoreferenced(), rasterio.open(png) as ds:
        bands = ds.read()
    if bands.shape[0] == 1:
        return bands[0], png.read_bytes()
    cls = bands[0].copy()
    cls[bands[-1] == 0] = NODATA
    return cls, None


def pack_mbtiles(tiles_dir: Path, mbtiles: Path, name: str, bounds_lonlat: tuple[float, float, float, float]) -> dict:
    """Directory pyramid to MBTiles (TMS rows). Tiles that are entirely NODATA are dropped here whatever the
    tiler did, so the archive never carries an empty tile."""
    mbtiles.unlink(missing_ok=True)
    con = sqlite3.connect(mbtiles)
    con.executescript("CREATE TABLE metadata (name TEXT, value TEXT);"
                      "CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB);"
                      "CREATE UNIQUE INDEX tile_index ON tiles (zoom_level, tile_column, tile_row);")
    per_zoom: dict[int, int] = {}
    blank = 0
    try:
        for png, z, x, y in _walk(tiles_dir):
            cls, raw = _read_tile(png)
            if (cls == NODATA).all():
                blank += 1
                continue
            con.execute("INSERT INTO tiles VALUES (?, ?, ?, ?)",
                        (z, x, (1 << z) - 1 - y, raw if raw is not None else _grey_png(cls)))
            per_zoom[z] = per_zoom.get(z, 0) + 1
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


def _walk(tiles_dir: Path):
    """Every <z>/<x>/<y>.png under the pyramid, in zoom order. Anything that is not a numbered directory is
    not a tile and is ignored."""
    for z_dir in sorted((p for p in tiles_dir.iterdir() if p.is_dir() and p.name.isdigit()), key=lambda p: int(p.name)):
        for x_dir in sorted((p for p in z_dir.iterdir() if p.is_dir() and p.name.isdigit()), key=lambda p: int(p.name)):
            for png in sorted((p for p in x_dir.glob("*.png") if p.stem.isdigit()), key=lambda p: int(p.stem)):
                yield png, int(z_dir.name), int(x_dir.name), int(png.stem)


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
