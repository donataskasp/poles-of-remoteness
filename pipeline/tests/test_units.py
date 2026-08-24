import logging

import numpy as np
import pytest
import rasterio
from rasterio.windows import Window
from shapely.geometry import MultiPolygon, Point, box

from poles.boundaries import AdminArea
from poles.config import RegionConfig, load_region
from poles.grid import Frame
from poles.poles import _units_from_fgb
from poles.units import (Unit, UnitsError, apply_territory_mask, country_of, inside_fraction, low_tif,
                         rasterize_units, select_units, unit_cells, write_units)
from tests.helpers import write_fgb


def _area(osm_id, code, geom, level=2, name=None):
    return AdminArea(osm_id, level, code, name or code, name or code, MultiPolygon([geom]) if geom.geom_type == "Polygon" else geom, True, False)


def _cfg(regions_dir, **over) -> RegionConfig:
    base = load_region(regions_dir / "europe.yaml").__dict__ | over
    return RegionConfig(**base)


def test_territory_mask_removes_island_but_keeps_mainland():
    mainland, island = box(0, 0, 4, 4), box(8, 8, 9, 9)
    geom = apply_territory_mask(MultiPolygon([mainland, island]), [{"name": "Isle", "bbox": [7.5, 7.5, 9.5, 9.5]}])
    assert geom.area == pytest.approx(16) and geom.contains(Point(2, 2)) and not geom.intersects(island)


def test_inside_fraction():
    assert inside_fraction(box(0, 0, 2, 2), box(0, 0, 10, 10)) == pytest.approx(1.0)
    assert inside_fraction(box(-1, 0, 1, 2), box(0, 0, 10, 10)) == pytest.approx(0.5)
    assert inside_fraction(box(20, 20, 21, 21), box(0, 0, 10, 10)) == 0.0


def test_level4_units_take_country_from_container(regions_dir):
    aa = _area(1, "AA", box(0, 0, 10, 10))
    bb = _area(2, "BB", box(20, 0, 30, 10))
    state = _area(3, "AA-X", box(1, 1, 3, 3), level=4)
    assert country_of(state, [aa, bb]) == "aa"
    assert country_of(bb, [aa, bb]) == "bb"
    cfg = _cfg(regions_dir, unit_admin_level=4, unit_countries=["aa"], unit_exclude=[], territory_mask=[], expected_units=1, transcontinental=[])
    units = select_units([aa, bb, state], cfg, box(-5, -5, 40, 15))
    assert [(u.code, u.country, u.index) for u in units] == [("aa-x", "aa", 1)]


def test_select_units_applies_exclude_supplement_rule_and_flags(regions_dir):
    aa = _area(1, "AA", box(0, 0, 10, 10))
    ru = _area(2, "RU", box(20, 0, 30, 10))
    outside = _area(3, "ZZ", box(50, 50, 60, 60))       # supplement country: outside the primary polygon
    half = _area(4, "HH", box(-6, 0, 4, 10))              # 40% inside: not a unit
    nocode = _area(5, None, box(0, 20, 1, 21), name="Land mass")
    cfg = _cfg(regions_dir, unit_countries=None, unit_exclude=["ru"], territory_mask=[], expected_units=1, transcontinental=["aa"])
    units = select_units([aa, ru, outside, half, nocode], cfg, box(0, 0, 40, 40))
    assert [(u.code, u.transcontinental) for u in units] == [("aa", True)]


def test_unit_count_mismatch_fails(regions_dir):
    aa = _area(1, "AA", box(0, 0, 10, 10))
    cfg = _cfg(regions_dir, unit_exclude=[], territory_mask=[], expected_units=2)
    with pytest.raises(UnitsError, match="expected 2"):
        select_units([aa], cfg, box(0, 0, 40, 40))


def test_expected_units_null_accepts_whatever_the_extract_holds(regions_dir):
    areas = [_area(1, "BB", box(4, 0, 6, 2)), _area(2, "AA", box(0, 0, 2, 2))]
    cfg = _cfg(regions_dir, unit_exclude=[], territory_mask=[], expected_units=None, transcontinental=[])
    units = select_units(areas, cfg, box(-1, -1, 10, 10))
    assert [(u.code, u.index) for u in units] == [("aa", 1), ("bb", 2)]


def test_unit_wiped_by_the_territory_mask_fails(regions_dir):
    island = _area(1, "II", box(0, 0, 1, 1))
    cfg = _cfg(regions_dir, unit_exclude=[], territory_mask=[{"name": "Isle", "bbox": [-1, -1, 2, 2]}],
               expected_units=1, transcontinental=[])
    with pytest.raises(UnitsError, match="territory mask"):
        select_units([island], cfg, box(-5, -5, 5, 5))


def test_incomplete_unit_is_warned_about(regions_dir, caplog):
    whole = AdminArea(1, 2, "AA", "Aa", "Aa", MultiPolygon([box(0, 0, 10, 10)]), True, False)
    cut = AdminArea(2, 2, "BB", "Bb", "Bb", MultiPolygon([box(20, 0, 30, 10)]), False, True)
    cfg = _cfg(regions_dir, unit_exclude=[], territory_mask=[], expected_units=2, transcontinental=[])
    with caplog.at_level(logging.WARNING):
        units = select_units([whole, cut], cfg, box(-5, -5, 40, 20))
    assert [u.closed_by_edge for u in units] == [False, True]
    assert len(caplog.records) == 1
    assert "bb" in caplog.records[0].getMessage() and "closed along the data edge" in caplog.records[0].getMessage()


def test_a_unit_whose_country_is_missing_is_skipped_with_a_warning(regions_dir, caplog):
    aa = _area(1, "AA", box(0, 0, 10, 10))
    inside = _area(3, "AA-X", box(1, 1, 3, 3), level=4)
    orphan = _area(4, "ZZ-Q", box(20, 1, 22, 3), level=4, name="Orphan")   # no level-2 area holds it
    cfg = _cfg(regions_dir, unit_admin_level=4, unit_countries=["aa"], unit_exclude=[], territory_mask=[],
               expected_units=None, transcontinental=[])
    with caplog.at_level(logging.WARNING):
        units = select_units([aa, inside, orphan], cfg, box(-5, -5, 40, 15))
    assert [u.code for u in units] == ["aa-x"]
    assert "Orphan" in caplog.text and "zz-q" in caplog.text.lower() and "no country" in caplog.text


def test_a_unit_split_at_the_antimeridian_is_still_inside_the_primary_polygons(regions_dir):
    # The unit and the extract polygon are both stored split at the line, which is how Geofabrik writes
    # its poly file and how the assembler now writes an area. Planar fractions work on both as they are.
    split_unit = MultiPolygon([box(178, 50, 180, 55), box(-180, 50, -178, 55)])
    primary = MultiPolygon([box(170, 45, 180, 60), box(-180, 45, -170, 60)])
    assert inside_fraction(split_unit, primary) == pytest.approx(1.0)
    aa = _area(1, "AA", primary)
    state = _area(3, "AA-X", split_unit, level=4)
    cfg = _cfg(regions_dir, unit_admin_level=4, unit_countries=["aa"], unit_exclude=[], territory_mask=[],
               expected_units=1, transcontinental=[])
    units = select_units([aa, state], cfg, primary)
    assert [(u.code, u.country) for u in units] == [("aa-x", "aa")]


# ---------- the candidate-cell raster ----------

def _unit(code: str, geom, index: int) -> Unit:
    return Unit(code, code.upper(), code.upper(), index, code, MultiPolygon([geom]), False, index)


def _mini(tmp_path, units, land, water=None):
    """A 6 x 6 degree frame of 1 degree cells, with the vector inputs the candidate rule reads.

    Cell (row, col) covers lon col..col+1 and lat 5-row..6-row, so its centre is at (col + 0.5, 5.5 - row)."""
    frame = Frame("EPSG:4326", 1.0, 0.0, 6.0, 6, 6)
    fgb = write_units(units, tmp_path / "units.fgb")
    land_fgb = write_fgb(tmp_path / "land.fgb", "land", land, {"fid": list(range(1, len(land) + 1))})
    water = water or [box(50, 50, 51, 51)]        # far outside the frame: the layer has to exist, not to matter
    water_fgb = write_fgb(tmp_path / "water.fgb", "water", water, {"fid": list(range(1, len(water) + 1))})
    return frame, fgb, land_fgb, water_fgb


def _raster(path):
    with rasterio.open(path) as ds:
        return ds.read(1)


def test_unit_raster_takes_an_islet_smaller_than_a_cell(tmp_path, log):
    """A candidate cell is any cell the unit's land touches, so a rock that holds no cell centre is one."""
    islet = box(1.1, 1.1, 1.2, 1.2)
    frame, fgb, land, water = _mini(tmp_path, [_unit("aa", islet, 1)], [box(1.05, 1.05, 1.25, 1.25)])
    counts = rasterize_units(fgb, frame, land, water, tmp_path / "units.tif", log, tmp_path)
    assert counts == {1: 1} and _raster(tmp_path / "units.tif")[4, 1] == 1


def test_unit_raster_takes_a_coastal_cell_whose_centre_is_at_sea(tmp_path, log):
    """The land part of a coastal cell is unit ground, whatever the cell centre happens to sit on."""
    coast = box(0, 0, 1.3, 1.3)
    frame, fgb, land, water = _mini(tmp_path, [_unit("aa", coast, 1)], [coast])
    counts = rasterize_units(fgb, frame, land, water, tmp_path / "units.tif", log, tmp_path)
    arr = _raster(tmp_path / "units.tif")
    assert counts == {1: 4}                       # the cell it fills and the three it only touches
    assert arr[5, 0] == 1 and arr[4, 0] == 1 and arr[5, 1] == 1 and arr[4, 1] == 1


def test_unit_raster_drops_only_the_cells_fully_inside_big_water(tmp_path, log):
    whole, lake = box(0, 0, 6, 6), box(1.2, 1.2, 3.8, 3.8)
    frame, fgb, land, water = _mini(tmp_path, [_unit("aa", whole, 1)], [whole], [lake])
    counts = rasterize_units(fgb, frame, land, water, tmp_path / "units.tif", log, tmp_path)
    arr = _raster(tmp_path / "units.tif")
    assert counts == {1: 35} and arr[3, 2] == 0   # lon 2..3, lat 2..3 is the only cell the lake covers whole
    assert arr[4, 1] == 1                         # centre in the lake, shore in the cell: still a candidate


def test_unit_raster_leaves_out_a_cell_no_land_touches(tmp_path, log):
    frame, fgb, land, water = _mini(tmp_path, [_unit("aa", box(0, 0, 3.9, 3.9), 1)], [box(0, 0, 2.5, 3.9)])
    counts = rasterize_units(fgb, frame, land, water, tmp_path / "units.tif", log, tmp_path)
    arr = _raster(tmp_path / "units.tif")
    assert counts == {1: 12} and arr[5, 3] == 0 and arr[5, 2] == 1


def test_unit_cells_gives_a_border_cell_to_both_units(tmp_path, log):
    """An int16 raster names one owner per cell, so the two rasters are burnt in opposite index order and
    a unit's cells are read as the union: no unit loses a cell to a neighbour that touches it too."""
    aa, bb = box(0, 0, 1.4, 6), box(1.4, 0, 6, 6)
    units = [_unit("aa", aa, 1), _unit("bb", bb, 2)]
    frame, fgb, land, water = _mini(tmp_path, units, [box(0, 0, 6, 6)])
    counts = rasterize_units(fgb, frame, land, water, tmp_path / "units.tif", log, tmp_path)
    assert counts == {1: 12, 2: 30}               # column 1 is a candidate cell of both units
    assert _raster(tmp_path / "units.tif")[0, 1] == 2 and _raster(low_tif(tmp_path / "units.tif"))[0, 1] == 1
    for unit in units:
        rows, cols = unit_cells(tmp_path / "units.tif", unit)
        assert 1 in cols.tolist()


def test_unit_cells_window_reads_a_box_and_still_reports_absolute_rows(tmp_path, log):
    """A window covering the unit answers what the whole raster would, in whole-raster coordinates."""
    unit = _unit("aa", box(1.1, 1.1, 1.2, 1.2), 1)
    frame, fgb, land, water = _mini(tmp_path, [unit], [box(1.05, 1.05, 1.25, 1.25)])
    rasterize_units(fgb, frame, land, water, tmp_path / "units.tif", log, tmp_path)
    window = Window(col_off=1, row_off=2, width=3, height=4)          # rows 2 to 5, cols 1 to 3
    rows, cols = unit_cells(tmp_path / "units.tif", unit, window=window)
    assert list(zip(rows.tolist(), cols.tolist())) == [(4, 1)]


def test_unit_cells_fails_when_the_unit_has_no_candidate_cell(tmp_path, log):
    unit = _unit("aa", box(1.1, 1.1, 1.2, 1.2), 1)
    frame, fgb, land, water = _mini(tmp_path, [unit], [box(5.1, 5.1, 5.2, 5.2)])   # land nowhere near the unit
    assert rasterize_units(fgb, frame, land, water, tmp_path / "units.tif", log, tmp_path) == {1: 0}
    with pytest.raises(UnitsError, match="no candidate cell"):
        unit_cells(tmp_path / "units.tif", unit)


def test_units_round_trip_through_the_fgb_keeps_every_persisted_field(tmp_path):
    """The resume path rebuilds units from units.fgb, so what it drops there ends up null in units.json."""
    units = [Unit("lt", "Lietuva", "Lithuania", 72596, "lt", MultiPolygon([box(0, 0, 2, 2)]), False, 1),
             Unit("tr", "Türkiye", "Turkey", 174737, "tr", MultiPolygon([box(4, 4, 5, 5)]), True, 2, closed_by_edge=True)]
    back = _units_from_fgb(write_units(units, tmp_path / "units.fgb"))
    assert back == units
