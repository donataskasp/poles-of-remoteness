"""Validation checks 1 to 7 (spec 6). Each returns CheckResults; the stage decides what blocks.

Every check re-derives its answer from the published JSON and the stage inputs, never from anything the
poles stage kept in memory, so a bug in the search cannot hide itself here. Check 1 in particular shares
no projection, no raster and no nearest-neighbour index with the search: it densifies the road geometry
in lon/lat and measures on the WGS84 ellipsoid with pyproj's Geod.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import rasterio
import shapely
import yaml
from pyogrio.raw import read
from pyproj import Geod, Transformer
from rasterio.windows import Window
from shapely.geometry.base import BaseGeometry

from ..classify import SET_A, SET_B
from ..config import RegionConfig
from ..errors import PolesError
from ..grid import Frame
from ..poles import DEDUP_M, validate_poles_json
from ..units import Unit

GEOD = Geod(ellps="WGS84")
DEG_PER_M = 1.0 / 111_320.0
INNER_KM, OUTER_KM = 10.0, 30.0
# attrib.pole_record publishes lat/lon rounded to 6 decimals, about 11 cm, so a pole the search
# refined onto a shoreline or a national border can be published a few centimetres outside the
# polygon it came from. Check 2 therefore asks "inside to within the publication rounding".
COORD_ROUND_DEG = 1e-6
SETS = {"A": SET_A, "B": SET_B}
# Check 6 tolerances: a regression entry is the same pole recomputed, an external entry is somebody
# else's definition of the same question, so it is only asked to land in the same place.
REF_MOVE_M, REF_REL = 500.0, 0.01
EXTERNAL_MOVE_M, EXTERNAL_REL = 5000.0, 0.2


class ChecksError(PolesError):
    """A check cannot answer its question: the inputs disagree with the poles it was handed."""


@dataclass
class CheckResult:
    check: str
    unit: str
    scenario: str
    passed: bool
    blocking: bool
    details: dict

    def to_dict(self) -> dict:
        return asdict(self)


def _iter(poles: dict[str, list[dict]]):
    for scenario, entries in poles.items():
        for entry in entries:
            for p in entry["poles"]:
                yield scenario, entry["unit"], p


def _bbox(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    dlat = radius_m * DEG_PER_M
    dlon = dlat / max(0.05, np.cos(np.radians(lat)))
    return lon - dlon, lat - dlat, lon + dlon, lat + dlat


def _nearest(lon: float, lat: float, coords: np.ndarray) -> float:
    """Smallest geodesic distance from lon/lat to the given lon/lat coordinates, or inf for none."""
    if not len(coords):
        return np.inf
    _, _, d = GEOD.inv(np.full(len(coords), lon), np.full(len(coords), lat), coords[:, 0], coords[:, 1])
    return float(d.min())


def _densify(geoms: np.ndarray, segment_m: float) -> np.ndarray:
    """Vertices of `geoms` with no gap longer than segment_m. The step is in degrees of latitude, so an
    east-west run at a high latitude only ever comes out finer than asked for."""
    return shapely.get_coordinates(shapely.segmentize(geoms, segment_m * DEG_PER_M))


def _coord_batches(geoms, segment_m: float, budget: int):
    """Densified coordinates of `geoms` in arrays of at most `budget` points.

    The budget is on vertices, not on geometries: one continent-scale bbox of roads densified at 1 m is tens
    of millions of points, and a single motorway can carry more of them than a thousand field tracks. Geodesic
    length in degrees over the step in degrees estimates a geometry's densified size, which groups the small
    ones; a geometry that busts the budget on its own is then sliced after densifying, so the array handed to
    one Geod.inv call is bounded whatever the ways look like."""
    if not len(geoms):
        return
    step = segment_m * DEG_PER_M
    sizes = shapely.length(geoms) / step + shapely.get_num_coordinates(geoms)
    start = 0
    while start < len(geoms):
        end, total = start + 1, sizes[start]
        while end < len(geoms) and total + sizes[end] <= budget:
            total += sizes[end]
            end += 1
        coords = _densify(geoms[start:end], segment_m)
        for at in range(0, max(len(coords), 1), budget):
            if len(coords):
                yield coords[at:at + budget]
        start = end


def _geodesic_min(lon: float, lat: float, geoms, segment_m: float, budget: int = 2_000_000) -> tuple[float, int]:
    """(distance, vertices measured), never holding more than `budget` densified points at once."""
    best, vertices = np.inf, 0
    for coords in _coord_batches(geoms, segment_m, budget):
        vertices += len(coords)
        best = min(best, _nearest(lon, lat, coords))
    return best, vertices


def recheck(poles, tiles, tolerance: float = 0.005, log: logging.Logger | None = None) -> list[CheckResult]:
    """Check 1: geodesic distance on the WGS84 ellipsoid to road vertices densified at 1 m, against every way of
    the scenario within twice the claimed distance, drawn from the highways tiles (all tags) and re-filtered here."""
    out = []
    for scenario, unit, p in _iter(poles):
        rs = tiles.query(*_bbox(p["lat"], p["lon"], 2 * p["dist_m"]))
        keep = np.array([h in SETS[scenario] for h in rs.attrs["highway"]], dtype=bool) if len(rs) else np.zeros(0, bool)
        geoms = rs.geoms[keep]
        d, vertices = _geodesic_min(p["lon"], p["lat"], geoms, 1.0)
        rel = abs(d - p["dist_m"]) / p["dist_m"] if p["dist_m"] > 0 else (0.0 if d == 0 else np.inf)
        passed = bool(np.isfinite(d) and rel <= tolerance)
        if log:
            log.info("recheck %s %s #%d: claimed %.1f m, geodesic %.1f m (%.3f%%), %d ways, %d vertices", unit,
                     scenario, p["rank"], p["dist_m"], d, rel * 100, len(geoms), vertices)
        out.append(CheckResult("recheck", unit, scenario, passed, True,
                               {"rank": p["rank"], "claimed_m": p["dist_m"],
                                "geodesic_m": round(d, 2) if np.isfinite(d) else None,
                                "relative_error": round(rel, 6) if np.isfinite(rel) else None,
                                "ways": int(len(geoms)), "vertices": vertices}))
    return out


def membership(poles, units: list[Unit], land_idx: Path, water_big: Path) -> list[CheckResult]:
    """Check 2: inside the unit polygon, on a land polygon, in no water polygon of 1 km2 or more.

    Inside is measured to within COORD_ROUND_DEG, the quantum the poles stage rounds its output to."""
    by_code = {u.code: u.geometry for u in units}
    pad = 10 * COORD_ROUND_DEG                 # read wider than the tolerance, or the filter hides the polygon
    out = []
    for scenario, unit, p in _iter(poles):
        pt = shapely.Point(p["lon"], p["lat"])
        tiny = (p["lon"] - pad, p["lat"] - pad, p["lon"] + pad, p["lat"] + pad)
        _, _, lwkb, _ = read(str(land_idx), layer="land", bbox=tiny)
        _, _, wwkb, _ = read(str(water_big), layer="water", bbox=tiny)
        in_unit = bool(shapely.dwithin(by_code[unit], pt, COORD_ROUND_DEG))
        on_land = bool(np.any(shapely.dwithin(shapely.from_wkb(lwkb), pt, COORD_ROUND_DEG))) if len(lwkb) else False
        # water is the disqualifying side, so it stays strict: rounding must not put a pole in a lake
        in_water = bool(np.any(shapely.contains(shapely.from_wkb(wwkb), pt))) if len(wwkb) else False
        out.append(CheckResult("membership", unit, scenario, in_unit and on_land and not in_water, True,
                               {"rank": p["rank"], "in_unit": in_unit, "on_land": on_land, "in_water": in_water}))
    return out


def edge_bound(poles, edge: BaseGeometry, segment_m: float = 100.0) -> list[CheckResult]:
    """Check 3: the pole must be farther from the data edge than its claimed distance.

    The edge is one polygon for the whole run, so it is densified once here rather than once per pole."""
    boundary = edge.boundary
    parts = np.array(list(boundary.geoms) if hasattr(boundary, "geoms") else [boundary], dtype=object)
    coords = _densify(parts, segment_m)
    out = []
    for scenario, unit, p in _iter(poles):
        d = _nearest(p["lon"], p["lat"], coords)
        out.append(CheckResult("edge_bound", unit, scenario, bool(d > p["dist_m"]), True,
                               {"rank": p["rank"], "claimed_m": p["dist_m"], "edge_m": round(d, 1)}))
    return out


def grid_shift_compare(unit: str, scenario: str, original: dict, shifted: dict | None,
                       move_m: float = 500.0, rel: float = 0.01) -> CheckResult:
    """Check 4: the winner recomputed on a half-cell shifted grid must stay within move_m and rel."""
    if shifted is None:
        return CheckResult("grid_shift", unit, scenario, False, True,
                           {"rank": original["rank"], "reason": "no pole on the shifted grid"})
    moved = GEOD.inv(original["lon"], original["lat"], shifted["lon"], shifted["lat"])[2]
    change = abs(shifted["dist_m"] - original["dist_m"]) / original["dist_m"] if original["dist_m"] else 0.0
    return CheckResult("grid_shift", unit, scenario, bool(moved <= move_m and change <= rel), True,
                       {"rank": original["rank"], "moved_m": round(moved, 1), "relative_change": round(change, 6),
                        "original_m": original["dist_m"], "shifted_m": shifted["dist_m"]})


def _ring_density(mask: np.ndarray, row: int, col: int, r_in_cells: float, r_out_cells: float) -> float:
    """Fraction of road cells in the annulus (r_in_cells, r_out_cells] around row/col, clipped to the raster."""
    r = int(np.ceil(r_out_cells))
    r0, r1 = max(0, row - r), min(mask.shape[0], row + r + 1)
    c0, c1 = max(0, col - r), min(mask.shape[1], col + r + 1)
    rr, cc = np.mgrid[r0:r1, c0:c1]
    d = np.hypot(rr - row, cc - col)
    ring = (d > r_in_cells) & (d <= r_out_cells)
    n = int(ring.sum())
    return float(mask[r0:r1, c0:c1][ring].sum()) / n if n else 0.0


def _ring_window(ds, row: int, col: int, radius: int) -> tuple[np.ndarray, int, int]:
    """The (2 * radius + 1) box of `ds` around row/col as a bool array, plus row/col inside that box.

    Clipped to the raster, which is what `_ring_density` would do to a full array anyway, so the densities
    come out identical to reading the whole thing. Hand the three straight to `_ring_density`."""
    r0, r1 = max(0, row - radius), min(ds.height, row + radius + 1)
    c0, c1 = max(0, col - radius), min(ds.width, col + radius + 1)
    if r1 <= r0 or c1 <= c0:
        return np.zeros((0, 0), dtype=bool), 0, 0
    return ds.read(1, window=Window(c0, r0, c1 - c0, r1 - r0)).astype(bool), row - r0, col - c0


def _sample_unit_cells(units_tif: Path, indices: set[int], n: int,
                       rng: np.random.Generator) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    """Up to n cells of each wanted unit index, block by block, in whole-raster coordinates.

    The unit raster is 1.35 GB at a continent-sized frame and the median only needs a sample of each unit,
    so the raster is never held whole: every cell gets a random key and the n smallest keys survive, which
    is a uniform sample without replacement whatever order the blocks arrive in."""
    keep = {i: (np.empty(0), np.empty(0, np.int64), np.empty(0, np.int64)) for i in indices}
    if not indices:
        return {}
    with rasterio.open(units_tif) as ds:
        wanted = np.array(sorted(indices), dtype=np.int64)
        for _, win in ds.block_windows(1):
            block = ds.read(1, window=win)
            present = np.intersect1d(np.unique(block[block > 0]).astype(np.int64), wanted)
            for idx in present.tolist():
                rows, cols = np.nonzero(block == idx)
                keys, r, c = keep[idx]
                keys = np.concatenate([keys, rng.random(len(rows))])
                r = np.concatenate([r, rows.astype(np.int64) + int(win.row_off)])
                c = np.concatenate([c, cols.astype(np.int64) + int(win.col_off)])
                if len(keys) > n:
                    pick = np.argpartition(keys, n)[:n]
                    keys, r, c = keys[pick], r[pick], c[pick]
                keep[idx] = (keys, r, c)
    return {i: (r, c) for i, (_, r, c) in keep.items()}


def holes(poles, road_masks: dict[str, Path], units_tif: Path, frame: Frame, units: list[Unit],
          top: int = 3, seed: int = 0, samples: int = 200) -> list[CheckResult]:
    """Check 5: an empty 0-10 km ring with a 10-30 km ring denser than the unit's median is a probable import gap.

    The unit median comes from `samples` cells of the unit drawn with a fixed seed, so a rerun over the same
    rasters flags the same candidates. Every raster read here is a window of the 30 km radius the rings need
    (or one block of the unit raster while sampling): at a continent-sized frame a full read would be
    hundreds of millions of cells."""
    to_frame = Transformer.from_crs("EPSG:4326", frame.crs, always_xy=True)
    inner, outer = INNER_KM * 1000 / frame.res, OUTER_KM * 1000 / frame.res
    radius = int(np.ceil(outer)) + 1
    by_code = {u.code: u for u in units}
    wanted: dict[str, int] = {}
    for scenario, entries in poles.items():
        for entry in entries:
            if not entry["poles"]:
                continue
            if entry["unit"] not in by_code:
                raise ChecksError(f"unit {entry['unit']!r} has poles in scenario {scenario} but is not in the units list")
            wanted[entry["unit"]] = by_code[entry["unit"]].index
    # One pass over the unit raster for every unit at once, and the same sample in both scenarios.
    sampled = _sample_unit_cells(units_tif, set(wanted.values()), samples, np.random.default_rng(seed))
    out = []
    for scenario, mask_path in road_masks.items():
        with rasterio.open(mask_path) as ds:
            medians: dict[str, float] = {}
            for unit, index in wanted.items():
                rows, cols = sampled.get(index, (np.empty(0, np.int64), np.empty(0, np.int64)))
                densities = [_ring_density(*_ring_window(ds, int(r), int(c), radius), inner, outer)
                             for r, c in zip(rows, cols)]
                medians[unit] = float(np.median(densities)) if densities else 0.0
            for entry in poles.get(scenario, []):
                unit = entry["unit"]
                for p in entry["poles"][:top]:
                    x, y = to_frame.transform(p["lon"], p["lat"])
                    row, col = int((frame.y1 - y) // frame.res), int((x - frame.x0) // frame.res)
                    if not (0 <= row < ds.height and 0 <= col < ds.width):
                        raise ChecksError(f"{unit} {scenario} #{p['rank']} at {p['lat']}, {p['lon']} falls outside "
                                          f"the grid frame at row {row}, col {col}; an empty window would read as "
                                          f"an empty inner ring and flag a hole that is really a bad coordinate")
                    win = _ring_window(ds, row, col, radius)
                    inner_d = _ring_density(*win, -1, inner)
                    outer_d = _ring_density(*win, inner, outer)
                    flagged = inner_d == 0 and outer_d > medians[unit]
                    out.append(CheckResult("holes", unit, scenario, not flagged, False,
                                           {"rank": p["rank"], "inner_density": inner_d, "outer_density": outer_d,
                                            "unit_median_outer": medians[unit]}))
    return out


def load_refs(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def references(poles, refs: dict) -> list[CheckResult]:
    """Check 6: regression against poles this pipeline published before (blocking) and against outside
    claims about the same question (informative)."""
    out = []
    winners = {(s, e["unit"]): e["poles"] for s, entries in poles.items() for e in entries}
    for unit, per_scenario in refs.items():
        if unit == "external":
            continue
        for scenario, ref in per_scenario.items():
            top = winners.get((scenario, unit), [])
            if not top:
                out.append(CheckResult("reference", unit, scenario, False, bool(ref.get("blocking")),
                                       {"reason": "no pole", "source": ref["source"]}))
                continue
            p = top[0]
            moved = GEOD.inv(ref["lon"], ref["lat"], p["lon"], p["lat"])[2]
            change = abs(p["dist_m"] - ref["dist_m"]) / ref["dist_m"]
            out.append(CheckResult("reference", unit, scenario, bool(moved <= REF_MOVE_M and change <= REF_REL),
                                   bool(ref.get("blocking")),
                                   {"source": ref["source"], "ref_m": ref["dist_m"], "ours_m": p["dist_m"],
                                    "moved_m": round(moved, 1), "relative_change": round(change, 6)}))
    for ref in refs.get("external", []):
        cands = winners.get((ref["scenario"], ref["unit"]), [])
        if not cands:
            out.append(CheckResult("reference", ref["unit"], ref["scenario"], False, False,
                                   {"name": ref["name"], "source": ref["source"], "reason": "no pole"}))
            continue
        dists = [GEOD.inv(ref["lon"], ref["lat"], p["lon"], p["lat"])[2] for p in cands]
        k = int(np.argmin(dists))
        change = abs(cands[k]["dist_m"] - ref["dist_m"]) / ref["dist_m"] if ref.get("dist_m") else None
        out.append(CheckResult("reference", ref["unit"], ref["scenario"],
                               bool(dists[k] <= EXTERNAL_MOVE_M and (change is None or change <= EXTERNAL_REL)), False,
                               {"name": ref["name"], "source": ref["source"], "note": ref.get("note"),
                                "ref_m": ref.get("dist_m"), "nearest_rank": cands[k]["rank"],
                                "ours_m": cands[k]["dist_m"], "moved_m": round(dists[k], 1),
                                "relative_change": None if change is None else round(change, 6)}))
    return out


def invariants(poles, units: list[Unit], cfg: RegionConfig, grid_meta: dict) -> list[CheckResult]:
    """Check 7 (the stage-2 part): A <= B, top_n or a reason, 10 km separation, unit count, JSON structure."""
    out = []
    a = {e["unit"]: e for e in poles.get("A", [])}
    b = {e["unit"]: e for e in poles.get("B", [])}
    out.append(CheckResult("invariant", "*", "*", grid_meta.get("a_le_b_violations", 1) == 0, True,
                           {"name": "a_le_b_grid", "violations": grid_meta.get("a_le_b_violations")}))
    for u in units:
        pa, pb = a.get(u.code, {}).get("poles", []), b.get(u.code, {}).get("poles", [])
        ok = (not pa or not pb) or pa[0]["dist_m"] <= pb[0]["dist_m"] + 0.01
        out.append(CheckResult("invariant", u.code, "*", ok, True,
                               {"name": "a_le_b_poles", "A": pa[0]["dist_m"] if pa else None,
                                "B": pb[0]["dist_m"] if pb else None}))
        for scenario, entries in (("A", a), ("B", b)):
            entry = entries.get(u.code)
            ok = entry is not None and (len(entry["poles"]) == cfg.top_n or bool(entry["reason"]))
            out.append(CheckResult("invariant", u.code, scenario, ok, True,
                                   {"name": "top_n_or_reason", "count": len(entry["poles"]) if entry else 0,
                                    "reason": entry["reason"] if entry else None}))
            ps = entry["poles"] if entry else []
            worst = min((GEOD.inv(p["lon"], p["lat"], q["lon"], q["lat"])[2]
                         for i, p in enumerate(ps) for q in ps[i + 1:]), default=np.inf)
            out.append(CheckResult("invariant", u.code, scenario, bool(worst >= DEDUP_M), True,
                                   {"name": "separation", "min_m": None if worst == np.inf else round(worst, 1)}))
    expected = cfg.expected_units
    out.append(CheckResult("invariant", "*", "*", expected is None or len(units) == expected, True,
                           {"name": "unit_count", "expected": expected, "found": len(units)}))
    for scenario in ("A", "B"):
        try:
            validate_poles_json(poles.get(scenario, []), cfg.top_n)
            out.append(CheckResult("invariant", "*", scenario, True, True, {"name": "structure"}))
        except (ValueError, KeyError, TypeError) as e:
            out.append(CheckResult("invariant", "*", scenario, False, True, {"name": "structure", "error": str(e)}))
    return out
