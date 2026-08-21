import numpy as np
import pytest
import rasterio
from shapely.geometry import MultiPolygon, box

from poles.grid import Frame, create_raster
from poles.poles import _allowed_factory, _unit_windows, top_n_dedup, validate_poles_json
from poles.units import Unit
from tests.helpers import write_fgb


def _p(lat, lon, d):
    return {"rank": 0, "lat": lat, "lon": lon, "dist_m": d, "nearest_way": {"id": 1, "highway": "track", "name": None, "ref": None, "country": "lt"},
            "nearest_place": None, "detail": None, "warnings": []}


def test_top_n_dedup_10km():
    poles = [_p(54.0, 24.0, 5000), _p(54.05, 24.0, 4900), _p(54.5, 24.0, 4800), _p(55.0, 24.0, 4700)]  # 2nd is 5.6 km from 1st
    kept = top_n_dedup(poles, top_n=3, dedup_m=10_000)
    assert [p["dist_m"] for p in kept] == [5000, 4800, 4700] and [p["rank"] for p in kept] == [1, 2, 3]


def test_stage_output_schema():
    good = [{"unit": "lt", "poles": [_p(54.0, 24.0, 5000) | {"rank": 1}], "reason": None}]
    validate_poles_json(good, top_n=1)
    short = [{"unit": "lt", "poles": [_p(54.0, 24.0, 5000) | {"rank": 1}], "reason": "only 1 pole(s)"}]
    validate_poles_json(short, top_n=10)                       # fewer than top_n is fine once it is explained
    with pytest.raises(ValueError, match="rank"):
        validate_poles_json([{"unit": "lt", "poles": [_p(54.0, 24.0, 5000) | {"rank": 2}], "reason": None}], top_n=1)
    with pytest.raises(ValueError, match="reason"):
        validate_poles_json([{"unit": "lt", "poles": [], "reason": None}], top_n=10)
    with pytest.raises(ValueError, match="dist_m"):
        validate_poles_json([{"unit": "lt", "poles": [_p(54.0, 24.0, -1) | {"rank": 1}], "reason": None}], top_n=1)


def test_unit_windows_are_the_tight_row_col_box_of_each_index(tmp_path):
    frame = Frame("EPSG:4326", 1.0, 0.0, 6.0, 6, 6)
    tif = create_raster(frame, tmp_path / "units.tif", dtype="int16")
    with rasterio.open(tif, "r+") as ds:
        a = np.zeros((6, 6), dtype="int16")
        a[1, 2] = a[3, 4] = 1
        a[5, 0] = 2
        ds.write(a, 1)
    assert _unit_windows(tif) == {1: (1, 2, 3, 3), 2: (5, 0, 1, 1)}


def test_allowed_needs_the_unit_and_land_and_no_big_water(tmp_path):
    unit = Unit("aa", "Aa", "Aa", 1, "aa", MultiPolygon([box(0, 0, 2, 2)]), False, 1)
    land = write_fgb(tmp_path / "land.fgb", "land", [box(-1, -1, 1.5, 3)], {"osm_id": [1]})
    water = write_fgb(tmp_path / "water.fgb", "water", [box(0.2, 0.2, 0.4, 0.4)], {"osm_id": [1]})
    allowed = _allowed_factory(unit, land, water)
    lons = np.array([1.0, 0.3, 1.8, 2.5])          # in the unit on land; in the lake; off the land polygon; outside the unit
    lats = np.array([1.0, 0.3, 1.0, 1.0])
    assert allowed(lons, lats).tolist() == [True, False, False, False]
