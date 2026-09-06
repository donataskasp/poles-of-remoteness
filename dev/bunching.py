#!/usr/bin/env python3
"""Bunching and island measures over the published site documents (issues #56 and #30).

Reads `site/data/<region>/units/<code>.json` only, so it needs no pipeline run and no R2. Two modes:

  bunching  how tightly a unit's visible poles sit together: per pole the geodesic distance to its
            nearest sibling, per unit the mean and minimum of those, how many poles have a neighbour
            inside --near-km, and the diameter (largest pairwise distance) of the set. Region totals
            give the share of units whose visible poles all fall inside --near-km and the share of
            poles with a neighbour that close. A unit with fewer than two visible poles is not bunched.

  islands   which published poles carry an `island_km2` tag, and which units change winner when the
            islands are hidden (the superset toggle of #30, `i` in the site hash).

The visible set is chosen exactly like `visiblePoles` in site/js/data.js: walk the poles in rank order,
drop a tagged pole when --islands 0, stop at --top. A missing `island_km2` counts as null (untagged),
which is what the currently committed pre-re-search data looks like.

Usage (from the repository root):
  pipeline/.venv/bin/python dev/bunching.py --data site/data --mode bunching
  pipeline/.venv/bin/python dev/bunching.py --mode islands --json work/islands.json
"""
from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path

from pyproj import Geod

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ("A", "B")
GEOD = Geod(ellps="WGS84")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def region_ids(data: Path) -> list[str]:
    return [r["id"] for r in load_json(data / "regions.json")["regions"]]


def unit_docs(data: Path, region: str) -> list[dict]:
    """Every unit document of a region, in the order of the region's unit index."""
    codes = [u["code"] for u in load_json(data / region / "units.json")["units"]]
    return [load_json(data / region / "units" / f"{code}.json") for code in codes]


def visible_poles(poles: list[dict], islands: bool, top: int) -> list[dict]:
    out: list[dict] = []
    for p in poles or []:
        if not islands and p.get("island_km2") is not None:
            continue
        out.append(p)
        if len(out) >= top:
            break
    return out


def km(a: dict, b: dict) -> float:
    return GEOD.inv(a["lon"], a["lat"], b["lon"], b["lat"])[2] / 1000.0


def unit_stats(poles: list[dict], near_km: float) -> dict:
    """Nearest-neighbour and diameter measures over one unit's visible poles."""
    n = len(poles)
    if n < 2:
        return {"poles": n, "nn_mean_km": None, "nn_min_km": None, "near": 0,
                "diameter_km": None, "bunched": False}
    nearest = [float("inf")] * n
    diameter = 0.0
    for i, j in combinations(range(n), 2):
        d = km(poles[i], poles[j])
        nearest[i] = min(nearest[i], d)
        nearest[j] = min(nearest[j], d)
        diameter = max(diameter, d)
    near = sum(1 for d in nearest if d <= near_km)
    return {"poles": n, "nn_mean_km": sum(nearest) / n, "nn_min_km": min(nearest), "near": near,
            "diameter_km": diameter, "bunched": diameter <= near_km}


def fmt(value: float | None, places: int = 2) -> str:
    return "-" if value is None else f"{value:.{places}f}"


def table(rows: list[list[str]], header: list[str]) -> str:
    widths = [max(len(str(r[i])) for r in [header] + rows) for i in range(len(header))]
    lines = ["  ".join(h.ljust(w) for h, w in zip(header, widths)).rstrip(),
             "  ".join("-" * w for w in widths)]
    lines += ["  ".join(str(c).ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows]
    return "\n".join(lines)


def share(part: int, whole: int) -> str:
    return f"{part}/{whole} ({100.0 * part / whole:.1f}%)" if whole else f"{part}/0 (n/a)"


def run_bunching(data: Path, regions: list[str], islands: bool, top: int, near_km: float) -> dict:
    doc = {"mode": "bunching", "near_km": near_km, "top": top, "islands": int(islands), "regions": []}
    for region in regions:
        rows: list[list[str]] = []
        entry = {"region": region, "units": [], "totals": {}}
        totals = {s: {"units": 0, "poles": 0, "bunched_units": 0, "near_poles": 0} for s in SCENARIOS}
        for unit in unit_docs(data, region):
            u = {"code": unit["code"], "name": unit.get("name_en") or unit.get("name"), "scenarios": {}}
            for scenario in SCENARIOS:
                stats = unit_stats(visible_poles(unit.get(scenario, {}).get("poles", []), islands, top), near_km)
                u["scenarios"][scenario] = stats
                t = totals[scenario]
                t["units"] += 1
                t["poles"] += stats["poles"]
                t["bunched_units"] += int(stats["bunched"])
                t["near_poles"] += stats["near"]
                rows.append([unit["code"], scenario, str(stats["poles"]), fmt(stats["nn_mean_km"]),
                             fmt(stats["nn_min_km"]), str(stats["near"]), fmt(stats["diameter_km"])])
            entry["units"].append(u)
        entry["totals"] = totals
        doc["regions"].append(entry)
        print(f"\n== {region} ==  visible poles per unit: top {top}, islands {'shown' if islands else 'hidden'}")
        print(table(rows, ["unit", "scen", "poles", "nn_mean_km", "nn_min_km", f"near<={near_km:g}km", "diam_km"]))
        for scenario in SCENARIOS:
            t = totals[scenario]
            print(f"TOTAL {region} {scenario}: units {t['units']}, poles {t['poles']}, "
                  f"bunched units {share(t['bunched_units'], t['units'])}, "
                  f"poles with a neighbour within {near_km:g} km {share(t['near_poles'], t['poles'])}")
    return doc


def run_islands(data: Path, regions: list[str], top: int) -> dict:
    doc = {"mode": "islands", "top": top, "regions": []}
    for region in regions:
        entry = {"region": region, "tagged": {s: 0 for s in SCENARIOS}, "poles": [], "winner_changes": []}
        for unit in unit_docs(data, region):
            for scenario in SCENARIOS:
                poles = unit.get(scenario, {}).get("poles", [])
                for p in poles:
                    if p.get("island_km2") is not None:
                        entry["tagged"][scenario] += 1
                        entry["poles"].append({"unit": unit["code"], "scenario": scenario, "rank": p.get("rank"),
                                               "dist_m": p.get("dist_m"), "island_km2": p.get("island_km2")})
                overall = visible_poles(poles, True, top)
                mainland = visible_poles(poles, False, top)
                if not overall:
                    continue
                first, land = overall[0], (mainland[0] if mainland else None)
                if land is not None and land.get("rank") == first.get("rank"):
                    continue
                entry["winner_changes"].append({
                    "unit": unit["code"], "scenario": scenario,
                    "overall": {"rank": first.get("rank"), "dist_m": first.get("dist_m"),
                                "island_km2": first.get("island_km2")},
                    "mainland": None if land is None else {"rank": land.get("rank"), "dist_m": land.get("dist_m")}})
        doc["regions"].append(entry)
        print(f"\n== {region} ==")
        print("tagged poles: " + ", ".join(f"{s} {entry['tagged'][s]}" for s in SCENARIOS))
        if entry["poles"]:
            print(table([[p["unit"], p["scenario"], str(p["rank"]), fmt(p["dist_m"], 1), fmt(p["island_km2"], 3)]
                         for p in entry["poles"]], ["unit", "scen", "rank", "dist_m", "island_km2"]))
        else:
            print("no pole carries island_km2 in this data")
        if entry["winner_changes"]:
            print("\nwinner changes when islands are hidden:")
            print(table([[c["unit"], c["scenario"], f"#{c['overall']['rank']} {fmt(c['overall']['dist_m'], 1)} m "
                          f"island {fmt(c['overall']['island_km2'], 3)} km2",
                          "none" if c["mainland"] is None else
                          f"#{c['mainland']['rank']} {fmt(c['mainland']['dist_m'], 1)} m"]
                         for c in entry["winner_changes"]], ["unit", "scen", "overall winner", "mainland winner"]))
        else:
            print("no unit changes winner when islands are hidden")
    return doc


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=ROOT / "site" / "data", help="published site data directory")
    ap.add_argument("--region", action="append", dest="regions", metavar="ID",
                    help="region id, repeatable; default every region in regions.json")
    ap.add_argument("--mode", choices=("bunching", "islands"), default="bunching")
    ap.add_argument("--islands", type=int, choices=(0, 1), default=1,
                    help="bunching mode: 1 keeps island poles in the visible set, 0 drops them")
    ap.add_argument("--top", type=int, default=10, help="visible poles per unit and scenario")
    ap.add_argument("--near-km", type=float, default=20.0, help="the bunching threshold in km")
    ap.add_argument("--json", type=Path, metavar="PATH", help="also write the numbers as JSON")
    args = ap.parse_args()
    regions = args.regions or region_ids(args.data)
    if args.mode == "bunching":
        doc = run_bunching(args.data, regions, bool(args.islands), args.top, args.near_km)
    else:
        doc = run_islands(args.data, regions, args.top)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
