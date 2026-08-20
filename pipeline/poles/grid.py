"""Stage grid: raster frame, road masks, tiled exact Euclidean distance transform, land mask."""
from __future__ import annotations

import json
import logging
import math
import os
import resource
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import rasterio
import shapely
from pyproj import CRS, Transformer
from rasterio.transform import Affine, from_origin
from rasterio.windows import Window
from scipy.ndimage import distance_transform_edt
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shp_transform, unary_union

from .config import RegionConfig
from .poly import parse_poly
from .shell import CmdResult, require_tools, rss_bytes, run_cmd
from .workspace import Workspace

STAGE = "grid"
TILE = 4096
GTIFF_OPTS = dict(driver="GTiff", tiled=True, blockxsize=512, blockysize=512, compress="deflate", bigtiff="IF_SAFER")


class GridError(RuntimeError):
    pass


# ---------- frame ----------

@dataclass(frozen=True)
class Frame:
    crs: str
    res: float
    x0: float
    y1: float
    width: int
    height: int

    @property
    def x1(self) -> float:
        return self.x0 + self.width * self.res

    @property
    def y0(self) -> float:
        return self.y1 - self.height * self.res

    @property
    def transform(self) -> Affine:
        return from_origin(self.x0, self.y1, self.res, self.res)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Frame":
        return cls(**d)


def frame_from_polygons(polys: list[BaseGeometry], src_crs: str, crs: str, res: float, margin_m: float) -> Frame:
    """Bbox of the polygons in `crs`, expanded by margin_m, snapped outward to multiples of res."""
    if CRS(src_crs) != CRS(crs):
        tr = Transformer.from_crs(src_crs, crs, always_xy=True).transform
        seg = 0.1 if CRS(src_crs).is_geographic else res
        polys = [shp_transform(tr, shapely.segmentize(p, seg)) for p in polys]
    minx, miny, maxx, maxy = unary_union(polys).bounds
    x0 = math.floor((minx - margin_m) / res) * res
    y0 = math.floor((miny - margin_m) / res) * res
    x1 = math.ceil((maxx + margin_m) / res) * res
    y1 = math.ceil((maxy + margin_m) / res) * res
    return Frame(crs, res, x0, y1, int(round((x1 - x0) / res)), int(round((y1 - y0) / res)))


# ---------- rasters ----------

def create_raster(frame: Frame, path: Path, dtype: str = "uint8", nodata=None) -> Path:
    """An all-zero single-band GeoTIFF on the frame, for gdal_rasterize to burn into."""
    with rasterio.open(path, "w", width=frame.width, height=frame.height, count=1, dtype=dtype, crs=frame.crs,
                       transform=frame.transform, nodata=nodata, **GTIFF_OPTS) as ds:
        block = np.zeros((512, frame.width), dtype=dtype)
        for row in range(0, frame.height, 512):
            h = min(512, frame.height - row)
            ds.write(block[:h], 1, window=Window(0, row, frame.width, h))
    return path


def rasterize(src: Path, layer: str, target_tif: Path, log: logging.Logger, tools_log: Path, *, burn: int = 1,
              all_touched: bool = False, sql: str | None = None) -> CmdResult:
    """gdal_rasterize into an existing raster; GDAL reprojects the layer to the raster's CRS on the fly."""
    cmd = ["gdal_rasterize", "--config", "GDAL_CACHEMAX", "4096", "-burn", str(burn)]
    if all_touched:
        cmd.append("-at")
    cmd += ["-sql", sql] if sql else ["-l", layer]
    cmd += [src, target_tif]
    return run_cmd(cmd, log, stderr_path=tools_log)


def write_float_tif(path: Path, data: np.ndarray, frame: Frame) -> None:
    with rasterio.open(path, "w", width=frame.width, height=frame.height, count=1, dtype="float32", crs=frame.crs,
                       transform=frame.transform, predictor=3, **GTIFF_OPTS) as ds:
        ds.write(data, 1)


def build_land_mask(land_fgb: Path, water_fgb: Path, frame: Frame, out_tif: Path, min_water_m2: float,
                    log: logging.Logger, workdir: Path) -> int:
    """land = 1 where osmdata land polygons cover the cell centre, minus water polygons of at least min_water_m2
    (area measured in the frame's equal-area CRS). Cell-centre rule for both; no ALL_TOUCHED.
    Returns the peak RSS in bytes over the commands it ran."""
    tools_log = Path(workdir) / "tools.log"
    create_raster(frame, out_tif)
    land_res = rasterize(land_fgb, "land", out_tif, log, tools_log, burn=1)
    water_proj = Path(workdir) / "water_proj.fgb"
    water_proj.unlink(missing_ok=True)
    proj_res = run_cmd(["ogr2ogr", "-f", "FlatGeobuf", water_proj, water_fgb, "-t_srs", frame.crs, "-nln", "water",
                        "-nlt", "PROMOTE_TO_MULTI", "-lco", "SPATIAL_INDEX=YES"], log, stderr_path=tools_log)
    water_res = rasterize(water_proj, "water", out_tif, log, tools_log, burn=0,
                          sql=f"SELECT * FROM water WHERE OGR_GEOM_AREA >= {float(min_water_m2)}")
    return max(r.max_rss_bytes for r in (land_res, proj_res, water_res))


# ---------- distance transform ----------

def untiled_edt(mask: np.ndarray, res_m: float) -> np.ndarray:
    """Single-array reference: metres to the nearest True cell. Debug fallback (POLES_EDT_UNTILED=1)."""
    if not mask.any():
        raise ValueError("no road cell in the mask")
    return (distance_transform_edt(~mask) * res_m).astype(np.float32)


def _tile_job(args):
    mask_path, out_path, shape, r0, r1, c0, c1, overlap, res_m = args
    mask = np.load(mask_path, mmap_mode="r")
    H, W = shape
    wr0, wr1 = max(0, r0 - overlap), min(H, r1 + overlap)
    wc0, wc1 = max(0, c0 - overlap), min(W, c1 + overlap)
    window = np.ascontiguousarray(mask[wr0:wr1, wc0:wc1])
    full = (wr0, wr1, wc0, wc1) == (0, H, 0, W)
    out = np.load(out_path, mmap_mode="r+")
    if not window.any():
        out[r0:r1, c0:c1] = np.inf
        unresolved = 0 if full else (r1 - r0) * (c1 - c0)
    else:
        d = distance_transform_edt(~window)[r0 - wr0:r1 - wr0, c0 - wc0:c1 - wc0]
        out[r0:r1, c0:c1] = (d * res_m).astype(np.float32)
        unresolved = 0 if full else int(np.count_nonzero(d >= overlap))
    out.flush()
    del out
    return (r0, c0, unresolved, rss_bytes(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))


def tiled_edt(road_mask: np.ndarray, res_m: float, overlap_cells: int, tile: int = TILE, workers: int | None = None,
              max_m: float | None = None, stats: dict | None = None) -> np.ndarray:
    """Distance in metres to the nearest True cell, computed per tile with overlap.

    A core cell whose result is below the overlap is exact: any closer road outside the window would be farther
    than the overlap. Cells at or above it are recomputed with doubled overlap until none remain, or, when max_m
    is given, until overlap * res_m >= max_m, after which they are set to max_m ("at least this far"). With
    max_m = None the result is bit-identical to untiled_edt everywhere."""
    H, W = road_mask.shape
    workers = workers or max(1, (os.cpu_count() or 2) - 2)
    tiles = [(r0, min(r0 + tile, H), c0, min(c0 + tile, W)) for r0 in range(0, H, tile) for c0 in range(0, W, tile)]
    pending = {t: int(overlap_cells) for t in tiles}
    doublings = 0
    peak = 0
    with tempfile.TemporaryDirectory(prefix="poles-edt-") as td:
        mask_path = Path(td) / "mask.npy"
        out_path = Path(td) / "dist.npy"
        np.save(mask_path, np.ascontiguousarray(road_mask, dtype=bool))
        np.lib.format.open_memmap(out_path, mode="w+", dtype=np.float32, shape=(H, W)).flush()
        while pending:
            jobs = [(str(mask_path), str(out_path), (H, W), *t, ov, float(res_m)) for t, ov in pending.items()]
            if workers == 1 or len(jobs) == 1:
                results = [_tile_job(j) for j in jobs]
            else:
                with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
                    results = list(pool.map(_tile_job, jobs))
            nxt: dict = {}
            for (t, ov), (_, _, unresolved, rss) in zip(pending.items(), results):
                peak = max(peak, rss)
                if unresolved and not (max_m is not None and ov * res_m >= max_m):
                    nxt[t] = ov * 2
            if nxt:
                doublings += 1
            pending = nxt
        dist = np.array(np.load(out_path, mmap_mode="r"))
    saturated = 0
    if max_m is not None:
        sat = ~(dist < max_m)
        saturated = int(sat.sum())
        dist[sat] = np.float32(max_m)
    elif not np.isfinite(dist).all():
        raise ValueError("no road cell in the mask")
    if stats is not None:
        stats.update({"tiles": len(tiles), "overlap_cells": int(overlap_cells), "doublings": doublings,
                      "saturated_cells": saturated, "worker_peak_rss_bytes": peak})
    return dist


# ---------- stage ----------

@contextmanager
def _step(log: logging.Logger, meta: dict, name: str):
    t0 = time.monotonic()
    log.info("-- %s", name)
    info: dict = {}
    yield info
    info.update({"duration_s": round(time.monotonic() - t0, 1),
                 "peak_rss_self_bytes": rss_bytes(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)})
    meta["steps"][name] = info
    log.info("-- %s done in %.0fs", name, info["duration_s"])


def _count_violations(a_tif: Path, b_tif: Path) -> int:
    violations = 0
    with rasterio.open(a_tif) as a, rasterio.open(b_tif) as b:
        for _, window in a.block_windows(1):
            violations += int(np.count_nonzero(a.read(1, window=window) > b.read(1, window=window)))
    return violations


def run(cfg: RegionConfig, ws: Workspace, log: logging.Logger) -> dict:
    require_tools(["gdal_rasterize", "ogr2ogr"])
    fetch_dir, extract_dir, classify_dir, out_dir = ws.dir("fetch"), ws.dir("extract"), ws.dir("classify"), ws.dir(STAGE)
    tools_log = out_dir / "tools.log"
    snapshot = json.loads((fetch_dir / "snapshot.json").read_text(encoding="utf-8"))
    primary_polys = [parse_poly(fetch_dir / s["poly"]) for s in snapshot["sources"] if s["role"] == "primary"]
    frame = frame_from_polygons(primary_polys, "EPSG:4326", cfg.coarse_crs, cfg.coarse_res_m, cfg.max_distance_m)
    (out_dir / "frame.json").write_text(json.dumps(frame.to_dict(), indent=2) + "\n", encoding="utf-8")
    log.info("frame %d x %d cells (%.0f M) at %d m in %s; margin %d m", frame.width, frame.height,
             frame.width * frame.height / 1e6, cfg.coarse_res_m, cfg.coarse_crs, cfg.max_distance_m)
    meta: dict = {"frame": frame.to_dict(), "steps": {}, "edt": {}}
    overlap = math.ceil(cfg.max_distance_m / cfg.coarse_res_m)
    workers = int(os.environ.get("POLES_WORKERS", "0")) or None
    untiled = os.environ.get("POLES_EDT_UNTILED") == "1"

    for scenario in ("A", "B"):
        mask_tif = out_dir / f"roads_{scenario}.tif"
        with _step(log, meta, f"rasterize_{scenario}") as info:
            create_raster(frame, mask_tif)
            info["tool_peak_rss_bytes"] = rasterize(classify_dir / f"roads_{scenario}.fgb", f"roads_{scenario}",
                                                    mask_tif, log, tools_log, burn=1, all_touched=True).max_rss_bytes
        with _step(log, meta, f"edt_{scenario}") as info:
            with rasterio.open(mask_tif) as ds:
                mask = ds.read(1).astype(bool)
            meta[f"road_cells_{scenario}"] = int(mask.sum())
            stats: dict = {}
            if untiled:
                dist = untiled_edt(mask, cfg.coarse_res_m)
            else:
                dist = tiled_edt(mask, cfg.coarse_res_m, overlap, TILE, workers, max_m=float(cfg.max_distance_m), stats=stats)
            del mask
            info["worker_peak_rss_bytes"] = stats.get("worker_peak_rss_bytes")
            meta["edt"].update({"tiles": stats.get("tiles"), "overlap_cells": overlap, "doublings": stats.get("doublings"),
                                f"saturated_cells_{scenario}": stats.get("saturated_cells")})
            write_float_tif(out_dir / f"dist_{scenario}.tif", dist, frame)
            del dist

    with _step(log, meta, "land") as info:
        info["tool_peak_rss_bytes"] = build_land_mask(ws.shared_dir() / "land.fgb", extract_dir / "water.fgb", frame,
                                                      out_dir / "land.tif", 1_000_000, log, out_dir)
        with rasterio.open(out_dir / "land.tif") as ds:
            meta["land_cells"] = int(sum(int(ds.read(1, window=w).sum()) for _, w in ds.block_windows(1)))

    with _step(log, meta, "invariant_a_le_b"):
        meta["a_le_b_violations"] = _count_violations(out_dir / "dist_A.tif", out_dir / "dist_B.tif")
        if meta["a_le_b_violations"]:
            raise GridError(f"A > B at {meta['a_le_b_violations']} cells; the road masks are inconsistent")
    return meta
