"""Stage extract: filter and merge the PBFs with osmium, export layers to FlatGeobuf, fetch land polygons.

Three properties are load bearing here, all learned the hard way on a full continent:

1. GDAL's GeoJSONSeq reader holds roughly 6 bytes of RAM per byte of input, so the 37.7 GB highways
   export cannot be converted in one ogr2ogr call (ogrinfo alone peaked at a 132 GB memory footprint
   and the conversion was SIGKILLed on a 24 GB machine). Every layer therefore goes through
   `chunk_lines` and a VRT union. Do not put the single-pass conversion back.
2. A FlatGeobuf whose packed R-tree passes 4 GiB is write-only in practice. Europe's highways merged
   to 101,461,002 features with a 4.33 GB index, and GDAL 3.13 then failed on the very first feature
   with "Invalid size detected: feature" in both the classic and the Arrow read path, while a spatial
   filter returned nothing; the header count and extent were fine and 4 M feature files read
   perfectly. So stage 1 builds no spatial index at all and never merges past MERGE_MAX_FEATURES.
   Issue #16.
3. Each step costs minutes to an hour, so every artefact is guarded by `_ensure`: a rerun after a
   failure resumes at the first missing piece instead of redoing 35 minutes of osmium.

The handle every later stage opens is `<layer>.vrt`, never the FlatGeobuf behind it. Under the merge
cap the VRT wraps one merged file, above it the VRT unions the chunks, and nothing downstream has to
know which.
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
# Merge only what stays comfortably readable. 101 M features produced a 4.33 GB index GDAL could not
# read; 4 M feature files are fine. 50 M sits well inside the working range with room to spare, and a
# layer above it is served from its chunks instead, which are a few million features each.
MERGE_MAX_FEATURES = 50_000_000
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


def _is_done(out: Path) -> bool:
    return out.exists() and out.with_name(out.name + MARKER).exists()


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


def _feature_count(path: Path, layer: str | None = None) -> int:
    """force_feature_count is not optional: a union VRT reports 0 and a FlatGeobuf layer that a -where
    emptied reports -1 without it, either of which would silently poison the counts. It stays cheap,
    since FlatGeobuf answers from its header even unindexed (`fast_feature_count`)."""
    return int(read_info(str(path), layer=layer, force_feature_count=True)["features"])


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
    Each chunk keeps its own stderr file so a failure among many parallel runs still reports that run's
    own GDAL error."""
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


def write_union_vrt(path: Path, name: str, sources: list[Path]) -> Path:
    """An OGRVRTUnionLayer over one or more FlatGeobufs, written next to them. The default field strategy
    is the union of the sub-layer schemas, so a field carried by only some sources survives and an empty
    source contributes none. Cheap to rewrite, so it is always written rather than patched."""
    layers = "".join(
        f'<OGRVRTLayer name="{name}"><SrcDataSource relativeToVRT="1">{src.name}</SrcDataSource>'
        f"<SrcLayer>{name}</SrcLayer></OGRVRTLayer>"
        for src in sources
    )
    path.write_text(f'<OGRVRTDataSource><OGRVRTUnionLayer name="{name}">{layers}</OGRVRTUnionLayer></OGRVRTDataSource>',
                    encoding="utf-8")
    return path


def export_layer(pbf: Path, name: str, spec: dict, out_dir: Path, log: logging.Logger, tools_log: Path) -> Path:
    """Produce `<name>.vrt`, the layer handle every later stage opens, and return it.

    osmium exports to a GeoJSONSeq file (piping into /vsistdin/ stops at 1 MB), which is split because
    GDAL's GeoJSONSeq reader needs about 6 bytes of RAM per input byte, and the chunks are converted in
    parallel. At or below MERGE_MAX_FEATURES the chunks are merged into one indexed `<name>.fgb` and the
    VRT wraps that; above it the unindexed chunks stay and the VRT unions them, because a merged layer
    that big grows a packed R-tree GDAL cannot read back (issue #16).
    """
    fgb = out_dir / f"{name}.fgb"
    seq = out_dir / f"{name}.geojsonseq"
    vrt = out_dir / f"{name}.vrt"
    merge_vrt = out_dir / f"{name}.merge.vrt"

    def produce() -> None:
        if _is_done(fgb):  # finished by an earlier run, possibly before VRT handles existed
            existing = _feature_count(fgb)
            if existing <= MERGE_MAX_FEATURES:
                log.info("%s: merged layer already on disk with %d features, writing the VRT over it", name, existing)
                write_union_vrt(vrt, name, [fgb])
                return
            # The header of an over-cap layer still reads; its features do not. Wrapping it would hand the
            # broken file to every later stage, so drop it and rebuild from chunks.
            log.warning("%s: the merged layer on disk holds %d features, over the %d cap; dropping it and "
                        "rebuilding from chunks (issue #16)", name, existing, MERGE_MAX_FEATURES)
            _discard(fgb)
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
        total = sum(_feature_count(part) for part in chunk_fgbs)
        if total > MERGE_MAX_FEATURES:
            log.info("%s: %d features in %d chunks, over the %d merge cap: serving the chunks through the VRT",
                     name, total, len(parts), MERGE_MAX_FEATURES)
            write_union_vrt(vrt, name, chunk_fgbs)
            return
        log.info("%s: %d features in %d chunks, within the %d merge cap: merging into one layer",
                 name, total, len(parts), MERGE_MAX_FEATURES)
        write_union_vrt(merge_vrt, name, chunk_fgbs)
        _ensure(fgb, log, lambda: run_cmd(
            ["ogr2ogr", "-f", "FlatGeobuf", fgb, merge_vrt, "-nln", name,
             "-lco", "SPATIAL_INDEX=NO", "-lco", f"TEMPORARY_DIR={out_dir}"], log, stderr_path=tools_log))
        merged = _feature_count(fgb)
        if merged != total:
            raise RuntimeError(f"{name}: merged {merged} features but the {len(parts)} chunks hold {total}")
        write_union_vrt(vrt, name, [fgb])
        for part in chunk_fgbs:
            _discard(part)

    _ensure(vrt, log, produce)
    _discard(seq)
    for leftover in [*out_dir.glob(f"{name}.part-*.geojsonseq"), *out_dir.glob(f"{name}.part-*.log")]:
        _discard(leftover)
    _discard(merge_vrt)
    return vrt


def ensure_land(shared: Path, log: logging.Logger, tools_log: Path, land_zip: Path | None = None) -> tuple[Path, dict]:
    """Download osmdata's split land polygons once into work/shared/ and convert them to land.fgb, wrapped
    in land.vrt so every layer in the pipeline is opened the same way. Returns the VRT."""
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
        run_cmd(["ogr2ogr", "-f", "FlatGeobuf", fgb, shp, "-nln", "land", "-lco", "SPATIAL_INDEX=NO"],
                log, stderr_path=tools_log)
    return write_union_vrt(shared / "land.vrt", "land", [fgb]), info


def level2_iso_codes(boundaries: Path, layer: str) -> list[str]:
    """ISO 3166-1 codes of the admin_level 2 polygons; empty when the extract carries no such relation."""
    if not {"admin_level", "ISO3166-1"} <= set(read_info(str(boundaries), layer=layer)["fields"]):
        return []
    meta, _, _, cols = read(str(boundaries), layer=layer, read_geometry=False, columns=["admin_level", "ISO3166-1"])
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
    vrts: dict[str, Path] = {}
    for name, spec in _LAYERS.items():
        thematic = out_dir / f"{name}.pbf"
        _ensure(thematic, log, lambda thematic=thematic, spec=spec: osmium(
            ["tags-filter", "--overwrite", "-o", thematic, merged, *(spec["filter"] or _admin_filters(cfg))],
            log, stderr_path=tools_log))
        vrts[name] = export_layer(thematic, name, spec, out_dir, log, tools_log)
        counts[name] = _feature_count(vrts[name], name)
        log.info("%s: %d features", name, counts[name])

    land_vrt, land_info = ensure_land(ws.shared_dir(), log, tools_log, land_zip)
    counts["land"] = _feature_count(land_vrt, "land")

    codes = level2_iso_codes(vrts["boundaries"], "boundaries")
    log.info("admin_level 2 polygons with ISO3166-1: %d (%s)", len(codes), " ".join(codes))
    return {"counts": counts, "level2_iso_codes": codes, **land_info}
