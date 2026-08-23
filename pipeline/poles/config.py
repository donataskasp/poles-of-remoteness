"""Region configuration: the only place a region is described."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """A missing, unknown, or mistyped region config key. The message names the key."""


@dataclass(frozen=True)
class RegionConfig:
    id: str
    name: str
    names: dict
    sources: list[str]
    supplement_sources: list[str]
    coarse_crs: str
    coarse_res_m: int
    unit_admin_level: int
    unit_countries: list[str] | None
    unit_exclude: list[str]
    unit_code_tag: str
    territory_mask: list[dict]
    edge_mask_m: int
    max_distance_m: int
    top_n: int
    detail_res_m: int
    detail_window_m: int
    class_table: list[int] | None
    expected_units: int | None
    transcontinental: list[str]
    references: Path | None

    @property
    def all_sources(self) -> list[str]:
        return [*self.sources, *self.supplement_sources]

    def is_unit_country(self, code: str) -> bool:
        """unit_countries None means every country in the extract; unit_exclude always wins."""
        if code in self.unit_exclude:
            return False
        return self.unit_countries is None or code in self.unit_countries


_NONE = type(None)
_TYPES: dict[str, tuple[type, ...]] = {
    "id": (str,), "name": (str,), "names": (dict,), "sources": (list,), "supplement_sources": (list,),
    "coarse_crs": (str,), "coarse_res_m": (int,), "unit_admin_level": (int,),
    "unit_countries": (list, _NONE), "unit_exclude": (list,), "unit_code_tag": (str,),
    "territory_mask": (list,), "edge_mask_m": (int,), "max_distance_m": (int,), "top_n": (int,),
    "detail_res_m": (int,), "detail_window_m": (int,), "class_table": (list, _NONE),
    "expected_units": (int, _NONE), "transcontinental": (list,), "references": (str, _NONE),
}
_DEFAULTS: dict[str, Any] = {
    "supplement_sources": [], "unit_countries": None, "unit_exclude": [], "territory_mask": [],
    "class_table": None, "expected_units": None, "transcontinental": [], "references": None,
}
_REQUIRED = tuple(k for k in _TYPES if k not in _DEFAULTS)
_STRING_LISTS = ("sources", "supplement_sources", "unit_exclude", "transcontinental")


def load_region(path: str | Path) -> RegionConfig:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top level must be a mapping")
    for key in _REQUIRED:
        if key not in raw:
            raise ConfigError(f"{path}: missing required key '{key}'")
    unknown = sorted(set(raw) - set(_TYPES))
    if unknown:
        raise ConfigError(f"{path}: unknown key(s) {unknown}")
    values: dict[str, Any] = {**_DEFAULTS, **raw}
    for key, types in _TYPES.items():
        value = values[key]
        names = "/".join(t.__name__ for t in types)
        if isinstance(value, bool) or not isinstance(value, types):
            raise ConfigError(f"{path}: key '{key}' must be {names}, got {type(value).__name__}")
    for key in _STRING_LISTS:
        if not all(isinstance(s, str) for s in values[key]):
            raise ConfigError(f"{path}: key '{key}' must be a list of strings")
    if values["unit_countries"] is not None and not all(isinstance(s, str) for s in values["unit_countries"]):
        raise ConfigError(f"{path}: key 'unit_countries' must be a list of strings or null")
    # The display names live in the config because Intl.DisplayNames localises countries, not regions:
    # a browser echoes a UN M49 code such as 150 back unchanged. `name` is the English name and the fallback.
    if not all(isinstance(k, str) and re.fullmatch(r"[a-z]{2}", k) and isinstance(v, str) and v
               for k, v in values["names"].items()):
        raise ConfigError(f"{path}: key 'names' must map two-letter language codes to non-empty names")
    if not values["sources"]:
        raise ConfigError(f"{path}: key 'sources' must list at least one URL")
    for mask in values["territory_mask"]:
        ok = isinstance(mask, dict) and isinstance(mask.get("name"), str) \
            and isinstance(mask.get("bbox"), list) and len(mask["bbox"]) == 4 \
            and all(isinstance(v, (int, float)) for v in mask["bbox"])
        if not ok:
            raise ConfigError(f"{path}: key 'territory_mask' entries need a 'name' and a 4-number 'bbox' [west, south, east, north]")
    if values["class_table"] is not None and not all(isinstance(v, int) for v in values["class_table"]):
        raise ConfigError(f"{path}: key 'class_table' must be a list of integers or null")
    if values["references"] is not None:
        refs = (path.parent / values["references"]).resolve()
        if not refs.is_file():
            raise ConfigError(f"{path}: key 'references' names '{values['references']}', which is not a file "
                              f"next to this config ({refs})")
        values["references"] = refs
    return RegionConfig(**values)


def poly_url(source_url: str) -> str:
    """Geofabrik publishes the extract polygon next to the PBF: <name>-latest.osm.pbf -> <name>.poly."""
    suffix = "-latest.osm.pbf"
    if not source_url.endswith(suffix):
        raise ConfigError(f"source '{source_url}' is not a Geofabrik -latest.osm.pbf URL")
    return source_url[: -len(suffix)] + ".poly"
