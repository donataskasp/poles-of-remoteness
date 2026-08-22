import numpy as np
import pytest
import rasterio
from pyproj import Geod, Transformer
from shapely.geometry import LineString, MultiPolygon, box

from poles.config import RegionConfig, load_region
from poles.grid import Frame, create_raster
from poles.roads import RoadSet
from poles.units import Unit, low_tif
from poles.validate.checks import (CheckResult, ChecksError, _coord_batches, _geodesic_min, edge_bound,
                                   grid_shift_compare, holes, invariants, load_refs, membership, recheck,
                                   references)
from tests.helpers import write_fgb

GEOD = Geod(ellps="WGS84")


def _pole(lat, lon, d, rank=1, way=1):
    return {"rank": rank, "lat": lat, "lon": lon, "dist_m": d,
            "nearest_way": {"id": way, "highway": "track", "name": None, "ref": None, "country": "lt"},
            "nearest_place": None, "detail": None, "warnings": []}


class _Tiles:
    def __init__(self, lines, highway="track"):
        self.lines, self.highway = lines, highway

    def query(self, west, south, east, north, where=None):
        n = len(self.lines)
        return RoadSet(np.array(self.lines, dtype=object),
                       {"osm_id": np.arange(1, n + 1).astype(object),
                        "highway": np.array([self.highway] * n, dtype=object),
                        "name": np.array([None] * n, dtype=object), "ref": np.array([None] * n, dtype=object)})


# ---------- check 1: independent geodesic recheck ----------

def test_recheck_agrees_within_tolerance_on_synthetic():
    road = LineString([(23.5, 54.40), (23.6, 54.40)])          # along a parallel; the pole sits 2 km north of it
    lat = 54.40 + 2000 / 111_320 * 1.0
    true = GEOD.inv(23.55, lat, 23.55, 54.40)[2]
    results = recheck({"A": [{"unit": "lt", "poles": [_pole(lat, 23.55, true)], "reason": None}]}, _Tiles([road]))
    assert len(results) == 1 and results[0].passed and results[0].blocking and results[0].check == "recheck"
    assert results[0].details["geodesic_m"] == pytest.approx(true, abs=1.0)


def test_recheck_catches_planted_error():
    road = LineString([(23.5, 54.40), (23.6, 54.40)])
    lat = 54.40 + 2000 / 111_320
    true = GEOD.inv(23.55, lat, 23.55, 54.40)[2]
    results = recheck({"A": [{"unit": "lt", "poles": [_pole(lat, 23.55, true * 1.02)], "reason": None}]}, _Tiles([road]))
    assert not results[0].passed


def test_recheck_ignores_ways_outside_the_scenario():
    footway = LineString([(23.5, 54.41), (23.6, 54.41)])      # closer, but not drivable
    road = LineString([(23.5, 54.40), (23.6, 54.40)])
    lat = 54.40 + 2000 / 111_320
    true = GEOD.inv(23.55, lat, 23.55, 54.40)[2]

    class Mixed(_Tiles):
        def query(self, *a, **k):
            rs = super().query(*a, **k)
            rs.attrs["highway"] = np.array(["footway", "track"], dtype=object)
            return rs

    results = recheck({"A": [{"unit": "lt", "poles": [_pole(lat, 23.55, true)], "reason": None}]}, Mixed([footway, road]))
    assert results[0].passed


def test_recheck_fails_when_no_way_of_the_scenario_is_in_range():
    """A pole on a road-free island, or one whose coarse value saturated, has nothing to measure against."""
    results = recheck({"A": [{"unit": "lt", "poles": [_pole(54.4, 23.5, 20_000)], "reason": None}]}, _Tiles([]))
    assert not results[0].passed
    assert results[0].details["geodesic_m"] is None and results[0].details["ways"] == 0


def test_geodesic_min_splits_a_batch_over_the_vertex_budget():
    """The budget bounds the coordinate array handed to one Geod.inv call, even for a single way whose own
    densified length exceeds it."""
    geoms = np.array([LineString([(20.0, 55.0), (21.0, 55.0)]),
                      LineString([(20.0, 54.0), (21.0, 54.0)])], dtype=object)
    whole, n_whole = _geodesic_min(20.5, 55.0, geoms, 100.0, budget=10_000_000)
    split, n_split = _geodesic_min(20.5, 55.0, geoms, 100.0, budget=500)
    assert split == pytest.approx(whole) and n_split == n_whole
    batches = list(_coord_batches(geoms, 100.0, 500))
    assert len(batches) > 1 and all(len(b) <= 500 for b in batches)
    assert sum(len(b) for b in batches) == n_whole


# ---------- check 2: membership ----------

def test_membership_needs_the_unit_and_land_and_no_big_water(tmp_path):
    unit = Unit("aa", "Aa", "Aa", 1, "aa", MultiPolygon([box(0, 0, 2, 2)]), False, 1)
    land = write_fgb(tmp_path / "land.fgb", "land", [box(-1, -1, 1.5, 3)], {"osm_id": [1]})
    water = write_fgb(tmp_path / "water.fgb", "water", [box(0.2, 0.2, 0.4, 0.4)], {"osm_id": [1]})
    poles = {"A": [{"unit": "aa", "poles": [_pole(1.0, 1.0, 100, rank=1),      # in the unit, on land, dry
                                            _pole(0.3, 0.3, 100, rank=2),      # in the lake
                                            _pole(1.0, 1.8, 100, rank=3),      # off the land polygon
                                            _pole(1.0, 2.5, 100, rank=4)],     # outside the unit
                    "reason": None}]}
    results = membership(poles, [unit], land, water)
    assert [r.passed for r in results] == [True, False, False, False]
    assert all(r.blocking and r.check == "membership" for r in results)
    assert results[1].details == {"rank": 2, "in_unit": True, "on_land": True, "in_water": True}
    assert results[2].details["on_land"] is False and results[3].details["in_unit"] is False


def test_membership_takes_the_unit_boundary_within_the_publication_rounding(tmp_path):
    """Published coordinates are rounded to 6 decimals, so a pole the search put on the boundary of its
    unit can be published a hair outside it. Inside means inside to within that rounding; a pole two
    metres out is still a failure."""
    unit = Unit("aa", "Aa", "Aa", 1, "aa", MultiPolygon([box(0, 0, 2, 2)]), False, 1)
    land = write_fgb(tmp_path / "land.fgb", "land", [box(-1, -1, 3, 3)], {"osm_id": [1]})
    water = write_fgb(tmp_path / "water.fgb", "water", [box(9, 9, 9.1, 9.1)], {"osm_id": [1]})
    poles = {"A": [{"unit": "aa", "poles": [_pole(2.0, 1.0, 100, rank=1),         # exactly on the boundary
                                            _pole(2.00002, 1.0, 100, rank=2)],    # about 2 m outside it
                    "reason": None}]}
    results = membership(poles, [unit], land, water)
    assert [r.passed for r in results] == [True, False]
    assert results[0].details == {"rank": 1, "in_unit": True, "on_land": True, "in_water": False}
    assert results[1].details["in_unit"] is False


def test_membership_takes_a_shoreline_pole_the_rounding_moved_off_the_land(tmp_path):
    """The real case this exists for: a coastal pole whose 6-decimal coordinates land a few centimetres
    off the land polygon it was refined on. Centimetres are rounding; metres are a pole in the sea."""
    unit = Unit("aa", "Aa", "Aa", 1, "aa", MultiPolygon([box(0, 0, 2, 2)]), False, 1)
    land = write_fgb(tmp_path / "land.fgb", "land", [box(0, 0, 1.0, 2)], {"osm_id": [1]})
    water = write_fgb(tmp_path / "water.fgb", "water", [box(9, 9, 9.1, 9.1)], {"osm_id": [1]})
    poles = {"A": [{"unit": "aa", "poles": [_pole(1.0, 1.0000004, 100, rank=1),   # 4 cm past the shore
                                            _pole(1.0, 1.00002, 100, rank=2)],    # about 2 m past it
                    "reason": None}]}
    results = membership(poles, [unit], land, water)
    assert [r.passed for r in results] == [True, False]
    assert results[0].details["on_land"] is True and results[1].details["on_land"] is False


# ---------- check 3: data-edge bound ----------

def test_edge_bound_fails_when_edge_closer_than_distance():
    edge = box(20.0, 50.0, 30.0, 60.0)
    near_edge = _pole(55.0, 29.9, 20_000)                      # about 6.4 km from lon 30
    inside = _pole(55.0, 25.0, 20_000)
    results = edge_bound({"A": [{"unit": "lt", "poles": [near_edge, inside], "reason": None}]}, edge)
    assert [r.passed for r in results] == [False, True] and all(r.blocking for r in results)
    assert results[0].details["edge_m"] == pytest.approx(6400, rel=0.05)


# ---------- check 4: grid-shift sensitivity ----------

def test_grid_shift_compare_judges_the_distance_with_a_metre_floor():
    orig = _pole(54.0, 24.0, 5000)
    ok = grid_shift_compare("lt", "A", orig, _pole(54.001, 24.0, 5030))       # 111 m, 30 m of 5 km
    changed = grid_shift_compare("lt", "A", orig, _pole(54.0, 24.0, 5100))    # 100 m, 2 %
    tiny = _pole(41.9, 12.45, 126.0)
    floor = grid_shift_compare("va", "A", tiny, _pole(41.9, 12.45, 127.4))    # 1.1 %, under the 10 m floor
    assert ok.passed and ok.blocking
    assert not changed.passed and changed.blocking and "tie" not in changed.details
    assert floor.passed


def test_grid_shift_compare_calls_a_far_move_at_the_same_distance_a_tie():
    orig = _pole(54.0, 24.0, 5000)
    tie = grid_shift_compare("lt", "A", orig, _pole(54.006, 24.0, 5002))      # 667 m, 2 m
    far = grid_shift_compare("lt", "A", orig, _pole(54.006, 24.0, 5200))      # 667 m, 4 %
    lost = grid_shift_compare("lt", "A", orig, None)
    assert not tie.passed and not tie.blocking and tie.details["tie"] is True
    assert not far.passed and far.blocking
    assert not lost.passed and lost.blocking


# ---------- check 5: hole detection ----------

def _frame_and_rasters(tmp_path, doughnut: bool):
    frame = Frame("EPSG:3035", 250.0, 5_000_000.0, 3_600_000.0, 400, 400)  # 100 km square
    rng = np.random.default_rng(0)
    roads = (rng.uniform(size=(400, 400)) < 0.02).astype("uint8")
    if doughnut:
        rr, cc = np.mgrid[0:400, 0:400]
        d = np.hypot(rr - 200, cc - 200) * 250.0
        roads[d <= 10_000] = 0
        roads[(d > 10_000) & (d <= 30_000)] = (rng.uniform(size=roads.shape) < 0.1)[(d > 10_000) & (d <= 30_000)]
    road_tif = tmp_path / "roads_A.tif"
    create_raster(frame, road_tif)
    with rasterio.open(road_tif, "r+") as ds:
        ds.write(roads, 1)
    units_tif = tmp_path / "units.tif"
    for path in (units_tif, low_tif(units_tif)):     # an uncontested unit holds the same cells in both
        create_raster(frame, path, dtype="int16")
        with rasterio.open(path, "r+") as ds:
            ds.write(np.ones((400, 400), dtype="int16"), 1)
    return frame, road_tif, units_tif


def _centre_unit_and_poles(dist_m=12_000):
    from pyproj import Transformer
    to_ll = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    lon, lat = to_ll.transform(5_000_000 + 200 * 250, 3_600_000 - 200 * 250)
    unit = Unit("uu", "U", "U", 1, "uu", MultiPolygon([box(lon - 1, lat - 1, lon + 1, lat + 1)]), False, 1)
    return unit, {"A": [{"unit": "uu", "poles": [_pole(lat, lon, dist_m)], "reason": None}]}


def test_hole_detector_flags_doughnut_and_passes_uniform(tmp_path):
    unit, poles = _centre_unit_and_poles()
    frame, road_tif, units_tif = _frame_and_rasters(tmp_path, doughnut=False)
    uniform = holes(poles, {"A": road_tif}, units_tif, frame, [unit])
    frame, road_tif, units_tif = _frame_and_rasters(tmp_path, doughnut=True)
    flagged = holes(poles, {"A": road_tif}, units_tif, frame, [unit])
    assert uniform[0].passed and not flagged[0].passed and not flagged[0].blocking
    assert flagged[0].details["inner_density"] == 0 and flagged[0].details["outer_density"] > flagged[0].details["unit_median_outer"]


def test_holes_samples_the_cells_a_bigger_unit_won_in_the_top_raster(tmp_path):
    """A small unit can lose every cell of the top raster to a neighbour that touches all of them; its cells
    are in the companion low raster, and without those the median is 0 and any empty inner ring is a hole."""
    unit, poles = _centre_unit_and_poles()
    frame, road_tif, units_tif = _frame_and_rasters(tmp_path, doughnut=False)
    with rasterio.open(units_tif, "r+") as ds:
        ds.write(np.full((400, 400), 2, dtype="int16"), 1)
    create_raster(frame, low_tif(units_tif), dtype="int16")
    alone = holes(poles, {"A": road_tif}, units_tif, frame, [unit])
    with rasterio.open(low_tif(units_tif), "r+") as ds:
        ds.write(np.ones((400, 400), dtype="int16"), 1)
    with_low = holes(poles, {"A": road_tif}, units_tif, frame, [unit])
    assert alone[0].details["unit_median_outer"] == 0.0
    assert with_low[0].details["unit_median_outer"] > 0.0


def test_holes_rejects_a_missing_low_raster(tmp_path):
    """Half the cells of every shared unit live in the companion raster; sampling without it would quietly
    halve the sample and skew the medians, so the missing file is an error, not a fallback."""
    unit, poles = _centre_unit_and_poles()
    frame, road_tif, units_tif = _frame_and_rasters(tmp_path, doughnut=False)
    low_tif(units_tif).unlink()
    with pytest.raises(ChecksError, match="units_low.tif"):
        holes(poles, {"A": road_tif}, units_tif, frame, [unit])


def test_holes_rejects_a_unit_it_was_not_given(tmp_path):
    unit, poles = _centre_unit_and_poles()
    frame, road_tif, units_tif = _frame_and_rasters(tmp_path, doughnut=False)
    stranger = {"A": [{"unit": "zz", "poles": poles["A"][0]["poles"], "reason": None}]}
    with pytest.raises(ChecksError, match="zz"):
        holes(stranger, {"A": road_tif}, units_tif, frame, [unit])


def test_holes_rejects_a_pole_outside_the_frame(tmp_path):
    """Off the raster the window comes back empty, which would read as an empty inner ring and flag a hole
    that is really a bad coordinate."""
    unit, _ = _centre_unit_and_poles()
    frame, road_tif, units_tif = _frame_and_rasters(tmp_path, doughnut=False)
    far = {"A": [{"unit": "uu", "poles": [_pole(0.0, 0.0, 12_000)], "reason": None}]}
    with pytest.raises(ChecksError, match="outside"):
        holes(far, {"A": road_tif}, units_tif, frame, [unit])


# ---------- check 6: reference values ----------

def test_references_block_only_when_marked():
    refs = {"lt": {"A": {"lat": 54.441473, "lon": 23.537020, "dist_m": 3425.6, "source": "demo", "blocking": True}},
            "external": [{"unit": "lt", "scenario": "A", "name": "Some article", "lat": 54.44, "lon": 23.54,
                          "dist_m": 3000, "source": "https://example.org", "note": "counts paths too"}]}
    good = {"A": [{"unit": "lt", "poles": [_pole(54.4416, 23.5372, 3430.0)], "reason": None}]}
    results = references(good, refs)
    assert [(r.passed, r.blocking) for r in results] == [(True, True), (True, False)]
    bad = {"A": [{"unit": "lt", "poles": [_pole(54.50, 23.5372, 3430.0)], "reason": None}]}   # 6.5 km away
    assert [r.passed for r in references(bad, refs)][0] is False


def test_references_report_a_unit_with_no_pole():
    refs = {"lt": {"A": {"lat": 54.441473, "lon": 23.537020, "dist_m": 3425.6, "source": "demo", "blocking": True}},
            "external": [{"unit": "lt", "scenario": "A", "name": "Some article", "lat": 54.44, "lon": 23.54,
                          "dist_m": 3000, "source": "https://example.org"}]}
    results = references({"A": [{"unit": "lt", "poles": [], "reason": "no pole"}]}, refs)
    assert [(r.passed, r.blocking) for r in results] == [(False, True), (False, False)]
    assert all(r.details["reason"] == "no pole" for r in results)


def test_shipped_refs_hold_the_published_lithuania_poles(regions_dir):
    from poles.config import load_region

    refs = load_refs(load_region(regions_dir / "europe.yaml").references)
    assert refs["lt"]["A"]["dist_m"] == 3425.6 and refs["lt"]["A"]["blocking"] is True
    assert (refs["lt"]["A"]["lat"], refs["lt"]["A"]["lon"]) == (54.441473, 23.537020)
    assert refs["lt"]["B"]["dist_m"] == 6674.6 and refs["lt"]["B"]["blocking"] is True
    assert (refs["lt"]["B"]["lat"], refs["lt"]["B"]["lon"]) == (53.995818, 24.462993)
    assert 3 <= len(refs["external"]) <= 5
    for entry in refs["external"]:
        assert set(entry) >= {"unit", "scenario", "name", "lat", "lon", "dist_m", "source", "note", "checked"}
        assert entry["scenario"] in ("A", "B") and entry["source"].startswith("https://")
        # An unquoted `no` is False in YAML 1.1, which would silently miss Norway's poles.
        assert isinstance(entry["unit"], str) and isinstance(entry["name"], str)


# ---------- check 7: invariants ----------

def _cfg(regions_dir, **over) -> RegionConfig:
    return RegionConfig(**(load_region(regions_dir / "europe.yaml").__dict__ | over))


def test_a_le_b_invariant_detects_violation(regions_dir):
    cfg = _cfg(regions_dir, expected_units=1, top_n=1)
    unit = Unit("lt", "LT", "Lithuania", 1, "lt", MultiPolygon([box(20, 53, 27, 57)]), False, 1)
    poles = {"A": [{"unit": "lt", "poles": [_pole(54.0, 24.0, 5000)], "reason": None}],
             "B": [{"unit": "lt", "poles": [_pole(54.2, 24.0, 4000)], "reason": None}]}
    results = {r.details.get("name"): r for r in invariants(poles, [unit], cfg, {"a_le_b_violations": 0})}
    assert not results["a_le_b_poles"].passed and results["a_le_b_grid"].passed and results["unit_count"].passed
    assert results["top_n_or_reason"].passed and results["separation"].passed and all(r.blocking for r in results.values())


def test_invariants_accept_a_microstate_with_one_pole_and_a_reason(regions_dir):
    """A unit too small to hold ten poles 10 km apart is fine as long as it says so."""
    cfg = _cfg(regions_dir, expected_units=1, top_n=10)
    unit = Unit("mc", "MC", "Monaco", 1, "mc", MultiPolygon([box(7.4, 43.7, 7.5, 43.8)]), False, 1)
    entry = {"unit": "mc", "poles": [_pole(43.75, 7.42, 900)], "reason": "only 1 pole(s)"}
    ok = {r.details["name"]: r for r in invariants({"A": [entry], "B": [entry]}, [unit], cfg, {"a_le_b_violations": 0})}
    assert ok["top_n_or_reason"].passed and ok["structure"].passed and ok["separation"].passed
    silent = {"unit": "mc", "poles": [_pole(43.75, 7.42, 900)], "reason": None}
    bad = [r for r in invariants({"A": [silent], "B": [silent]}, [unit], cfg, {"a_le_b_violations": 0})
           if r.details["name"] in ("top_n_or_reason", "structure")]
    assert not any(r.passed for r in bad)


def test_invariants_flag_poles_closer_than_the_dedup_distance(regions_dir):
    cfg = _cfg(regions_dir, expected_units=1, top_n=2)
    unit = Unit("lt", "LT", "Lithuania", 1, "lt", MultiPolygon([box(20, 53, 27, 57)]), False, 1)
    close = {"unit": "lt", "poles": [_pole(54.0, 24.0, 5000, rank=1), _pole(54.03, 24.0, 4900, rank=2)], "reason": None}
    results = [r for r in invariants({"A": [close], "B": [close]}, [unit], cfg, {"a_le_b_violations": 0})
               if r.details["name"] == "separation"]
    assert not any(r.passed for r in results)
    assert results[0].details["min_m"] == pytest.approx(3336, rel=0.02)


def test_invariants_flag_a_grid_violation_a_missing_unit_and_a_wrong_unit_count(regions_dir):
    cfg = _cfg(regions_dir, expected_units=2, top_n=1)
    unit = Unit("lt", "LT", "Lithuania", 1, "lt", MultiPolygon([box(20, 53, 27, 57)]), False, 1)
    results = {(r.details.get("name"), r.scenario): r
               for r in invariants({"A": [], "B": []}, [unit], cfg, {"a_le_b_violations": 17})}
    assert not results[("a_le_b_grid", "*")].passed and results[("a_le_b_grid", "*")].details["violations"] == 17
    assert not results[("unit_count", "*")].passed and results[("unit_count", "*")].details == {"name": "unit_count", "expected": 2, "found": 1}
    assert not results[("top_n_or_reason", "A")].passed and results[("top_n_or_reason", "A")].details["count"] == 0
    assert results[("a_le_b_poles", "*")].passed        # nothing published for either scenario, so nothing to compare


# ---------- shared shape ----------

def test_results_mark_blocking_correctly():
    r = CheckResult("holes", "lt", "A", False, False, {})
    assert r.to_dict() == {"check": "holes", "unit": "lt", "scenario": "A", "passed": False, "blocking": False, "details": {}}


def test_every_pole_check_is_empty_for_a_unit_with_no_poles(tmp_path):
    unit, _ = _centre_unit_and_poles()
    empty = {"A": [{"unit": "uu", "poles": [], "reason": "no pole"}]}
    land = write_fgb(tmp_path / "land.fgb", "land", [box(-1, -1, 1, 1)], {"osm_id": [1]})
    water = write_fgb(tmp_path / "water.fgb", "water", [box(0.2, 0.2, 0.4, 0.4)], {"osm_id": [1]})
    frame, road_tif, units_tif = _frame_and_rasters(tmp_path, doughnut=False)
    assert recheck(empty, _Tiles([])) == []
    assert membership(empty, [unit], land, water) == []
    assert edge_bound(empty, box(-10, -10, 10, 10)) == []
    assert holes(empty, {"A": road_tif}, units_tif, frame, [unit]) == []


def test_holes_reads_windows_and_never_a_whole_raster(tmp_path, monkeypatch):
    """At the Europe frame the unit raster is 675 M cells (1.35 GB) and each road mask is another 675 M.
    The detector has to reach them through windows, so no read here may exceed one 512 x 512 block."""
    frame = Frame("EPSG:3035", 250.0, 5_000_000.0, 3_600_000.0, 2000, 2000)   # 500 km square, 4 M cells
    rng = np.random.default_rng(0)
    road_tif, units_tif = tmp_path / "roads_A.tif", tmp_path / "units.tif"
    create_raster(frame, road_tif)
    with rasterio.open(road_tif, "r+") as ds:
        ds.write((rng.uniform(size=(2000, 2000)) < 0.02).astype("uint8"), 1)
    for path in (units_tif, low_tif(units_tif)):
        create_raster(frame, path, dtype="int16")
        with rasterio.open(path, "r+") as ds:
            ds.write(np.ones((2000, 2000), dtype="int16"), 1)
    to_ll = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    lon, lat = to_ll.transform(5_000_000 + 1900 * 250, 3_600_000 - 1900 * 250)   # far from the raster origin
    unit = Unit("uu", "U", "U", 1, "uu", MultiPolygon([box(lon - 5, lat - 5, lon + 5, lat + 5)]), False, 1)
    poles = {"A": [{"unit": "uu", "poles": [_pole(lat, lon, 12_000)], "reason": None}]}

    reads: list[tuple] = []
    real_open = rasterio.open

    class Spy:
        def __init__(self, ds):
            self._ds = ds

        def __enter__(self):
            self._ds.__enter__()
            return self

        def __exit__(self, *exc):
            return self._ds.__exit__(*exc)

        def __getattr__(self, name):
            return getattr(self._ds, name)

        def read(self, *args, **kwargs):
            data = self._ds.read(*args, **kwargs)
            reads.append((kwargs.get("window"), data.size))
            return data

    monkeypatch.setattr(rasterio, "open", lambda *a, **k: Spy(real_open(*a, **k)))
    results = holes(poles, {"A": road_tif}, units_tif, frame, [unit])
    assert len(results) == 1 and results[0].passed
    assert reads and all(window is not None for window, _ in reads)
    assert max(size for _, size in reads) <= 512 * 512
