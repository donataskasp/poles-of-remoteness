import numpy as np
import pytest
from shapely.geometry import MultiPolygon, Point, Polygon, box

from poles.antimeridian import (lon_delta, lon_intervals, split_antimeridian, split_bbox, unwrap_ring,
                                wrapped_bounds)

# A unit drawn the way OSM stores one that sits on the line: the ring's longitudes step from 178 east
# to 178 west, which is 4 degrees of ground and 356 degrees of arithmetic.
CROSSER = Polygon([(178.0, 50.0), (-178.0, 50.0), (-178.0, 55.0), (178.0, 55.0), (178.0, 50.0)])


def test_unwrap_ring_makes_a_crossing_ring_continuous():
    assert unwrap_ring([(179.0, 0.0), (-179.0, 1.0), (179.0, 2.0)]) == [(179.0, 0.0), (181.0, 1.0), (179.0, 2.0)]
    # A ring that steps west across the line lands in the same window as one that steps east, so a
    # shell and a hole of the same relation are always written in comparable coordinates.
    assert unwrap_ring([(-179.0, 0.0), (179.0, 1.0), (-179.0, 2.0)]) == [(181.0, 0.0), (179.0, 1.0), (181.0, 2.0)]
    # A ring that stays put comes back coordinate for coordinate.
    ring = [(10.0, 0.0), (11.0, 0.0), (11.0, 1.0), (10.0, 0.0)]
    assert unwrap_ring(ring) == ring


def test_split_antimeridian_cuts_a_crossing_polygon_in_two():
    out = split_antimeridian(CROSSER)
    assert out.geom_type == "MultiPolygon" and len(out.geoms) == 2
    assert sorted(round(p.bounds[0], 6) for p in out.geoms) == [-180.0, 178.0]
    assert sorted(round(p.bounds[2], 6) for p in out.geoms) == [-178.0, 180.0]
    assert out.area == pytest.approx(4.0 * 5.0)          # 4 degrees of longitude, 5 of latitude
    assert out.contains(Point(179.5, 52.5)) and out.contains(Point(-179.5, 52.5))
    assert not out.contains(Point(0.0, 52.5))


def test_split_antimeridian_keeps_a_hole_and_leaves_an_ordinary_polygon_alone():
    holed = Polygon([(178.0, 50.0), (-178.0, 50.0), (-178.0, 55.0), (178.0, 55.0)],
                    [[(179.0, 51.0), (-179.5, 51.0), (-179.5, 51.5), (179.0, 51.5)]])
    out = split_antimeridian(holed)
    assert out.area == pytest.approx(20.0 - 1.5 * 0.5)
    assert not out.contains(Point(179.5, 51.25)) and not out.contains(Point(-179.9, 51.25))
    plain = box(20.0, 53.0, 26.5, 56.5)
    same = split_antimeridian(plain)
    assert same.geom_type == "MultiPolygon" and len(same.geoms) == 1 and same.geoms[0].equals(plain)


def test_lon_intervals_merges_and_sorts_the_parts():
    geom = MultiPolygon([box(-180.0, 50.0, -178.0, 55.0), box(178.0, 50.0, 180.0, 55.0),
                         box(-179.0, 40.0, -175.0, 45.0)])
    assert lon_intervals(geom) == [(-180.0, -175.0), (178.0, 180.0)]
    assert lon_intervals(box(20.0, 53.0, 26.5, 56.5)) == [(20.0, 26.5)]


def test_wrapped_bounds_takes_the_short_way_only_when_the_parts_touch_both_edges():
    crossing = split_antimeridian(CROSSER)
    assert crossing.bounds == (-180.0, 50.0, 180.0, 55.0)          # the plain bounds are half the planet
    assert wrapped_bounds(crossing) == (178.0, 50.0, 182.0, 55.0)  # the short way round
    apart = MultiPolygon([box(-170.0, 50.0, -160.0, 55.0), box(160.0, 50.0, 170.0, 55.0)])
    assert wrapped_bounds(apart) == apart.bounds                    # neither part reaches the line
    plain = box(20.0, 53.0, 26.5, 56.5)
    assert wrapped_bounds(plain) == (20.0, 53.0, 26.5, 56.5)
    with pytest.raises(ValueError, match="empty"):
        wrapped_bounds(MultiPolygon())


def test_split_bbox_returns_one_or_two_ordinary_boxes():
    assert split_bbox(178.0, 50.0, 182.0, 55.0) == [(178.0, 50.0, 180.0, 55.0), (-180.0, 50.0, -178.0, 55.0)]
    assert split_bbox(-182.0, 50.0, -178.0, 55.0) == [(178.0, 50.0, 180.0, 55.0), (-180.0, 50.0, -178.0, 55.0)]
    assert split_bbox(20.0, 53.0, 26.5, 56.5) == [(20.0, 53.0, 26.5, 56.5)]
    assert split_bbox(-400.0, -10.0, 400.0, 10.0) == [(-180.0, -10.0, 180.0, 10.0)]
    with pytest.raises(ValueError, match="never inverted"):
        split_bbox(170.0, 50.0, -170.0, 55.0)


def test_lon_delta_wraps_and_works_elementwise():
    assert lon_delta(179.9, -179.9) == pytest.approx(-0.2)
    assert lon_delta(-179.9, 179.9) == pytest.approx(0.2)
    assert lon_delta(10.0, 4.0) == pytest.approx(6.0)
    assert lon_delta(0.0, 0.0) == pytest.approx(0.0)
    assert lon_delta(0.0, 180.0) == pytest.approx(180.0)           # the open end of (-180, 180]
    got = lon_delta(np.array([179.9, -179.9, 10.0]), -179.9)
    assert got == pytest.approx([-0.2, 0.0, -170.1])
