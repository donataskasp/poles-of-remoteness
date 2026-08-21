import numpy as np
import pytest
from shapely.geometry import LineString, MultiPolygon, Point, box

from poles.attrib import Countries, Places, nearest_way, pole_record
from poles.boundaries import AdminArea
from poles.refine import RefinedPole, UtmRoads
from poles.roads import RoadSet
from tests.helpers import write_fgb


def test_places_nearest_is_geodesic_and_prefers_english_name(tmp_path):
    pts = [Point(23.50, 54.38), Point(23.60, 54.50), Point(24.0, 54.0)]
    fgb = write_fgb(tmp_path / "places.fgb", "places", pts, {
        "osm_id": [1, 2, 3], "name": ["Kaimas", "Miestelis", "Toli"], "name:en": [None, "Townlet", None],
        "place": ["village", "town", "city"], "population": [None, "1200", None]})
    places = Places(fgb, layer="places")
    near = places.nearest(23.55, 54.45)
    assert near["name"] == "Townlet" and near["type"] == "town"
    assert near["dist_m"] == pytest.approx(6430, rel=0.02) and (near["lat"], near["lon"]) == (54.5, 23.6)


def test_nearest_way_country_uses_all_countries_not_only_units():
    lt = AdminArea(1, 2, "LT", "Lietuva", "Lithuania", MultiPolygon([box(20, 53, 26.9, 56.5)]), True, False)
    ru = AdminArea(2, 2, "RU", "Россия", "Russia", MultiPolygon([box(26.9, 53, 40, 60)]), False, True)
    countries = Countries([lt, ru])
    assert countries.code_at(25.0, 54.5) == "lt" and countries.code_at(30.0, 55.0) == "ru" and countries.code_at(0, 0) is None
    road = LineString([(27.0, 54.0), (27.0, 55.0)])         # just inside RU
    rs = RoadSet(np.array([road], dtype=object), {"osm_id": np.array([9], dtype=object), "highway": np.array(["track"], dtype=object),
                                                  "name": np.array([None], dtype=object), "ref": np.array(["A-1"], dtype=object)})
    roads = UtmRoads(rs, 32635)
    pole = RefinedPole(54.5, 26.8, 13_000.0, 9, 0.0, 0.0, 32635, 0)
    way = nearest_way(roads, pole, countries)
    assert way == {"id": 9, "highway": "track", "name": None, "ref": "A-1", "country": "ru"}


def test_pole_record_shape():
    pole = RefinedPole(54.4414731, 23.5370201, 3425.567, 1385319417, 0, 0, 32635, 0)
    rec = pole_record(1, pole, {"id": 1385319417, "highway": "track", "name": None, "ref": None, "country": "lt"},
                      {"name": "Kumečiai", "type": "village", "dist_m": 3700.0, "lat": 54.47, "lon": 23.53})
    assert rec == {"rank": 1, "lat": 54.441473, "lon": 23.53702, "dist_m": 3425.57,
                   "nearest_way": {"id": 1385319417, "highway": "track", "name": None, "ref": None, "country": "lt"},
                   "nearest_place": {"name": "Kumečiai", "type": "village", "dist_m": 3700.0, "lat": 54.47, "lon": 23.53},
                   "detail": None, "warnings": []}


def test_places_nearest_reports_missing_name_and_place_as_null_never_as_the_string_none(tmp_path):
    fgb = write_fgb(tmp_path / "places.fgb", "places", [Point(23.50, 54.38)],
                    {"osm_id": [1], "name": [None], "name:en": [None], "place": [None], "population": [None]})
    near = Places(fgb, layer="places").nearest(23.50, 54.38)
    assert near["name"] is None and near["type"] is None
