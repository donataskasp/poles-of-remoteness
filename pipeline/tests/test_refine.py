import numpy as np
import pytest
import shapely
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


def _brute_force(roadset, epsg, cx, cy, allowed=None, half=250.0, step=5.0):
    """The answer refine() must give, computed independently: plain shapely distance from every lattice
    point of the window to every road, no STRtree and nothing from poles.refine."""
    to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    to_ll = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    geoms = []
    for g in roadset.geoms:
        coords = np.asarray(g.coords)
        xs, ys = to_utm.transform(coords[:, 0], coords[:, 1])
        geoms.append(LineString(list(zip(xs, ys))))
    offsets = np.arange(-half, half + step / 2, step)
    gx, gy = np.meshgrid(cx + offsets, cy + offsets)
    px, py = gx.ravel(), gy.ravel()
    if allowed is not None:
        lons, lats = to_ll.transform(px, py)
        keep = np.asarray(allowed(np.asarray(lons), np.asarray(lats)), dtype=bool)
        px, py = px[keep], py[keep]
    pts = shapely.points(px, py)
    d = np.min(np.stack([shapely.distance(pts, g) for g in geoms]), axis=0)
    k = int(np.argmax(d))
    return float(d[k]), float(px[k]), float(py[k])


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
    pole = refine(500_000, 6_001_000, f"EPSG:{epsg}", roads, half_m=250.0, step=5.0)
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


@pytest.mark.parametrize("seed", range(6))
def test_matches_a_brute_force_five_metre_sweep(seed):
    """The published number is the maximum of a 5 m sweep of the window (spec 2.4), masked or not."""
    epsg, cx, cy = 32635, 500_000.0, 6_001_000.0
    rng = np.random.default_rng(seed)
    lines = []
    for _ in range(int(rng.integers(2, 8))):
        x0, y0 = cx + rng.uniform(-1200, 1200), cy + rng.uniform(-1200, 1200)
        lines.append([(x0 + rng.uniform(-600, 600), y0 + rng.uniform(-600, 600)) for _ in range(3)])
    roadset = _roadset(lines, epsg)
    roads = UtmRoads(roadset, epsg)
    to_ll = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    _, lat_cut = to_ll.transform(cx, cy)
    south_half = lambda lons, lats: np.asarray(lats) < lat_cut

    pole = refine(cx, cy, f"EPSG:{epsg}", roads)
    assert pole.dist_m == pytest.approx(_brute_force(roadset, epsg, cx, cy)[0], abs=1e-6)

    masked = refine(cx, cy, f"EPSG:{epsg}", roads, allowed=south_half)
    assert masked.dist_m == pytest.approx(_brute_force(roadset, epsg, cx, cy, south_half)[0], abs=1e-6)
    assert masked.lat < lat_cut and masked.dist_m <= pole.dist_m


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
    # x and y come back in the UTM zone, not in the frame the caller asked in: the same point is about
    # (5.29 M, 3.53 M) in EPSG:3035, so these bounds fail loudly if the frame coordinates leak through.
    assert pole.utm_epsg == epsg
    assert 499_700 <= pole.x <= 500_300 and pole.y == pytest.approx(6_001_250, abs=5)
    assert abs(pole.x - x) > 1000 and abs(pole.y - y) > 1000


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
    cache.get(25.0, 54.0, 25.1, 54.1, 32635)          # same zone, bbox outside the cached one: a fresh query
    assert len(tiles.calls) == 2
    cache.get(25.02, 54.02, 25.08, 54.08, 32636)      # inside the cached bbox but another zone: a fresh query
    assert len(tiles.calls) == 3
