import base64
import json
import re

import pytest
from shapely.geometry import MultiPolygon, box

from poles.units import Unit
from poles.validate.checks import CheckResult
from poles.validate.report import tile_xy, write_contact_sheet, write_report_html, write_report_json

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
EM_DASH = "\u2014"


def _units():
    return [Unit("aa", "A", "Alpha", 1, "aa", MultiPolygon([box(0, 0, 1, 1)]), False, 1),
            Unit("bb", "B", "Beta", 2, "bb", MultiPolygon([box(2, 0, 3, 1)]), True, 2)]


def _pole(lat, lon, d, rank=1):
    return {"rank": rank, "lat": lat, "lon": lon, "dist_m": d, "nearest_way": {"id": 5, "highway": "track", "name": "Miško kelias", "ref": None, "country": "aa"},
            "nearest_place": {"name": "Kaimas", "type": "village", "dist_m": 2500.0, "lat": lat + 0.02, "lon": lon}, "detail": None, "warnings": []}


def test_report_json_has_every_check_for_every_unit(tmp_path):
    results = [CheckResult("recheck", "aa", "A", True, True, {}), CheckResult("recheck", "bb", "A", False, True, {"relative_error": 0.02}),
               CheckResult("holes", "aa", "A", False, False, {}), CheckResult("invariant", "*", "*", True, True, {"name": "unit_count"})]
    summary = write_report_json(results, tmp_path / "report.json", extra={"snapshot": "2026-08-19"})
    data = json.loads((tmp_path / "report.json").read_text())
    assert len(data["results"]) == 4 and data["snapshot"] == "2026-08-19"
    assert summary == {"blocking_failures": 1, "warnings": 1, "per_check": {"recheck": {"passed": 1, "failed": 1}, "holes": {"passed": 0, "failed": 1}, "invariant": {"passed": 1, "failed": 0}}}
    assert {(r["check"], r["unit"], r["scenario"]) for r in data["results"]} == {("recheck", "aa", "A"), ("recheck", "bb", "A"), ("holes", "aa", "A"), ("invariant", "*", "*")}
    write_report_html(results, _units(), tmp_path / "report.html", "test")
    html = (tmp_path / "report.html").read_text()
    assert "Alpha" in html and "Beta" in html and "1 blocking failure" in html and EM_DASH not in html


def test_report_html_lists_the_excluded_poles(tmp_path):
    excluded = [{"unit": "bb", "scenario": "A", "rank": 1, "lat": 0.5, "lon": 2.5, "dist_m": 1234.0,
                 "details": {"claimed_m": 1234.0, "edge_m": 900.0}}]
    write_report_html([CheckResult("recheck", "aa", "A", True, True, {})], _units(), tmp_path / "report.html",
                      "test", excluded=excluded)
    html = (tmp_path / "report.html").read_text()
    assert "1 excluded pole" in html and "Beta" in html and "2.50000" in html and EM_DASH not in html


def test_tile_xy():
    x, y = tile_xy(0.0, 0.0, 1)
    assert (x, y) == (1.0, 1.0)
    x, y = tile_xy(23.537, 54.4415, 13)
    assert int(x) == 4631 and int(y) == 2613


def test_contact_sheet_lists_every_unit_once_per_scenario(tmp_path):
    calls = []
    def fetch(z, x, y):
        calls.append((z, x, y))
        return PNG
    poles = {"A": [{"unit": "aa", "poles": [_pole(0.5, 0.5, 4321.0)], "reason": None}, {"unit": "bb", "poles": [_pole(0.5, 2.5, 1234.0)], "reason": None}],
             "B": [{"unit": "aa", "poles": [_pole(0.6, 0.5, 5000.0)], "reason": None}, {"unit": "bb", "poles": [], "reason": "only 0 poles"}]}
    results = [CheckResult("holes", "aa", "A", False, False, {"inner_density": 0.0}), CheckResult("reference", "aa", "B", False, False, {"name": "Some article", "moved_m": 9000})]
    write_contact_sheet(poles, _units(), results, tmp_path / "sheet.html", fetch_tile=fetch, zoom=13, title="test")
    html = (tmp_path / "sheet.html").read_text()
    assert len(re.findall(r'class="card"', html)) == 4          # 2 units x 2 scenarios, the empty one included
    assert len(calls) == 27 and all(z == 13 for z, _, _ in calls)  # 3 winners x 9 tiles; no tiles for the empty entry
    assert html.count("data:image/png;base64,") == 27
    assert "4.32 km" in html and "Miško kelias" in html and "probable import gap" in html and "Some article" in html and "only 0 poles" in html
    assert "Esri" in html and EM_DASH not in html


def test_contact_sheet_shows_the_first_pole_that_was_not_excluded(tmp_path):
    calls = []
    def fetch(z, x, y):
        calls.append((z, x, y))
        return PNG
    poles = {"A": [{"unit": "aa", "poles": [_pole(0.5, 0.5, 9000.0), _pole(0.7, 0.7, 4321.0, rank=2)], "reason": None},
                   {"unit": "bb", "poles": [_pole(0.5, 2.5, 1234.0)], "reason": None}]}
    excluded = [{"unit": "aa", "scenario": "A", "rank": 1, "lat": 0.5, "lon": 0.5, "dist_m": 9000.0, "details": {"edge_m": 100.0}},
                {"unit": "bb", "scenario": "A", "rank": 1, "lat": 0.5, "lon": 2.5, "dist_m": 1234.0, "details": {"edge_m": 50.0}}]
    write_contact_sheet(poles, _units(), [], tmp_path / "sheet.html", fetch_tile=fetch, zoom=13, excluded=excluded)
    html = (tmp_path / "sheet.html").read_text()
    assert len(calls) == 9 and html.count("data:image/png;base64,") == 9   # aa falls back to rank 2, bb has nothing left
    assert "4.32 km" in html and "9.00 km" not in html
    assert html.count("1 pole excluded") == 2 and "every pole excluded" in html


def test_contact_sheet_survives_a_tile_that_will_not_download(tmp_path):
    calls = []
    def fetch(z, x, y):
        calls.append((z, x, y))
        if len(calls) == 5:                                    # the centre tile of the mosaic
            raise RuntimeError(f"tile {z}/{x}/{y} failed three times: HTTP 500")
        return PNG
    poles = {"A": [{"unit": "aa", "poles": [_pole(0.5, 0.5, 4321.0)], "reason": None}]}
    write_contact_sheet(poles, [_units()[0]], [], tmp_path / "sheet.html", fetch_tile=fetch, zoom=13)
    html = (tmp_path / "sheet.html").read_text()
    assert "1 satellite tile did not download" in html and "4.32 km" in html


def test_stage_exit_code_nonzero_on_blocking_failure(tmp_path, monkeypatch, regions_dir):
    from poles import cli
    from poles.validate import ValidationFailed
    def boom(cfg, ws, log):
        raise ValidationFailed("2 blocking validation failure(s)")
    monkeypatch.setattr(cli, "registry", lambda: {"validate": boom})
    rc = cli.main(["run", "europe", "--stage", "validate", "--snapshot", "2026-01-01", "--work", str(tmp_path), "--regions-dir", str(regions_dir)])
    assert rc == 1


def test_validate_is_registered_in_the_stage_order():
    from poles.stages import ORDER, registry
    assert "validate" in ORDER and registry()["validate"] is not None


def test_edge_bound_failures_become_exclusions_and_stop_blocking():
    from poles.validate import edge_exclusions
    poles = {"A": [{"unit": "aa", "poles": [_pole(0.5, 0.5, 9000.0), _pole(0.7, 0.7, 4321.0, rank=2)], "reason": None}]}
    results = [CheckResult("edge_bound", "aa", "A", False, True, {"rank": 1, "claimed_m": 9000.0, "edge_m": 800.0}),
               CheckResult("edge_bound", "aa", "A", True, True, {"rank": 2, "claimed_m": 4321.0, "edge_m": 90000.0}),
               CheckResult("recheck", "aa", "A", False, True, {"rank": 1})]
    kept, excluded = edge_exclusions(results, poles)
    assert [ (r.check, r.passed, r.blocking) for r in kept ] == [("edge_bound", False, False), ("edge_bound", True, True), ("recheck", False, True)]
    assert excluded == [{"unit": "aa", "scenario": "A", "rank": 1, "lat": 0.5, "lon": 0.5, "dist_m": 9000.0,
                         "details": {"rank": 1, "claimed_m": 9000.0, "edge_m": 800.0}}]


def test_load_poles_names_the_file_it_could_not_read(tmp_path):
    from poles.errors import PolesError
    from poles.validate import load_poles
    (tmp_path / "A.json").write_text(json.dumps([{"unit": "aa", "poles": [], "reason": None, "extra": 1}]), encoding="utf-8")
    (tmp_path / "B.json").write_text("[]", encoding="utf-8")
    with pytest.raises(PolesError, match="A.json"):
        load_poles(tmp_path, 3)


def test_load_poles_returns_both_scenarios(tmp_path):
    from poles.validate import load_poles
    entry = [{"unit": "aa", "poles": [_pole(0.5, 0.5, 4321.0)], "reason": "only 1 pole"}]
    (tmp_path / "A.json").write_text(json.dumps(entry), encoding="utf-8")
    (tmp_path / "B.json").write_text(json.dumps(entry), encoding="utf-8")
    assert sorted(load_poles(tmp_path, 3)) == ["A", "B"]


def test_grid_shift_compares_the_first_pole_that_was_not_excluded():
    """Rank 1 excluded means rank 2 is what gets published, so rank 2 is what check 4 has to validate."""
    from poles.validate import shift_results
    poles = {"A": [{"unit": "aa", "poles": [_pole(0.5, 0.5, 9000.0), _pole(0.7, 0.7, 4321.0, rank=2)], "reason": None}]}
    excluded = [{"unit": "aa", "scenario": "A", "rank": 1, "lat": 0.5, "lon": 0.5, "dist_m": 9000.0, "details": {}}]
    shifted = {("A", "aa"): [_pole(0.5, 0.5, 9000.0), _pole(0.70001, 0.70001, 4322.0, rank=2)]}
    results = shift_results(poles, shifted, excluded)
    assert len(results) == 1 and results[0].passed and results[0].blocking
    assert results[0].details["rank"] == 2 and results[0].details["shifted_m"] == 4322.0


def test_grid_shift_is_not_blocking_when_every_pole_is_excluded():
    from poles.validate import shift_results
    poles = {"A": [{"unit": "aa", "poles": [_pole(0.5, 0.5, 9000.0)], "reason": None}],
             "B": [{"unit": "aa", "poles": [_pole(0.5, 0.5, 9000.0)], "reason": None}]}
    excluded = [{"unit": "aa", "scenario": "A", "rank": 1, "lat": 0.5, "lon": 0.5, "dist_m": 9000.0, "details": {}}]
    moved = [_pole(0.6, 0.6, 4000.0)]                          # far enough to fail the comparison
    results = shift_results(poles, {("A", "aa"): moved, ("B", "aa"): moved}, excluded)
    assert [(r.scenario, r.passed, r.blocking) for r in results] == [("A", False, False), ("B", False, True)]
    assert results[0].details["all_poles_excluded"] is True and "all_poles_excluded" not in results[1].details


def test_shifted_winners_of_an_older_shape_are_recomputed(tmp_path):
    """The first version of the file kept one pole per key. Reading that as a list would be a TypeError
    deep inside check 4, so the loader says "recompute" instead, like the poles stage's result cache."""
    from poles.validate import load_shifted_winners
    path = tmp_path / "shifted_winners.json"
    path.write_text(json.dumps({"A/aa": _pole(0.5, 0.5, 4321.0), "B/aa": None}), encoding="utf-8")
    assert load_shifted_winners(path) is None
    path.write_text("not json at all", encoding="utf-8")
    assert load_shifted_winners(path) is None
    path.write_text(json.dumps({"A/aa": [{"rank": 1, "lat": 0.5}], "B/aa": []}), encoding="utf-8")
    assert load_shifted_winners(path) is None                  # a pole without the fields check 4 reads
    path.write_text(json.dumps({"A/aa": [_pole(0.5, 0.5, 4321.0)], "B/aa": []}), encoding="utf-8")
    loaded = load_shifted_winners(path)
    assert sorted(loaded) == [("A", "aa"), ("B", "aa")] and loaded[("A", "aa")][0]["dist_m"] == 4321.0


def test_contact_sheet_escapes_the_text_it_did_not_write(tmp_path):
    """Place types and unit codes come from OSM and from a region file; neither may inject markup."""
    units = [Unit("<b>x</b>", "A", "Alpha", 1, "aa", MultiPolygon([box(0, 0, 1, 1)]), False, 1)]
    pole = _pole(0.5, 0.5, 4321.0)
    pole["nearest_place"] = {"name": "Kaimas", "type": "<b>village</b>", "dist_m": 2500.0, "lat": 0.52, "lon": 0.5}
    poles = {"A": [{"unit": "<b>x</b>", "poles": [pole], "reason": None}]}
    write_contact_sheet(poles, units, [], tmp_path / "sheet.html", fetch_tile=lambda z, x, y: PNG, zoom=13)
    html = (tmp_path / "sheet.html").read_text()
    assert "&lt;b&gt;village&lt;/b&gt;" in html and "&lt;b&gt;x&lt;/b&gt;" in html
    assert "<b>village</b>" not in html and "<b>x</b>" not in html


def test_contact_sheet_stops_fetching_after_five_failures_in_a_row(tmp_path):
    """A tile server that has stopped answering costs a minute per tile; the sheet gives up on imagery
    rather than spending hours on it and never reaching the verdict."""
    calls = []
    def fetch(z, x, y):
        calls.append((z, x, y))
        raise RuntimeError("tile server is down")
    poles = {"A": [{"unit": "aa", "poles": [_pole(0.5, 0.5, 4321.0)], "reason": None},
                   {"unit": "bb", "poles": [_pole(0.5, 2.5, 1234.0)], "reason": None}]}
    write_contact_sheet(poles, _units(), [], tmp_path / "sheet.html", fetch_tile=fetch, zoom=13)
    html = (tmp_path / "sheet.html").read_text()
    assert len(calls) == 5
    assert html.count("satellite imagery unavailable") == 2 and "1.23 km" in html and "4.32 km" in html


def test_mosaic_wraps_x_and_skips_the_tiles_off_the_world(tmp_path):
    calls = []
    def fetch(z, x, y):
        calls.append((z, x, y))
        return PNG
    poles = {"A": [{"unit": "aa", "poles": [_pole(0.0, 179.99, 4321.0)], "reason": None}]}
    write_contact_sheet(poles, [_units()[0]], [], tmp_path / "sheet.html", fetch_tile=fetch, zoom=1)
    assert len(calls) == 6                                     # two rows of three; the row past the pole is gone
    assert {x for _, x, _ in calls} == {0, 1} and {y for _, _, y in calls} == {0, 1}
    assert "did not download" not in (tmp_path / "sheet.html").read_text()


def test_tile_cache_fetches_once_and_keeps_the_file(tmp_path):
    from poles.validate.report import cached_tile_fetcher
    calls = []
    def fetch(z, x, y):
        calls.append((z, x, y))
        return PNG
    get = cached_tile_fetcher(tmp_path / "tiles", fetch=fetch)
    assert get(13, 4631, 2613) == PNG and get(13, 4631, 2613) == PNG
    assert calls == [(13, 4631, 2613)] and (tmp_path / "tiles" / "13" / "4631" / "2613.jpg").is_file()
    assert cached_tile_fetcher(tmp_path / "tiles", fetch=fetch)(13, 4631, 2613) == PNG and len(calls) == 1


def _stage_env(tmp_path, monkeypatch, cfg, sheet):
    """`validate.run` with its inputs stubbed out: what is under test here is the order of the writes and
    the verdict, not the checks, which have their own tests."""
    from types import SimpleNamespace

    from poles import validate
    from poles.workspace import Workspace
    ws = Workspace(str(tmp_path), cfg.id, "2026-01-01")
    (ws.dir("fetch") / "snapshot.json").write_text(json.dumps({"sources": [{"poly": "x.poly"}]}), encoding="utf-8")
    (ws.dir("grid") / "done.json").write_text(json.dumps({"stage": "grid"}), encoding="utf-8")
    prepared = SimpleNamespace(units=_units(), frame=None, units_tif=None, land_idx=None, water_big=None,
                               roads_dir=tmp_path, windows={})
    monkeypatch.setattr(validate, "prepare", lambda *a: prepared)
    monkeypatch.setattr(validate, "parse_poly", lambda p: box(0, 0, 1, 1))
    monkeypatch.setattr(validate, "RoadTiles", lambda p: None)
    monkeypatch.setattr(validate, "load_poles", lambda *a: {"A": [{"unit": "aa", "poles": [_pole(0.5, 0.5, 4321.0)], "reason": None}], "B": []})
    monkeypatch.setattr(validate, "shifted_poles", lambda *a: {})
    monkeypatch.setattr(validate, "shift_results", lambda *a: [])
    monkeypatch.setattr(validate.checks, "recheck", lambda *a, **k: [CheckResult("recheck", "aa", "A", False, True, {"rank": 1})])
    for name in ("membership", "edge_bound", "holes", "invariants", "references"):
        monkeypatch.setattr(validate.checks, name, lambda *a, **k: [])
    monkeypatch.setattr(validate.checks, "load_refs", lambda p: {})
    monkeypatch.setattr(validate, "write_contact_sheet", sheet)
    return validate, ws


def test_run_writes_the_three_files_before_it_raises(tmp_path, monkeypatch, cfg, log):
    def sheet(poles, units, results, path, **kw):
        path.write_text("<!doctype html>", encoding="utf-8")
    validate, ws = _stage_env(tmp_path, monkeypatch, cfg, sheet)
    with pytest.raises(validate.ValidationFailed):
        validate.run(cfg, ws, log)
    out = ws.dir("validate")
    assert all((out / f).is_file() for f in ("report.json", "report.html", "contact-sheet.html"))


def test_run_reaches_the_verdict_when_the_contact_sheet_throws(tmp_path, monkeypatch, cfg, log):
    def sheet(*args, **kwargs):
        raise RuntimeError("the tile server never answered")
    validate, ws = _stage_env(tmp_path, monkeypatch, cfg, sheet)
    with pytest.raises(validate.ValidationFailed):
        validate.run(cfg, ws, log)
    out = ws.dir("validate")
    assert (out / "report.json").is_file() and (out / "report.html").is_file()
    assert not (out / "contact-sheet.html").exists()
