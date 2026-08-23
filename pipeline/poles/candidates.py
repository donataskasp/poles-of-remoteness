"""Branch-and-bound over the coarse grid (spec 3.2 stage 5, DECISIONS 2026-08-21 item 4).

Every cell of a unit carries a coarse distance c (cell centre to the nearest road cell centre, projected
metres). Any point of the cell is within half a diagonal of the centre and the nearest road passes within
half a diagonal of the road cell centre, so the true distance of any point in the cell is at most
(c + 2 * hd) * (1 + pad), where pad bounds the projection's scale error at that cell plus a small safety
for UTM and the ellipsoid. Cells are visited in descending order of that bound, which is not the same as
descending c once the pads differ; a refined point is a lower bound on the unit's maximum. A refined point
becomes final once no unvisited cell can beat it; final points are accepted greedily with the dedup distance,
measured as a lower bound on the ground separation so that an accepted pair survives the exact geodesic
recheck the poles stage runs later; every unvisited cell that lies surely within the dedup distance of an
accepted pole is dominated and skipped. The result equals "refine every cell, sort, accept greedily under
the same separation rule", checked against a brute-force model on synthetic fields in
tests/test_candidates.py.
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
    """Relative length distortion of `crs` at lon/lat points, from Tissot's indicatrix, plus `safety`.

    The Tissot semiaxes a and b are map over ground scale factors, so a map length m covers a ground
    length between m / a and m / b. Both directions are needed: `upper()` wants m * (1 + pad) >= m / b,
    hence pad >= 1 / b - 1, and the dedup test wants m / (1 + pad) <= m / a, hence pad >= a - 1. On an
    equal-area frame (a * b = 1) the two forms agree, which is why the plan's 1 - b reads the same
    there, but on a conformal frame such as UTM only 1 / b - 1 carries the upper direction.
    """
    proj = Proj(crs)

    def pad(lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
        f = proj.get_factors(np.asarray(lons, dtype=float), np.asarray(lats, dtype=float))
        a = np.asarray(f.tissot_semimajor, dtype=float)
        b = np.asarray(f.tissot_semiminor, dtype=float)
        return np.maximum(a - 1.0, 1.0 / b - 1.0) + safety

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
    They are sorted by each cell's own upper bound `upper()` descending on construction, so that bound
    at index i is the largest of every cell from i on; `.order` maps a sorted index back to the caller's
    index, and `refiner(i)` is called with the sorted index.
    """

    def __init__(self, xs, ys, coarse, pads, res_m: float, top_n: int, refiner: Callable[[int], Refined | None],
                 dedup_m: float = 10_000.0, warn_at: int = 500, fail_at: int = 200_000, log: logging.Logger | None = None):
        xs, ys, coarse, pads = (np.asarray(a, dtype=float) for a in (xs, ys, coarse, pads))
        if len({xs.size, ys.size, coarse.size, pads.size}) != 1:
            raise ValueError("candidates: xs, ys, coarse and pads must have the same length, got "
                             f"{xs.size}, {ys.size}, {coarse.size}, {pads.size}")
        self.hd = half_diag(res_m)
        # Sorted by each cell's own bound, not by its coarse value: a far cell with a small pad can bound
        # lower than a nearer cell with a large one, and only this order makes uppers[i] the maximum of
        # the rest. On a frame spanning 23 degrees of latitude the pads run 10 to 1 across one unit.
        uppers = (coarse + 2 * self.hd) * (1 + pads)
        order = np.argsort(-uppers, kind="stable")
        self.order = order
        self.xs, self.ys, self.coarse, self.pads = xs[order], ys[order], coarse[order], pads[order]
        self.uppers = uppers[order]
        self.top_n, self.refiner, self.dedup_m = top_n, refiner, dedup_m
        self.warn_at, self.fail_at, self.log = warn_at, fail_at, log
        self.pad_max = float(self.pads.max()) if self.pads.size else 0.0

    def upper(self, i: int) -> float:
        """Upper bound on the exact ground distance of any point of cell i.

        Let p be a point of the cell and cR the centre of the road cell nearest the cell centre. That
        road cell holds a road point r*, so the exact distance obeys |p to r*| <= |p to cR| + hd <=
        |centre to cR| + 2 * hd, and |centre to cR| is what the coarse grid stored. Every term is a map
        length, covering at most 1 + pads[i] ground metres (Tissot plus safety), so the whole sum
        scales: |p to r*| <= (coarse[i] + 2 * hd) * (1 + pads[i]). Scaling the half diagonals with the
        sum, rather than leaving them unscaled, is what makes the argument hold for the grid step as
        well as for the distance (DECISIONS 2026-08-21 item 4). The pad is sampled at the cell centre
        while the ray spans up to coarse + 2 * hd, so the scale varies along it; the 0.002 safety covers
        that gradient too, which on a LAEA frame 2,500 km from the centre is about 3e-4 over 20 km.
        """
        return self.uppers[i]

    def run(self) -> SearchResult:
        n = len(self.coarse)
        alive = np.ones(n, dtype=bool)
        pending: list[Refined] = []      # refined, not yet final, kept sorted by dist_m descending
        accepted: list[Refined] = []
        refinements = 0
        warn_msgs: list[str] = []
        i = 0

        def finalize(up_to_value: float) -> None:
            """Make final every pending point above up_to_value, greedily accept, mask dominated cells."""
            while pending and pending[0].dist_m > up_to_value and len(accepted) < self.top_n:
                p = pending.pop(0)
                if all(math.hypot(p.x - q.x, p.y - q.y) / (1 + self.pad_max) >= self.dedup_m for q in accepted):
                    accepted.append(p)
                    if self.dedup_m > 0:
                        # A cell is dominated when even its farthest point is surely within dedup_m of p.
                        # The acceptance test above measures a separation as hypot / (1 + pad_max), a lower
                        # bound on the true ground distance, so an accepted pair survives the exact geodesic
                        # recheck downstream. A point of this cell is at most hd beyond the centre in the
                        # projection, so its separation from p measures at most (d + hd) / (1 + pad_max).
                        # Below dedup_m every point of the cell would fail the very test p just passed, so
                        # masking loses no pole; the same pad_max on both sides is what makes the two exact
                        # complements, and a per-cell pad here would mask cells acceptance would still take.
                        d = np.hypot(self.xs - p.x, self.ys - p.y)
                        alive[(d + self.hd) / (1 + self.pad_max) < self.dedup_m] = False

        while i < n and len(accepted) < self.top_n:
            if not alive[i]:
                i += 1
                continue
            # Cells are sorted by their own upper bound descending, so uppers[i] is the largest bound any
            # cell from i on can have: nothing still unrefined can beat a pending point above it, and that
            # point is final. `pad_max` belongs to the separations below, never to a bound.
            remaining_upper = self.uppers[i]
            finalize(remaining_upper)
            if len(accepted) >= self.top_n or not alive[i]:
                i += 1
                continue
            refined = self.refiner(i)
            refinements += 1
            if refinements == self.warn_at:
                msg = f"{refinements} refinements and counting; the unit has a large plateau near its maximum"
                warn_msgs.append(msg)
                if self.log:
                    self.log.warning(msg)
            if self.log and refinements % 5000 == 0:
                self.log.info("%d refinements; accepted %d of %d, best pending %s m, bound on the rest %s m",
                              refinements, len(accepted), self.top_n,
                              f"{pending[0].dist_m if pending else 0:,.0f}", f"{remaining_upper:,.0f}")
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
        return SearchResult(accepted, refinements, exhausted, warn_msgs)
