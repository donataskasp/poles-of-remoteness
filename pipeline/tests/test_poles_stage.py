import json
import logging
import threading
import time
from dataclasses import replace
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import numpy as np
import pytest
import rasterio
import shapely
from pyogrio.raw import read
from pyproj import Transformer
from shapely.geometry import LineString, MultiPolygon, Polygon, box

from poles import poles as poles_mod
from poles.areas import AreaField
from poles.attrib import Countries
from poles.boundaries import AdminArea
from poles.candidates import Refined
from poles.errors import PolesError
from poles.grid import Frame, create_raster, write_float_tif
from poles.poles import (Prepared, UnitJob, _allowed_factory, _bbox_window, _search_pending, _unit_meta,
                         _unit_windows, validate_poles_json, write_water_big)
from poles.extract import MARKER
from poles.refine import RefinedPole, UtmRoads, utm_epsg
from poles.roads import RoadSet
from poles.units import Unit, land_tif, low_tif, water_tif, write_units
from poles.workspace import Workspace
from tests.helpers import write_fgb


def _p(lat, lon, d):
    return {"rank": 0, "lat": lat, "lon": lon, "dist_m": d, "nearest_way": {"id": 1, "highway": "track", "name": None, "ref": None, "country": "lt"},
            "nearest_place": None, "island_km2": None, "detail": None, "warnings": []}


def test_stage_output_schema():
    good = [{"unit": "lt", "poles": [_p(54.0, 24.0, 5000) | {"rank": 1}], "reason": None}]
    validate_poles_json(good, top_n=1)
    short = [{"unit": "lt", "poles": [_p(54.0, 24.0, 5000) | {"rank": 1}], "reason": "only 1 pole(s)"}]
    validate_poles_json(short, top_n=10)                       # fewer than top_n is fine once it is explained
    with pytest.raises(ValueError, match="rank"):
        validate_poles_json([{"unit": "lt", "poles": [_p(54.0, 24.0, 5000) | {"rank": 2}], "reason": None}], top_n=1)
    with pytest.raises(ValueError, match="reason"):
        validate_poles_json([{"unit": "lt", "poles": [], "reason": None}], top_n=10)
    with pytest.raises(ValueError, match="dist_m"):
        validate_poles_json([{"unit": "lt", "poles": [_p(54.0, 24.0, -1) | {"rank": 1}], "reason": None}], top_n=1)


def test_unit_windows_are_the_tight_row_col_box_of_each_index(tmp_path):
    frame = Frame("EPSG:4326", 1.0, 0.0, 6.0, 6, 6)
    tif = create_raster(frame, tmp_path / "units.tif", dtype="int16")
    with rasterio.open(tif, "r+") as ds:
        a = np.zeros((6, 6), dtype="int16")
        a[1, 2] = a[3, 4] = 1
        a[5, 0] = 2
        ds.write(a, 1)
    assert _unit_windows(tif) == {1: (1, 2, 3, 3), 2: (5, 0, 1, 1)}


def test_unit_windows_cover_every_raster_a_unit_has_cells_in(tmp_path):
    """A cell two units touch is in the top raster under one index and in the companion under the other, so
    a window taken from one raster alone would cut off the cells the other holds."""
    frame = Frame("EPSG:4326", 1.0, 0.0, 6.0, 6, 6)
    hi = create_raster(frame, tmp_path / "units.tif", dtype="int16")
    lo = create_raster(frame, low_tif(tmp_path / "units.tif"), dtype="int16")
    with rasterio.open(hi, "r+") as ds:
        a = np.zeros((6, 6), dtype="int16")
        a[1, 2] = 1
        ds.write(a, 1)
    with rasterio.open(lo, "r+") as ds:
        a = np.zeros((6, 6), dtype="int16")
        a[4, 5] = 1
        ds.write(a, 1)
    assert _unit_windows(hi, lo) == {1: (1, 2, 4, 4)}


def test_allowed_needs_the_unit_and_land_and_no_big_water(tmp_path):
    unit = Unit("aa", "Aa", "Aa", 1, "aa", MultiPolygon([box(0, 0, 2, 2)]), False, 1)
    land = write_fgb(tmp_path / "land.fgb", "land", [box(-1, -1, 1.5, 3)], {"osm_id": [1]})
    water = write_fgb(tmp_path / "water.fgb", "water", [box(0.2, 0.2, 0.4, 0.4)], {"osm_id": [1]})
    allowed = _allowed_factory(unit, land, water)
    lons = np.array([1.0, 0.3, 1.8, 2.5])          # in the unit on land; in the lake; off the land polygon; outside the unit
    lats = np.array([1.0, 0.3, 1.0, 1.0])
    assert allowed(lons, lats).tolist() == [True, False, False, False]


def test_allowed_reads_only_the_two_windows_a_unit_on_the_line_covers(tmp_path, monkeypatch):
    unit = Unit("aa", "Aa", "Aa", 1, "aa",
                MultiPolygon([box(178.0, 50.0, 180.0, 52.0), box(-180.0, 50.0, -178.0, 52.0)]), False, 1)
    land = write_fgb(tmp_path / "land.fgb", "land",
                     [box(177.5, 49.5, 180.0, 52.5), box(-180.0, 49.5, -177.5, 52.5)], {"osm_id": [1, 2]})
    water = write_fgb(tmp_path / "water.fgb", "water", [box(179.0, 50.5, 179.2, 50.7)], {"osm_id": [1]})
    seen = []
    real_read = poles_mod.read
    monkeypatch.setattr(poles_mod, "read", lambda *a, **k: (seen.append(k["bbox"]), real_read(*a, **k))[1])
    allowed = _allowed_factory(unit, land, water)
    # Two reads per index, one per side of the line, and never a box that spans the planet.
    assert [round(v, 6) for b in seen for v in b] == [177.95, 49.95, 180.0, 52.05,
                                                      -180.0, 49.95, -177.95, 52.05] * 2
    lons = np.array([179.0, -179.0, 179.1, 170.0])   # east of the line; west of it; in the lake; outside the unit
    lats = np.array([51.0, 51.0, 50.6, 51.0])
    assert allowed(lons, lats).tolist() == [True, True, False, False]


def test_write_water_big_keeps_only_the_large_polygon(tmp_path, log):
    """Real ogr2ogr: the area filter must survive whatever copy path GDAL picks."""
    src = write_fgb(tmp_path / "water_proj.fgb", "water",
                    [box(4_300_000, 3_220_000, 4_302_000, 3_222_000),      # 2 km x 2 km, 4 km2
                     box(4_310_000, 3_220_000, 4_310_100, 3_220_100)],     # 100 m x 100 m, 0.01 km2
                    {"osm_id": [1, 2]}, crs="EPSG:3035")
    dst = tmp_path / "water_big.fgb"
    write_water_big(src, dst, 1_000_000.0, log, tmp_path / "tools.log")
    meta, _, wkb, fields = read(str(dst), layer="water")
    assert len(wkb) == 1 and dict(zip(meta["fields"], fields))["osm_id"].tolist() == [1]
    assert "4326" in meta["crs"]


def test_write_water_big_splits_a_polygon_on_the_line_into_two_valid_parts(tmp_path, log):
    """Real ogr2ogr: a lake straddling 180 must come out as two parts inside [-180, 180], not as one polygon
    that runs the long way round the planet (the lon/lat copy of a region on the line, issue #22).

    GDAL cuts at the line by itself only for a polygon centred on it; one lying mostly on one side with a lobe
    past the line comes back as a single 359 degree band, and a valid one when it has no holes, so no later
    validity check would catch it. The frame is centred away from the line, as a region's frame is."""
    crs = "+proj=laea +lat_0=50 +lon_0=-100 +datum=WGS84 +units=m"
    to_frame = Transformer.from_crs("EPSG:4326", crs, always_xy=True)

    def projected(shell, holes=()):                                        # the frame is continuous across 180
        return Polygon([to_frame.transform(*v) for v in shell], [[to_frame.transform(*v) for v in h] for h in holes])

    lagoon = projected([(179.2, 68.97), (-179.99, 68.97), (-179.99, 69.28), (179.2, 69.28)],   # 0.81 deg, mostly east
                       [[(179.5, 69.1), (179.6, 69.1), (179.6, 69.15), (179.5, 69.15)]])
    plain = projected([(-150.0, 60.0), (-149.95, 60.0), (-149.95, 60.05), (-150.0, 60.05)])   # about 15 km2
    tiny = projected([(-150.0, 61.0), (-150.001, 61.0), (-150.001, 61.001), (-150.0, 61.001)])   # 0.006 km2
    src = write_fgb(tmp_path / "water_proj.fgb", "water",
                    [MultiPolygon([lagoon]), MultiPolygon([plain]), MultiPolygon([tiny])],
                    {"osm_id": [1, 2, 3]}, crs=crs)
    dst = tmp_path / "water_big.fgb"
    write_water_big(src, dst, 1_000_000.0, log, tmp_path / "tools.log")
    meta, _, wkb, fields = read(str(dst), layer="water")
    assert meta["geometry_type"] == "MultiPolygon"
    by_id = dict(zip(dict(zip(meta["fields"], fields))["osm_id"].tolist(), (shapely.from_wkb(w) for w in wkb)))
    assert sorted(by_id) == [1, 2]
    on_line, east = by_id[1], by_id[2]
    assert on_line.geom_type == "MultiPolygon" and len(on_line.geoms) == 2 and on_line.is_valid
    for part in on_line.geoms:
        assert -180.0 <= part.bounds[0] and part.bounds[2] <= 180.0
        assert part.bounds[2] - part.bounds[0] < 1.0                       # each part hugs its own side
    assert sorted(round(b) for part in on_line.geoms for b in (part.bounds[0], part.bounds[2])) == [-180, -180, 179, 180]
    assert sum(len(part.interiors) for part in on_line.geoms) == 1                 # the hole survives the cut
    assert east.geom_type == "MultiPolygon" and len(east.geoms) == 1 and round(east.bounds[0], 1) == -150.0


# ---------- run(): the per-unit result cache and worker deaths ----------

class _SerialPool:
    """Stands in for ProcessPoolExecutor with the same surface run() uses, minus the processes. Each job
    runs where it is submitted and its future is handed back already finished."""

    def __init__(self, max_workers=None):
        self.max_workers = max_workers

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def submit(self, fn, job):
        f = Future()
        try:
            f.set_result(fn(job))
        except BaseException as exc:                            # noqa: BLE001 - a pool carries anything a job raises
            f.set_exception(exc)
        return f


class _DyingPool(_SerialPool):
    """The worker holding the first job dies the way one killed by the OOM killer does; the jobs behind it
    finish. The message has to name the job that died, and that job is exactly the one with no result."""

    def __init__(self, max_workers=None):
        super().__init__(max_workers)
        self.submitted = 0

    def submit(self, fn, job):
        self.submitted += 1
        if self.submitted > 1:
            return super().submit(fn, job)
        f = Future()
        f.set_exception(BrokenProcessPool("A process in the process pool was terminated abruptly"))
        return f


def _prepared(tmp_path, codes) -> Prepared:
    frame = Frame("EPSG:3035", 250, 0.0, 1000.0, 4, 4)
    units = [Unit(c, c, c, i, c, MultiPolygon([box(0, 0, 1, 1)]), False, i, cells=100 - i)
             for i, c in enumerate(codes, start=1)]
    return Prepared(frame, units, tmp_path / "countries.fgb", tmp_path / "roads", tmp_path / "units.tif",
                    tmp_path / "land_idx.fgb", tmp_path / "water_big.fgb", tmp_path / "places.vrt", {})


def _result(code, scenario, dist):
    return {"unit": code, "scenario": scenario, "poles": [_p(54.0, 24.0, dist) | {"rank": 1}], "reason": "one pole",
            "refinements": 1, "warnings": [], "duration_s": 0.1, "top_coarse_m": dist}


def _patch_run(monkeypatch, tmp_path, codes, pool=_SerialPool):
    prepared = _prepared(tmp_path, codes)
    searched: list[tuple[str, str]] = []

    def fake_search(job):
        searched.append((job.unit.code, job.scenario))
        return _result(job.unit.code, job.scenario, 3000)

    monkeypatch.setattr(poles_mod, "prepare", lambda cfg, ws, log: prepared)
    monkeypatch.setattr(poles_mod, "search_unit", fake_search)
    monkeypatch.setattr(poles_mod, "ProcessPoolExecutor", pool)
    monkeypatch.setattr(poles_mod, "Places", lambda path: _StubPlaces())
    prepared.places.write_text("", encoding="utf-8")        # present; the stub above stands in for its content
    return searched


def test_run_reuses_cached_unit_results_and_searches_only_the_rest(tmp_path, cfg, log, monkeypatch):
    ws = Workspace(tmp_path / "work", "rr", "2026-01-01")
    results = ws.dir("poles") / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "aa-A.json").write_text(json.dumps(_result("aa", "A", 5000)), encoding="utf-8")
    (results / "bb-B.json").write_text(json.dumps(_result("bb", "B", 4000)), encoding="utf-8")
    searched = _patch_run(monkeypatch, tmp_path, ["aa", "bb"])
    meta = poles_mod.run(cfg, ws, log)
    assert sorted(searched) == [("aa", "B"), ("bb", "A")]
    assert (meta["cached"], meta["searched"]) == (2, 2)
    a = json.loads((ws.dir("poles") / "A.json").read_text(encoding="utf-8"))
    assert [e["unit"] for e in a] == ["aa", "bb"] and a[0]["poles"][0]["dist_m"] == 5000   # the cached one, not a fresh search
    assert (results / "aa-B.json").is_file()                                              # every searched job is cached too


def test_run_attributes_every_pole_in_the_parent_from_one_places_layer(tmp_path, cfg, log, monkeypatch):
    """The workers hand back poles with no place; run() fills them all, cached and fresh alike, from the
    layer loaded once, so a re-attribution from the cache reads exactly what a fresh search reads."""
    ws = Workspace(tmp_path / "work", "rr", "2026-01-01")
    results = ws.dir("poles") / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "aa-A.json").write_text(json.dumps(_result("aa", "A", 5000)), encoding="utf-8")
    _patch_run(monkeypatch, tmp_path, ["aa"])

    class _Named:
        def nearest(self, lon, lat):
            return {"name": f"near {lat:.1f} {lon:.1f}", "type": "village", "dist_m": 1.0, "lat": lat, "lon": lon}

    monkeypatch.setattr(poles_mod, "Places", lambda path: _Named())
    poles_mod.run(cfg, ws, log)
    for s in ("A", "B"):
        entries = json.loads((ws.dir("poles") / f"{s}.json").read_text(encoding="utf-8"))
        assert entries[0]["poles"][0]["nearest_place"]["name"] == "near 54.0 24.0"
    cached = json.loads((results / "aa-A.json").read_text(encoding="utf-8"))
    assert cached["poles"][0]["nearest_place"] is None       # the cache holds the search, never the attribution


def test_a_missing_places_layer_stops_the_stage_after_the_searches_and_a_rerun_attributes_from_the_cache(
        tmp_path, cfg, log, monkeypatch):
    """The layer is read only at the end, in the parent: without it every search still runs and is cached,
    the stage fails naming the file, and the rerun with the file back searches nothing."""
    ws = Workspace(tmp_path / "work", "rr", "2026-01-01")
    searched = _patch_run(monkeypatch, tmp_path, ["aa", "bb"])
    (tmp_path / "places.vrt").unlink()
    with pytest.raises(PolesError, match=r"places\.vrt is missing.*4 searched job\(s\).*cached under"):
        poles_mod.run(cfg, ws, log)
    assert len(searched) == 4 and not (ws.dir("poles") / "A.json").exists()
    assert sorted(p.name for p in (ws.dir("poles") / "results").glob("*.json")) == ["aa-A.json", "aa-B.json", "bb-A.json", "bb-B.json"]
    (tmp_path / "places.vrt").write_text("", encoding="utf-8")
    meta = poles_mod.run(cfg, ws, log)
    assert len(searched) == 4 and (meta["cached"], meta["searched"]) == (4, 0)
    assert (ws.dir("poles") / "A.json").is_file() and (ws.dir("poles") / "B.json").is_file()


def test_forced_run_clears_the_result_cache(tmp_path, cfg, log, monkeypatch):
    ws = Workspace(tmp_path / "work", "rr", "2026-01-01")
    results = ws.dir("poles") / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "aa-A.json").write_text(json.dumps(_result("aa", "A", 5000)), encoding="utf-8")
    ws.forced = True
    searched = _patch_run(monkeypatch, tmp_path, ["aa"])
    meta = poles_mod.run(cfg, ws, log)
    assert searched == [("aa", "A"), ("aa", "B")] and meta["cached"] == 0


def test_a_dead_worker_becomes_a_poles_error_naming_the_job_and_the_finished_results_stay(tmp_path, cfg, log, monkeypatch):
    """The job the dead worker held is the one a rerun has to redo, so it is the one the message must name:
    it is the future whose result was never stored, not one of the futures that were never reached."""
    ws = Workspace(tmp_path / "work", "rr", "2026-01-01")
    _patch_run(monkeypatch, tmp_path, ["aa", "bb"], pool=_DyingPool)      # job order: aa-A first, and it dies
    with pytest.raises(PolesError, match="unit aa scenario A.*3 of 4.*POLES_WORKERS"):
        poles_mod.run(cfg, ws, log)
    assert (ws.dir("poles") / "results" / "bb-A.json").is_file()          # the jobs behind it are still cached
    assert not (ws.dir("poles") / "results" / "aa-A.json").exists()


def test_a_saturated_candidate_cell_is_a_poles_error_naming_the_unit_and_the_cell(tmp_path, cfg, monkeypatch):
    """A cell at the cap is a real "at least max_distance_m" answer the search cannot rank, so it aborts.
    The message has to say which cell it was, or finding it means rerunning the continent."""
    monkeypatch.setattr(poles_mod, "vector_component_areas", lambda *a, **k: ({}, {}))
    frame = Frame("EPSG:3035", 250.0, 5_000_000.0, 3_600_000.0, 4, 4)
    unit = Unit("aa", "aa", "aa", 1, "aa", MultiPolygon([box(0, 0, 1, 1)]), False, 1, cells=16)
    units_tif = create_raster(frame, tmp_path / "units.tif", dtype="int16")
    with rasterio.open(units_tif, "r+") as ds:
        ds.write(np.ones((4, 4), dtype="int16"), 1)
    create_raster(frame, low_tif(units_tif), dtype="int16")
    # The candidate rule's two masks, which the island floor reads: 16 land cells of 250 m are 1 km2, so
    # this unit sits exactly on the floor and the saturated cell is on qualifying land.
    _write_mask(land_tif(units_tif), np.ones((4, 4)), frame, "uint8")
    _write_mask(water_tif(units_tif), np.zeros((4, 4)), frame, "uint8")
    dist = np.full((4, 4), 1000.0, dtype="float32")
    dist[2, 3] = float(cfg.max_distance_m)
    write_float_tif(tmp_path / "dist_A.tif", dist, frame)
    prepared = Prepared(frame, [unit], tmp_path / "countries.fgb", tmp_path / "roads", units_tif,
                        tmp_path / "land_idx.fgb", tmp_path / "water_big.fgb", tmp_path / "places.vrt",
                        {"aa": (0, 0, 4, 4)})
    lon, lat = Transformer.from_crs(frame.crs, "EPSG:4326", always_xy=True).transform(
        5_000_000.0 + 3.5 * 250.0, 3_600_000.0 - 2.5 * 250.0)
    with pytest.raises(PolesError) as exc:
        poles_mod.search_unit(UnitJob(cfg, prepared, unit, "A", tmp_path / "dist_A.tif", 3, tmp_path / "log.txt"))
    message = str(exc.value)
    assert "unit aa scenario A" in message and f"lon {lon:.4f}, lat {lat:.4f}" in message
    assert "1 of 16 candidate cells" in message and "territory_mask" in message


def test_a_poles_error_from_a_worker_is_not_rewritten(tmp_path, cfg, log, monkeypatch):
    ws = Workspace(tmp_path / "work", "rr", "2026-01-01")

    def boom(job):
        raise PolesError("unit aa scenario A: top coarse value 250000.0 m is the saturation cap")

    _patch_run(monkeypatch, tmp_path, ["aa"])
    monkeypatch.setattr(poles_mod, "search_unit", boom)
    with pytest.raises(PolesError, match="saturation cap"):
        poles_mod.run(cfg, ws, log)


def test_a_cache_file_of_the_wrong_shape_is_a_poles_error_naming_the_file(tmp_path, cfg, log, monkeypatch):
    ws = Workspace(tmp_path / "work", "rr", "2026-01-01")
    results = ws.dir("poles") / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "aa-A.json").write_text(json.dumps({"unit": "aa", "poles": []}), encoding="utf-8")
    _patch_run(monkeypatch, tmp_path, ["aa"])
    with pytest.raises(PolesError, match="aa-A.json"):
        poles_mod.run(cfg, ws, log)
    (results / "aa-A.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(PolesError, match="aa-A.json"):
        poles_mod.run(cfg, ws, log)


# ---------- _search_pending(): a result is cached the moment its own job finishes ----------

def _job(code, scenario="A"):
    unit = Unit(code, code, code, 1, code, MultiPolygon([box(0, 0, 1, 1)]), False, 1, cells=1)
    return UnitJob(None, None, unit, scenario, Path("dist.tif"), 3, Path("log.txt"))


def _wait_for(path: Path, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.01)
    return False


def test_results_are_cached_as_they_finish_not_in_job_order(tmp_path, log, monkeypatch):
    """`pool.map` yields in job order, so a run that died held back everything the later jobs had already
    finished: two searches were lost that way on North America run 4 (issue #45)."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    gate = threading.Event()

    def stub(job):
        if job.unit.code == "slow":
            assert gate.wait(5)
        return _result(job.unit.code, job.scenario, 3000)

    monkeypatch.setattr(poles_mod, "search_unit", stub)
    jobs = [_job("slow"), _job("quick")]          # the biggest unit heads the queue, as it does in run()
    got: list[list[dict]] = []
    runner = threading.Thread(target=lambda: got.append(_search_pending(jobs, results_dir, 2, log, ThreadPoolExecutor)))
    runner.start()
    try:
        assert _wait_for(results_dir / "quick-A.json")
        assert not (results_dir / "slow-A.json").exists()      # still running, and it does not hold quick back
    finally:
        gate.set()
        runner.join(5)
    assert not runner.is_alive()
    assert (results_dir / "slow-A.json").is_file()
    assert [r["unit"] for r in got[0]] == ["quick", "slow"]    # completion order, not job order


def test_a_worker_error_keeps_the_finished_results_and_reraises(tmp_path, log, monkeypatch):
    """The worker's own error comes back unchanged, what finished before it is kept, and the jobs still
    queued behind it are cancelled instead of searched."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    quick_done = threading.Event()
    started: list[str] = []

    def stub(job):
        started.append(job.unit.code)
        if job.unit.code == "quick":
            quick_done.set()
            return _result(job.unit.code, job.scenario, 3000)
        if job.unit.code == "boom":
            assert quick_done.wait(5)
            raise PolesError("candidates: branch-and-bound exceeded 200000 refinements")
        time.sleep(0.05)                                       # long enough that a freed worker takes one, not ten
        return _result(job.unit.code, job.scenario, 3000)

    monkeypatch.setattr(poles_mod, "search_unit", stub)
    jobs = [_job("boom"), _job("quick")] + [_job(f"zz{i}") for i in range(20)]
    t0 = time.monotonic()
    with pytest.raises(PolesError, match="exceeded 200000 refinements"):
        _search_pending(jobs, results_dir, 2, log, ThreadPoolExecutor)
    assert time.monotonic() - t0 < 10                          # it returned, it did not wait out the queue
    assert (results_dir / "quick-A.json").is_file()            # finished before the error, so it is kept
    assert len([c for c in started if c.startswith("zz")]) <= 4   # 20 without cancellation


def test_any_worker_error_cancels_the_queue_and_keeps_the_finished_results(tmp_path, log, monkeypatch):
    """A MemoryError or a RasterioIOError is not a PolesError and not a BrokenProcessPool, and it has to take
    the same path: without it a finished result is dropped and the pool sits through the whole queue before
    the traceback appears."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    quick_done = threading.Event()
    started: list[str] = []

    def stub(job):
        started.append(job.unit.code)
        if job.unit.code == "quick":
            quick_done.set()
            return _result(job.unit.code, job.scenario, 3000)
        if job.unit.code == "boom":
            assert quick_done.wait(5)
            raise RuntimeError("a worker ran out of memory")
        time.sleep(0.05)                                       # long enough that a freed worker takes one, not ten
        return _result(job.unit.code, job.scenario, 3000)

    monkeypatch.setattr(poles_mod, "search_unit", stub)
    jobs = [_job("boom"), _job("quick")] + [_job(f"zz{i}") for i in range(20)]
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="ran out of memory") as exc:
        _search_pending(jobs, results_dir, 2, log, ThreadPoolExecutor)
    assert exc.type is RuntimeError                            # the worker's own error, not a rewritten one
    assert time.monotonic() - t0 < 10
    assert (results_dir / "quick-A.json").is_file()
    assert len([c for c in started if c.startswith("zz")]) <= 4


def test_a_cache_write_that_fails_while_draining_does_not_replace_the_error(tmp_path, log, monkeypatch, caplog):
    """The drain runs while an error is already on its way out, and the machine it exists for is one whose
    disk is full, so the write it makes is exactly the one that fails. It must not become the reported error."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    running = threading.Barrier(3)      # boom raises only once bad and good run: a job still queued is cancelled
    draining = threading.Event()        # and both finish inside the drain, not before it (issue #48)
    real_cache = poles_mod._cache_result

    class _Pool(ThreadPoolExecutor):
        """Futures whose exception() announces the drain: nothing else in _search_pending calls it."""

        def submit(self, fn, *args, **kwargs):
            f = super().submit(fn, *args, **kwargs)
            real_exception = f.exception

            def exception(timeout=None):
                draining.set()
                return real_exception(timeout)
            f.exception = exception
            return f

    def flaky_cache(dirpath, result):
        if result["unit"] == "bad":
            raise OSError(28, "No space left on device")
        real_cache(dirpath, result)

    def stub(job):
        running.wait(5)
        if job.unit.code == "boom":
            raise PolesError("unit boom scenario A: the search gave up")
        assert draining.wait(5)
        return _result(job.unit.code, job.scenario, 3000)

    monkeypatch.setattr(poles_mod, "search_unit", stub)
    monkeypatch.setattr(poles_mod, "_cache_result", flaky_cache)
    jobs = [_job("boom"), _job("bad"), _job("good")]
    with caplog.at_level(logging.ERROR, logger=log.name):
        with pytest.raises(PolesError, match="the search gave up"):
            _search_pending(jobs, results_dir, 3, log, _Pool)
    assert (results_dir / "good-A.json").is_file()             # the drain carried on past the failed write
    assert not (results_dir / "bad-A.json").exists()
    assert [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR and "bad" in r.getMessage()]


def test_timing_json_is_sorted_by_unit(tmp_path, cfg, log, monkeypatch):
    """Results arrive in completion order now, so timing.json has to sort or its key order drifts run to run
    and a diff against an earlier run says everything changed."""
    ws = Workspace(tmp_path / "work", "rr", "2026-01-01")
    _patch_run(monkeypatch, tmp_path, ["bb", "aa"], pool=ThreadPoolExecutor)
    bb_cached = {"A": threading.Event(), "B": threading.Event()}
    real_cache = poles_mod._cache_result

    def cache(dirpath, result):
        real_cache(dirpath, result)
        if result["unit"] == "bb":
            bb_cached[result["scenario"]].set()

    def slow_aa(job):
        if job.unit.code == "aa":
            assert bb_cached[job.scenario].wait(5)             # bb is consumed first in both scenarios (#48)
        return _result(job.unit.code, job.scenario, 3000)

    monkeypatch.setattr(poles_mod, "search_unit", slow_aa)
    monkeypatch.setattr(poles_mod, "_cache_result", cache)
    poles_mod.run(cfg, ws, log)
    timing = json.loads((ws.dir("poles") / "timing.json").read_text(encoding="utf-8"))
    assert sorted(timing) == ["A", "B"]
    for s in ("A", "B"):
        assert list(timing[s]) == ["aa", "bb"]


def _prepare_workspace(tmp_path, monkeypatch, unit=None):
    """The least on-disk state prepare() needs to reach its units.tif branch: the rest is marked done or stubbed."""
    ws = Workspace(tmp_path / "work", "rr", "2026-01-01")
    frame = Frame("EPSG:3035", 250.0, 0.0, 1000.0, 4, 4)
    (ws.dir("grid") / "frame.json").write_text(json.dumps(frame.to_dict()), encoding="utf-8")
    fetch = ws.dir("fetch")
    (fetch / "r.poly").write_text("r\n1\n 0 0\n 1 0\n 1 1\n 0 1\n 0 0\nEND\nEND\n", encoding="utf-8")
    (fetch / "snapshot.json").write_text(json.dumps({"sources": [
        {"url": "http://x/r-latest.osm.pbf", "role": "primary", "poly": "r.poly"}]}), encoding="utf-8")
    out = ws.dir("poles")
    write_units([unit or Unit("aa", "Aa", "Aa", 1, "aa", MultiPolygon([box(0, 0, 1, 1)]), False, 1)], out / "units.fgb")
    for name in ("countries.fgb", "units.fgb", "land_idx.fgb", "water_big.fgb"):
        (out / name).touch()
        (out / (name + MARKER)).touch()
    (out / "roads").mkdir(exist_ok=True)
    (out / "roads" / "tiles.json").write_text("{}", encoding="utf-8")

    def fake_rasterize(units_fgb, frame, land_src, water_src, out_tif, log, workdir):
        out_tif.touch()
        return {1: 100}

    monkeypatch.setattr(poles_mod, "rasterize_units", fake_rasterize)
    monkeypatch.setattr(poles_mod, "_unit_windows", lambda *tifs: {1: (0, 0, 2, 2)})
    return ws, out


def test_prepare_clears_the_result_cache_when_it_rebuilds_the_units(tmp_path, cfg, log, monkeypatch):
    ws, out = _prepare_workspace(tmp_path, monkeypatch)
    results = out / "results"
    results.mkdir()
    (results / "aa-A.json").write_text(json.dumps(_result("aa", "A", 5000)), encoding="utf-8")
    poles_mod.prepare(cfg, ws, log)
    assert not results.exists()                   # units rebuilt, so every job cached against the old ones is stale
    results.mkdir()
    (results / "aa-A.json").write_text(json.dumps(_result("aa", "A", 5000)), encoding="utf-8")
    poles_mod.prepare(cfg, ws, log)
    assert (results / "aa-A.json").is_file()      # units.tif done: the cache belongs to these units and stays


def test_units_json_bbox_takes_the_short_way_round_the_line(tmp_path, cfg, log, monkeypatch):
    # The bbox units.json publishes is what the site zooms to. Written from plain bounds, a unit split at
    # the line asks the map to show the whole world (issue #22).
    straddler = Unit("aa", "Aa", "Aa", 1, "aa",
                     MultiPolygon([box(178.0, 50.0, 180.0, 55.0), box(-180.0, 50.0, -178.0, 55.0)]), False, 1)
    ws, out = _prepare_workspace(tmp_path, monkeypatch, unit=straddler)
    poles_mod.prepare(cfg, ws, log)
    bbox = json.loads((out / "units.json").read_text(encoding="utf-8"))["units"][0]["bbox"]
    assert bbox == [178.0, 50.0, 182.0, 55.0]


# ---------- windows and the resume path ----------

def test_bbox_window_floors_and_ceils_flips_y_and_clamps_to_the_frame():
    """The fallback window for a unit that units.json has no window for."""
    frame = Frame("EPSG:4326", 1.0, 0.0, 10.0, 10, 10)          # x 0..10, y 0..10, row 0 at the top
    same = Transformer.from_crs("EPSG:4326", "EPSG:4326", always_xy=True)
    unit = Unit("aa", "Aa", "Aa", 1, "aa", MultiPolygon([box(2.3, 3.4, 4.6, 5.7)]), False, 1)
    win = _bbox_window(unit, frame, same)
    # x 2.3..4.6 with a one-cell pad -> cols 1..6 exclusive; y 3.4..5.7 -> rows from the top: 10-5.7-1=3.3 -> 3, to 10-3.4+1=7.6 -> 8
    assert (win.col_off, win.width) == (1, 5) and (win.row_off, win.height) == (3, 5)
    edge = Unit("bb", "Bb", "Bb", 2, "bb", MultiPolygon([box(-3.0, -3.0, 1.0, 1.0)]), False, 2)
    win = _bbox_window(edge, frame, same)                        # clamped, never negative and never past the frame
    assert (win.col_off, win.row_off) == (0, 8) and (win.width, win.height) == (2, 2)


def test_bbox_window_of_a_unit_on_the_line_is_narrow_and_holds_the_far_side():
    """The fallback window when units.json has no window for a unit. Measured: 800 columns of an 800
    column frame before the fix, 72 after, with the far side of the line inside it either way."""
    crs = "+proj=laea +lat_0=50 +lon_0=170 +datum=WGS84 +units=m"
    to_frame = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    frame = Frame(crs, 5000.0, -2_000_000.0, 2_000_000.0, 800, 800)
    straddler = Unit("aa", "Aa", "Aa", 1, "aa",
                     MultiPolygon([box(178.0, 50.0, 180.0, 55.0), box(-180.0, 50.0, -178.0, 55.0)]), False, 1)
    win = _bbox_window(straddler, frame, to_frame)
    assert win.width < 200                              # about 4 degrees of ground, not 360
    fx, fy = to_frame.transform(-179.0, 52.5)           # a point on the far side of the line
    col, row = int((fx - frame.x0) / frame.res), int((frame.y1 - fy) / frame.res)
    assert win.col_off <= col < win.col_off + win.width
    assert win.row_off <= row < win.row_off + win.height


def test_unit_meta_raises_poles_error_naming_the_file(tmp_path):
    units = [Unit("aa", "Aa", "Aa", 1, "aa", MultiPolygon([box(0, 0, 1, 1)]), False, 1)]
    missing = tmp_path / "units.json"
    with pytest.raises(PolesError, match="units.json"):
        _unit_meta(missing, units)
    missing.write_text(json.dumps({"units": [{"code": "bb", "cells": 1, "area_km2": 1.0, "window": [0, 0, 1, 1]}]}), encoding="utf-8")
    with pytest.raises(PolesError, match="aa"):
        _unit_meta(missing, units)
    missing.write_text(json.dumps({"units": [{"code": "aa", "cells": 1, "area_km2": 1.0}]}), encoding="utf-8")
    with pytest.raises(PolesError, match="window"):
        _unit_meta(missing, units)
    missing.write_text(json.dumps({"units": [{"code": "aa", "cells": 7, "area_km2": 0.4, "window": [1, 2, 3, 4]}]}), encoding="utf-8")
    windows = _unit_meta(missing, units)
    assert windows == {"aa": (1, 2, 3, 4)} and (units[0].cells, units[0].area_km2) == (7, 0.4)


def _one_road_utm(lon: float, lat: float) -> UtmRoads:
    """One north-south road at `lon`, projected into the UTM zone of (lon, lat)."""
    rs = RoadSet(np.array([LineString([(lon, lat - 0.1), (lon, lat + 0.1)])], dtype=object),
                 {"osm_id": np.array([7], dtype=object), "highway": np.array(["track"], dtype=object),
                  "name": np.array([""], dtype=object), "ref": np.array([""], dtype=object)})
    return UtmRoads(rs, utm_epsg(lon, lat))


def test_refine_cell_carries_the_way_record_and_never_the_road_set():
    """A pending candidate lives until the search finalises it; if it held the road set it would pin the
    whole window (issue #43). The payload is the pole and its nearest-way record, nothing else."""
    roads = _one_road_utm(25.0, 54.1)
    countries = Countries([AdminArea(1, 2, "lt", "Lietuva", "Lithuania", MultiPolygon([box(24, 53, 26, 55)]), True, False)])
    frame_crs = "EPSG:3035"
    to_frame = Transformer.from_crs("EPSG:4326", frame_crs, always_xy=True)
    x, y = to_frame.transform(25.03, 54.1)
    refined = poles_mod.refine_cell(x, y, frame_crs, roads, half_m=125.0, allowed=lambda lons, lats: np.ones(len(lons), bool),
                                    countries=countries, to_frame=to_frame)
    assert isinstance(refined, Refined)
    pole, way = refined.payload
    assert isinstance(pole, RefinedPole)
    assert way == {"id": 7, "highway": "track", "name": "", "ref": "", "country": "lt"}
    assert not any(isinstance(v, (UtmRoads, RoadSet)) for v in refined.payload)
    assert abs(refined.dist_m - pole.dist_m) < 1e-9 and 1_500 < refined.dist_m < 2_500


@pytest.fixture
def worker_log_parent():
    """Hand `poles.unit` to the test empty and take back what the test attached.

    `_worker_logger` hangs a FileHandler on that shared logger and leaves it there for the life of the
    process, which in a session means an open file under a tmp_path that is about to be deleted and a first
    caller deciding where every later one writes. `propagate` is restored with the handlers because pytest
    attaches its capture handlers to every non-propagating logger at the start of each phase, and the guard
    under test (`if not parent.handlers`) would then see those instead of an empty logger."""
    parent = logging.getLogger("poles.unit")
    for h in list(parent.handlers):
        parent.removeHandler(h)
    parent.propagate = True
    try:
        yield parent
    finally:
        for h in list(parent.handlers):
            parent.removeHandler(h)
            if isinstance(h, logging.FileHandler):
                h.close()
        parent.setLevel(logging.NOTSET)
        parent.propagate = True


def test_worker_log_records_name_their_unit_and_scenario(tmp_path, worker_log_parent):
    """The run log's "500 refinements and counting" warnings named no unit, so the worker that grew to
    20 GB could not be matched to its job (issue #43). The handler hangs on the shared parent and keeps the
    first log_path it saw, so what has to carry the job is the record's logger name."""
    job = UnitJob(cfg=None, prepared=None, unit=Unit("zz", "Z", "Z", 1, "zz", MultiPolygon([box(20.0, 53.0, 21.0, 54.0)]), False, 1),
                  scenario="B", dist_tif=tmp_path / "d.tif", top_n=3, log_path=tmp_path / "log.txt")
    log = poles_mod._worker_logger(job)
    assert len(worker_log_parent.handlers) == 1, "the call under test attaches exactly one handler"
    handler = worker_log_parent.handlers[0]
    assert Path(handler.baseFilename) == job.log_path
    assert "%(name)s" in handler.formatter._fmt and log.name == "poles.unit.zz.B"


# ---------- the island floor (spec 2.3, issue #30) ----------

_WAY = {"id": 1, "highway": "track", "name": None, "ref": None, "country": "aa"}


class _StubPlaces:
    def nearest(self, lon, lat):
        return None


class _StubCache:
    """RoadCache's shape, with nothing behind it: the refinement is stubbed out in these tests."""

    def __init__(self, *args, **kwargs):
        pass

    def get(self, *args, **kwargs):
        return None


def _write_mask(path, arr, frame, dtype):
    with rasterio.open(path, "w", width=frame.width, height=frame.height, count=1, dtype=dtype,
                       crs=frame.crs, transform=frame.transform) as ds:
        ds.write(np.asarray(arr).astype(dtype), 1)


def _field_job(tmp_path, monkeypatch, dist, cfg, *, land=None, unit=None, top_n=1, scenario="A"):
    """One synthetic unit and scenario ready for `search_unit`, with the road machinery stubbed out.

    `dist` is the scenario's coarse raster, `land` the all-touched land mask of the candidate rule (default
    every cell) and `unit` the unit's own cells (default every land cell). A refinement returns its cell's
    centre carrying that cell's coarse value, so every expected pole is arithmetic on `dist`. Returns the
    job and the list the refiner records the (row, col) of every cell it was asked for in.
    """
    dist = np.asarray(dist, dtype="float32")
    h, w = dist.shape
    frame = Frame("EPSG:3035", 250.0, 5_000_000.0, 3_600_000.0, w, h)
    land = np.ones((h, w), dtype=bool) if land is None else np.asarray(land, dtype=bool)
    cells = land if unit is None else (np.asarray(unit, dtype=bool) & land)
    write_float_tif(tmp_path / f"dist_{scenario}.tif", dist, frame)
    units_tif = tmp_path / "units.tif"
    _write_mask(units_tif, np.where(cells, 1, 0), frame, "int16")
    _write_mask(low_tif(units_tif), np.zeros((h, w)), frame, "int16")
    _write_mask(land_tif(units_tif), land, frame, "uint8")
    _write_mask(water_tif(units_tif), np.zeros((h, w)), frame, "uint8")
    unit_obj = Unit("aa", "Aa", "Aa", 1, "aa", MultiPolygon([box(0, 0, 1, 1)]), False, 1, cells=int(cells.sum()))
    prepared = Prepared(frame, [unit_obj], tmp_path / "countries.fgb", tmp_path / "roads", units_tif,
                        tmp_path / "land_idx.fgb", tmp_path / "water_big.fgb", tmp_path / "places.vrt",
                        {"aa": (0, 0, h, w)})
    to_ll = Transformer.from_crs(frame.crs, "EPSG:4326", always_xy=True)
    refined_at: list[tuple[int, int]] = []

    def fake_refine_cell(x, y, frame_crs, roads, half_m, allowed, countries, to_frame):
        col = int(round((x - frame.x0) / frame.res - 0.5))
        row = int(round((frame.y1 - y) / frame.res - 0.5))
        refined_at.append((row, col))
        lon, lat = to_ll.transform(x, y)
        d = float(dist[row, col])
        return Refined(float(x), float(y), d, (RefinedPole(lat, lon, d, 1, x, y, 32635, 0), _WAY))

    monkeypatch.setattr(poles_mod, "refine_cell", fake_refine_cell)
    monkeypatch.setattr(poles_mod, "RoadTiles", lambda *a, **k: None)
    monkeypatch.setattr(poles_mod, "RoadCache", _StubCache)
    monkeypatch.setattr(poles_mod, "_allowed_factory",
                        lambda *a, **k: (lambda lons, lats: np.ones(len(lons), bool)))
    monkeypatch.setattr(poles_mod, "_countries", lambda path: None)
    monkeypatch.setattr(poles_mod, "vector_component_areas", lambda *a, **k: ({}, {}))   # no land polygons here: raster areas
    job = UnitJob(cfg, prepared, unit_obj, scenario, tmp_path / f"dist_{scenario}.tif", top_n,
                  tmp_path / "log.txt")
    return job, refined_at


def test_a_reef_that_rasterises_to_an_island_is_measured_from_its_land_polygons(tmp_path):
    """All-touched rasterisation makes 19 cells of a few rocks; the floor reads the polygons' own area instead
    (Les Minquiers, 0.1 km2 of land under a 1.2 km2 raster component). Only the small components are measured:
    the big one keeps its cell count."""
    from shapely.geometry import box as sbox
    from tests.helpers import write_fgb
    from poles.areas import AreaField
    from poles.units import Unit
    frame = Frame("EPSG:3035", 250, 4_000_000.0, 3_000_000.0, 12, 12)
    to_frame = Transformer.from_crs("EPSG:4326", frame.crs, always_xy=True)
    land = np.zeros((12, 12), dtype=bool)
    land[1:4, 1:4] = True                  # nine cells, 0.5625 km2 of raster: the reef
    land[6:11, 6:11] = True                # 25 cells, 1.5625 km2: an island, also small in raster terms
    land[0, 8:12] = True                   # four cells on the window's border: clipped, so never measured
    field = AreaField.from_arrays(np.full((12, 12), 1000.0), land, 250.0, 0, 0, 250_000.0)
    comps = field.land_components()
    to_ll = Transformer.from_crs(frame.crs, "EPSG:4326", always_xy=True)

    def cell_box(r, c, shrink):    # a land polygon inside cell (r, c), shrunk to a fraction of the cell
        x0 = frame.x0 + c * frame.res + shrink * frame.res
        y0 = frame.y1 - (r + 1) * frame.res + shrink * frame.res
        x1 = frame.x0 + (c + 1) * frame.res - shrink * frame.res
        y1 = frame.y1 - r * frame.res - shrink * frame.res
        lons, lats = to_ll.transform([x0, x1, x1, x0], [y0, y0, y1, y1])
        return shapely.Polygon(zip(lons, lats))

    rocks = [cell_box(r, c, 0.45) for r in (1, 2, 3) for c in (1, 2, 3)]     # 9 rocks of 25 x 25 m
    island = [cell_box(r, c, 0.0) for r in range(6, 11) for c in range(6, 11)]  # whole cells: 1.5625 km2
    island.append(cell_box(5, 8, 0.0))     # a whole land cell the raster calls water: outside the outline, not counted
    write_fgb(tmp_path / "land_idx.fgb", "land", rocks + island, {"fid": list(range(len(rocks) + len(island)))})
    lons, lats = to_ll.transform([frame.x0, frame.x0 + 12 * frame.res], [frame.y1 - 12 * frame.res, frame.y1])
    unit = Unit("aa", "Aa", "Aa", 1, "aa", MultiPolygon([sbox(lons[0], lats[0], lons[1], lats[1])]), False, 1, cells=45)
    rows, cols = np.nonzero(land)
    labels = comps.labels[rows, cols]
    areas, merges = poles_mod.vector_component_areas(field, comps, labels, tmp_path / "land_idx.fgb", unit, frame, to_frame)
    reef, isle, strip = int(comps.labels[2, 2]), int(comps.labels[8, 8]), int(comps.labels[0, 9])
    assert areas[reef] == pytest.approx(9 * 0.025 * 0.025, rel=0.05)
    assert areas[isle] == pytest.approx(1.5625, rel=0.02)
    assert strip not in areas                                # on the border: the cell count stands
    assert merges == {}                                      # every land polygon here ends at its own shore
    keep, km2, _ = poles_mod._island_cells(field, rows, cols, 1_000_000, measure=lambda lab: (areas, merges))
    assert not keep[labels == reef].any() and keep[labels == isle].all()
    assert km2[labels == isle][0] == pytest.approx(1.5625, rel=0.02)
    assert not keep[labels == strip].any()                   # four cells of raster: under the floor as counted
    # A component above the raster cut-off is not measured at all.
    assert poles_mod.vector_component_areas(field, comps, labels, tmp_path / "land_idx.fgb", unit, frame, to_frame, below_km2=0.1) == ({}, {})


def test_a_raster_fragment_of_the_mainland_is_merged_into_it_and_not_dropped_as_an_islet(tmp_path):
    """All-touched water can cut a shore off from its mainland in the raster (Keyesport, Carlyle Lake,
    on the half-shifted grid). The land polygon under such a fragment runs on into the mainland's cells,
    so the fragment is that body, kept and untagged; a true islet's polygon ends at its shore."""
    from shapely.geometry import box as sbox
    from tests.helpers import write_fgb
    from poles.areas import AreaField
    from poles.units import Unit
    frame = Frame("EPSG:3035", 250, 4_000_000.0, 3_000_000.0, 12, 12)
    to_frame = Transformer.from_crs("EPSG:4326", frame.crs, always_xy=True)
    to_ll = Transformer.from_crs(frame.crs, "EPSG:4326", always_xy=True)
    land = np.zeros((12, 12), dtype=bool)
    land[1:11, 1:6] = True                 # the mainland: 50 cells, 3.125 km2
    land[1:11, 7:11] = True                # cut off by a column of non-land cells (6): 40 cells, 2.5 km2
    field = AreaField.from_arrays(np.full((12, 12), 1000.0), land, 250.0, 0, 0, 250_000.0)
    comps = field.land_components()

    def box_of(r0, r1, c0, c1):            # frame cells [r0, r1) x [c0, c1) as a lon/lat polygon
        x0, x1 = frame.x0 + c0 * frame.res, frame.x0 + c1 * frame.res
        y0, y1 = frame.y1 - r1 * frame.res, frame.y1 - r0 * frame.res
        lons, lats = to_ll.transform([x0, x1, x1, x0], [y0, y0, y1, y1])
        return shapely.Polygon(zip(lons, lats))

    # One land polygon spans the mainland, the column and the fragment; the lake on it covers the column
    # down to row 8 only, so the land runs on through rows 9 and 10 (all-touched water cut the raster
    # there, the vector land is whole): a fragment of the mainland, not an island.
    write_fgb(tmp_path / "land_idx.fgb", "land", [box_of(1, 11, 1, 11)], {"fid": [0]})
    write_fgb(tmp_path / "water_big.fgb", "water", [box_of(1, 9, 6, 7)], {"fid": [0]})
    lons, lats = to_ll.transform([frame.x0, frame.x0 + 12 * frame.res], [frame.y1 - 12 * frame.res, frame.y1])
    unit = Unit("aa", "Aa", "Aa", 1, "aa", MultiPolygon([sbox(lons[0], lats[0], lons[1], lats[1])]), False, 1, cells=90)
    rows, cols = np.nonzero(land)
    labels = comps.labels[rows, cols]
    main, frag = int(comps.labels[5, 2]), int(comps.labels[5, 8])
    assert main != frag
    areas, merges = poles_mod.vector_component_areas(field, comps, labels, tmp_path / "land_idx.fgb", unit, frame, to_frame,
                                                     water_big=tmp_path / "water_big.fgb")
    assert merges == {frag: main}
    keep, km2, is_main = poles_mod._island_cells(field, rows, cols, 1_000_000, measure=lambda lab: (areas, merges))
    assert keep.all() and is_main.all()                     # one body: nothing dropped, nothing tagged
    # With the lake running the whole column, the land under the fragment ends at its own shore: an island
    # of 2.5 km2, kept and tagged (Keyesport's 0.04 km2 in Carlyle Lake was this shape, under the floor).
    write_fgb(tmp_path / "water2.fgb", "water", [box_of(1, 11, 6, 7)], {"fid": [0]})
    areas, merges = poles_mod.vector_component_areas(field, comps, labels, tmp_path / "land_idx.fgb", unit, frame, to_frame,
                                                     water_big=tmp_path / "water2.fgb")
    assert merges == {} and areas[frag] == pytest.approx(2.5, rel=0.02)
    keep, km2, is_main = poles_mod._island_cells(field, rows, cols, 1_000_000, measure=lambda lab: (areas, merges))
    assert keep.all() and not is_main[labels == frag].any() and km2[labels == frag][0] == pytest.approx(2.5, rel=0.02)


def test_allowed_refuses_a_point_on_a_body_of_land_under_the_floor(tmp_path):
    """The grid-independent island floor: a point on a land piece less the big water that is smaller than
    the floor is refused, whatever the raster made of its cells; a point on the mainland piece, and on an
    island above the floor, is allowed. Without to_frame the floor is not applied."""
    from shapely.geometry import box as sbox
    from tests.helpers import write_fgb
    from poles.units import Unit
    to_frame = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
    mainland = sbox(20.0, 50.0, 20.2, 50.2)                        # about 200 km2
    islet = sbox(20.30, 50.10, 20.305, 50.105)                      # about 0.2 km2
    island = sbox(20.40, 50.10, 20.43, 50.13)                       # about 7 km2
    lake_isle = sbox(20.10, 50.10, 20.103, 50.103)                  # about 0.07 km2, inside a lake on the mainland
    lake = shapely.Polygon(sbox(20.08, 50.08, 20.12, 50.12).exterior.coords, [lake_isle.exterior.coords])
    write_fgb(tmp_path / "land.fgb", "land", [mainland, islet, island], {"fid": [0, 1, 2]})
    write_fgb(tmp_path / "water.fgb", "water", [lake], {"fid": [0]})
    unit = Unit("aa", "Aa", "Aa", 1, "aa", MultiPolygon([sbox(19.9, 49.9, 20.5, 50.3)]), False, 1, cells=1)
    lons = np.array([20.05, 20.3025, 20.415, 20.1015, 20.09])
    lats = np.array([50.05, 50.1025, 50.115, 50.1015, 50.09])       # mainland, islet, island, lake islet, lake
    floor = poles_mod._allowed_factory(unit, tmp_path / "land.fgb", tmp_path / "water.fgb", to_frame, 1_000_000)
    assert floor(lons, lats).tolist() == [True, False, True, False, False]
    plain = poles_mod._allowed_factory(unit, tmp_path / "land.fgb", tmp_path / "water.fgb")
    assert plain(lons, lats).tolist() == [True, True, True, True, False]


def test_a_candidate_cell_on_a_land_component_below_the_floor_is_not_searched(tmp_path, cfg, monkeypatch):
    """The islet is the farthest cell of the unit and it is never refined: the gate is at the cell, before
    the search, so a rock that rasterises to less than the floor cannot produce a pole (issue #30)."""
    dist = np.full((20, 20), 100.0)
    land = np.zeros((20, 20), dtype=bool)
    land[2:10, 2:10] = True                  # 64 cells of 0.0625 km2 each: 4 km2, above the floor
    land[15, 15] = True                      # one cell: 0.0625 km2, under it
    dist[5, 5], dist[15, 15] = 5000.0, 9000.0
    job, refined_at = _field_job(tmp_path, monkeypatch, dist, cfg, land=land)
    result = poles_mod.search_unit(job)
    assert [p["dist_m"] for p in result["poles"]] == [5000.0]
    assert (15, 15) not in refined_at
    assert result["top_coarse_m"] == 5000.0   # the cap check sees the unit the floor left behind


def test_a_unit_of_nothing_but_small_islets_returns_no_pole_with_a_reason_naming_the_floor(tmp_path, cfg, monkeypatch):
    dist = np.full((20, 20), 100.0)
    land = np.zeros((20, 20), dtype=bool)
    land[3, 3], land[10, 10] = True, True
    dist[3, 3], dist[10, 10] = 9000.0, 8000.0
    job, refined_at = _field_job(tmp_path, monkeypatch, dist, cfg, land=land)
    result = poles_mod.search_unit(job)
    assert result["poles"] == [] and result["refinements"] == 0 and refined_at == []
    assert "min_island_m2" in result["reason"] and "land component" in result["reason"]


def test_a_saturated_cell_on_a_dropped_islet_no_longer_stops_the_run(tmp_path, cfg, monkeypatch):
    """A sub-cell rock at the distance cap is what `territory_mask` entries were added for; the floor now
    removes the cell before the cap is read. A saturated cell on qualifying land still stops the run."""
    dist = np.full((20, 20), 100.0)
    land = np.zeros((20, 20), dtype=bool)
    land[2:10, 2:10] = True
    land[15, 15] = True
    dist[5, 5], dist[15, 15] = 5000.0, float(cfg.max_distance_m)
    job, _ = _field_job(tmp_path, monkeypatch, dist, cfg, land=land)
    assert [p["dist_m"] for p in poles_mod.search_unit(job)["poles"]] == [5000.0]


def test_the_island_gate_keeps_the_largest_component_of_a_unit_whatever_the_window_holds():
    """"The unit's largest land component" is measured over the unit's own cells, not over the window: an
    island unit's own mainland is never tagged, however much foreign land the padded window holds."""
    land = np.zeros((14, 14), dtype=bool)
    land[1:5, 1:5] = True                    # the unit's island: 16 cells, exactly 1 km2
    land[7:14, 7:14] = True                  # a bigger landmass the window covers and the unit has no cell in
    field = AreaField.from_arrays(np.full((14, 14), 1000.0), land, 250.0, 0, 0, 250_000.0)
    rows, cols = np.nonzero(land)
    unit_only = rows < 5
    keep, island_km2, is_main = poles_mod._island_cells(field, rows[unit_only], cols[unit_only], 1_000_000)
    assert keep.all() and is_main.all()
    assert island_km2[0] == pytest.approx(1.0)


def test_the_island_gate_drops_what_is_under_the_floor_and_tags_the_rest(tmp_path):
    land = np.zeros((14, 14), dtype=bool)
    land[1:5, 1:5] = True                    # 16 cells, 1 km2: the unit's largest
    land[8:11, 8:11] = True                  # 9 cells, 0.5625 km2: over a 0.5 km2 floor, not the largest
    land[13, 13] = True                      # one cell: under it
    field = AreaField.from_arrays(np.full((14, 14), 1000.0), land, 250.0, 0, 0, 250_000.0)
    rows, cols = np.nonzero(land)
    keep, island_km2, is_main = poles_mod._island_cells(field, rows, cols, 500_000)
    assert keep.sum() == 25 and not keep[-1]
    assert is_main.sum() == 16
    assert sorted(set(np.round(island_km2[keep], 4).tolist())) == [0.5625, 1.0]


# ---------- the distinct-area rule, end to end (issue #56) ----------

def _plateau(valley: bool):
    """A 20 x 20 field with a three row plateau at 5,000 m and a peak at each end of it.

    `valley` cuts the plateau's middle column down to 1,000 m, which is the road running through it.
    """
    dist = np.full((20, 20), 100.0)
    dist[9:12, 4:17] = 5000.0
    dist[10, 5], dist[10, 15] = 6000.0, 5900.0
    if valley:
        dist[9:12, 10] = 1000.0
    return dist


def test_two_peaks_split_by_a_road_valley_both_become_poles(tmp_path, cfg, monkeypatch):
    """The col between them is 1,000 m, well under half of the nearer peak's 5,900 m, so the two ends of
    the plateau are two places and both are published."""
    job, _ = _field_job(tmp_path, monkeypatch, _plateau(valley=True), replace(cfg, dedup_m=1000), top_n=2)
    result = poles_mod.search_unit(job)
    assert [p["dist_m"] for p in result["poles"]] == [6000.0, 5900.0] and result["reason"] is None


def test_two_peaks_on_one_plateau_yield_one_pole_and_a_reason(tmp_path, cfg, monkeypatch):
    """The same two peaks with 5,000 m ground between them: every route stays above half of 5,900, so it
    is one place and the second peak is not a second pole (issue #56, the bunching)."""
    job, _ = _field_job(tmp_path, monkeypatch, _plateau(valley=False), replace(cfg, dedup_m=1000), top_n=2)
    result = poles_mod.search_unit(job)
    assert [p["dist_m"] for p in result["poles"]] == [6000.0]
    assert result["reason"] and "1 mainland pole(s)" in result["reason"]


def _two_blocks():
    """A high block with a peak at each end; the middle four columns are the gap the tests vary."""
    dist = np.full((20, 20), 100.0)
    dist[9:14, 3:17] = 4000.0
    dist[10, 4], dist[12, 14] = 6000.0, 5900.0
    land = np.zeros((20, 20), dtype=bool)
    land[9:14, 3:17] = True
    return dist, land


def test_a_peak_on_an_islet_is_a_separate_place_from_the_mainland_peak(tmp_path, cfg, monkeypatch):
    """Connectivity is measured over land alone, so water between two peaks makes them two places even
    though the ground on both sides is high. Both islands clear the floor here (25 cells, 1.56 km2), so the
    point of the test is the water, not the floor; the same field with a land bridge gives one pole."""
    dist, land = _two_blocks()
    land[:, 8:12] = False                       # the strait
    job, _ = _field_job(tmp_path, monkeypatch, dist, replace(cfg, dedup_m=1000), land=land, top_n=2)
    result = poles_mod.search_unit(job)
    assert [p["dist_m"] for p in result["poles"]] == [6000.0, 5900.0]

    bridged, land = _two_blocks()               # the same field, the strait filled in
    (tmp_path / "bridged").mkdir()
    job, _ = _field_job(tmp_path / "bridged", monkeypatch, bridged, replace(cfg, dedup_m=1000), land=land, top_n=2)
    assert [p["dist_m"] for p in poles_mod.search_unit(job)["poles"]] == [6000.0]


# ---------- the superset and the island tag (issues #30, #56) ----------

def _archipelago(mainland_peaks, island_peaks):
    """A 40 x 40 field of 250 m cells: one mainland block and four islands, with peaks planted on both.

    The mainland is 800 cells (50 km2) across the top twenty rows; each island is 4 by 4 cells, exactly the
    1 km2 default floor, so nothing here is dropped and these tests are about the superset alone. The peaks
    are `mainland_peaks` along row 5 at ten cell intervals and `island_peaks` one per island; every other
    land cell sits at 100 m, far below any col threshold, so each peak is its own place.
    """
    dist = np.full((40, 40), 100.0)
    land = np.zeros((40, 40), dtype=bool)
    land[0:20, :] = True
    for k in range(4):
        land[30:34, 8 * k:8 * k + 4] = True
    for k, d in enumerate(mainland_peaks):
        dist[5, 5 + 10 * k] = d
    for k, d in enumerate(island_peaks):
        dist[31, 8 * k + 1] = d
    return dist, land


def test_a_unit_with_islands_publishes_ten_mainland_poles_and_the_islands_above_the_tenth(tmp_path, cfg, monkeypatch):
    """The search stops on the count of mainland poles, and the islands it met on the way come too.

    Ten is `top_n`, three here so the whole superset can be written out: the mainland peaks are 9, 7 and 5 km
    and the island peaks 8, 6 and 4 km, so the published set is everything down to the third mainland pole
    and the 4 km island below it is not in it.
    """
    dist, land = _archipelago([9000.0, 7000.0, 5000.0, 3000.0], [8000.0, 6000.0, 4000.0, 2000.0])
    job, _ = _field_job(tmp_path, monkeypatch, dist, replace(cfg, dedup_m=1000), land=land, top_n=3)
    result = poles_mod.search_unit(job)
    assert [p["dist_m"] for p in result["poles"]] == [9000.0, 8000.0, 7000.0, 6000.0, 5000.0]
    assert [p["island_km2"] for p in result["poles"]] == [None, 1.0, None, 1.0, None]
    assert result["reason"] is None


def test_ranks_are_the_overall_order_of_the_superset_with_no_gaps(tmp_path, cfg, monkeypatch):
    """A rank is the pole's place in the whole published set, islands included: the site filters, the
    pipeline does not renumber, and the rank is what a detail raster and a marker are selected by."""
    dist, land = _archipelago([9000.0, 7000.0, 5000.0, 3000.0], [8000.0, 6000.0, 4000.0, 2000.0])
    job, _ = _field_job(tmp_path, monkeypatch, dist, replace(cfg, dedup_m=1000), land=land, top_n=3)
    assert [p["rank"] for p in poles_mod.search_unit(job)["poles"]] == [1, 2, 3, 4, 5]


def test_no_more_than_top_n_island_poles_are_published(tmp_path, cfg, monkeypatch):
    """Every peak here is on an island but the two highest, so the cap is what stops the island half."""
    dist, land = _archipelago([5000.0, 4000.0, 3000.0, 2000.0], [9000.0, 8000.0, 7000.0, 6000.0])
    job, _ = _field_job(tmp_path, monkeypatch, dist, replace(cfg, dedup_m=1000), land=land, top_n=2)
    result = poles_mod.search_unit(job)
    assert [p["dist_m"] for p in result["poles"]] == [9000.0, 8000.0, 5000.0, 4000.0]
    assert [p["island_km2"] for p in result["poles"]] == [1.0, 1.0, None, None]


def test_reaching_the_island_cap_retires_every_remaining_island_cell(tmp_path, cfg, monkeypatch):
    """Without that one retirement an archipelago unit would refine skerries it can no longer take all the
    way down to its last mainland pole; the third island's peak outranks both mainland poles and is never
    refined at all."""
    dist, land = _archipelago([5000.0, 4000.0, 3000.0, 2000.0], [9000.0, 8000.0, 7000.0, 6000.0])
    job, refined_at = _field_job(tmp_path, monkeypatch, dist, replace(cfg, dedup_m=1000), land=land, top_n=2)
    poles_mod.search_unit(job)
    assert (31, 1) in refined_at and (31, 9) in refined_at        # the two islands the cap had room for
    assert (31, 17) not in refined_at and (31, 25) not in refined_at


def test_a_landlocked_unit_publishes_exactly_top_n_poles(tmp_path, cfg, monkeypatch):
    """With no second land component the superset is inert: the quota is the old count and nothing is tagged."""
    dist, land = _archipelago([9000.0, 7000.0, 5000.0, 3000.0], [])
    land[30:34, :] = False                       # the islands go, so the unit is one landmass
    job, _ = _field_job(tmp_path, monkeypatch, dist, replace(cfg, dedup_m=1000), land=land, top_n=3)
    result = poles_mod.search_unit(job)
    assert [p["dist_m"] for p in result["poles"]] == [9000.0, 7000.0, 5000.0]
    assert [p["island_km2"] for p in result["poles"]] == [None, None, None]


def test_a_pole_on_the_units_largest_land_component_is_not_tagged(tmp_path, cfg, monkeypatch):
    dist, land = _archipelago([5000.0], [9000.0])
    job, _ = _field_job(tmp_path, monkeypatch, dist, replace(cfg, dedup_m=1000), land=land, top_n=1)
    mainland = poles_mod.search_unit(job)["poles"][1]
    assert mainland["dist_m"] == 5000.0 and mainland["island_km2"] is None


def test_a_pole_on_a_smaller_component_carries_that_components_area(tmp_path, cfg, monkeypatch):
    """The area published is the whole component's, which is what "on an island of 1 km2" means to a reader."""
    dist, land = _archipelago([5000.0], [9000.0])
    job, _ = _field_job(tmp_path, monkeypatch, dist, replace(cfg, dedup_m=1000), land=land, top_n=1)
    island = poles_mod.search_unit(job)["poles"][0]
    assert island["dist_m"] == 9000.0 and island["island_km2"] == 1.0


def test_the_exhausted_reason_counts_mainland_poles(tmp_path, cfg, monkeypatch):
    """A unit that runs out says how many mainland poles it found, not how many records it wrote."""
    dist, land = _archipelago([5000.0], [9000.0])
    job, _ = _field_job(tmp_path, monkeypatch, dist, replace(cfg, dedup_m=1000), land=land, top_n=2)
    result = poles_mod.search_unit(job)
    assert "1 mainland pole(s)" in result["reason"]
    assert sum(1 for p in result["poles"] if p["island_km2"] is None) == 1


def _entry(unit, *poles):
    return {"unit": unit, "poles": list(poles), "reason": None}


def _sp(rank, dist, island=None):
    """One published pole, as `validate_poles_json` reads it."""
    return dict(_p(55.0 + rank / 100, 24.0, dist), rank=rank, island_km2=island)


def test_validate_poles_json_counts_mainland_poles_not_all_poles():
    """Two mainland poles and two islands is a complete unit at top_n = 2; two islands alone is not."""
    validate_poles_json([_entry("aa", _sp(1, 9000.0, 1.0), _sp(2, 8000.0), _sp(3, 7000.0, 2.0), _sp(4, 6000.0))], 2)
    with pytest.raises(ValueError, match="fewer than 2 mainland poles"):
        validate_poles_json([_entry("aa", _sp(1, 9000.0, 1.0), _sp(2, 8000.0, 2.0))], 2)
    silent = {"unit": "aa", "poles": [_sp(1, 9000.0, 1.0), _sp(2, 8000.0, 2.0)], "reason": "only 0 mainland pole(s)"}
    validate_poles_json([silent], 2)


def test_validate_poles_json_refuses_more_islands_than_top_n():
    with pytest.raises(ValueError, match="island poles"):
        validate_poles_json([_entry("aa", _sp(1, 9000.0, 1.0), _sp(2, 8000.0, 2.0), _sp(3, 7000.0))], 1)
