import json
import shutil
import zipfile

import numpy as np
import pytest
import shapely
from pyogrio import read_info
from pyogrio.raw import read, write

from poles import extract
from poles.extract import chunk_lines
from poles.osmium import osmium
from poles.shell import ToolError
from poles.workspace import Workspace
from tests.helpers import write_fgb


def _land_zip(tmp_path):
    """A zip shaped like osmdata's: land-polygons-split-4326/land_polygons.shp with one square around the fixture."""
    d = tmp_path / "land-polygons-split-4326"
    d.mkdir()
    geom = shapely.box(24.5, 54.5, 25.5, 55.5)
    write(str(d / "land_polygons.shp"), geometry=np.array([shapely.to_wkb(geom)], dtype=object),
          field_data=[np.array([1], dtype=np.int64)], fields=["FID"], driver="ESRI Shapefile",
          geometry_type="Polygon", crs="EPSG:4326")
    z = tmp_path / "land-polygons-split-4326.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for p in d.iterdir():
            zf.write(p, f"land-polygons-split-4326/{p.name}")
    return z


def _workspace(tmp_path, tiny_pbf) -> Workspace:
    ws = Workspace(tmp_path / "work", "test", "2026-01-01")
    shutil.copy(tiny_pbf, ws.dir("fetch") / "tiny-latest.osm.pbf")
    (ws.dir("fetch") / "snapshot.json").write_text(json.dumps({"region": "test", "snapshot": "2026-01-01", "sources": [
        {"url": "http://x/tiny-latest.osm.pbf", "role": "primary", "file": "tiny-latest.osm.pbf", "poly": "tiny.poly"}]}))
    return ws


def _fields(path) -> list[str]:
    return list(read_info(str(path))["fields"])


def _vrt_count(path, layer) -> int:
    return int(read_info(str(path), layer=layer, force_feature_count=True)["features"])


def _column(path, name):
    meta, _, _, field_data = read(str(path), read_geometry=False)
    return list(field_data[list(meta["fields"]).index(name)])


def test_extract_tiny_fixture_produces_five_layers_with_expected_counts(tmp_path, tiny_pbf, cfg, log):
    ws = _workspace(tmp_path, tiny_pbf)
    meta = extract.run(cfg, ws, log, land_zip=_land_zip(tmp_path))
    ex = ws.dir("extract")
    assert meta["counts"] == {"highways": 2, "boundaries": 1, "places": 1, "water": 1, "land": 1}
    assert {"osm_id", "highway", "name", "ref", "ice_road"} <= set(_fields(ex / "highways.fgb"))
    assert sorted(_column(ex / "highways.fgb", "highway")) == ["primary", "track"]
    assert _column(ex / "highways.fgb", "ice_road") in (["yes", None], [None, "yes"])
    assert _column(ex / "boundaries.fgb", "ISO3166-1") == ["XX"] and _column(ex / "boundaries.fgb", "admin_level") == ["2"]
    # The maritime admin_level 2 relation is filtered out: only the administrative one survives.
    assert _column(ex / "boundaries.fgb", "name") == ["Testland"]
    assert meta["level2_iso_codes"] == ["XX"]
    assert _column(ex / "places.fgb", "name") == ["Kaimas"]
    assert _column(ex / "water.fgb", "name") == ["Ezeras"]
    assert read_info(str(ex / "water.fgb"))["geometry_type"] in ("Polygon", "MultiPolygon")
    assert (ws.shared_dir() / "land.fgb").is_file() and read_info(str(ws.shared_dir() / "land.fgb"))["features"] == 1
    # Every layer is handed on as a VRT, whichever branch produced it, land included.
    for layer in ("highways", "boundaries", "places", "water"):
        assert _vrt_count(ex / f"{layer}.vrt", layer) == meta["counts"][layer]
    assert _vrt_count(ws.shared_dir() / "land.vrt", "land") == 1
    assert not list(ex.glob("*.geojsonseq")) and not list(ex.glob("*-filtered.pbf"))
    # The chunked conversion leaves no chunks, no chunk logs and no scratch merge VRT behind.
    assert not list(ex.glob("*.part-*")) and not list(ex.glob("*.merge.vrt"))
    # Every artefact that survives carries its done marker, so a rerun can skip it.
    assert {p.name for p in ex.glob("*.ok")} == {"filtered.pbf.ok"} | {
        f"{layer}.{kind}.ok" for layer in ("highways", "boundaries", "places", "water")
        for kind in ("pbf", "fgb", "vrt")}


def test_extract_large_layer_keeps_chunks_behind_vrt(tmp_path, tiny_pbf, cfg, log, monkeypatch):
    """Above the merge cap the chunks stay put and the VRT unions them: a single FlatGeobuf that big grows
    a packed R-tree GDAL cannot read back (issue #16)."""
    monkeypatch.setattr(extract, "CHUNK_BYTES", 1)      # one feature per chunk
    monkeypatch.setattr(extract, "MERGE_MAX_FEATURES", 1)
    ws = _workspace(tmp_path, tiny_pbf)
    meta = extract.run(cfg, ws, log, land_zip=_land_zip(tmp_path))
    ex = ws.dir("extract")
    assert meta["counts"]["highways"] == 2
    assert not (ex / "highways.fgb").exists()
    assert sorted(p.name for p in ex.glob("highways.part-*.fgb")) == [
        "highways.part-0000.fgb", "highways.part-0001.fgb"]
    assert _vrt_count(ex / "highways.vrt", "highways") == 2
    fields = set(read_info(str(ex / "highways.vrt"), layer="highways")["fields"])
    assert {"osm_id", "highway", "name", "ref", "ice_road"} <= fields
    # The chunk text and per chunk logs still go, only the chunk FlatGeobufs stay.
    assert not list(ex.glob("*.geojsonseq")) and not list(ex.glob("*.part-*.log"))
    # The one-feature layers are under the cap and still merge into a single file.
    assert (ex / "water.fgb").is_file() and not list(ex.glob("water.part-*"))


def test_extract_upgrades_a_layer_done_by_the_old_layout(tmp_path, tiny_pbf, cfg, log, monkeypatch):
    """A layer finished before VRT handles existed keeps its FlatGeobuf and only gains the VRT: re-exporting
    it would cost an hour on a continent."""
    ws = _workspace(tmp_path, tiny_pbf)
    ex = ws.dir("extract")
    write_fgb(ex / "water.fgb", "water", [shapely.box(25.100, 55.040, 25.132, 55.058)],
              {"osm_id": [104], "natural": ["water"], "water": ["lake"], "name": ["Ezeras"]})
    (ex / "water.fgb.ok").touch()

    calls: list[list[str]] = []
    real = extract.osmium

    def record(args, *a, **kw):
        calls.append([str(x) for x in args])
        return real(args, *a, **kw)

    monkeypatch.setattr(extract, "osmium", record)
    meta = extract.run(cfg, ws, log, land_zip=_land_zip(tmp_path))

    def exported(layer: str) -> bool:
        return any(c[0] == "export" and any(f"{layer}.geojsonseq" in x for x in c) for c in calls)

    assert (ex / "water.vrt").is_file() and (ex / "water.vrt.ok").is_file()
    assert _vrt_count(ex / "water.vrt", "water") == 1 and meta["counts"]["water"] == 1
    assert _column(ex / "water.fgb", "name") == ["Ezeras"]
    assert not exported("water"), "the finished layer must not be exported again"
    assert exported("highways"), "the unfinished layers must still be exported"


def test_extract_rerun_skips_osmium_when_markers_exist(tmp_path, tiny_pbf, cfg, log, monkeypatch):
    """Every osmium step on a continent costs minutes to an hour; a rerun must resume, not redo."""
    ws = _workspace(tmp_path, tiny_pbf)
    land_zip = _land_zip(tmp_path)
    first = extract.run(cfg, ws, log, land_zip=land_zip)

    def refuse(*args, **kwargs):
        raise AssertionError("osmium must not run")

    monkeypatch.setattr(extract, "osmium", refuse)
    again = extract.run(cfg, ws, log, land_zip=land_zip)
    assert again["counts"] == first["counts"]
    assert again["level2_iso_codes"] == first["level2_iso_codes"]


def test_extract_with_one_feature_per_chunk_keeps_every_row_and_field(tmp_path, tiny_pbf, cfg, log, monkeypatch):
    """CHUNK_BYTES of 1 puts every feature in its own chunk, so the VRT union merges schemas that differ:
    the highway chunks carry name / ice_road+ref respectively and both sets of fields must survive. It also
    pins the empty-chunk arithmetic: the boundaries chunk holding the maritime relation is emptied by the
    -where, and an empty FlatGeobuf reports a feature count of -1 unless the count is forced."""
    monkeypatch.setattr(extract, "CHUNK_BYTES", 1)
    ws = _workspace(tmp_path, tiny_pbf)
    meta = extract.run(cfg, ws, log, land_zip=_land_zip(tmp_path))
    ex = ws.dir("extract")
    assert meta["counts"] == {"highways": 2, "boundaries": 1, "places": 1, "water": 1, "land": 1}
    assert {"osm_id", "highway", "name", "ref", "ice_road"} <= set(_fields(ex / "highways.fgb"))
    assert sorted(_column(ex / "highways.fgb", "highway")) == ["primary", "track"]
    assert sorted(v for v in _column(ex / "highways.fgb", "name") if v) == ["Main road"]
    assert sorted(v for v in _column(ex / "highways.fgb", "ref") if v) == ["T1"]
    assert not list(ex.glob("*.part-*")) and not list(ex.glob("*.merge.vrt")) and not list(ex.glob("*.geojsonseq"))
    assert _vrt_count(ex / "highways.vrt", "highways") == 2


def test_extract_rebuilds_a_merged_layer_that_is_over_the_cap(tmp_path, tiny_pbf, cfg, log, monkeypatch):
    """The layer Europe already merged is over the cap and unreadable. Wrapping it in a VRT would hand the
    broken file to every later stage, so an over-cap FlatGeobuf on disk is dropped and rebuilt (issue #16)."""
    monkeypatch.setattr(extract, "MERGE_MAX_FEATURES", 0)
    ws = _workspace(tmp_path, tiny_pbf)
    ex = ws.dir("extract")
    write_fgb(ex / "water.fgb", "water", [shapely.box(25.100, 55.040, 25.132, 55.058)],
              {"osm_id": [104], "natural": ["water"], "water": ["lake"], "name": ["Stale"]})
    (ex / "water.fgb.ok").touch()

    meta = extract.run(cfg, ws, log, land_zip=_land_zip(tmp_path))

    assert not (ex / "water.fgb").exists() and not (ex / "water.fgb.ok").exists()
    assert _vrt_count(ex / "water.vrt", "water") == 1 and meta["counts"]["water"] == 1
    # Rebuilt from the PBF, so the stale row is gone.
    assert _column(ex / "water.part-0000.fgb", "name") == ["Ezeras"]


def test_chunk_lines_splits_on_line_boundaries_and_roundtrips(tmp_path):
    src = tmp_path / "in.geojsonseq"
    lines = [b"a" * 5, b"b" * 30, b"c" * 1, b"d" * 12, b"e" * 7, b"f" * 40, b"g" * 3]
    src.write_bytes(b"".join(line + b"\n" for line in lines))
    chunk_bytes = 20

    parts = chunk_lines(src, chunk_bytes, tmp_path / "out")

    assert [p.name for p in parts] == [f"out.part-{i:04d}.geojsonseq" for i in range(len(parts))]
    assert b"".join(p.read_bytes() for p in parts) == src.read_bytes()
    assert all(p.read_bytes().endswith(b"\n") for p in parts)
    for part in parts:
        data = part.read_bytes()
        # Over the cap only when the chunk is one line that does not fit on its own.
        assert len(data) <= chunk_bytes or data.count(b"\n") == 1
    assert any(len(p.read_bytes()) > chunk_bytes for p in parts), "the oversized-line case must be exercised"


def test_chunk_lines_on_an_empty_file_produces_no_chunks(tmp_path):
    src = tmp_path / "in.geojsonseq"
    src.write_bytes(b"")
    assert chunk_lines(src, 1024, tmp_path / "out") == []


def test_osmium_failure_raises_with_command_in_message(tmp_path, log):
    with pytest.raises(ToolError) as e:
        osmium(["cat", tmp_path / "missing.osm.pbf", "-o", tmp_path / "out.pbf"], log)
    assert "osmium cat" in str(e.value) and "missing.osm.pbf" in str(e.value)
