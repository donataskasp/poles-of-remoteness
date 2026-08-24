"""End to end cover for the publish stage on a tiny but complete workspace: real GDAL, a real tiler, real
pmtiles, a real process pool, and R2 stubbed at the module boundary."""
import dataclasses
import json
import logging
import os
import sqlite3
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
import shapely
from pyproj import Transformer
from rasterio.io import MemoryFile
from shapely.geometry import LineString, box

from poles import publish
from poles.classes import ClassTable, default_edges
from poles.config import load_region
from poles.errors import PolesError
from poles.grid import Frame, create_raster
from poles.publish import r2 as r2mod
from poles.publish import tiles as tilesmod
from poles.roads import build_tiles
from poles.workspace import Workspace
from tests.helpers import write_fgb

# A detail raster carries its georeference in its sidecar, not in the PNG.
pytestmark = pytest.mark.filterwarnings("ignore::rasterio.errors.NotGeoreferencedWarning")

# The frame of test_publish_raster: 40 by 32 cells of 250 m in EPSG:3035, around 24E 55N.
FRAME = Frame(crs="EPSG:3035", res=250, x0=5_300_000, y1=3_660_000, width=40, height=32)


def _table(cfg):
    """The table the stage builds for this region, so the tests class distances exactly as it does."""
    return ClassTable(cfg.class_table) if cfg.class_table else ClassTable()


# A class no distance on this frame produces (the grid tops out around class 103), so a pixel carrying it
# came from somewhere other than the source raster.
POISON = 200


def _local_run(cfg, ws, log, monkeypatch):
    """The stage as far as R2: every local artefact is built, then the missing configuration stops it."""
    for name in r2mod.ENV_NAMES.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("POLES_WORKERS", "2")
    with pytest.raises(r2mod.PublishError):
        publish.run(cfg, ws, log)


def _z9_pngs(out, scenario="A"):
    return sorted((out / f"tiles_{scenario}" / "9").rglob("*.png"))


def _png_bands(png):
    with rasterio.open(png) as ds:
        return ds.read()


def _mbtile(mbtiles, z, x, y):
    """One tile out of the packed archive, by XYZ coordinates (the archive stores TMS rows)."""
    con = sqlite3.connect(mbtiles)
    try:
        blob = con.execute("SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                           (z, x, (1 << z) - 1 - y)).fetchone()[0]
    finally:
        con.close()
    with MemoryFile(blob) as mem, mem.open() as ds:
        return ds.read(1)


def _mtimes(*paths):
    return {p.name: p.stat().st_mtime_ns for p in paths}


def _pole(rank, lat, lon, dist):
    return {"rank": rank, "lat": lat, "lon": lon, "dist_m": dist,
            "nearest_way": {"id": 1, "highway": "unclassified", "name": None, "ref": None, "country": "lt"},
            "nearest_place": {"name": "Kaunas", "type": "city", "dist_m": 5000.0, "lat": 54.9, "lon": 23.9},
            "detail": None, "warnings": []}


@pytest.fixture
def workspace(tmp_path, regions_dir):
    # edge_mask_m: the 10 km test frame must not be all edge band. top_n: two poles are the whole set here.
    cfg = dataclasses.replace(load_region(regions_dir / "europe.yaml"), edge_mask_m=1_000, top_n=2)
    ws = Workspace(tmp_path / "work", cfg.id, "2026-01-01")
    to_ll = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    # fetch: one source polygon covering the frame minus a 1 km rim
    fetch = ws.dir("fetch")
    rim = box(FRAME.x0 + 1_000, FRAME.y0 + 1_000, FRAME.x1 - 1_000, FRAME.y1 - 1_000)
    ring = [to_ll.transform(x, y) for x, y in rim.exterior.coords]
    (fetch / "r.poly").write_text("r\n1\n" + "".join(f"  {lon} {lat}\n" for lon, lat in ring) + "END\nEND\n")
    (fetch / "snapshot.json").write_text(json.dumps({"region": cfg.id, "snapshot": "2026-01-01", "created_at": "x", "sources": [
        {"url": "https://example.org/r.pbf", "role": "primary", "file": "r.pbf", "size": 1, "md5": "m", "sha256": "s",
         "last_modified": "2026-01-01T00:00:00+00:00", "poly": "r.poly"}]}))
    # grid: distances rising northwards from a road along the southern frame edge; all land
    grid = ws.dir("grid")
    (grid / "frame.json").write_text(json.dumps(FRAME.to_dict()))
    rows = (np.arange(FRAME.height)[::-1] + 0.5) * FRAME.res
    dist = np.repeat(rows[:, None], FRAME.width, axis=1).astype(np.float32)
    for name in ("dist_A", "dist_B"):
        create_raster(FRAME, grid / f"{name}.tif", "float32", None)
        with rasterio.open(grid / f"{name}.tif", "r+") as ds:
            ds.write(dist, 1)
    create_raster(FRAME, grid / "land.tif", "uint8", None)
    with rasterio.open(grid / "land.tif", "r+") as ds:
        ds.write(np.ones((FRAME.height, FRAME.width), np.uint8), 1)
    # poles: unit lt in the middle, road along the south edge, two poles per scenario
    poles_dir = ws.dir("poles")
    unit_3035 = box(FRAME.x0 + 2_000, FRAME.y0 + 2_000, FRAME.x1 - 2_000, FRAME.y1 - 2_000)
    unit = shapely.transform(unit_3035, lambda c: np.column_stack(to_ll.transform(c[:, 0], c[:, 1])))
    write_fgb(poles_dir / "units.fgb", "units", [shapely.MultiPolygon([unit])],
              {"code": ["lt"], "name": ["Lietuva"], "name_en": ["Lithuania"], "osm_id": [72596], "country": ["lt"], "idx": [1],
               "transcontinental": [0], "closed_by_edge": [0]})
    (poles_dir / "units.json").write_text(json.dumps({"units": [{
        "code": "lt", "name": "Lietuva", "name_en": "Lithuania", "osm_id": 72596, "country": "lt", "index": 1, "area_km2": 1.0,
        "cells": 10, "transcontinental": False, "closed_by_edge": False, "bbox": list(unit.bounds), "window": [0, 0, 1, 1]}]}))
    land = shapely.transform(box(FRAME.x0, FRAME.y0, FRAME.x1, FRAME.y1), lambda c: np.column_stack(to_ll.transform(c[:, 0], c[:, 1])))
    write_fgb(poles_dir / "land_idx.fgb", "land", [land], {"id": [1]})
    write_fgb(poles_dir / "water_big.fgb", "water", [box(0, 0, 0.001, 0.001)], {"id": [1]})
    road = shapely.transform(LineString([(FRAME.x0 - 50_000, FRAME.y0), (FRAME.x1 + 50_000, FRAME.y0)]),
                             lambda c: np.column_stack(to_ll.transform(c[:, 0], c[:, 1])))
    # unclassified, not track: the detail rasters query the tiles with the scenario's own where clause, so a
    # track-only region would leave scenario B with no road at all.
    write_fgb(poles_dir / "roads_src.fgb", "highways", [road],
              {"osm_id": [1], "highway": ["unclassified"], "name": [None], "ref": [None]})
    build_tiles(poles_dir / "roads_src.fgb", "highways", poles_dir / "roads", logging.getLogger("t"), tile_deg=5.0)
    cx, cy = unit_3035.centroid.x, FRAME.y1 - 3_000
    lon1, lat1 = to_ll.transform(cx, cy)
    lon2, lat2 = to_ll.transform(cx + 1_000, cy - 500)
    d1, d2 = cy - FRAME.y0, cy - 500 - FRAME.y0
    for s in ("A", "B"):
        (poles_dir / f"{s}.json").write_text(json.dumps([{"unit": "lt", "poles": [_pole(1, lat1, lon1, d1), _pole(2, lat2, lon2, d2)], "reason": None}]))
    ws.mark_done("poles", {})
    # validate: rank 1 of scenario B withheld
    val = ws.dir("validate")
    (val / "report.json").write_text(json.dumps({"region": cfg.id, "snapshot": "2026-01-01", "generated_at": "x", "summary": {}, "results": [],
                                                 "excluded": [{"unit": "lt", "scenario": "B", "rank": 1, "lat": lat1, "lon": lon1, "dist_m": d1, "details": {}}]}))
    (val / "report.html").write_text("<p>report</p>")
    (val / "contact-sheet.html").write_text("<p>sheet</p>")
    ws.mark_done("validate", {})
    return cfg, ws


def _r2_env(monkeypatch, tmp_path):
    for key, value in {"POLES_R2_ACCOUNT_ID": "acct", "POLES_R2_BUCKET": "b", "POLES_R2_TOKEN_FILE": str(tmp_path / "t"),
                       "POLES_R2_ACCESS_KEY_ID_FILE": str(tmp_path / "k"), "POLES_R2_SECRET_FILE": str(tmp_path / "s")}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv(r2mod.ENV_BASE, raising=False)
    for f in ("t", "k", "s"):
        (tmp_path / f).write_text("x")


def test_refuses_without_validate(tmp_path, regions_dir, log):
    cfg = load_region(regions_dir / "europe.yaml")
    ws = Workspace(tmp_path / "work", cfg.id, "2026-01-01")
    with pytest.raises(PolesError, match="validate"):
        publish.run(cfg, ws, log)


def test_refuses_a_validate_report_without_an_excluded_list(workspace, log):
    """An older report has no exclusion list, and reading one as an empty list would publish poles validation
    refused. The stage stops before it builds anything."""
    cfg, ws = workspace
    report = json.loads((ws.dir("validate") / "report.json").read_text())
    report.pop("excluded")
    (ws.dir("validate") / "report.json").write_text(json.dumps(report))
    with pytest.raises(PolesError, match="excluded"):
        publish.run(cfg, ws, log)
    assert not (ws.dir("publish") / "explore_A.tif").exists()


def test_a_dirty_tree_publishes_without_a_pipeline_commit(log, monkeypatch, caplog):
    """The manifest names the commit that produced the publish. A hash that does not describe the code that ran
    is worse than no hash, so a dirty tree, and a machine without git at all, record none."""
    answers = {"rev-parse": "abc123\n", "status": ""}

    def git(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout=answers[cmd[1]])

    monkeypatch.setattr(publish.subprocess, "run", git)
    assert publish._pipeline_commit(log) == "abc123"
    answers["status"] = " M pipeline/poles/publish/__init__.py\n"
    with caplog.at_level(logging.WARNING, logger="poles.test"):
        assert publish._pipeline_commit(log) is None
    assert "dirty" in caplog.text

    def no_git(cmd, **kwargs):
        raise OSError("git is not installed")

    monkeypatch.setattr(publish.subprocess, "run", no_git)
    assert publish._pipeline_commit(log) is None


def test_builds_local_artefacts_then_names_the_missing_r2_config(workspace, log, monkeypatch):
    cfg, ws = workspace
    for name in r2mod.ENV_NAMES.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("POLES_WORKERS", "2")
    with pytest.raises(r2mod.PublishError, match="POLES_R2_ACCOUNT_ID"):
        publish.run(cfg, ws, log)
    out = ws.dir("publish")
    for name in ("explore_A.tif", "explore_A_3857.tif", "A.pmtiles", "explore_B.tif", "B.pmtiles"):
        assert (out / name).exists(), name
    assert (out / "detail" / "lt" / "A-1.png").exists() and (out / "detail" / "lt" / "A-2.json").exists()
    assert (out / "detail" / "lt" / "B-1.png").exists() and not (out / "detail" / "lt" / "B-2.png").exists()
    assert not ws.is_done("publish")
    with rasterio.open(out / "explore_A.tif") as ds:
        cls = ds.read(1)
    assert cls[16, 20] not in (254, 255) and cls[0, 20] == 255 and cls[2, 20] == 255   # rim outside the source polygon
    assert (out / "inside.tif.ok").exists()


def test_resume_after_a_partial_local_run_keeps_the_artefacts(workspace, log, monkeypatch, tmp_path):
    cfg, ws = workspace
    for name in r2mod.ENV_NAMES.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("POLES_WORKERS", "2")
    with pytest.raises(r2mod.PublishError):
        publish.run(cfg, ws, log)
    out = ws.dir("publish")
    before = {p.name: p.stat().st_mtime_ns for p in (out / "explore_A.tif", out / "A.pmtiles",
                                                     out / "detail" / "lt" / "A-1.png")}
    _r2_env(monkeypatch, tmp_path)
    monkeypatch.setattr(r2mod, "ensure_bucket", lambda cfg_, log_, api_base=None: "https://pub-test.r2.dev")
    monkeypatch.setattr(r2mod, "s3_client", lambda cfg_, endpoint_url=None: object())
    monkeypatch.setattr(r2mod, "upload_tree", lambda client, bucket, items, log_, workers=8, forced=False: {"uploaded": len(items), "skipped": 0, "bytes": 1})
    monkeypatch.setattr(r2mod, "verify_head", lambda base, keys, range_keys, log_, workers=8: {"at": "2026-01-02T00:00:00+00:00", "keys": len(keys), "range_ok": len(range_keys)})
    ws.site_dir = None                                   # --no-write-site
    meta = publish.run(cfg, ws, log)
    assert {p.name: p.stat().st_mtime_ns for p in (out / "explore_A.tif", out / "A.pmtiles",
                                                   out / "detail" / "lt" / "A-1.png")} == before
    assert meta["detail"]["skipped"] == 3 and meta["site_dir"] is None
    assert json.loads((out / "site" / "manifest.json").read_text())["regions"][cfg.id]["snapshot"] == "2026-01-01"
    assert (out / "site" / "regions.json").exists()
    assert not (tmp_path / "site_data").exists()


def test_force_clears_the_markers_and_rebuilds(workspace, log, monkeypatch, tmp_path):
    cfg, ws = workspace
    _r2_env(monkeypatch, tmp_path)
    monkeypatch.setenv("POLES_WORKERS", "2")
    monkeypatch.setattr(r2mod, "ensure_bucket", lambda cfg_, log_, api_base=None: "https://pub-test.r2.dev")
    monkeypatch.setattr(r2mod, "s3_client", lambda cfg_, endpoint_url=None: object())
    monkeypatch.setattr(r2mod, "upload_tree", lambda client, bucket, items, log_, workers=8, forced=False: {"uploaded": len(items), "skipped": 0, "bytes": 1})
    monkeypatch.setattr(r2mod, "verify_head", lambda base, keys, range_keys, log_, workers=8: {"at": "x", "keys": len(keys), "range_ok": len(range_keys)})
    ws.site_dir = None
    publish.run(cfg, ws, log)
    out = ws.dir("publish")
    watched = [out / "explore_A.tif", out / "A.pmtiles", out / "detail" / "lt" / "A-1.png"]
    before = [p.stat().st_mtime_ns for p in watched]
    ws.forced = True
    meta = publish.run(cfg, ws, log)
    assert [p.stat().st_mtime_ns for p in watched] != before
    assert meta["detail"]["skipped"] == 0 and meta["detail"]["count"] == 3


def test_force_recuts_the_z9_tiles_it_would_otherwise_resume_over(workspace, log, monkeypatch):
    """`gdal raster tile --resume` regenerates only missing files, so a forced rerun that kept the tile
    directory would pack the previous run's pixels into a fresh archive and publish new counts over them."""
    cfg, ws = workspace
    _local_run(cfg, ws, log, monkeypatch)
    out = ws.dir("publish")
    png = _z9_pngs(out)[0]
    good = _png_bands(png)
    x, y = int(png.parent.name), int(png.stem)
    png.write_bytes(tilesmod._grey_png(np.full((tilesmod.TILE_PX, tilesmod.TILE_PX), POISON, np.uint8)))
    ws.forced = True
    _local_run(cfg, ws, log, monkeypatch)
    assert np.array_equal(_png_bands(png), good)
    assert POISON not in np.unique(_mbtile(out / "A.mbtiles", 9, x, y))


def test_a_changed_class_table_rebuilds_the_explore_chain_without_force(workspace, log, monkeypatch):
    """No marker records what an artefact was built from, so without the input stamp a table change would
    publish new class edges in regions.json over pixels classed with the old ones."""
    cfg, ws = workspace
    _local_run(cfg, ws, log, monkeypatch)
    out = ws.dir("publish")
    watched = (out / "explore_A.tif", out / "explore_A_3857.tif", out / "A.pmtiles")
    before = _mtimes(*watched)
    png = _z9_pngs(out)[0]
    before_tile = _png_bands(png)
    with rasterio.open(out / "explore_A.tif") as ds:
        before_cls = ds.read(1)
    wider = dataclasses.replace(cfg, class_table=[0, *(v * 2 for v in default_edges()[1:])])
    _local_run(wider, ws, log, monkeypatch)
    assert _mtimes(*watched) != before
    with rasterio.open(out / "explore_A.tif") as ds:
        assert not np.array_equal(ds.read(1), before_cls)
    assert not np.array_equal(_png_bands(png), before_tile)   # the tiles the site draws, not only the raster
    assert json.loads((out / "inputs.json").read_text())["class_edges"] == wider.class_table


def test_a_rebuilt_grid_raster_rebuilds_the_explore_chain(workspace, log, monkeypatch):
    """The same family as issue #18: a rerun of an earlier stage must not leave the publish artefacts behind."""
    cfg, ws = workspace
    _local_run(cfg, ws, log, monkeypatch)
    out = ws.dir("publish")
    with rasterio.open(out / "explore_A.tif") as ds:
        before = ds.read(1)
    with rasterio.open(ws.dir("grid") / "dist_A.tif", "r+") as ds:   # as a rerun of the grid stage leaves it
        ds.write(np.full((FRAME.height, FRAME.width), 30_000.0, np.float32), 1)
    _local_run(cfg, ws, log, monkeypatch)
    with rasterio.open(out / "explore_A.tif") as ds:
        assert not np.array_equal(ds.read(1), before)


def test_a_missing_input_stamp_adopts_the_artefacts_on_disk(workspace, log, monkeypatch):
    """The stamp arrives after the artefacts do. Adopting them is what keeps a finished run from throwing
    away a day of tiles to learn that nothing changed."""
    cfg, ws = workspace
    _local_run(cfg, ws, log, monkeypatch)
    out = ws.dir("publish")
    before = _mtimes(out / "explore_A.tif", out / "A.pmtiles", out / "explore_B.tif")
    (out / "inputs.json").unlink()
    _local_run(cfg, ws, log, monkeypatch)
    assert _mtimes(out / "explore_A.tif", out / "A.pmtiles", out / "explore_B.tif") == before
    stamp = json.loads((out / "inputs.json").read_text())
    assert stamp["class_edges"] == ClassTable().edges and stamp["edge_mask_m"] == cfg.edge_mask_m


def test_detail_rebuilds_when_the_published_set_changes(workspace, log, monkeypatch):
    """A detail raster is named by its post-exclusion rank, so a different exclusion list renames the pictures.
    Without the stamp the rerun would keep the old image under the new rank's name and say nothing."""
    cfg, ws = workspace
    for name in r2mod.ENV_NAMES.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("POLES_WORKERS", "2")
    with pytest.raises(r2mod.PublishError):
        publish.run(cfg, ws, log)
    b1 = ws.dir("publish") / "detail" / "lt" / "B-1.png"
    with rasterio.open(b1) as ds:
        before = ds.read(1)
    before_mtime = b1.stat().st_mtime_ns
    # validate now withholds rank 2 instead of rank 1, so B-1 must become the picture of the other pole
    kept = json.loads((ws.dir("poles") / "B.json").read_text())[0]["poles"][0]
    dropped = json.loads((ws.dir("poles") / "B.json").read_text())[0]["poles"][1]
    report = json.loads((ws.dir("validate") / "report.json").read_text())
    report["excluded"][0].update(rank=2, lat=dropped["lat"], lon=dropped["lon"], dist_m=dropped["dist_m"])
    (ws.dir("validate") / "report.json").write_text(json.dumps(report))
    with pytest.raises(r2mod.PublishError):
        publish.run(cfg, ws, log)
    assert b1.stat().st_mtime_ns != before_mtime
    with rasterio.open(b1) as ds:
        after = ds.read(1)
    assert not np.array_equal(after, before)
    n = int(cfg.detail_window_m // cfg.detail_res_m) // 2
    assert abs(int(after[n, n]) - int(_table(cfg).to_class(kept["dist_m"]))) <= 1
    stamp = json.loads((ws.dir("publish") / "detail" / "published.json").read_text())
    assert ["B", "lt", 1, kept["lat"], kept["lon"]] in stamp["poles"] and len(stamp["poles"]) == 3
    assert stamp["class_edges"] == _table(cfg).edges
    assert len(stamp["edge_band_sha256"]) == 64


def test_full_run_with_r2_mocked_writes_site_and_done(workspace, log, monkeypatch, tmp_path):
    cfg, ws = workspace
    _r2_env(monkeypatch, tmp_path)
    monkeypatch.setenv("POLES_WORKERS", "2")
    uploaded, verified = [], {}
    monkeypatch.setattr(r2mod, "ensure_bucket", lambda cfg_, log_, api_base=None: "https://pub-test.r2.dev")
    monkeypatch.setattr(r2mod, "s3_client", lambda cfg_, endpoint_url=None: object())
    monkeypatch.setattr(r2mod, "upload_tree", lambda client, bucket, items, log_, workers=8, forced=False: (uploaded.extend(items), {"uploaded": len(items), "skipped": 0, "bytes": 1})[1])
    monkeypatch.setattr(r2mod, "verify_head", lambda base, keys, range_keys, log_, workers=8: verified.update(base=base, keys=keys, range_keys=range_keys) or {"at": "2026-01-02T00:00:00+00:00", "keys": len(keys), "range_ok": len(range_keys)})
    ws.site_dir = tmp_path / "site_data"
    meta = publish.run(cfg, ws, log)
    keys = sorted(k for _, k in uploaded)
    assert f"{cfg.id}/2026-01-01/A.pmtiles" in keys and f"{cfg.id}/2026-01-01/detail/lt/A-1.png" in keys
    assert f"{cfg.id}/2026-01-01/validation/contact-sheet.html" in keys
    assert verified["base"] == "https://pub-test.r2.dev" and sorted(verified["keys"]) == keys
    assert verified["range_keys"] == [f"{cfg.id}/2026-01-01/A.pmtiles", f"{cfg.id}/2026-01-01/B.pmtiles"]
    site = ws.dir("publish") / "site"
    regions = json.loads((site / "regions.json").read_text())
    assert regions["regions"][0]["r2_base"] == "https://pub-test.r2.dev" and regions["regions"][0]["units_count"] == 1
    unit = json.loads((site / cfg.id / "units" / "lt.json").read_text())
    assert [p["rank"] for p in unit["B"]["poles"]] == [1] and unit["B"]["withheld"] == 1 and unit["A"]["withheld"] == 0
    assert unit["B"]["poles"][0]["detail"] == "detail/lt/B-1"
    assert (ws.site_dir / "regions.json").exists() and (ws.site_dir / cfg.id / "units.json").exists()
    assert meta["archives"]["A"]["max_zoom"] == 9 and meta["detail"]["count"] == 3 and meta["upload"]["uploaded"] == len(keys)
    assert meta["verify"]["keys"] == len(keys) and meta["r2_base"] == "https://pub-test.r2.dev"
    # the detail raster at the pole's own pixel agrees with the coarse grid to one class
    with rasterio.open(ws.dir("publish") / "detail" / "lt" / "A-1.png") as ds:
        arr = ds.read(1)
    d1 = json.loads((ws.dir("poles") / "A.json").read_text())[0]["poles"][0]["dist_m"]
    n = int(cfg.detail_window_m // cfg.detail_res_m) // 2
    assert abs(int(arr[n, n]) - int(_table(cfg).to_class(d1))) <= 1


def test_upload_set_covers_the_archives_details_and_validation(workspace):
    cfg, ws = workspace
    out = ws.dir("publish")
    (out / "detail" / "lt").mkdir(parents=True)
    for name in ("A-1.png", "A-1.json", "A-1.png.aux.xml"):
        (out / "detail" / "lt" / name).write_text("x")
    (out / "detail" / "published.json").write_text("[]")     # bookkeeping, not an object of the site
    items = publish.upload_set(ws, cfg.id, ws.snapshot)
    keys = [k for _, k in items]
    assert keys == [f"{cfg.id}/2026-01-01/A.pmtiles", f"{cfg.id}/2026-01-01/B.pmtiles",
                    f"{cfg.id}/2026-01-01/detail/lt/A-1.json", f"{cfg.id}/2026-01-01/detail/lt/A-1.png",
                    f"{cfg.id}/2026-01-01/validation/report.json", f"{cfg.id}/2026-01-01/validation/report.html",
                    f"{cfg.id}/2026-01-01/validation/contact-sheet.html"]
    assert items[0][0] == out / "A.pmtiles" and items[-1][0] == ws.dir("validate") / "contact-sheet.html"


def test_cli_flags(monkeypatch):
    from poles.cli import build_parser
    monkeypatch.delenv("POLES_SITE_DIR", raising=False)
    args = build_parser().parse_args(["run", "europe", "--stage", "publish", "--site-dir", "/x/site/data", "--no-write-site"])
    assert args.site_dir == "/x/site/data" and args.no_write_site is True
    args = build_parser().parse_args(["run", "europe"])
    assert args.no_write_site is False and args.site_dir.endswith(os.path.join("site", "data"))
