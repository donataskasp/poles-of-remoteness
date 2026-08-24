import pytest
from shapely.geometry import LineString, Point, box

from poles.boundaries import (Relation, _osmium_tolerant, assemble, assemble_area, load_admin_areas,
                              read_relations, seed_points, way_geometries)
from poles.shell import ToolError

EDGE = box(0, 0, 10, 10)
CODES = {2: "ISO3166-1", 4: "ISO3166-2"}


def test_read_relations_filters_administrative_at_levels(admin_pbf, tmp_path, log):
    rels = read_relations(admin_pbf, {2, 4}, tmp_path, log)
    assert sorted(r.id for r in rels) == [201, 202, 203, 205, 206]  # 204 is maritime
    r201 = next(r for r in rels if r.id == 201)
    assert r201.tags["ISO3166-1"] == "AA" and ("w", 103, "inner") in r201.members and ("n", 51, "admin_centre") in r201.members


def test_way_geometries_and_seeds_tolerate_missing_ids(admin_pbf, tmp_path, log):
    ways = way_geometries(admin_pbf, {101, 104, 105}, tmp_path, log)
    assert set(ways) == {101, 104} and ways[104].coords[0] == (12.0, 6.0)
    seeds = seed_points(admin_pbf, {50, 999}, tmp_path, log)
    assert set(seeds) == {50} and seeds[50].equals(Point(8, 7.5))


def test_assemble_closed_rings_with_inner_hole():
    rel = Relation(1, {}, [("w", 1, "outer"), ("w", 2, "outer"), ("w", 3, "inner")])
    ways = {1: LineString([(0, 0), (4, 0), (4, 4)]), 2: LineString([(4, 4), (0, 4), (0, 0)]),
            3: LineString([(1, 1), (2, 1), (2, 2), (1, 2), (1, 1)])}
    geom = assemble(rel, ways, {}, None)
    assert geom.geom_type == "MultiPolygon" and geom.area == pytest.approx(16 - 1)
    assert not geom.contains(Point(1.5, 1.5)) and geom.contains(Point(3, 3))


def test_assemble_open_ring_is_closed_along_edge_at_seed_faces():
    rel = Relation(2, {}, [("w", 4, "outer"), ("w", 5, "outer"), ("n", 50, "admin_centre")])
    ways = {4: LineString([(12, 6), (6, 6), (6, 9), (12, 9)])}
    geom = assemble(rel, ways, {50: Point(8, 7.5)}, EDGE)
    assert geom.area == pytest.approx(12.0)  # (6..10) x (6..9)
    assert geom.contains(Point(8, 7.5)) and not geom.contains(Point(11, 7.5)) and not geom.contains(Point(5, 7.5))


def test_assemble_open_ring_without_seed_or_edge_returns_none():
    rel = Relation(3, {}, [("w", 4, "outer")])
    ways = {4: LineString([(12, 6), (6, 6), (6, 9), (12, 9)])}
    assert assemble(rel, ways, {}, EDGE) is None
    assert assemble(rel, ways, {50: Point(8, 7.5)}, None) is None


def test_assemble_splits_a_relation_drawn_across_the_antimeridian():
    # Two member ways forming one ring from 178 east to 178 west, the way OSM stores a unit on the line.
    rel = Relation(5, {}, [("w", 10, "outer"), ("w", 11, "outer")])
    ways = {10: LineString([(178.0, 50.0), (179.0, 50.0), (-179.0, 50.0), (-178.0, 50.0)]),
            11: LineString([(-178.0, 50.0), (-178.0, 55.0), (178.0, 55.0), (178.0, 50.0)])}
    geom = assemble(rel, ways, {}, None)
    assert geom.geom_type == "MultiPolygon" and len(geom.geoms) == 2
    assert all(p.bounds[0] >= -180.0 and p.bounds[2] <= 180.0 for p in geom.geoms)
    assert geom.area == pytest.approx(20.0)              # 4 degrees of longitude, 5 of latitude
    assert geom.contains(Point(179.5, 52.5)) and geom.contains(Point(-179.5, 52.5))
    assert not geom.contains(Point(0.0, 52.5))


def test_assemble_across_the_line_keeps_an_inner_ring_as_a_hole():
    rel = Relation(6, {}, [("w", 10, "outer"), ("w", 11, "outer"), ("w", 12, "inner")])
    ways = {10: LineString([(178.0, 50.0), (179.0, 50.0), (-179.0, 50.0), (-178.0, 50.0)]),
            11: LineString([(-178.0, 50.0), (-178.0, 55.0), (178.0, 55.0), (178.0, 50.0)]),
            12: LineString([(179.5, 51.0), (-179.5, 51.0), (-179.5, 52.0), (179.5, 52.0), (179.5, 51.0)])}
    geom = assemble(rel, ways, {}, None)
    assert geom.area == pytest.approx(20.0 - 1.0)        # a hole 1 degree wide and 1 degree tall
    assert not geom.contains(Point(179.75, 51.5)) and not geom.contains(Point(-179.75, 51.5))
    assert geom.contains(Point(179.75, 53.0))


def test_assemble_across_the_line_keeps_a_hole_that_lies_wholly_in_the_far_lobe():
    """The inner ring never steps over the line itself, so it unwraps to where it was stored while the
    shell moves east of 180. Only a containment test that turns by a whole 360 still sees it as a hole."""
    rel = Relation(7, {}, [("w", 10, "outer"), ("w", 11, "outer"), ("w", 13, "inner")])
    ways = {10: LineString([(178.0, 50.0), (179.0, 50.0), (-179.0, 50.0), (-178.0, 50.0)]),
            11: LineString([(-178.0, 50.0), (-178.0, 55.0), (178.0, 55.0), (178.0, 50.0)]),
            13: LineString([(-179.5, 51.0), (-179.0, 51.0), (-179.0, 52.0), (-179.5, 52.0), (-179.5, 51.0)])}
    geom = assemble(rel, ways, {}, None)
    assert geom.geom_type == "MultiPolygon" and len(geom.geoms) == 2 and geom.is_valid
    assert geom.area == pytest.approx(20.0 - 0.5)        # a hole half a degree wide and 1 degree tall
    assert not geom.contains(Point(-179.25, 51.5))
    assert geom.contains(Point(-179.75, 51.5)) and geom.contains(Point(179.5, 51.5))


def test_load_admin_areas_end_to_end(admin_pbf, tmp_path, log):
    areas = {a.osm_id: a for a in load_admin_areas(admin_pbf, {2, 4}, EDGE, tmp_path, log, CODES)}
    assert set(areas) == {201, 202, 203, 205, 206}
    aa, bb, cc, land, ax = areas[201], areas[202], areas[203], areas[205], areas[206]
    assert (aa.code, aa.level, aa.name_en, aa.complete, aa.closed_by_edge) == ("AA", 2, "Alphaland", True, False)
    assert aa.geometry.area == pytest.approx(9 - 1) and not aa.geometry.contains(Point(2.5, 2.5))
    assert (bb.code, bb.complete, bb.closed_by_edge) == ("BB", False, True) and bb.geometry.area == pytest.approx(12)
    assert cc.code == "CC" and cc.geometry.area == pytest.approx(1)
    assert land.code is None and land.geometry.area == pytest.approx(9)
    assert (ax.code, ax.level) == ("AA-X", 4) and ax.geometry.area == pytest.approx(2.6 * 0.6)


def test_assemble_area_flags_only_a_ring_the_edge_actually_closed():
    """An open line the edge cannot close (no seed node) is dropped, so the rings that survive are real."""
    rel = Relation(4, {"admin_level": "2", "ISO3166-1": "AA", "name": "Alpha"},
                   [("w", 4, "outer"), ("w", 6, "outer"), ("w", 7, "outer")])
    ways = {4: LineString([(12, 6), (6, 6), (6, 9), (12, 9)]),
            6: LineString([(1, 1), (3, 1), (3, 3), (1, 3), (1, 1)])}
    area = assemble_area(rel, ways, {}, EDGE, "ISO3166-1")
    assert area.geometry.area == pytest.approx(4) and area.complete is False and area.closed_by_edge is False
    assert assemble_area(rel, {}, {}, EDGE, "ISO3166-1") is None  # no member present at all


@pytest.mark.parametrize("case", ["prints an error and exits 1", "exits 2"])
def test_osmium_tolerant_reraises_a_real_failure_and_drops_the_stale_output(admin_pbf, tmp_path, log, case):
    """Only a silent exit 1 is a missing id. A hard failure exits 1 too and still creates an empty output,
    so tolerating it would let seed_points read last run's file, or an empty one, as this run's answer."""
    out = tmp_path / "seeds.opl"
    out.write_text("n50 v0 dV c0 t i0 u T x8 y7.5\n", encoding="utf-8")  # left over from an earlier run
    src = admin_pbf if case == "exits 2" else tmp_path / "absent.osm.pbf"
    args = ["getid", "--overwrite", "-f", "opl", "-o", out, src, "n50"]
    if case == "exits 2":
        args.insert(1, "--no-such-flag")
    with pytest.raises(ToolError):
        _osmium_tolerant(args, out, log, tmp_path / "tools.log")
    assert not out.exists() or out.read_text(encoding="utf-8") == ""  # the stale content is gone either way
