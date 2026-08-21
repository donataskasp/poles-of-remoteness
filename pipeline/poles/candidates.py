"""Branch-and-bound over the coarse grid (spec 3.2 stage 5, DECISIONS 2026-08-21 item 4).

Every cell of a unit carries a coarse distance c (cell centre to the nearest road cell centre, projected
metres). Any point of the cell is within half a diagonal of the centre and the nearest road passes within
half a diagonal of the road cell centre, so the true distance of any point in the cell is at most
(c + 2 * hd) * (1 + pad), where pad bounds the projection's scale error at that cell plus a small safety
for UTM and the ellipsoid. Cells are visited in descending c; a refined point is a lower bound on the
unit's maximum. A refined point becomes final once no unvisited cell can beat it; final points are
accepted greedily with the dedup distance; every unvisited cell that lies surely within the dedup
distance of an accepted pole is dominated and skipped. The result equals "refine every cell, sort,
accept greedily", proven on synthetic fields in tests/test_candidates.py.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from pyproj import Proj

from .errors import PolesError

PAD_SAFETY = 0.002


def half_diag(res_m: float) -> float:
    return res_m * math.sqrt(2) / 2


def pad_fn_for(crs: str, safety: float = PAD_SAFETY) -> Callable[[np.ndarray, np.ndarray], np.ndarray]:
    """Max relative length distortion of `crs` at lon/lat points, from Tissot's indicatrix, plus `safety`."""
    proj = Proj(crs)

    def pad(lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
        f = proj.get_factors(np.asarray(lons, dtype=float), np.asarray(lats, dtype=float))
        a = np.asarray(f.tissot_semimajor, dtype=float)
        b = np.asarray(f.tissot_semiminor, dtype=float)
        return np.maximum(np.abs(a - 1.0), np.abs(1.0 - b)) + safety

    return pad


@dataclass
class Refined:
    x: float
    y: float
    dist_m: float
    payload: object = None


@dataclass
class SearchResult:
    accepted: list[Refined]
    refinements: int
    exhausted: bool
    warnings: list[str] = field(default_factory=list)


class Search:
    """Refine the fewest coarse cells that still prove the unit's top_n poles (spec 3.2 stage 5).

    Inputs are one entry per coarse cell of one unit and one scenario: cell centres `xs`, `ys` in the
    frame CRS, the coarse distance `coarse`, and the per-cell projection pad `pads` from `pad_fn_for`.
    They are sorted by `coarse` descending on construction; `.order` maps a sorted index back to the
    caller's index, and `refiner(i)` is called with the sorted index.
    """

    def __init__(self, xs, ys, coarse, pads, res_m: float, top_n: int, refiner: Callable[[int], Refined | None],
                 dedup_m: float = 10_000.0, warn_at: int = 500, fail_at: int = 20_000, log: logging.Logger | None = None):
        order = np.argsort(-np.asarray(coarse, dtype=float), kind="stable")
        self.order = order
        self.xs = np.asarray(xs, dtype=float)[order]
        self.ys = np.asarray(ys, dtype=float)[order]
        self.coarse = np.asarray(coarse, dtype=float)[order]
        self.pads = np.asarray(pads, dtype=float)[order]
        self.hd = half_diag(res_m)
        self.top_n, self.refiner, self.dedup_m = top_n, refiner, dedup_m
        self.warn_at, self.fail_at, self.log = warn_at, fail_at, log
        self.pad_max = float(self.pads.max()) if len(self.pads) else 0.0

    def upper(self, i: int) -> float:
        """Upper bound on the exact distance of any point of cell i.

        Let p be a point of the cell and r the road nearest to p. The cell centre is within hd of p and
        the road cell holding r has its centre within hd of r, so the centre-to-road-cell-centre distance
        that produced coarse[i] is at least |p to r| - 2 * hd on the coarse grid. Both terms are measured
        in the projection, where a length can be short of the true one by at most a factor 1 + pads[i]
        (Tissot plus safety), so the whole sum scales: |p to r| <= (coarse[i] + 2 * hd) * (1 + pads[i]).
        Scaling the half diagonals with the sum, rather than leaving them unscaled, is what makes the
        argument hold for the grid step as well as for the distance (DECISIONS 2026-08-21 item 4).
        """
        return (self.coarse[i] + 2 * self.hd) * (1 + self.pads[i])

    def run(self) -> SearchResult:
        n = len(self.coarse)
        alive = np.ones(n, dtype=bool)
        pending: list[Refined] = []      # refined, not yet final, kept sorted by dist_m descending
        accepted: list[Refined] = []
        refinements = 0
        warnings: list[str] = []
        i = 0

        def finalize(up_to_value: float) -> None:
            """Make final every pending point above up_to_value, greedily accept, mask dominated cells."""
            while pending and pending[0].dist_m > up_to_value and len(accepted) < self.top_n:
                p = pending.pop(0)
                if all(math.hypot(p.x - q.x, p.y - q.y) * (1 + self.pad_max) >= self.dedup_m for q in accepted):
                    accepted.append(p)
                    if self.dedup_m > 0:
                        # A cell is dominated when even its farthest point is surely within dedup_m of p.
                        # The acceptance test above measures a separation as hypot * (1 + pad_max), an upper
                        # bound on the true ground distance; a point of this cell is at most hd beyond the
                        # centre in the projection, so its separation from p measures at most
                        # (d + hd) * (1 + pad_max). Below dedup_m every point of the cell would fail the very
                        # test p just passed, so masking loses no pole; the same pad_max on both sides is what
                        # makes the two exact complements, and a per-cell pad here would mask cells whose
                        # points acceptance would still have taken.
                        d = np.hypot(self.xs - p.x, self.ys - p.y)
                        alive[(d + self.hd) * (1 + self.pad_max) < self.dedup_m] = False

        while i < n and len(accepted) < self.top_n:
            if not alive[i]:
                i += 1
                continue
            # Cells are sorted by coarse descending, so this bounds every cell from i on: nothing still
            # unrefined can beat a pending point above it, and that point is final.
            remaining_upper = (self.coarse[i] + 2 * self.hd) * (1 + self.pad_max)
            finalize(remaining_upper)
            if len(accepted) >= self.top_n or not alive[i]:
                i += 1
                continue
            refined = self.refiner(i)
            refinements += 1
            if refinements == self.warn_at:
                msg = f"{refinements} refinements and counting; the unit has a large plateau near its maximum"
                warnings.append(msg)
                if self.log:
                    self.log.warning(msg)
            if refinements >= self.fail_at:
                raise PolesError(f"candidates: branch-and-bound exceeded {self.fail_at} refinements; "
                                 "the bound is not pruning")
            if refined is not None:
                k = 0
                while k < len(pending) and pending[k].dist_m >= refined.dist_m:
                    k += 1
                pending.insert(k, refined)
            i += 1
        finalize(-math.inf)
        exhausted = len(accepted) < self.top_n
        return SearchResult(accepted, refinements, exhausted, warnings)
