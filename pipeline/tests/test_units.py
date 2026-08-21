import logging

import numpy as np
import pytest
import rasterio
from rasterio.windows import Window
from shapely.geometry import MultiPolygon, Point, box

from poles.boundaries import AdminArea
from poles.config import RegionConfig, load_region
from poles.grid import Frame, create_raster
from poles.poles import _units_from_fgb
from poles.units import (Unit, UnitsError, apply_territory_mask, country_of, inside_fraction, rasterize_units,
                         select_units, unit_cells, write_units)


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


def test_unit_raster_assigns_each_cell_to_one_unit(tmp_path, log, regions_dir):
    aa = _area(1, "AA", box(0, 0, 2, 2))
    bb = _area(2, "BB", box(2, 0, 4, 2))
    cfg = _cfg(regions_dir, unit_exclude=[], territory_mask=[], expected_units=2, transcontinental=[])
    units = select_units([aa, bb], cfg, box(-1, -1, 10, 10))
    fgb = write_units(units, tmp_path / "units.fgb")
    frame = Frame("EPSG:4326", 0.5, -1.0, 3.0, 10, 8)        # lon -1..4, lat -1..3 at 0.5 degree cells
    land = create_raster(frame, tmp_path / "land.tif")
    with rasterio.open(land, "r+") as ds:
        arr = ds.read(1)
        arr[:, :] = 1
        arr[:, 9] = 0                                        # the easternmost column is sea
        ds.write(arr, 1)
    counts = rasterize_units(fgb, frame, land, tmp_path / "units.tif", log, tmp_path)
    with rasterio.open(tmp_path / "units.tif") as ds:
        u = ds.read(1)
    assert u.dtype == np.int16 and set(np.unique(u)) == {0, 1, 2}
    assert counts == {1: 16, 2: 12}                         # 4 x 4 cells each, minus bb's sea column
    assert u[2:6, 2:6].min() == 1 and u[2:6, 6:9].min() == 2 and u[:, 9].max() == 0 and u[0].max() == 0


def test_unit_cells_falls_back_to_all_touched_for_a_microstate(tmp_path, log, regions_dir):
    tiny = _area(1, "TT", box(1.1, 1.1, 1.2, 1.2))        # smaller than a cell, contains no cell centre
    cfg = _cfg(regions_dir, unit_exclude=[], territory_mask=[], expected_units=1, transcontinental=[])
    units = select_units([tiny], cfg, box(0, 0, 10, 10))
    fgb = write_units(units, tmp_path / "units.fgb")
    frame = Frame("EPSG:4326", 0.5, 0.0, 3.0, 6, 6)
    land = create_raster(frame, tmp_path / "land.tif")
    with rasterio.open(land, "r+") as ds:
        ds.write(np.ones((6, 6), dtype="uint8"), 1)
    counts = rasterize_units(fgb, frame, land, tmp_path / "units.tif", log, tmp_path)
    assert counts == {1: 0}
    rows, cols = unit_cells(tmp_path / "units.tif", units[0], frame, log, tmp_path)
    assert list(zip(rows.tolist(), cols.tolist())) == [(3, 2)]   # lat 1.1..1.2 is row 3, lon 1.1..1.2 is col 2


def test_unit_cells_window_reads_a_box_and_still_reports_absolute_rows(tmp_path, log, regions_dir):
    """A window covering the unit answers the same as the whole raster, for a unit that holds a cell centre
    and for a microstate that has to fall back to all-touched."""
    big = _area(1, "BB", box(0.55, 0.55, 0.95, 0.95))     # holds exactly the centre of the cell at row 4, col 1
    tiny = _area(2, "TT", box(1.1, 1.1, 1.2, 1.2))        # smaller than a cell, contains no cell centre
    cfg = _cfg(regions_dir, unit_exclude=[], territory_mask=[], expected_units=2, transcontinental=[])
    units = select_units([big, tiny], cfg, box(0, 0, 10, 10))
    fgb = write_units(units, tmp_path / "units.fgb")
    frame = Frame("EPSG:4326", 0.5, 0.0, 3.0, 6, 6)
    land = create_raster(frame, tmp_path / "land.tif")
    with rasterio.open(land, "r+") as ds:
        ds.write(np.ones((6, 6), dtype="uint8"), 1)
    assert rasterize_units(fgb, frame, land, tmp_path / "units.tif", log, tmp_path) == {1: 1, 2: 0}
    bb, tt = units                                                # sorted by code: bb then tt
    window = Window(col_off=1, row_off=2, width=3, height=4)      # rows 2 to 5, cols 1 to 3
    rows, cols = unit_cells(tmp_path / "units.tif", bb, frame, log, tmp_path, window=window)
    assert list(zip(rows.tolist(), cols.tolist())) == [(4, 1)]
    rows, cols = unit_cells(tmp_path / "units.tif", tt, frame, log, tmp_path, window=window)
    assert list(zip(rows.tolist(), cols.tolist())) == [(3, 2)]    # lat 1.1..1.2 is row 3, lon 1.1..1.2 is col 2


def test_units_round_trip_through_the_fgb_keeps_every_persisted_field(tmp_path):
    """The resume path rebuilds units from units.fgb, so what it drops there ends up null in units.json."""
    units = [Unit("lt", "Lietuva", "Lithuania", 72596, "lt", MultiPolygon([box(0, 0, 2, 2)]), False, 1),
             Unit("tr", "Türkiye", "Turkey", 174737, "tr", MultiPolygon([box(4, 4, 5, 5)]), True, 2, closed_by_edge=True)]
    back = _units_from_fgb(write_units(units, tmp_path / "units.fgb"))
    assert back == units
