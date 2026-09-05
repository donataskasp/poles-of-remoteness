"""The coarse grid read as a landscape: the ladder, the superlevel labellings, the land components.

Synthetic fields only, small enough that the expected answer is arithmetic anyone can check by hand.
"""
import numpy as np
import pytest
import rasterio

from poles.areas import (NO_LEVEL, AreaField, AreasError, LADDER_STEP, col_threshold, ladder_index,
                         ladder_value)
from poles.grid import Frame, write_float_tif

ANCHOR = 1000.0


def _field(dist, land=None, res_m=250.0, row_off=0, col_off=0, anchor_m=ANCHOR):
    """An AreaField over a hand-written distance field; land defaults to every cell."""
    dist = np.asarray(dist, dtype="float32")
    if dist.ndim == 1:
        dist = dist[None, :]
    land = np.ones(dist.shape, dtype=bool) if land is None else np.asarray(land, dtype=bool)
    return AreaField.from_arrays(dist, land, res_m, row_off, col_off, anchor_m)


# ---------- the ladder ----------

def test_ladder_quantises_down_and_is_monotone():
    """theta_k = anchor * (1 - step) ** k, and a threshold takes the first rung at or below it.

    Down is the safe direction: a lower threshold gives a larger superlevel set, hence more connectivity,
    hence more candidates called the same place, so the quantisation can only make the rule stricter."""
    assert ladder_index(ANCHOR, ANCHOR) == 0 and ladder_value(0, ANCHOR) == ANCHOR
    for d in (999.0, 500.0, 100.0, 1.0):
        k = ladder_index(d, ANCHOR)
        assert ladder_value(k, ANCHOR) <= d < ladder_value(k - 1, ANCHOR)
        assert ladder_value(k, ANCHOR) > d * (1 - LADDER_STEP)
    falling = ladder_index(np.array([1000.0, 900.0, 500.0, 100.0]), ANCHOR)
    assert list(falling) == sorted(falling) and falling[0] < falling[-1]
    assert ladder_index(0.0, ANCHOR) == NO_LEVEL          # the ladder cannot name a cell on a road
    assert ladder_index(2 * ANCHOR, ANCHOR) == 0          # above the anchor is the top rung, never negative


def test_col_threshold_takes_the_lower_of_the_two_distances():
    assert col_threshold(100.0, 60.0, 0.5) == 30.0
    assert col_threshold(60.0, 100.0, 0.5) == 30.0
    assert col_threshold(80.0, 80.0, 0.25) == 20.0


# ---------- connectivity ----------

def test_two_peaks_split_by_a_road_valley_are_two_components():
    """A 1 x 21 ridge at 1,000 m with a 200 m valley in the middle: at a threshold of 500 the valley is
    out of the superlevel set and the two ends are two places; at 100 it is in and they are one."""
    dist = np.full(21, 1000.0)
    dist[10] = 200.0
    f = _field(dist)
    left, right = f.component_at(0, 5, 500.0), f.component_at(0, 15, 500.0)
    assert left > 0 and right > 0 and left != right
    assert f.component_at(0, 5, 100.0) == f.component_at(0, 15, 100.0) > 0


def test_two_peaks_on_one_plateau_are_one_component():
    f = _field(np.full(21, 1000.0))
    assert f.component_at(0, 2, 500.0) == f.component_at(0, 18, 500.0) > 0


def test_water_does_not_join_two_areas():
    """Two identical peaks two cells apart. The gap is above the threshold either way, so only the land
    mask decides: land joins them, water leaves them two places."""
    dist = np.array([1000.0, 1000.0, 900.0, 900.0, 1000.0, 1000.0])
    joined = _field(dist)
    assert joined.component_at(0, 0, 500.0) == joined.component_at(0, 5, 500.0) > 0
    land = np.array([[True, True, False, False, True, True]])
    split = _field(dist, land=land)
    assert split.component_at(0, 0, 500.0) != split.component_at(0, 5, 500.0)
    assert split.component_at(0, 2, 500.0) == 0


def test_component_at_returns_zero_for_a_cell_below_the_threshold_or_off_land():
    dist = np.array([[1000.0, 200.0, 1000.0]])
    f = _field(dist, land=np.array([[True, True, False]]))
    assert f.component_at(0, 0, 500.0) > 0
    assert f.component_at(0, 1, 500.0) == 0      # below the threshold
    assert f.component_at(0, 2, 500.0) == 0      # off land, whatever its distance says


def test_labels_at_is_cached_per_ladder_step_and_recomputed_when_the_step_changes():
    """One entry, keyed by the ladder index: thresholds arrive non-increasing, so a second would never hit."""
    dist = np.full(21, 1000.0)
    dist[10] = 200.0
    f = _field(dist)
    first = f.labels_at(500.0)
    assert f.labels_at(499.9) is first                    # the same rung, the same array
    other = f.labels_at(100.0)
    assert other is not first and other.max() == 1        # a lower rung joins the two ends
    assert f.labels_at(500.0) is not first                # one entry only, so the old rung is recomputed


def test_dead_cells_only_names_cells_whose_whole_neighbourhood_is_in_the_component():
    """A refined point never leaves its cell's eight neighbours, so a cell whose whole neighbourhood is
    in the component can hold no new place and is retired."""
    rows, cols = np.mgrid[0:5, 0:5]
    rows, cols = rows.ravel(), cols.ravel()
    flat = _field(np.full((5, 5), 1000.0))
    comp = flat.component_at(2, 2, 500.0)
    dead = flat.dead_cells(rows, cols, comp, 500.0)
    assert dead.sum() == 9                                  # the 3 x 3 interior, never the window's edge
    assert {(int(r), int(c)) for r, c, d in zip(rows, cols, dead) if d} == {
        (r, c) for r in (1, 2, 3) for c in (1, 2, 3)}
    holed = np.full((5, 5), 1000.0)
    holed[2, 2] = 200.0                                     # a valley cell: nothing around it is dead now
    f = _field(holed)
    dead = f.dead_cells(rows, cols, f.component_at(0, 0, 500.0), 500.0)
    assert not dead.any()


def test_rowcol_maps_frame_indices_into_the_window_and_rejects_a_point_outside_it():
    f = _field(np.full((4, 6), 1000.0), row_off=10, col_off=20)
    wr, wc = f.rowcol(np.array([10, 13]), np.array([20, 25]))
    assert list(wr) == [0, 3] and list(wc) == [0, 5]
    with pytest.raises(AreasError, match="outside"):
        f.rowcol(np.array([9]), np.array([20]))
    with pytest.raises(AreasError, match="outside"):
        f.rowcol(np.array([10]), np.array([26]))


# ---------- land components ----------

def test_an_islet_is_its_own_component_of_one_cell():
    land = np.array([[True, True, False, False, True]])
    f = _field(np.full(5, 1000.0), land=land)
    comps = f.land_components()
    islet = comps.labels[0, 4]
    assert islet > 0 and islet != comps.labels[0, 0]
    assert (comps.labels == islet).sum() == 1
    assert comps.area_km2[islet] == pytest.approx(0.0625)     # one 250 m cell


def test_land_components_areas_are_cell_counts_times_the_cell_area():
    land = np.zeros((4, 6), dtype=bool)
    land[0:2, 0:2] = True                                     # four cells
    land[3, 5] = True                                         # one cell, not touching the block
    f = _field(np.full((4, 6), 1000.0), land=land)
    comps = f.land_components()
    block, islet = comps.labels[0, 0], comps.labels[3, 5]
    assert comps.area_km2[block] == pytest.approx(4 * 0.0625)
    assert comps.area_km2[islet] == pytest.approx(0.0625)
    assert comps.area_km2[0] == 0                              # index 0 is "off land" and carries no area
    assert comps.labels[2, 2] == 0
    assert f.land_components() is comps                        # labelled once, then kept


def test_a_cell_on_a_road_is_land_but_in_no_superlevel_set():
    """Distance 0 is the low ground that separates areas, so it belongs to no set the ladder can name,
    while it is still part of its land component: a mainland is not cut into pieces along its own roads,
    which would leave every piece under the island floor."""
    f = _field(np.array([[1000.0, 0.0, 1000.0]]))
    assert f.component_at(0, 1, 1.0) == 0
    comps = f.land_components()
    assert comps.labels[0, 1] == comps.labels[0, 0] > 0
    assert comps.area_km2[comps.labels[0, 0]] == pytest.approx(3 * 0.0625)


# ---------- reading the rasters ----------

def test_read_takes_the_candidate_rule_land_mask_from_the_two_rasters(tmp_path):
    """The candidate rule of the unit raster: land touches the cell and big water does not fill it."""
    frame = Frame("EPSG:3035", 250.0, 0.0, 1000.0, 4, 4)
    dist = np.full((4, 4), 1000.0, dtype="float32")
    dist[1, 1] = 200.0
    write_float_tif(tmp_path / "dist.tif", dist, frame)
    land = np.ones((4, 4), dtype="uint8")
    land[3, :] = 0                                            # a row of open sea
    water = np.zeros((4, 4), dtype="uint8")
    water[0, 3] = 1                                           # a cell big water fills
    for name, arr in (("land.tif", land), ("water.tif", water)):
        with rasterio.open(tmp_path / name, "w", width=4, height=4, count=1, dtype="uint8",
                           crs=frame.crs, transform=frame.transform) as ds:
            ds.write(arr, 1)
    from rasterio.windows import Window
    f = AreaField.read(tmp_path / "dist.tif", tmp_path / "land.tif", tmp_path / "water.tif", frame,
                       Window(col_off=0, row_off=0, width=4, height=4), ANCHOR)
    assert f.component_at(0, 0, 500.0) > 0
    assert f.component_at(3, 0, 500.0) == 0                   # not land
    assert f.component_at(0, 3, 500.0) == 0                   # filled by big water
    assert f.component_at(1, 1, 500.0) == 0                   # land, but below the threshold
    comps = f.land_components()
    assert (comps.labels > 0).sum() == 11                     # 16 cells less the sea row less the water cell


def test_read_takes_only_its_window_of_the_rasters(tmp_path):
    """A worker reads its unit's box, and the returned field answers in whole-frame coordinates."""
    frame = Frame("EPSG:3035", 250.0, 0.0, 2000.0, 8, 8)
    dist = np.full((8, 8), 1000.0, dtype="float32")
    dist[5, 5] = 200.0
    write_float_tif(tmp_path / "dist.tif", dist, frame)
    for name, value in (("land.tif", 1), ("water.tif", 0)):
        with rasterio.open(tmp_path / name, "w", width=8, height=8, count=1, dtype="uint8",
                           crs=frame.crs, transform=frame.transform) as ds:
            ds.write(np.full((8, 8), value, dtype="uint8"), 1)
    from rasterio.windows import Window
    f = AreaField.read(tmp_path / "dist.tif", tmp_path / "land.tif", tmp_path / "water.tif", frame,
                       Window(col_off=4, row_off=4, width=4, height=4), ANCHOR)
    assert f.level.shape == (4, 4)
    assert f.component_at(4, 4, 500.0) > 0
    assert f.component_at(5, 5, 500.0) == 0                   # the valley, addressed by its frame row and col
    with pytest.raises(AreasError, match="outside"):
        f.component_at(0, 0, 500.0)
