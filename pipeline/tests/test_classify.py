import pytest
import shapely
from pyogrio import read_info
from pyogrio.raw import read

from poles import classify
from poles.workspace import Workspace
from tests.helpers import write_fgb

SET_B = [
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
    "living_street", "service", "road", "busway",
    "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",
]
EXCLUDED = [
    "path", "footway", "cycleway", "bridleway", "steps", "pedestrian", "corridor", "proposed",
    "construction", "abandoned", "razed", "platform", "raceway", "bus_guideway", "escape", "elevator",
]

CASES = (
    [({"highway": h}, (True, True)) for h in SET_B]
    + [({"highway": "track"}, (True, False))]
    + [({"highway": h}, (False, False)) for h in EXCLUDED]
    + [
        ({"highway": "unclassified", "access": "private"}, (True, True)),   # physical, not legal
        ({"highway": "service", "motor_vehicle": "no"}, (True, True)),
        ({"highway": "track", "ice_road": "yes"}, (True, False)),
        ({"highway": "unclassified", "winter_road": "yes"}, (True, True)),
        ({"highway": "motorway_link"}, (True, True)),
        ({"highway": "proposed", "proposed": "primary"}, (False, False)),
        ({"name": "no highway tag"}, (False, False)),
        ({"highway": "bus_stop"}, (False, False)),
        ({"highway": "primary", "area": "yes"}, (True, True)),
        ({"highway": "ferry"}, (False, False)),
    ]
)


@pytest.mark.parametrize("tags,expected", CASES, ids=[str(t) for t, _ in CASES])
def test_classify_highway_table(tags, expected):
    assert classify.classify_highway(tags) == expected


def test_sets_match_spec_lists():
    assert classify.SET_B == frozenset(SET_B)
    assert classify.SET_A == frozenset(SET_B) | {"track"}
    assert not (classify.SET_A & frozenset(EXCLUDED))


def test_where_clause_is_built_from_the_sets():
    assert classify.where_clause("A") == "highway IN (" + ", ".join(f"'{h}'" for h in sorted(classify.SET_A)) + ")"
    assert "'track'" in classify.where_clause("A") and "'track'" not in classify.where_clause("B")


def _highways_fixture(ws: Workspace) -> dict[int, dict]:
    """One way per interesting tag case; returns osm_id -> tags."""
    rows = {}
    i = 0
    for tags, _ in CASES:
        if "highway" not in tags:
            continue
        i += 1
        rows[1000 + i] = tags
    geoms = [shapely.LineString([(25 + k * 0.001, 55), (25 + k * 0.001, 55.001)]) for k in range(len(rows))]
    write_fgb(ws.dir("extract") / "highways.fgb", "highways", geoms, {
        "osm_id": list(rows),
        "highway": [t.get("highway") for t in rows.values()],
        "name": [t.get("name") for t in rows.values()],
        "ref": [None for _ in rows],
        "ice_road": [t.get("ice_road") for t in rows.values()],
        "winter_road": [t.get("winter_road") for t in rows.values()],
    })
    return rows


def _way_ids(path) -> set[int]:
    meta, _, _, field_data = read(str(path), read_geometry=False)
    return set(int(v) for v in field_data[list(meta["fields"]).index("way_id")])


def test_run_matches_classify_highway_row_by_row(tmp_path, cfg, log):
    ws = Workspace(tmp_path, "europe", "2026-08-19")
    rows = _highways_fixture(ws)
    meta = classify.run(cfg, ws, log)
    got_a, got_b = _way_ids(ws.dir("classify") / "roads_A.fgb"), _way_ids(ws.dir("classify") / "roads_B.fgb")
    assert got_a == {i for i, t in rows.items() if classify.classify_highway(t)[0]}
    assert got_b == {i for i, t in rows.items() if classify.classify_highway(t)[1]}
    assert meta == {"roads_A": len(got_a), "roads_B": len(got_b)}
    info = read_info(str(ws.dir("classify") / "roads_A.fgb"))
    assert list(info["fields"]) == ["way_id", "highway", "name", "ref"]


def test_run_writes_two_layers_with_subset_relation(tmp_path, cfg, log):
    ws = Workspace(tmp_path, "europe", "2026-08-19")
    _highways_fixture(ws)
    classify.run(cfg, ws, log)
    a, b = _way_ids(ws.dir("classify") / "roads_A.fgb"), _way_ids(ws.dir("classify") / "roads_B.fgb")
    assert b < a and len(a) == len(b) + 2   # the two track rows are in A only
