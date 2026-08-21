import numpy as np
import pytest
from pyproj import Transformer
from shapely.geometry import LineString

from poles.refine import RoadCache, UtmRoads, refine, utm_epsg
from poles.roads import RoadSet

COLUMNS = ("osm_id", "highway", "name", "ref")


def _roadset(lines_utm, epsg, ids=None):
    """Roads given in UTM metres, converted to the lon/lat RoadSet the pipeline carries."""
    to_ll = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    geoms = []
    for line in lines_utm:
        xs, ys = zip(*line)
        lons, lats = to_ll.transform(xs, ys)
        geoms.append(LineString(list(zip(lons, lats))))
    ids = ids or list(range(1, len(geoms) + 1))
    n = len(geoms)
    return RoadSet(np.array(geoms, dtype=object), {"osm_id": np.array(ids, dtype=object), "highway": np.array(["track"] * n, dtype=object),
                                                   "name": np.array([None] * n, dtype=object), "ref": np.array([None] * n, dtype=object)})


def test_utm_zone_selection_including_norway_exception_not_applied():
    assert utm_epsg(23.5, 54.4) == 32634          # zone 34N runs 18E to 24E
    assert utm_epsg(25.3, 54.7) == 32635          # just east of the 24E seam: zone 35N
    assert utm_epsg(-3.0, 40.0) == 32630          # Spain, zone 30N
    assert utm_epsg(5.0, 60.0) == 32631           # Bergen: plain zone 31, the Norway exception (zone 32) is not applied
    assert utm_epsg(151.2, -33.9) == 32756        # Sydney, southern hemisphere
    assert utm_epsg(-180.0, 10.0) == 32601 and utm_epsg(180.0, 10.0) == 32660


def test_single_straight_road_known_offset():
    epsg = 32635
    road = [(500_000 - 5000, 6_000_000), (500_000 + 5000, 6_000_000)]   # along y = 6,000,000 in zone 35N
    roads = UtmRoads(_roadset([road], epsg), epsg)
    # window centred 1000 m north of the road: the maximum is at the far (north) edge, 1250 m away
    pole = refine(500_000, 6_001_000, f"EPSG:{epsg}", roads, half_m=250.0, steps=(25.0, 5.0))
    assert pole.dist_m == pytest.approx(1250.0, abs=2.5)
    assert pole.utm_epsg == epsg and pole.way_id == 1
    assert pole.y == pytest.approx(6_001_250, abs=5) and 499_700 <= pole.x <= 500_300


def test_two_roads_midpoint():
    epsg = 32635
    a = [(490_000, 6_000_000), (510_000, 6_000_000)]
    b = [(490_000, 6_002_000), (510_000, 6_002_000)]
    roads = UtmRoads(_roadset([a, b], epsg), epsg)
    pole = refine(500_000, 6_000_900, f"EPSG:{epsg}", roads)
    assert pole.dist_m == pytest.approx(1000.0, abs=2.5) and pole.y == pytest.approx(6_001_000, abs=5)


def test_result_nearest_way_id_matches_closest_geometry():
    epsg = 32635
    a = [(499_000, 6_000_000), (501_000, 6_000_000)]
    b = [(499_000, 6_003_000), (501_000, 6_003_000)]
    roads = UtmRoads(_roadset([a, b], epsg, ids=[77, 88]), epsg)
    pole = refine(500_000, 6_002_600, f"EPSG:{epsg}", roads, half_m=100.0)
    assert pole.way_id == 88 and pole.way_index == 1


def test_allowed_mask_restricts_grid_and_none_when_empty():
    epsg = 32635
    road = [(495_000, 6_000_000), (505_000, 6_000_000)]
    roads = UtmRoads(_roadset([road], epsg), epsg)
    to_ll = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    lon_cut, _ = to_ll.transform(500_000, 6_001_000)
    west_only = lambda lons, lats: np.asarray(lons) < lon_cut
    pole = refine(500_000, 6_001_000, f"EPSG:{epsg}", roads, allowed=west_only)
    assert pole.x < 500_000
    assert refine(500_000, 6_001_000, f"EPSG:{epsg}", roads, allowed=lambda lons, lats: np.zeros(len(lons), bool)) is None


def test_empty_road_set_returns_none():
    roads = UtmRoads(RoadSet.empty(COLUMNS), 32635)
    assert refine(500_000, 6_001_000, "EPSG:32635", roads) is None


def test_src_crs_is_transformed_to_utm():
    epsg = 32635
    road = [(500_000 - 5000, 6_000_000), (500_000 + 5000, 6_000_000)]
    roads = UtmRoads(_roadset([road], epsg), epsg)
    to_laea = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:3035", always_xy=True)
    x, y = to_laea.transform(500_000, 6_001_000)
    pole = refine(x, y, "EPSG:3035", roads)
    assert pole.dist_m == pytest.approx(1250.0, abs=3.0)


class _FakeTiles:
    def __init__(self):
        self.calls = []
    def query(self, west, south, east, north, where=None):
        self.calls.append((west, south, east, north, where))
        return _roadset([[(500_000 - 5000, 6_000_000), (500_000 + 5000, 6_000_000)]], 32635)


def test_road_cache_reuses_covering_bbox():
    tiles = _FakeTiles()
    cache = RoadCache(tiles, where="highway IN ('track')", pad_deg=0.5)
    r1 = cache.get(23.0, 54.0, 23.1, 54.1, 32635)
    r2 = cache.get(23.02, 54.02, 23.08, 54.08, 32635)
    assert r1 is r2 and len(tiles.calls) == 1 and tiles.calls[0][4] == "highway IN ('track')"
    cache.get(30.0, 60.0, 30.1, 60.1, 32636)
    assert len(tiles.calls) == 2
