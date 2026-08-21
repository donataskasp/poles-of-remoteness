from pathlib import Path

import pytest
import yaml

from poles.config import ConfigError, RegionConfig, load_region, poly_url

REGIONS = Path(__file__).resolve().parents[1] / "regions"
SUPPLEMENTS = ("armenia", "azerbaijan", "iran", "iraq", "syria")


def _variant(tmp_path: Path, **overrides) -> Path:
    """Europe config with keys overridden; a value of None under key 'drop' removes keys."""
    raw = yaml.safe_load((REGIONS / "europe.yaml").read_text(encoding="utf-8"))
    for key in overrides.pop("drop", []):
        raw.pop(key)
    raw.update(overrides)
    path = tmp_path / "variant.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def test_load_europe_config_matches_spec_table():
    cfg = load_region(REGIONS / "europe.yaml")
    assert isinstance(cfg, RegionConfig)
    assert cfg.id == "europe" and cfg.name == "Europe"
    assert cfg.sources == ["https://download.geofabrik.de/europe-latest.osm.pbf"]
    assert cfg.supplement_sources == [
        f"https://download.geofabrik.de/asia/{c}-latest.osm.pbf" for c in SUPPLEMENTS
    ]
    assert cfg.all_sources == cfg.sources + cfg.supplement_sources
    assert cfg.coarse_crs == "EPSG:3035"
    assert cfg.coarse_res_m == 250
    assert cfg.unit_admin_level == 2
    assert cfg.unit_countries is None
    assert cfg.unit_exclude == ["ru"]
    assert cfg.unit_code_tag == "ISO3166-1"
    assert [m["name"] for m in cfg.territory_mask] == [
        "Svalbard", "Jan Mayen", "Franz Josef Land", "Novaya Zemlya", "Azores", "Madeira",
    ]
    assert all(len(m["bbox"]) == 4 for m in cfg.territory_mask)
    # Bjornoya (Bear Island, 74.4 N 19.0 E) belongs to Svalbard; the first Europe run saturated on it
    svalbard = next(m["bbox"] for m in cfg.territory_mask if m["name"] == "Svalbard")
    assert svalbard[0] <= 19.0 <= svalbard[2] and svalbard[1] <= 74.4 <= svalbard[3]
    assert cfg.edge_mask_m == 50_000
    # DECISIONS 2026-08-20: raised from the spec table's 150 km so saturation lands in class 253
    assert cfg.max_distance_m == 250_000
    assert cfg.top_n == 10
    assert cfg.expected_units == 52          # counted on the 2026-08-19 snapshot in stage 2
    assert cfg.transcontinental == ["tr", "ge"]
    assert (cfg.detail_res_m, cfg.detail_window_m) == (50, 20_000)
    assert cfg.class_table is None


def test_missing_required_key_raises_config_error_naming_key(tmp_path):
    with pytest.raises(ConfigError, match="coarse_crs"):
        load_region(_variant(tmp_path, drop=["coarse_crs"]))


def test_wrong_type_raises_config_error_naming_key(tmp_path):
    with pytest.raises(ConfigError, match="coarse_res_m"):
        load_region(_variant(tmp_path, coarse_res_m="250"))
    with pytest.raises(ConfigError, match="top_n"):
        load_region(_variant(tmp_path, top_n=True))


def test_unknown_key_raises_config_error_naming_key(tmp_path):
    with pytest.raises(ConfigError, match="coarse_resolution"):
        load_region(_variant(tmp_path, coarse_resolution=250))


def test_unit_countries_none_means_all_except_exclude(tmp_path):
    cfg = load_region(_variant(tmp_path, unit_countries=None, unit_exclude=["ru"]))
    assert cfg.is_unit_country("lt") and cfg.is_unit_country("tr")
    assert not cfg.is_unit_country("ru")
    explicit = load_region(_variant(tmp_path, unit_countries=["us", "ca"], unit_exclude=[]))
    assert explicit.is_unit_country("us") and not explicit.is_unit_country("mx")


def test_poly_url_derives_from_geofabrik_source():
    assert poly_url("https://download.geofabrik.de/asia/iran-latest.osm.pbf") == "https://download.geofabrik.de/asia/iran.poly"
    with pytest.raises(ConfigError):
        poly_url("https://example.org/roads.pbf")
