import json
import math
from concurrent.futures.process import BrokenProcessPool
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import rasterio
import shapely
from pyproj import Transformer
from shapely.geometry import LineString, box

from poles.classes import EDGE, NODATA, ClassTable, default_edges
from poles.errors import PolesError
from poles.publish import detail
from poles.refine import UtmRoads, utm_epsg
from poles.roads import RoadSet, build_tiles
from poles.workspace import Workspace
from tests.helpers import write_fgb

# A detail raster carries its georeference in its sidecar, not in the PNG, so rasterio's warning is noise.
pytestmark = pytest.mark.filterwarnings("ignore::rasterio.errors.NotGeoreferencedWarning")

LAT, LON = 55.0, 24.0


class _DyingPool:
    """Runs the first job in this process, then dies the way a worker killed by the OOM killer does."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def map(self, fn, jobs, chunksize=1):
        def gen():
            yield fn(list(jobs)[0])
            raise BrokenProcessPool("A process in the process pool was terminated abruptly")
        return gen()


def _roads_through(lat, lon, epsg):
    """One east-west road 1 km south of (lat, lon), in the zone's UTM coordinates, as an EPSG:4326 RoadSet."""
    to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    to_ll = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    x, y = to_utm.transform(lon, lat)
    line = LineString([to_ll.transform(x - 50_000, y - 1_000), to_ll.transform(x + 50_000, y - 1_000)])
    return RoadSet(np.array([line], dtype=object), {"osm_id": np.array([1], dtype=object), "highway": np.array(["track"], dtype=object)})


def test_georef_matches_spec():
    g = detail.georef(60.0, 10.0, 50, 20_000)
    assert g.width == g.height == 400
    assert math.isclose(g.dlat, 50 / 111_320)
    assert math.isclose(g.dlon, g.dlat / math.cos(math.radians(60.0)))
    assert math.isclose(g.west, 10.0 - 200 * g.dlon) and math.isclose(g.north, 60.0 + 200 * g.dlat)
    assert set(g.to_dict()) == {"west", "north", "dlon", "dlat", "width", "height"}


def test_classify_window_distances_masks_and_bands():
    epsg = utm_epsg(LON, LAT)
    roads = UtmRoads(_roads_through(LAT, LON, epsg), epsg)
    g = detail.georef(LAT, LON, 50, 2_000)                      # 40 x 40 pixels
    lons, lats = detail.centres(g)
    assert len(lons) == 40 and len(lats) == 40
    band = box(g.west, g.north - 2 * g.dlat, g.west + 40 * g.dlon, g.north)   # the top two rows
    land_ok = lambda lo, la: np.asarray(lo) > g.west + 3 * g.dlon                 # first three columns are water
    arr = detail.classify_window(g, roads, land_ok, band, ClassTable())
    assert arr.shape == (40, 40) and arr.dtype == np.uint8
    assert (arr[0, 3:] == EDGE).all() and (arr[1, 3:] == EDGE).all()
    assert (arr[:, :3] == NODATA).all()
    centre = arr[20, 20]                                         # the pole itself sits 1 km from the road: class 20
    assert centre in (19, 20)
    assert arr[39, 20] < arr[20, 20] < arr[2, 20]                # distance grows northwards, away from the road


def test_write_and_read_back(tmp_path):
    g = detail.georef(LAT, LON, 50, 2_000)
    arr = np.arange(1600, dtype=np.uint16).reshape(40, 40).astype(np.uint8)
    png, js = detail.write_detail(tmp_path, "lt", "A", 3, arr, g)
    assert png == tmp_path / "lt" / "A-3.png" and js == tmp_path / "lt" / "A-3.json"
    with rasterio.open(png) as ds:
        assert ds.count == 1 and np.array_equal(ds.read(1), arr)
    assert json.loads(js.read_text()) == g.to_dict()


def test_land_test_uses_land_minus_big_water(tmp_path):
    land = box(23.9, 54.9, 24.1, 55.1)
    water = box(24.0, 55.0, 24.05, 55.05)
    write_fgb(tmp_path / "land_idx.fgb", "land", [land], {"id": [1]})
    write_fgb(tmp_path / "water_big.fgb", "water", [water], {"id": [1]})
    ok = detail.land_test(tmp_path / "land_idx.fgb", tmp_path / "water_big.fgb", (23.8, 54.8, 24.2, 55.2))
    got = ok(np.array([23.95, 24.02, 24.5]), np.array([54.95, 55.02, 55.0]))
    assert got.tolist() == [True, False, False]


# ---------- beyond the plan's four: the cases a continental run hits ----------

def test_georef_keeps_the_window_square_in_metres_at_a_high_latitude():
    """A window 20 km wide at 78 N spans nearly five times the longitude it does at the equator."""
    g = detail.georef(78.0, 15.0, 50, 20_000)
    assert g.width == g.height == 400
    assert math.isclose(g.dlon / g.dlat, 1 / math.cos(math.radians(78.0)))
    span_m = g.dlon * g.width * math.cos(math.radians(78.0)) * 111_320
    assert math.isclose(span_m, 20_000, rel_tol=1e-9)
    lons, lats = detail.centres(g)
    assert math.isclose(lons[0], g.west + g.dlon / 2) and math.isclose(lats[0], g.north - g.dlat / 2)
    assert math.isclose(lons[-1], g.west + g.dlon * (g.width - 0.5))


def test_classify_window_matches_hand_measured_distances():
    """Every pixel against the distance measured straight from the road geometry, not through the tree."""
    epsg = utm_epsg(LON, LAT)
    roads = UtmRoads(_roads_through(LAT, LON, epsg), epsg)
    g = detail.georef(LAT, LON, 50, 2_000)
    table = ClassTable()
    arr = detail.classify_window(g, roads, lambda lo, la: np.ones(len(np.asarray(lo)), bool), None, table)
    lons, lats = detail.centres(g)
    glon, glat = np.meshgrid(lons, lats)
    x, y = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True).transform(glon.ravel(), glat.ravel())
    hand = shapely.distance(shapely.points(np.asarray(x), np.asarray(y)), roads.geoms[0]).reshape(40, 40)
    assert np.array_equal(arr, table.to_class(hand))
    assert hand[20, 20] == pytest.approx(975, abs=10)    # the pole is 1 km out, its pixel centre 25 m nearer
    assert arr[20, 20] == 19


def test_classify_window_is_continuous_across_a_utm_zone_seam():
    """A window straddling 6 E is measured wholly in the zone of its centre, so no column jumps at the seam."""
    lat, lon = 55.0, 6.0
    epsg = utm_epsg(lon, lat)
    roads = UtmRoads(_roads_through(lat, lon, epsg), epsg)
    g = detail.georef(lat, lon, 50, 2_000)
    assert g.west < 6.0 < g.west + g.dlon * g.width               # the seam runs down the middle of the window
    arr = detail.classify_window(g, roads, lambda lo, la: np.ones(len(np.asarray(lo)), bool), None, ClassTable())
    row = arr[20].astype(int)
    # The row tilts against the grid this far from the central meridian, so the distance drifts along it; what
    # a second zone would add is a step of many classes at the seam, and there is none.
    assert np.abs(np.diff(row)).max() <= 1


def test_classify_window_all_edge_when_the_window_sits_in_the_band():
    epsg = utm_epsg(LON, LAT)
    roads = UtmRoads(_roads_through(LAT, LON, epsg), epsg)
    g = detail.georef(LAT, LON, 50, 2_000)
    band = box(g.west - 1, g.north - g.dlat * g.height - 1, g.west + g.dlon * g.width + 1, g.north + 1)
    arr = detail.classify_window(g, roads, lambda lo, la: np.ones(len(np.asarray(lo)), bool), band, ClassTable())
    assert (arr == EDGE).all()


def test_classify_window_saturates_without_roads():
    """No road within reach leaves every land pixel in the open-ended top class, never in EDGE or a nodata gap."""
    g = detail.georef(LAT, LON, 50, 2_000)
    roads = UtmRoads(RoadSet.empty(("osm_id", "highway")), utm_epsg(LON, LAT))
    land_ok = lambda lo, la: np.asarray(lo) > g.west + 3 * g.dlon
    arr = detail.classify_window(g, roads, land_ok, None, ClassTable())
    assert (arr[:, 3:] == 253).all() and (arr[:, :3] == NODATA).all()


def test_write_detail_leaves_no_aux_file(tmp_path):
    g = detail.georef(LAT, LON, 50, 2_000)
    png, js = detail.write_detail(tmp_path, "lt", "B", 1, np.zeros((40, 40), np.uint8), g)
    assert sorted(p.name for p in (tmp_path / "lt").iterdir()) == ["B-1.json", "B-1.png"]
    assert json.loads(js.read_text())["width"] == 40


def _tiles_dir(tmp_path: Path, log) -> Path:
    """Road tiles holding a track 1 km south of (55, 24), a residential road 3 km south of it, and a
    residential road 5 km south of (55.1, 24.2)."""
    geoms = [LineString([(23.9, 54.991), (24.1, 54.991)]),
             LineString([(23.9, 54.973), (24.1, 54.973)]),
             LineString([(24.1, 55.055), (24.3, 55.055)])]
    src = write_fgb(tmp_path / "highways.fgb", "highways", geoms,
                    {"osm_id": [1, 2, 3], "highway": ["track", "residential", "residential"],
                     "name": [None] * 3, "ref": [None] * 3})
    out = tmp_path / "roads"
    build_tiles(src, "highways", out, log, tile_deg=10.0, workers=1)
    return out


def _workspace(tmp_path: Path, log) -> Workspace:
    ws = Workspace(tmp_path / "work", "test", "snap")
    poles_dir = ws.dir("poles")
    tiles = _tiles_dir(tmp_path, log)
    tiles.rename(poles_dir / "roads")
    write_fgb(poles_dir / "land_idx.fgb", "land", [box(23.8, 54.8, 24.4, 55.3)], {"id": [1]})
    write_fgb(poles_dir / "water_big.fgb", "water", [box(24.005, 54.99, 24.02, 55.01)], {"id": [1]})
    return ws


def _published() -> dict:
    return {"A": [{"unit": "aa", "poles": [{"rank": 1, "lat": 55.0, "lon": 24.0, "dist_m": 1000.0},
                                           {"rank": 2, "lat": 55.1, "lon": 24.2, "dist_m": 5000.0}],
                   "reason": None},
                  {"unit": "bb", "poles": [], "reason": "no pole"}],
            "B": [{"unit": "aa", "poles": [{"rank": 1, "lat": 55.0, "lon": 24.0, "dist_m": 3000.0}], "reason": None},
                  {"unit": "bb", "poles": [], "reason": "no pole"}]}


def _class_at(png: Path, row: int, col: int) -> int:
    with rasterio.open(png) as ds:
        return int(ds.read(1)[row, col])


def test_run_detail_renders_every_published_pole(tmp_path, cfg, log, monkeypatch):
    monkeypatch.setenv("POLES_WORKERS", "2")
    ws = _workspace(tmp_path, log)
    small = replace(cfg, detail_window_m=2_000)          # 40 x 40 windows keep the pool test to seconds
    out = ws.dir("publish") / "detail"
    stats = detail.run_detail(small, ws, _published(), ClassTable(), None, log)
    assert stats["count"] == 3 and stats["skipped"] == 0 and stats["seconds"] >= 0
    names = sorted(p.name for p in (out / "aa").iterdir())
    assert names == ["A-1.json", "A-1.png", "A-2.json", "A-2.png", "B-1.json", "B-1.png"]
    assert not (out / "bb").exists()                     # a unit with no poles is no job
    assert stats["bytes"] == sum(p.stat().st_size for p in (out / "aa").glob("*.png"))
    a1, b1 = out / "aa" / "A-1.png", out / "aa" / "B-1.png"
    assert _class_at(a1, 20, 20) < _class_at(b1, 20, 20)  # A counts the track 1 km out, B the road 3 km out
    with rasterio.open(a1) as ds:
        arr = ds.read(1)
    assert arr.shape == (40, 40) and (arr == NODATA).any()   # the lake in the middle of the window
    g = json.loads((out / "aa" / "A-1.json").read_text())
    assert g["width"] == g["height"] == 40 and math.isclose(g["dlat"], 50 / 111_320)


def test_run_detail_resumes_and_reruns_when_forced(tmp_path, cfg, log, monkeypatch):
    monkeypatch.setenv("POLES_WORKERS", "1")
    ws = _workspace(tmp_path, log)
    small = replace(cfg, detail_window_m=2_000)
    out = ws.dir("publish") / "detail"
    detail.run_detail(small, ws, _published(), ClassTable(), None, log)
    stamp = (out / "aa" / "A-1.png").stat().st_mtime_ns
    again = detail.run_detail(small, ws, _published(), ClassTable(), None, log)
    assert again["skipped"] == 3 and again["count"] == 3 and again["bytes"] > 0
    assert (out / "aa" / "A-1.png").stat().st_mtime_ns == stamp
    (out / "aa" / "A-2.json").unlink()                   # a PNG without its sidecar is half a raster
    third = detail.run_detail(small, ws, _published(), ClassTable(), None, log)
    assert third["skipped"] == 2 and (out / "aa" / "A-2.json").exists()
    ws.forced = True
    forced = detail.run_detail(small, ws, _published(), ClassTable(), None, log)
    assert forced["skipped"] == 0 and (out / "aa" / "A-1.png").stat().st_mtime_ns != stamp


def test_render_bands_the_pixels_inside_the_edge_band(tmp_path, cfg, log):
    ws = _workspace(tmp_path, log)
    band = box(23.99, 54.99, 24.01, 55.01)               # a square over the middle of the first pole's window
    stats = detail.run_detail(replace(cfg, detail_window_m=2_000), ws, _published(), ClassTable(),
                              band, log)
    assert stats["count"] == 3
    with rasterio.open(ws.dir("publish") / "detail" / "aa" / "A-1.png") as ds:
        arr = ds.read(1)
    assert arr[20, 20] == EDGE                           # inside the band
    assert arr[0, 0] != EDGE and arr[39, 0] != EDGE       # the western columns are outside it


def test_render_refuses_a_pole_with_no_road_in_reach(tmp_path, cfg, log):
    """The pole's own nearest way is inside its padded window by construction, so an empty road set is a
    broken input, not a raster to publish."""
    ws = _workspace(tmp_path, log)
    poles_dir = ws.dir("poles")
    job = detail.DetailJob(str(poles_dir / "roads"), str(poles_dir / "land_idx.fgb"), str(poles_dir / "water_big.fgb"),
                           str(ws.dir("publish") / "detail"), "aa", "A", ((1, 55.28, 24.0, 100.0),), 50, 2_000,
                           b"", tuple(default_edges()))
    with pytest.raises(PolesError, match="aa"):
        detail.render(job)


def test_run_detail_classes_with_the_region_table(tmp_path, cfg, log, monkeypatch):
    """A region that sets its own class edges gets them in the detail rasters, not a worker's default table."""
    monkeypatch.setenv("POLES_WORKERS", "1")
    ws = _workspace(tmp_path, log)
    one = {"A": [{"unit": "aa", "poles": [{"rank": 1, "lat": 55.0, "lon": 24.0, "dist_m": 1000.0}], "reason": None}],
           "B": []}
    coarse = ClassTable([2 * e for e in default_edges()])      # every class twice as wide as the default one
    stats = detail.run_detail(replace(cfg, detail_window_m=2_000), ws, one, coarse, None, log)
    assert stats["count"] == 1
    # The pixel is 977 m from the track (1002 m south of the pole, 25 m of that inside the pixel): class 9 of
    # a table in 100 m steps, where the default table in 50 m steps would say 19.
    assert _class_at(ws.dir("publish") / "detail" / "aa" / "A-1.png", 20, 20) in (9, 10)


def test_render_refuses_a_pole_the_land_index_does_not_know(tmp_path, cfg, log):
    """Stage 2 searched the pole on land, so a land index that disagrees is the wrong file or a bbox handed
    over in the wrong order; either way it would silently blank every raster of the run."""
    ws = _workspace(tmp_path, log)
    poles_dir = ws.dir("poles")
    write_fgb(poles_dir / "land_idx.fgb", "land", [box(10.0, 40.0, 10.1, 40.1)], {"id": [1]})   # another country
    args = (str(poles_dir / "roads"), str(poles_dir / "land_idx.fgb"), str(poles_dir / "water_big.fgb"),
            str(ws.dir("publish") / "detail"), "aa", "A")
    job = detail.DetailJob(*args, ((1, 55.0, 24.0, 1000.0),), 50, 2_000, b"", tuple(default_edges()))
    with pytest.raises(PolesError, match="aa A rank 1"):
        detail.render(job)
    assert not (ws.dir("publish") / "detail" / "aa").exists()
    # A window with a sliver of land in it is a result, not a failure: the threshold is the pole, not an area.
    write_fgb(poles_dir / "land_idx.fgb", "land", [box(23.9995, 54.9997, 24.0005, 55.0003)], {"id": [1]})
    out = detail.render(job)
    assert out["rendered"] == [1] and out["warnings"] == []
    with rasterio.open(ws.dir("publish") / "detail" / "aa" / "A-1.png") as ds:
        arr = ds.read(1)
    assert (arr != NODATA).sum() == 4                    # the four pixel centres inside that sliver


def test_render_publishes_a_sub_pixel_islet_and_warns(tmp_path, cfg, log):
    """A pole can stand on a rock narrower than one pixel (Bell Rock, 14 m across, is a real top-ten pole), so
    an all-nodata window is honest output plus a warning, not a run-stopping error."""
    ws = _workspace(tmp_path, log)
    poles_dir = ws.dir("poles")
    write_fgb(poles_dir / "land_idx.fgb", "land", [box(23.99993, 54.99996, 24.00007, 55.00004)], {"id": [1]})
    job = detail.DetailJob(str(poles_dir / "roads"), str(poles_dir / "land_idx.fgb"),
                           str(poles_dir / "water_big.fgb"), str(ws.dir("publish") / "detail"), "aa", "A",
                           ((1, 55.0, 24.0, 1000.0),), 50, 2_000, b"", tuple(default_edges()))
    out = detail.render(job)
    assert out["rendered"] == [1] and len(out["warnings"]) == 1 and "islet" in out["warnings"][0]
    with rasterio.open(ws.dir("publish") / "detail" / "aa" / "A-1.png") as ds:
        assert (ds.read(1) == NODATA).all()


def test_render_refuses_a_blank_window_whose_land_is_far_from_the_pole(tmp_path, cfg, log):
    """Land in the file but hundreds of metres from the pole is not an islet under the pole: the pole is over
    water, so the window is blank for a reason worth stopping on."""
    ws = _workspace(tmp_path, log)
    poles_dir = ws.dir("poles")
    g = detail.georef(LAT, LON, 50, 2_000)
    # On a pixel edge, and a tenth of a pixel wide, so no pixel centre can fall on it; 470 m off the pole.
    lon0, lat0 = g.west + g.dlon * 12, g.north - g.dlat * 15
    write_fgb(poles_dir / "land_idx.fgb", "land", [box(lon0 - 3e-5, lat0 - 1.5e-5, lon0 + 3e-5, lat0 + 1.5e-5)],
              {"id": [1]})
    job = detail.DetailJob(str(poles_dir / "roads"), str(poles_dir / "land_idx.fgb"),
                           str(poles_dir / "water_big.fgb"), str(ws.dir("publish") / "detail"), "aa", "A",
                           ((1, 55.0, 24.0, 1000.0),), 50, 2_000, b"", tuple(default_edges()))
    with pytest.raises(PolesError, match="nearest land"):
        detail.render(job)


def test_run_detail_names_the_job_in_flight_when_a_worker_dies(tmp_path, cfg, log, monkeypatch):
    """An OOM-killed worker must name the unit and scenario it was on and point at POLES_WORKERS, the same
    way the poles stage does; a bare BrokenProcessPool traceback tells the operator nothing."""
    monkeypatch.setenv("POLES_WORKERS", "3")
    ws = _workspace(tmp_path, log)
    monkeypatch.setattr(detail, "ProcessPoolExecutor", lambda max_workers: _DyingPool())
    with pytest.raises(PolesError, match="POLES_WORKERS") as exc:
        detail.run_detail(replace(cfg, detail_window_m=2_000), ws, _published(), ClassTable(), None, log)
    assert "aa" in str(exc.value) and " B" in str(exc.value) and "3" in str(exc.value)


def test_run_detail_accepts_a_scenario_with_nothing_published(tmp_path, cfg, log, monkeypatch):
    """A region may publish nothing in one scenario; a missing key is an empty job list, not a KeyError."""
    monkeypatch.setenv("POLES_WORKERS", "1")
    ws = _workspace(tmp_path, log)
    only_a = {"A": [{"unit": "aa", "poles": [{"rank": 1, "lat": 55.0, "lon": 24.0, "dist_m": 1000.0}],
                     "reason": None}]}
    stats = detail.run_detail(replace(cfg, detail_window_m=2_000), ws, only_a, ClassTable(), None, log)
    assert stats["count"] == 1 and (ws.dir("publish") / "detail" / "aa" / "A-1.png").exists()
    assert detail.run_detail(replace(cfg, detail_window_m=2_000), ws, {}, ClassTable(), None, log)["count"] == 0
