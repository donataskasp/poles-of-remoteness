# Stage 1: Pipeline Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `pipeline/` package (region config, resumable CLI, fetch, extract, classify, grid with a tiled exact distance transform, container, CI tests) and run Europe through the grid stage on the owner's Mac, recording runtime, memory, disk, and a tile-size measurement.

**Architecture:** A Python 3.12 package `poles` with one CLI (`poles run <region>`), a YAML region config as the only place a region is described, a `Workspace` of per-stage directories with `done.json` markers, and stage functions that are idempotent and resumable. Heavy lifting is delegated to osmium-tool and GDAL CLI tools through a subprocess wrapper that logs every command and measures it; the distance transform is scipy's exact EDT run per 4096-cell tile with overlap in a process pool.

**Tech Stack:** Python 3.12, numpy, scipy, shapely 2, pyproj, rasterio, pyogrio, PyYAML, pytest; osmium-tool 1.19 (brew) / 1.16 (Ubuntu 24.04); GDAL 3.13 (brew) / 3.11 (container); pmtiles CLI; Docker via colima on the Mac.

**Spec:** `docs/EUROPE_SPEC.md` sections 2.1, 2.3, 3.1-3.5 and `docs/EUROPE_PLAN.md` Stage 1 (tasks 1.1-1.8). Deviations are recorded in `docs/DECISIONS.md` under "2026-08-20: Stage 1 implementation decisions"; read that entry too.

## Global Constraints

- No em dashes anywhere: code, comments, docs, commit messages, issue text.
- No secrets in the repo. Nothing in code names Europe; `pipeline/regions/<region>.yaml` is the only place a region is described.
- Tests: real pytest for pipeline math and for tool behaviour we rely on for correctness (georeferencing, schema survival); nothing else. Synthetic fixtures only, no network in tests (a local HTTP server thread is fine).
- Tag sets, class table, accuracy tiers exactly as spec 2.3, 3.4, 2.4.
- Identifiers: `<region>` lowercase slug; `<snapshot>` is `YYYY-MM-DD` of the primary extract's `Last-Modified` in GMT; unit codes lowercase ISO.
- Stage functions: `run(cfg: RegionConfig, ws: Workspace, log: logging.Logger) -> dict | None`; the returned dict is stage-specific metadata; the runner adds timing and resource numbers and writes `done.json`. Idempotent: the runner skips a stage whose `done.json` exists unless `--force`.
- Branch `europe` only. Commit after every green task with explicit paths, identity Donatas / donatas.kasparavicius@gmail.com (repo-local override; verify with `git config user.email` before the first commit).
- Python: `pipeline/.venv` (created with `uv venv pipeline/.venv --python 3.12`). Run tests as `cd pipeline && .venv/bin/python -m pytest -q`. CLI tools from `/opt/homebrew/bin` (osmium, ogr2ogr, ogrinfo, gdal_rasterize, gdalwarp, gdal_translate, gdaladdo, pmtiles). `export PATH=/opt/homebrew/bin:$PATH` in every shell.
- Work data lives in `work/<region>/<snapshot>/<stage>/` under the repo root, gitignored. The Europe snapshot is `2026-08-19`; its six PBFs and `.md5` files were pre-downloaded into `work/europe/2026-08-19/fetch/` with curl, so the fetch stage must adopt existing complete files (verify, do not re-download).

## Measured facts the plan relies on

- Europe extract polygon (`europe.poly`): lon -32.68 to 46.75, lat 29.64 to 81.47, one part. In EPSG:3035 at 250 m the bbox is 26,588 x 21,625 cells bare and 28,588 x 23,625 (675 M cells, 2.7 GB float32, 7 x 6 tiles of 4096) with the 250 km margin.
- Geofabrik serves PBFs and `.md5` files through a 302 to a mirror; the mirror honours `Range` (206). `europe-latest.osm.pbf` is 34,824,371,403 bytes, `Last-Modified: Wed, 19 Aug 2026 22:18:15 GMT`; its md5 file reads `db177178703cbb0d69077af5caa8b200  europe-260819.osm.pbf` (hash first, dated name second).
- GDAL cannot convert a piped GeoJSONSeq stream into FlatGeobuf: the GeoJSONSeq driver makes a schema pass then rewinds, and `/vsistdin/` only buffers 1 MB (probe stopped at 2,132 of 3,001 features with an error). Converting from a file on disk keeps every row and every field, including fields first seen on the last feature. The extract stage therefore writes GeoJSONSeq files and deletes them after conversion.
- osmdata `land-polygons-split-4326.zip`: 925,328,500 bytes, `Last-Modified` 2026-08-20 03:37 GMT.

## File structure

```
pipeline/
  pyproject.toml            package metadata, entry point `poles`, pytest config
  requirements.txt          pinned (uv pip freeze now; pip freeze inside the container in Task 8)
  README.md                 how to run (Task 2)
  Dockerfile                Task 8
  regions/europe.yaml       Task 1
  poles/__init__.py
  poles/config.py           RegionConfig, load_region, ConfigError, poly_url
  poles/workspace.py        Workspace
  poles/stages.py           ORDER, registry()
  poles/runner.py           run_pipeline, Measured
  poles/shell.py            run_cmd, require_tools, ToolError, CmdResult
  poles/logsetup.py         get_logger
  poles/http.py             head, snapshot_id, fetch_text, download, hash_file, parse_checksum_line
  poles/cli.py              argparse, main, resolve_snapshot
  poles/fetch.py            stage fetch
  poles/osmium.py           osmium(args, log, stderr_path)
  poles/extract.py          stage extract
  poles/classify.py         classify_highway, where_clause, stage classify
  poles/poly.py             parse_poly (Osmosis .poly format)
  poles/grid.py             Frame, frame_from_polygons, rasterize helpers, tiled_edt, untiled_edt, build_land_mask, stage grid
  tests/conftest.py         fixtures: regions_dir, cfg, log, tools check, tiny_pbf, http_server
  tests/helpers.py          write_fgb (shapely geometries to FlatGeobuf via pyogrio)
  tests/fixtures/tiny.osm   hand-written OSM XML; the PBF is generated at test time with osmium
  tests/test_config.py, test_workspace.py, test_cli.py, test_fetch.py, test_classify.py, test_extract.py, test_poly.py, test_grid.py
.github/workflows/pipeline-tests.yml   Task 8
.gitignore                  add /work/
```

---

### Task 1: Package skeleton, region config, workspace

**Files:**
- Create: `pipeline/pyproject.toml`, `pipeline/requirements.txt`, `pipeline/poles/__init__.py`, `pipeline/poles/config.py`, `pipeline/poles/workspace.py`, `pipeline/regions/europe.yaml`, `pipeline/tests/conftest.py`, `pipeline/tests/test_config.py`, `pipeline/tests/test_workspace.py`
- Modify: `.gitignore` (append `/work/`)

**Interfaces:**
- Produces: `RegionConfig` (frozen dataclass, fields as in the plan's Shared interfaces plus property `all_sources` and method `is_unit_country(code) -> bool`), `load_region(path) -> RegionConfig`, `ConfigError(ValueError)`, `poly_url(source_url) -> str`; `Workspace(root, region, snapshot)` with `.root, .region, .snapshot, .base, .shared`, `.dir(stage) -> Path`, `.shared_dir() -> Path`, `.is_done(stage)`, `.mark_done(stage, meta)`, `.meta(stage) -> dict`, `.clear_done(stage)`.

- [ ] **Step 1: Package metadata and pins**

`pipeline/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "poles"
version = "0.1.0"
description = "Pole of remoteness pipeline: OSM extract to per-unit poles and explore rasters"
requires-python = ">=3.12"
dependencies = []

[project.scripts]
poles = "poles.cli:main"

[tool.setuptools.packages.find]
include = ["poles*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
```

`pipeline/requirements.txt`: the exact output of `uv pip freeze --python pipeline/.venv/bin/python` (17 lines on 2026-08-20: affine 3.0.0, attrs 26.1.0, certifi 2026.7.22, click 8.4.2, iniconfig 2.3.0, numpy 2.5.2, packaging 26.3, pluggy 1.6.0, pygments 2.21.0, pyogrio 0.13.0, pyparsing 3.3.2, pyproj 3.7.2, pytest 9.1.1, pyyaml 6.0.3, rasterio 1.5.1, scipy 1.18.0, shapely 2.1.2). Run the command and paste its output rather than typing it.

`pipeline/poles/__init__.py`: `"""Pole of remoteness pipeline."""` and `__version__ = "0.1.0"`.

Append to `.gitignore`:

```
# pipeline working data: PBFs, layers, grids; regenerable from the snapshot identity
/work/
```

Install editable: `cd pipeline && uv pip install --python .venv/bin/python -e .`

- [ ] **Step 2: Failing config tests**

`pipeline/tests/conftest.py`:

```python
import logging
from pathlib import Path

import pytest

from poles.config import load_region

REGIONS = Path(__file__).resolve().parents[1] / "regions"


@pytest.fixture
def regions_dir() -> Path:
    return REGIONS


@pytest.fixture
def cfg():
    return load_region(REGIONS / "europe.yaml")


@pytest.fixture
def log() -> logging.Logger:
    logger = logging.getLogger("poles.test")
    logger.setLevel(logging.DEBUG)
    return logger
```

`pipeline/tests/test_config.py`:

```python
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
    assert cfg.edge_mask_m == 50_000
    # DECISIONS 2026-08-20: raised from the spec table's 150 km so saturation lands in class 253
    assert cfg.max_distance_m == 250_000
    assert cfg.top_n == 10
    assert cfg.expected_units is None
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
```

- [ ] **Step 3: Run to verify failure**

Run: `cd pipeline && .venv/bin/python -m pytest -q tests/test_config.py`
Expected: FAIL (ImportError: cannot import name 'ConfigError' from 'poles.config', or ModuleNotFoundError).

- [ ] **Step 4: Region YAML and config module**

`pipeline/regions/europe.yaml`:

```yaml
# Europe region. Spec: docs/EUROPE_SPEC.md section 2.1 (Europe column).
# This file is the only place the region is described; nothing in code names it.
id: europe
name: Europe

sources:
  - https://download.geofabrik.de/europe-latest.osm.pbf
# Roads count, no units: Turkey's and Georgia's borders with these would otherwise be data edges.
supplement_sources:
  - https://download.geofabrik.de/asia/armenia-latest.osm.pbf
  - https://download.geofabrik.de/asia/azerbaijan-latest.osm.pbf
  - https://download.geofabrik.de/asia/iran-latest.osm.pbf
  - https://download.geofabrik.de/asia/iraq-latest.osm.pbf
  - https://download.geofabrik.de/asia/syria-latest.osm.pbf

coarse_crs: EPSG:3035
coarse_res_m: 250

unit_admin_level: 2
unit_countries: null          # every country in the extract ...
unit_exclude: [ru]            # ... except Russia (roads count, no unit)
unit_code_tag: ISO3166-1
# Main territory only. Generous lon/lat boxes [west, south, east, north]; stage 2 applies them.
territory_mask:
  - {name: Svalbard, bbox: [10.0, 76.0, 36.0, 81.0]}
  - {name: Jan Mayen, bbox: [-9.5, 70.7, -7.5, 71.3]}
  - {name: Franz Josef Land, bbox: [44.0, 79.5, 66.0, 82.0]}
  - {name: Novaya Zemlya, bbox: [50.0, 70.3, 70.0, 77.5]}
  - {name: Azores, bbox: [-31.5, 36.5, -24.5, 40.0]}
  - {name: Madeira, bbox: [-17.5, 32.3, -16.0, 33.3]}

edge_mask_m: 50000
# DECISIONS 2026-08-20: 250 km, not the spec table's 150 km. The tiled distance transform is exact
# below this value and saturates at it; 250 km keeps saturation inside class 253 ("240 km or more").
max_distance_m: 250000
top_n: 10
detail_res_m: 50
detail_window_m: 20000

class_table: null             # null = the default table in spec 3.4
expected_units: null          # set once counted in stage 2
transcontinental: [tr, ge]
```

`pipeline/poles/config.py`:

```python
"""Region configuration: the only place a region is described."""
from __future__ import annotations

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
    "id": (str,), "name": (str,), "sources": (list,), "supplement_sources": (list,),
    "coarse_crs": (str,), "coarse_res_m": (int,), "unit_admin_level": (int,),
    "unit_countries": (list, _NONE), "unit_exclude": (list,), "unit_code_tag": (str,),
    "territory_mask": (list,), "edge_mask_m": (int,), "max_distance_m": (int,), "top_n": (int,),
    "detail_res_m": (int,), "detail_window_m": (int,), "class_table": (list, _NONE),
    "expected_units": (int, _NONE), "transcontinental": (list,),
}
_DEFAULTS: dict[str, Any] = {
    "supplement_sources": [], "unit_countries": None, "unit_exclude": [], "territory_mask": [],
    "class_table": None, "expected_units": None, "transcontinental": [],
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
    return RegionConfig(**values)


def poly_url(source_url: str) -> str:
    """Geofabrik publishes the extract polygon next to the PBF: <name>-latest.osm.pbf -> <name>.poly."""
    suffix = "-latest.osm.pbf"
    if not source_url.endswith(suffix):
        raise ConfigError(f"source '{source_url}' is not a Geofabrik -latest.osm.pbf URL")
    return source_url[: -len(suffix)] + ".poly"
```

- [ ] **Step 5: Run config tests to verify they pass**

Run: `cd pipeline && .venv/bin/python -m pytest -q tests/test_config.py`
Expected: 7 passed.

- [ ] **Step 6: Failing workspace tests**

`pipeline/tests/test_workspace.py`:

```python
from poles.workspace import Workspace


def test_workspace_done_marker_roundtrip(tmp_path):
    ws = Workspace(tmp_path, "europe", "2026-08-19")
    assert not ws.is_done("fetch")
    ws.mark_done("fetch", {"duration_s": 1.5, "files": 6})
    assert ws.is_done("fetch")
    meta = ws.meta("fetch")
    assert meta["duration_s"] == 1.5 and meta["files"] == 6
    assert meta["stage"] == "fetch" and meta["region"] == "europe" and meta["snapshot"] == "2026-08-19"
    assert meta["finished_at"].endswith("+00:00")
    ws.clear_done("fetch")
    assert not ws.is_done("fetch")
    ws.clear_done("fetch")  # idempotent


def test_workspace_dirs_are_per_region_snapshot_stage(tmp_path):
    ws = Workspace(tmp_path, "europe", "2026-08-19")
    grid = ws.dir("grid")
    assert grid == tmp_path / "europe" / "2026-08-19" / "grid" and grid.is_dir()
    assert ws.base == tmp_path / "europe" / "2026-08-19"
    other = Workspace(tmp_path, "north-america", "2026-09-01")
    assert other.dir("grid") != grid
    assert ws.shared_dir() == other.shared_dir() == tmp_path / "shared"
    assert ws.shared_dir().is_dir()
```

- [ ] **Step 7: Run to verify failure**

Run: `cd pipeline && .venv/bin/python -m pytest -q tests/test_workspace.py`
Expected: FAIL with ModuleNotFoundError: poles.workspace.

- [ ] **Step 8: Workspace module**

`pipeline/poles/workspace.py`:

```python
"""Per-region, per-snapshot working directories and stage done-markers."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

DONE = "done.json"


class Workspace:
    """work/<region>/<snapshot>/<stage>/ plus work/shared/ for region-independent downloads."""

    def __init__(self, root: str | Path, region: str, snapshot: str):
        self.root = Path(root)
        self.region = region
        self.snapshot = snapshot
        self.base = self.root / region / snapshot
        self.shared = self.root / "shared"

    def dir(self, stage: str) -> Path:
        d = self.base / stage
        d.mkdir(parents=True, exist_ok=True)
        return d

    def shared_dir(self) -> Path:
        self.shared.mkdir(parents=True, exist_ok=True)
        return self.shared

    def is_done(self, stage: str) -> bool:
        return (self.base / stage / DONE).is_file()

    def mark_done(self, stage: str, meta: dict) -> None:
        payload = {
            "stage": stage,
            "region": self.region,
            "snapshot": self.snapshot,
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **meta,
        }
        target = self.dir(stage) / DONE
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(target)

    def meta(self, stage: str) -> dict:
        return json.loads((self.base / stage / DONE).read_text(encoding="utf-8"))

    def clear_done(self, stage: str) -> None:
        marker = self.base / stage / DONE
        if marker.exists():
            marker.unlink()
```

- [ ] **Step 9: Run all tests**

Run: `cd pipeline && .venv/bin/python -m pytest -q`
Expected: 9 passed.

- [ ] **Step 10: Commit**

```bash
git add .gitignore pipeline/pyproject.toml pipeline/requirements.txt pipeline/poles/__init__.py pipeline/poles/config.py pipeline/poles/workspace.py pipeline/regions/europe.yaml pipeline/tests/conftest.py pipeline/tests/test_config.py pipeline/tests/test_workspace.py
git commit -m "pipeline: package skeleton, Europe region config, workspace with done-markers"
```

---

### Task 2: CLI with resumable stages, runner, shell wrapper, logging

**Files:**
- Create: `pipeline/poles/stages.py`, `pipeline/poles/runner.py`, `pipeline/poles/shell.py`, `pipeline/poles/logsetup.py`, `pipeline/poles/http.py` (HEAD and snapshot id only; Task 3 extends it), `pipeline/poles/cli.py`, `pipeline/README.md`, `pipeline/tests/test_cli.py`

**Interfaces:**
- Consumes: `RegionConfig`, `load_region`, `Workspace` from Task 1.
- Produces: `stages.ORDER` (tuple of the seven names), `stages.registry() -> dict[str, StageFn | None]`; `runner.run_pipeline(cfg, ws, log, *, only: str | None, force: bool, registry: dict) -> list[str]`; `shell.run_cmd(argv, log, *, cwd=None, env=None, stdin_path=None, stdout_path=None, stderr_path=None) -> CmdResult(argv, returncode, duration_s, max_rss_bytes)`, `shell.require_tools(names)`, `shell.ToolError`, `shell.rss_bytes(ru_maxrss)`; `logsetup.get_logger(ws) -> Logger`; `http.head(url) -> dict(size, last_modified, accept_ranges, final_url)`, `http.snapshot_id(dt) -> str`; `cli.main(argv=None) -> int`, `cli.resolve_snapshot(cfg) -> str`.

- [ ] **Step 1: Failing CLI and runner tests**

`pipeline/tests/test_cli.py`:

```python
import logging

from poles import cli
from poles.runner import run_pipeline
from poles.stages import ORDER, registry
from poles.workspace import Workspace


def _stubs(calls: list[str]):
    def make(name):
        def stage(cfg, ws, log):
            calls.append(name)
            return {"n": 1}
        return stage
    return {name: make(name) for name in ORDER}


def test_registry_lists_all_seven_stages_in_order():
    assert ORDER == ("fetch", "extract", "classify", "grid", "poles", "validate", "publish")
    assert tuple(registry()) == ORDER


def test_run_executes_stages_in_order_and_skips_done(tmp_path, cfg, log):
    calls: list[str] = []
    ws = Workspace(tmp_path, "europe", "2026-08-19")
    ws.mark_done("extract", {})
    executed = run_pipeline(cfg, ws, log, only=None, force=False, registry=_stubs(calls))
    assert calls == ["fetch", "classify", "grid", "poles", "validate", "publish"]
    assert executed == calls
    assert all(ws.is_done(name) for name in ORDER)
    meta = ws.meta("fetch")
    assert meta["n"] == 1 and "duration_s" in meta and "peak_rss_self_bytes" in meta and "disk_bytes" in meta


def test_stage_flag_runs_single_stage(tmp_path, cfg, log):
    calls: list[str] = []
    ws = Workspace(tmp_path, "europe", "2026-08-19")
    run_pipeline(cfg, ws, log, only="grid", force=False, registry=_stubs(calls))
    assert calls == ["grid"]
    assert ws.is_done("grid") and not ws.is_done("fetch")


def test_force_reruns_done_stage(tmp_path, cfg, log):
    calls: list[str] = []
    ws = Workspace(tmp_path, "europe", "2026-08-19")
    ws.mark_done("grid", {"n": 0})
    run_pipeline(cfg, ws, log, only="grid", force=False, registry=_stubs(calls))
    assert calls == []
    run_pipeline(cfg, ws, log, only="grid", force=True, registry=_stubs(calls))
    assert calls == ["grid"] and ws.meta("grid")["n"] == 1


def test_unimplemented_stage_stops_the_run(tmp_path, cfg, log):
    calls: list[str] = []
    reg = _stubs(calls)
    reg["poles"] = None
    run_pipeline(cfg, ws := Workspace(tmp_path, "europe", "2026-08-19"), log, only=None, force=False, registry=reg)
    assert calls == ["fetch", "extract", "classify", "grid"]
    assert not ws.is_done("poles")


def test_failing_stage_leaves_no_done_marker(tmp_path, cfg, log):
    def boom(cfg, ws, log):
        raise RuntimeError("osmium exploded")
    reg = _stubs([])
    reg["fetch"] = boom
    ws = Workspace(tmp_path, "europe", "2026-08-19")
    try:
        run_pipeline(cfg, ws, log, only="fetch", force=False, registry=reg)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected the stage error to propagate")
    assert not ws.is_done("fetch")


def test_unknown_region_fails_with_message(tmp_path, capsys):
    rc = cli.main(["run", "atlantis", "--snapshot", "2026-01-01", "--work", str(tmp_path)])
    assert rc == 2
    assert "unknown region 'atlantis'" in capsys.readouterr().err


def test_cli_resolves_region_file_and_workspace(tmp_path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(cli, "registry", lambda: _stubs(calls))
    rc = cli.main(["run", "europe", "--stage", "fetch", "--snapshot", "2026-08-19", "--work", str(tmp_path)])
    assert rc == 0 and calls == ["fetch"]
    assert (tmp_path / "europe" / "2026-08-19" / "fetch" / "done.json").is_file()
    assert (tmp_path / "europe" / "2026-08-19" / "log.txt").is_file()


def test_run_cmd_failure_names_the_command(log):
    from poles.shell import ToolError, run_cmd
    try:
        run_cmd(["sh", "-c", "echo nope >&2; exit 3"], log)
    except ToolError as e:
        assert "exit 3" in str(e) and "sh -c" in str(e) and "nope" in str(e)
    else:
        raise AssertionError("expected ToolError")


def test_run_cmd_measures_duration_and_rss(log):
    from poles.shell import run_cmd
    res = run_cmd(["sh", "-c", "sleep 0.2"], log)
    assert res.returncode == 0 and res.duration_s >= 0.2 and res.max_rss_bytes > 0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd pipeline && .venv/bin/python -m pytest -q tests/test_cli.py`
Expected: FAIL with ModuleNotFoundError (poles.cli / poles.runner / poles.stages).

- [ ] **Step 3: Implement stages, shell, logsetup, http (head), runner, cli**

`pipeline/poles/stages.py`:

```python
"""Ordered stage registry. Each stage module registers its run function here as it lands."""
from __future__ import annotations

import logging
from typing import Callable, Optional

from .config import RegionConfig
from .workspace import Workspace

StageFn = Callable[[RegionConfig, Workspace, logging.Logger], Optional[dict]]

ORDER: tuple[str, ...] = ("fetch", "extract", "classify", "grid", "poles", "validate", "publish")


def registry() -> dict[str, StageFn | None]:
    """Stage name -> run function, or None for stages that later plan stages will add."""
    reg: dict[str, StageFn | None] = {name: None for name in ORDER}
    return reg
```

`pipeline/poles/shell.py`:

```python
"""Subprocess wrapper: logs the exact command, measures wall time and peak RSS, fails loudly."""
from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path


class ToolError(RuntimeError):
    """A required CLI tool is missing or exited non-zero. The message carries the command."""


@dataclass
class CmdResult:
    argv: list[str]
    returncode: int
    duration_s: float
    max_rss_bytes: int


def rss_bytes(ru_maxrss: int) -> int:
    """ru_maxrss is bytes on macOS and kilobytes on Linux."""
    return ru_maxrss if sys.platform == "darwin" else ru_maxrss * 1024


def require_tools(names: list[str]) -> None:
    missing = [n for n in names if shutil.which(n) is None]
    if missing:
        raise ToolError(f"missing tool(s) on PATH: {', '.join(missing)}")


def run_cmd(argv, log: logging.Logger, *, cwd=None, env=None, stdin_path=None, stdout_path=None, stderr_path=None) -> CmdResult:
    """Run argv to completion. stdout/stderr go to files when given (stderr appended), else stdout is
    discarded and stderr is captured for the error message. Peak RSS comes from wait4 on this child."""
    argv = [str(a) for a in argv]
    redirect = (f" < {stdin_path}" if stdin_path else "") + (f" > {stdout_path}" if stdout_path else "")
    log.info("$ %s%s", shlex.join(argv), redirect)
    t0 = time.monotonic()
    with ExitStack() as stack:
        stdin = stack.enter_context(open(stdin_path, "rb")) if stdin_path else subprocess.DEVNULL
        stdout = stack.enter_context(open(stdout_path, "wb")) if stdout_path else subprocess.DEVNULL
        if stderr_path:
            stderr = stack.enter_context(open(stderr_path, "ab"))
            stderr.write(f"\n$ {shlex.join(argv)}\n".encode())
            stderr.flush()
        else:
            stderr = stack.enter_context(tempfile.TemporaryFile())
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=stdin, stdout=stdout, stderr=stderr)
        _, status, ru = os.wait4(proc.pid, 0)
        proc.returncode = os.waitstatus_to_exitcode(status)
        duration = time.monotonic() - t0
        result = CmdResult(argv, proc.returncode, round(duration, 1), rss_bytes(ru.ru_maxrss))
        if proc.returncode != 0:
            stderr.flush()
            size = stderr.seek(0, os.SEEK_END)
            stderr.seek(max(0, size - 4000))
            tail = stderr.read().decode("utf-8", "replace").strip()
            raise ToolError(f"command failed with exit {proc.returncode}: {shlex.join(argv)}\n{tail}")
    log.info("done in %.0fs, peak RSS %.2f GB: %s", result.duration_s, result.max_rss_bytes / 1e9, argv[0])
    return result


def dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file())
```

`pipeline/poles/logsetup.py`:

```python
"""One logger per run: stderr plus work/<region>/<snapshot>/log.txt."""
from __future__ import annotations

import logging

from .workspace import Workspace

FORMAT = "%(asctime)s %(levelname)s %(message)s"


def get_logger(ws: Workspace) -> logging.Logger:
    logger = logging.getLogger(f"poles.{ws.region}.{ws.snapshot}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        ws.base.mkdir(parents=True, exist_ok=True)
        for handler in (logging.StreamHandler(), logging.FileHandler(ws.base / "log.txt", encoding="utf-8")):
            handler.setFormatter(logging.Formatter(FORMAT, datefmt="%Y-%m-%dT%H:%M:%S"))
            logger.addHandler(handler)
    return logger
```

`pipeline/poles/http.py` (Task 3 adds download helpers below these):

```python
"""HTTP helpers over urllib. Redirects are followed: Geofabrik serves downloads through mirrors."""
from __future__ import annotations

import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

USER_AGENT = "poles-pipeline/0.1"
TIMEOUT_S = 60


def _request(url: str, method: str = "GET", headers: dict | None = None):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT, **(headers or {})})
    return urllib.request.urlopen(req, timeout=TIMEOUT_S)


def head(url: str) -> dict:
    """size (int or None), last_modified (aware datetime or None), accept_ranges (bool), final_url."""
    with _request(url, "HEAD") as r:
        h = r.headers
        lm = h.get("Last-Modified")
        return {
            "size": int(h["Content-Length"]) if h.get("Content-Length") else None,
            "last_modified": parsedate_to_datetime(lm) if lm else None,
            "accept_ranges": h.get("Accept-Ranges", "").lower() == "bytes",
            "final_url": r.geturl(),
        }


def snapshot_id(last_modified: datetime) -> str:
    """Snapshot identity: the primary file's Last-Modified date in GMT."""
    return last_modified.astimezone(timezone.utc).strftime("%Y-%m-%d")
```

`pipeline/poles/runner.py`:

```python
"""Runs stages in order with skip, force, and per-stage resource accounting."""
from __future__ import annotations

import logging
import resource
import time

from .config import RegionConfig
from .shell import dir_size, rss_bytes
from .stages import ORDER
from .workspace import Workspace


def run_pipeline(cfg: RegionConfig, ws: Workspace, log: logging.Logger, *, only: str | None, force: bool, registry: dict) -> list[str]:
    """Returns the names of the stages that actually ran. Stops at the first unimplemented stage."""
    names = [only] if only else list(ORDER)
    executed: list[str] = []
    for name in names:
        fn = registry.get(name)
        if fn is None:
            log.info("stopping: stage '%s' is not implemented yet", name)
            break
        if ws.is_done(name) and not force:
            log.info("skip %s: done at %s", name, ws.meta(name).get("finished_at"))
            continue
        ws.clear_done(name)
        log.info("=== stage %s ===", name)
        t0 = time.monotonic()
        meta = fn(cfg, ws, log) or {}
        meta.update({
            "duration_s": round(time.monotonic() - t0, 1),
            "peak_rss_self_bytes": rss_bytes(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
            "peak_rss_children_cumulative_bytes": rss_bytes(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss),
            "disk_bytes": dir_size(ws.dir(name)),
        })
        ws.mark_done(name, meta)
        executed.append(name)
        log.info("=== %s done in %.0fs, %.2f GB on disk ===", name, meta["duration_s"], meta["disk_bytes"] / 1e9)
    return executed
```

`peak_rss_self_bytes` is the Python process's high-water mark so far (exact per stage only when stages run in separate invocations); the children figure is the max over all children so far. Stages that shell out record exact per-command numbers themselves through `run_cmd`.

`pipeline/poles/cli.py`:

```python
"""poles run <region> [--stage X] [--snapshot YYYY-MM-DD] [--work DIR] [--regions-dir DIR] [--force]"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import http
from .config import ConfigError, RegionConfig, load_region
from .logsetup import get_logger
from .runner import run_pipeline
from .stages import ORDER, registry
from .workspace import Workspace


def regions_dir(explicit: str | None) -> Path:
    return Path(explicit or os.environ.get("POLES_REGIONS") or Path(__file__).resolve().parents[1] / "regions")


def resolve_snapshot(cfg: RegionConfig) -> str:
    info = http.head(cfg.sources[0])
    if info["last_modified"] is None:
        raise ConfigError(f"{cfg.sources[0]} sent no Last-Modified header; pass --snapshot")
    return http.snapshot_id(info["last_modified"])


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="poles", description="Pole of remoteness pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the pipeline for a region")
    r.add_argument("region", help="region id, resolved to <regions-dir>/<region>.yaml")
    r.add_argument("--stage", choices=ORDER, help="run this stage only")
    r.add_argument("--snapshot", help="YYYY-MM-DD; default: Last-Modified date of the primary source")
    r.add_argument("--work", default=os.environ.get("POLES_WORK", "work"), help="work directory (default: ./work or $POLES_WORK)")
    r.add_argument("--regions-dir", help="directory of region YAML files (default: pipeline/regions or $POLES_REGIONS)")
    r.add_argument("--force", action="store_true", help="rerun stages even if their done.json exists")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = regions_dir(args.regions_dir) / f"{args.region}.yaml"
    if not path.is_file():
        print(f"poles: unknown region '{args.region}': no {path}", file=sys.stderr)
        return 2
    try:
        cfg = load_region(path)
        snapshot = args.snapshot or resolve_snapshot(cfg)
    except ConfigError as e:
        print(f"poles: {e}", file=sys.stderr)
        return 2
    ws = Workspace(args.work, cfg.id, snapshot)
    log = get_logger(ws)
    log.info("poles run %s snapshot %s work %s%s", cfg.id, snapshot, ws.base, " (forced)" if args.force else "")
    if not args.snapshot:
        log.info("snapshot taken from the primary source's Last-Modified; pass --snapshot %s to resume this one later", snapshot)
    run_pipeline(cfg, ws, log, only=args.stage, force=args.force, registry=registry())
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`pipeline/README.md`:

```markdown
# poles: the compute pipeline

One command per region: `poles run europe`. Stages `fetch, extract, classify, grid, poles, validate, publish` run in order, each resumable through `work/<region>/<snapshot>/<stage>/done.json`. `--stage X` runs one stage, `--force` reruns a finished one, `--snapshot YYYY-MM-DD` pins the snapshot (default: the primary source's Last-Modified date).

Local setup: `uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r requirements.txt -e .`; tools on PATH: osmium, ogr2ogr, ogrinfo, gdal_rasterize, gdalwarp, gdal_translate, gdaladdo, pmtiles. Tests: `.venv/bin/python -m pytest -q`. Container: `docker build -t poles pipeline/` then `docker run --rm -v "$PWD/work:/work" poles run europe --work /work`.

Regions live in `regions/<region>.yaml`; nothing in code names a region. Spec and plan: `docs/EUROPE_SPEC.md`, `docs/EUROPE_PLAN.md`.
```

- [ ] **Step 4: Run tests**

Run: `cd pipeline && .venv/bin/python -m pytest -q`
Expected: all pass (9 from Task 1 plus 10 here). Also run `cd pipeline && .venv/bin/poles run europe --stage fetch --snapshot 2026-08-19 --work ../work` and expect the log line `stopping: stage 'fetch' is not implemented yet` and exit 0 (no `done.json` written).

- [ ] **Step 5: Commit**

```bash
git add pipeline/poles/stages.py pipeline/poles/runner.py pipeline/poles/shell.py pipeline/poles/logsetup.py pipeline/poles/http.py pipeline/poles/cli.py pipeline/README.md pipeline/tests/test_cli.py
git commit -m "pipeline: poles CLI with ordered, resumable stages and measured subprocess wrapper"
```

---

### Task 3: fetch

**Files:**
- Modify: `pipeline/poles/http.py` (add `fetch_text`, `download`, `hash_file`, `parse_checksum_line`), `pipeline/poles/stages.py` (register fetch), `pipeline/tests/conftest.py` (add `http_server` fixture)
- Create: `pipeline/poles/fetch.py`, `pipeline/tests/test_fetch.py`

**Interfaces:**
- Consumes: `http.head`, `http.snapshot_id`, `config.poly_url`, `Workspace`, `cli.resolve_snapshot`.
- Produces: `http.download(url, dest: Path, log, *, expected_size: int | None = None, retries: int = 10) -> int`, `http.fetch_text(url) -> str`, `http.hash_file(path) -> dict[str, str]` (keys `md5`, `sha256`), `http.parse_checksum_line(text) -> str`; `fetch.run(cfg, ws, log) -> dict`, `fetch.FetchError`, `fetch.source_filename(url) -> str`; file layout `fetch/<basename>`, `fetch/<basename>.md5` (`<hash>  <basename>`), `fetch/<name>.poly`, `fetch/snapshot.json`:

```json
{"region": "europe", "snapshot": "2026-08-19", "created_at": "...",
 "sources": [{"url": "...", "role": "primary|supplement", "file": "europe-latest.osm.pbf", "size": 1,
              "md5": "...", "sha256": "...", "last_modified": "2026-08-19T22:18:15+00:00", "poly": "europe.poly"}]}
```

- [ ] **Step 1: Local HTTP server fixture and failing tests**

Add to `pipeline/tests/conftest.py`:

```python
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from email.utils import formatdate


class _RangeHandler(BaseHTTPRequestHandler):
    """Serves files from `directory` with Range support and a fixed Last-Modified; records requests."""
    directory: Path = Path(".")
    requests: list[tuple[str, str, str | None]] = []
    last_modified = "Wed, 19 Aug 2026 22:18:15 GMT"

    def log_message(self, *args):  # keep pytest output clean
        pass

    def _serve(self, send_body: bool):
        path = self.directory / self.path.lstrip("/")
        self.requests.append((self.command, self.path, self.headers.get("Range")))
        if not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        start, end = 0, len(data) - 1
        status = 200
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            start = int(rng[6:].split("-")[0])
            status = 206
        self.send_response(status)
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Last-Modified", self.last_modified)
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        self.end_headers()
        if send_body:
            self.wfile.write(data[start:])

    def do_GET(self):
        self._serve(True)

    def do_HEAD(self):
        self._serve(False)


@pytest.fixture
def http_server(tmp_path):
    """Yields (base_url, docroot, requests). Put files in docroot, fetch them at base_url/<name>."""
    docroot = tmp_path / "www"
    docroot.mkdir()
    handler = type("Handler", (_RangeHandler,), {"directory": docroot, "requests": []})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", docroot, handler.requests
    finally:
        server.shutdown()
```

`pipeline/tests/test_fetch.py`:

```python
import hashlib
import json
import os

import pytest

from poles import cli, fetch, http
from poles.config import RegionConfig
from poles.workspace import Workspace


def _publish(docroot, name: str, data: bytes, *, md5: str | None = None, poly: bool = True) -> None:
    (docroot / name).write_bytes(data)
    (docroot / f"{name}.md5").write_text(f"{md5 or hashlib.md5(data).hexdigest()}  {name.replace('-latest', '-260819')}\n")
    if poly:
        (docroot / name.replace("-latest.osm.pbf", ".poly")).write_text("x\n1\n 0 0\n 1 0\n 1 1\n 0 1\n 0 0\nEND\nEND\n")


def _cfg(cfg: RegionConfig, base: str, names: list[str]) -> RegionConfig:
    urls = [f"{base}/{n}" for n in names]
    return RegionConfig(**{**cfg.__dict__, "sources": urls[:1], "supplement_sources": urls[1:]})


def test_resume_partial_download(http_server, tmp_path, log):
    base, docroot, requests = http_server
    data = os.urandom(100_000)
    _publish(docroot, "a-latest.osm.pbf", data)
    dest = tmp_path / "a-latest.osm.pbf"
    dest.write_bytes(data[:40_000])
    size = http.download(f"{base}/a-latest.osm.pbf", dest, log, expected_size=len(data))
    assert size == len(data) and dest.read_bytes() == data
    assert ("GET", "/a-latest.osm.pbf", "bytes=40000-") in requests


def test_download_restarts_when_partial_file_is_too_large(http_server, tmp_path, log):
    base, docroot, _ = http_server
    data = os.urandom(10_000)
    _publish(docroot, "b-latest.osm.pbf", data)
    dest = tmp_path / "b-latest.osm.pbf"
    dest.write_bytes(os.urandom(20_000))
    http.download(f"{base}/b-latest.osm.pbf", dest, log, expected_size=len(data))
    assert dest.read_bytes() == data


def test_checksum_mismatch_raises_and_deletes_file(http_server, tmp_path, cfg, log):
    base, docroot, _ = http_server
    _publish(docroot, "c-latest.osm.pbf", b"hello world", md5="0" * 32)
    ws = Workspace(tmp_path / "work", "europe", "2026-08-19")
    with pytest.raises(fetch.FetchError, match="checksum mismatch"):
        fetch.run(_cfg(cfg, base, ["c-latest.osm.pbf"]), ws, log)
    assert not (ws.dir("fetch") / "c-latest.osm.pbf").exists()
    assert not (ws.dir("fetch") / "snapshot.json").exists()


def test_snapshot_id_from_last_modified(http_server, cfg):
    base, docroot, _ = http_server
    _publish(docroot, "d-latest.osm.pbf", b"data")
    info = http.head(f"{base}/d-latest.osm.pbf")
    assert http.snapshot_id(info["last_modified"]) == "2026-08-19"
    assert cli.resolve_snapshot(_cfg(cfg, base, ["d-latest.osm.pbf"])) == "2026-08-19"


def test_parse_checksum_line_takes_the_hash_only():
    assert http.parse_checksum_line("db177178703cbb0d69077af5caa8b200  europe-260819.osm.pbf\n") == "db177178703cbb0d69077af5caa8b200"
    with pytest.raises(ValueError):
        http.parse_checksum_line("<html>302 Found</html>")


def test_snapshot_json_lists_every_source(http_server, tmp_path, cfg, log):
    base, docroot, _ = http_server
    blobs = {n: os.urandom(5_000 + i) for i, n in enumerate(["e-latest.osm.pbf", "f-latest.osm.pbf", "g-latest.osm.pbf"])}
    for name, data in blobs.items():
        _publish(docroot, name, data)
    ws = Workspace(tmp_path / "work", "europe", "2026-08-19")
    meta = fetch.run(_cfg(cfg, base, list(blobs)), ws, log)
    snap = json.loads((ws.dir("fetch") / "snapshot.json").read_text())
    assert [s["file"] for s in snap["sources"]] == list(blobs)
    assert [s["role"] for s in snap["sources"]] == ["primary", "supplement", "supplement"]
    for s in snap["sources"]:
        data = blobs[s["file"]]
        assert s["size"] == len(data) and s["md5"] == hashlib.md5(data).hexdigest() and s["sha256"] == hashlib.sha256(data).hexdigest()
        assert s["last_modified"] == "2026-08-19T22:18:15+00:00"
        assert (ws.dir("fetch") / s["poly"]).read_text().startswith("x\n")
    assert snap["snapshot"] == "2026-08-19" and meta["files"] == 3


def test_existing_complete_file_is_verified_not_redownloaded(http_server, tmp_path, cfg, log):
    base, docroot, requests = http_server
    data = os.urandom(8_000)
    _publish(docroot, "h-latest.osm.pbf", data)
    ws = Workspace(tmp_path / "work", "europe", "2026-08-19")
    (ws.dir("fetch") / "h-latest.osm.pbf").write_bytes(data)
    fetch.run(_cfg(cfg, base, ["h-latest.osm.pbf"]), ws, log)
    assert not any(m == "GET" and p == "/h-latest.osm.pbf" for m, p, _ in requests)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd pipeline && .venv/bin/python -m pytest -q tests/test_fetch.py`
Expected: FAIL (ImportError: cannot import name 'fetch').

- [ ] **Step 3: Implement http download helpers and the fetch stage**

Append to `pipeline/poles/http.py`:

```python
import hashlib
import logging
import re
import time
import urllib.error
from pathlib import Path

CHUNK = 1 << 20
_HEX32 = re.compile(r"\b[0-9a-fA-F]{32}\b")


def fetch_text(url: str) -> str:
    with _request(url) as r:
        return r.read().decode("utf-8", "replace")


def parse_checksum_line(text: str) -> str:
    """First 32-hex token of a `<md5>  <filename>` line. Raises ValueError on anything else (an HTML error page)."""
    m = _HEX32.search(text.strip().splitlines()[0] if text.strip() else "")
    if not m:
        raise ValueError(f"no md5 hash in checksum text: {text[:80]!r}")
    return m.group(0).lower()


def hash_file(path: Path) -> dict[str, str]:
    """md5 and sha256 in one pass."""
    md5, sha = hashlib.md5(), hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            md5.update(chunk)
            sha.update(chunk)
    return {"md5": md5.hexdigest(), "sha256": sha.hexdigest()}


def download(url: str, dest: Path, log: logging.Logger, *, expected_size: int | None = None, retries: int = 10) -> int:
    """Download url to dest, resuming a partial file with a Range request. Returns the final size."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    attempt = 0
    while True:
        have = dest.stat().st_size if dest.exists() else 0
        if expected_size is not None and have == expected_size:
            return have
        if expected_size is not None and have > expected_size:
            log.warning("%s is larger than expected (%d > %d bytes); restarting", dest.name, have, expected_size)
            dest.unlink()
            have = 0
        try:
            with _request(url, headers={"Range": f"bytes={have}-"} if have else None) as r:
                if have and r.status != 206:
                    log.warning("server ignored Range for %s; restarting from zero", dest.name)
                    have = 0
                with open(dest, "ab" if have else "wb") as f:
                    done, last_log, t0 = have, time.monotonic(), time.monotonic()
                    while chunk := r.read(CHUNK):
                        f.write(chunk)
                        done += len(chunk)
                        if time.monotonic() - last_log >= 60:
                            rate = (done - have) / max(1e-6, time.monotonic() - t0) / 1e6
                            log.info("%s: %.2f GB%s at %.0f MB/s", dest.name, done / 1e9, f" of {expected_size / 1e9:.2f}" if expected_size else "", rate)
                            last_log = time.monotonic()
            size = dest.stat().st_size
            if expected_size is not None and size != expected_size:
                raise OSError(f"short download: {size} of {expected_size} bytes")
            return size
        except urllib.error.HTTPError as e:
            if e.code == 416 and dest.exists():
                return dest.stat().st_size
            attempt += 1
            if attempt > retries:
                raise
            log.warning("download of %s failed (%s); retry %d/%d", dest.name, e, attempt, retries)
            time.sleep(min(60, 5 * attempt))
        except (urllib.error.URLError, OSError) as e:
            attempt += 1
            if attempt > retries:
                raise
            log.warning("download of %s failed (%s); retry %d/%d", dest.name, e, attempt, retries)
            time.sleep(min(60, 5 * attempt))
```

`pipeline/poles/fetch.py`:

```python
"""Stage fetch: download sources and supplements, verify Geofabrik md5s, record the snapshot identity."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from . import http
from .config import RegionConfig, poly_url
from .workspace import Workspace

STAGE = "fetch"


class FetchError(RuntimeError):
    pass


def source_filename(url: str) -> str:
    return url.rsplit("/", 1)[-1]


def fetch_one(url: str, role: str, out_dir: Path, log: logging.Logger) -> dict:
    name = source_filename(url)
    dest = out_dir / name
    md5_path = out_dir / f"{name}.md5"
    info = http.head(url)
    expected_md5 = http.parse_checksum_line(http.fetch_text(url + ".md5"))
    if dest.exists() and md5_path.exists() and http.parse_checksum_line(md5_path.read_text()) != expected_md5:
        log.warning("remote %s changed since the partial download started; restarting it", name)
        dest.unlink()
    md5_path.write_text(f"{expected_md5}  {name}\n", encoding="utf-8")
    size = http.download(url, dest, log, expected_size=info["size"])
    hashes = http.hash_file(dest)
    if hashes["md5"] != expected_md5:
        dest.unlink()
        md5_path.unlink()
        raise FetchError(f"checksum mismatch for {name}: expected {expected_md5}, got {hashes['md5']}; file deleted, rerun to download it again")
    poly = out_dir / source_filename(poly_url(url))
    http.download(poly_url(url), poly, log)
    lm = info["last_modified"]
    return {
        "url": url, "role": role, "file": name, "size": size, "md5": hashes["md5"], "sha256": hashes["sha256"],
        "last_modified": lm.astimezone(timezone.utc).isoformat(timespec="seconds") if lm else None,
        "poly": poly.name,
    }


def run(cfg: RegionConfig, ws: Workspace, log: logging.Logger) -> dict:
    out_dir = ws.dir(STAGE)
    records = [fetch_one(url, "primary", out_dir, log) for url in cfg.sources]
    records += [fetch_one(url, "supplement", out_dir, log) for url in cfg.supplement_sources]
    primary_lm = records[0]["last_modified"]
    if primary_lm and http.snapshot_id(datetime.fromisoformat(primary_lm)) != ws.snapshot:
        log.warning("primary Last-Modified %s does not match snapshot %s (explicit --snapshot?)", primary_lm, ws.snapshot)
    snapshot = {
        "region": cfg.id, "snapshot": ws.snapshot,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": records,
    }
    (out_dir / "snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    log.info("fetched %d files, %.2f GB", len(records), sum(r["size"] for r in records) / 1e9)
    return {"files": len(records), "bytes": sum(r["size"] for r in records)}
```

Register in `pipeline/poles/stages.py` inside `registry()` before `return reg`:

```python
    from . import fetch
    reg["fetch"] = fetch.run
```

- [ ] **Step 4: Run tests**

Run: `cd pipeline && .venv/bin/python -m pytest -q`
Expected: all pass. Then the real thing, in the background under caffeinate (the six PBFs are already on disk, so this verifies 35 GB and downloads six `.poly` files):

```bash
cd pipeline && export PATH=/opt/homebrew/bin:$PATH && nohup caffeinate -i .venv/bin/poles run europe --stage fetch --snapshot 2026-08-19 --work ../work > ../work/europe/2026-08-19/fetch-run.log 2>&1 &
```

Expected in `fetch-run.log`: no re-download GETs of the PBFs (only HEAD, md5, poly), `fetched 6 files, 35.xx GB`, and `fetch/done.json` with `duration_s`. The orchestrator runs this, not the subagent.

- [ ] **Step 5: Commit**

```bash
git add pipeline/poles/http.py pipeline/poles/fetch.py pipeline/poles/stages.py pipeline/tests/conftest.py pipeline/tests/test_fetch.py
git commit -m "pipeline: fetch stage with resumable downloads, md5 verification, and snapshot.json"
```

---

### Task 4: classify

**Files:**
- Create: `pipeline/poles/classify.py`, `pipeline/tests/helpers.py`, `pipeline/tests/test_classify.py`
- Modify: `pipeline/poles/stages.py` (register classify)

**Interfaces:**
- Consumes: `shell.run_cmd`, `shell.require_tools`, `Workspace`; input `extract/highways.fgb` (layer `highways`, fields `osm_id` Integer64, `highway`, `name`, `ref`, `ice_road`, `winter_road`).
- Produces: `classify.SET_A`, `classify.SET_B`, `classify.classify_highway(tags: dict[str, str]) -> tuple[bool, bool]`, `classify.where_clause(scenario: "A" | "B") -> str`, `classify.run(cfg, ws, log) -> dict` writing `classify/roads_A.fgb` and `classify/roads_B.fgb` (layers `roads_A`, `roads_B`; fields `way_id` Integer64, `highway`, `name`, `ref`); `tests/helpers.write_fgb(path, layer, geoms, fields: dict[str, list], crs="EPSG:4326", geometry_type=None)`.

- [ ] **Step 1: Test helper and failing tests**

`pipeline/tests/helpers.py`:

```python
"""Write small FlatGeobuf layers from shapely geometries without pandas."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import shapely
from pyogrio.raw import write


def write_fgb(path: Path, layer: str, geoms, fields: dict[str, list], crs: str = "EPSG:4326", geometry_type: str | None = None) -> Path:
    geoms = list(geoms)
    geometry_type = geometry_type or shapely.get_type_id(geoms[0]) and shapely.get_geometry_type(geoms[0]).name.replace("_", "")
    arrays = []
    for values in fields.values():
        if all(isinstance(v, (int, np.integer)) for v in values if v is not None) and any(v is not None for v in values):
            arrays.append(np.array(values, dtype=np.int64))
        else:
            arrays.append(np.array(values, dtype=object))
    write(str(path), geometry=np.array([shapely.to_wkb(g) for g in geoms], dtype=object), field_data=arrays,
          fields=list(fields), layer=layer, driver="FlatGeobuf", geometry_type=geometry_type, crs=crs)
    return path
```

If `shapely.get_geometry_type(...).name` does not give `LineString`/`Polygon`/`Point` spelled that way, compute it with `{0: "Point", 1: "LineString", 3: "Polygon", 4: "MultiPoint", 5: "MultiLineString", 6: "MultiPolygon"}[shapely.get_type_id(geoms[0])]` instead; the requirement is that `geometry_type` is the OGR name.

`pipeline/tests/test_classify.py`:

```python
import pytest
import shapely
from pyogrio import read_info
from pyogrio.raw import read

from poles import classify
from poles.workspace import Workspace
from tests.helpers import write_fgb

SET_B = [
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
    "living_street", "service", "road", "busway",
    "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",
]
EXCLUDED = [
    "path", "footway", "cycleway", "bridleway", "steps", "pedestrian", "corridor", "proposed",
    "construction", "abandoned", "razed", "platform", "raceway", "bus_guideway", "escape", "elevator",
]

CASES = (
    [({"highway": h}, (True, True)) for h in SET_B]
    + [({"highway": "track"}, (True, False))]
    + [({"highway": h}, (False, False)) for h in EXCLUDED]
    + [
        ({"highway": "unclassified", "access": "private"}, (True, True)),   # physical, not legal
        ({"highway": "service", "motor_vehicle": "no"}, (True, True)),
        ({"highway": "track", "ice_road": "yes"}, (True, False)),
        ({"highway": "unclassified", "winter_road": "yes"}, (True, True)),
        ({"highway": "motorway_link"}, (True, True)),
        ({"highway": "proposed", "proposed": "primary"}, (False, False)),
        ({"name": "no highway tag"}, (False, False)),
        ({"highway": "bus_stop"}, (False, False)),
        ({"highway": "primary", "area": "yes"}, (True, True)),
        ({"highway": "ferry"}, (False, False)),
    ]
)


@pytest.mark.parametrize("tags,expected", CASES, ids=[str(t) for t, _ in CASES])
def test_classify_highway_table(tags, expected):
    assert classify.classify_highway(tags) == expected


def test_sets_match_spec_lists():
    assert classify.SET_B == frozenset(SET_B)
    assert classify.SET_A == frozenset(SET_B) | {"track"}
    assert not (classify.SET_A & frozenset(EXCLUDED))


def test_where_clause_is_built_from_the_sets():
    assert classify.where_clause("A") == "highway IN (" + ", ".join(f"'{h}'" for h in sorted(classify.SET_A)) + ")"
    assert "'track'" in classify.where_clause("A") and "'track'" not in classify.where_clause("B")


def _highways_fixture(ws: Workspace) -> dict[int, dict]:
    """One way per interesting tag case; returns osm_id -> tags."""
    rows = {}
    i = 0
    for tags, _ in CASES:
        if "highway" not in tags:
            continue
        i += 1
        rows[1000 + i] = tags
    geoms = [shapely.LineString([(25 + k * 0.001, 55), (25 + k * 0.001, 55.001)]) for k in range(len(rows))]
    write_fgb(ws.dir("extract") / "highways.fgb", "highways", geoms, {
        "osm_id": list(rows),
        "highway": [t.get("highway") for t in rows.values()],
        "name": [t.get("name") for t in rows.values()],
        "ref": [None for _ in rows],
        "ice_road": [t.get("ice_road") for t in rows.values()],
        "winter_road": [t.get("winter_road") for t in rows.values()],
    })
    return rows


def _way_ids(path) -> set[int]:
    meta, _, _, field_data = read(str(path), read_geometry=False)
    return set(int(v) for v in field_data[list(meta["fields"]).index("way_id")])


def test_run_matches_classify_highway_row_by_row(tmp_path, cfg, log):
    ws = Workspace(tmp_path, "europe", "2026-08-19")
    rows = _highways_fixture(ws)
    meta = classify.run(cfg, ws, log)
    got_a, got_b = _way_ids(ws.dir("classify") / "roads_A.fgb"), _way_ids(ws.dir("classify") / "roads_B.fgb")
    assert got_a == {i for i, t in rows.items() if classify.classify_highway(t)[0]}
    assert got_b == {i for i, t in rows.items() if classify.classify_highway(t)[1]}
    assert meta == {"roads_A": len(got_a), "roads_B": len(got_b)}
    info = read_info(str(ws.dir("classify") / "roads_A.fgb"))
    assert list(info["fields"]) == ["way_id", "highway", "name", "ref"]


def test_run_writes_two_layers_with_subset_relation(tmp_path, cfg, log):
    ws = Workspace(tmp_path, "europe", "2026-08-19")
    _highways_fixture(ws)
    classify.run(cfg, ws, log)
    a, b = _way_ids(ws.dir("classify") / "roads_A.fgb"), _way_ids(ws.dir("classify") / "roads_B.fgb")
    assert b < a and len(a) == len(b) + 2   # the two track rows are in A only
```

`tests/helpers` import: add an empty `pipeline/tests/__init__.py` so `from tests.helpers import write_fgb` resolves with `testpaths = ["tests"]` and rootdir `pipeline/`.

- [ ] **Step 2: Run to verify failure**

Run: `cd pipeline && .venv/bin/python -m pytest -q tests/test_classify.py`
Expected: FAIL with ImportError (poles.classify).

- [ ] **Step 3: Implement classify**

`pipeline/poles/classify.py`:

```python
"""Stage classify: scenario membership from highway tags (spec 2.3), applied to highways.fgb with ogr2ogr."""
from __future__ import annotations

import logging

from pyogrio import read_info

from .config import RegionConfig
from .shell import require_tools, run_cmd
from .workspace import Workspace

STAGE = "classify"

_BASE = ("motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
         "living_street", "service", "road", "busway")
_LINKS = ("motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link")
SET_B: frozenset[str] = frozenset(_BASE + _LINKS)
SET_A: frozenset[str] = SET_B | {"track"}
# Listed for documentation and tests; anything outside SET_A is excluded regardless of other tags.
EXCLUDED: frozenset[str] = frozenset(("path", "footway", "cycleway", "bridleway", "steps", "pedestrian", "corridor",
                                      "proposed", "construction", "abandoned", "razed", "platform", "raceway",
                                      "bus_guideway", "escape", "elevator"))


def classify_highway(tags: dict[str, str]) -> tuple[bool, bool]:
    """(in_a, in_b). Physical drivability only: access tags are ignored; ice and winter roads count when their
    highway value is in the set; a way without a highway tag is in neither."""
    hw = tags.get("highway")
    if hw is None:
        return (False, False)
    return (hw in SET_A, hw in SET_B)


def where_clause(scenario: str) -> str:
    members = {"A": SET_A, "B": SET_B}[scenario]
    return "highway IN (" + ", ".join(f"'{h}'" for h in sorted(members)) + ")"


def run(cfg: RegionConfig, ws: Workspace, log: logging.Logger) -> dict:
    require_tools(["ogr2ogr"])
    src = ws.dir("extract") / "highways.fgb"
    out_dir = ws.dir(STAGE)
    counts: dict[str, int] = {}
    for scenario in ("A", "B"):
        out = out_dir / f"roads_{scenario}.fgb"
        out.unlink(missing_ok=True)
        sql = f"SELECT osm_id AS way_id, highway, name, ref FROM highways WHERE {where_clause(scenario)}"
        run_cmd(["ogr2ogr", "-f", "FlatGeobuf", out, src, "-sql", sql, "-nln", f"roads_{scenario}",
                 "-lco", "SPATIAL_INDEX=YES"], log, stderr_path=out_dir / "tools.log")
        counts[f"roads_{scenario}"] = int(read_info(str(out))["features"])
        log.info("roads_%s: %d ways", scenario, counts[f"roads_{scenario}"])
    if counts["roads_B"] > counts["roads_A"]:
        raise RuntimeError(f"B has more ways than A ({counts}); the tag sets are broken")
    return counts
```

Register in `stages.py`: `from . import classify; reg["classify"] = classify.run`.

- [ ] **Step 4: Run tests**

Run: `cd pipeline && .venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add pipeline/poles/classify.py pipeline/poles/stages.py pipeline/tests/__init__.py pipeline/tests/helpers.py pipeline/tests/test_classify.py
git commit -m "pipeline: classify stage with the spec 2.3 tag sets, table-driven tests"
```

---

### Task 5: extract

**Files:**
- Create: `pipeline/poles/osmium.py`, `pipeline/poles/extract.py`, `pipeline/tests/fixtures/tiny.osm`, `pipeline/tests/test_extract.py`
- Modify: `pipeline/poles/stages.py` (register extract), `pipeline/tests/conftest.py` (add `tiny_pbf` fixture)

**Interfaces:**
- Consumes: `shell.run_cmd`, `shell.require_tools`, `http.download`, `http.head`, `http.hash_file`, `fetch/snapshot.json`.
- Produces: `osmium.osmium(args, log, stderr_path=None) -> CmdResult`; `extract.run(cfg, ws, log, *, land_zip: Path | None = None) -> dict` writing `extract/highways.fgb` (layer `highways`: `osm_id`, `highway`, `name`, `ref`, `ice_road`, `winter_road`), `extract/boundaries.fgb` (layer `boundaries`, polygons, `boundary = 'administrative'` only: `osm_id`, `admin_level`, `ISO3166-1`, `ISO3166-2`, `name`, `name:en`), `extract/places.fgb` (layer `places`, points: `osm_id`, `place`, `name`, `name:en`, `population`), `extract/water.fgb` (layer `water`, polygons: `osm_id`, `natural`, `water`, `name`), `work/shared/land.fgb` (layer `land`); meta `{"counts": {...}, "level2_iso_codes": [...], "land_zip_sha256": ..., "land_zip_last_modified": ...}`.

- [ ] **Step 1: Fixture, conftest fixture, failing tests**

`pipeline/tests/fixtures/tiny.osm` (nodes, then ways, then relations, ids ascending; a 2 km water square; the country ring encloses everything):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="hand">
  <node id="1" version="1" timestamp="2026-01-01T00:00:00Z" lat="55.0100" lon="25.0100"/>
  <node id="2" version="1" timestamp="2026-01-01T00:00:00Z" lat="55.0100" lon="25.0300"/>
  <node id="3" version="1" timestamp="2026-01-01T00:00:00Z" lat="55.0200" lon="25.0100"/>
  <node id="4" version="1" timestamp="2026-01-01T00:00:00Z" lat="55.0200" lon="25.0300"/>
  <node id="5" version="1" timestamp="2026-01-01T00:00:00Z" lat="54.9000" lon="24.9000"/>
  <node id="6" version="1" timestamp="2026-01-01T00:00:00Z" lat="54.9000" lon="25.2000"/>
  <node id="7" version="1" timestamp="2026-01-01T00:00:00Z" lat="55.1000" lon="25.2000"/>
  <node id="8" version="1" timestamp="2026-01-01T00:00:00Z" lat="55.1000" lon="24.9000"/>
  <node id="9" version="1" timestamp="2026-01-01T00:00:00Z" lat="55.0150" lon="25.0200">
    <tag k="place" v="village"/>
    <tag k="name" v="Kaimas"/>
    <tag k="name:en" v="Village"/>
  </node>
  <node id="10" version="1" timestamp="2026-01-01T00:00:00Z" lat="55.0400" lon="25.1000"/>
  <node id="11" version="1" timestamp="2026-01-01T00:00:00Z" lat="55.0400" lon="25.1320"/>
  <node id="12" version="1" timestamp="2026-01-01T00:00:00Z" lat="55.0580" lon="25.1320"/>
  <node id="13" version="1" timestamp="2026-01-01T00:00:00Z" lat="55.0580" lon="25.1000"/>
  <way id="101" version="1" timestamp="2026-01-01T00:00:00Z">
    <nd ref="1"/><nd ref="2"/>
    <tag k="highway" v="primary"/>
    <tag k="name" v="Main road"/>
  </way>
  <way id="102" version="1" timestamp="2026-01-01T00:00:00Z">
    <nd ref="3"/><nd ref="4"/>
    <tag k="highway" v="track"/>
    <tag k="ice_road" v="yes"/>
    <tag k="ref" v="T1"/>
  </way>
  <way id="103" version="1" timestamp="2026-01-01T00:00:00Z">
    <nd ref="5"/><nd ref="6"/><nd ref="7"/><nd ref="8"/><nd ref="5"/>
  </way>
  <way id="104" version="1" timestamp="2026-01-01T00:00:00Z">
    <nd ref="10"/><nd ref="11"/><nd ref="12"/><nd ref="13"/><nd ref="10"/>
    <tag k="natural" v="water"/>
    <tag k="water" v="lake"/>
    <tag k="name" v="Ezeras"/>
  </way>
  <relation id="201" version="1" timestamp="2026-01-01T00:00:00Z">
    <member type="way" ref="103" role="outer"/>
    <tag k="type" v="boundary"/>
    <tag k="boundary" v="administrative"/>
    <tag k="admin_level" v="2"/>
    <tag k="ISO3166-1" v="XX"/>
    <tag k="name" v="Testland"/>
    <tag k="name:en" v="Testland"/>
  </relation>
</osm>
```

Add to `pipeline/tests/conftest.py`:

```python
import shutil
import subprocess

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def tiny_pbf(tmp_path_factory) -> Path:
    """tiny.osm converted to PBF at test time; keeps binaries out of git and proves osmium is installed."""
    if shutil.which("osmium") is None:
        pytest.fail("osmium-tool is required for the extract tests (brew install osmium-tool)")
    out = tmp_path_factory.mktemp("tiny") / "tiny-latest.osm.pbf"
    subprocess.run(["osmium", "cat", "--overwrite", "-o", str(out), str(FIXTURES / "tiny.osm")], check=True)
    return out
```

`pipeline/tests/test_extract.py`:

```python
import json
import shutil
import zipfile

import pytest
import shapely
from pyogrio import read_info
from pyogrio.raw import read

from poles import extract
from poles.osmium import osmium
from poles.shell import ToolError
from poles.workspace import Workspace
from tests.helpers import write_fgb


def _land_zip(tmp_path):
    """A zip shaped like osmdata's: land-polygons-split-4326/land_polygons.shp with one square around the fixture."""
    d = tmp_path / "land-polygons-split-4326"
    d.mkdir()
    from pyogrio.raw import write
    import numpy as np
    geom = shapely.box(24.5, 54.5, 25.5, 55.5)
    write(str(d / "land_polygons.shp"), geometry=np.array([shapely.to_wkb(geom)], dtype=object), field_data=[np.array([1], dtype=np.int64)],
          fields=["FID"], driver="ESRI Shapefile", geometry_type="Polygon", crs="EPSG:4326")
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
    assert meta["level2_iso_codes"] == ["XX"]
    assert _column(ex / "places.fgb", "name") == ["Kaimas"]
    assert _column(ex / "water.fgb", "name") == ["Ezeras"]
    assert read_info(str(ex / "water.fgb"))["geometry_type"] in ("Polygon", "MultiPolygon")
    assert (ws.shared_dir() / "land.fgb").is_file() and read_info(str(ws.shared_dir() / "land.fgb"))["features"] == 1
    assert not list(ex.glob("*.geojsonseq")) and not list(ex.glob("*-filtered.pbf"))


def test_boundaries_keep_only_administrative(tmp_path, tiny_pbf, cfg, log):
    """A maritime admin_level 2 relation must not become a unit candidate."""
    ws = _workspace(tmp_path, tiny_pbf)
    extract.run(cfg, ws, log, land_zip=_land_zip(tmp_path))
    assert _column(ws.dir("extract") / "boundaries.fgb", "boundary") == ["administrative"] if "boundary" in _fields(ws.dir("extract") / "boundaries.fgb") else True


def test_osmium_failure_raises_with_command_in_message(tmp_path, log):
    with pytest.raises(ToolError) as e:
        osmium(["cat", tmp_path / "missing.osm.pbf", "-o", tmp_path / "out.pbf"], log)
    assert "osmium cat" in str(e.value) and "missing.osm.pbf" in str(e.value)
```

`test_boundaries_keep_only_administrative` as written is weak because the fixture has no maritime relation; strengthen it by adding to `tiny.osm` a second relation 202 with `type=boundary`, `boundary=maritime`, `admin_level=2`, `name=EEZ` using the same way 103 as outer, and assert `meta["counts"]["boundaries"] == 1` and `_column(..., "name") == ["Testland"]`. Do that: edit the fixture, then the first test's `boundaries: 1` count proves the filter.

- [ ] **Step 2: Run to verify failure**

Run: `cd pipeline && .venv/bin/python -m pytest -q tests/test_extract.py`
Expected: FAIL with ImportError (poles.extract / poles.osmium).

- [ ] **Step 3: Implement osmium wrapper and extract**

`pipeline/poles/osmium.py`:

```python
"""Thin osmium-tool wrapper: the exact command is logged and any failure names it."""
from __future__ import annotations

import logging
from pathlib import Path

from .shell import CmdResult, run_cmd


def osmium(args: list, log: logging.Logger, stderr_path: Path | None = None, stdout_path: Path | None = None) -> CmdResult:
    return run_cmd(["osmium", *args], log, stderr_path=stderr_path, stdout_path=stdout_path)
```

`pipeline/poles/extract.py`:

```python
"""Stage extract: filter and merge the PBFs with osmium, export layers to FlatGeobuf, fetch land polygons."""
from __future__ import annotations

import json
import logging
import shutil
import zipfile
from pathlib import Path

from pyogrio import read_info
from pyogrio.raw import read

from . import http
from .config import RegionConfig
from .osmium import osmium
from .shell import require_tools, run_cmd
from .workspace import Workspace

STAGE = "extract"
LAND_URL = "https://osmdata.openstreetmap.de/download/land-polygons-split-4326.zip"
LAND_DIRNAME = "land-polygons-split-4326"
PLACES = "city,town,village,hamlet,isolated_dwelling"

# osmium export configs: which tags each layer keeps; ids and types become osm_id / osm_type.
_LAYERS = {
    "highways": {"filter": ["w/highway"], "geometry": "linestring",
                 "tags": ["highway", "name", "ref", "ice_road", "winter_road"], "where": None},
    "boundaries": {"filter": None, "geometry": "polygon",
                   "tags": ["boundary", "admin_level", "ISO3166-1", "ISO3166-2", "name", "name:en"],
                   "where": "boundary = 'administrative'"},
    "places": {"filter": [f"n/place={PLACES}"], "geometry": "point",
               "tags": ["place", "name", "name:en", "population"], "where": None},
    "water": {"filter": ["wr/natural=water"], "geometry": "polygon",
              "tags": ["natural", "water", "name"], "where": None},
}


def _admin_filters(cfg: RegionConfig) -> list[str]:
    return [f"r/admin_level={level}" for level in sorted({2, cfg.unit_admin_level})]


def _export_config(path: Path, tags: list[str]) -> Path:
    path.write_text(json.dumps({
        "attributes": {"type": "osm_type", "id": "osm_id"},
        "linear_tags": True, "area_tags": True,
        "include_tags": tags,
    }, indent=2), encoding="utf-8")
    return path


def _feature_count(path: Path) -> int:
    return int(read_info(str(path))["features"])


def export_layer(pbf: Path, name: str, spec: dict, out_dir: Path, log: logging.Logger, tools_log: Path) -> int:
    """osmium export to a GeoJSONSeq file, then ogr2ogr to FlatGeobuf (GDAL needs a seekable file for its
    schema pass; piping through /vsistdin/ stops at 1 MB). The text file is deleted afterwards."""
    cfg_path = _export_config(out_dir / f"export-{name}.json", spec["tags"])
    seq = out_dir / f"{name}.geojsonseq"
    fgb = out_dir / f"{name}.fgb"
    fgb.unlink(missing_ok=True)
    osmium(["export", "--overwrite", "-f", "geojsonseq", "-c", cfg_path, f"--geometry-types={spec['geometry']}",
            "-o", seq, pbf], log, stderr_path=tools_log)
    cmd = ["ogr2ogr", "-f", "FlatGeobuf", fgb, seq, "-nln", name, "-lco", "SPATIAL_INDEX=YES"]
    if spec["where"]:
        cmd += ["-where", spec["where"]]
    run_cmd(cmd, log, stderr_path=tools_log)
    seq.unlink()
    return _feature_count(fgb)


def ensure_land(shared: Path, log: logging.Logger, tools_log: Path, land_zip: Path | None = None) -> tuple[Path, dict]:
    """Download osmdata's split land polygons once into work/shared/ and convert them to land.fgb."""
    zip_path = land_zip or shared / f"{LAND_DIRNAME}.zip"
    info: dict = {}
    if land_zip is None:
        head = http.head(LAND_URL)
        http.download(LAND_URL, zip_path, log, expected_size=head["size"])
        info["land_zip_last_modified"] = head["last_modified"].isoformat() if head["last_modified"] else None
    info["land_zip_sha256"] = http.hash_file(zip_path)["sha256"]
    fgb = shared / "land.fgb"
    if not fgb.exists():
        unzip_dir = shared / LAND_DIRNAME
        if not unzip_dir.exists():
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(shared)
        shp = next(unzip_dir.glob("*.shp"))
        run_cmd(["ogr2ogr", "-f", "FlatGeobuf", fgb, shp, "-nln", "land", "-lco", "SPATIAL_INDEX=YES"], log, stderr_path=tools_log)
    return fgb, info


def run(cfg: RegionConfig, ws: Workspace, log: logging.Logger, *, land_zip: Path | None = None) -> dict:
    require_tools(["osmium", "ogr2ogr"])
    fetch_dir, out_dir = ws.dir("fetch"), ws.dir(STAGE)
    tools_log = out_dir / "tools.log"
    snapshot = json.loads((fetch_dir / "snapshot.json").read_text(encoding="utf-8"))
    pbfs = [fetch_dir / s["file"] for s in snapshot["sources"]]
    all_filters = ["w/highway", *_admin_filters(cfg), f"n/place={PLACES}", "wr/natural=water"]

    filtered = []
    for pbf in pbfs:
        out = out_dir / f"{pbf.name.removesuffix('.osm.pbf')}-filtered.pbf"
        osmium(["tags-filter", "--overwrite", "-o", out, pbf, *all_filters], log, stderr_path=tools_log)
        filtered.append(out)
    merged = out_dir / "filtered.pbf"
    if len(filtered) == 1:
        filtered[0].replace(merged)
    else:
        osmium(["merge", "--overwrite", "-o", merged, *filtered], log, stderr_path=tools_log)
        for f in filtered:
            f.unlink()

    counts: dict[str, int] = {}
    for name, spec in _LAYERS.items():
        thematic = out_dir / f"{name}.pbf"
        osmium(["tags-filter", "--overwrite", "-o", thematic, merged, *(spec["filter"] or _admin_filters(cfg))], log, stderr_path=tools_log)
        counts[name] = export_layer(thematic, name, spec, out_dir, log, tools_log)
        log.info("%s: %d features", name, counts[name])

    land_fgb, land_info = ensure_land(ws.shared_dir(), log, tools_log, land_zip)
    counts["land"] = _feature_count(land_fgb)

    meta_b, _, _, cols = read(str(out_dir / "boundaries.fgb"), read_geometry=False, columns=["admin_level", "ISO3166-1"]) \
        if "ISO3166-1" in read_info(str(out_dir / "boundaries.fgb"))["fields"] else ({"fields": []}, None, None, [])
    codes = sorted({str(code) for level, code in zip(cols[0], cols[1]) if str(level) == "2" and code}) if cols else []
    log.info("admin_level 2 polygons with ISO3166-1: %d (%s)", len(codes), " ".join(codes))
    return {"counts": counts, "level2_iso_codes": codes, **land_info}
```

Notes for the implementer: check `osmium export --help` (1.19 local, 1.16 in the container) for the config keys `attributes`, `linear_tags`, `area_tags`, `include_tags`; if `include_tags` is not honoured, fall back to exporting all tags and selecting columns in ogr2ogr with `-select` (a warning, not an error, for absent fields). If `osmium export` needs more than flex_mem can hold for Europe, add `-i sparse_file_array,<out_dir>/nodes.idx`; the plan expects flex_mem to fit (about 5 GB for Europe's highways). Do not pipe into `/vsistdin/`.

Register in `stages.py`: `from . import extract; reg["extract"] = extract.run`.

- [ ] **Step 4: Run tests**

Run: `cd pipeline && .venv/bin/python -m pytest -q`
Expected: all pass, including the five-layer count test with `boundaries: 1` despite the maritime relation.

- [ ] **Step 5: Commit**

```bash
git add pipeline/poles/osmium.py pipeline/poles/extract.py pipeline/poles/stages.py pipeline/tests/conftest.py pipeline/tests/fixtures/tiny.osm pipeline/tests/test_extract.py
git commit -m "pipeline: extract stage: osmium filter and merge, FlatGeobuf layers, osmdata land polygons"
```

---

### Task 6: grid (frame, rasterize, tiled EDT, land mask)

**Files:**
- Create: `pipeline/poles/poly.py`, `pipeline/poles/grid.py`, `pipeline/tests/test_poly.py`, `pipeline/tests/test_grid.py`
- Modify: `pipeline/poles/stages.py` (register grid)

**Interfaces:**
- Consumes: `shell.run_cmd`, `shell.require_tools`, `shell.rss_bytes`, `fetch/snapshot.json` (`poly` per source), `classify/roads_A.fgb`, `classify/roads_B.fgb`, `extract/water.fgb`, `work/shared/land.fgb`.
- Produces: `poly.parse_poly(path) -> shapely (Multi)Polygon` (lon/lat); `grid.Frame(crs, res, x0, y1, width, height)` with `x1`, `y0`, `transform`, `to_dict()`, `Frame.from_dict()`; `grid.frame_from_polygons(polys, src_crs, crs, res, margin_m) -> Frame`; `grid.create_raster(frame, path, dtype="uint8", nodata=None)`; `grid.rasterize(src, layer, target_tif, log, tools_log, *, burn=1, all_touched=False, sql=None)`; `grid.untiled_edt(mask, res_m) -> float32 array`; `grid.tiled_edt(road_mask, res_m, overlap_cells, tile=4096, workers=None, max_m=None, stats=None) -> float32 array`; `grid.build_land_mask(land_fgb, water_fgb, frame, out_tif, min_water_m2, log, workdir)`; `grid.run(cfg, ws, log) -> dict` writing `grid/frame.json`, `grid/roads_A.tif`, `grid/roads_B.tif`, `grid/dist_A.tif`, `grid/dist_B.tif`, `grid/land.tif`, with meta `{"frame": {...}, "steps": {name: {"duration_s", "peak_rss_self_bytes", "tool_peak_rss_bytes"|"worker_peak_rss_bytes"}}, "road_cells_A", "road_cells_B", "land_cells", "a_le_b_violations": 0, "edt": {"tiles", "overlap_cells", "doublings", "saturated_cells_A", "saturated_cells_B"}}`.

- [ ] **Step 1: Failing poly test**

`pipeline/tests/test_poly.py`:

```python
from poles.poly import parse_poly

SAMPLE = """europe
1
   0.0   0.0
   4.0   0.0
   4.0   4.0
   0.0   4.0
   0.0   0.0
END
!hole
   1.0   1.0
   2.0   1.0
   2.0   2.0
   1.0   2.0
   1.0   1.0
END
2
   10.0  10.0
   11.0  10.0
   11.0  11.0
   10.0  11.0
   10.0  10.0
END
END
"""


def test_parse_poly_with_hole_and_two_parts(tmp_path):
    p = tmp_path / "s.poly"
    p.write_text(SAMPLE)
    geom = parse_poly(p)
    assert abs(geom.area - (16 - 1 + 1)) < 1e-9
    assert geom.bounds == (0.0, 0.0, 11.0, 11.0)
    assert not geom.contains(__import__("shapely").Point(1.5, 1.5))
```

- [ ] **Step 2: Run to verify failure**

Run: `cd pipeline && .venv/bin/python -m pytest -q tests/test_poly.py`
Expected: FAIL (ModuleNotFoundError: poles.poly).

- [ ] **Step 3: Implement poly**

`pipeline/poles/poly.py`:

```python
"""Osmosis .poly files (Geofabrik extract polygons): sections are rings, a leading '!' marks a hole."""
from __future__ import annotations

from pathlib import Path

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


def parse_poly(path: Path) -> BaseGeometry:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    outers: list[Polygon] = []
    holes: list[Polygon] = []
    i = 1  # line 0 is the name
    while i < len(lines):
        header = lines[i].strip()
        i += 1
        if header == "END" or not header:
            continue
        is_hole = header.startswith("!")
        coords = []
        while i < len(lines) and lines[i].strip() != "END":
            x, y = lines[i].split()
            coords.append((float(x), float(y)))
            i += 1
        i += 1  # the ring's END
        (holes if is_hole else outers).append(Polygon(coords))
    geom = unary_union(outers)
    for hole in holes:
        geom = geom.difference(hole)
    return geom
```

- [ ] **Step 4: Run poly test**

Run: `cd pipeline && .venv/bin/python -m pytest -q tests/test_poly.py`
Expected: 1 passed.

- [ ] **Step 5: Failing grid tests**

`pipeline/tests/test_grid.py`:

```python
import numpy as np
import pytest
import rasterio
import shapely
from pyproj import Transformer
from scipy.ndimage import distance_transform_edt

from poles import grid
from tests.helpers import write_fgb


# ---------- distance transform ----------

def test_untiled_edt_is_scipy_times_res():
    mask = np.zeros((10, 10), bool)
    mask[5, 5] = True
    got = grid.untiled_edt(mask, 250.0)
    assert got.dtype == np.float32
    assert np.array_equal(got, (distance_transform_edt(~mask) * 250.0).astype(np.float32))


def test_tiled_equals_untiled_random_sparse_roads():
    rng = np.random.default_rng(7)
    mask = rng.random((200, 200)) < 0.01
    ref = grid.untiled_edt(mask, 250.0)
    got = grid.tiled_edt(mask, 250.0, overlap_cells=20, tile=64, workers=2)
    assert got.dtype == np.float32 and got.shape == mask.shape
    assert np.array_equal(got, ref)


def test_tiled_equals_untiled_when_overlap_too_small_forces_doubling():
    mask = np.zeros((300, 300), bool)
    mask[0, 0] = True
    ref = grid.untiled_edt(mask, 50.0)
    stats = {}
    got = grid.tiled_edt(mask, 50.0, overlap_cells=16, tile=128, workers=1, stats=stats)
    assert np.array_equal(got, ref)
    assert stats["doublings"] > 0


def test_max_m_saturates_far_cells_and_keeps_near_cells_exact():
    mask = np.zeros((300, 300), bool)
    mask[150, 150] = True
    ref = grid.untiled_edt(mask, 10.0)
    stats = {}
    got = grid.tiled_edt(mask, 10.0, overlap_cells=8, tile=100, workers=1, max_m=500.0, stats=stats)
    near = ref < 500.0
    assert np.array_equal(got[near], ref[near])
    assert np.all(got[~near] == np.float32(500.0))
    assert stats["saturated_cells"] == int((~near).sum())


def test_no_roads_raises_without_cap_and_saturates_with_cap():
    mask = np.zeros((50, 50), bool)
    with pytest.raises(ValueError, match="no road"):
        grid.tiled_edt(mask, 1.0, overlap_cells=4, tile=25, workers=1)
    assert np.all(grid.tiled_edt(mask, 1.0, overlap_cells=4, tile=25, workers=1, max_m=9.0) == np.float32(9.0))


def test_tiled_handles_non_multiple_shapes_and_all_road_tiles():
    mask = np.zeros((130, 70), bool)
    mask[:64, :64] = True
    ref = grid.untiled_edt(mask, 1.0)
    assert np.array_equal(grid.tiled_edt(mask, 1.0, overlap_cells=8, tile=64, workers=2), ref)


# ---------- frame ----------

def test_frame_bounds_snap_outward_to_resolution():
    poly = shapely.box(100.3, 200.7, 1100.2, 1300.9)
    f = grid.frame_from_polygons([poly], "EPSG:3035", "EPSG:3035", 250, margin_m=0)
    assert (f.x0, f.y0, f.x1, f.y1) == (0, 0, 1250, 1500)
    assert (f.width, f.height) == (5, 6)
    g = grid.frame_from_polygons([poly], "EPSG:3035", "EPSG:3035", 250, margin_m=300)
    assert (g.x0, g.y0, g.x1, g.y1) == (-250, -250, 1500, 1750)
    assert grid.Frame.from_dict(g.to_dict()) == g


def test_frame_reprojects_lonlat_polygon():
    f = grid.frame_from_polygons([shapely.box(9.9, 51.9, 10.1, 52.1)], "EPSG:4326", "EPSG:3035", 250, 0)
    cx, cy = (f.x0 + f.x1) / 2, (f.y0 + f.y1) / 2
    assert abs(cx - 4_321_000) < 1_000 and abs(cy - 3_210_000) < 1_000
    assert f.transform.a == 250 and f.transform.e == -250


# ---------- rasterize and land mask (need gdal_rasterize, ogr2ogr) ----------

def _frame_20km() -> grid.Frame:
    return grid.Frame("EPSG:3035", 250, 4_300_000, 3_220_000, 80, 80)


def test_rasterize_lonlat_roads_land_in_projected_frame(tmp_path, log):
    frame = _frame_20km()
    to_lonlat = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True).transform
    cx, cy = 4_310_125, 3_209_875   # centre of cell (row 40, col 40)
    line = shapely.LineString([to_lonlat(cx - 600, cy), to_lonlat(cx + 600, cy)])
    write_fgb(tmp_path / "roads.fgb", "roads", [line], {"way_id": [1]}, crs="EPSG:4326")
    out = tmp_path / "roads.tif"
    grid.create_raster(frame, out)
    grid.rasterize(tmp_path / "roads.fgb", "roads", out, log, tmp_path / "tools.log", burn=1, all_touched=True)
    with rasterio.open(out) as ds:
        arr = ds.read(1)
        assert ds.crs.to_epsg() == 3035 and ds.transform == frame.transform
    assert arr[40, 40] == 1 and arr[40, 38] == 1 and arr[40, 42] == 1
    assert 5 <= arr.sum() <= 12 and arr[0, 0] == 0


def test_land_mask_subtracts_lakes_over_threshold_only(tmp_path, log):
    frame = _frame_20km()
    land = shapely.box(4_300_000, 3_200_000, 4_320_000, 3_220_000)
    big = shapely.box(4_305_000, 3_205_000, 4_307_000, 3_207_000)        # 4 km2: removed
    small = shapely.box(4_312_000, 3_212_000, 4_312_500, 3_212_500)      # 0.25 km2: stays land
    write_fgb(tmp_path / "land.fgb", "land", [land], {"fid": [1]}, crs="EPSG:3035")
    write_fgb(tmp_path / "water.fgb", "water", [big, small], {"osm_id": [1, 2]}, crs="EPSG:3035")
    out = tmp_path / "land.tif"
    grid.build_land_mask(tmp_path / "land.fgb", tmp_path / "water.fgb", frame, out, 1_000_000, log, tmp_path)
    with rasterio.open(out) as ds:
        arr = ds.read(1)
    row = lambda y: int((frame.y1 - y) // frame.res)
    col = lambda x: int((x - frame.x0) // frame.res)
    assert arr[row(3_206_000), col(4_306_000)] == 0
    assert arr[row(3_212_250), col(4_312_250)] == 1
    assert arr[10, 10] == 1
    assert int(arr.sum()) == 80 * 80 - 64


def test_land_mask_with_lonlat_inputs(tmp_path, log):
    """The real inputs are WGS84: land from osmdata, water from OSM. The mask must still land in the frame."""
    frame = _frame_20km()
    to_lonlat = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    land = shapely.ops.transform(to_lonlat.transform, shapely.box(4_300_000, 3_200_000, 4_320_000, 3_220_000).segmentize(250))
    lake = shapely.ops.transform(to_lonlat.transform, shapely.box(4_305_000, 3_205_000, 4_307_000, 3_207_000).segmentize(100))
    write_fgb(tmp_path / "land.fgb", "land", [land], {"fid": [1]}, crs="EPSG:4326")
    write_fgb(tmp_path / "water.fgb", "water", [lake], {"osm_id": [1]}, crs="EPSG:4326")
    out = tmp_path / "land.tif"
    grid.build_land_mask(tmp_path / "land.fgb", tmp_path / "water.fgb", frame, out, 1_000_000, log, tmp_path)
    with rasterio.open(out) as ds:
        arr = ds.read(1)
    assert arr[int((3_220_000 - 3_206_000) // 250), int((4_306_000 - 4_300_000) // 250)] == 0
    assert abs(int(arr.sum()) - (6400 - 64)) <= 40
```

- [ ] **Step 6: Run to verify failure**

Run: `cd pipeline && .venv/bin/python -m pytest -q tests/test_grid.py`
Expected: FAIL (ModuleNotFoundError: poles.grid).

- [ ] **Step 7: Implement grid**

`pipeline/poles/grid.py`:

```python
"""Stage grid: raster frame, road masks, tiled exact Euclidean distance transform, land mask."""
from __future__ import annotations

import json
import logging
import math
import os
import resource
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import rasterio
import shapely
from pyproj import CRS, Transformer
from rasterio.transform import Affine, from_origin
from rasterio.windows import Window
from scipy.ndimage import distance_transform_edt
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shp_transform, unary_union

from .config import RegionConfig
from .poly import parse_poly
from .shell import require_tools, rss_bytes, run_cmd
from .workspace import Workspace

STAGE = "grid"
TILE = 4096
GTIFF_OPTS = dict(driver="GTiff", tiled=True, blockxsize=512, blockysize=512, compress="deflate", bigtiff="IF_SAFER")


class GridError(RuntimeError):
    pass


# ---------- frame ----------

@dataclass(frozen=True)
class Frame:
    crs: str
    res: float
    x0: float
    y1: float
    width: int
    height: int

    @property
    def x1(self) -> float:
        return self.x0 + self.width * self.res

    @property
    def y0(self) -> float:
        return self.y1 - self.height * self.res

    @property
    def transform(self) -> Affine:
        return from_origin(self.x0, self.y1, self.res, self.res)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Frame":
        return cls(**d)


def frame_from_polygons(polys: list[BaseGeometry], src_crs: str, crs: str, res: float, margin_m: float) -> Frame:
    """Bbox of the polygons in `crs`, expanded by margin_m, snapped outward to multiples of res."""
    if CRS(src_crs) != CRS(crs):
        tr = Transformer.from_crs(src_crs, crs, always_xy=True).transform
        seg = 0.1 if CRS(src_crs).is_geographic else res
        polys = [shp_transform(tr, shapely.segmentize(p, seg)) for p in polys]
    minx, miny, maxx, maxy = unary_union(polys).bounds
    x0 = math.floor((minx - margin_m) / res) * res
    y0 = math.floor((miny - margin_m) / res) * res
    x1 = math.ceil((maxx + margin_m) / res) * res
    y1 = math.ceil((maxy + margin_m) / res) * res
    return Frame(crs, res, x0, y1, int(round((x1 - x0) / res)), int(round((y1 - y0) / res)))


# ---------- rasters ----------

def create_raster(frame: Frame, path: Path, dtype: str = "uint8", nodata=None) -> Path:
    """An all-zero single-band GeoTIFF on the frame, for gdal_rasterize to burn into."""
    with rasterio.open(path, "w", width=frame.width, height=frame.height, count=1, dtype=dtype, crs=frame.crs,
                       transform=frame.transform, nodata=nodata, **GTIFF_OPTS) as ds:
        block = np.zeros((512, frame.width), dtype=dtype)
        for row in range(0, frame.height, 512):
            h = min(512, frame.height - row)
            ds.write(block[:h], 1, window=Window(0, row, frame.width, h))
    return path


def rasterize(src: Path, layer: str, target_tif: Path, log: logging.Logger, tools_log: Path, *, burn: int = 1,
              all_touched: bool = False, sql: str | None = None) -> None:
    """gdal_rasterize into an existing raster; GDAL reprojects the layer to the raster's CRS on the fly."""
    cmd = ["gdal_rasterize", "--config", "GDAL_CACHEMAX", "4096", "-burn", str(burn)]
    if all_touched:
        cmd.append("-at")
    cmd += ["-sql", sql] if sql else ["-l", layer]
    cmd += [src, target_tif]
    run_cmd(cmd, log, stderr_path=tools_log)


def write_float_tif(path: Path, data: np.ndarray, frame: Frame) -> None:
    with rasterio.open(path, "w", width=frame.width, height=frame.height, count=1, dtype="float32", crs=frame.crs,
                       transform=frame.transform, predictor=3, **GTIFF_OPTS) as ds:
        ds.write(data, 1)


def build_land_mask(land_fgb: Path, water_fgb: Path, frame: Frame, out_tif: Path, min_water_m2: float,
                    log: logging.Logger, workdir: Path) -> None:
    """land = 1 where osmdata land polygons cover the cell centre, minus water polygons of at least min_water_m2
    (area measured in the frame's equal-area CRS). Cell-centre rule for both; no ALL_TOUCHED."""
    tools_log = Path(workdir) / "tools.log"
    create_raster(frame, out_tif)
    rasterize(land_fgb, "land", out_tif, log, tools_log, burn=1)
    water_proj = Path(workdir) / "water_proj.fgb"
    water_proj.unlink(missing_ok=True)
    run_cmd(["ogr2ogr", "-f", "FlatGeobuf", water_proj, water_fgb, "-t_srs", frame.crs, "-nln", "water",
             "-nlt", "PROMOTE_TO_MULTI", "-lco", "SPATIAL_INDEX=YES"], log, stderr_path=tools_log)
    rasterize(water_proj, "water", out_tif, log, tools_log, burn=0,
              sql=f"SELECT * FROM water WHERE OGR_GEOM_AREA >= {float(min_water_m2)}")


# ---------- distance transform ----------

def untiled_edt(mask: np.ndarray, res_m: float) -> np.ndarray:
    """Single-array reference: metres to the nearest True cell. Debug fallback (POLES_EDT_UNTILED=1)."""
    if not mask.any():
        raise ValueError("no road cell in the mask")
    return (distance_transform_edt(~mask) * res_m).astype(np.float32)


def _tile_job(args):
    mask_path, out_path, shape, r0, r1, c0, c1, overlap, res_m = args
    mask = np.load(mask_path, mmap_mode="r")
    H, W = shape
    wr0, wr1 = max(0, r0 - overlap), min(H, r1 + overlap)
    wc0, wc1 = max(0, c0 - overlap), min(W, c1 + overlap)
    window = np.ascontiguousarray(mask[wr0:wr1, wc0:wc1])
    full = (wr0, wr1, wc0, wc1) == (0, H, 0, W)
    out = np.load(out_path, mmap_mode="r+")
    if not window.any():
        out[r0:r1, c0:c1] = np.inf
        unresolved = 0 if full else (r1 - r0) * (c1 - c0)
    else:
        d = distance_transform_edt(~window)[r0 - wr0:r1 - wr0, c0 - wc0:c1 - wc0]
        out[r0:r1, c0:c1] = (d * res_m).astype(np.float32)
        unresolved = 0 if full else int(np.count_nonzero(d >= overlap))
    out.flush()
    del out
    return (r0, c0, unresolved, rss_bytes(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))


def tiled_edt(road_mask: np.ndarray, res_m: float, overlap_cells: int, tile: int = TILE, workers: int | None = None,
              max_m: float | None = None, stats: dict | None = None) -> np.ndarray:
    """Distance in metres to the nearest True cell, computed per tile with overlap.

    A core cell whose result is below the overlap is exact: any closer road outside the window would be farther
    than the overlap. Cells at or above it are recomputed with doubled overlap until none remain, or, when max_m
    is given, until overlap * res_m >= max_m, after which they are set to max_m ("at least this far"). With
    max_m = None the result is bit-identical to untiled_edt everywhere."""
    H, W = road_mask.shape
    workers = workers or max(1, (os.cpu_count() or 2) - 2)
    tiles = [(r0, min(r0 + tile, H), c0, min(c0 + tile, W)) for r0 in range(0, H, tile) for c0 in range(0, W, tile)]
    pending = {t: int(overlap_cells) for t in tiles}
    doublings = 0
    peak = 0
    with tempfile.TemporaryDirectory(prefix="poles-edt-") as td:
        mask_path = Path(td) / "mask.npy"
        out_path = Path(td) / "dist.npy"
        np.save(mask_path, np.ascontiguousarray(road_mask, dtype=bool))
        np.lib.format.open_memmap(out_path, mode="w+", dtype=np.float32, shape=(H, W)).flush()
        while pending:
            jobs = [(str(mask_path), str(out_path), (H, W), *t, ov, float(res_m)) for t, ov in pending.items()]
            if workers == 1 or len(jobs) == 1:
                results = [_tile_job(j) for j in jobs]
            else:
                with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
                    results = list(pool.map(_tile_job, jobs))
            nxt: dict = {}
            for (t, ov), (_, _, unresolved, rss) in zip(pending.items(), results):
                peak = max(peak, rss)
                if unresolved and not (max_m is not None and ov * res_m >= max_m):
                    nxt[t] = ov * 2
            if nxt:
                doublings += 1
            pending = nxt
        dist = np.array(np.load(out_path, mmap_mode="r"))
    saturated = 0
    if max_m is not None:
        sat = ~(dist < max_m)
        saturated = int(sat.sum())
        dist[sat] = np.float32(max_m)
    elif not np.isfinite(dist).all():
        raise ValueError("no road cell in the mask")
    if stats is not None:
        stats.update({"tiles": len(tiles), "overlap_cells": int(overlap_cells), "doublings": doublings,
                      "saturated_cells": saturated, "worker_peak_rss_bytes": peak})
    return dist


# ---------- stage ----------

@contextmanager
def _step(log: logging.Logger, meta: dict, name: str):
    t0 = time.monotonic()
    log.info("-- %s", name)
    info: dict = {}
    yield info
    info.update({"duration_s": round(time.monotonic() - t0, 1),
                 "peak_rss_self_bytes": rss_bytes(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)})
    meta["steps"][name] = info
    log.info("-- %s done in %.0fs", name, info["duration_s"])


def _count_violations(a_tif: Path, b_tif: Path) -> int:
    violations = 0
    with rasterio.open(a_tif) as a, rasterio.open(b_tif) as b:
        for _, window in a.block_windows(1):
            violations += int(np.count_nonzero(a.read(1, window=window) > b.read(1, window=window)))
    return violations


def run(cfg: RegionConfig, ws: Workspace, log: logging.Logger) -> dict:
    require_tools(["gdal_rasterize", "ogr2ogr"])
    fetch_dir, extract_dir, classify_dir, out_dir = ws.dir("fetch"), ws.dir("extract"), ws.dir("classify"), ws.dir(STAGE)
    tools_log = out_dir / "tools.log"
    snapshot = json.loads((fetch_dir / "snapshot.json").read_text(encoding="utf-8"))
    primary_polys = [parse_poly(fetch_dir / s["poly"]) for s in snapshot["sources"] if s["role"] == "primary"]
    frame = frame_from_polygons(primary_polys, "EPSG:4326", cfg.coarse_crs, cfg.coarse_res_m, cfg.max_distance_m)
    (out_dir / "frame.json").write_text(json.dumps(frame.to_dict(), indent=2) + "\n", encoding="utf-8")
    log.info("frame %d x %d cells (%.0f M) at %d m in %s; margin %d m", frame.width, frame.height,
             frame.width * frame.height / 1e6, cfg.coarse_res_m, cfg.coarse_crs, cfg.max_distance_m)
    meta: dict = {"frame": frame.to_dict(), "steps": {}, "edt": {}}
    overlap = math.ceil(cfg.max_distance_m / cfg.coarse_res_m)
    workers = int(os.environ.get("POLES_WORKERS", "0")) or None
    untiled = os.environ.get("POLES_EDT_UNTILED") == "1"

    for scenario in ("A", "B"):
        mask_tif = out_dir / f"roads_{scenario}.tif"
        with _step(log, meta, f"rasterize_{scenario}") as info:
            create_raster(frame, mask_tif)
            res = rasterize(classify_dir / f"roads_{scenario}.fgb", f"roads_{scenario}", mask_tif, log, tools_log, burn=1, all_touched=True)
        with _step(log, meta, f"edt_{scenario}") as info:
            with rasterio.open(mask_tif) as ds:
                mask = ds.read(1).astype(bool)
            meta[f"road_cells_{scenario}"] = int(mask.sum())
            stats: dict = {}
            if untiled:
                dist = untiled_edt(mask, cfg.coarse_res_m)
            else:
                dist = tiled_edt(mask, cfg.coarse_res_m, overlap, TILE, workers, max_m=float(cfg.max_distance_m), stats=stats)
            del mask
            info["worker_peak_rss_bytes"] = stats.get("worker_peak_rss_bytes")
            meta["edt"].update({"tiles": stats.get("tiles"), "overlap_cells": overlap, "doublings": stats.get("doublings"),
                                f"saturated_cells_{scenario}": stats.get("saturated_cells")})
            write_float_tif(out_dir / f"dist_{scenario}.tif", dist, frame)
            del dist

    with _step(log, meta, "land"):
        build_land_mask(ws.shared_dir() / "land.fgb", extract_dir / "water.fgb", frame, out_dir / "land.tif", 1_000_000, log, out_dir)
        with rasterio.open(out_dir / "land.tif") as ds:
            meta["land_cells"] = int(sum(int(ds.read(1, window=w).sum()) for _, w in ds.block_windows(1)))

    with _step(log, meta, "invariant_a_le_b"):
        meta["a_le_b_violations"] = _count_violations(out_dir / "dist_A.tif", out_dir / "dist_B.tif")
        if meta["a_le_b_violations"]:
            raise GridError(f"A > B at {meta['a_le_b_violations']} cells; the road masks are inconsistent")
    return meta
```

`rasterize` returns None; drop the `res =` assignment when copying. Record each `run_cmd` result's `max_rss_bytes` for the rasterize steps by having `rasterize` return the `CmdResult` and storing `info["tool_peak_rss_bytes"] = res.max_rss_bytes`; do the same in `build_land_mask` by returning the max over its three commands. Register in `stages.py`: `from . import grid; reg["grid"] = grid.run`.

- [ ] **Step 8: Run tests**

Run: `cd pipeline && .venv/bin/python -m pytest -q`
Expected: all pass. If `test_rasterize_lonlat_roads_land_in_projected_frame` fails because GDAL did not reproject the layer, change `rasterize` to first run `ogr2ogr -t_srs <frame.crs>` into `<workdir>/<layer>_proj.fgb` and burn that; the test stays as written.

- [ ] **Step 9: Commit**

```bash
git add pipeline/poles/poly.py pipeline/poles/grid.py pipeline/poles/stages.py pipeline/tests/test_poly.py pipeline/tests/test_grid.py
git commit -m "pipeline: grid stage: frame from extract polygons, road masks, tiled exact EDT with saturation, land mask"
```

---

### Task 7: Europe run through grid (orchestrator)

**Files:** none committed except numbers in `docs/EUROPE_SPEC.md` section 3.3 (Task 10). Logs and `done.json` files live under `work/europe/2026-08-19/`.

- [ ] **Step 1: Run fetch, extract, classify, grid in one command in the background**

```bash
cd pipeline && export PATH=/opt/homebrew/bin:$PATH && nohup caffeinate -i .venv/bin/poles run europe --snapshot 2026-08-19 --work ../work > ../work/europe/2026-08-19/run-stage1.log 2>&1 &
```

The run stops by itself at `stopping: stage 'poles' is not implemented yet`.

- [ ] **Step 2: While it runs, watch the log every 10 to 20 minutes**

`tail -5 work/europe/2026-08-19/run-stage1.log; du -sh work/europe/2026-08-19/*; ps -o rss,etime,command -p $(pgrep -f 'osmium|ogr2ogr|gdal_rasterize|poles run') | head`. On any failure, fix the bug, commit, rerun the same command; finished stages are skipped.

- [ ] **Step 3: After grid, verify the acceptance conditions**

```bash
cd pipeline && .venv/bin/python - <<'EOF'
import json, numpy as np, rasterio
from pathlib import Path
from poles import grid
base = Path("../work/europe/2026-08-19")
for st in ("fetch", "extract", "classify", "grid"):
    m = json.load(open(base / st / "done.json")); print(st, m["duration_s"], "s", round(m["disk_bytes"]/1e9, 2), "GB", round(m["peak_rss_self_bytes"]/1e9, 2), "GB self")
f = grid.Frame.from_dict(json.load(open(base / "grid/frame.json"))); print(f)
with rasterio.open(base / "grid/roads_A.tif") as ds:
    mask = ds.read(1, window=((8192, 12288), (12288, 16384))).astype(bool)   # a 4096 x 4096 excerpt over land
ref = grid.untiled_edt(mask, f.res)
got = grid.tiled_edt(mask, f.res, overlap_cells=200, tile=1024, workers=4)
print("excerpt tiled == untiled bit for bit:", np.array_equal(ref, got), "road cells", int(mask.sum()))
EOF
```

Expected: `dist_A.tif`, `dist_B.tif`, `land.tif` exist with the frame from `frame.json` (about 28,588 x 23,625), `a_le_b_violations` is 0 in `grid/done.json`, the excerpt comparison prints True. Pick an excerpt window that contains roads (adjust the window until `road cells` is well above zero).

- [ ] **Step 4: Collect the numbers for spec 3.3**

From each `done.json`: `duration_s`, `disk_bytes`, `peak_rss_self_bytes`, and the per-command peaks in `grid/done.json` `steps` and in the log lines `done in Ns, peak RSS X GB: osmium|ogr2ogr|gdal_rasterize`. Note the largest child per stage.

---

### Task 8: Container and CI tests

**Files:**
- Create: `pipeline/Dockerfile`, `pipeline/.dockerignore`, `.github/workflows/pipeline-tests.yml`
- Modify: `pipeline/requirements.txt` (re-pin with `pip freeze` inside the container)

- [ ] **Step 1: Dockerfile**

`pipeline/.dockerignore`:

```
.venv
__pycache__
*.pyc
.pytest_cache
```

`pipeline/Dockerfile`:

```dockerfile
# GDAL image on Ubuntu 24.04 (python3.12). Check https://github.com/OSGeo/gdal/pkgs/container/gdal for the tag.
FROM ghcr.io/osgeo/gdal:ubuntu-small-3.11.3

ARG PMTILES_VERSION=1.31.2
RUN apt-get update \
 && apt-get install -y --no-install-recommends osmium-tool python3-venv python3-pip curl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && arch="$(uname -m)" && case "$arch" in x86_64) pm=x86_64 ;; aarch64) pm=arm64 ;; *) echo "unsupported arch $arch" && exit 1 ;; esac \
 && curl -fsSL "https://github.com/protomaps/go-pmtiles/releases/download/v${PMTILES_VERSION}/go-pmtiles_${PMTILES_VERSION}_Linux_${pm}.tar.gz" \
    | tar -xz -C /usr/local/bin pmtiles \
 && pmtiles version

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.txt
COPY . /app
RUN /opt/venv/bin/pip install --no-cache-dir --no-deps -e /app
ENV PATH="/opt/venv/bin:${PATH}" POLES_WORK=/work POLES_REGIONS=/app/regions
VOLUME ["/work"]
ENTRYPOINT ["poles"]
CMD ["--help"]
```

Verify the base tag exists (`docker pull`); if `ubuntu-small-3.11.3` is gone, use the newest `ubuntu-small-3.11.x` or `3.12.x` tag and write the tag you used. Verify the go-pmtiles asset name for the version at https://github.com/protomaps/go-pmtiles/releases (the pattern above is from v1.x releases); adjust if it differs.

- [ ] **Step 2: Build and run**

```bash
export PATH=/opt/homebrew/bin:$PATH
colima status || colima start --cpu 6 --memory 10 --disk 80
docker build -t poles:dev pipeline/
docker run --rm --entrypoint pytest poles:dev -q /app/tests
docker run --rm --entrypoint pip poles:dev freeze > pipeline/requirements.txt
docker run --rm -v "$PWD/work:/work" poles:dev run europe --stage classify --snapshot 2026-08-19 --work /work --force
```

Expected: image builds; tests pass inside the container (osmium 1.16 and GDAL 3.11 behave like the brew versions); `requirements.txt` is re-pinned (review the diff: same versions, possibly extra transitive pins; no platform-specific packages); the classify run inside the container recomputes `roads_A.fgb` and `roads_B.fgb` with the same counts as the native run (compare `classify/done.json` before and after). Rebuild the image after re-pinning and rerun the container tests once more.

- [ ] **Step 3: CI workflow**

`.github/workflows/pipeline-tests.yml`:

```yaml
name: pipeline-tests

on:
  push:
    paths:
      - "pipeline/**"
      - ".github/workflows/pipeline-tests.yml"
  pull_request:
    paths:
      - "pipeline/**"
      - ".github/workflows/pipeline-tests.yml"

jobs:
  pytest:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - name: Build the pipeline image
        uses: docker/build-push-action@v6
        with:
          context: pipeline
          tags: poles:ci
          load: true
          cache-from: type=gha
          cache-to: type=gha,mode=max
      - name: Run the pipeline tests in the image
        run: docker run --rm --entrypoint pytest poles:ci -q /app/tests
```

Pin the actions to the major versions already used by `deploy-cloudflare.yml` style (check that file; dependabot keeps them current).

- [ ] **Step 4: Commit and push the branch, watch CI**

```bash
git add pipeline/Dockerfile pipeline/.dockerignore pipeline/requirements.txt .github/workflows/pipeline-tests.yml
git commit -m "pipeline: container on the GDAL image with osmium and pmtiles; pytest in CI on pipeline changes"
git push -u origin europe
GH_CONFIG_DIR=~/personal/.gh-personal gh run watch --repo donataskasp/atokiausia-lietuva --exit-status $(GH_CONFIG_DIR=~/personal/.gh-personal gh run list --repo donataskasp/atokiausia-lietuva --workflow pipeline-tests --branch europe --limit 1 --json databaseId -q '.[0].databaseId')
```

Expected: green. Pushing `europe` does not deploy anything (`deploy-cloudflare.yml` runs on `main` only; confirm by reading its `on:` block before pushing).

---

### Task 9: Throwaway tile-size measurement

**Files:** a scratch script in the scratchpad directory, deleted afterwards; numbers into `docs/EUROPE_SPEC.md` section 4.1 (Task 10).

Inputs: `out/dist_A.npy` (float32, shape (12581, 16880), 25 m, EPSG:3346, origin `xmin 273120.46179172664`, `ymax 6272815.205785843` from `out/dist_A.meta.json`); `out/land.gpkg` for the land mask; the default class table from spec 3.4.

- [ ] **Step 1: Script**

```python
# scratch: tile-size measurement from the LT 50 m grid (spec task 1.8). Not committed.
import json, sqlite3, subprocess, sys
from pathlib import Path
import numpy as np, rasterio
from rasterio.transform import from_origin
from rasterio.features import rasterize as rio_rasterize
import pyogrio, shapely

ROOT = Path("/Users/donatas.kasparavicius/Personal/pole-of-remoteness")
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)

def default_edges():
    e = list(range(0, 2500, 50)) + list(range(2500, 10000, 100)) + list(range(10000, 30000, 250)) \
        + list(range(30000, 60000, 1000)) + list(range(60000, 240000, 10000))
    e.append(240000)
    assert len(e) == 254 and all(b > a for a, b in zip(e, e[1:])), len(e)
    return np.array(e, dtype=np.float64)

meta = json.load(open(ROOT / "out/dist_A.meta.json"))
dist = np.load(ROOT / "out/dist_A.npy")                      # float32 metres at 25 m
tr25 = from_origin(meta["xmin"], meta["ymax"], 25, 25)
with rasterio.open(OUT / "dist25.tif", "w", driver="GTiff", width=dist.shape[1], height=dist.shape[0], count=1,
                   dtype="float32", crs="EPSG:3346", transform=tr25, tiled=True, compress="deflate") as ds:
    ds.write(dist, 1)
subprocess.run(["gdalwarp", "-overwrite", "-tr", "250", "-250", "-r", "average", str(OUT / "dist25.tif"), str(OUT / "dist250.tif")], check=True)
with rasterio.open(OUT / "dist250.tif") as ds:
    d250 = ds.read(1); tr250 = ds.transform; shape = d250.shape
land = pyogrio.read_dataframe(ROOT / "out/land.gpkg") if False else None   # no pandas: use raw read
meta_l, _, geoms, _ = pyogrio.raw.read(str(ROOT / "out/land.gpkg"))
land_mask = rio_rasterize([(shapely.from_wkb(g), 1) for g in geoms], out_shape=shape, transform=tr250, fill=0, dtype="uint8").astype(bool)
cls = (np.searchsorted(default_edges(), d250, side="right") - 1).clip(0, 253).astype(np.uint8)
cls[~land_mask] = 255
with rasterio.open(OUT / "cls250.tif", "w", driver="GTiff", width=shape[1], height=shape[0], count=1, dtype="uint8",
                   crs="EPSG:3346", transform=tr250, nodata=255, tiled=True, compress="deflate") as ds:
    ds.write(cls, 1)
z9 = 40075016.68557849 / (256 * 2 ** 9)
subprocess.run(["gdalwarp", "-overwrite", "-t_srs", "EPSG:3857", "-tr", str(z9), str(z9), "-r", "near", "-dstnodata", "255",
                "-tap", str(OUT / "cls250.tif"), str(OUT / "cls3857.tif")], check=True)
mb = OUT / "lt.mbtiles"; mb.unlink(missing_ok=True)
subprocess.run(["gdal_translate", "-of", "MBTILES", "-co", "TILE_FORMAT=PNG", "-co", "ZOOM_LEVEL_STRATEGY=UPPER",
                str(OUT / "cls3857.tif"), str(mb)], check=True)
subprocess.run(["gdaladdo", "-r", "nearest", str(mb), "2", "4", "8", "16", "32", "64", "128", "256", "512"], check=True)
pm = OUT / "lt.pmtiles"; pm.unlink(missing_ok=True)
subprocess.run(["pmtiles", "convert", str(mb), str(pm)], check=True)
con = sqlite3.connect(mb)
rows = con.execute("select zoom_level, count(*), sum(length(tile_data)), max(length(tile_data)) from tiles group by zoom_level order by zoom_level").fetchall()
for z, n, total, mx in rows:
    print(f"z{z}: {n} tiles, {total/1e6:.2f} MB, {total/n/1e3:.1f} KB avg, {mx/1e3:.1f} KB max")
one = con.execute("select tile_data from tiles where zoom_level = (select max(zoom_level) from tiles) limit 1").fetchone()[0]
print("png header bytes 24..29 (colour type at offset 25):", list(one[24:30]))
land_km2 = land_mask.sum() * 0.0625
print(f"land km2 {land_km2:.0f}; pmtiles {pm.stat().st_size/1e6:.2f} MB; bytes per land km2 {pm.stat().st_size/land_km2:.1f}")
z9n = [r for r in rows if r[0] == 9][0]
print(f"z9 bytes per tile {z9n[2]/z9n[1]/1e3:.1f} KB over {z9n[1]} tiles")
```

Run: `export PATH=/opt/homebrew/bin:$PATH; cd pipeline && .venv/bin/python <scratch>/measure_tiles.py <scratch>/tiles`

- [ ] **Step 2: Interpret**

Record: z9 tile count and average bytes; max zoom reached (if `gdal_translate` picked z8 or z10 as the native zoom, say so and scale); PNG colour type (0 = grey, 3 = palette, 2/6 = RGB/RGBA; if RGB or RGBA, note that stage 3 must write single-band tiles itself and scale the bytes by 1/3 or 1/4 as an estimate); archive bytes per land km². Project: Europe land km² from `work/europe/2026-08-19/grid/done.json` `land_cells` x 0.0625 (if the grid has finished; else use 10.2 M km² as the extract's land estimate and say so); North America about 24.5 M km². Tile bytes scale with land area at z9 and the lower zooms add about a third.

- [ ] **Step 3: Delete the scratch files**

`rm -rf <scratch>/measure_tiles.py <scratch>/tiles`.

---

### Task 10: Close-out (orchestrator)

- [ ] **Step 1: Spec numbers**

`docs/EUROPE_SPEC.md` 3.3: add a table "Measured on 2026-08-20/21, Europe snapshot 2026-08-19, M4 Pro 12 cores 24 GB" with rows fetch, extract, classify, grid: wall clock, peak RSS (largest process), disk after the stage, plus the frame size and the EDT tile stats. 4.1: replace "Estimated 0.5 GB for Europe and 1 GB for North America" with the measured bytes per z9 land tile, bytes per land km², and the projected Europe and North America archive sizes per scenario, with the measurement's caveats.

- [ ] **Step 2: DECISIONS**

Append to the "2026-08-20: Stage 1 implementation decisions" entry anything decided during execution (extract via files not pipes, filter-per-source-then-merge, anything the real data forced). Dated; no deletions.

- [ ] **Step 3: OVERVIEW**

`docs/OVERVIEW.md`: status paragraph says Stage 1 is done with the measured numbers; NEXT-UP becomes Stage 2 (#8), poles and validation, starting with task 2.1 units; "What works" gains the pipeline through grid; known risks found during the run listed (for example admin relations that did not assemble).

- [ ] **Step 4: Issue #7**

Tick every checklist box in the issue body with one line of evidence each (command, file, number), comment with the summary and the spec sections updated, remove `in-progress`, close. File separate issues for risks found (missing country polygons, anything deferred).

- [ ] **Step 5: Commit docs, push the branch**

```bash
git add docs/EUROPE_SPEC.md docs/DECISIONS.md docs/OVERVIEW.md
git commit -m "Stage 1 done: record Europe grid run numbers and tile-size measurement; NEXT-UP is stage 2"
git push origin europe
```

Stop for the owner's review. Do not start Stage 2.

---

## Self-review notes

- Spec coverage: 2.1 (Task 1 config), 2.3 tag sets (Task 4), 3.1 shape and CLI (Tasks 1-2, 8), 3.2 stages 1-4 (Tasks 3-6), 3.3 numbers (Tasks 7, 10), 3.5 tests named for stage 1 (tag classification: Task 4; tiled equals untiled incl. forced doubling: Task 6; the class table, refinement, branch-and-bound, unit, schema tests belong to later stages), 4.1 measurement (Task 9), 10.1 acceptance (Tasks 7-10).
- Deviations recorded in DECISIONS: bounded doubling with saturation; Europe max_distance_m 250 km; frame = primary sources bbox plus margin; file-based GeoJSONSeq conversion; filter per source then merge; colima.
- Type consistency: `RegionConfig` fields match the plan's Shared interfaces; stage functions return `dict | None` and the runner writes `done.json` (refinement of `mark_done` usage, noted in Global Constraints); `tiled_edt` keeps the shared signature plus `max_m` and `stats`.
