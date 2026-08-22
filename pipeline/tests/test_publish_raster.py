import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
import shapely
from shapely.geometry import box

from poles.classes import EDGE, NODATA, ClassTable
from poles.shell import ToolError
from poles.grid import Frame, create_raster, write_float_tif
from poles.publish import raster

# A small frame in EPSG:3035 around 24E 55N (Lithuania). 250 m cells.
FRAME = Frame(crs="EPSG:3035", res=250, x0=5_300_000, y1=3_660_000, width=40, height=32)


def _write(path: Path, data: np.ndarray, dtype: str, nodata=None, frame: Frame = FRAME):
    create_raster(frame, path, dtype, nodata)
    with rasterio.open(path, "r+") as ds:
        ds.write(data.astype(dtype), 1)


def test_quantise_applies_table_and_masks(tmp_path, log):
    dist = np.full((32, 40), 75.0, dtype=np.float32)       # class 1
    dist[0, :] = 250_000.0                                 # saturated: class 253
    dist[1, :] = 2_500.0                                   # class 50
    land = np.ones((32, 40), dtype=np.uint8)
    land[:, 0] = 0                                         # water column
    inside = np.ones((32, 40), dtype=np.uint8)
    inside[:, 39] = 0                                      # outside the data
    band = np.zeros((32, 40), dtype=np.uint8)
    band[31, :] = 1                                        # edge band row
    for name, arr, dt in [("dist", dist, "float32"), ("land", land, "uint8"), ("inside", inside, "uint8"), ("band", band, "uint8")]:
        _write(tmp_path / f"{name}.tif", arr, dt)
    out = tmp_path / "explore.tif"
    stats = raster.quantise(tmp_path / "dist.tif", tmp_path / "land.tif", tmp_path / "inside.tif", tmp_path / "band.tif",
                            out, ClassTable(), log)
    with rasterio.open(out) as ds:
        assert ds.nodatavals == (NODATA,) and ds.dtypes == ("uint8",) and ds.crs.to_string() == "EPSG:3035"
        cls = ds.read(1)
    assert cls[5, 5] == 1 and cls[0, 5] == 253 and cls[1, 5] == 50
    assert (cls[:, 0] == NODATA).all() and (cls[:, 39] == NODATA).all()
    assert cls[31, 5] == EDGE and cls[31, 0] == NODATA          # nodata wins over the band
    assert stats == {"cells": 32 * 40, "nodata": 64, "edge": 38, "classed": 32 * 40 - 64 - 38}


def test_edge_masks_band_hugs_the_boundary(tmp_path, log):
    # Edge polygon: the middle of the frame, as lon/lat. Band 1 km wide: a thin ring inside and outside it.
    from pyproj import Transformer
    to_ll = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    poly_3035 = box(FRAME.x0 + 2_000, FRAME.y0 + 2_000, FRAME.x1 - 2_000, FRAME.y1 - 2_000)
    edge_4326 = shapely.transform(poly_3035, lambda c: np.column_stack(to_ll.transform(c[:, 0], c[:, 1])))
    inside_tif, band_tif = raster.edge_masks(edge_4326, FRAME, 1_000, tmp_path, log, tmp_path / "tools.log")
    with rasterio.open(inside_tif) as ds:
        inside = ds.read(1)
    with rasterio.open(band_tif) as ds:
        band = ds.read(1)
    assert inside[16, 20] == 1 and inside[0, 0] == 0 and inside[31, 39] == 0
    assert band[16, 20] == 0                     # frame centre is 4 km from the boundary
    assert band[8, 20] == 1 and band[6, 20] == 1  # rows 7..8 straddle the northern boundary (y = y1 - 2 km)
    assert band[13, 20] == 0 and band[16, 20] == 0
    assert (tmp_path / "edgeband_4326.wkb").exists()
    assert (tmp_path / "inside.tif.ok").exists() and (tmp_path / "edgeband.tif.ok").exists()
    ring = shapely.from_wkb((tmp_path / "edgeband_4326.wkb").read_bytes())
    assert ring.contains(shapely.Point(to_ll.transform(FRAME.x0 + 2_000, FRAME.y0 + 4_000)))


def test_edge_polygon_unions_every_source(tmp_path):
    (tmp_path / "a.poly").write_text("a\n1\n  10 50\n  12 50\n  12 52\n  10 52\nEND\nEND\n")
    (tmp_path / "b.poly").write_text("b\n1\n  11 51\n  13 51\n  13 53\n  11 53\nEND\nEND\n")
    (tmp_path / "snapshot.json").write_text(json.dumps({"sources": [{"poly": "a.poly"}, {"poly": "b.poly"}]}))
    geom = raster.edge_polygon(tmp_path)
    assert geom.contains(shapely.Point(10.5, 50.5)) and geom.contains(shapely.Point(12.5, 52.5))
    assert abs(geom.area - 7.0) < 1e-9


def test_warp_to_mercator_is_tile_aligned(tmp_path, log):
    cls = np.random.default_rng(1).integers(0, 254, size=(32, 40), dtype=np.uint8)
    cls[:, 0] = NODATA
    _write(tmp_path / "explore.tif", cls, "uint8", nodata=NODATA)
    out = raster.warp_to_mercator(tmp_path / "explore.tif", tmp_path / "explore_3857.tif", log, tmp_path / "tools.log")
    with rasterio.open(out) as ds:
        assert ds.crs.to_string() == "EPSG:3857" and ds.nodatavals == (NODATA,) and ds.dtypes == ("uint8",)
        assert abs(ds.res[0] - raster.Z9_RES) < 1e-9 and abs(ds.res[1] - raster.Z9_RES) < 1e-9
        x0, y1 = ds.transform.c, ds.transform.f
        assert abs((x0 + raster.MERC_MAX) / raster.Z9_RES - round((x0 + raster.MERC_MAX) / raster.Z9_RES)) < 1e-6
        assert abs((raster.MERC_MAX - y1) / raster.Z9_RES - round((raster.MERC_MAX - y1) / raster.Z9_RES)) < 1e-6
        data = ds.read(1)
    assert set(np.unique(data)).issubset(set(np.unique(cls)) | {NODATA})
    assert (data != NODATA).sum() > 0


# ---------- beyond the plan's four: the cases the production grids hit ----------

def test_quantise_treats_unusable_distances_as_nodata(tmp_path, log):
    """NaN and the source's own nodata never reach the class table; they publish as NODATA."""
    dist = np.full((32, 40), 1_000.0, dtype=np.float32)     # class 20
    dist[2, :5] = np.nan
    dist[3, :5] = -9999.0                                   # the source's nodata marker
    dist[4, :5] = np.inf
    write_float_tif(tmp_path / "dist.tif", dist, FRAME)     # predictor=3, as the grid stage writes it
    with rasterio.open(tmp_path / "dist.tif", "r+") as ds:
        ds.nodata = -9999.0
    for name in ("land", "inside"):
        _write(tmp_path / f"{name}.tif", np.ones((32, 40), dtype=np.uint8), "uint8")
    _write(tmp_path / "band.tif", np.zeros((32, 40), dtype=np.uint8), "uint8")
    out = tmp_path / "explore.tif"
    stats = raster.quantise(tmp_path / "dist.tif", tmp_path / "land.tif", tmp_path / "inside.tif", tmp_path / "band.tif",
                            out, ClassTable(), log)
    with rasterio.open(out) as ds:
        cls = ds.read(1)
    assert (cls[2:5, :5] == NODATA).all()
    assert cls[2, 5] == 20 and cls[10, 10] == 20
    assert stats == {"cells": 32 * 40, "nodata": 15, "edge": 0, "classed": 32 * 40 - 15}


def test_quantise_windows_a_grid_wider_than_one_block(tmp_path, log):
    """More than one 512 x 512 block, and neither side a multiple of 512: every window lands where it belongs."""
    frame = Frame(crs="EPSG:3035", res=250, x0=5_300_000, y1=3_660_000, width=600, height=520)
    rng = np.random.default_rng(7)
    dist = rng.uniform(0, 300_000, size=(520, 600)).astype(np.float32)
    land = np.ones((520, 600), dtype=np.uint8)
    land[520 - 8:, :] = 0                       # an all-nodata strip in the bottom block row
    inside = np.ones((520, 600), dtype=np.uint8)
    band = np.zeros((520, 600), dtype=np.uint8)  # an all-zero band raster
    for name, arr, dt in [("dist", dist, "float32"), ("land", land, "uint8"), ("inside", inside, "uint8"), ("band", band, "uint8")]:
        _write(tmp_path / f"{name}.tif", arr, dt, frame=frame)
    table = ClassTable()
    out = tmp_path / "explore.tif"
    stats = raster.quantise(tmp_path / "dist.tif", tmp_path / "land.tif", tmp_path / "inside.tif", tmp_path / "band.tif",
                            out, table, log)
    with rasterio.open(tmp_path / "dist.tif") as ds:
        assert len(list(ds.block_windows(1))) == 4
    with rasterio.open(out) as ds:
        cls = ds.read(1)
    expected = table.to_class(dist)  # the table saturates at class 253 on its own, no clamp needed
    expected[land == 0] = NODATA
    assert (cls == expected).all()
    assert stats == {"cells": 600 * 520, "nodata": 600 * 8, "edge": 0, "classed": 600 * 512}


def test_quantise_rejects_a_mask_off_the_distance_grid(tmp_path, log):
    other = Frame(crs="EPSG:3035", res=250, x0=5_300_000, y1=3_660_000, width=40, height=16)
    _write(tmp_path / "dist.tif", np.zeros((32, 40), dtype=np.float32), "float32")
    _write(tmp_path / "land.tif", np.ones((32, 40), dtype=np.uint8), "uint8")
    _write(tmp_path / "inside.tif", np.ones((32, 40), dtype=np.uint8), "uint8")
    _write(tmp_path / "band.tif", np.zeros((16, 40), dtype=np.uint8), "uint8", frame=other)
    with pytest.raises(ValueError, match="band.tif"):
        raster.quantise(tmp_path / "dist.tif", tmp_path / "land.tif", tmp_path / "inside.tif", tmp_path / "band.tif",
                        tmp_path / "explore.tif", ClassTable(), log)


def test_edge_masks_and_warp_skip_finished_outputs(tmp_path, log):
    from pyproj import Transformer
    to_ll = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    poly_3035 = box(FRAME.x0 + 2_000, FRAME.y0 + 2_000, FRAME.x1 - 2_000, FRAME.y1 - 2_000)
    edge_4326 = shapely.transform(poly_3035, lambda c: np.column_stack(to_ll.transform(c[:, 0], c[:, 1])))
    inside_tif, band_tif = raster.edge_masks(edge_4326, FRAME, 1_000, tmp_path, log, tmp_path / "tools.log")
    stamp = inside_tif.stat().st_mtime_ns
    raster.edge_masks(edge_4326, FRAME, 1_000, tmp_path, log, tmp_path / "tools.log")
    assert inside_tif.stat().st_mtime_ns == stamp
    assert (tmp_path / "edgeband_4326.wkb.ok").exists()
    (tmp_path / "edgeband_4326.wkb").unlink()  # the wkb is an output too, so a resume without it rebuilds
    raster.edge_masks(edge_4326, FRAME, 1_000, tmp_path, log, tmp_path / "tools.log")
    assert raster._done(tmp_path / "edgeband_4326.wkb")

    _write(tmp_path / "explore.tif", np.zeros((32, 40), dtype=np.uint8), "uint8", nodata=NODATA)
    out = raster.warp_to_mercator(tmp_path / "explore.tif", tmp_path / "explore_3857.tif", log, tmp_path / "tools.log")
    warped = out.stat().st_mtime_ns
    raster.warp_to_mercator(tmp_path / "explore.tif", tmp_path / "explore_3857.tif", log, tmp_path / "tools.log")
    assert out.stat().st_mtime_ns == warped


def test_project_densifies_before_it_reprojects():
    """A side straight in lon/lat is a curve in the frame CRS: without densifying, a continental outline lands
    tens of kilometres from the real one, and the masks with it."""
    from pyproj import Transformer
    to_frame = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
    to_ll = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)

    def vertices_only(geom, tr):
        return shapely.transform(geom, lambda c: np.column_stack(tr.transform(c[:, 0], c[:, 1])))

    def max_offset(truth, line):
        """Farthest any point of the true curve sits from the polyline under test."""
        return float(shapely.distance(shapely.points(shapely.get_coordinates(truth)), line).max())

    outline = box(20.0, 45.0, 45.0, 75.0)  # the eastern side is 30 degrees of the 45E meridian
    truth = vertices_only(shapely.segmentize(outline, 0.02), to_frame).boundary
    projected = raster._project(outline, "EPSG:4326", "EPSG:3035", raster.SEGMENT_DEG)
    assert max_offset(truth, projected.boundary) < FRAME.res  # within one coarse cell
    assert max_offset(truth, vertices_only(outline, to_frame).boundary) > 10_000  # what vertices alone would do

    back = raster._project(projected, "EPSG:3035", "EPSG:4326", raster.SEGMENT_M)  # and the way back, for the wkb
    probes = shapely.get_coordinates(shapely.segmentize(projected.boundary, 5_000.0))
    truth_ll = shapely.points(np.column_stack(to_ll.transform(probes[:, 0], probes[:, 1])))
    assert float(shapely.distance(truth_ll, back.boundary).max()) < 1e-5  # about a metre


def _edge_polygon_over_the_frame() -> shapely.Geometry:
    from pyproj import Transformer
    to_ll = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    poly_3035 = box(FRAME.x0 + 2_000, FRAME.y0 + 2_000, FRAME.x1 - 2_000, FRAME.y1 - 2_000)
    return shapely.transform(poly_3035, lambda c: np.column_stack(to_ll.transform(c[:, 0], c[:, 1])))


def test_edge_masks_drop_the_marker_before_rewriting(tmp_path, log, monkeypatch):
    """A crash while rewriting must not leave a done marker beside a truncated raster."""
    edge_4326 = _edge_polygon_over_the_frame()
    inside_tif, band_tif = raster.edge_masks(edge_4326, FRAME, 1_000, tmp_path, log, tmp_path / "tools.log")
    band_tif.with_name(band_tif.name + raster.MARKER).unlink()  # as a crash after inside.tif would leave it

    def explode(*args, **kwargs):
        raise ToolError("gdal_rasterize died")

    monkeypatch.setattr(raster, "rasterize", explode)
    with pytest.raises(ToolError):
        raster.edge_masks(edge_4326, FRAME, 1_000, tmp_path, log, tmp_path / "tools.log")
    assert inside_tif.exists() and not raster._done(inside_tif)  # truncated by create_raster, and no longer "done"
    monkeypatch.undo()

    raster.edge_masks(edge_4326, FRAME, 1_000, tmp_path, log, tmp_path / "tools.log")
    with rasterio.open(inside_tif) as ds:
        assert ds.read(1).any()  # rebuilt, not trusted


def test_warp_drops_the_marker_before_rewriting(tmp_path, log, monkeypatch):
    cls = np.zeros((32, 40), dtype=np.uint8)
    _write(tmp_path / "explore.tif", cls, "uint8", nodata=NODATA)
    out = tmp_path / "explore_3857.tif"
    out.with_name(out.name + raster.MARKER).touch()  # a marker left over from a run whose output is gone

    def explode(*args, **kwargs):
        raise ToolError("gdalwarp died")

    monkeypatch.setattr(raster, "run_cmd", explode)
    with pytest.raises(ToolError):
        raster.warp_to_mercator(tmp_path / "explore.tif", out, log, tmp_path / "tools.log")
    assert not out.with_name(out.name + raster.MARKER).exists()
    monkeypatch.undo()

    raster.warp_to_mercator(tmp_path / "explore.tif", out, log, tmp_path / "tools.log")
    assert raster._done(out)
