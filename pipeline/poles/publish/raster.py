"""Explore class rasters: the coarse distance grid quantised with the class table, masked, and warped to
Web Mercator at the z9 resolution for the tiler."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import rasterio
import shapely
from pyogrio.raw import write as ogr_write
from pyproj import Transformer
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from ..classes import EDGE, NODATA, ClassTable
from ..extract import MARKER
from ..grid import GTIFF_OPTS, Frame, create_raster, rasterize
from ..poly import parse_poly
from ..shell import run_cmd

Z9_RES = 40075016.68557849 / (256 * 512)
MERC_MAX = 20037508.342789244
SEGMENT_DEG = 0.1     # densify a lon/lat outline every 0.1 degrees before projecting it, as grid.py does
SEGMENT_M = 1_000.0   # and every kilometre on the way back to lon/lat


def _done(path: Path) -> bool:
    return path.exists() and path.with_name(path.name + MARKER).exists()


def _mark(path: Path) -> None:
    path.with_name(path.name + MARKER).touch()


def _unmark(path: Path) -> None:
    """Drop the done marker before rewriting the artefact, so a crash mid-rewrite cannot look finished."""
    path.with_name(path.name + MARKER).unlink(missing_ok=True)


def edge_polygon(fetch_dir: Path) -> BaseGeometry:
    """Union of every source extract polygon: the same data edge validation's check 3 measures against."""
    snapshot = json.loads((fetch_dir / "snapshot.json").read_text(encoding="utf-8"))
    polys = [parse_poly(fetch_dir / s["poly"]) for s in snapshot["sources"]]
    if not polys:
        raise ValueError(f"{fetch_dir / 'snapshot.json'}: no sources")
    return unary_union(polys)


def _project(geom: BaseGeometry, src: str, dst: str, segment: float) -> BaseGeometry:
    """Reproject, densified first: a side that is straight in the source CRS is a curve in the target one, and
    on a continental outline the two run tens of kilometres apart (a 30 degree meridian edge lands 85 km off
    without this). grid.frame_from_polygons and validate's edge check densify before the same transform.
    `segment` is in the source CRS's units: degrees out of EPSG:4326, metres out of the frame CRS."""
    tr = Transformer.from_crs(src, dst, always_xy=True)
    dense = shapely.segmentize(geom, segment)
    return shapely.transform(dense, lambda c: np.column_stack(tr.transform(c[:, 0], c[:, 1])))


def _polygon_fgb(geom: BaseGeometry, path: Path, crs: str) -> Path:
    path.unlink(missing_ok=True)
    ogr_write(str(path), geometry=np.array([shapely.to_wkb(geom)], dtype=object),
              field_data=[np.array([1], dtype=np.int32)], fields=["v"], layer="mask", driver="FlatGeobuf",
              geometry_type="MultiPolygon" if geom.geom_type == "MultiPolygon" else "Polygon", crs=crs)
    return path


def edge_masks(edge_4326: BaseGeometry, frame: Frame, edge_mask_m: float, out_dir: Path, log: logging.Logger,
               tools_log: Path) -> tuple[Path, Path]:
    """inside.tif: 1 where the cell lies inside the region's data. edgeband.tif: 1 within edge_mask_m of the data
    edge, where a distance is only a lower bound. The band is also kept in EPSG:4326 for the detail rasters."""
    inside_tif, band_tif = out_dir / "inside.tif", out_dir / "edgeband.tif"
    band_wkb = out_dir / "edgeband_4326.wkb"
    if _done(inside_tif) and _done(band_tif) and _done(band_wkb):
        return inside_tif, band_tif
    edge_proj = _project(edge_4326, "EPSG:4326", frame.crs, SEGMENT_DEG)
    band_proj = edge_proj.boundary.buffer(edge_mask_m)
    _unmark(band_wkb)
    band_wkb.write_bytes(shapely.to_wkb(_project(band_proj, frame.crs, "EPSG:4326", SEGMENT_M)))
    _mark(band_wkb)
    for geom, tif in ((edge_proj, inside_tif), (band_proj, band_tif)):
        fgb = _polygon_fgb(geom, out_dir / (tif.stem + ".fgb"), frame.crs)
        _unmark(tif)
        create_raster(frame, tif, "uint8", nodata=None)
        rasterize(fgb, "mask", tif, log, tools_log, burn=1, all_touched=True)
        _mark(tif)
        log.info("publish: %s written", tif.name)
    return inside_tif, band_tif


def _same_frame(ref: rasterio.DatasetReader, other: rasterio.DatasetReader) -> bool:
    return (ref.width, ref.height, ref.transform) == (other.width, other.height, other.transform)


def quantise(dist_tif: Path, land_tif: Path, inside_tif: Path, band_tif: Path, out_tif: Path, table: ClassTable,
             log: logging.Logger) -> dict:
    """Class index per cell, block by block. NODATA off land and outside the data beats EDGE beats the class.

    A distance that is not a usable number (the grid's own nodata, NaN, infinity) is NODATA as well: it never
    reaches the class table."""
    counts = {"cells": 0, "nodata": 0, "edge": 0, "classed": 0}
    with rasterio.open(dist_tif) as dist, rasterio.open(land_tif) as land, rasterio.open(inside_tif) as inside, \
            rasterio.open(band_tif) as band:
        for path, ds in ((land_tif, land), (inside_tif, inside), (band_tif, band)):
            if not _same_frame(dist, ds):
                raise ValueError(f"{path} is not on the same frame as {dist_tif}")
        profile = dict(dist.profile, dtype="uint8", count=1, nodata=NODATA, **GTIFF_OPTS)
        with rasterio.open(out_tif, "w", **profile) as out:
            for _, win in dist.block_windows(1):
                d = dist.read(1, window=win)
                unusable = ~np.isfinite(d)
                if dist.nodata is not None and np.isfinite(dist.nodata):
                    unusable |= d == d.dtype.type(dist.nodata)
                cls = table.to_class(np.where(unusable, d.dtype.type(0), d))
                on_band = band.read(1, window=win) == 1
                off = (land.read(1, window=win) == 0) | (inside.read(1, window=win) == 0) | unusable
                cls[on_band] = EDGE
                cls[off] = NODATA
                out.write(cls, 1, window=win)
                counts["cells"] += cls.size
                counts["nodata"] += int(off.sum())
                counts["edge"] += int((on_band & ~off).sum())
    counts["classed"] = counts["cells"] - counts["nodata"] - counts["edge"]
    log.info("publish: %s: %s", out_tif.name, counts)
    return counts


def _mercator_extent(src_tif: Path) -> tuple[float, float, float, float]:
    """Bounding box of the source footprint in EPSG:3857, sampled along its edge and clamped to the world."""
    with rasterio.open(src_tif) as ds:
        b, crs = ds.bounds, ds.crs.to_string()
    tr = Transformer.from_crs(crs, "EPSG:3857", always_xy=True)
    n = 200
    xs = np.concatenate([np.linspace(b.left, b.right, n), np.full(n, b.right), np.linspace(b.right, b.left, n), np.full(n, b.left)])
    ys = np.concatenate([np.full(n, b.bottom), np.linspace(b.bottom, b.top, n), np.full(n, b.top), np.linspace(b.top, b.bottom, n)])
    mx, my = tr.transform(xs, ys)
    mx, my = np.asarray(mx), np.asarray(my)
    ok = np.isfinite(mx) & np.isfinite(my)
    mx, my = np.clip(mx[ok], -MERC_MAX, MERC_MAX), np.clip(my[ok], -MERC_MAX, MERC_MAX)
    return float(mx.min()), float(my.min()), float(mx.max()), float(my.max())


def warp_to_mercator(src_tif: Path, out_tif: Path, log: logging.Logger, tools_log: Path) -> Path:
    """Nearest-neighbour warp to EPSG:3857 on the z9 pixel grid (-tap at Z9_RES), so the tiler cuts z9 without
    resampling. Class values are categories; any other resampling would invent classes."""
    if _done(out_tif):
        return out_tif
    w, s, e, n = _mercator_extent(src_tif)
    cmd = ["gdalwarp", "-overwrite", "-t_srs", "EPSG:3857", "-r", "near", "-tr", repr(Z9_RES), repr(Z9_RES), "-tap",
           "-te", repr(w), repr(s), repr(e), repr(n), "-ot", "Byte", "-dstnodata", str(NODATA),
           "-multi", "-wo", "NUM_THREADS=ALL_CPUS", "--config", "GDAL_CACHEMAX", "2048",
           "-co", "TILED=YES", "-co", "BLOCKXSIZE=512", "-co", "BLOCKYSIZE=512", "-co", "COMPRESS=DEFLATE", "-co", "BIGTIFF=IF_SAFER",
           src_tif, out_tif]
    _unmark(out_tif)
    res = run_cmd(cmd, log, stderr_path=tools_log)
    _mark(out_tif)
    log.info("publish: %s warped in %.0f s", out_tif.name, res.duration_s)
    return out_tif
