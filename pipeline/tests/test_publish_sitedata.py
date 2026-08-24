import json
from pathlib import Path

import pytest

from poles.classes import ClassTable
from poles.errors import PolesError
from poles.publish import sitedata


def _pole(rank, dist):
    return {"rank": rank, "lat": 55.0 + rank / 100, "lon": 24.0, "dist_m": dist,
            "nearest_way": {"id": 1, "highway": "track", "name": None, "ref": None, "country": "lt"},
            "nearest_place": {"name": "Kaunas", "type": "city", "dist_m": 5000.0, "lat": 54.9, "lon": 23.9},
            "detail": None, "warnings": []}


POLES = {
    "A": [{"unit": "lt", "poles": [_pole(1, 9000.0), _pole(2, 8000.0), _pole(3, 7000.0)], "reason": None},
          {"unit": "lv", "poles": [_pole(1, 9500.0)], "reason": None},
          {"unit": "mc", "poles": [], "reason": "no land cell"}],
    "B": [{"unit": "lt", "poles": [_pole(1, 12000.0)], "reason": None},
          {"unit": "lv", "poles": [_pole(1, 12000.0)], "reason": None},
          {"unit": "mc", "poles": [], "reason": "no land cell"}],
}
# area_km2, cells and window are stage 2's, measured off the land cells of the unit raster.
UNITS_META = [
    {"code": "lt", "name": "Lietuva", "name_en": "Lithuania", "osm_id": 72596, "country": "lt", "index": 1, "area_km2": 64833.2,
     "cells": 1037331, "transcontinental": False, "closed_by_edge": False, "bbox": [20.9, 53.9, 26.9, 56.5], "window": [0, 0, 1, 1]},
    {"code": "lv", "name": "Latvija", "name_en": "Latvia", "osm_id": 72594, "country": "lv", "index": 2, "area_km2": 64407.1,
     "cells": 1030514, "transcontinental": False, "closed_by_edge": False, "bbox": [20.9, 55.6, 28.3, 58.1], "window": [0, 0, 1, 1]},
    {"code": "mc", "name": "Monaco", "name_en": "Monaco", "osm_id": 1124039, "country": "mc", "index": 3, "area_km2": 0.0,
     "cells": 0, "transcontinental": False, "closed_by_edge": False, "bbox": [7.4, 43.7, 7.5, 43.8], "window": [0, 0, 1, 1]},
]
REGION = {"id": "testland", "name": "Testland", "names": {"lt": "Testlandija"}, "snapshot": "2026-01-01", "unit_level": 2,
          "r2_base": "https://pub-x.r2.dev", "max_distance_m": 250000, "edge_mask_m": 50000, "detail_res_m": 50,
          "detail_window_m": 20000}
ARCHIVES = {"A": {"key_name": "A.pmtiles", "bytes": 10, "tiles": 3, "min_zoom": 0, "max_zoom": 9, "tile_type": "png", "per_zoom": {9: 1}, "blank_skipped": 0},
            "B": {"key_name": "B.pmtiles", "bytes": 10, "tiles": 3, "min_zoom": 0, "max_zoom": 9, "tile_type": "png", "per_zoom": {9: 1}, "blank_skipped": 0}}
SOURCES = [{"url": "https://example.org/x.pbf", "role": "primary", "file": "x.pbf", "size": 1, "md5": "a", "sha256": "b",
            "last_modified": "2026-01-01T00:00:00+00:00", "poly": "x.poly"}]

# A complete foreign region, so the merge tests exercise the merge instead of bypassing the schema.
OTHER_REGION = {"id": "other", "name": "Other", "names": {"lt": "Kita"}, "snapshot": "2025-01-01", "unit_level": 2,
                "units_count": 1, "r2_base": "https://pub-y.r2.dev", "class_edges": ClassTable().edges,
                "max_distance_m": 250000, "edge_mask_m": 50000, "detail_res_m": 50, "detail_window_m": 20000}
OTHER_MANIFEST = {"snapshot": "2025-01-01", "published_at": "2025-01-01T00:00:00+00:00", "r2_base": "https://pub-y.r2.dev",
                  "pipeline_commit": None, "sources": [], "archives": {}, "detail": {"count": 0, "bytes": 0},
                  "validation": {"report": "other/2025-01-01/validation/report.json",
                                 "report_html": "other/2025-01-01/validation/report.html",
                                 "contact_sheet": "other/2025-01-01/validation/contact-sheet.html"},
                  "verified": {"at": "2025-01-01T00:00:00+00:00", "keys": 0, "range_ok": 0}}


def _build(published=None, units_meta=None):
    published = published or sitedata.apply_exclusions(POLES, [])
    return sitedata.build(REGION, units_meta or UNITS_META, published, ClassTable(), ARCHIVES, {"count": 5, "bytes": 50},
                          {"at": "2026-01-02T00:00:00+00:00", "keys": 13, "range_ok": 2}, SOURCES,
                          "2026-01-02T00:00:00+00:00", "abc123")


def _seed_other(tmp_path: Path, regions_entry=None, manifest_entry=None) -> None:
    (tmp_path / "regions.json").write_text(json.dumps({"schema_version": 1, "regions": [regions_entry or OTHER_REGION]}))
    (tmp_path / "manifest.json").write_text(json.dumps({"schema_version": 1, "generated_at": "2025-01-01T00:00:00+00:00",
                                                        "regions": {"other": manifest_entry or OTHER_MANIFEST}}))


def test_apply_exclusions_drops_reranks_and_counts():
    out = sitedata.apply_exclusions(POLES, [{"unit": "lt", "scenario": "A", "rank": 2, "lat": 0, "lon": 0, "dist_m": 0, "details": {}}])
    lt = out["A"][0]
    assert [p["rank"] for p in lt["poles"]] == [1, 2] and [p["dist_m"] for p in lt["poles"]] == [9000.0, 7000.0]
    assert lt["withheld"] == 1 and out["A"][1]["withheld"] == 0 and out["B"][0]["withheld"] == 0
    assert POLES["A"][0]["poles"][1]["rank"] == 2                      # input untouched


def test_apply_exclusions_refuses_unmatched():
    with pytest.raises(PolesError, match="rerun validate"):
        sitedata.apply_exclusions(POLES, [{"unit": "lt", "scenario": "A", "rank": 9, "lat": 0, "lon": 0, "dist_m": 0, "details": {}}])


def test_apply_exclusions_can_empty_a_unit():
    every = [{"unit": "lt", "scenario": "A", "rank": r, "lat": 0, "lon": 0, "dist_m": 0, "details": {}} for r in (1, 2, 3)]
    lt = sitedata.apply_exclusions(POLES, every)["A"][0]
    assert lt["poles"] == [] and lt["withheld"] == 3 and lt["reason"] is None


def test_regional_ranks_dense_ties_by_code():
    published = sitedata.apply_exclusions(POLES, [])
    assert sitedata.regional_ranks(published["A"]) == {"lv": 1, "lt": 2}
    assert sitedata.regional_ranks(published["B"]) == {"lt": 1, "lv": 1}


def test_build_documents():
    site = _build()
    assert site.regions_entry["id"] == "testland" and site.regions_entry["units_count"] == 3
    assert site.regions_entry["names"] == REGION["names"]   # the site says the region's name in the reader's language
    assert len(site.regions_entry["class_edges"]) == 254 and site.regions_entry["r2_base"] == REGION["r2_base"]
    units = {u["code"]: u for u in site.units_doc["units"]}
    assert units["lt"]["A"]["dist_m"] == 9000.0 and units["lt"]["A"]["rank"] == 2 and units["lt"]["A"]["withheld"] == 0
    assert units["mc"]["A"] is None and units["mc"]["B"] is None
    assert units["lt"]["area_km2"] == 64833.2 and units["lt"]["name_en"] == "Lithuania"
    lt = site.unit_docs["lt"]
    assert lt["A"]["poles"][0]["detail"] == "detail/lt/A-1" and lt["A"]["withheld"] == 0 and lt["A"]["reason"] is None
    assert lt["area_km2"] == 64833.2
    assert site.unit_docs["mc"]["A"] == {"poles": [], "withheld": 0, "reason": "no land cell"}
    m = site.manifest_entry
    assert m["archives"]["A"]["key"] == "testland/2026-01-01/A.pmtiles" and m["detail"]["count"] == 5
    assert m["validation"]["report"] == "testland/2026-01-01/validation/report.json" and m["pipeline_commit"] == "abc123"
    assert m["sources"][0]["sha256"] == "b"


def test_build_fills_a_missing_name_from_the_other_one():
    meta = [dict(UNITS_META[0], name_en=None), dict(UNITS_META[1], name=None), dict(UNITS_META[2], name=None, name_en=None)]
    site = _build(units_meta=meta)
    units = {u["code"]: u for u in site.units_doc["units"]}
    assert (units["lt"]["name"], units["lt"]["name_en"]) == ("Lietuva", "Lietuva")
    assert (units["lv"]["name"], units["lv"]["name_en"]) == ("Latvia", "Latvia")
    assert (units["mc"]["name"], units["mc"]["name_en"]) == ("mc", "mc")
    for doc in site.unit_docs.values():
        sitedata.validate_doc("unit", doc)
    sitedata.validate_doc("units", site.units_doc)


def test_build_renumbers_detail_stems_after_an_exclusion():
    published = sitedata.apply_exclusions(POLES, [{"unit": "lt", "scenario": "A", "rank": 1, "lat": 0, "lon": 0,
                                                   "dist_m": 0, "details": {}}])
    site = _build(published)
    lt = site.unit_docs["lt"]["A"]
    assert [p["detail"] for p in lt["poles"]] == ["detail/lt/A-1", "detail/lt/A-2"]
    assert [p["dist_m"] for p in lt["poles"]] == [8000.0, 7000.0] and lt["withheld"] == 1
    summary = {u["code"]: u for u in site.units_doc["units"]}["lt"]["A"]
    assert summary["dist_m"] == 8000.0 and summary["withheld"] == 1 and summary["rank"] == 2


def test_build_marks_a_missing_scenario_not_searched():
    published = sitedata.apply_exclusions({"A": POLES["A"]}, [])
    site = _build(published)
    assert site.unit_docs["lt"]["B"] == {"poles": [], "withheld": 0, "reason": "not searched"}
    assert {u["code"]: u for u in site.units_doc["units"]}["lt"]["B"] is None
    sitedata.validate_doc("unit", site.unit_docs["lt"])


def test_build_refuses_a_unit_the_unit_list_does_not_know():
    published = sitedata.apply_exclusions({"A": [*POLES["A"], {"unit": "xx", "poles": [_pole(1, 99000.0)], "reason": None}],
                                           "B": POLES["B"]}, [])
    with pytest.raises(PolesError, match=r"\['xx'\]"):
        _build(published)


def test_unit_doc_accepts_an_unnamed_nearest_place():
    """OSM has unnamed hamlets and isolated dwellings: 5 of the 918 poles of the Europe run have one as the
    nearest place, so the site's contract has to carry a null place name."""
    pole = _pole(1, 9000.0)
    pole["nearest_place"] = {"name": None, "type": "isolated_dwelling", "dist_m": 3949.5, "lat": 57.7, "lon": 25.7}
    poles = {"A": [{"unit": "lt", "poles": [pole], "reason": None}], "B": []}
    site = _build(sitedata.apply_exclusions(poles, []))
    assert site.unit_docs["lt"]["A"]["poles"][0]["nearest_place"]["name"] is None
    sitedata.validate_doc("unit", site.unit_docs["lt"])


def test_every_document_validates():
    site = _build()
    sitedata.validate_doc("regions", sitedata.merge_regions(None, site.regions_entry))
    sitedata.validate_doc("units", site.units_doc)
    for doc in site.unit_docs.values():
        sitedata.validate_doc("unit", doc)
    sitedata.validate_doc("manifest", sitedata.merge_manifest(None, "testland", site.manifest_entry, "2026-01-02T00:00:00+00:00"))
    with pytest.raises(PolesError, match=r"regions/0: 'name' is a required property \(schema .*/required\)"):
        sitedata.validate_doc("regions", {"schema_version": 1, "regions": [{"id": "x"}]})
    with pytest.raises(PolesError, match="<root>: Additional properties are not allowed"):
        bad = dict(site.units_doc)
        bad["extra"] = 1
        sitedata.validate_doc("units", bad)


def test_schemas_close_the_pole_attribution_objects():
    site = _build()
    doc = json.loads(json.dumps(site.unit_docs["lt"]))
    doc["A"]["poles"][0]["nearest_way"]["surface"] = "gravel"
    with pytest.raises(PolesError, match="A/poles/0/nearest_way: Additional properties are not allowed"):
        sitedata.validate_doc("unit", doc)
    doc = json.loads(json.dumps(site.unit_docs["lt"]))
    doc["A"]["poles"][0]["nearest_place"]["population"] = 300000
    with pytest.raises(PolesError, match="A/poles/0/nearest_place: Additional properties are not allowed"):
        sitedata.validate_doc("unit", doc)


def test_schemas_refuse_a_bad_unit_code():
    site = _build()
    doc = json.loads(json.dumps(site.unit_docs["lt"]))
    doc["code"] = "LT"
    with pytest.raises(PolesError, match="code: 'LT' does not match"):
        sitedata.validate_doc("unit", doc)


def test_merge_regions_keeps_a_republished_region_in_place():
    site = _build()
    first = sitedata.merge_regions({"schema_version": 1, "regions": [site.regions_entry, OTHER_REGION]}, site.regions_entry)
    assert [r["id"] for r in first["regions"]] == ["testland", "other"]
    assert sitedata.merge_regions(None, site.regions_entry)["regions"] == [site.regions_entry]


def test_write_site_merges_other_regions(tmp_path):
    site = _build()
    _seed_other(tmp_path)
    paths = sitedata.write_site(site, tmp_path, "testland", "2026-01-02T00:00:00+00:00")
    regions = json.loads((tmp_path / "regions.json").read_text())
    assert [r["id"] for r in regions["regions"]] == ["other", "testland"]
    assert regions["regions"][0] == OTHER_REGION                              # foreign entry kept as it was
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert set(manifest["regions"]) == {"other", "testland"} and manifest["generated_at"] == "2026-01-02T00:00:00+00:00"
    assert (tmp_path / "testland" / "units.json").exists() and (tmp_path / "testland" / "units" / "lt.json").exists()
    assert len(paths) == 3 + 1 + 2
    again = sitedata.write_site(site, tmp_path, "testland", "2026-01-03T00:00:00+00:00")
    assert [r["id"] for r in json.loads((tmp_path / "regions.json").read_text())["regions"]] == ["other", "testland"]
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert set(manifest["regions"]) == {"other", "testland"} and manifest["generated_at"] == "2026-01-03T00:00:00+00:00"
    assert manifest["regions"]["other"] == OTHER_MANIFEST
    assert again == paths


def test_write_site_writes_the_region_documents_before_it_announces_the_region(tmp_path):
    site = _build()
    paths = [p.relative_to(tmp_path).as_posix() for p in sitedata.write_site(site, tmp_path, "testland", "2026-01-02T00:00:00+00:00")]
    assert paths[:3] == ["testland/units/lt.json", "testland/units/lv.json", "testland/units/mc.json"]
    assert paths[3:] == ["testland/units.json", "manifest.json", "regions.json"]


def test_write_site_removes_a_unit_that_is_no_longer_published(tmp_path):
    site = _build()
    orphan = tmp_path / "testland" / "units" / "xx.json"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("{}")
    sitedata.write_site(site, tmp_path, "testland", "2026-01-02T00:00:00+00:00")
    assert not orphan.exists()
    assert sorted(p.name for p in (tmp_path / "testland" / "units").iterdir()) == ["lt.json", "lv.json", "mc.json"]


def test_write_site_writes_nothing_when_an_existing_region_is_incomplete(tmp_path):
    site = _build()
    # The stub carries the keys before 'snapshot' in the schema, so the refusal names 'snapshot' whatever
    # order the required list is written in.
    stub = {"id": "other", "name": "Other", "names": {"lt": "Kita"}}
    _seed_other(tmp_path, regions_entry=stub)
    with pytest.raises(PolesError, match="regions/0: 'snapshot' is a required property"):
        sitedata.write_site(site, tmp_path, "testland", "2026-01-02T00:00:00+00:00")
    assert not (tmp_path / "testland").exists()
    assert json.loads((tmp_path / "regions.json").read_text())["regions"] == [stub]


def test_write_site_refuses_unreadable_existing_json(tmp_path):
    site = _build()
    (tmp_path / "manifest.json").write_text("{ not json")
    with pytest.raises(PolesError, match="not JSON.*fix or remove it before publishing"):
        sitedata.write_site(site, tmp_path, "testland", "2026-01-02T00:00:00+00:00")


def test_write_site_refuses_existing_json_that_is_not_an_object(tmp_path):
    site = _build()
    (tmp_path / "regions.json").write_text('[{"id": "other"}]')
    with pytest.raises(PolesError, match="not a JSON object but a list; fix or remove it before publishing"):
        sitedata.write_site(site, tmp_path, "testland", "2026-01-02T00:00:00+00:00")
