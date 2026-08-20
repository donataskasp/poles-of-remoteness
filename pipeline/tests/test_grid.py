import numpy as np
import pytest
import rasterio
import shapely
from pyproj import Transformer
from scipy.ndimage import distance_transform_edt

from poles import grid
from tests.helpers import write_fgb


# ---------- distance transform ----------

def test_untiled_edt_is_scipy_times_res():
    mask = np.zeros((10, 10), bool)
    mask[5, 5] = True
    got = grid.untiled_edt(mask, 250.0)
    assert got.dtype == np.float32
    assert np.array_equal(got, (distance_transform_edt(~mask) * 250.0).astype(np.float32))


def test_tiled_equals_untiled_random_sparse_roads():
    rng = np.random.default_rng(7)
    mask = rng.random((200, 200)) < 0.01
    ref = grid.untiled_edt(mask, 250.0)
    got = grid.tiled_edt(mask, 250.0, overlap_cells=20, tile=64, workers=2)
    assert got.dtype == np.float32 and got.shape == mask.shape
    assert np.array_equal(got, ref)


def test_tiled_equals_untiled_when_overlap_too_small_forces_doubling():
    mask = np.zeros((300, 300), bool)
    mask[0, 0] = True
    ref = grid.untiled_edt(mask, 50.0)
    stats = {}
    got = grid.tiled_edt(mask, 50.0, overlap_cells=16, tile=128, workers=1, stats=stats)
    assert np.array_equal(got, ref)
    assert stats["doublings"] > 0


def test_max_m_saturates_far_cells_and_keeps_near_cells_exact():
    mask = np.zeros((300, 300), bool)
    mask[150, 150] = True
    ref = grid.untiled_edt(mask, 10.0)
    stats = {}
    got = grid.tiled_edt(mask, 10.0, overlap_cells=8, tile=100, workers=1, max_m=500.0, stats=stats)
    near = ref < 500.0
    assert np.array_equal(got[near], ref[near])
    assert np.all(got[~near] == np.float32(500.0))
    assert stats["saturated_cells"] == int((~near).sum())


def test_no_roads_raises_without_cap_and_saturates_with_cap():
    mask = np.zeros((50, 50), bool)
    with pytest.raises(ValueError, match="no road"):
        grid.tiled_edt(mask, 1.0, overlap_cells=4, tile=25, workers=1)
    assert np.all(grid.tiled_edt(mask, 1.0, overlap_cells=4, tile=25, workers=1, max_m=9.0) == np.float32(9.0))


def test_tiled_handles_non_multiple_shapes_and_all_road_tiles():
    mask = np.zeros((130, 70), bool)
    mask[:64, :64] = True
    ref = grid.untiled_edt(mask, 1.0)
    assert np.array_equal(grid.tiled_edt(mask, 1.0, overlap_cells=8, tile=64, workers=2), ref)


# ---------- frame ----------

def test_frame_bounds_snap_outward_to_resolution():
    poly = shapely.box(100.3, 200.7, 1100.2, 1300.9)
    f = grid.frame_from_polygons([poly], "EPSG:3035", "EPSG:3035", 250, margin_m=0)
    assert (f.x0, f.y0, f.x1, f.y1) == (0, 0, 1250, 1500)
    assert (f.width, f.height) == (5, 6)
    g = grid.frame_from_polygons([poly], "EPSG:3035", "EPSG:3035", 250, margin_m=300)
    assert (g.x0, g.y0, g.x1, g.y1) == (-250, -250, 1500, 1750)
    assert grid.Frame.from_dict(g.to_dict()) == g


def test_frame_reprojects_lonlat_polygon():
    f = grid.frame_from_polygons([shapely.box(9.9, 51.9, 10.1, 52.1)], "EPSG:4326", "EPSG:3035", 250, 0)
    cx, cy = (f.x0 + f.x1) / 2, (f.y0 + f.y1) / 2
    assert abs(cx - 4_321_000) < 1_000 and abs(cy - 3_210_000) < 1_000
    assert f.transform.a == 250 and f.transform.e == -250


# ---------- rasterize and land mask (need gdal_rasterize, ogr2ogr) ----------

def _frame_20km() -> grid.Frame:
    return grid.Frame("EPSG:3035", 250, 4_300_000, 3_220_000, 80, 80)


def test_rasterize_lonlat_roads_land_in_projected_frame(tmp_path, log):
    frame = _frame_20km()
    to_lonlat = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True).transform
    cx, cy = 4_310_125, 3_209_875   # centre of cell (row 40, col 40)
    line = shapely.LineString([to_lonlat(cx - 600, cy), to_lonlat(cx + 600, cy)])
    write_fgb(tmp_path / "roads.fgb", "roads", [line], {"way_id": [1]}, crs="EPSG:4326")
    out = tmp_path / "roads.tif"
    grid.create_raster(frame, out)
    grid.rasterize(tmp_path / "roads.fgb", "roads", out, log, tmp_path / "tools.log", burn=1, all_touched=True)
    with rasterio.open(out) as ds:
        arr = ds.read(1)
        assert ds.crs.to_epsg() == 3035 and ds.transform == frame.transform
    assert arr[40, 40] == 1 and arr[40, 38] == 1 and arr[40, 42] == 1
    assert 5 <= arr.sum() <= 12 and arr[0, 0] == 0


def test_land_mask_subtracts_lakes_over_threshold_only(tmp_path, log):
    frame = _frame_20km()
    land = shapely.box(4_300_000, 3_200_000, 4_320_000, 3_220_000)
    big = shapely.box(4_305_000, 3_205_000, 4_307_000, 3_207_000)        # 4 km2: removed
    small = shapely.box(4_312_000, 3_212_000, 4_312_500, 3_212_500)      # 0.25 km2: stays land
    write_fgb(tmp_path / "land.fgb", "land", [land], {"fid": [1]}, crs="EPSG:3035")
    write_fgb(tmp_path / "water.fgb", "water", [big, small], {"osm_id": [1, 2]}, crs="EPSG:3035")
    out = tmp_path / "land.tif"
    grid.build_land_mask(tmp_path / "land.fgb", tmp_path / "water.fgb", frame, out, 1_000_000, log, tmp_path)
    with rasterio.open(out) as ds:
        arr = ds.read(1)
    row = lambda y: int((frame.y1 - y) // frame.res)
    col = lambda x: int((x - frame.x0) // frame.res)
    assert arr[row(3_206_000), col(4_306_000)] == 0
    assert arr[row(3_212_250), col(4_312_250)] == 1
    assert arr[10, 10] == 1
    assert int(arr.sum()) == 80 * 80 - 64


def test_land_mask_with_lonlat_inputs(tmp_path, log):
    """The real inputs are WGS84: land from osmdata, water from OSM. The mask must still land in the frame."""
    frame = _frame_20km()
    to_lonlat = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    land = shapely.ops.transform(to_lonlat.transform, shapely.box(4_300_000, 3_200_000, 4_320_000, 3_220_000).segmentize(250))
    lake = shapely.ops.transform(to_lonlat.transform, shapely.box(4_305_000, 3_205_000, 4_307_000, 3_207_000).segmentize(100))
    write_fgb(tmp_path / "land.fgb", "land", [land], {"fid": [1]}, crs="EPSG:4326")
    write_fgb(tmp_path / "water.fgb", "water", [lake], {"osm_id": [1]}, crs="EPSG:4326")
    out = tmp_path / "land.tif"
    grid.build_land_mask(tmp_path / "land.fgb", tmp_path / "water.fgb", frame, out, 1_000_000, log, tmp_path)
    with rasterio.open(out) as ds:
        arr = ds.read(1)
    assert arr[int((3_220_000 - 3_206_000) // 250), int((4_306_000 - 4_300_000) // 250)] == 0
    assert abs(int(arr.sum()) - (6400 - 64)) <= 40
