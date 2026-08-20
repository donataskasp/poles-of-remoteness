"""Stage extract: filter and merge the PBFs with osmium, export layers to FlatGeobuf, fetch land polygons.

Two properties are load bearing here, both learned the hard way on a full continent:

1. GDAL's GeoJSONSeq reader holds roughly 6 bytes of RAM per byte of input, so the 37.7 GB highways
   export cannot be converted in one ogr2ogr call (ogrinfo alone peaked at a 132 GB memory footprint
   and the conversion was SIGKILLed on a 24 GB machine). Every layer therefore goes through
   `chunk_lines` and a VRT union merge. Do not put the single-pass conversion back.
2. Each step costs minutes to an hour, so every artefact is guarded by `_ensure`: a rerun after a
   failure resumes at the first missing piece instead of redoing 35 minutes of osmium.
"""
from __future__ import annotations

import json
import logging
import os
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

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
# 256 MB of GeoJSONSeq costs the reader about 1.5 GB; six of those in parallel fit a 24 GB machine.
CHUNK_BYTES = 256 * 1024 * 1024
MARKER = ".ok"

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


def _ensure(out: Path, log: logging.Logger, produce: Callable[[], None]) -> None:
    """Run `produce` unless `out` and its `<out>.ok` marker both exist. The marker is written only after
    `produce` returns, so a half-written artefact is never mistaken for a finished one."""
    marker = out.with_name(out.name + MARKER)
    if out.exists() and marker.exists():
        log.info("skip %s: done", out.name)
        return
    marker.unlink(missing_ok=True)
    produce()
    marker.touch()


def _discard(path: Path) -> None:
    """Delete an intermediate and its done marker; both may already be gone."""
    path.unlink(missing_ok=True)
    path.with_name(path.name + MARKER).unlink(missing_ok=True)


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
    """force_feature_count is not optional: a FlatGeobuf layer that a -where emptied reports -1 otherwise,
    which would silently poison both the chunk arithmetic and the counts in the stage meta."""
    return int(read_info(str(path), force_feature_count=True)["features"])


def chunk_lines(src: Path, chunk_bytes: int, prefix: Path) -> list[Path]:
    """Split a newline-delimited file into `<prefix>.part-NNNN.geojsonseq` chunks of at most chunk_bytes.

    A line never straddles two chunks, so a line longer than chunk_bytes becomes an oversized chunk of its
    own. Concatenating the chunks in order reproduces `src` byte for byte. An empty input yields no chunks.
    """
    parts: list[Path] = []
    out = None
    written = 0
    try:
        with open(src, "rb") as f:
            for line in f:
                if out is None or written + len(line) > chunk_bytes:
                    if out is not None:
                        out.close()
                    part = Path(f"{prefix}.part-{len(parts):04d}.geojsonseq")
                    parts.append(part)
                    out = open(part, "wb")
                    written = 0
                out.write(line)
                written += len(line)
    finally:
        if out is not None:
            out.close()
    return parts


def _convert_chunks(parts: list[Path], name: str, where: str | None, log: logging.Logger) -> list[Path]:
    """Convert the chunks to FlatGeobuf in parallel; the threads only wait on ogr2ogr subprocesses.
    No spatial index: the chunks are transient and only the merged layer is queried. Each chunk keeps its
    own stderr file so a failure among many parallel runs still reports that run's own GDAL error."""
    workers = min(6, max(1, (os.cpu_count() or 3) - 2))

    def convert(part: Path) -> Path:
        out = part.with_suffix(".fgb")
        out.unlink(missing_ok=True)
        cmd = ["ogr2ogr", "-f", "FlatGeobuf", out, part, "-nln", name, "-lco", "SPATIAL_INDEX=NO"]
        if where:
            cmd += ["-where", where]
        run_cmd(cmd, log, stderr_path=part.with_suffix(".log"))
        return out

    log.info("%s: converting %d chunks with %d workers", name, len(parts), workers)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(convert, parts))


def write_union_vrt(path: Path, name: str, parts: list[Path]) -> Path:
    """An OGRVRTUnionLayer over the chunk FlatGeobufs. The default field strategy is the union of the
    sub-layer schemas, so a field carried by only some chunks survives; an empty chunk contributes none."""
    layers = "".join(
        f'<OGRVRTLayer name="{name}"><SrcDataSource relativeToVRT="1">{part.name}</SrcDataSource>'
        f"<SrcLayer>{name}</SrcLayer></OGRVRTLayer>"
        for part in parts
    )
    path.write_text(f'<OGRVRTDataSource><OGRVRTUnionLayer name="{name}">{layers}</OGRVRTUnionLayer></OGRVRTDataSource>',
                    encoding="utf-8")
    return path


def export_layer(pbf: Path, name: str, spec: dict, out_dir: Path, log: logging.Logger, tools_log: Path) -> int:
    """osmium export to a GeoJSONSeq file, then chunked ogr2ogr conversions merged through a VRT union.

    The text file goes to disk first because piping into /vsistdin/ stops at 1 MB, and it is then split
    because GDAL's GeoJSONSeq reader needs about 6 bytes of RAM per input byte: a 37.7 GB export would
    need over 100 GB to read in one pass. The chunks, the VRT and the text file are deleted once the
    merged layer exists and its feature count matches the sum of the chunk counts.
    """
    fgb = out_dir / f"{name}.fgb"
    seq = out_dir / f"{name}.geojsonseq"

    def produce() -> None:
        cfg_path = _export_config(out_dir / f"export-{name}.json", spec["tags"])
        _ensure(seq, log, lambda: osmium(
            ["export", "--overwrite", "-f", "geojsonseq", "-c", cfg_path, f"--geometry-types={spec['geometry']}",
             "-o", seq, pbf], log, stderr_path=tools_log))
        for stale in sorted(out_dir.glob(f"{name}.part-*")):
            _discard(stale)
        parts = chunk_lines(seq, CHUNK_BYTES, out_dir / name)
        if not parts:
            raise RuntimeError(f"{name}: osmium export produced no features; check the tag filters in {cfg_path.name}")
        chunk_fgbs = _convert_chunks(parts, name, spec["where"], log)
        expected = sum(_feature_count(p) for p in chunk_fgbs)
        vrt = write_union_vrt(out_dir / f"{name}.vrt", name, chunk_fgbs)
        fgb.unlink(missing_ok=True)
        run_cmd(["ogr2ogr", "-f", "FlatGeobuf", fgb, vrt, "-nln", name,
                 "-lco", "SPATIAL_INDEX=YES", "-lco", f"TEMPORARY_DIR={out_dir}"], log, stderr_path=tools_log)
        merged = _feature_count(fgb)
        log.info("%s: %d chunks, %d features in the chunks, %d in %s", name, len(parts), expected, merged, fgb.name)
        if merged != expected:
            raise RuntimeError(f"{name}: merged {merged} features but the {len(parts)} chunks hold {expected}")

    _ensure(fgb, log, produce)
    _discard(seq)
    for leftover in sorted(out_dir.glob(f"{name}.part-*")):
        _discard(leftover)
    _discard(out_dir / f"{name}.vrt")
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

    merged = out_dir / "filtered.pbf"
    per_source = [out_dir / f"{pbf.name.removesuffix('.osm.pbf')}-filtered.pbf" for pbf in pbfs]

    def merge_sources() -> None:
        for src, dest in zip(pbfs, per_source):
            _ensure(dest, log, lambda src=src, dest=dest: osmium(
                ["tags-filter", "--overwrite", "-o", dest, src, *all_filters], log, stderr_path=tools_log))
        if len(per_source) == 1:
            per_source[0].replace(merged)  # a rename, not a 10 GB copy
        else:
            osmium(["merge", "--overwrite", "-o", merged, *per_source], log, stderr_path=tools_log)

    _ensure(merged, log, merge_sources)
    for path in per_source:  # only once filtered.pbf is marked done
        _discard(path)

    counts: dict[str, int] = {}
    for name, spec in _LAYERS.items():
        thematic = out_dir / f"{name}.pbf"
        _ensure(thematic, log, lambda thematic=thematic, spec=spec: osmium(
            ["tags-filter", "--overwrite", "-o", thematic, merged, *(spec["filter"] or _admin_filters(cfg))],
            log, stderr_path=tools_log))
        counts[name] = export_layer(thematic, name, spec, out_dir, log, tools_log)
        log.info("%s: %d features", name, counts[name])

    land_fgb, land_info = ensure_land(ws.shared_dir(), log, tools_log, land_zip)
    counts["land"] = _feature_count(land_fgb)

    codes = level2_iso_codes(out_dir / "boundaries.fgb")
    log.info("admin_level 2 polygons with ISO3166-1: %d (%s)", len(codes), " ".join(codes))
    return {"counts": counts, "level2_iso_codes": codes, **land_info}
