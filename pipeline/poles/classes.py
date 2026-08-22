"""Distance class table shared by the explore tiles, the detail rasters and the site (spec 3.4).

Class c covers [edges[c], edges[c+1]) metres; the last real class, 253, is open-ended. Two reserved values
sit above the real classes: EDGE for cells whose distance is only a lower bound because the data ends within
edge_mask_m of them, NODATA for water and everything outside the region's data. site/js/classes.js mirrors
this file; tests/test_classes.py compares the two."""
from __future__ import annotations

import math

import numpy as np

EDGE = 254
NODATA = 255
N_CLASSES = 254  # real classes 0..253


def default_edges() -> list[int]:
    edges = list(range(0, 2_500, 50))                # 50 m steps to 2.5 km: classes 0..49
    edges += list(range(2_500, 10_000, 100))         # 100 m steps to 10 km: classes 50..124
    edges += list(range(10_000, 30_000, 250))        # 250 m steps to 30 km: classes 125..204
    edges += list(range(30_000, 60_000, 1_000))      # 1 km steps to 60 km: classes 205..234
    edges += list(range(60_000, 240_000, 10_000))    # 10 km steps to 240 km: classes 235..252
    edges.append(240_000)                            # class 253: 240 km and beyond
    return edges


class ClassTable:
    def __init__(self, edges: list[int] | None = None):
        e = [int(v) for v in (edges if edges is not None else default_edges())]
        if len(e) != N_CLASSES:
            raise ValueError(f"class table needs {N_CLASSES} lower edges, got {len(e)}")
        if e[0] != 0 or any(b <= a for a, b in zip(e, e[1:])):
            raise ValueError("class edges must start at 0 and increase strictly")
        self.edges = e
        self._arr = np.asarray(e, dtype=np.float64)

    def to_class(self, dist_m) -> np.ndarray:
        """Class of each distance in metres, as uint8.

        Feed a block or a window, not a whole continental grid: this allocates arrays the size of its input,
        and the publish stage windows its rasters for exactly that reason."""
        d = np.asarray(dist_m)
        if d.dtype.kind != "f":  # already floating point stays as it is; ints and bools need a float view
            d = d.astype(np.float64)
        if not np.all(np.isfinite(d)) or np.any(d < 0):
            raise ValueError("distances must be finite and non-negative")
        return (np.searchsorted(self._arr, d, side="right") - 1).astype(np.uint8)

    def _check(self, c: int) -> int:
        if not 0 <= c < len(self.edges):
            raise ValueError(f"class {c} is outside 0..{len(self.edges) - 1}")
        return c

    def lower(self, c: int) -> int:
        return self.edges[self._check(c)]

    def upper(self, c: int) -> float:
        c = self._check(c)
        return float(self.edges[c + 1]) if c + 1 < len(self.edges) else math.inf

    def mid(self, c: int) -> float:
        hi = self.upper(c)
        return (self.lower(c) + hi) / 2 if hi != math.inf else float(self.lower(c))
