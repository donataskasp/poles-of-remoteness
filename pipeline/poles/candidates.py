"""Branch-and-bound over the coarse grid (spec 3.2 stage 5, DECISIONS 2026-08-21 item 4).

Every cell of a unit carries a coarse distance c (cell centre to the nearest road cell centre, projected
metres). Any point of the cell is within half a diagonal of the centre and the nearest road passes within
half a diagonal of the road cell centre, so the true distance of any point in the cell is at most
(c + 2 * hd) * (1 + pad), where pad bounds the projection's scale error at that cell plus a small safety
for UTM and the ellipsoid. Cells are visited in descending order of that bound, which is not the same as
descending c once the pads differ; a refined point is a lower bound on the unit's maximum. A refined point
becomes final once no unvisited cell can beat it.

A final point is accepted when it clears **two** conditions. The floor: it is at least `dedup_m` from every
accepted pole, measured as a lower bound on the ground separation so that an accepted pair survives the exact
geodesic recheck the poles stage runs later. And, when the caller passes a `distinct` callback, the
distinct-area rule: it is not connected to an accepted pole over ground that stays above a fraction of its own
distance to a road (issue #56). The floor is tested first because it is arithmetic while the callback reads a
raster. Every unvisited cell that lies surely within the dedup distance of an accepted pole is dominated and
skipped, and the callback may retire cells of its own through `Verdict.dead`.

That second retirement is what keeps a plateau unit inside its budget, and it is sound for the same reason the
first one is. Candidates are finalised in globally descending distance, so every later candidate carries a
threshold no larger than this one's, and the superlevel sets only grow as the threshold falls: a cell joined to
this candidate's area now is joined to it at every threshold still to come and can never be a new place,
whether this candidate was accepted or refused. `poles.areas` answers the connectivity question and quantises
the threshold **down** onto a fixed ladder, which makes the rule slightly stricter than its exact statement
and never looser.

How many poles the search wants, and which of them it may take at all, is the `Quota`'s to say rather than
a bare `top_n`: `CountQuota` is the plain count and the default, and the poles stage passes one that keeps
going until it holds `top_n` poles on the unit's main landmass while taking the island poles it meets on
the way, up to a cap. A quota's refusal costs nothing and stops nothing, and a quota that has reached a cap
returns the cells it can no longer take so they are retired in one operation.

The result equals "refine every cell, sort, accept greedily under the same rules", checked against a
brute-force model on synthetic fields in tests/test_candidates.py.
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


@dataclass(frozen=True)
class Verdict:
    """What the `distinct` callback answers about one finalised candidate.

    `separate` is whether it is a new place. `dead` is a boolean over the search's own sorted cell order,
    naming cells that can never hold a new place and are retired whatever the verdict was."""

    separate: bool
    dead: np.ndarray | None = None


@dataclass
class Refined:
    x: float
    y: float
    dist_m: float
    payload: object = None
    cell: int = -1               # the sorted index the point was refined from; the search stamps it
    at: tuple[int, int] | None = None   # frame row and column of the refined point itself, for the distinct rule


@dataclass
class SearchResult:
    accepted: list[Refined]
    refinements: int
    exhausted: bool
    warnings: list[str] = field(default_factory=list)


class Quota:
    """How many more poles the search wants, and whether it may take the one in hand.

    `wants_more` is the loop condition, asked before every cell and again after every acceptance; the
    result's `exhausted` is its last answer. `accepts` is asked of a candidate that has already cleared the
    separation floor, and a refusal only means "not this kind of pole": the search runs on and the next
    candidate down may still be taken. `taken` records an accepted pole and may return a boolean over the
    search's own sorted cell order, naming cells the quota can no longer take; they are retired at once,
    which is how a cap on one kind of pole stops the search refining more of that kind for nothing.
    """

    def wants_more(self) -> bool:
        raise NotImplementedError

    def accepts(self, p: Refined) -> bool:
        raise NotImplementedError

    def taken(self, p: Refined) -> np.ndarray | None:
        raise NotImplementedError


class CountQuota(Quota):
    """`top_n` poles, whatever they are: what the search did before there was a quota at all."""

    def __init__(self, top_n: int):
        self.top_n, self.count = int(top_n), 0

    def wants_more(self) -> bool:
        return self.count < self.top_n

    def accepts(self, p: Refined) -> bool:
        return True

    def taken(self, p: Refined) -> np.ndarray | None:
        self.count += 1
        return None


class Search:
    """Refine the fewest coarse cells that still prove the unit's top_n poles (spec 3.2 stage 5).

    Inputs are one entry per coarse cell of one unit and one scenario: cell centres `xs`, `ys` in the
    frame CRS, the coarse distance `coarse`, and the per-cell projection pad `pads` from `pad_fn_for`.
    They are sorted by each cell's own upper bound `upper()` descending on construction, so that bound
    at index i is the largest of every cell from i on; `.order` maps a sorted index back to the caller's
    index, and `refiner(i)` is called with the sorted index.

    `quota` decides how many poles the search wants and which of them it may take; without one it is
    `CountQuota(top_n)`, which is the plain "the first top_n" rule. It may also be replaced after
    construction and before `run()`, which is what a quota that reads the sorted cell order needs: the
    sort happens here, and `Refined.cell` is an index into it.
    """

    def __init__(self, xs, ys, coarse, pads, res_m: float, top_n: int, refiner: Callable[[int], Refined | None],
                 dedup_m: float = 10_000.0, distinct: Callable[[Refined, list[Refined]], Verdict] | None = None,
                 quota: Quota | None = None,
                 warn_at: int = 500, fail_at: int = 200_000, log: logging.Logger | None = None):
        xs, ys, coarse, pads = (np.asarray(a, dtype=float) for a in (xs, ys, coarse, pads))
        if len({xs.size, ys.size, coarse.size, pads.size}) != 1:
            raise ValueError("candidates: xs, ys, coarse and pads must have the same length, got "
                             f"{xs.size}, {ys.size}, {coarse.size}, {pads.size}")
        self.hd = half_diag(res_m)
        # Sorted by each cell's own bound, not by its coarse value: a far cell with a small pad can bound
        # lower than a nearer cell with a large one, and only this order makes uppers[i] the maximum of
        # the rest. On a frame spanning 23 degrees of latitude the pads run 10 to 1 across one unit.
        # The assumption: the cell's own distortion plus PAD_SAFETY covers the whole path, although the
        # coarse value is a planar path to a road that may lie far away where the frame distorts
        # differently (the unit-wide pad_max this replaced assumed the same for roads outside the unit).
        # The backstop is validation, which re-measures every published pole geodesically: check 1 against
        # the road geometry and check 4 against a half-shifted grid, so a pad too small for a long path
        # fails there rather than passing quietly.
        uppers = (coarse + 2 * self.hd) * (1 + pads)
        order = np.argsort(-uppers, kind="stable")
        self.order = order
        self.xs, self.ys, self.coarse, self.pads = xs[order], ys[order], coarse[order], pads[order]
        self.uppers = uppers[order]
        self.top_n, self.refiner, self.dedup_m, self.distinct = top_n, refiner, dedup_m, distinct
        self.quota = CountQuota(top_n) if quota is None else quota
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
            while pending and pending[0].dist_m > up_to_value and self.quota.wants_more():
                p = pending.pop(0)
                if not all(math.hypot(p.x - q.x, p.y - q.y) / (1 + self.pad_max) >= self.dedup_m for q in accepted):
                    continue          # the floor is arithmetic and the callback reads a raster: fail cheap first
                if not self.quota.accepts(p):
                    # Also arithmetic, and a pole the quota refuses changes nothing: it is not this
                    # candidate's place that is spoken for, only its kind, so nothing is retired for it
                    # and the raster is not read. The quota's own `taken` is what retires that kind.
                    continue
                if self.distinct is not None:
                    verdict = self.distinct(p, accepted)
                    # Whatever the verdict: candidates are finalised in globally descending distance, so a
                    # cell joined to this one now is joined to every later candidate too, and can be no new
                    # place either way. Rejected, it is the same place as whatever p was rejected against.
                    if verdict.dead is not None:
                        alive[verdict.dead] = False
                    if not verdict.separate:
                        continue
                accepted.append(p)
                retired = self.quota.taken(p)
                if retired is not None:
                    alive[retired] = False
                if self.dedup_m > 0:
                    # A cell is dominated when even its farthest point is surely within dedup_m of p.
                    # The acceptance test above measures a separation as hypot / (1 + pad_max), a lower
                    # bound on the true ground distance, so an accepted pair survives the exact geodesic
                    # recheck downstream. A point of this cell is at most hd beyond the centre in the
                    # projection, so its separation from p measures at most (d + hd) / (1 + pad_max).
                    # Below dedup_m every point of the cell would fail the very test p just passed, so
                    # masking loses no pole; the same pad_max on both sides is what makes the two exact
                    # complements, and a per-cell pad here would mask cells acceptance would still take.
                    # The floor stays a necessary condition under the distinct-area rule, so this mask is
                    # as sound as it was and retires no cell the rule would have taken.
                    d = np.hypot(self.xs - p.x, self.ys - p.y)
                    alive[(d + self.hd) / (1 + self.pad_max) < self.dedup_m] = False

        while i < n and self.quota.wants_more():
            if not alive[i]:
                i += 1
                continue
            # Cells are sorted by their own upper bound descending, so uppers[i] is the largest bound any
            # cell from i on can have: nothing still unrefined can beat a pending point above it, and that
            # point is final. `pad_max` belongs to the separations below, never to a bound.
            remaining_upper = self.uppers[i]
            finalize(remaining_upper)
            if not self.quota.wants_more() or not alive[i]:
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
                # The search is the only thing that knows which sorted index it handed the refiner, and the
                # distinct callback needs the candidate's cell to ask about its component. Stamped here so
                # every refiner gets it, rather than asked of each one.
                refined.cell = i
                k = 0
                while k < len(pending) and pending[k].dist_m >= refined.dist_m:
                    k += 1
                pending.insert(k, refined)
            i += 1
        finalize(-math.inf)
        return SearchResult(accepted, refinements, self.quota.wants_more(), warn_msgs)
