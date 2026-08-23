import json
import logging
import threading
import time
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
from poles.units import Unit, low_tif, write_units
from poles.workspace import Workspace
from tests.helpers import write_fgb


def _p(lat, lon, d):
    return {"rank": 0, "lat": lat, "lon": lon, "dist_m": d, "nearest_way": {"id": 1, "highway": "track", "name": None, "ref": None, "country": "lt"},
            "nearest_place": None, "detail": None, "warnings": []}


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


def test_a_saturated_candidate_cell_is_a_poles_error_naming_the_unit_and_the_cell(tmp_path, cfg):
    """A cell at the cap is a real "at least max_distance_m" answer the search cannot rank, so it aborts.
    The message has to say which cell it was, or finding it means rerunning the continent."""
    frame = Frame("EPSG:3035", 250.0, 5_000_000.0, 3_600_000.0, 4, 4)
    unit = Unit("aa", "aa", "aa", 1, "aa", MultiPolygon([box(0, 0, 1, 1)]), False, 1, cells=16)
    units_tif = create_raster(frame, tmp_path / "units.tif", dtype="int16")
    with rasterio.open(units_tif, "r+") as ds:
        ds.write(np.ones((4, 4), dtype="int16"), 1)
    create_raster(frame, low_tif(units_tif), dtype="int16")
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
