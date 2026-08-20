"""Stage extract: filter and merge the PBFs with osmium, export layers to FlatGeobuf, fetch land polygons."""
from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path

from pyogrio import read_info
from pyogrio.raw import read

from . import http
from .config import RegionConfig
from .osmium import osmium
from .shell import require_tools, run_cmd
from .workspace import Workspace

STAGE = "extract"
LAND_URL = "https://osmdata.openstreetmap.de/download/land-polygons-split-4326.zip"
LAND_DIRNAME = "land-polygons-split-4326"
PLACES = "city,town,village,hamlet,isolated_dwelling"

# osmium export configs: which tags each layer keeps; ids and types become osm_id / osm_type.
_LAYERS = {
    "highways": {"filter": ["w/highway"], "geometry": "linestring",
                 "tags": ["highway", "name", "ref", "ice_road", "winter_road"], "where": None},
    "boundaries": {"filter": None, "geometry": "polygon",
                   "tags": ["boundary", "admin_level", "ISO3166-1", "ISO3166-2", "name", "name:en"],
                   "where": "boundary = 'administrative'"},
    "places": {"filter": [f"n/place={PLACES}"], "geometry": "point",
               "tags": ["place", "name", "name:en", "population"], "where": None},
    "water": {"filter": ["wr/natural=water"], "geometry": "polygon",
              "tags": ["natural", "water", "name"], "where": None},
}


def _admin_filters(cfg: RegionConfig) -> list[str]:
    return [f"r/admin_level={level}" for level in sorted({2, cfg.unit_admin_level})]


def _export_config(path: Path, tags: list[str]) -> Path:
    path.write_text(json.dumps({
        "attributes": {"type": "osm_type", "id": "osm_id"},
        "linear_tags": True, "area_tags": True,
        "include_tags": tags,
    }, indent=2), encoding="utf-8")
    return path


def _feature_count(path: Path) -> int:
    return int(read_info(str(path))["features"])


def export_layer(pbf: Path, name: str, spec: dict, out_dir: Path, log: logging.Logger, tools_log: Path) -> int:
    """osmium export to a GeoJSONSeq file, then ogr2ogr to FlatGeobuf (GDAL needs a seekable file for its
    schema pass; piping through /vsistdin/ stops at 1 MB). The text file is deleted afterwards."""
    cfg_path = _export_config(out_dir / f"export-{name}.json", spec["tags"])
    seq = out_dir / f"{name}.geojsonseq"
    fgb = out_dir / f"{name}.fgb"
    fgb.unlink(missing_ok=True)
    osmium(["export", "--overwrite", "-f", "geojsonseq", "-c", cfg_path, f"--geometry-types={spec['geometry']}",
            "-o", seq, pbf], log, stderr_path=tools_log)
    cmd = ["ogr2ogr", "-f", "FlatGeobuf", fgb, seq, "-nln", name, "-lco", "SPATIAL_INDEX=YES"]
    if spec["where"]:
        cmd += ["-where", spec["where"]]
    run_cmd(cmd, log, stderr_path=tools_log)
    seq.unlink()
    return _feature_count(fgb)


def ensure_land(shared: Path, log: logging.Logger, tools_log: Path, land_zip: Path | None = None) -> tuple[Path, dict]:
    """Download osmdata's split land polygons once into work/shared/ and convert them to land.fgb."""
    zip_path = land_zip or shared / f"{LAND_DIRNAME}.zip"
    info: dict = {}
    if land_zip is None:
        head = http.head(LAND_URL)
        http.download(LAND_URL, zip_path, log, expected_size=head["size"])
        info["land_zip_last_modified"] = head["last_modified"].isoformat() if head["last_modified"] else None
    info["land_zip_sha256"] = http.hash_file(zip_path)["sha256"]
    fgb = shared / "land.fgb"
    if not fgb.exists():
        unzip_dir = shared / LAND_DIRNAME
        if not unzip_dir.exists():
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(shared)
        shp = next(unzip_dir.glob("*.shp"))
        run_cmd(["ogr2ogr", "-f", "FlatGeobuf", fgb, shp, "-nln", "land", "-lco", "SPATIAL_INDEX=YES"], log, stderr_path=tools_log)
    return fgb, info


def level2_iso_codes(boundaries: Path) -> list[str]:
    """ISO 3166-1 codes of the admin_level 2 polygons; empty when the extract carries no such relation."""
    if not {"admin_level", "ISO3166-1"} <= set(read_info(str(boundaries))["fields"]):
        return []
    meta, _, _, cols = read(str(boundaries), read_geometry=False, columns=["admin_level", "ISO3166-1"])
    by_name = dict(zip(meta["fields"], cols))  # pyogrio returns layer order, not the order asked for
    return sorted({str(code) for level, code in zip(by_name["admin_level"], by_name["ISO3166-1"])
                   if str(level) == "2" and code})


def run(cfg: RegionConfig, ws: Workspace, log: logging.Logger, *, land_zip: Path | None = None) -> dict:
    require_tools(["osmium", "ogr2ogr"])
    fetch_dir, out_dir = ws.dir("fetch"), ws.dir(STAGE)
    tools_log = out_dir / "tools.log"
    snapshot = json.loads((fetch_dir / "snapshot.json").read_text(encoding="utf-8"))
    pbfs = [fetch_dir / s["file"] for s in snapshot["sources"]]
    all_filters = ["w/highway", *_admin_filters(cfg), f"n/place={PLACES}", "wr/natural=water"]

    filtered = []
    for pbf in pbfs:
        out = out_dir / f"{pbf.name.removesuffix('.osm.pbf')}-filtered.pbf"
        osmium(["tags-filter", "--overwrite", "-o", out, pbf, *all_filters], log, stderr_path=tools_log)
        filtered.append(out)
    merged = out_dir / "filtered.pbf"
    if len(filtered) == 1:
        filtered[0].replace(merged)
    else:
        osmium(["merge", "--overwrite", "-o", merged, *filtered], log, stderr_path=tools_log)
        for f in filtered:
            f.unlink()

    counts: dict[str, int] = {}
    for name, spec in _LAYERS.items():
        thematic = out_dir / f"{name}.pbf"
        osmium(["tags-filter", "--overwrite", "-o", thematic, merged, *(spec["filter"] or _admin_filters(cfg))], log, stderr_path=tools_log)
        counts[name] = export_layer(thematic, name, spec, out_dir, log, tools_log)
        log.info("%s: %d features", name, counts[name])

    land_fgb, land_info = ensure_land(ws.shared_dir(), log, tools_log, land_zip)
    counts["land"] = _feature_count(land_fgb)

    codes = level2_iso_codes(out_dir / "boundaries.fgb")
    log.info("admin_level 2 polygons with ISO3166-1: %d (%s)", len(codes), " ".join(codes))
    return {"counts": counts, "level2_iso_codes": codes, **land_info}
