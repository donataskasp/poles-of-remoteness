"""The coarse distance grid read as a landscape: superlevel sets, connectivity, land components.

Two rules of the search live here, and nothing else does. Neither knows about units, scenarios or poles.

**The distinct-area rule.** Two candidates count as one place unless the ground between them drops below
`fraction * min(d_p, d_q)`, measured over land on the scenario's coarse grid. "Between them" is answered by
connectivity: label the superlevel set `{distance >= threshold}` restricted to land, and ask whether the two
cells carry the same label. A col (the saddle between two summits) lower than the threshold is exactly what
splits one label into two, which is why the region config calls the fraction `area_col_fraction`.

**The island floor.** `land_components` labels the land itself, with an area per label, so the poles stage
can refuse a candidate cell whose whole land component is smaller than `min_island_m2` and can tag a pole
that sits on a component other than its unit's largest.

**The ladder, and why the rule carries it.** A labelling per candidate would be a `scipy.ndimage.label` call
per acceptance test, and on the largest unit the padded window is about 240 M cells. Thresholds are therefore
quantised **down** to a fixed ladder `theta_k = anchor * (1 - step) ** k`, anchored on the region's
`max_distance_m`, and a labelling is computed once per ladder index and cached. Down is the safe direction: a
lower threshold gives a larger superlevel set, hence more connectivity, hence more candidates called "the same
place", so the quantisation can only make the rule stricter, never looser. That makes it part of the rule
rather than an implementation detail, which is why validation shares this module instead of asking the same
question its own way. At `step = 0.01` the error is one percent of the threshold, which is half a percent of
the candidate's distance.

**Memory.** The per-cell state is one `uint16` array, `level`, holding `ladder_index(distance)` for land cells
and `NO_LEVEL` for everything else, so the mask at ladder index `k` is `level <= k` and no separate land array
is retained: 480 MB at 240 M cells, against 960 MB as float32 plus 240 MB of land mask. A labelling costs an
int32 array of the window on top while it is cached, and the `scipy.ndimage.label` call itself sees only the
mask's bounding box, which is what keeps a high threshold cheap on a continental window.

One rung of that `uint16` is spent on the difference between "not land" and "land the ladder cannot name":
a cell a road crosses has distance 0, which belongs to no superlevel set (it is the low ground that separates
areas) and yet is land. Folding the two into one sentinel would cut every mainland into pieces along its own
roads and the island floor would then reject the mainland, so land below the ladder carries `BELOW_LADDER`:
never in a superlevel set, always in its land component.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window
from scipy.ndimage import label as _label

from .errors import PolesError
from .grid import Frame

LADDER_STEP = 0.01          # the threshold ladder's relative step; part of the rule, see the module docstring
NO_LEVEL = 65535            # uint16 sentinel: this cell is not land, so it is in nothing at all
BELOW_LADDER = NO_LEVEL - 1  # land whose distance is below every rung: in no superlevel set, in its component
_STRUCTURE = np.ones((3, 3), dtype=bool)   # 8-connectivity: a diagonal step is a walk on the ground
_READ_ROWS = 512            # one strip of the window per raster read, so no float32 window is ever whole


class AreasError(PolesError):
    """A cell addressed outside the window it was read for. The message names both."""


def ladder_index(distance_m, anchor_m: float, step: float = LADDER_STEP):
    """The rung at or below `distance_m`: the smallest k with `anchor * (1 - step) ** k <= distance`.

    Scalar in, scalar out; array in, uint16 array out. A distance of zero or less gets `NO_LEVEL`: the ladder
    cannot name it, and it is the low ground that separates areas, so it belongs to no superlevel set, which
    is the answer the rule wants. A field turns that into `BELOW_LADDER` where the cell is land. Anything at
    or above the anchor gets rung 0.
    """
    scalar = np.isscalar(distance_m) or np.asarray(distance_m).ndim == 0
    d = np.asarray(distance_m, dtype="float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = np.ceil(np.log(d / anchor_m) / math.log(1.0 - step))
    out = np.where(np.isfinite(raw), np.clip(raw, 0, BELOW_LADDER), NO_LEVEL)
    out = np.where(d > 0, out, NO_LEVEL).astype("uint16")
    return int(out) if scalar else out


def ladder_value(index: int, anchor_m: float, step: float = LADDER_STEP) -> float:
    """The threshold rung `index` stands for: `anchor * (1 - step) ** index`."""
    return float(anchor_m) * (1.0 - step) ** int(index)


def col_threshold(d_a: float, d_b: float, fraction: float) -> float:
    """The col two poles must clear to count as two places: `fraction * min(d_a, d_b)`."""
    return fraction * min(float(d_a), float(d_b))


@dataclass(frozen=True)
class LandComponents:
    labels: np.ndarray            # int32 over the window, 0 off land
    area_km2: np.ndarray          # float32 by label, index 0 unused


class AreaField:
    """One window of one scenario's coarse grid, land-masked, with cached superlevel labellings.

    Rows and columns are frame indices throughout, the same ones the unit raster and the poles stage use;
    `rowcol` is the only place the window offset appears.
    """

    def __init__(self, level: np.ndarray, res_m: float, row_off: int, col_off: int, anchor_m: float,
                 step: float = LADDER_STEP):
        self.level = level
        self.res_m = float(res_m)
        self.row_off, self.col_off = int(row_off), int(col_off)
        self.anchor_m, self.step = float(anchor_m), float(step)
        self._labels: np.ndarray | None = None
        self._labels_k: int | None = None
        self._dead: np.ndarray | None = None
        self._dead_key: tuple[int, int] | None = None
        self._land: LandComponents | None = None

    # ---------- construction ----------

    @classmethod
    def from_arrays(cls, dist, land, res_m: float, row_off: int, col_off: int, anchor_m: float,
                    step: float = LADDER_STEP) -> "AreaField":
        level = ladder_index(np.asarray(dist), anchor_m, step)
        land = np.asarray(land, dtype=bool)
        level[land & (level == NO_LEVEL)] = BELOW_LADDER
        level[~land] = NO_LEVEL
        return cls(level, res_m, row_off, col_off, anchor_m, step)

    @classmethod
    def read(cls, dist_tif: Path, land_tif: Path, water_tif: Path, frame: Frame, window: Window,
             anchor_m: float, step: float = LADDER_STEP) -> "AreaField":
        """The window of the three rasters, as one uint16 level array.

        The land mask is the candidate rule of `units.rasterize_units`: the all-touched land raster is 1 and
        the big-water raster is 0. It is read strip by strip so the float32 distance window is never
        materialised whole; at a continental unit that window alone would be a gigabyte.
        """
        row_off, col_off = int(window.row_off), int(window.col_off)
        height, width = int(window.height), int(window.width)
        level = np.empty((height, width), dtype="uint16")
        with rasterio.open(dist_tif) as dist_ds, rasterio.open(land_tif) as land_ds, \
                rasterio.open(water_tif) as water_ds:
            for r0 in range(0, height, _READ_ROWS):
                rows = min(_READ_ROWS, height - r0)
                strip = Window(col_off=col_off, row_off=row_off + r0, width=width, height=rows)
                block = ladder_index(dist_ds.read(1, window=strip), anchor_m, step)
                keep = (land_ds.read(1, window=strip) > 0) & (water_ds.read(1, window=strip) == 0)
                block[keep & (block == NO_LEVEL)] = BELOW_LADDER
                block[~keep] = NO_LEVEL
                level[r0:r0 + rows] = block
        return cls(level, frame.res, row_off, col_off, anchor_m, step)

    # ---------- addressing ----------

    def rowcol(self, rows, cols) -> tuple[np.ndarray, np.ndarray]:
        """Frame indices to window indices. A point outside the window is an error, not a clamp."""
        wr = np.asarray(rows, dtype=np.int64) - self.row_off
        wc = np.asarray(cols, dtype=np.int64) - self.col_off
        h, w = self.level.shape
        bad = (wr < 0) | (wr >= h) | (wc < 0) | (wc >= w)
        if bad.any():
            i = int(np.argmax(bad))
            r = np.atleast_1d(np.asarray(rows))[i]
            c = np.atleast_1d(np.asarray(cols))[i]
            raise AreasError(f"areas: cell (row {r}, col {c}) is outside the window "
                             f"(rows {self.row_off} to {self.row_off + h - 1}, "
                             f"cols {self.col_off} to {self.col_off + w - 1})")
        return wr, wc

    # ---------- superlevel sets ----------

    def rung(self, threshold_m: float) -> int:
        """The ladder index a threshold is quantised down to: the key of every cached labelling and dead mask.
        A threshold at or below zero means every land cell the ladder can name, never the ground under a road."""
        return min(int(ladder_index(threshold_m, self.anchor_m, self.step)), BELOW_LADDER - 1)

    def labels_at(self, threshold_m: float) -> np.ndarray:
        """The 8-connected components of `{distance >= threshold}` over land, as int32 over the window.

        The threshold is quantised down to its ladder rung and one labelling is cached, keyed by that rung:
        thresholds arrive non-increasing over a search, so a second entry would never be hit. The returned
        array is the cache's own, so a caller that needs two labellings at once must copy one.
        """
        k = self.rung(threshold_m)
        if self._labels_k == k and self._labels is not None:
            return self._labels
        mask = self.level <= k
        labels = np.zeros(self.level.shape, dtype=np.int32)
        rows_any, cols_any = mask.any(axis=1), mask.any(axis=0)
        if rows_any.any():
            # The crop is what keeps a high threshold cheap: the set is a few peaks of a continental window.
            r0, r1 = int(np.argmax(rows_any)), len(rows_any) - int(np.argmax(rows_any[::-1]))
            c0, c1 = int(np.argmax(cols_any)), len(cols_any) - int(np.argmax(cols_any[::-1]))
            labels[r0:r1, c0:c1] = _label(mask[r0:r1, c0:c1], structure=_STRUCTURE)[0]
        self._labels, self._labels_k = labels, k
        return labels

    def component_at(self, row: int, col: int, threshold_m: float) -> int:
        """The label of the cell at this threshold, 0 when it is below it or off land."""
        wr, wc = self.rowcol(row, col)
        return int(self.labels_at(threshold_m)[int(wr), int(wc)])

    def dead_mask(self, component: int, threshold_m: float) -> np.ndarray:
        """True over the window where the cell **and all eight of its neighbours** carry `component`.

        That neighbourhood is what makes the search's pruning lossless: a refined point never leaves its
        cell's eight neighbours, so a point refined from a dead cell lands in a cell of the component and
        would be rejected against it anyway. A cell on the window's edge is never dead, because what lies
        beyond the window was not read. The erosion runs over the component's own bounding box with eight
        shifted ANDs, so its cost is the component's extent and not the number of cells asked about; one
        mask is cached, keyed by rung and component, because the search asks for the same pair once per
        finalised candidate of a plateau and a continental unit finalises hundreds.
        """
        key = (self.rung(threshold_m), int(component))
        if self._dead_key == key and self._dead is not None:
            return self._dead
        member = self.labels_at(threshold_m) == int(component)
        dead = np.zeros(member.shape, dtype=bool)
        rows_any, cols_any = member.any(axis=1), member.any(axis=0)
        if rows_any.any():
            r0, r1 = int(np.argmax(rows_any)), len(rows_any) - int(np.argmax(rows_any[::-1]))
            c0, c1 = int(np.argmax(cols_any)), len(cols_any) - int(np.argmax(cols_any[::-1]))
            m = member[r0:r1, c0:c1]
            h, w = m.shape
            if h >= 3 and w >= 3:
                # The crop's own border stays False: a cell there has a neighbour outside the bounding box,
                # which holds no member by construction, and the window's edge lies at or beyond it.
                core = m[1:h - 1, 1:w - 1].copy()
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if dr or dc:
                            core &= m[1 + dr:h - 1 + dr, 1 + dc:w - 1 + dc]
                dead[r0 + 1:r1 - 1, c0 + 1:c1 - 1] = core
        self._dead, self._dead_key = dead, key
        return dead

    def dead_cells(self, rows, cols, component: int, threshold_m: float) -> np.ndarray:
        """`dead_mask` read at the given frame cells, in their order."""
        wr, wc = self.rowcol(rows, cols)
        return self.dead_mask(component, threshold_m)[wr, wc]

    # ---------- land ----------

    def land_components(self) -> LandComponents:
        """The 8-connected components of the land itself, with an area per label, labelled once and kept."""
        if self._land is None:
            labels, count = _label(self.level != NO_LEVEL, structure=_STRUCTURE)
            counts = np.bincount(labels.ravel(), minlength=count + 1).astype("float64")
            counts[0] = 0.0                                   # index 0 is "off land" and carries no area
            area = (counts * (self.res_m / 1000.0) ** 2).astype("float32")
            self._land = LandComponents(labels.astype(np.int32, copy=False), area)
        return self._land
