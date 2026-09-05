import shutil
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
    ref = raw.get("references")
    if isinstance(ref, str) and (REGIONS / ref).is_file():
        shutil.copy(REGIONS / ref, tmp_path / ref)          # the key is relative to its config, so it must exist beside it
    return path


def test_load_europe_config_matches_spec_table():
    cfg = load_region(REGIONS / "europe.yaml")
    assert isinstance(cfg, RegionConfig)
    assert cfg.id == "europe" and cfg.name == "Europe"
    assert cfg.names == {"lt": "Europa"}     # display names by language; `name` is the English one
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
        "Svalbard", "Jan Mayen", "Franz Josef Land", "Novaya Zemlya", "Azores", "Madeira", "Rockall",
    ]
    assert all(len(m["bbox"]) == 4 for m in cfg.territory_mask)
    # Bjornoya (Bear Island, 74.4 N 19.0 E) belongs to Svalbard; the first Europe run saturated on it
    svalbard = next(m["bbox"] for m in cfg.territory_mask if m["name"] == "Svalbard")
    assert svalbard[0] <= 19.0 <= svalbard[2] and svalbard[1] <= 74.4 <= svalbard[3]
    # Rockall (57.6 N 13.7 W) is one unit cell with no land centre; the second stage-2 run saturated on it
    rockall = next(m["bbox"] for m in cfg.territory_mask if m["name"] == "Rockall")
    assert rockall[0] <= -13.69 <= rockall[2] and rockall[1] <= 57.6 <= rockall[3]
    assert cfg.edge_mask_m == 50_000
    # DECISIONS 2026-08-20: raised from the spec table's 150 km so saturation lands in class 253
    assert cfg.max_distance_m == 250_000
    assert cfg.top_n == 10
    assert cfg.expected_units == 52          # counted on the 2026-08-19 snapshot in stage 2
    assert cfg.transcontinental == ["tr", "ge"]
    assert (cfg.detail_res_m, cfg.detail_window_m) == (50, 20_000)
    assert cfg.class_table is None


def test_load_north_america_config_matches_spec_table(regions_dir):
    cfg = load_region(regions_dir / "north-america.yaml")
    assert cfg.id == "north-america" and cfg.name == "North America"
    assert cfg.names == {"lt": "Šiaurės Amerika"}
    assert cfg.sources == ["https://download.geofabrik.de/north-america-latest.osm.pbf"]
    assert cfg.supplement_sources == []
    assert cfg.coarse_crs == "+proj=laea +lat_0=50 +lon_0=-100 +datum=WGS84 +units=m"
    assert cfg.coarse_res_m == 250
    assert cfg.unit_admin_level == 4 and cfg.unit_code_tag == "ISO3166-2"
    assert cfg.unit_countries == ["us", "ca"] and cfg.unit_exclude == []
    assert cfg.territory_mask == [{"name": "Northwestern Hawaiian Islands", "bbox": [-179.0, 22.5, -161.0, 29.0]}]
    assert cfg.transcontinental == []
    assert cfg.edge_mask_m == 50_000 and cfg.max_distance_m == 500_000
    assert cfg.top_n == 10 and cfg.detail_res_m == 50 and cfg.detail_window_m == 20_000
    assert cfg.expected_units == 64 and cfg.class_table is None
    assert cfg.references == (regions_dir / "north-america-refs.yaml").resolve()
    assert cfg.is_unit_country("us") and cfg.is_unit_country("ca") and not cfg.is_unit_country("mx")
    assert poly_url(cfg.sources[0]).endswith("/north-america.poly")


def test_references_resolves_beside_the_region_config():
    cfg = load_region(REGIONS / "europe.yaml")
    assert cfg.references == (REGIONS / "europe-refs.yaml").resolve()
    assert cfg.references.is_file()


def test_references_is_optional_and_a_missing_file_names_the_key(tmp_path):
    # A region need not ship reference poles; check 6 then has nothing to compare and says so.
    assert load_region(_variant(tmp_path, drop=["references"])).references is None
    with pytest.raises(ConfigError, match="references"):
        load_region(_variant(tmp_path, references="nowhere-refs.yaml"))


def test_the_new_rule_keys_have_defaults_when_a_config_omits_them(tmp_path):
    """A region that says nothing about the distinct-area rule gets the values both regions ship today."""
    cfg = load_region(_variant(tmp_path, drop=["area_col_fraction", "dedup_m", "min_island_m2"]))
    assert cfg.area_col_fraction == 0.5
    assert cfg.dedup_m == 10_000
    assert cfg.min_island_m2 == 1_000_000


def test_area_col_fraction_outside_zero_to_one_is_a_config_error_naming_the_key(tmp_path):
    """0 would make every candidate a new place and 1 would demand a drop to zero between two poles."""
    for bad in (0.0, 1.0, -0.5, 1.5):
        with pytest.raises(ConfigError, match="area_col_fraction"):
            load_region(_variant(tmp_path, area_col_fraction=bad))
    assert load_region(_variant(tmp_path, area_col_fraction=0.75)).area_col_fraction == 0.75


def test_a_negative_dedup_or_island_floor_is_a_config_error_naming_the_key(tmp_path):
    with pytest.raises(ConfigError, match="dedup_m"):
        load_region(_variant(tmp_path, dedup_m=-1))
    with pytest.raises(ConfigError, match="min_island_m2"):
        load_region(_variant(tmp_path, min_island_m2=-1))
    zeroed = load_region(_variant(tmp_path, dedup_m=0, min_island_m2=0))   # both floors off is a legal region
    assert (zeroed.dedup_m, zeroed.min_island_m2) == (0, 0)


def test_area_col_fraction_accepts_an_int_but_not_a_bool(tmp_path):
    """An int is a legal type, so 0 and 1 are refused by the range rather than by the type, while the bool
    guard in `load_region` refuses `true` before the range is ever reached."""
    with pytest.raises(ConfigError, match="area_col_fraction.*greater than 0 and less than 1"):
        load_region(_variant(tmp_path, area_col_fraction=1))
    with pytest.raises(ConfigError, match="area_col_fraction.*must be float/int, got bool"):
        load_region(_variant(tmp_path, area_col_fraction=True))


def test_missing_required_key_raises_config_error_naming_key(tmp_path):
    with pytest.raises(ConfigError, match="coarse_crs"):
        load_region(_variant(tmp_path, drop=["coarse_crs"]))


def test_wrong_type_raises_config_error_naming_key(tmp_path):
    with pytest.raises(ConfigError, match="coarse_res_m"):
        load_region(_variant(tmp_path, coarse_res_m="250"))
    with pytest.raises(ConfigError, match="top_n"):
        load_region(_variant(tmp_path, top_n=True))


def test_names_is_required_and_maps_language_codes_to_strings(tmp_path):
    # The display names live in the config because Intl.DisplayNames localises countries, not regions.
    with pytest.raises(ConfigError, match="'names'"):
        load_region(_variant(tmp_path, drop=["names"]))
    with pytest.raises(ConfigError, match="'names'"):
        load_region(_variant(tmp_path, names=["Europa"]))
    with pytest.raises(ConfigError, match="'names'"):
        load_region(_variant(tmp_path, names={"lt": 3}))
    with pytest.raises(ConfigError, match="'names'"):
        load_region(_variant(tmp_path, names={"lithuanian": "Europa"}))


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
