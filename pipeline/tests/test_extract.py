import json
import shutil
import zipfile

import numpy as np
import pytest
import shapely
from pyogrio import read_info
from pyogrio.raw import read, write

from poles import extract
from poles.osmium import osmium
from poles.shell import ToolError
from poles.workspace import Workspace


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
    assert not list(ex.glob("*.geojsonseq")) and not list(ex.glob("*-filtered.pbf"))


def test_osmium_failure_raises_with_command_in_message(tmp_path, log):
    with pytest.raises(ToolError) as e:
        osmium(["cat", tmp_path / "missing.osm.pbf", "-o", tmp_path / "out.pbf"], log)
    assert "osmium cat" in str(e.value) and "missing.osm.pbf" in str(e.value)
