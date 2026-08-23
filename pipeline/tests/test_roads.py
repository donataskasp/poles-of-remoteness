import json
from pathlib import Path

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, MultiPolygon, box

from poles.errors import PolesError
from poles.roads import RoadTiles, build_tiles, tile_grid
from tests.helpers import write_fgb


def _roads(tmp_path: Path) -> Path:
    # 400 short ways spread over lon 0..20, lat 40..60; one way crosses the tile seam at lon 10.
    rng = np.random.default_rng(1)
    xs = rng.uniform(0.5, 19.5, 400)
    ys = rng.uniform(40.5, 59.5, 400)
    geoms = [LineString([(x, y), (x + 0.01, y + 0.01)]) for x, y in zip(xs, ys)]
    geoms.append(LineString([(9.99, 45.0), (10.01, 45.0)]))
    ids = list(range(1, len(geoms) + 1))
    hw = ["track" if i % 3 == 0 else "residential" for i in ids]
    return write_fgb(tmp_path / "highways.fgb", "highways", geoms,
                     {"osm_id": ids, "highway": hw, "name": [None] * len(ids), "ref": [None] * len(ids)})


def test_tile_grid_snaps_outward_and_names_by_corner():
    tiles = tile_grid((-3.2, 41.1, 7.9, 52.0), 5.0)
    names = {t.name for t in tiles}
    assert names == {"t_-5_40", "t_0_40", "t_5_40", "t_-5_45", "t_0_45", "t_5_45", "t_-5_50", "t_0_50", "t_5_50"}
    t = next(t for t in tiles if t.name == "t_-5_40")
    assert (t.west, t.south, t.east, t.north) == (-5.0, 40.0, 0.0, 45.0)


def test_build_tiles_covers_every_feature_and_skips_empty(tmp_path, log):
    src = _roads(tmp_path)
    out = tmp_path / "roads"
    meta = build_tiles(src, "highways", out, log, tile_deg=10.0, workers=2)
    assert meta["source_features"] == 401
    assert {t["name"] for t in meta["tiles"]} == {"t_0_40", "t_10_40", "t_0_50", "t_10_50"}
    assert sum(t["features"] for t in meta["tiles"]) == 402  # the seam way sits in two tiles
    assert json.loads((out / "tiles.json").read_text())["tile_deg"] == 10.0
    assert all((out / f"{t['name']}.fgb").exists() and (out / f"{t['name']}.fgb.ok").exists() for t in meta["tiles"])


def test_query_dedups_seam_way_and_applies_where(tmp_path, log):
    src = _roads(tmp_path)
    out = tmp_path / "roads"
    build_tiles(src, "highways", out, log, tile_deg=10.0, workers=2)
    tiles = RoadTiles(out)
    # A box tight around the seam: the only way in it is 401, which lives in both tiles at lon 10.
    rs = tiles.query(9.95, 44.95, 10.05, 45.05)
    assert list(rs.attrs["osm_id"]) == [401]
    assert len(rs) == 1 and shapely.get_type_id(rs.geoms[0]) == 1
    everything = tiles.query(0, 40, 20, 60)
    assert len(everything) == 401
    tracks = tiles.query(0, 40, 20, 60, where="highway IN ('track')")
    assert len(tracks) == len([i for i in range(1, 402) if i % 3 == 0])
    # osm_id drives the dedup, so it is read even when the caller does not want it back
    lean = tiles.query(9.95, 44.95, 10.05, 45.05, columns=("highway",))
    assert len(lean) == 1 and set(lean.attrs) == {"highway"}
    nothing = tiles.query(30, 40, 31, 41)
    assert len(nothing) == 0
    assert set(nothing.attrs) == {"osm_id", "highway", "name", "ref"}


def test_build_tiles_resumes_from_markers(tmp_path, log):
    src = _roads(tmp_path)
    out = tmp_path / "roads"
    build_tiles(src, "highways", out, log, tile_deg=10.0, workers=1)
    marker = out / "t_0_40.fgb.ok"
    before = (out / "t_0_40.fgb").stat().st_mtime_ns
    build_tiles(src, "highways", out, log, tile_deg=10.0, workers=1)
    assert marker.exists() and (out / "t_0_40.fgb").stat().st_mtime_ns == before


def test_build_tiles_refuses_a_tile_past_the_index_limit(tmp_path, log, monkeypatch):
    src = _roads(tmp_path)
    out = tmp_path / "roads"
    monkeypatch.setattr("poles.roads.INDEX_LIMIT", 3)
    with pytest.raises(PolesError, match="t_0_40"):
        build_tiles(src, "highways", out, log, tile_deg=10.0, workers=1)
    assert not (out / "tiles.json").exists()


def test_tile_grid_from_longitude_intervals_skips_the_empty_ocean():
    # The shape a region drawn across the antimeridian has: its plain bounds run the whole world and
    # would tile 72 columns, of which 68 are ocean nobody asked about.
    bounds = (-180.0, 50.0, 180.0, 60.0)
    intervals = [(-180.0, -170.0), (170.0, 180.0)]
    tiles = tile_grid(bounds, 5.0, intervals)
    assert {t.name for t in tiles} == {"t_-180_50", "t_-175_50", "t_170_50", "t_175_50",
                                       "t_-180_55", "t_-175_55", "t_170_55", "t_175_55"}
    assert len(tile_grid(bounds, 5.0)) == 72 * 2


def test_build_tiles_lays_the_grid_out_from_the_extent_when_it_is_given(tmp_path, log):
    src = _roads(tmp_path)
    extent = MultiPolygon([box(0.0, 40.0, 9.0, 60.0), box(11.0, 40.0, 20.0, 60.0)])
    meta = build_tiles(src, "highways", tmp_path / "roads", log, tile_deg=10.0, workers=2, extent=extent)
    assert {t["name"] for t in meta["tiles"]} == {"t_0_40", "t_10_40", "t_0_50", "t_10_50"}
    assert sum(t["features"] for t in meta["tiles"]) == 402


def test_build_tiles_refuses_an_extent_that_does_not_cover_the_source(tmp_path, log):
    # The coverage guard used to be satisfied by construction (the grid came from the source's own
    # bounds). Now that the grid comes from the extract polygons it is the real check that the two agree.
    src = _roads(tmp_path)
    with pytest.raises(PolesError, match="but the source has"):
        build_tiles(src, "highways", tmp_path / "roads2", log, tile_deg=10.0, workers=2,
                    extent=box(0.0, 40.0, 9.0, 49.0))


def test_query_reads_both_sides_of_the_antimeridian(tmp_path, log):
    # Two ways either side of the line and one way across it: in the tile grid they are 360 degrees
    # apart, on the ground 0.1 degrees. The way across the line lands in both tiles under one osm_id.
    geoms = [LineString([(179.95, 51.9), (179.95, 52.1)]),
             LineString([(-179.95, 51.9), (-179.95, 52.1)]),
             LineString([(179.99, 52.0), (-179.99, 52.0)])]
    src = write_fgb(tmp_path / "highways.fgb", "highways", geoms,
                    {"osm_id": [1, 2, 3], "highway": ["track"] * 3, "name": [None] * 3, "ref": [None] * 3})
    out = tmp_path / "roads"
    extent = MultiPolygon([box(179.0, 51.0, 180.0, 53.0), box(-180.0, 51.0, -179.0, 53.0)])
    build_tiles(src, "highways", out, log, tile_deg=10.0, workers=2, extent=extent)
    tiles = RoadTiles(out)
    assert sorted(int(i) for i in tiles.query(179.9, 51.95, 180.1, 52.05).attrs["osm_id"]) == [1, 2, 3]
    # The same window written the other way round reads the same three ways.
    assert sorted(int(i) for i in tiles.query(-180.1, 51.95, -179.9, 52.05).attrs["osm_id"]) == [1, 2, 3]
    # An ordinary window still behaves like an ordinary window.
    assert sorted(int(i) for i in tiles.query(179.90, 51.95, 179.93, 52.05).attrs["osm_id"]) == [3]
