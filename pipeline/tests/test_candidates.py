import logging

import numpy as np
import pytest

from poles.candidates import Refined, Search, half_diag, pad_fn_for
from poles.errors import PolesError


def test_pad_grows_with_distance_from_centre():
    pad = pad_fn_for("EPSG:3035")
    near = pad(np.array([10.0]), np.array([52.0]))[0]
    far = pad(np.array([-10.0]), np.array([35.0]))[0]
    arctic = pad(np.array([30.0]), np.array([75.0]))[0]
    assert 0.002 <= near < 0.003 and near < arctic and near < far
    assert 0.02 < far < 0.04  # about 2,500 km from the centre: 1/cos(c/2) - 1 is about 2%


def test_half_diag():
    assert half_diag(250.0) == pytest.approx(176.7767)


def _truth_field(rng, n=60, roads=25):
    """A synthetic unit: n x n cells of 100 m; roads are random points; the true distance is exact."""
    res = 100.0
    road = rng.uniform(0, n * res, size=(roads, 2))
    def true_dist(px, py):
        return np.sqrt(((px[:, None] - road[None, :, 0]) ** 2 + (py[:, None] - road[None, :, 1]) ** 2).min(axis=1))
    rows, cols = np.mgrid[0:n, 0:n]
    xs, ys = (cols.ravel() + 0.5) * res, (rows.ravel() + 0.5) * res
    # coarse = distance between cell centres after snapping roads to cells, scaled by a fake projection error
    road_cells = (np.floor(road / res) + 0.5) * res
    coarse = np.sqrt(((xs[:, None] - road_cells[None, :, 0]) ** 2 + (ys[:, None] - road_cells[None, :, 1]) ** 2).min(axis=1))
    pads = 0.002 + 0.01 * (xs / (n * res))
    coarse = coarse * (1 + (pads - 0.002) * rng.uniform(-1, 1, size=len(xs)))  # the 0.002 safety covers second-order terms, as in production
    return res, xs, ys, coarse, pads, true_dist


def _exact_refiner(xs, ys, res, true_dist):
    sub = np.linspace(-res / 2 + 1, res / 2 - 1, 25)
    gx, gy = np.meshgrid(sub, sub)
    def refiner(i):
        px, py = xs[i] + gx.ravel(), ys[i] + gy.ravel()
        d = true_dist(px, py)
        k = int(np.argmax(d))
        return Refined(float(px[k]), float(py[k]), float(d[k]), None)
    return refiner


def _search(xs, ys, coarse, pads, res, true_dist, **kw):
    """A Search over an exact refiner. The refiner is called with the sorted index, so it reads the
    search's own sorted centres and is bound after construction, exactly as the poles stage does."""
    search = Search(xs, ys, coarse, pads, res, refiner=lambda i: refine(i), **kw)
    refine = _exact_refiner(search.xs, search.ys, res, true_dist)
    return search


@pytest.mark.parametrize("seed", range(12))
def test_never_prunes_planted_maximum(seed):
    rng = np.random.default_rng(seed)
    res, xs, ys, coarse, pads, true_dist = _truth_field(rng)
    # brute force truth: the best refined value over every cell
    refine_all = _exact_refiner(xs, ys, res, true_dist)
    best = max(refine_all(i).dist_m for i in range(len(xs)))
    s = _search(xs, ys, coarse, pads, res, true_dist, top_n=1, dedup_m=0.0)
    r = s.run()
    assert r.accepted[0].dist_m == pytest.approx(best)
    assert r.refinements < len(xs)  # it pruned something


def test_dedup_and_dominance_give_top_n_at_least_dedup_apart():
    rng = np.random.default_rng(3)
    res, xs, ys, coarse, pads, true_dist = _truth_field(rng)
    s = _search(xs, ys, coarse, pads, res, true_dist, top_n=3, dedup_m=800.0)
    r = s.run()
    assert len(r.accepted) == 3
    for a in r.accepted:
        for b in r.accepted:
            if a is not b:
                assert np.hypot(a.x - b.x, a.y - b.y) >= 800.0
    # greedy truth: refine everything, sort, accept under the search's own separation rule, which is
    # the lower bound of the ground distance, hence the map distance divided by the largest pad
    pad_max = pads.max()
    allp = sorted((_exact_refiner(xs, ys, res, true_dist)(i) for i in range(len(xs))), key=lambda p: -p.dist_m)
    greedy = []
    for p in allp:
        if all(np.hypot(p.x - q.x, p.y - q.y) / (1 + pad_max) >= 800.0 for q in greedy):
            greedy.append(p)
        if len(greedy) == 3:
            break
    assert [round(p.dist_m, 6) for p in r.accepted] == [round(p.dist_m, 6) for p in greedy]


def test_exhausted_unit_returns_fewer_poles_with_reason():
    xs = np.array([50.0, 150.0]); ys = np.array([50.0, 50.0])
    coarse = np.array([300.0, 280.0]); pads = np.array([0.002, 0.002])
    refiner = lambda i: Refined(xs[i], ys[i], coarse[i], None)
    r = Search(xs, ys, coarse, pads, 100.0, top_n=5, refiner=refiner, dedup_m=10_000.0).run()
    assert len(r.accepted) == 1 and r.exhausted and r.refinements <= 2


def test_refiner_none_skips_cell_and_warn_threshold_logs(caplog):
    xs = np.arange(10) * 100.0 + 50; ys = np.zeros(10) + 50
    coarse = np.full(10, 1000.0); pads = np.full(10, 0.002)
    calls = []
    def refiner(i):
        calls.append(i)
        return None if i % 2 else Refined(xs[i], ys[i], coarse[i], None)
    log = logging.getLogger("poles.candidates.test")
    with caplog.at_level(logging.WARNING, logger=log.name):
        r = Search(xs, ys, coarse, pads, 100.0, top_n=2, refiner=refiner, dedup_m=150.0, warn_at=3, log=log).run()
    assert len(r.accepted) == 2 and any("refinements" in w for w in r.warnings)
    assert calls == list(range(10))  # every cell was tried, the odd ones just yielded nothing
    assert [p.x for p in r.accepted] == [50.0, 250.0]  # both poles come from even cells
    assert len(r.warnings) == 1  # the threshold warns once per run
    assert [rec.message for rec in caplog.records] == r.warnings


def test_empty_unit_is_exhausted_not_an_error():
    empty = np.array([], dtype=float)
    r = Search(empty, empty, empty, empty, 100.0, top_n=3, refiner=lambda i: None).run()
    assert r.accepted == [] and r.exhausted and r.refinements == 0


def test_all_zero_coarse_still_returns_the_top_n():
    xs = np.array([50.0, 150.0, 250.0, 350.0]); ys = np.zeros(4) + 50
    coarse = np.zeros(4); pads = np.full(4, 0.002)
    r = Search(xs, ys, coarse, pads, 100.0, top_n=2,
               refiner=lambda i: Refined(xs[i], ys[i], float(i), None), dedup_m=150.0).run()
    assert [p.dist_m for p in r.accepted] == [3.0, 1.0] and not r.exhausted


def test_fail_at_raises_rather_than_capping_silently():
    n = 50
    xs = np.arange(n) * 1000.0; ys = np.zeros(n)
    coarse = np.full(n, 1000.0); pads = np.full(n, 0.002)
    s = Search(xs, ys, coarse, pads, 100.0, top_n=1,
               refiner=lambda i: Refined(xs[i], ys[i], 10.0, None), dedup_m=0.0, warn_at=2, fail_at=5)
    with pytest.raises(PolesError, match="5 refinements"):
        s.run()


def test_progress_line_every_5000_refinements(caplog):
    """A long plateau has to say something while it works: one INFO line every 5,000 refinements."""
    n = 5001
    xs = np.arange(n) * 250.0; ys = np.zeros(n)
    coarse = np.full(n, 10_000.0); pads = np.zeros(n)
    # Nothing can be finalised before the end: every refined value stays under (10,000 + 2 * hd) * 1.0.
    # The values rise with i so each one enters the pending list at its front; equal values would walk
    # the whole list on every insert and make this test quadratic for no gain.
    refiner = lambda i: Refined(xs[i], ys[i], 10_000.0 + i * 0.05, None)
    log = logging.getLogger("poles.candidates.progress")
    with caplog.at_level(logging.INFO, logger=log.name):
        r = Search(xs, ys, coarse, pads, 250.0, top_n=1, refiner=refiner, dedup_m=0.0, log=log).run()
    assert r.refinements == n
    progress = [rec.getMessage() for rec in caplog.records if rec.levelno == logging.INFO]
    assert len(progress) == 1 and progress[0].startswith("5000 refinements;")
    assert "accepted 0 of 1" in progress[0] and " m," in progress[0]
    assert [rec.getMessage() for rec in caplog.records if rec.levelno == logging.WARNING] == r.warnings
    assert len(r.warnings) == 1 and r.warnings[0].startswith("500 refinements")


def test_pad_window_pair_is_rejected_because_the_ground_distance_is_not_sure():
    """A pair whose map separation sits inside the pad window is not accepted (map 1000 m, pad 0.01,
    so the ground distance is only sure to be 1000 / 1.01 = 990.1 m)."""
    xs = np.array([0.0, 1000.0]); ys = np.zeros(2)
    coarse = np.array([500.0, 400.0]); pads = np.full(2, 0.01)
    refiner = lambda i: Refined(xs[i], ys[i], coarse[i], None)
    r = Search(xs, ys, coarse, pads, 100.0, top_n=2, refiner=refiner, dedup_m=1000.0).run()
    assert len(r.accepted) == 1 and r.exhausted  # 990.1 < 1000, so the second pole is not sure to be far enough
    r = Search(xs, ys, coarse, pads, 100.0, top_n=2, refiner=refiner, dedup_m=980.0).run()
    assert len(r.accepted) == 2  # 990.1 >= 980, so the same pair passes just below the window


def test_order_maps_back_to_the_callers_index_and_upper_bounds_one_cell():
    xs = np.array([0.0, 10.0, 20.0]); ys = np.zeros(3)
    coarse = np.array([100.0, 300.0, 200.0]); pads = np.array([0.01, 0.02, 0.03])
    s = Search(xs, ys, coarse, pads, 100.0, top_n=1, refiner=lambda i: None)
    assert list(s.order) == [1, 2, 0]
    assert list(s.coarse) == [300.0, 200.0, 100.0] and list(s.xs) == [10.0, 20.0, 0.0]
    assert s.upper(0) == pytest.approx((300.0 + 2 * half_diag(100.0)) * 1.02)


def test_cells_sort_by_their_own_upper_bound_not_by_coarse_value():
    """A far cell with a small pad can bound lower than a nearer cell with a large one."""
    xs = np.array([0.0, 100_000.0]); ys = np.zeros(2)
    coarse = np.array([100_000.0, 99_000.0]); pads = np.array([0.01, 0.05])
    s = Search(xs, ys, coarse, pads, 250.0, top_n=1, refiner=lambda i: None)
    b_upper = (99_000.0 + 2 * half_diag(250.0)) * 1.05          # about 104,322 m
    a_upper = (100_000.0 + 2 * half_diag(250.0)) * 1.01         # about 101,357 m
    assert b_upper > a_upper
    assert list(s.order) == [1, 0] and list(s.coarse) == [99_000.0, 100_000.0]
    assert s.uppers[0] == pytest.approx(b_upper) and s.uppers[1] == pytest.approx(a_upper)
    assert s.upper(0) == pytest.approx(b_upper)


def test_per_cell_bound_prunes_what_the_unit_wide_pad_would_have_refined():
    """P refines to its coarse value and nothing left can beat it, so it is the only refinement.

    Sorted by their own bounds the cells run P (101,357.09), R (99,388.91), Q (99,337.09), so the bound
    at i = 1 is R's, and it already sits below P's 100,000 m: P is final and the search stops before
    either of the other two. Under the unit-wide pad_max (0.10, carried by R) every remaining cell was
    bounded with 1.10, which put Q at about 108,189 m, above P, so the old rule refined Q as well.
    """
    xs = np.array([0.0, 100_000.0, 200_000.0]); ys = np.zeros(3)
    coarse = np.array([100_000.0, 98_000.0, 90_000.0])          # P, Q, R
    pads = np.array([0.01, 0.01, 0.10])
    s = Search(xs, ys, coarse, pads, 250.0, top_n=1, dedup_m=0.0,
               refiner=lambda i: Refined(float(s.xs[i]), float(s.ys[i]), float(s.coarse[i]), None))
    assert s.uppers[1] == pytest.approx((90_000.0 + 2 * half_diag(250.0)) * 1.10)   # R sorts above Q
    assert s.uppers[2] == pytest.approx((98_000.0 + 2 * half_diag(250.0)) * 1.01)
    assert s.uppers[2] < 100_000.0                                                 # Q cannot beat P
    r = s.run()
    assert r.refinements == 1
    assert r.accepted[0].x == 0.0 and r.accepted[0].dist_m == pytest.approx(100_000.0)


def test_mismatched_input_lengths_are_rejected():
    with pytest.raises(ValueError, match="same length"):
        Search(np.zeros(3), np.zeros(3), np.zeros(2), np.zeros(3), 100.0, top_n=1, refiner=lambda i: None)
