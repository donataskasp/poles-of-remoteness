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


def test_grid_shift_does_not_block_for_an_excluded_winner():
    from poles.validate import shift_results
    poles = {"A": [{"unit": "aa", "poles": [_pole(0.5, 0.5, 9000.0)], "reason": None}],
             "B": [{"unit": "aa", "poles": [_pole(0.5, 0.5, 9000.0)], "reason": None}]}
    excluded = [{"unit": "aa", "scenario": "A", "rank": 1, "lat": 0.5, "lon": 0.5, "dist_m": 9000.0, "details": {}}]
    moved = _pole(0.6, 0.6, 4000.0)                            # far enough to fail the comparison
    results = shift_results(poles, {("A", "aa"): moved, ("B", "aa"): moved}, excluded)
    assert [(r.scenario, r.passed, r.blocking) for r in results] == [("A", False, False), ("B", False, True)]
    assert results[0].details["excluded_winner"] is True and "excluded_winner" not in results[1].details
