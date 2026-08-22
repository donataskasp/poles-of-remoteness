"""The site's JSON contract (spec 4.2): exclusions applied, ranks renumbered, geodesic unit areas, four documents
validated against the frozen schemas in poles/schemas and merged per region with what the site already holds."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path

import shapely
from jsonschema import Draft202012Validator
from pyogrio.raw import read
from pyproj import Geod
from shapely.geometry.base import BaseGeometry

from ..classes import ClassTable
from ..errors import PolesError
from ..poles import SCENARIOS

SCHEMA_VERSION = 1
SCHEMAS = Path(__file__).resolve().parent.parent / "schemas"
GEOD = Geod(ellps="WGS84")


@dataclass(frozen=True)
class SiteData:
    regions_entry: dict
    units_doc: dict
    unit_docs: dict[str, dict]
    manifest_entry: dict


def apply_exclusions(poles: dict[str, list[dict]], excluded: list[dict]) -> dict[str, list[dict]]:
    """Validation's refused poles leave the published set; the rest renumber from 1 within their unit (#21)."""
    drop = {(e["scenario"], e["unit"], int(e["rank"])) for e in excluded}
    seen = set()
    out: dict[str, list[dict]] = {}
    for scenario, units in poles.items():
        out[scenario] = []
        for u in units:
            kept = []
            for p in sorted(u["poles"], key=lambda p: p["rank"]):
                key = (scenario, u["unit"], int(p["rank"]))
                if key in drop:
                    seen.add(key)
                    continue
                kept.append(dict(copy.deepcopy(p), rank=len(kept) + 1))
            out[scenario].append({"unit": u["unit"], "poles": kept, "reason": u.get("reason"),
                                  "withheld": len(u["poles"]) - len(kept)})
    missing = sorted(drop - seen)
    if missing:
        raise PolesError(f"validate/report.json excludes poles that are not in poles/<scenario>.json: {missing}; rerun validate")
    return out


def unit_area_km2(geom: BaseGeometry) -> float:
    area, _ = GEOD.geometry_area_perimeter(geom)
    return round(abs(area) / 1e6, 1)


def unit_geometries(units_fgb: Path) -> dict[str, BaseGeometry]:
    meta, _, wkb, fields = read(str(units_fgb), layer="units", columns=["code"])
    codes = dict(zip(meta["fields"], fields))["code"]
    return {code: shapely.from_wkb(g) for code, g in zip(codes, wkb)}


def regional_ranks(published_scenario: list[dict]) -> dict[str, int]:
    """Dense rank of each unit's best pole across the region, farthest first; equal distances share a rank."""
    best = [(u["poles"][0]["dist_m"], u["unit"]) for u in published_scenario if u["poles"]]
    best.sort(key=lambda t: (-t[0], t[1]))
    ranks, rank, prev = {}, 0, None
    for dist, code in best:
        if dist != prev:
            rank += 1
            prev = dist
        ranks[code] = rank
    return ranks


def _unit_summary(unit: dict, rank: int | None) -> dict | None:
    if not unit["poles"]:
        return None
    top = unit["poles"][0]
    return {"dist_m": top["dist_m"], "lat": top["lat"], "lon": top["lon"], "rank": rank, "withheld": unit["withheld"]}


def build(region: dict, units_meta: list[dict], geoms: dict[str, BaseGeometry], published: dict[str, list[dict]],
          table: ClassTable, archives: dict, detail_meta: dict, verify_meta: dict, sources: list[dict],
          generated_at: str, pipeline_commit: str | None) -> SiteData:
    rid, snapshot = region["id"], region["snapshot"]
    by_unit = {s: {u["unit"]: u for u in published.get(s, [])} for s in SCENARIOS}
    ranks = {s: regional_ranks(published.get(s, [])) for s in SCENARIOS}
    units_rows, unit_docs = [], {}
    for m in units_meta:
        code = m["code"]
        base = {"code": code, "name": m["name"], "name_en": m["name_en"], "country": m["country"],
                "area_km2": unit_area_km2(geoms[code]), "bbox": m["bbox"],
                "transcontinental": bool(m["transcontinental"]), "closed_by_edge": bool(m["closed_by_edge"])}
        row = dict(base)
        doc = {"region": rid, "snapshot": snapshot, **base}
        for s in SCENARIOS:
            u = by_unit[s].get(code, {"unit": code, "poles": [], "reason": "not searched", "withheld": 0})
            row[s] = _unit_summary(u, ranks[s].get(code))
            poles = [dict(p, detail=f"detail/{code}/{s}-{p['rank']}") for p in u["poles"]]
            doc[s] = {"poles": poles, "withheld": u["withheld"], "reason": u["reason"]}
        units_rows.append(row)
        unit_docs[code] = doc
    regions_entry = {"id": rid, "name": region["name"], "snapshot": snapshot, "unit_level": region["unit_level"],
                     "units_count": len(units_meta), "r2_base": region["r2_base"], "class_edges": list(table.edges),
                     "max_distance_m": region["max_distance_m"], "edge_mask_m": region["edge_mask_m"],
                     "detail_res_m": region["detail_res_m"], "detail_window_m": region["detail_window_m"]}
    prefix = f"{rid}/{snapshot}"
    manifest_entry = {"snapshot": snapshot, "published_at": generated_at, "r2_base": region["r2_base"],
                      "pipeline_commit": pipeline_commit, "sources": [dict(s) for s in sources],
                      "archives": {s: {"key": f"{prefix}/{a['key_name']}", "bytes": a["bytes"], "tiles": a["tiles"],
                                       "min_zoom": a["min_zoom"], "max_zoom": a["max_zoom"]} for s, a in archives.items()},
                      "detail": {"count": detail_meta["count"], "bytes": detail_meta["bytes"]},
                      "validation": {"report": f"{prefix}/validation/report.json", "report_html": f"{prefix}/validation/report.html",
                                     "contact_sheet": f"{prefix}/validation/contact-sheet.html"},
                      "verified": dict(verify_meta)}
    return SiteData(regions_entry, {"region": rid, "snapshot": snapshot, "units": units_rows}, unit_docs, manifest_entry)


def merge_regions(existing: dict | None, entry: dict) -> dict:
    regions = [r for r in (existing or {}).get("regions", []) if r.get("id") != entry["id"]]
    return {"schema_version": SCHEMA_VERSION, "regions": regions + [entry]}


def merge_manifest(existing: dict | None, region_id: str, entry: dict, generated_at: str) -> dict:
    regions = dict((existing or {}).get("regions", {}))
    regions[region_id] = entry
    return {"schema_version": SCHEMA_VERSION, "generated_at": generated_at, "regions": regions}


_validators: dict[str, Draft202012Validator] = {}


def _path_key(error) -> tuple:
    """Document order for an error path, comparable even when array indices and object keys sit at the same
    depth: a bare list of the path would compare an int with a str and raise."""
    return tuple((0, p, "") if isinstance(p, int) else (1, 0, p) for p in error.path)


def validate_doc(name: str, doc: dict) -> None:
    if name not in _validators:
        schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        _validators[name] = Draft202012Validator(schema)
    err = next(iter(sorted(_validators[name].iter_errors(doc), key=_path_key)), None)
    if err is not None:
        where = "/".join(str(p) for p in err.path) or "<root>"
        raise PolesError(f"{name}.schema.json: {where}: {err.message}")


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise PolesError(f"{path}: not JSON ({exc}); fix or remove it before publishing") from exc


def _dump(path: Path, doc: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def write_site(site: SiteData, out_dir: Path, region_id: str, generated_at: str) -> list[Path]:
    """Every document is validated before any of them is written, so a refused publish leaves the site as it was."""
    regions = merge_regions(_read_json(out_dir / "regions.json"), site.regions_entry)
    manifest = merge_manifest(_read_json(out_dir / "manifest.json"), region_id, site.manifest_entry, generated_at)
    validate_doc("regions", regions)
    validate_doc("manifest", manifest)
    validate_doc("units", site.units_doc)
    for doc in site.unit_docs.values():
        validate_doc("unit", doc)
    written = [_dump(out_dir / "regions.json", regions), _dump(out_dir / "manifest.json", manifest),
               _dump(out_dir / region_id / "units.json", site.units_doc)]
    for code, doc in site.unit_docs.items():
        written.append(_dump(out_dir / region_id / "units" / f"{code}.json", doc))
    return written
