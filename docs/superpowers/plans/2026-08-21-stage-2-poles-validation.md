# Stage 2: Poles and Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `poles` and `validate` stages to the pipeline: unit polygons from OSM admin boundaries, branch-and-bound over the coarse grid to exact UTM refinement, nearest-way and nearest-settlement attribution, the eight validation checks with a report and a satellite contact sheet, and run both on the computed Europe snapshot so Lithuania's published poles are reproduced.

**Architecture:** The poles stage first builds its own inputs from stage-1 outputs (countries and units assembled from `boundaries.pbf` with a custom ring assembler, the 101 M highways re-tiled into indexed FlatGeobufs, indexed land and large-water copies), then runs one search per unit and scenario in a process pool: cells of the unit sorted by coarse distance, each refined exactly in its UTM zone until no unrefined cell can beat the accepted poles. The validate stage re-derives every published number by an independent geodesic path and writes `report.json`, `report.html`, and `contact-sheet.html`; any blocking failure makes the CLI exit non-zero.

**Tech Stack:** Python 3.12, numpy, scipy, shapely 2, pyproj, rasterio, pyogrio (bundled GDAL 3.12.4 for reads; the CLI tools are GDAL 3.13.3), PyYAML, pytest; osmium-tool 1.19 and ogr2ogr / gdal_rasterize as subprocesses through `poles.shell.run_cmd`.

**Spec:** `docs/EUROPE_SPEC.md` sections 2.1, 2.2, 2.4, 3.2 (stages 5 and 6), 6; `docs/EUROPE_PLAN.md` Stage 2 (tasks 2.1 to 2.6), "Global constraints" and "Shared interfaces". Deviations are recorded in `docs/DECISIONS.md` under "2026-08-21: Stage 2 implementation decisions" (Task 9 writes the entry; the decisions themselves are listed in "Decisions fixed by this plan" below and are binding for every task).

## Global Constraints

- No em dashes anywhere: code, comments, docs, commit messages, issue text.
- No secrets in the repo. Nothing in code names Europe; `pipeline/regions/<region>.yaml` is the only place a region is described.
- Tests: real pytest for pipeline math, synthetic fixtures only, no network (the contact sheet's tile fetch is injected and stubbed in tests).
- Tag sets exactly as spec 2.3 (`poles.classify.SET_A`, `SET_B`); accuracy tiers as spec 2.4: published poles are exact vector distances at a 5 m search step in the local UTM zone.
- Identifiers: `<region>` lowercase slug; `<snapshot>` `YYYY-MM-DD`; unit codes lowercase ISO 3166-1 alpha-2 (`lt`) or ISO 3166-2 (`us-ak`).
- Stage functions: `run(cfg: RegionConfig, ws: Workspace, log: logging.Logger) -> dict | None`; idempotent; the runner writes `done.json`. Long sub-steps inside a stage are guarded by `<artefact>.ok` markers exactly like `poles.extract._ensure` so a crash resumes at the first missing piece.
- Every extract layer is opened through its `<layer>.vrt` handle (`highways.vrt`, `places.vrt`, `water.vrt`, `work/shared/land.vrt`); `boundaries.pbf` is read with osmium because the FlatGeobuf export lacks relation membership and the incomplete relations (issue #15).
- Branch `europe` only. Commit after every green task with explicit paths, identity Donatas / donatas.kasparavicius@gmail.com (repo-local override; verify with `git config user.email` before the first commit). Never `git add -A`.
- Python: `pipeline/.venv`. Run tests as `cd pipeline && .venv/bin/python -m pytest -q`. CLI tools from `/opt/homebrew/bin`; `export PATH=/opt/homebrew/bin:$PATH` in every shell.
- Work data: `work/europe/2026-08-19/` holds fetch, extract, classify, grid with `done.json`; **do not recompute them**. New outputs go to `work/europe/2026-08-19/poles/` and `validate/`. Disk: about 96 GB free at planning time; the highways tiles add about 25 GB.
- Memory: 24 GB machine. The poles stage pool uses `POLES_WORKERS` (default 4). Stop colima before the grid-shift check (check 4 reruns the tiled EDT).
- Long runs: background under `caffeinate -i`, logs under the work directory, never block the session on them.

## Measured facts the plan relies on

- `work/europe/2026-08-19/extract/boundaries.pbf` (226 MB) holds 166 admin_level 2 relations of which 73 carry `ISO3166-1`; among them EEZs (`boundary=maritime`), "land mass" relations without ISO, and partial neighbours (AF, JO, KW, MA, PK, SA, TM, ...) whose rings are incomplete. Selecting `boundary=administrative` plus an ISO code and assembling only closed rings from the present members yields: ES 7 outer rings (626 of 637 members present, Canary ways absent), FR 2 outer plus 1 inner (1385 of 1730), NL 9 outer plus 22 inner (Baarle), NO 7 (222 of 223, Bouvet absent), IR 1, LT 1; RU has 3 closed rings plus one open line of about 13,000 km cut at the extract edge, and its `admin_centre` node (Moscow) is present while its `label` node is not. osmium's own assembler rejects any relation with a missing member, which is why stage 1 lost ES, FR, NL, NO, RU, IR.
- `osmium getid` exits 1 when a requested or referenced id is missing but still writes everything it found; treat exit codes 0 and 1 as success for that command.
- `osmium export` needs `-n` (`--keep-untagged`) to emit untagged boundary ways, and an export config with `"attributes": {"type": "@type", "id": "@id"}` to carry ids.
- FlatGeobuf spatial index limit in GDAL 3.13.3 (issue #16, measured 2026-08-21 with `places.fgb` repeated through a VRT union): 1.78 M features indexed read and query correctly; at 85 M and 105 M features the file builds without error but returns no features at all (`-limit 1`, `-fid`, `-spat` all empty). Bisection: 5.3 M, 10.7 M, 21.3 M and 42.6 M features (7.25 GB file) read their first feature and answer the spatial query with exactly the expected count; 63.9 M fails both (and its file, 8.14 GB, is smaller per feature than the 42.6 M one, so the writer is probably the broken side). The safe ceiling recorded in DECISIONS is 40 M features per indexed FlatGeobuf; `TILE_DEG = 5.0` keeps Europe's densest tile (estimated 10 M ways) 4x below it.
- One `ogr2ogr -spat` pass over `highways.vrt` (101,461,002 features, 141 unindexed chunks) takes 39 s and 0.57 GB RSS and produced an indexed 4.9 M-feature tile for lon 20 to 30, lat 50 to 60. About 100 non-empty 5-degree tiles at six parallel passes is about 11 minutes.
- Coarse grid: frame 28,588 x 23,625 cells, EPSG:3035, 250 m, `x0 = 434000`, `y1 = 6821250` (`grid/frame.json`); `dist_A.tif`, `dist_B.tif` float32 saturated at 250,000; `land.tif` uint8; `roads_A.tif`, `roads_B.tif` uint8 road masks. Half-diagonal of a cell is 176.78 m.
- Lithuania's published poles (`site/data/spots.json`, snapshot 2026-08-17): A 3425.6 m at lat 54.441473, lon 23.537020 (nearest way 1385319417, track); B 6674.6 m at lat 53.995818, lon 24.462993 (way 70542812, unclassified "Baublių g.").
- `places.vrt`: 1,775,822 points with `osm_id, name, name:en, place, population`. `highways.vrt` fields: `osm_type, osm_id, highway, name, ref, ice_road, winter_road` (GeoJSONSeq-derived: `osm_id` is a 64-bit integer).

## Decisions fixed by this plan (Task 9 copies them into DECISIONS)

1. **Country and unit polygons are assembled by `poles.boundaries` from the present members of each relation** (closed outer rings become polygons, inner rings become holes of the outer ring that contains them; an open outer line is closed along the data-edge polygon and only the faces containing the relation's `admin_centre` or `label` node are kept). Stays OSM-only, needs no per-country downloads, and documents the cut: `closed_by_edge` is recorded per area. Closes #15.
2. **Roads are served to stage 2 and later stages from `poles/roads/`: the full `highways.vrt` split into indexed FlatGeobuf tiles of `TILE_DEG` degrees in lon/lat, built by parallel `ogr2ogr -spat` passes, queried by bbox with way-id deduplication and an optional `where`.** One structure serves refinement (filtered by the scenario's tag set), attribution, check 1 (all highway tags, re-filtered inline), and stage 3's detail rasters. The measured index limit is recorded. Closes #16.
3. **A supplement country is never a unit, decided by geometry, not by a list:** a country is unit-eligible only if at least half of its area lies inside the union of the primary source polygons (`unit_countries` and `unit_exclude` still apply on top). Armenia, Azerbaijan, Iran, Iraq, Syria lie outside `europe.poly` and drop out; Turkey and Georgia lie inside.
4. **The branch-and-bound bound is `(coarse_m + 2 * half_diag) * (1 + pad)`**, not the spec's `coarse_m + 2 * half_diag * (1 + pad)`: the projection scale error applies to the whole coarse distance, and the spec's form would under-bound a 30 km pole by about 600 m at Europe's edge. `pad` is the projection's Tissot distortion at the cell (max of semimajor minus one and one minus semiminor, from pyproj `get_factors`) plus 0.002 for the UTM scale factor and the ellipsoid. The plan's "2 km dedup among candidates" is replaced by an exact dominance rule: once a pole is final (no unrefined cell can beat it) and accepted, every cell whose farthest point is surely within the 10 km dedup distance of it is skipped. No silent cap: a warning at 500 refinements per unit and scenario, a hard failure at 20,000.
5. **Unit area is the land-cell count of `units.tif` times the cell area, and `units.tif` is the cell-centre rasterisation of the unit polygons ANDed with `grid/land.tif`**, so the unit raster, the explore layer, and the published area use one land definition (osmdata land minus water of 1 km² or more). The unit polygon in `units.fgb` is the admin polygon minus the territory mask, not land-clipped; check 2 tests land and water separately. A unit with no cell centre on land falls back to all-touched cells of its own polygon.
6. **Refinement grid points are restricted to the unit polygon, the land polygons, and outside water polygons of 1 km² or more**, so a pole can never be published in the sea, in a lake, or across the border (the plan's `refine` gains an `allowed` predicate).
7. **Check 5's thresholds are module constants** (`INNER_KM = 10`, `OUTER_KM = 30`, outer density above the unit's median over 200 random land cells, inner zero), not region config keys; promote them to config when a region needs different values.
8. **Check 7's class-table and R2 HEAD parts run in stage 3**, where the class table and the upload exist; stage 2's check 7 covers A <= B (grid-level count from `grid/done.json` plus the exact winners per unit), `top_n` poles or a recorded reason, 10 km separation, the unit count, and the `poles/*.json` structure.
9. **Fewer than `top_n` poles is a recorded reason, not a failure, when the unit is exhausted**: the 10 km discs of its accepted poles cover every land cell (microstates, Malta).

## File structure

```
pipeline/
  poles/errors.py              PolesError (base for stage failures the CLI reports without a traceback)
  poles/roads.py               Tile, tile_grid, build_tiles, RoadTiles, RoadSet (Task 1)
  poles/opl.py                 OPL decoding helpers (Task 2)
  poles/boundaries.py          Relation, AdminArea, read_relations, way_geometries, seed_points, assemble, load_admin_areas (Task 2)
  poles/units.py               Unit, select_units, apply_territory_mask, inside_fraction, country_of, write_units, rasterize_units, unit_cells (Task 3)
  poles/candidates.py          pad_fn_for, Search, SearchResult, HALF_DIAG helpers (Task 4)
  poles/refine.py              utm_epsg, RefinedPole, refine, RoadCache (Task 5)
  poles/attrib.py              Places, Countries, nearest_way (Task 6)
  poles/poles.py               stage poles: prepare inputs, search_unit, run (Task 6)
  poles/validate/__init__.py   stage validate: run, ValidationFailed (Task 8)
  poles/validate/checks.py     CheckResult, checks 1 to 7 (Task 7)
  poles/validate/refs.yaml     reference poles (Task 7)
  poles/validate/report.py     report.json, report.html, contact-sheet.html (Task 8)
  poles/stages.py              register poles and validate
  poles/cli.py                 catch PolesError -> exit 1
  regions/europe.yaml          expected_units set after the count (Task 6)
  tests/fixtures/admin.osm     hand-written admin boundaries (Task 2)
  tests/test_roads.py, test_opl.py, test_boundaries.py, test_units.py, test_candidates.py,
  tests/test_refine.py, test_attrib.py, test_poles_stage.py, test_checks.py, test_report.py
docs/DECISIONS.md, docs/EUROPE_SPEC.md (3.3), docs/OVERVIEW.md   (Task 9)
```

---

### Task 1: Road tiles (issue #16)

**Files:**
- Create: `pipeline/poles/errors.py`, `pipeline/poles/roads.py`, `pipeline/tests/test_roads.py`
- Modify: `pipeline/poles/cli.py` (catch `PolesError`)

**Interfaces:**
- Consumes: `poles.shell.run_cmd`, `require_tools`; `tests.helpers.write_fgb`.
- Produces: `class PolesError(RuntimeError)`; `@dataclass(frozen=True) Tile(name: str, west: float, south: float, east: float, north: float)`; `tile_grid(bounds: tuple[float, float, float, float], tile_deg: float) -> list[Tile]` (names `t_<west>_<south>` with signs, e.g. `t_-10_35`, `t_20_50`); `build_tiles(src: Path, layer: str, out_dir: Path, log, *, tile_deg: float = TILE_DEG, workers: int | None = None) -> dict` (writes `<out_dir>/<tile.name>.fgb` indexed for every non-empty tile, each guarded by `.ok`, then `<out_dir>/tiles.json` = `{"tile_deg", "layer", "source_features", "tiles": [{"name", "west", "south", "east", "north", "features"}]}`; returns that dict); `@dataclass RoadSet(geoms: np.ndarray, attrs: dict[str, np.ndarray])` with `__len__`; `class RoadTiles(out_dir)` with `.tiles: list[Tile]`, `.query(west, south, east, north, where: str | None = None, columns=("osm_id", "highway", "name", "ref")) -> RoadSet` (geometries as shapely objects in lon/lat, deduplicated by `osm_id`, empty arrays when nothing matches).
- `TILE_DEG` is a module constant; Task 1 sets it from the bisection result (5.0 if 24 copies = 43 M features read correctly, else 2.5).

- [ ] **Step 1: Error base class and CLI catch**

`pipeline/poles/errors.py`:

```python
"""Failures a stage raises on purpose. The CLI prints them without a traceback and exits 1."""
from __future__ import annotations


class PolesError(RuntimeError):
    """A stage found a condition that must stop the run (bad data, failed validation, broken invariant)."""
```

In `pipeline/poles/cli.py`, import `from .errors import PolesError` and wrap the pipeline call in `main`:

```python
    try:
        run_pipeline(cfg, ws, log, only=args.stage, force=args.force, registry=registry())
    except PolesError as e:
        log.error("%s", e)
        return 1
    return 0
```

- [ ] **Step 2: Write the failing tests**

`pipeline/tests/test_roads.py`:

```python
import json
from pathlib import Path

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString

from poles.roads import RoadTiles, Tile, build_tiles, tile_grid
from tests.helpers import write_fgb


def _roads(tmp_path: Path) -> Path:
    # 400 short ways spread over lon 0..20, lat 40..60; one way crosses the tile seam at lon 10.
    rng = np.random.default_rng(1)
    xs = rng.uniform(0.5, 19.5, 400)
    ys = rng.uniform(40.5, 59.5, 400)
    geoms = [LineString([(x, y), (x + 0.01, y + 0.01)]) for x, y in zip(xs, ys)]
    geoms.append(LineString([(9.99, 45.0), (10.01, 45.0)]))
    ids = list(range(1, len(geoms) + 1))
    hw = ["track" if i % 3 == 0 else "residential" for i in ids]
    return write_fgb(tmp_path / "highways.fgb", "highways", geoms,
                     {"osm_id": ids, "highway": hw, "name": [None] * len(ids), "ref": [None] * len(ids)})


def test_tile_grid_snaps_outward_and_names_by_corner():
    tiles = tile_grid((-3.2, 41.1, 7.9, 52.0), 5.0)
    names = {t.name for t in tiles}
    assert names == {"t_-5_40", "t_0_40", "t_5_40", "t_-5_45", "t_0_45", "t_5_45", "t_-5_50", "t_0_50", "t_5_50"}
    t = next(t for t in tiles if t.name == "t_-5_40")
    assert (t.west, t.south, t.east, t.north) == (-5.0, 40.0, 0.0, 45.0)


def test_build_tiles_covers_every_feature_and_skips_empty(tmp_path, log):
    src = _roads(tmp_path)
    out = tmp_path / "roads"
    meta = build_tiles(src, "highways", out, log, tile_deg=10.0, workers=2)
    assert meta["source_features"] == 401
    assert {t["name"] for t in meta["tiles"]} == {"t_0_40", "t_10_40", "t_0_50", "t_10_50"}
    assert sum(t["features"] for t in meta["tiles"]) == 402  # the seam way sits in two tiles
    assert json.loads((out / "tiles.json").read_text())["tile_deg"] == 10.0
    assert all((out / f"{t['name']}.fgb").exists() and (out / f"{t['name']}.fgb.ok").exists() for t in meta["tiles"])


def test_query_dedups_seam_way_and_applies_where(tmp_path, log):
    src = _roads(tmp_path)
    out = tmp_path / "roads"
    build_tiles(src, "highways", out, log, tile_deg=10.0, workers=2)
    tiles = RoadTiles(out)
    rs = tiles.query(9.9, 44.9, 10.1, 45.1)
    assert list(rs.attrs["osm_id"]) == [401]
    assert len(rs) == 1 and shapely.get_type_id(rs.geoms[0]) == 1
    everything = tiles.query(0, 40, 20, 60)
    assert len(everything) == 401
    tracks = tiles.query(0, 40, 20, 60, where="highway IN ('track')")
    assert len(tracks) == len([i for i in range(1, 402) if i % 3 == 0])
    assert len(tiles.query(30, 40, 31, 41)) == 0


def test_build_tiles_resumes_from_markers(tmp_path, log):
    src = _roads(tmp_path)
    out = tmp_path / "roads"
    build_tiles(src, "highways", out, log, tile_deg=10.0, workers=1)
    marker = out / "t_0_40.fgb.ok"
    before = (out / "t_0_40.fgb").stat().st_mtime_ns
    build_tiles(src, "highways", out, log, tile_deg=10.0, workers=1)
    assert marker.exists() and (out / "t_0_40.fgb").stat().st_mtime_ns == before
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_roads.py -q`
Expected: ImportError on `poles.roads`.

- [ ] **Step 4: Implement `poles/roads.py`**

```python
"""Spatial access to the road layers (issue #16).

GDAL 3.13 cannot read back a FlatGeobuf whose packed R-tree is large (measured 2026-08-21: 1.78 M
indexed features read and query correctly, 85 M and 105 M return no features at all), so the 101 M
highways stay as unindexed chunks behind `highways.vrt` in stage 1 and this module re-tiles them into
indexed FlatGeobufs of TILE_DEG degrees, each a few million features, built by one `ogr2ogr -spat`
pass per tile (39 s per pass on Europe, six in parallel). A query opens the tiles that intersect the
bbox, reads each through its index, and deduplicates by osm_id because a way crossing a seam is
stored in every tile it touches.
"""
from __future__ import annotations

import json
import logging
import math
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import shapely
from pyogrio import read_info
from pyogrio.raw import read

from .shell import require_tools, run_cmd

TILE_DEG = 5.0  # set from the measured index limit (Task 1, step 7)
MARKER = ".ok"


@dataclass(frozen=True)
class Tile:
    name: str
    west: float
    south: float
    east: float
    north: float

    def intersects(self, west: float, south: float, east: float, north: float) -> bool:
        return not (east < self.west or west > self.east or north < self.south or south > self.north)


@dataclass
class RoadSet:
    geoms: np.ndarray
    attrs: dict[str, np.ndarray]

    def __len__(self) -> int:
        return len(self.geoms)

    @classmethod
    def empty(cls, columns) -> "RoadSet":
        return cls(np.array([], dtype=object), {c: np.array([], dtype=object) for c in columns})


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def tile_grid(bounds: tuple[float, float, float, float], tile_deg: float) -> list[Tile]:
    """Tiles of tile_deg anchored at multiples of tile_deg, covering bounds (west, south, east, north)."""
    w0 = math.floor(bounds[0] / tile_deg) * tile_deg
    s0 = math.floor(bounds[1] / tile_deg) * tile_deg
    tiles = []
    south = s0
    while south < bounds[3]:
        west = w0
        while west < bounds[2]:
            tiles.append(Tile(f"t_{_fmt(west)}_{_fmt(south)}", west, south, west + tile_deg, south + tile_deg))
            west += tile_deg
        south += tile_deg
    return tiles


def _count(path: Path) -> int:
    return int(read_info(str(path), force_feature_count=True)["features"])


def build_tiles(src: Path, layer: str, out_dir: Path, log: logging.Logger, *, tile_deg: float = TILE_DEG,
                workers: int | None = None) -> dict:
    """One `ogr2ogr -spat` pass per tile over the unindexed source; every non-empty tile becomes an indexed
    FlatGeobuf guarded by a `.ok` marker, so a rerun skips finished tiles. Writes tiles.json last."""
    require_tools(["ogr2ogr"])
    out_dir.mkdir(parents=True, exist_ok=True)
    info = read_info(str(src), layer=layer, force_feature_count=True)
    bounds = tuple(float(v) for v in info["total_bounds"])
    grid = tile_grid(bounds, tile_deg)
    workers = workers or min(6, max(1, (os.cpu_count() or 3) - 2))
    log.info("roads: %d tiles of %s deg over %s with %d workers", len(grid), tile_deg, bounds, workers)
    tools_log = out_dir / "tools.log"

    def one(tile: Tile) -> tuple[Tile, int]:
        fgb = out_dir / f"{tile.name}.fgb"
        marker = fgb.with_name(fgb.name + MARKER)
        empty = fgb.with_name(fgb.name + ".empty")
        if empty.exists():
            return tile, 0
        if fgb.exists() and marker.exists():
            return tile, _count(fgb)
        marker.unlink(missing_ok=True)
        fgb.unlink(missing_ok=True)
        run_cmd(["ogr2ogr", "-f", "FlatGeobuf", fgb, src, "-nln", layer, "-spat", tile.west, tile.south, tile.east,
                 tile.north, "-lco", "SPATIAL_INDEX=YES", "-lco", f"TEMPORARY_DIR={out_dir}"],
                log, stderr_path=tools_log)
        n = _count(fgb) if fgb.exists() else 0
        if n == 0:
            fgb.unlink(missing_ok=True)
            empty.touch()
            return tile, 0
        marker.touch()
        return tile, n

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, grid))
    tiles = [{"name": t.name, "west": t.west, "south": t.south, "east": t.east, "north": t.north, "features": n}
             for t, n in results if n > 0]
    meta = {"tile_deg": tile_deg, "layer": layer, "source_features": int(info["features"]), "tiles": tiles}
    total = sum(t["features"] for t in tiles)
    if total < meta["source_features"]:
        raise RuntimeError(f"roads: tiles hold {total} features but the source has {meta['source_features']}")
    (out_dir / "tiles.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    log.info("roads: %d non-empty tiles, %d features (%d in the source)", len(tiles), total, meta["source_features"])
    return meta


class RoadTiles:
    def __init__(self, out_dir: Path):
        self.dir = Path(out_dir)
        meta = json.loads((self.dir / "tiles.json").read_text(encoding="utf-8"))
        self.layer = meta["layer"]
        self.tiles = [Tile(t["name"], t["west"], t["south"], t["east"], t["north"]) for t in meta["tiles"]]

    def query(self, west: float, south: float, east: float, north: float, where: str | None = None,
              columns=("osm_id", "highway", "name", "ref")) -> RoadSet:
        columns = tuple(columns)
        geoms: list[np.ndarray] = []
        attrs: dict[str, list[np.ndarray]] = {c: [] for c in columns}
        for tile in self.tiles:
            if not tile.intersects(west, south, east, north):
                continue
            meta, _, wkb, fields = read(str(self.dir / f"{tile.name}.fgb"), layer=self.layer, columns=list(columns),
                                        bbox=(west, south, east, north), where=where)
            if len(wkb) == 0:
                continue
            by_name = dict(zip(meta["fields"], fields))
            geoms.append(shapely.from_wkb(wkb))
            for c in columns:
                attrs[c].append(np.asarray(by_name[c], dtype=object))
        if not geoms:
            return RoadSet.empty(columns)
        all_geoms = np.concatenate(geoms)
        all_attrs = {c: np.concatenate(attrs[c]) for c in columns}
        _, first = np.unique(all_attrs["osm_id"].astype(np.int64), return_index=True)
        first.sort()
        return RoadSet(all_geoms[first], {c: all_attrs[c][first] for c in columns})
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_roads.py -q`
Expected: 4 passed. If `read_info` returns `total_bounds` as None for a VRT, compute the bounds with `ogrinfo -so` parsing instead (stage 1 saw `ogrinfo -so` report the union extent from the chunk headers); the tests use a single FlatGeobuf and must stay green either way.

- [ ] **Step 6: Run the whole suite and commit**

Run: `cd pipeline && .venv/bin/python -m pytest -q`
Expected: 101 passed.

```bash
git add pipeline/poles/errors.py pipeline/poles/roads.py pipeline/poles/cli.py pipeline/tests/test_roads.py
git commit -m "poles: road tiles, indexed FlatGeobufs of TILE_DEG degrees built by parallel ogr2ogr -spat passes; PolesError exits the CLI with 1 (issue #16)"
```

- [ ] **Step 7: Set TILE_DEG from the measured limit**

Read the bisection log at `<scratchpad>/fgb-limit/bisect.log` (the orchestrator passes the path). Rule: the densest Europe tile at 5 degrees is about 10 M ways; keep `TILE_DEG = 5.0` if files of 43 M features (24 copies) read and query correctly, otherwise `TILE_DEG = 2.5`. Write the measured boundary into the module docstring ("N M features read correctly, M M did not") and commit: `git commit -m "roads: TILE_DEG from the measured FlatGeobuf index limit"`.

- [ ] **Step 8: Build the Europe tiles in the background**

```bash
cd <repo>/pipeline && export PATH=/opt/homebrew/bin:$PATH
nohup caffeinate -i .venv/bin/python -c "
import logging, sys
from pathlib import Path
from poles.roads import build_tiles
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', stream=sys.stdout)
w = Path('../work/europe/2026-08-19')
build_tiles(w / 'extract' / 'highways.vrt', 'highways', w / 'poles' / 'roads', logging.getLogger('tiles'))
" > ../work/europe/2026-08-19/roads-tiles.log 2>&1 &
```

Record in the task report: wall clock, tile count, largest tile's feature count, disk used. Verify with `ogrinfo -al -q -spat 25.0 54.5 25.5 55.0 ../work/europe/2026-08-19/poles/roads/t_25_50.fgb | grep -c OGRFeature` that the densest-looking tile answers a spatial query (non-zero).

---

### Task 2: Admin boundary assembly from the present members (issue #15)

**Files:**
- Create: `pipeline/poles/opl.py`, `pipeline/poles/boundaries.py`, `pipeline/tests/fixtures/admin.osm`, `pipeline/tests/test_opl.py`, `pipeline/tests/test_boundaries.py`
- Modify: `pipeline/tests/conftest.py` (add the `admin_pbf` fixture)

**Interfaces:**
- Consumes: `poles.osmium.osmium(args, log, stderr_path)` (exists: runs the osmium CLI through `run_cmd`), `poles.shell.run_cmd`.
- Produces: `opl.decode(s: str) -> str`; `opl.parse_tags(field: str) -> dict[str, str]`; `opl.parse_members(field: str) -> list[tuple[str, int, str]]` (type letter, id, role); `@dataclass Relation(id: int, tags: dict[str, str], members: list[tuple[str, int, str]])`; `read_relations(pbf: Path, levels: set[int], work: Path, log) -> list[Relation]` (only `boundary=administrative` and `type=boundary` or `multipolygon` at those levels); `way_geometries(pbf: Path, way_ids: set[int], work: Path, log) -> dict[int, LineString]`; `seed_points(pbf: Path, node_ids: set[int], work: Path, log) -> dict[int, Point]`; `@dataclass AdminArea(osm_id: int, level: int, code: str | None, name: str | None, name_en: str | None, geometry: MultiPolygon, complete: bool, closed_by_edge: bool)`; `assemble(rel: Relation, ways: dict[int, LineString], seeds: dict[int, Point], edge: BaseGeometry | None) -> MultiPolygon | None` plus flags via `assemble_area(rel, ways, seeds, edge, code_tag) -> AdminArea | None`; `load_admin_areas(pbf: Path, levels: set[int], edge: BaseGeometry | None, work: Path, log, code_tags: dict[int, str]) -> list[AdminArea]`.
- `code_tags` maps a level to the tag holding its code (`{2: "ISO3166-1", 4: "ISO3166-2"}`); codes are returned upper-case as tagged, the units task lower-cases them.

- [ ] **Step 1: OPL helpers and their tests**

`pipeline/tests/test_opl.py`:

```python
from poles.opl import decode, parse_members, parse_tags


def test_decode_percent_escapes():
    assert decode("Bosnia%20%and%20%Herzegovina") == "Bosnia and Herzegovina"
    assert decode("a%2c%b%3d%c%25%") == "a,b=c%"
    assert decode("plain-text_ok") == "plain-text_ok"


def test_parse_tags_and_members():
    assert parse_tags("admin_level=2,boundary=administrative,ISO3166-1=LT,name=Lietuva") == {
        "admin_level": "2", "boundary": "administrative", "ISO3166-1": "LT", "name": "Lietuva"}
    assert parse_tags("") == {}
    assert parse_members("w1@outer,w22@inner,n3@admin_centre,r4@") == [
        ("w", 1, "outer"), ("w", 22, "inner"), ("n", 3, "admin_centre"), ("r", 4, "")]
    assert parse_members("") == []
```

`pipeline/poles/opl.py`:

```python
"""osmium's OPL text format, enough to read relations: tags in the T field, members in the M field.
Special characters are written as %<hex codepoint>% (space is %20%, comma %2c%, equals %3d%)."""
from __future__ import annotations

import re

_ESC = re.compile(r"%([0-9a-fA-F]+)%")


def decode(s: str) -> str:
    return _ESC.sub(lambda m: chr(int(m.group(1), 16)), s)


def parse_tags(field: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    if not field:
        return tags
    for item in field.split(","):
        key, _, value = item.partition("=")
        tags[decode(key)] = decode(value)
    return tags


def parse_members(field: str) -> list[tuple[str, int, str]]:
    members = []
    if not field:
        return members
    for item in field.split(","):
        ref, _, role = item.partition("@")
        members.append((ref[0], int(ref[1:]), decode(role)))
    return members
```

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_opl.py -q` -> 2 passed.

- [ ] **Step 2: The admin fixture**

`pipeline/tests/fixtures/admin.osm`. Coordinates are lon/lat degrees; the test edge polygon is the box 0..10 x 0..10. Country AA is a square 1..4 made of two ways with an enclave CC (square 2..3, closed way 103 shared as AA's inner and CC's outer). State AA-X (level 4) is a closed way inside AA. Country BB is cut by the edge: way 104 runs from (12,6) west to (6,6), north to (6,9), east to (12,9); way 105 (which would close it at lon 12) is referenced by relation 202 but absent from the file; node 50 (8, 7.5) is BB's admin_centre. Relation 204 is an EEZ (`boundary=maritime`) and relation 205 a "land mass" without ISO; both must be ignored by the unit selection (205 still assembles as an area with code None).

```xml
<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="hand">
  <node id="1" lat="1" lon="1"/>
  <node id="2" lat="1" lon="4"/>
  <node id="3" lat="4" lon="4"/>
  <node id="4" lat="4" lon="1"/>
  <node id="11" lat="2" lon="2"/>
  <node id="12" lat="2" lon="3"/>
  <node id="13" lat="3" lon="3"/>
  <node id="14" lat="3" lon="2"/>
  <node id="21" lat="1.2" lon="1.2"/>
  <node id="22" lat="1.2" lon="3.8"/>
  <node id="23" lat="1.8" lon="3.8"/>
  <node id="24" lat="1.8" lon="1.2"/>
  <node id="31" lat="6" lon="12"/>
  <node id="32" lat="6" lon="6"/>
  <node id="33" lat="9" lon="6"/>
  <node id="34" lat="9" lon="12"/>
  <node id="41" lat="5" lon="5"/>
  <node id="42" lat="5" lon="6"/>
  <node id="43" lat="6" lon="6.5"/>
  <node id="44" lat="6" lon="5"/>
  <node id="50" lat="7.5" lon="8"><tag k="place" v="city"/><tag k="name" v="Beta City"/></node>
  <node id="51" lat="2.5" lon="1.5"><tag k="place" v="town"/><tag k="name" v="Alpha Town"/></node>
  <way id="101"><nd ref="1"/><nd ref="2"/><nd ref="3"/><tag k="boundary" v="administrative"/><tag k="admin_level" v="2"/></way>
  <way id="102"><nd ref="3"/><nd ref="4"/><nd ref="1"/><tag k="boundary" v="administrative"/><tag k="admin_level" v="2"/></way>
  <way id="103"><nd ref="11"/><nd ref="12"/><nd ref="13"/><nd ref="14"/><nd ref="11"/></way>
  <way id="104"><nd ref="31"/><nd ref="32"/><nd ref="33"/><nd ref="34"/></way>
  <way id="106"><nd ref="21"/><nd ref="22"/><nd ref="23"/><nd ref="24"/><nd ref="21"/></way>
  <way id="107"><nd ref="41"/><nd ref="42"/><nd ref="43"/><nd ref="44"/><nd ref="41"/></way>
  <relation id="201">
    <member type="way" ref="101" role="outer"/><member type="way" ref="102" role="outer"/>
    <member type="way" ref="103" role="inner"/><member type="node" ref="51" role="admin_centre"/>
    <tag k="type" v="boundary"/><tag k="boundary" v="administrative"/><tag k="admin_level" v="2"/>
    <tag k="ISO3166-1" v="AA"/><tag k="name" v="Alpha"/><tag k="name:en" v="Alphaland"/>
  </relation>
  <relation id="202">
    <member type="way" ref="104" role="outer"/><member type="way" ref="105" role="outer"/>
    <member type="node" ref="50" role="admin_centre"/>
    <tag k="type" v="boundary"/><tag k="boundary" v="administrative"/><tag k="admin_level" v="2"/>
    <tag k="ISO3166-1" v="BB"/><tag k="name" v="Beta"/>
  </relation>
  <relation id="203">
    <member type="way" ref="103" role="outer"/>
    <tag k="type" v="boundary"/><tag k="boundary" v="administrative"/><tag k="admin_level" v="2"/>
    <tag k="ISO3166-1" v="CC"/><tag k="name" v="Gamma"/>
  </relation>
  <relation id="204">
    <member type="way" ref="107" role="outer"/>
    <tag k="type" v="boundary"/><tag k="boundary" v="maritime"/><tag k="admin_level" v="2"/>
    <tag k="ISO3166-1" v="AA"/><tag k="name" v="Alpha EEZ"/>
  </relation>
  <relation id="205">
    <member type="way" ref="101" role="outer"/><member type="way" ref="102" role="outer"/>
    <tag k="type" v="boundary"/><tag k="boundary" v="administrative"/><tag k="admin_level" v="2"/>
    <tag k="name" v="Alpha (land mass)"/>
  </relation>
  <relation id="206">
    <member type="way" ref="106" role="outer"/>
    <tag k="type" v="boundary"/><tag k="boundary" v="administrative"/><tag k="admin_level" v="4"/>
    <tag k="ISO3166-2" v="AA-X"/><tag k="name" v="Xi"/>
  </relation>
</osm>
```

Add to `pipeline/tests/conftest.py`, next to `tiny_pbf`:

```python
@pytest.fixture(scope="session")
def admin_pbf(tmp_path_factory) -> Path:
    """admin.osm converted to PBF at test time (hand-written admin boundaries, see test_boundaries.py)."""
    if shutil.which("osmium") is None:
        pytest.fail("osmium-tool is required (brew install osmium-tool)")
    out = tmp_path_factory.mktemp("admin") / "boundaries.pbf"
    subprocess.run(["osmium", "cat", "--overwrite", "-o", str(out), str(FIXTURES / "admin.osm")], check=True)
    return out
```

- [ ] **Step 3: Write the failing boundary tests**

`pipeline/tests/test_boundaries.py`:

```python
import pytest
from shapely.geometry import LineString, Point, box

from poles.boundaries import Relation, assemble, load_admin_areas, read_relations, seed_points, way_geometries

EDGE = box(0, 0, 10, 10)
CODES = {2: "ISO3166-1", 4: "ISO3166-2"}


def test_read_relations_filters_administrative_at_levels(admin_pbf, tmp_path, log):
    rels = read_relations(admin_pbf, {2, 4}, tmp_path, log)
    assert sorted(r.id for r in rels) == [201, 202, 203, 205, 206]  # 204 is maritime
    r201 = next(r for r in rels if r.id == 201)
    assert r201.tags["ISO3166-1"] == "AA" and ("w", 103, "inner") in r201.members and ("n", 51, "admin_centre") in r201.members


def test_way_geometries_and_seeds_tolerate_missing_ids(admin_pbf, tmp_path, log):
    ways = way_geometries(admin_pbf, {101, 104, 105}, tmp_path, log)
    assert set(ways) == {101, 104} and ways[104].coords[0] == (12.0, 6.0)
    seeds = seed_points(admin_pbf, {50, 999}, tmp_path, log)
    assert set(seeds) == {50} and seeds[50].equals(Point(8, 7.5))


def test_assemble_closed_rings_with_inner_hole():
    rel = Relation(1, {}, [("w", 1, "outer"), ("w", 2, "outer"), ("w", 3, "inner")])
    ways = {1: LineString([(0, 0), (4, 0), (4, 4)]), 2: LineString([(4, 4), (0, 4), (0, 0)]),
            3: LineString([(1, 1), (2, 1), (2, 2), (1, 2), (1, 1)])}
    geom = assemble(rel, ways, {}, None)
    assert geom.geom_type == "MultiPolygon" and geom.area == pytest.approx(16 - 1)
    assert not geom.contains(Point(1.5, 1.5)) and geom.contains(Point(3, 3))


def test_assemble_open_ring_is_closed_along_edge_at_seed_faces():
    rel = Relation(2, {}, [("w", 4, "outer"), ("w", 5, "outer"), ("n", 50, "admin_centre")])
    ways = {4: LineString([(12, 6), (6, 6), (6, 9), (12, 9)])}
    geom = assemble(rel, ways, {50: Point(8, 7.5)}, EDGE)
    assert geom.area == pytest.approx(12.0)  # (6..10) x (6..9)
    assert geom.contains(Point(8, 7.5)) and not geom.contains(Point(11, 7.5)) and not geom.contains(Point(5, 7.5))


def test_assemble_open_ring_without_seed_or_edge_returns_none():
    rel = Relation(3, {}, [("w", 4, "outer")])
    ways = {4: LineString([(12, 6), (6, 6), (6, 9), (12, 9)])}
    assert assemble(rel, ways, {}, EDGE) is None
    assert assemble(rel, ways, {50: Point(8, 7.5)}, None) is None


def test_load_admin_areas_end_to_end(admin_pbf, tmp_path, log):
    areas = {a.osm_id: a for a in load_admin_areas(admin_pbf, {2, 4}, EDGE, tmp_path, log, CODES)}
    assert set(areas) == {201, 202, 203, 205, 206}
    aa, bb, cc, land, ax = areas[201], areas[202], areas[203], areas[205], areas[206]
    assert (aa.code, aa.level, aa.name_en, aa.complete, aa.closed_by_edge) == ("AA", 2, "Alphaland", True, False)
    assert aa.geometry.area == pytest.approx(9 - 1) and not aa.geometry.contains(Point(2.5, 2.5))
    assert (bb.code, bb.complete, bb.closed_by_edge) == ("BB", False, True) and bb.geometry.area == pytest.approx(12)
    assert cc.code == "CC" and cc.geometry.area == pytest.approx(1)
    assert land.code is None and land.geometry.area == pytest.approx(9)
    assert (ax.code, ax.level) == ("AA-X", 4) and ax.geometry.area == pytest.approx(2.6 * 0.6)
```

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_boundaries.py -q` -> ImportError.

- [ ] **Step 4: Implement `poles/boundaries.py`**

```python
"""Admin areas from `boundaries.pbf`, assembled from whatever members the extract holds (issue #15).

osmium's area assembler (and therefore stage 1's `osmium export`) drops a relation as soon as one member
is missing, which loses every country with territory outside the extract: Spain (Canaries), France
(overseas), the Netherlands (Caribbean), Norway (Bouvet), Russia and Iran (cut by the edge). Here the
present outer ways are merged into rings; closed rings become polygons with the inner rings they
contain as holes; an open line (a ring cut by the data edge) is closed along the edge polygon and only
the faces holding the relation's admin_centre or label node are kept, which is how Russia west of the
Volga becomes a polygon for nearest-way attribution. Relations are read as OPL, way geometries through
`osmium export -n`, seed nodes through `osmium getid`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import shapely
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, polygonize, unary_union

from . import opl
from .osmium import osmium
from .shell import run_cmd

ACCEPTED_TYPES = ("boundary", "multipolygon")


@dataclass
class Relation:
    id: int
    tags: dict[str, str]
    members: list[tuple[str, int, str]]


@dataclass
class AdminArea:
    osm_id: int
    level: int
    code: str | None
    name: str | None
    name_en: str | None
    geometry: MultiPolygon
    complete: bool
    closed_by_edge: bool


def _osmium_tolerant(args: list, log: logging.Logger, stderr_path: Path) -> None:
    """getid exits 1 when an id is missing but still writes what it found; both codes are fine here."""
    from .shell import ToolError
    try:
        osmium(args, log, stderr_path=stderr_path)
    except ToolError as e:
        if "exit 1:" not in str(e):
            raise


def read_relations(pbf: Path, levels: set[int], work: Path, log: logging.Logger) -> list[Relation]:
    work.mkdir(parents=True, exist_ok=True)
    out = work / "relations.opl"
    filters = [f"r/admin_level={level}" for level in sorted(levels)]
    osmium(["tags-filter", "--overwrite", "--omit-referenced", "-f", "opl", "-o", out, pbf, *filters], log,
           stderr_path=work / "tools.log")
    rels: list[Relation] = []
    for line in out.read_text(encoding="utf-8").splitlines():
        if not line.startswith("r"):
            continue
        fields = line.split(" ")
        rid = int(fields[0][1:])
        tags = members = None
        for f in fields[1:]:
            if f.startswith("T"):
                tags = opl.parse_tags(f[1:])
            elif f.startswith("M"):
                members = opl.parse_members(f[1:])
        tags, members = tags or {}, members or []
        if tags.get("boundary") != "administrative" or tags.get("type") not in ACCEPTED_TYPES:
            continue
        if tags.get("admin_level") not in {str(level) for level in levels}:
            continue
        rels.append(Relation(rid, tags, members))
    return rels


def way_geometries(pbf: Path, way_ids: set[int], work: Path, log: logging.Logger) -> dict[int, LineString]:
    """Linestrings for the requested way ids that exist in the file (untagged ways included)."""
    work.mkdir(parents=True, exist_ok=True)
    cfg = work / "export-ways.json"
    cfg.write_text(json.dumps({"attributes": {"type": "@type", "id": "@id"}, "linear_tags": True, "area_tags": False}),
                   encoding="utf-8")
    seq = work / "ways.geojsonseq"
    osmium(["export", "--overwrite", "-n", "-f", "geojsonseq", "-c", cfg, "--geometry-types=linestring", "-o", seq, pbf],
           log, stderr_path=work / "tools.log")
    ways: dict[int, LineString] = {}
    with open(seq, encoding="utf-8") as f:
        for line in f:
            line = line.lstrip("\x1e").strip()
            if not line:
                continue
            feature = json.loads(line)
            wid = int(feature["properties"]["@id"])
            if wid in way_ids:
                ways[wid] = shapely.from_geojson(json.dumps(feature["geometry"]))
    seq.unlink(missing_ok=True)
    return ways


def seed_points(pbf: Path, node_ids: set[int], work: Path, log: logging.Logger) -> dict[int, Point]:
    if not node_ids:
        return {}
    work.mkdir(parents=True, exist_ok=True)
    out = work / "seeds.opl"
    _osmium_tolerant(["getid", "--overwrite", "-f", "opl", "-o", out, pbf, *(f"n{n}" for n in sorted(node_ids))],
                     log, work / "tools.log")
    seeds: dict[int, Point] = {}
    for line in out.read_text(encoding="utf-8").splitlines():
        if not line.startswith("n"):
            continue
        fields = line.split(" ")
        x = y = None
        for f in fields[1:]:
            if f.startswith("x"):
                x = float(f[1:])
            elif f.startswith("y"):
                y = float(f[1:])
        if x is not None and y is not None:
            seeds[int(fields[0][1:])] = Point(x, y)
    return seeds


def _rings_and_open(lines: list[LineString]) -> tuple[list[Polygon], list[LineString]]:
    if not lines:
        return [], []
    merged = linemerge(lines) if len(lines) > 1 else lines[0]
    parts = list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]
    rings = [Polygon(p.coords) for p in parts if p.is_ring and len(p.coords) >= 4]
    return rings, [p for p in parts if not p.is_ring]


def assemble(rel: Relation, ways: dict[int, LineString], seeds: dict[int, Point], edge: BaseGeometry | None) -> MultiPolygon | None:
    outer_lines = [ways[ref] for kind, ref, role in rel.members if kind == "w" and role in ("outer", "") and ref in ways]
    inner_lines = [ways[ref] for kind, ref, role in rel.members if kind == "w" and role == "inner" and ref in ways]
    outers, open_lines = _rings_and_open(outer_lines)
    inners, _ = _rings_and_open(inner_lines)
    polys: list[Polygon] = []
    for shell in outers:
        holes = [h for h in inners if shell.contains(h.representative_point())]
        polys.append(Polygon(shell.exterior.coords, [h.exterior.coords for h in holes]) if holes else shell)
    if open_lines and edge is not None:
        seed_pts = [seeds[ref] for kind, ref, role in rel.members if kind == "n" and role in ("admin_centre", "label") and ref in seeds]
        if seed_pts:
            noded = unary_union([*open_lines, edge.boundary])
            for face in polygonize(noded):
                if any(face.contains(s) for s in seed_pts):
                    polys.append(face)
    if not polys:
        return None
    geom = shapely.make_valid(unary_union(polys))
    if geom.geom_type == "Polygon":
        geom = MultiPolygon([geom])
    elif geom.geom_type == "GeometryCollection":
        geom = MultiPolygon([g for g in geom.geoms if g.geom_type == "Polygon"] +
                            [p for g in geom.geoms if g.geom_type == "MultiPolygon" for p in g.geoms])
    return geom if not geom.is_empty else None


def assemble_area(rel: Relation, ways: dict[int, LineString], seeds: dict[int, Point], edge: BaseGeometry | None,
                  code_tag: str) -> AdminArea | None:
    geom = assemble(rel, ways, seeds, edge)
    if geom is None:
        return None
    way_refs = [ref for kind, ref, _ in rel.members if kind == "w"]
    complete = all(ref in ways for ref in way_refs)
    _, open_lines = _rings_and_open([ways[r] for kind, r, role in rel.members if kind == "w" and role in ("outer", "") and r in ways])
    return AdminArea(rel.id, int(rel.tags["admin_level"]), rel.tags.get(code_tag) or None, rel.tags.get("name"),
                     rel.tags.get("name:en") or rel.tags.get("name"), geom, complete, bool(open_lines))


def load_admin_areas(pbf: Path, levels: set[int], edge: BaseGeometry | None, work: Path, log: logging.Logger,
                     code_tags: dict[int, str]) -> list[AdminArea]:
    rels = read_relations(pbf, levels, work, log)
    way_ids = {ref for r in rels for kind, ref, _ in r.members if kind == "w"}
    node_ids = {ref for r in rels for kind, ref, role in r.members if kind == "n" and role in ("admin_centre", "label")}
    ways = way_geometries(pbf, way_ids, work, log)
    seeds = seed_points(pbf, node_ids, work, log)
    log.info("boundaries: %d relations, %d of %d member ways present, %d seed nodes", len(rels), len(ways), len(way_ids), len(seeds))
    areas = []
    for rel in rels:
        area = assemble_area(rel, ways, seeds, edge, code_tags.get(int(rel.tags["admin_level"]), "ISO3166-1"))
        if area is None:
            log.warning("boundaries: relation %d (%s) yields no polygon from the present members", rel.id, rel.tags.get("name"))
            continue
        areas.append(area)
    return areas
```

- [ ] **Step 5: Run the tests, then the suite**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_boundaries.py tests/test_opl.py -q` -> 8 passed. Then the full suite. If `shapely.from_geojson` rejects the feature geometry, build with `shapely.linestrings(feature["geometry"]["coordinates"])` instead.

- [ ] **Step 6: Commit**

```bash
git add pipeline/poles/opl.py pipeline/poles/boundaries.py pipeline/tests/fixtures/admin.osm pipeline/tests/conftest.py pipeline/tests/test_opl.py pipeline/tests/test_boundaries.py
git commit -m "poles: assemble admin areas from the present relation members, open rings closed along the data edge at the seed node (issue #15)"
```

- [ ] **Step 7: Smoke test on Europe (not a unit test)**

```bash
cd pipeline && export PATH=/opt/homebrew/bin:$PATH && .venv/bin/python -c "
import logging, sys, json
from pathlib import Path
from shapely.ops import unary_union
from poles.boundaries import load_admin_areas
from poles.poly import parse_poly
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
w = Path('../work/europe/2026-08-19')
snap = json.loads((w / 'fetch' / 'snapshot.json').read_text())
edge = unary_union([parse_poly(w / 'fetch' / s['poly']) for s in snap['sources']])
areas = load_admin_areas(w / 'extract' / 'boundaries.pbf', {2}, edge, w / 'poles' / 'boundaries-smoke', logging.getLogger('b'), {2: 'ISO3166-1'})
for a in sorted(areas, key=lambda a: a.code or ''):
    print(a.code, a.osm_id, a.name_en, round(a.geometry.area, 2), 'complete' if a.complete else 'partial', 'edge' if a.closed_by_edge else '')
"
```

Expected: ES, FR, NL, NO, RU (closed_by_edge), IR present with plausible areas in square degrees (ES about 60, FR about 70, RU several hundred); report the full list in the task summary. Delete `work/europe/2026-08-19/poles/boundaries-smoke` afterwards.

---

### Task 3: Units (task 2.1)

**Files:**
- Create: `pipeline/poles/units.py`, `pipeline/tests/test_units.py`

**Interfaces:**
- Consumes: `AdminArea` (Task 2); `poles.grid.Frame`, `create_raster`, `rasterize` (exist); `tests.helpers.write_fgb`; `poles.config.RegionConfig`.
- Produces: `class UnitsError(PolesError)`; `@dataclass Unit(code: str, name: str | None, name_en: str | None, osm_id: int, country: str, geometry: MultiPolygon, transcontinental: bool, index: int, area_km2: float = 0.0, cells: int = 0, closed_by_edge: bool = False)`; `apply_territory_mask(geom, masks: list[dict]) -> MultiPolygon` (masks are the config's `{name, bbox: [w, s, e, n]}` entries); `inside_fraction(geom, region: BaseGeometry) -> float`; `country_of(area: AdminArea, countries: list[AdminArea]) -> str | None` (level-2 own code, else the level-2 area containing the representative point); `select_units(areas: list[AdminArea], cfg: RegionConfig, primary: BaseGeometry) -> list[Unit]` (sorted by code, `index` 1-based in that order; raises `UnitsError` on a missing code only when the area is unit-eligible, and on `expected_units` mismatch); `write_units(units, path: Path)` (FlatGeobuf `units` with fields `code, name_en, country, idx, transcontinental`); `rasterize_units(units_fgb: Path, frame: Frame, land_tif: Path, out_tif: Path, log, workdir: Path) -> dict[int, int]` (int16 `units.tif`, cell counts per index after the land AND); `unit_cells(units_tif: Path, unit: Unit, frame: Frame, log, workdir: Path) -> tuple[np.ndarray, np.ndarray]` (rows, cols; all-touched fallback when the unit has no cell).

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/test_units.py`:

```python
import numpy as np
import pytest
import rasterio
from shapely.geometry import MultiPolygon, Point, box

from poles.boundaries import AdminArea
from poles.config import RegionConfig, load_region
from poles.grid import Frame, create_raster
from poles.units import (UnitsError, apply_territory_mask, country_of, inside_fraction, rasterize_units,
                         select_units, unit_cells, write_units)


def _area(osm_id, code, geom, level=2, name=None):
    return AdminArea(osm_id, level, code, name or code, name or code, MultiPolygon([geom]) if geom.geom_type == "Polygon" else geom, True, False)


def _cfg(regions_dir, **over) -> RegionConfig:
    base = load_region(regions_dir / "europe.yaml").__dict__ | over
    return RegionConfig(**base)


def test_territory_mask_removes_island_but_keeps_mainland():
    mainland, island = box(0, 0, 4, 4), box(8, 8, 9, 9)
    geom = apply_territory_mask(MultiPolygon([mainland, island]), [{"name": "Isle", "bbox": [7.5, 7.5, 9.5, 9.5]}])
    assert geom.area == pytest.approx(16) and geom.contains(Point(2, 2)) and not geom.intersects(island)


def test_inside_fraction():
    assert inside_fraction(box(0, 0, 2, 2), box(0, 0, 10, 10)) == pytest.approx(1.0)
    assert inside_fraction(box(-1, 0, 1, 2), box(0, 0, 10, 10)) == pytest.approx(0.5)
    assert inside_fraction(box(20, 20, 21, 21), box(0, 0, 10, 10)) == 0.0


def test_level4_units_take_country_from_container(regions_dir):
    aa = _area(1, "AA", box(0, 0, 10, 10))
    bb = _area(2, "BB", box(20, 0, 30, 10))
    state = _area(3, "AA-X", box(1, 1, 3, 3), level=4)
    assert country_of(state, [aa, bb]) == "aa"
    assert country_of(bb, [aa, bb]) == "bb"
    cfg = _cfg(regions_dir, unit_admin_level=4, unit_countries=["aa"], unit_exclude=[], territory_mask=[], expected_units=1, transcontinental=[])
    units = select_units([aa, bb, state], cfg, box(-5, -5, 40, 15))
    assert [(u.code, u.country, u.index) for u in units] == [("aa-x", "aa", 1)]


def test_select_units_applies_exclude_supplement_rule_and_flags(regions_dir):
    aa = _area(1, "AA", box(0, 0, 10, 10))
    ru = _area(2, "RU", box(20, 0, 30, 10))
    outside = _area(3, "ZZ", box(50, 50, 60, 60))       # supplement country: outside the primary polygon
    half = _area(4, "HH", box(-6, 0, 4, 10))              # 40% inside: not a unit
    nocode = _area(5, None, box(0, 20, 1, 21), name="Land mass")
    cfg = _cfg(regions_dir, unit_countries=None, unit_exclude=["ru"], territory_mask=[], expected_units=1, transcontinental=["aa"])
    units = select_units([aa, ru, outside, half, nocode], cfg, box(0, 0, 40, 40))
    assert [(u.code, u.transcontinental) for u in units] == [("aa", True)]


def test_unit_count_mismatch_fails(regions_dir):
    aa = _area(1, "AA", box(0, 0, 10, 10))
    cfg = _cfg(regions_dir, unit_exclude=[], territory_mask=[], expected_units=2)
    with pytest.raises(UnitsError, match="expected 2"):
        select_units([aa], cfg, box(0, 0, 40, 40))


def test_unit_raster_assigns_each_cell_to_one_unit(tmp_path, log, regions_dir):
    aa = _area(1, "AA", box(0, 0, 2, 2))
    bb = _area(2, "BB", box(2, 0, 4, 2))
    cfg = _cfg(regions_dir, unit_exclude=[], territory_mask=[], expected_units=2, transcontinental=[])
    units = select_units([aa, bb], cfg, box(-1, -1, 10, 10))
    fgb = write_units(units, tmp_path / "units.fgb")
    frame = Frame("EPSG:4326", 0.5, -1.0, 3.0, 10, 8)        # lon -1..4, lat -1..3 at 0.5 degree cells
    land = create_raster(frame, tmp_path / "land.tif")
    with rasterio.open(land, "r+") as ds:
        arr = ds.read(1)
        arr[:, :] = 1
        arr[:, 9] = 0                                        # the easternmost column is sea
        ds.write(arr, 1)
    counts = rasterize_units(fgb, frame, land, tmp_path / "units.tif", log, tmp_path)
    with rasterio.open(tmp_path / "units.tif") as ds:
        u = ds.read(1)
    assert u.dtype == np.int16 and set(np.unique(u)) == {0, 1, 2}
    assert counts == {1: 16, 2: 12}                         # 4 x 4 cells each, minus bb's sea column
    assert u[2:6, 2:6].min() == 1 and u[2:6, 6:9].min() == 2 and u[:, 9].max() == 0 and u[0].max() == 0


def test_unit_cells_falls_back_to_all_touched_for_a_microstate(tmp_path, log, regions_dir):
    tiny = _area(1, "TT", box(1.1, 1.1, 1.2, 1.2))        # smaller than a cell, contains no cell centre
    cfg = _cfg(regions_dir, unit_exclude=[], territory_mask=[], expected_units=1, transcontinental=[])
    units = select_units([tiny], cfg, box(0, 0, 10, 10))
    fgb = write_units(units, tmp_path / "units.fgb")
    frame = Frame("EPSG:4326", 0.5, 0.0, 3.0, 6, 6)
    land = create_raster(frame, tmp_path / "land.tif")
    with rasterio.open(land, "r+") as ds:
        ds.write(np.ones((6, 6), dtype="uint8"), 1)
    counts = rasterize_units(fgb, frame, land, tmp_path / "units.tif", log, tmp_path)
    assert counts == {1: 0}
    rows, cols = unit_cells(tmp_path / "units.tif", units[0], frame, log, tmp_path)
    assert list(zip(rows.tolist(), cols.tolist())) == [(3, 2)]   # lat 1.1..1.2 is row 3, lon 1.1..1.2 is col 2
```

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_units.py -q` -> ImportError.

- [ ] **Step 2: Implement `poles/units.py`**

```python
"""Units: the admin areas that get a pole and a rank (spec 2.2), and their raster on the coarse frame."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
import shapely
from pyogrio.raw import write
from shapely.geometry import MultiPolygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .boundaries import AdminArea
from .config import RegionConfig
from .errors import PolesError
from .grid import Frame, create_raster, rasterize

MIN_INSIDE_FRACTION = 0.5  # at least half of a country must lie inside the primary source polygons to be a unit


class UnitsError(PolesError):
    pass


@dataclass
class Unit:
    code: str
    name: str | None
    name_en: str | None
    osm_id: int
    country: str
    geometry: MultiPolygon
    transcontinental: bool
    index: int
    area_km2: float = 0.0
    cells: int = 0
    closed_by_edge: bool = False


def _multi(geom: BaseGeometry) -> MultiPolygon:
    if geom.geom_type == "Polygon":
        return MultiPolygon([geom])
    if geom.geom_type == "GeometryCollection":
        return MultiPolygon([p for g in geom.geoms for p in (g.geoms if g.geom_type == "MultiPolygon" else [g]) if p.geom_type == "Polygon"])
    return geom


def apply_territory_mask(geom: BaseGeometry, masks: list[dict]) -> MultiPolygon:
    for mask in masks:
        w, s, e, n = mask["bbox"]
        geom = geom.difference(box(w, s, e, n))
    return _multi(geom)


def inside_fraction(geom: BaseGeometry, region: BaseGeometry) -> float:
    return 0.0 if geom.area == 0 else geom.intersection(region).area / geom.area


def country_of(area: AdminArea, countries: list[AdminArea]) -> str | None:
    if area.level == 2:
        return area.code.lower() if area.code else None
    point = area.geometry.representative_point()
    for c in countries:
        if c.level == 2 and c.code and c.geometry.contains(point):
            return c.code.lower()
    return None


def select_units(areas: list[AdminArea], cfg: RegionConfig, primary: BaseGeometry) -> list[Unit]:
    countries = [a for a in areas if a.level == 2]
    units: list[Unit] = []
    for area in areas:
        if area.level != cfg.unit_admin_level:
            continue
        if inside_fraction(area.geometry, primary) < MIN_INSIDE_FRACTION:
            continue
        country = country_of(area, countries)
        if country is None:
            if area.level == 2 and area.code is None:
                continue  # "land mass" style relations without a code are not countries
            raise UnitsError(f"unit relation {area.osm_id} ({area.name}) has no country")
        if not cfg.is_unit_country(country):
            continue
        if not area.code:
            raise UnitsError(f"unit relation {area.osm_id} ({area.name}) has no {cfg.unit_code_tag} code")
        code = area.code.lower()
        geom = apply_territory_mask(area.geometry, cfg.territory_mask)
        if geom.is_empty:
            raise UnitsError(f"unit {code}: the territory mask removed everything")
        units.append(Unit(code, area.name, area.name_en, area.osm_id, country, geom, code in cfg.transcontinental, 0,
                          closed_by_edge=area.closed_by_edge))
    units.sort(key=lambda u: u.code)
    for i, u in enumerate(units, start=1):
        u.index = i
    if cfg.expected_units is not None and len(units) != cfg.expected_units:
        raise UnitsError(f"expected {cfg.expected_units} units, found {len(units)}: {' '.join(u.code for u in units)}")
    if len(units) > 32000:
        raise UnitsError("more than 32000 units do not fit the int16 unit raster")
    return units


def write_units(units: list[Unit], path: Path) -> Path:
    write(str(path), geometry=np.array([shapely.to_wkb(u.geometry) for u in units], dtype=object),
          field_data=[np.array([u.code for u in units], dtype=object), np.array([u.name_en for u in units], dtype=object),
                      np.array([u.country for u in units], dtype=object), np.array([u.index for u in units], dtype=np.int32),
                      np.array([int(u.transcontinental) for u in units], dtype=np.int32)],
          fields=["code", "name_en", "country", "idx", "transcontinental"], layer="units", driver="FlatGeobuf",
          geometry_type="MultiPolygon", crs="EPSG:4326")
    return path


def rasterize_units(units_fgb: Path, frame: Frame, land_tif: Path, out_tif: Path, log: logging.Logger, workdir: Path) -> dict[int, int]:
    """int16 unit index per cell (cell-centre rule, later units overwrite earlier ones on shared edges), ANDed with land."""
    tools_log = Path(workdir) / "tools.log"
    create_raster(frame, out_tif, dtype="int16")
    cmd = ["gdal_rasterize", "-a", "idx", "-l", "units", units_fgb, out_tif]
    from .shell import run_cmd
    run_cmd(cmd, log, stderr_path=tools_log)
    counts: dict[int, int] = {}
    with rasterio.open(out_tif, "r+") as units, rasterio.open(land_tif) as land:
        for _, window in units.block_windows(1):
            u = units.read(1, window=window)
            u[land.read(1, window=window) == 0] = 0
            units.write(u, 1, window=window)
            ids, n = np.unique(u[u > 0], return_counts=True)
            for i, c in zip(ids.tolist(), n.tolist()):
                counts[i] = counts.get(i, 0) + c
    return counts


def unit_cells(units_tif: Path, unit: Unit, frame: Frame, log: logging.Logger, workdir: Path) -> tuple[np.ndarray, np.ndarray]:
    """(rows, cols) of the unit's cells. A unit too small to hold a cell centre (a microstate) gets the cells its
    polygon touches instead, so it still has candidates; its refinement is masked to the polygon anyway."""
    with rasterio.open(units_tif) as ds:
        rows, cols = np.nonzero(ds.read(1) == unit.index)
    if len(rows):
        return rows, cols
    log.warning("unit %s has no cell centre on the %d m grid; using all-touched cells", unit.code, frame.res)
    tmp_fgb = Path(workdir) / f"unit-{unit.code}.fgb"
    write_units([unit], tmp_fgb)
    tmp_tif = Path(workdir) / f"unit-{unit.code}.tif"
    create_raster(frame, tmp_tif)
    rasterize(tmp_fgb, "units", tmp_tif, log, Path(workdir) / "tools.log", burn=1, all_touched=True)
    with rasterio.open(tmp_tif) as ds:
        rows, cols = np.nonzero(ds.read(1))
    tmp_fgb.unlink(missing_ok=True)
    tmp_tif.unlink(missing_ok=True)
    if not len(rows):
        raise UnitsError(f"unit {unit.code} touches no cell of the frame")
    return rows, cols
```

Note for the implementer: `unit_cells` reads the whole `units.tif` (1.35 GB for Europe) once per call; Task 6 reads a window instead (it knows the unit bbox). Keep this simple version for the tests and the fallback, and add `window: Window | None = None` if Task 6 needs it.

- [ ] **Step 3: Run the tests, then the suite, then commit**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_units.py -q` -> 7 passed; full suite green.

```bash
git add pipeline/poles/units.py pipeline/tests/test_units.py
git commit -m "poles: unit selection (country rule, supplement rule by area, territory mask), units.fgb and int16 units.tif ANDed with land"
```

---

### Task 4: Candidates, the branch-and-bound sweep (task 2.2)

**Files:**
- Create: `pipeline/poles/candidates.py`, `pipeline/tests/test_candidates.py`

**Interfaces:**
- Consumes: nothing from other tasks (pure numpy plus pyproj).
- Produces: `half_diag(res_m) -> float`; `pad_fn_for(crs: str, safety: float = PAD_SAFETY) -> Callable[[np.ndarray, np.ndarray], np.ndarray]` (lons, lats -> pad per point, `>= safety`); `@dataclass Refined(x: float, y: float, dist_m: float, payload: object)` (x, y in the frame CRS); `@dataclass SearchResult(accepted: list[Refined], refinements: int, exhausted: bool, warnings: list[str])`; `class Search(xs, ys, coarse, pads, res_m, top_n, refiner, dedup_m=10_000.0, warn_at=500, fail_at=20_000, log=None)` with `.run() -> SearchResult`. `refiner(i: int) -> Refined | None` receives the index into the (already sorted) arrays; returning None means the cell has no allowed point. `Search` sorts its inputs by coarse descending itself and exposes `.order` for callers that need the original index.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/test_candidates.py`:

```python
import numpy as np
import pytest

from poles.candidates import Refined, Search, half_diag, pad_fn_for


def test_pad_grows_with_distance_from_centre():
    pad = pad_fn_for("EPSG:3035")
    near = pad(np.array([10.0]), np.array([52.0]))[0]
    far = pad(np.array([-10.0]), np.array([35.0]))[0]
    arctic = pad(np.array([30.0]), np.array([75.0]))[0]
    assert 0.002 <= near < 0.003 and near < arctic and near < far
    assert 0.02 < far < 0.04  # about 2,500 km from the centre: 1/cos(c/2) - 1 is about 2%


def test_half_diag():
    assert half_diag(250.0) == pytest.approx(176.7767)


def _truth_field(rng, n=60, roads=25):
    """A synthetic unit: n x n cells of 100 m; roads are random points; the true distance is exact."""
    res = 100.0
    road = rng.uniform(0, n * res, size=(roads, 2))
    def true_dist(px, py):
        return np.sqrt(((px[:, None] - road[None, :, 0]) ** 2 + (py[:, None] - road[None, :, 1]) ** 2).min(axis=1))
    rows, cols = np.mgrid[0:n, 0:n]
    xs, ys = (cols.ravel() + 0.5) * res, (rows.ravel() + 0.5) * res
    # coarse = distance between cell centres after snapping roads to cells, scaled by a fake projection error
    road_cells = (np.floor(road / res) + 0.5) * res
    coarse = np.sqrt(((xs[:, None] - road_cells[None, :, 0]) ** 2 + (ys[:, None] - road_cells[None, :, 1]) ** 2).min(axis=1))
    pads = 0.002 + 0.01 * (xs / (n * res))
    coarse = coarse * (1 + (pads - 0.002) * rng.uniform(-1, 1, size=len(xs)))  # the 0.002 safety covers second-order terms, as in production
    return res, xs, ys, coarse, pads, true_dist


def _exact_refiner(xs, ys, res, true_dist):
    sub = np.linspace(-res / 2 + 1, res / 2 - 1, 25)
    gx, gy = np.meshgrid(sub, sub)
    def refiner(i):
        px, py = xs[i] + gx.ravel(), ys[i] + gy.ravel()
        d = true_dist(px, py)
        k = int(np.argmax(d))
        return Refined(float(px[k]), float(py[k]), float(d[k]), None)
    return refiner


@pytest.mark.parametrize("seed", range(12))
def test_never_prunes_planted_maximum(seed):
    rng = np.random.default_rng(seed)
    res, xs, ys, coarse, pads, true_dist = _truth_field(rng)
    # brute force truth: the best refined value over every cell
    refine_all = _exact_refiner(xs, ys, res, true_dist)
    best = max(refine_all(i).dist_m for i in range(len(xs)))
    s = Search(xs, ys, coarse, pads, res, top_n=1, refiner=_exact_refiner(xs, ys, res, true_dist), dedup_m=0.0)
    r = s.run()
    assert r.accepted[0].dist_m == pytest.approx(best)
    assert r.refinements < len(xs)  # it pruned something


def test_dedup_and_dominance_give_top_n_at_least_dedup_apart():
    rng = np.random.default_rng(3)
    res, xs, ys, coarse, pads, true_dist = _truth_field(rng)
    s = Search(xs, ys, coarse, pads, res, top_n=3, refiner=_exact_refiner(xs, ys, res, true_dist), dedup_m=800.0)
    r = s.run()
    assert len(r.accepted) == 3
    for a in r.accepted:
        for b in r.accepted:
            if a is not b:
                assert np.hypot(a.x - b.x, a.y - b.y) >= 800.0
    # greedy truth: refine everything, sort, accept with the same dedup
    allp = sorted((_exact_refiner(xs, ys, res, true_dist)(i) for i in range(len(xs))), key=lambda p: -p.dist_m)
    greedy = []
    for p in allp:
        if all(np.hypot(p.x - q.x, p.y - q.y) >= 800.0 for q in greedy):
            greedy.append(p)
        if len(greedy) == 3:
            break
    assert [round(p.dist_m, 6) for p in r.accepted] == [round(p.dist_m, 6) for p in greedy]


def test_exhausted_unit_returns_fewer_poles_with_reason():
    xs = np.array([50.0, 150.0]); ys = np.array([50.0, 50.0])
    coarse = np.array([300.0, 280.0]); pads = np.array([0.002, 0.002])
    refiner = lambda i: Refined(xs[i], ys[i], coarse[i], None)
    r = Search(xs, ys, coarse, pads, 100.0, top_n=5, refiner=refiner, dedup_m=10_000.0).run()
    assert len(r.accepted) == 1 and r.exhausted and r.refinements <= 2


def test_refiner_none_skips_cell_and_warn_threshold_logs():
    xs = np.arange(10) * 100.0 + 50; ys = np.zeros(10) + 50
    coarse = np.full(10, 1000.0); pads = np.full(10, 0.002)
    calls = []
    def refiner(i):
        calls.append(i)
        return None if i % 2 else Refined(xs[i], ys[i], coarse[i], None)
    r = Search(xs, ys, coarse, pads, 100.0, top_n=2, refiner=refiner, dedup_m=150.0, warn_at=3).run()
    assert len(r.accepted) == 2 and any("refinements" in w for w in r.warnings)
```

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_candidates.py -q` -> ImportError.

- [ ] **Step 2: Implement `poles/candidates.py`**

```python
"""Branch-and-bound over the coarse grid (spec 3.2 stage 5, DECISIONS 2026-08-21 item 4).

Every cell of a unit carries a coarse distance c (cell centre to the nearest road cell centre, projected
metres). Any point of the cell is within half a diagonal of the centre and the nearest road passes within
half a diagonal of the road cell centre, so the true distance of any point in the cell is at most
(c + 2 * hd) * (1 + pad), where pad bounds the projection's scale error at that cell plus a small safety
for UTM and the ellipsoid. Cells are visited in descending c; a refined point is a lower bound on the
unit's maximum. A refined point becomes final once no unvisited cell can beat it; final points are
accepted greedily with the dedup distance; every unvisited cell that lies surely within the dedup
distance of an accepted pole is dominated and skipped. The result equals "refine every cell, sort,
accept greedily", proven on synthetic fields in tests/test_candidates.py.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from pyproj import Proj

PAD_SAFETY = 0.002


def half_diag(res_m: float) -> float:
    return res_m * math.sqrt(2) / 2


def pad_fn_for(crs: str, safety: float = PAD_SAFETY) -> Callable[[np.ndarray, np.ndarray], np.ndarray]:
    """Max relative length distortion of `crs` at lon/lat points, from Tissot's indicatrix, plus `safety`."""
    proj = Proj(crs)

    def pad(lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
        f = proj.get_factors(np.asarray(lons, dtype=float), np.asarray(lats, dtype=float))
        a = np.asarray(f.tissot_semimajor, dtype=float)
        b = np.asarray(f.tissot_semiminor, dtype=float)
        return np.maximum(np.abs(a - 1.0), np.abs(1.0 - b)) + safety

    return pad


@dataclass
class Refined:
    x: float
    y: float
    dist_m: float
    payload: object = None


@dataclass
class SearchResult:
    accepted: list[Refined]
    refinements: int
    exhausted: bool
    warnings: list[str] = field(default_factory=list)


class Search:
    def __init__(self, xs, ys, coarse, pads, res_m: float, top_n: int, refiner: Callable[[int], Refined | None],
                 dedup_m: float = 10_000.0, warn_at: int = 500, fail_at: int = 20_000, log: logging.Logger | None = None):
        order = np.argsort(-np.asarray(coarse, dtype=float), kind="stable")
        self.order = order
        self.xs = np.asarray(xs, dtype=float)[order]
        self.ys = np.asarray(ys, dtype=float)[order]
        self.coarse = np.asarray(coarse, dtype=float)[order]
        self.pads = np.asarray(pads, dtype=float)[order]
        self.hd = half_diag(res_m)
        self.top_n, self.refiner, self.dedup_m = top_n, refiner, dedup_m
        self.warn_at, self.fail_at, self.log = warn_at, fail_at, log
        self.pad_max = float(self.pads.max()) if len(self.pads) else 0.0

    def upper(self, i: int) -> float:
        return (self.coarse[i] + 2 * self.hd) * (1 + self.pads[i])

    def run(self) -> SearchResult:
        n = len(self.coarse)
        alive = np.ones(n, dtype=bool)
        pending: list[Refined] = []      # refined, not yet final, kept sorted by dist_m descending
        accepted: list[Refined] = []
        refinements = 0
        warnings: list[str] = []
        i = 0

        def finalize(up_to_value: float) -> None:
            """Make final every pending point above up_to_value, greedily accept, mask dominated cells."""
            nonlocal pending
            while pending and pending[0].dist_m > up_to_value and len(accepted) < self.top_n:
                p = pending.pop(0)
                if all(math.hypot(p.x - q.x, p.y - q.y) * (1 + self.pad_max) >= self.dedup_m for q in accepted):
                    accepted.append(p)
                    if self.dedup_m > 0:
                        # a cell is dominated when even its farthest point is within dedup_m of p
                        d = np.hypot(self.xs - p.x, self.ys - p.y)
                        alive[(d + self.hd) * (1 + self.pads) < self.dedup_m] = False

        while i < n and len(accepted) < self.top_n:
            if not alive[i]:
                i += 1
                continue
            remaining_upper = (self.coarse[i] + 2 * self.hd) * (1 + self.pad_max)
            finalize(remaining_upper)
            if len(accepted) >= self.top_n or not alive[i]:
                i += 1
                continue
            refined = self.refiner(i)
            refinements += 1
            if refinements == self.warn_at:
                msg = f"{refinements} refinements and counting; the unit has a large plateau near its maximum"
                warnings.append(msg)
                if self.log:
                    self.log.warning(msg)
            if refinements >= self.fail_at:
                raise RuntimeError(f"branch-and-bound exceeded {self.fail_at} refinements; the bound is not pruning")
            if refined is not None:
                k = 0
                while k < len(pending) and pending[k].dist_m >= refined.dist_m:
                    k += 1
                pending.insert(k, refined)
            i += 1
        finalize(-math.inf)
        exhausted = len(accepted) < self.top_n
        return SearchResult(accepted, refinements, exhausted, warnings)
```

- [ ] **Step 3: Run the tests, then the suite, then commit**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_candidates.py -q` -> 17 passed (12 seeds plus 5). If `test_never_prunes_planted_maximum` fails, the bound is wrong, not the test: do not loosen the test.

```bash
git add pipeline/poles/candidates.py pipeline/tests/test_candidates.py
git commit -m "poles: branch-and-bound sweep with Tissot distortion pad, final-point greedy acceptance and exact dominance pruning"
```

---

### Task 5: Exact refinement in UTM (task 2.3)

**Files:**
- Create: `pipeline/poles/refine.py`, `pipeline/tests/test_refine.py`

**Interfaces:**
- Consumes: `RoadSet` (Task 1).
- Produces: `utm_epsg(lon: float, lat: float) -> int` (32600 + zone north, 32700 + zone south, zone = floor((lon + 180) / 6) + 1 clamped to 1..60; no Norway or Svalbard exceptions, which only matter for grid conventions, not for distances); `@dataclass RefinedPole(lat: float, lon: float, dist_m: float, way_id: int, x: float, y: float, utm_epsg: int, way_index: int)`; `class UtmRoads(roads: RoadSet, epsg: int)` with `.geoms` (UTM), `.tree: STRtree`, `.roads` (the lon/lat RoadSet); `refine(x: float, y: float, src_crs: str, roads: UtmRoads, half_m: float = 250.0, steps: tuple[float, float] = (25.0, 5.0), allowed: Callable[[np.ndarray, np.ndarray], np.ndarray] | None = None) -> RefinedPole | None` (`allowed(lons, lats)` returns a boolean mask; None when no grid point is allowed or the road set is empty); `class RoadCache(tiles: RoadTiles, where: str | None)` with `.get(west, south, east, north, epsg) -> UtmRoads` (reuses the last `UtmRoads` when the requested bbox lies inside the cached bbox and the zone matches; otherwise queries the tiles with a bbox padded by `pad_deg`, default 0.2).

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/test_refine.py`:

```python
import numpy as np
import pytest
from pyproj import Transformer
from shapely.geometry import LineString

from poles.refine import RoadCache, UtmRoads, refine, utm_epsg
from poles.roads import RoadSet


def _roadset(lines_utm, epsg, ids=None):
    """Roads given in UTM metres, converted to the lon/lat RoadSet the pipeline carries."""
    to_ll = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    geoms = []
    for line in lines_utm:
        xs, ys = zip(*line)
        lons, lats = to_ll.transform(xs, ys)
        geoms.append(LineString(list(zip(lons, lats))))
    ids = ids or list(range(1, len(geoms) + 1))
    n = len(geoms)
    return RoadSet(np.array(geoms, dtype=object), {"osm_id": np.array(ids, dtype=object), "highway": np.array(["track"] * n, dtype=object),
                                                   "name": np.array([None] * n, dtype=object), "ref": np.array([None] * n, dtype=object)})


def test_utm_zone_selection_including_norway_exception_not_applied():
    assert utm_epsg(23.5, 54.4) == 32635          # Lithuania, zone 35N
    assert utm_epsg(-3.0, 40.0) == 32630          # Spain, zone 30N
    assert utm_epsg(5.0, 60.0) == 32631           # Bergen: plain zone 31, the Norway exception (zone 32) is not applied
    assert utm_epsg(151.2, -33.9) == 32756        # Sydney, southern hemisphere
    assert utm_epsg(-180.0, 10.0) == 32601 and utm_epsg(180.0, 10.0) == 32660


def test_single_straight_road_known_offset():
    epsg = 32635
    road = [(500_000 - 5000, 6_000_000), (500_000 + 5000, 6_000_000)]   # along y = 6,000,000 in zone 35N
    roads = UtmRoads(_roadset([road], epsg), epsg)
    # window centred 1000 m north of the road: the maximum is at the far (north) edge, 1250 m away
    pole = refine(500_000, 6_001_000, f"EPSG:{epsg}", roads, half_m=250.0, steps=(25.0, 5.0))
    assert pole.dist_m == pytest.approx(1250.0, abs=2.5)
    assert pole.utm_epsg == epsg and pole.way_id == 1
    assert pole.y == pytest.approx(6_001_250, abs=5) and 499_700 <= pole.x <= 500_300


def test_two_roads_midpoint():
    epsg = 32635
    a = [(490_000, 6_000_000), (510_000, 6_000_000)]
    b = [(490_000, 6_002_000), (510_000, 6_002_000)]
    roads = UtmRoads(_roadset([a, b], epsg), epsg)
    pole = refine(500_000, 6_000_900, f"EPSG:{epsg}", roads)
    assert pole.dist_m == pytest.approx(1000.0, abs=2.5) and pole.y == pytest.approx(6_001_000, abs=5)


def test_result_nearest_way_id_matches_closest_geometry():
    epsg = 32635
    a = [(499_000, 6_000_000), (501_000, 6_000_000)]
    b = [(499_000, 6_003_000), (501_000, 6_003_000)]
    roads = UtmRoads(_roadset([a, b], epsg, ids=[77, 88]), epsg)
    pole = refine(500_000, 6_002_600, f"EPSG:{epsg}", roads, half_m=100.0)
    assert pole.way_id == 88 and pole.way_index == 1


def test_allowed_mask_restricts_grid_and_none_when_empty():
    epsg = 32635
    road = [(495_000, 6_000_000), (505_000, 6_000_000)]
    roads = UtmRoads(_roadset([road], epsg), epsg)
    to_ll = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    lon_cut, _ = to_ll.transform(500_000, 6_001_000)
    west_only = lambda lons, lats: np.asarray(lons) < lon_cut
    pole = refine(500_000, 6_001_000, f"EPSG:{epsg}", roads, allowed=west_only)
    assert pole.x < 500_000
    assert refine(500_000, 6_001_000, f"EPSG:{epsg}", roads, allowed=lambda lons, lats: np.zeros(len(lons), bool)) is None


def test_src_crs_is_transformed_to_utm():
    epsg = 32635
    road = [(500_000 - 5000, 6_000_000), (500_000 + 5000, 6_000_000)]
    roads = UtmRoads(_roadset([road], epsg), epsg)
    to_laea = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:3035", always_xy=True)
    x, y = to_laea.transform(500_000, 6_001_000)
    pole = refine(x, y, "EPSG:3035", roads)
    assert pole.dist_m == pytest.approx(1250.0, abs=3.0)


class _FakeTiles:
    def __init__(self):
        self.calls = []
    def query(self, west, south, east, north, where=None):
        self.calls.append((west, south, east, north, where))
        return _roadset([[(500_000 - 5000, 6_000_000), (500_000 + 5000, 6_000_000)]], 32635)


def test_road_cache_reuses_covering_bbox():
    tiles = _FakeTiles()
    cache = RoadCache(tiles, where="highway IN ('track')", pad_deg=0.5)
    r1 = cache.get(23.0, 54.0, 23.1, 54.1, 32635)
    r2 = cache.get(23.02, 54.02, 23.08, 54.08, 32635)
    assert r1 is r2 and len(tiles.calls) == 1 and tiles.calls[0][4] == "highway IN ('track')"
    cache.get(30.0, 60.0, 30.1, 60.1, 32636)
    assert len(tiles.calls) == 2
```

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_refine.py -q` -> ImportError.

- [ ] **Step 2: Implement `poles/refine.py`**

```python
"""Exact refinement of a coarse candidate: the farthest point from any road on a 25 m then 5 m grid in the
candidate's UTM zone (spec 2.4, same method as the Lithuania demo)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
import shapely
from pyproj import Transformer
from shapely.strtree import STRtree

from .roads import RoadSet


def utm_epsg(lon: float, lat: float) -> int:
    zone = min(60, max(1, int(math.floor((lon + 180.0) / 6.0)) + 1))
    return (32600 if lat >= 0 else 32700) + zone


@dataclass
class RefinedPole:
    lat: float
    lon: float
    dist_m: float
    way_id: int
    x: float
    y: float
    utm_epsg: int
    way_index: int


class UtmRoads:
    """A RoadSet projected to one UTM zone with its STRtree, built once per cached bbox."""

    def __init__(self, roads: RoadSet, epsg: int):
        self.roads = roads
        self.epsg = epsg
        tr = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
        self.geoms = shapely.transform(roads.geoms, lambda c: np.column_stack(tr.transform(c[:, 0], c[:, 1]))) if len(roads) else np.array([], dtype=object)
        self.tree = STRtree(self.geoms) if len(roads) else None
        self.to_lonlat = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)


def _best_on_grid(cx: float, cy: float, half: float, step: float, roads: UtmRoads, allowed) -> tuple[float, float, float, int] | None:
    ax = np.arange(cx - half, cx + half + step / 2, step)
    ay = np.arange(cy - half, cy + half + step / 2, step)
    gx, gy = np.meshgrid(ax, ay)
    px, py = gx.ravel(), gy.ravel()
    if allowed is not None:
        lons, lats = roads.to_lonlat.transform(px, py)
        keep = np.asarray(allowed(np.asarray(lons), np.asarray(lats)), dtype=bool)
        px, py = px[keep], py[keep]
        if len(px) == 0:
            return None
    pts = shapely.points(px, py)
    idx, dist = roads.tree.query_nearest(pts, return_distance=True, all_matches=False)
    d = np.full(len(pts), -np.inf)
    d[idx[0]] = dist
    nearest = np.full(len(pts), -1)
    nearest[idx[0]] = idx[1]
    k = int(np.argmax(d))
    return float(px[k]), float(py[k]), float(d[k]), int(nearest[k])


def refine(x: float, y: float, src_crs: str, roads: UtmRoads, half_m: float = 250.0, steps: tuple[float, float] = (25.0, 5.0),
           allowed: Callable[[np.ndarray, np.ndarray], np.ndarray] | None = None) -> RefinedPole | None:
    if roads.tree is None:
        return None
    if src_crs != f"EPSG:{roads.epsg}":
        cx, cy = Transformer.from_crs(src_crs, f"EPSG:{roads.epsg}", always_xy=True).transform(x, y)
    else:
        cx, cy = x, y
    coarse_step, fine_step = steps
    best = _best_on_grid(cx, cy, half_m, coarse_step, roads, allowed)
    if best is None:
        return None
    bx, by, _, _ = best
    fine = _best_on_grid(bx, by, coarse_step, fine_step, roads, allowed) or best
    fx, fy, fd, fi = fine
    lon, lat = roads.to_lonlat.transform(fx, fy)
    return RefinedPole(float(lat), float(lon), fd, int(roads.roads.attrs["osm_id"][fi]), fx, fy, roads.epsg, fi)


class RoadCache:
    """Roads for one bbox at a time: refinements of neighbouring cells share one tile query and one projection."""

    def __init__(self, tiles, where: str | None = None, pad_deg: float = 0.2):
        self.tiles, self.where, self.pad_deg = tiles, where, pad_deg
        self._bbox: tuple[float, float, float, float] | None = None
        self._roads: UtmRoads | None = None

    def get(self, west: float, south: float, east: float, north: float, epsg: int) -> UtmRoads:
        b = self._bbox
        if self._roads is not None and self._roads.epsg == epsg and b is not None \
                and b[0] <= west and b[1] <= south and b[2] >= east and b[3] >= north:
            return self._roads
        bbox = (west - self.pad_deg, south - self.pad_deg, east + self.pad_deg, north + self.pad_deg)
        self._roads = UtmRoads(self.tiles.query(*bbox, where=self.where), epsg)
        self._bbox = bbox
        return self._roads
```

- [ ] **Step 3: Run the tests, then the suite, then commit**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_refine.py -q` -> 8 passed.

```bash
git add pipeline/poles/refine.py pipeline/tests/test_refine.py
git commit -m "poles: exact UTM refinement on a 25 m then 5 m grid with an allowed-point mask and a road cache"
```

---

### Task 6: Attribution and the poles stage (task 2.4), then the Europe run

**Files:**
- Create: `pipeline/poles/attrib.py`, `pipeline/poles/poles.py`, `pipeline/tests/test_attrib.py`, `pipeline/tests/test_poles_stage.py`
- Modify: `pipeline/poles/stages.py` (register `poles`), `pipeline/regions/europe.yaml` (`expected_units` after the count)

**Interfaces:**
- Consumes: `RoadTiles`, `RoadSet`, `build_tiles` (Task 1); `load_admin_areas`, `AdminArea` (Task 2); `select_units`, `write_units`, `rasterize_units`, `unit_cells`, `Unit` (Task 3); `Search`, `Refined`, `pad_fn_for`, `half_diag` (Task 4); `refine`, `RoadCache`, `UtmRoads`, `utm_epsg`, `RefinedPole` (Task 5); `poles.grid.Frame`; `poles.classify.where_clause(scenario)`; `poles.poly.parse_poly`.
- Produces (attrib): `class Places(path: Path)` (loads `places.vrt` into memory once: lon/lat arrays, names, types; `.nearest(lon, lat) -> dict` with keys `name, type, dist_m, lat, lon`, geodesic over the 64 nearest by scaled planar distance, `name:en` preferred then `name`); `class Countries(areas: list[AdminArea])` (level-2 areas with a code, including non-units; `.code_at(lon, lat) -> str | None` lower-case, STRtree query then `contains`); `nearest_way(roads: UtmRoads, pole: RefinedPole, countries: Countries) -> dict` with keys `id, highway, name, ref, country` (country from the nearest point on the way to the pole, in lon/lat); `pole_record(rank, refined, way, place) -> dict` (the `Pole` shape: `rank, lat, lon, dist_m, nearest_way, nearest_place, detail: None, warnings: []`, coordinates rounded to 6 decimals, `dist_m` to 2).
- Produces (poles stage): `prepare(cfg, ws, log) -> Prepared` (idempotent sub-steps with `.ok` markers: `poles/countries.fgb` and `poles/units.fgb`, `poles/units.tif`, `poles/units.json`, `poles/roads/` tiles, `poles/land_idx.fgb`, `poles/water_big.fgb`); `search_unit(job: UnitJob) -> dict` (module-level for the process pool; returns `{unit, scenario, poles: [Pole...], reason, refinements, duration_s, top_coarse_m}`); `run(cfg, ws, log) -> dict` (writes `poles/A.json`, `poles/B.json` as `[{"unit", "poles", "reason"}]`, `poles/timing.json`; raises `PolesError` if any unit's top coarse value equals `max_distance_m`).
- `poles/units.json`: `{"units": [{"code", "name", "name_en", "osm_id", "country", "index", "area_km2", "cells", "transcontinental", "closed_by_edge", "bbox": [w, s, e, n]}]}`.

- [ ] **Step 1: Write the failing attribution tests**

`pipeline/tests/test_attrib.py`:

```python
import numpy as np
import pytest
from shapely.geometry import LineString, MultiPolygon, Point, box

from poles.attrib import Countries, Places, nearest_way, pole_record
from poles.boundaries import AdminArea
from poles.refine import RefinedPole, UtmRoads
from poles.roads import RoadSet
from tests.helpers import write_fgb


def test_places_nearest_is_geodesic_and_prefers_english_name(tmp_path):
    pts = [Point(23.50, 54.38), Point(23.60, 54.50), Point(24.0, 54.0)]
    fgb = write_fgb(tmp_path / "places.fgb", "places", pts, {
        "osm_id": [1, 2, 3], "name": ["Kaimas", "Miestelis", "Toli"], "name:en": [None, "Townlet", None],
        "place": ["village", "town", "city"], "population": [None, "1200", None]})
    places = Places(fgb, layer="places")
    near = places.nearest(23.55, 54.45)
    assert near["name"] == "Townlet" and near["type"] == "town"
    assert near["dist_m"] == pytest.approx(6430, rel=0.02) and (near["lat"], near["lon"]) == (54.5, 23.6)


def test_nearest_way_country_uses_all_countries_not_only_units():
    lt = AdminArea(1, 2, "LT", "Lietuva", "Lithuania", MultiPolygon([box(20, 53, 26.9, 56.5)]), True, False)
    ru = AdminArea(2, 2, "RU", "Россия", "Russia", MultiPolygon([box(26.9, 53, 40, 60)]), False, True)
    countries = Countries([lt, ru])
    assert countries.code_at(25.0, 54.5) == "lt" and countries.code_at(30.0, 55.0) == "ru" and countries.code_at(0, 0) is None
    road = LineString([(27.0, 54.0), (27.0, 55.0)])         # just inside RU
    rs = RoadSet(np.array([road], dtype=object), {"osm_id": np.array([9], dtype=object), "highway": np.array(["track"], dtype=object),
                                                   "name": np.array([None], dtype=object), "ref": np.array(["A-1"], dtype=object)})
    roads = UtmRoads(rs, 32635)
    pole = RefinedPole(54.5, 26.8, 13_000.0, 9, 0.0, 0.0, 32635, 0)
    way = nearest_way(roads, pole, countries)
    assert way == {"id": 9, "highway": "track", "name": None, "ref": "A-1", "country": "ru"}


def test_pole_record_shape():
    pole = RefinedPole(54.4414731, 23.5370201, 3425.567, 1385319417, 0, 0, 32635, 0)
    rec = pole_record(1, pole, {"id": 1385319417, "highway": "track", "name": None, "ref": None, "country": "lt"},
                      {"name": "Kumečiai", "type": "village", "dist_m": 3700.0, "lat": 54.47, "lon": 23.53})
    assert rec == {"rank": 1, "lat": 54.441473, "lon": 23.53702, "dist_m": 3425.57,
                   "nearest_way": {"id": 1385319417, "highway": "track", "name": None, "ref": None, "country": "lt"},
                   "nearest_place": {"name": "Kumečiai", "type": "village", "dist_m": 3700.0, "lat": 54.47, "lon": 23.53},
                   "detail": None, "warnings": []}
```

- [ ] **Step 2: Implement `poles/attrib.py`**

```python
"""Attribution of a refined pole: nearest way with its country, nearest settlement (spec 3.2 stage 5)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import shapely
from pyogrio.raw import read
from pyproj import Geod
from shapely.strtree import STRtree

from .boundaries import AdminArea
from .refine import RefinedPole, UtmRoads

GEOD = Geod(ellps="WGS84")


class Places:
    def __init__(self, path: Path, layer: str = "places"):
        meta, _, wkb, fields = read(str(path), layer=layer, columns=["name", "name:en", "place"])
        by = dict(zip(meta["fields"], fields))
        pts = shapely.from_wkb(wkb)
        self.lon = shapely.get_x(pts)
        self.lat = shapely.get_y(pts)
        self.name = np.where(np.asarray(by["name:en"], dtype=object) != None, by["name:en"], by["name"])  # noqa: E711
        self.kind = np.asarray(by["place"], dtype=object)

    def nearest(self, lon: float, lat: float, k: int = 64) -> dict | None:
        if len(self.lon) == 0:
            return None
        scale = np.cos(np.radians(lat))
        planar = ((self.lon - lon) * scale) ** 2 + (self.lat - lat) ** 2
        idx = np.argpartition(planar, min(k, len(planar) - 1))[:k]
        _, _, dist = GEOD.inv(np.full(len(idx), lon), np.full(len(idx), lat), self.lon[idx], self.lat[idx])
        j = idx[int(np.argmin(dist))]
        return {"name": self.name[j], "type": str(self.kind[j]), "dist_m": round(float(dist.min()), 1),
                "lat": round(float(self.lat[j]), 6), "lon": round(float(self.lon[j]), 6)}


class Countries:
    def __init__(self, areas: list[AdminArea]):
        self.areas = [a for a in areas if a.level == 2 and a.code]
        self.tree = STRtree([a.geometry for a in self.areas]) if self.areas else None

    def code_at(self, lon: float, lat: float) -> str | None:
        if self.tree is None:
            return None
        p = shapely.Point(lon, lat)
        for i in self.tree.query(p, predicate="intersects"):
            return self.areas[int(i)].code.lower()
        return None


def nearest_way(roads: UtmRoads, pole: RefinedPole, countries: Countries) -> dict:
    attrs = roads.roads.attrs
    i = pole.way_index
    way_utm = roads.geoms[i]
    on_way = shapely.shortest_line(way_utm, shapely.Point(pole.x, pole.y)).coords[0]
    lon, lat = roads.to_lonlat.transform(on_way[0], on_way[1])
    clean = lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else str(v)
    return {"id": int(attrs["osm_id"][i]), "highway": clean(attrs["highway"][i]), "name": clean(attrs["name"][i]),
            "ref": clean(attrs["ref"][i]), "country": countries.code_at(lon, lat)}


def pole_record(rank: int, pole: RefinedPole, way: dict, place: dict | None) -> dict:
    return {"rank": rank, "lat": round(pole.lat, 6), "lon": round(pole.lon, 6), "dist_m": round(pole.dist_m, 2),
            "nearest_way": way, "nearest_place": place, "detail": None, "warnings": []}
```

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_attrib.py -q` -> 3 passed. Commit: `git add pipeline/poles/attrib.py pipeline/tests/test_attrib.py && git commit -m "poles: nearest way with country from every level-2 area, nearest settlement by geodesic distance"`.

- [ ] **Step 3: Write the failing stage tests**

`pipeline/tests/test_poles_stage.py`:

```python
import json
import logging

import numpy as np
import pytest

from poles.poles import top_n_dedup, validate_poles_json


def _p(lat, lon, d):
    return {"rank": 0, "lat": lat, "lon": lon, "dist_m": d, "nearest_way": {"id": 1, "highway": "track", "name": None, "ref": None, "country": "lt"},
            "nearest_place": None, "detail": None, "warnings": []}


def test_top_n_dedup_10km():
    poles = [_p(54.0, 24.0, 5000), _p(54.05, 24.0, 4900), _p(54.5, 24.0, 4800), _p(55.0, 24.0, 4700)]  # 2nd is 5.6 km from 1st
    kept = top_n_dedup(poles, top_n=3, dedup_m=10_000)
    assert [p["dist_m"] for p in kept] == [5000, 4800, 4700] and [p["rank"] for p in kept] == [1, 2, 3]


def test_stage_output_schema():
    good = [{"unit": "lt", "poles": [_p(54.0, 24.0, 5000) | {"rank": 1}], "reason": None}]
    validate_poles_json(good, top_n=10)
    with pytest.raises(ValueError, match="rank"):
        validate_poles_json([{"unit": "lt", "poles": [_p(54.0, 24.0, 5000) | {"rank": 2}], "reason": None}], top_n=10)
    with pytest.raises(ValueError, match="reason"):
        validate_poles_json([{"unit": "lt", "poles": [], "reason": None}], top_n=10)
    with pytest.raises(ValueError, match="dist_m"):
        validate_poles_json([{"unit": "lt", "poles": [_p(54.0, 24.0, -1) | {"rank": 1}], "reason": None}], top_n=10)
```

- [ ] **Step 4: Implement `poles/poles.py`**

```python
"""Stage poles: units, road tiles, and one branch-and-bound search per unit and scenario (spec 3.2 stage 5)."""
from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
import shapely
from pyogrio.raw import read
from pyproj import Geod, Transformer
from rasterio.windows import Window, from_bounds
from shapely.ops import unary_union
from shapely.prepared import prep
from shapely.strtree import STRtree

from .attrib import Countries, Places, nearest_way, pole_record
from .boundaries import AdminArea, load_admin_areas
from .candidates import Refined, Search, half_diag, pad_fn_for
from .classify import where_clause
from .config import RegionConfig
from .errors import PolesError
from .extract import MARKER
from .grid import Frame
from .poly import parse_poly
from .refine import RoadCache, refine, utm_epsg
from .roads import RoadTiles, build_tiles
from .shell import require_tools, run_cmd
from .units import Unit, rasterize_units, select_units, unit_cells, write_units
from .workspace import Workspace

STAGE = "poles"
SCENARIOS = ("A", "B")
DEDUP_M = 10_000.0
MIN_WATER_M2 = 1_000_000.0
GEOD = Geod(ellps="WGS84")


def _done(path: Path) -> bool:
    return path.exists() and path.with_name(path.name + MARKER).exists()


def _mark(path: Path) -> None:
    path.with_name(path.name + MARKER).touch()


def _areas_to_fgb(areas: list[AdminArea], path: Path) -> None:
    from pyogrio.raw import write
    write(str(path), geometry=np.array([shapely.to_wkb(a.geometry) for a in areas], dtype=object),
          field_data=[np.array([a.osm_id for a in areas], dtype=np.int64), np.array([a.level for a in areas], dtype=np.int32),
                      np.array([a.code for a in areas], dtype=object), np.array([a.name_en for a in areas], dtype=object),
                      np.array([int(a.complete) for a in areas], dtype=np.int32), np.array([int(a.closed_by_edge) for a in areas], dtype=np.int32)],
          fields=["osm_id", "level", "code", "name_en", "complete", "closed_by_edge"], layer="countries", driver="FlatGeobuf",
          geometry_type="MultiPolygon", crs="EPSG:4326")


def load_countries(path: Path) -> list[AdminArea]:
    meta, _, wkb, fields = read(str(path), layer="countries")
    by = dict(zip(meta["fields"], fields))
    geoms = shapely.from_wkb(wkb)
    return [AdminArea(int(by["osm_id"][i]), int(by["level"][i]), by["code"][i], None, by["name_en"][i], geoms[i],
                      bool(by["complete"][i]), bool(by["closed_by_edge"][i])) for i in range(len(geoms))]


@dataclass
class Prepared:
    frame: Frame
    units: list[Unit]
    countries_fgb: Path
    roads_dir: Path
    units_tif: Path
    land_idx: Path
    water_big: Path


def prepare(cfg: RegionConfig, ws: Workspace, log: logging.Logger) -> Prepared:
    require_tools(["osmium", "ogr2ogr", "gdal_rasterize"])
    fetch_dir, extract_dir, grid_dir, out = ws.dir("fetch"), ws.dir("extract"), ws.dir("grid"), ws.dir(STAGE)
    tools_log = out / "tools.log"
    frame = Frame.from_dict(json.loads((grid_dir / "frame.json").read_text(encoding="utf-8")))
    snapshot = json.loads((fetch_dir / "snapshot.json").read_text(encoding="utf-8"))
    polys = {s["url"]: parse_poly(fetch_dir / s["poly"]) for s in snapshot["sources"]}
    primary = unary_union([polys[s["url"]] for s in snapshot["sources"] if s["role"] == "primary"])
    edge = unary_union(list(polys.values()))

    countries_fgb, units_fgb, units_json = out / "countries.fgb", out / "units.fgb", out / "units.json"
    if not (_done(countries_fgb) and _done(units_fgb)):
        levels = {2, cfg.unit_admin_level}
        areas = load_admin_areas(extract_dir / "boundaries.pbf", levels, edge, out / "boundaries", log,
                                 {2: "ISO3166-1", cfg.unit_admin_level: cfg.unit_code_tag})
        _areas_to_fgb(areas, countries_fgb)
        _mark(countries_fgb)
        units = select_units(areas, cfg, primary)
        write_units(units, units_fgb)
        _mark(units_fgb)
        log.info("units: %d (%s)", len(units), " ".join(u.code for u in units))
    else:
        units = _units_from_fgb(units_fgb, cfg)

    units_tif = out / "units.tif"
    if not _done(units_tif):
        counts = rasterize_units(units_fgb, frame, grid_dir / "land.tif", units_tif, log, out)
        cell_km2 = (frame.res / 1000.0) ** 2
        for u in units:
            u.cells = counts.get(u.index, 0)
            u.area_km2 = round(u.cells * cell_km2, 1)
        units_json.write_text(json.dumps({"units": [{
            "code": u.code, "name": u.name, "name_en": u.name_en, "osm_id": u.osm_id, "country": u.country, "index": u.index,
            "area_km2": u.area_km2, "cells": u.cells, "transcontinental": u.transcontinental, "closed_by_edge": u.closed_by_edge,
            "bbox": list(u.geometry.bounds)} for u in units]}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        _mark(units_tif)
    else:
        meta = {u["code"]: u for u in json.loads(units_json.read_text(encoding="utf-8"))["units"]}
        for u in units:
            u.cells, u.area_km2 = meta[u.code]["cells"], meta[u.code]["area_km2"]

    roads_dir = out / "roads"
    if not (roads_dir / "tiles.json").exists():
        build_tiles(extract_dir / "highways.vrt", "highways", roads_dir, log)

    land_idx = out / "land_idx.fgb"
    if not _done(land_idx):
        run_cmd(["ogr2ogr", "-f", "FlatGeobuf", land_idx, ws.shared_dir() / "land.vrt", "-nln", "land", "-lco", "SPATIAL_INDEX=YES"],
                log, stderr_path=tools_log)
        _mark(land_idx)
    water_big = out / "water_big.fgb"
    if not _done(water_big):
        run_cmd(["ogr2ogr", "-f", "FlatGeobuf", water_big, grid_dir / "water_proj.fgb", "-t_srs", "EPSG:4326", "-nln", "water",
                 "-sql", f"SELECT * FROM water WHERE OGR_GEOM_AREA >= {MIN_WATER_M2}", "-lco", "SPATIAL_INDEX=YES"],
                log, stderr_path=tools_log)
        _mark(water_big)
    return Prepared(frame, units, countries_fgb, roads_dir, units_tif, land_idx, water_big)


def _units_from_fgb(path: Path, cfg: RegionConfig) -> list[Unit]:
    meta, _, wkb, fields = read(str(path), layer="units")
    by = dict(zip(meta["fields"], fields))
    geoms = shapely.from_wkb(wkb)
    return [Unit(by["code"][i], None, by["name_en"][i], 0, by["country"][i], geoms[i], bool(by["transcontinental"][i]), int(by["idx"][i]))
            for i in range(len(geoms))]


@dataclass
class UnitJob:
    cfg: RegionConfig
    prepared: Prepared
    unit: Unit
    scenario: str
    dist_tif: Path
    top_n: int
    log_path: Path


def _allowed_factory(unit: Unit, land_idx: Path, water_big: Path) -> callable:
    """Point allowed when inside the unit, on a land polygon, and in no water polygon of 1 km2 or more."""
    w, s, e, n = unit.geometry.bounds
    pad = 0.05
    _, _, lwkb, _ = read(str(land_idx), layer="land", bbox=(w - pad, s - pad, e + pad, n + pad))
    _, _, wwkb, _ = read(str(water_big), layer="water", bbox=(w - pad, s - pad, e + pad, n + pad))
    land_tree = STRtree(shapely.from_wkb(lwkb)) if len(lwkb) else None
    water_tree = STRtree(shapely.from_wkb(wwkb)) if len(wwkb) else None
    unit_prep = prep(unit.geometry)

    def allowed(lons, lats):
        pts = shapely.points(lons, lats)
        ok = np.fromiter((unit_prep.contains(p) for p in pts), dtype=bool, count=len(pts))
        if land_tree is None:
            return np.zeros(len(pts), bool)
        on_land = np.zeros(len(pts), bool)
        on_land[np.unique(land_tree.query(pts, predicate="within")[0])] = True
        ok &= on_land
        if water_tree is not None:
            in_water = np.zeros(len(pts), bool)
            in_water[np.unique(water_tree.query(pts, predicate="within")[0])] = True
            ok &= ~in_water
        return ok

    return allowed


def search_unit(job: UnitJob) -> dict:
    t0 = time.monotonic()
    cfg, prep_, unit, scenario = job.cfg, job.prepared, job.unit, job.scenario
    frame = prep_.frame
    log = logging.getLogger(f"poles.unit.{unit.code}.{scenario}")
    with rasterio.open(prep_.units_tif) as units_ds, rasterio.open(job.dist_tif) as dist_ds:
        to_frame = Transformer.from_crs("EPSG:4326", frame.crs, always_xy=True)
        ring = shapely.segmentize(shapely.box(*unit.geometry.bounds).exterior, 0.1)
        fx, fy = to_frame.transform(*np.asarray(ring.coords).T)
        window = from_bounds(max(frame.x0, fx.min() - frame.res), max(frame.y0, fy.min() - frame.res),
                             min(frame.x1, fx.max() + frame.res), min(frame.y1, fy.max() + frame.res), frame.transform).round_offsets().round_lengths()
        u = units_ds.read(1, window=window)
        rows, cols = np.nonzero(u == unit.index)
        if len(rows) == 0:
            rows, cols = unit_cells(prep_.units_tif, unit, frame, log, prep_.units_tif.parent)
            rows, cols = rows - int(window.row_off), cols - int(window.col_off)
        dist = dist_ds.read(1, window=window)
    coarse = dist[rows, cols].astype(float)
    if len(coarse) == 0:
        raise PolesError(f"unit {unit.code}: no cells")
    top_coarse = float(coarse.max())
    if top_coarse >= cfg.max_distance_m:
        raise PolesError(f"unit {unit.code} scenario {scenario}: top coarse value {top_coarse} m is the saturation cap; raise max_distance_m")
    abs_rows, abs_cols = rows + int(window.row_off), cols + int(window.col_off)
    xs = frame.x0 + (abs_cols + 0.5) * frame.res
    ys = frame.y1 - (abs_rows + 0.5) * frame.res
    to_ll = Transformer.from_crs(frame.crs, "EPSG:4326", always_xy=True)
    lons, lats = to_ll.transform(xs, ys)
    pads = pad_fn_for(frame.crs)(np.asarray(lons), np.asarray(lats))

    tiles = RoadTiles(prep_.roads_dir)
    cache = RoadCache(tiles, where=where_clause(scenario))
    allowed = _allowed_factory(unit, prep_.land_idx, prep_.water_big)
    countries = Countries(load_countries(prep_.countries_fgb))
    hd = half_diag(frame.res)

    def refiner(i: int) -> Refined | None:
        radius_m = coarse_sorted[i] * 1.2 + 1000.0 + 2 * hd
        lon, lat = lon_sorted[i], lat_sorted[i]
        dlat = radius_m / 111_320.0
        dlon = dlat / max(0.05, np.cos(np.radians(lat)))
        epsg = utm_epsg(lon, lat)
        roads = cache.get(lon - dlon, lat - dlat, lon + dlon, lat + dlat, epsg)
        r = refine(x_sorted[i], y_sorted[i], frame.crs, roads, allowed=allowed)
        if r is None:
            return None
        fx, fy = to_frame.transform(r.lon, r.lat)
        return Refined(float(fx), float(fy), r.dist_m, (r, roads))

    search = Search(xs, ys, coarse, pads, frame.res, job.top_n, refiner, DEDUP_M, log=log)
    coarse_sorted, x_sorted, y_sorted = search.coarse, search.xs, search.ys
    lon_sorted, lat_sorted = np.asarray(lons)[search.order], np.asarray(lats)[search.order]
    result = search.run()

    places = Places(job.prepared.roads_dir.parent.parent / "extract" / "places.vrt")
    poles = []
    for rank, acc in enumerate(result.accepted, start=1):
        refined, roads = acc.payload
        poles.append(pole_record(rank, refined, nearest_way(roads, refined, countries), places.nearest(refined.lon, refined.lat)))
    reason = None
    if result.exhausted:
        reason = f"only {len(poles)} pole(s): every land cell of the unit lies within {DEDUP_M / 1000:.0f} km of them"
    return {"unit": unit.code, "scenario": scenario, "poles": poles, "reason": reason, "refinements": result.refinements,
            "warnings": result.warnings, "duration_s": round(time.monotonic() - t0, 1), "top_coarse_m": top_coarse}


def top_n_dedup(poles: list[dict], top_n: int, dedup_m: float = DEDUP_M) -> list[dict]:
    """Greedy top-n with geodesic dedup over already-refined poles (used by validation's re-runs and tests)."""
    kept: list[dict] = []
    for p in sorted(poles, key=lambda p: -p["dist_m"]):
        if all(GEOD.inv(p["lon"], p["lat"], q["lon"], q["lat"])[2] >= dedup_m for q in kept):
            kept.append(dict(p, rank=len(kept) + 1))
        if len(kept) == top_n:
            break
    return kept


def validate_poles_json(data: list[dict], top_n: int) -> None:
    for entry in data:
        if set(entry) != {"unit", "poles", "reason"}:
            raise ValueError(f"entry keys {sorted(entry)}")
        if len(entry["poles"]) < top_n and not entry["reason"]:
            raise ValueError(f"unit {entry['unit']}: fewer than {top_n} poles without a reason")
        for i, p in enumerate(entry["poles"], start=1):
            if p["rank"] != i:
                raise ValueError(f"unit {entry['unit']}: rank {p['rank']} at position {i}")
            if not (isinstance(p["dist_m"], (int, float)) and p["dist_m"] >= 0):
                raise ValueError(f"unit {entry['unit']}: bad dist_m {p['dist_m']}")
            if set(p["nearest_way"]) != {"id", "highway", "name", "ref", "country"}:
                raise ValueError(f"unit {entry['unit']}: nearest_way keys")
            if not (-90 <= p["lat"] <= 90 and -180 <= p["lon"] <= 180):
                raise ValueError(f"unit {entry['unit']}: coordinates")


def run(cfg: RegionConfig, ws: Workspace, log: logging.Logger) -> dict:
    prepared = prepare(cfg, ws, log)
    out, grid_dir = ws.dir(STAGE), ws.dir("grid")
    workers = int(os.environ.get("POLES_WORKERS", "0")) or 4
    jobs = [UnitJob(cfg, prepared, u, s, grid_dir / f"dist_{s}.tif", cfg.top_n, ws.base / "log.txt")
            for s in SCENARIOS for u in sorted(prepared.units, key=lambda u: -u.cells)]
    log.info("poles: %d jobs (%d units x %d scenarios) on %d workers", len(jobs), len(prepared.units), len(SCENARIOS), workers)
    results: list[dict] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for r in pool.map(search_unit, jobs):
            results.append(r)
            log.info("%s %s: %d poles, best %.0f m, %d refinements, %.0fs%s", r["unit"], r["scenario"], len(r["poles"]),
                     r["poles"][0]["dist_m"] if r["poles"] else 0, r["refinements"], r["duration_s"],
                     f" ({r['reason']})" if r["reason"] else "")
    timing = {}
    for s in SCENARIOS:
        entries = [{"unit": r["unit"], "poles": r["poles"], "reason": r["reason"]} for r in results if r["scenario"] == s]
        entries.sort(key=lambda e: e["unit"])
        validate_poles_json(entries, cfg.top_n)
        (out / f"{s}.json").write_text(json.dumps(entries, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        timing[s] = {r["unit"]: {"duration_s": r["duration_s"], "refinements": r["refinements"], "top_coarse_m": r["top_coarse_m"],
                                 "warnings": r["warnings"]} for r in results if r["scenario"] == s}
    (out / "timing.json").write_text(json.dumps(timing, indent=1) + "\n", encoding="utf-8")
    return {"units": len(prepared.units), "jobs": len(jobs), "workers": workers,
            "total_refinements": sum(r["refinements"] for r in results)}
```

Register the stage in `pipeline/poles/stages.py` (`from . import poles as poles_stage; reg["poles"] = poles_stage.run`). The `UnitJob` is pickled to workers: `RegionConfig`, `Prepared` (paths, `Frame`, units with shapely geometries) all pickle.

- [ ] **Step 5: Run the tests, suite, commit**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_poles_stage.py -q` -> 2 passed; full suite green; also `.venv/bin/poles run europe --snapshot 2026-08-19 --work ../work --stage poles --help` is not a thing, so check `.venv/bin/python -c "from poles.stages import registry; assert registry()['poles']"`.

```bash
git add pipeline/poles/poles.py pipeline/poles/stages.py pipeline/tests/test_poles_stage.py
git commit -m "poles: stage orchestrator, prepared inputs with markers, per-unit search in a process pool, A.json and B.json"
```

- [ ] **Step 6: First Europe run of the prepare step, count the units, set expected_units**

Run in the background (units and tiles first; the tiles may already exist from Task 1 step 8):

```bash
cd pipeline && export PATH=/opt/homebrew/bin:$PATH && nohup caffeinate -i .venv/bin/python -c "
import logging, sys
from poles.config import load_region
from poles.workspace import Workspace
from poles.logsetup import get_logger
from poles.poles import prepare
cfg = load_region('regions/europe.yaml'); ws = Workspace('../work', 'europe', '2026-08-19')
p = prepare(cfg, ws, get_logger(ws))
print('UNITS', len(p.units), ' '.join(f'{u.code}:{u.cells}' for u in p.units))
" > ../work/europe/2026-08-19/poles-prepare.log 2>&1 &
```

Review the list: `ru` absent, `tr` and `ge` present, `es fr nl no` present, no supplement country (am az iq sy ir), every unit has cells > 0 (microstates may be small). Then set `expected_units: <count>` in `pipeline/regions/europe.yaml` with a comment listing the date of the count, and post the code list to issue #8 as a comment. Commit: `git commit -m "europe: expected_units set from the stage-2 count"`.

- [ ] **Step 7: Lithuania first, then the full Europe run**

A single-unit dry run keeps the feedback loop short:

```bash
cd pipeline && export PATH=/opt/homebrew/bin:$PATH && .venv/bin/python -c "
import logging, sys, json
from pathlib import Path
from poles.config import load_region
from poles.workspace import Workspace
from poles.logsetup import get_logger
from poles.poles import prepare, UnitJob, search_unit
cfg = load_region('regions/europe.yaml'); ws = Workspace('../work', 'europe', '2026-08-19'); log = get_logger(ws)
p = prepare(cfg, ws, log)
lt = next(u for u in p.units if u.code == 'lt')
for s in 'AB':
    r = search_unit(UnitJob(cfg, p, lt, s, ws.dir('grid') / f'dist_{s}.tif', 10, ws.base / 'log.txt'))
    print(s, json.dumps(r['poles'][0], ensure_ascii=False), r['refinements'], r['duration_s'])
"
```

Expected: A about 3426 m near 54.4415 N 23.5370 E, B about 6675 m near 53.9958 N 24.4630 E (within 1% and 500 m of the published values; the snapshot is two days newer, so small changes are legitimate, large ones are a bug). Then the full stage in the background:

```bash
cd pipeline && export PATH=/opt/homebrew/bin:$PATH && POLES_WORKERS=4 nohup caffeinate -i .venv/bin/poles run europe --snapshot 2026-08-19 --work ../work --stage poles > ../work/europe/2026-08-19/poles-run.log 2>&1 &
```

Record per-unit timing from `poles/timing.json` (total wall clock, slowest units, total refinements, peak RSS from `done.json`) for Task 9.

---

### Task 7: Validation checks (task 2.5)

**Files:**
- Create: `pipeline/poles/validate/__init__.py` (empty for now; Task 8 fills it), `pipeline/poles/validate/checks.py`, `pipeline/poles/validate/refs.yaml`, `pipeline/tests/test_checks.py`

**Interfaces:**
- Consumes: `RoadTiles`/`RoadSet` (Task 1), `Unit` (Task 3), `Frame` (grid), `poles.classify.SET_A`, `SET_B`, `poles.poles.validate_poles_json`, `GEOD`.
- Produces: `@dataclass CheckResult(check: str, unit: str, scenario: str, passed: bool, blocking: bool, details: dict)` with `.to_dict()`; `PolesByScenario = dict[str, list[dict]]` (the parsed `A.json` / `B.json`); `recheck(poles, tiles, tolerance=0.005, log=None) -> list[CheckResult]` (check `recheck`); `membership(poles, units, land_idx: Path, water_big: Path) -> list[CheckResult]` (`membership`); `edge_bound(poles, edge: BaseGeometry) -> list[CheckResult]` (`edge_bound`); `grid_shift_compare(unit: str, scenario: str, original: dict, shifted: dict | None, move_m=500.0, rel=0.01) -> CheckResult` (`grid_shift`; the heavy rerun lives in Task 8); `holes(poles, road_masks: dict[str, Path], units_tif: Path, frame: Frame, units: list[Unit], top=3, seed=0) -> list[CheckResult]` (`holes`, never blocking); `references(poles, refs: dict) -> list[CheckResult]` (`reference`); `invariants(poles, units, cfg, grid_meta: dict) -> list[CheckResult]` (`invariant`, one result per invariant per unit or per region with unit `"*"`); `load_refs(path) -> dict`.
- Blocking: recheck, membership, edge_bound, grid_shift, invariant always; reference only for entries with `blocking: true`; holes never.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/test_checks.py`:

```python
import json

import numpy as np
import pytest
import rasterio
from pyproj import Geod
from shapely.geometry import LineString, MultiPolygon, box

from poles.config import RegionConfig, load_region
from poles.grid import Frame, create_raster
from poles.roads import RoadSet
from poles.units import Unit
from poles.validate.checks import (CheckResult, edge_bound, grid_shift_compare, holes, invariants, recheck, references)

GEOD = Geod(ellps="WGS84")


def _pole(lat, lon, d, rank=1, way=1):
    return {"rank": rank, "lat": lat, "lon": lon, "dist_m": d, "nearest_way": {"id": way, "highway": "track", "name": None, "ref": None, "country": "lt"},
            "nearest_place": None, "detail": None, "warnings": []}


class _Tiles:
    def __init__(self, lines, highway="track"):
        self.lines, self.highway = lines, highway
    def query(self, west, south, east, north, where=None):
        n = len(self.lines)
        return RoadSet(np.array(self.lines, dtype=object), {"osm_id": np.arange(1, n + 1).astype(object), "highway": np.array([self.highway] * n, dtype=object),
                                                            "name": np.array([None] * n, dtype=object), "ref": np.array([None] * n, dtype=object)})


def test_recheck_agrees_within_tolerance_on_synthetic():
    road = LineString([(23.5, 54.40), (23.6, 54.40)])          # along a parallel; the pole sits 2 km north of it
    lat = 54.40 + 2000 / 111_320 * 1.0
    true = GEOD.inv(23.55, lat, 23.55, 54.40)[2]
    results = recheck({"A": [{"unit": "lt", "poles": [_pole(lat, 23.55, true)], "reason": None}]}, _Tiles([road]))
    assert len(results) == 1 and results[0].passed and results[0].blocking and results[0].check == "recheck"
    assert results[0].details["geodesic_m"] == pytest.approx(true, abs=1.0)


def test_recheck_catches_planted_error():
    road = LineString([(23.5, 54.40), (23.6, 54.40)])
    lat = 54.40 + 2000 / 111_320
    true = GEOD.inv(23.55, lat, 23.55, 54.40)[2]
    results = recheck({"A": [{"unit": "lt", "poles": [_pole(lat, 23.55, true * 1.02)], "reason": None}]}, _Tiles([road]))
    assert not results[0].passed


def test_recheck_ignores_ways_outside_the_scenario():
    footway = LineString([(23.5, 54.41), (23.6, 54.41)])      # closer, but not drivable
    road = LineString([(23.5, 54.40), (23.6, 54.40)])
    lat = 54.40 + 2000 / 111_320
    true = GEOD.inv(23.55, lat, 23.55, 54.40)[2]
    class Mixed(_Tiles):
        def query(self, *a, **k):
            rs = super().query(*a, **k)
            rs.attrs["highway"] = np.array(["footway", "track"], dtype=object)
            return rs
    results = recheck({"A": [{"unit": "lt", "poles": [_pole(lat, 23.55, true)], "reason": None}]}, Mixed([footway, road]))
    assert results[0].passed


def test_edge_bound_fails_when_edge_closer_than_distance():
    edge = box(20.0, 50.0, 30.0, 60.0)
    near_edge = _pole(55.0, 29.9, 20_000)                      # about 6.4 km from lon 30
    inside = _pole(55.0, 25.0, 20_000)
    results = edge_bound({"A": [{"unit": "lt", "poles": [near_edge, inside], "reason": None}]}, edge)
    assert [r.passed for r in results] == [False, True] and all(r.blocking for r in results)
    assert results[0].details["edge_m"] == pytest.approx(6400, rel=0.05)


def test_grid_shift_compare():
    orig = _pole(54.0, 24.0, 5000)
    ok = grid_shift_compare("lt", "A", orig, _pole(54.001, 24.0, 5030))     # 111 m, 0.6%
    moved = grid_shift_compare("lt", "A", orig, _pole(54.006, 24.0, 5000))  # 667 m
    changed = grid_shift_compare("lt", "A", orig, _pole(54.0, 24.0, 5100))  # 2%
    lost = grid_shift_compare("lt", "A", orig, None)
    assert ok.passed and not moved.passed and not changed.passed and not lost.passed and ok.blocking


def _frame_and_rasters(tmp_path, doughnut: bool):
    frame = Frame("EPSG:3035", 250.0, 5_000_000.0, 3_600_000.0, 400, 400)  # 100 km square
    rng = np.random.default_rng(0)
    roads = (rng.uniform(size=(400, 400)) < 0.02).astype("uint8")
    if doughnut:
        rr, cc = np.mgrid[0:400, 0:400]
        d = np.hypot(rr - 200, cc - 200) * 250.0
        roads[d <= 10_000] = 0
        roads[(d > 10_000) & (d <= 30_000)] = (rng.uniform(size=roads.shape) < 0.1)[(d > 10_000) & (d <= 30_000)]
    road_tif = tmp_path / "roads_A.tif"
    create_raster(frame, road_tif)
    with rasterio.open(road_tif, "r+") as ds:
        ds.write(roads, 1)
    units_tif = tmp_path / "units.tif"
    create_raster(frame, units_tif, dtype="int16")
    with rasterio.open(units_tif, "r+") as ds:
        ds.write(np.ones((400, 400), dtype="int16"), 1)
    return frame, road_tif, units_tif


def test_hole_detector_flags_doughnut_and_passes_uniform(tmp_path):
    from pyproj import Transformer
    to_ll = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    lon, lat = to_ll.transform(5_000_000 + 200 * 250, 3_600_000 - 200 * 250)
    unit = Unit("uu", "U", "U", 1, "uu", MultiPolygon([box(lon - 1, lat - 1, lon + 1, lat + 1)]), False, 1)
    poles = {"A": [{"unit": "uu", "poles": [_pole(lat, lon, 12_000)], "reason": None}]}
    frame, road_tif, units_tif = _frame_and_rasters(tmp_path, doughnut=False)
    uniform = holes(poles, {"A": road_tif}, units_tif, frame, [unit])
    frame, road_tif, units_tif = _frame_and_rasters(tmp_path, doughnut=True)
    flagged = holes(poles, {"A": road_tif}, units_tif, frame, [unit])
    assert uniform[0].passed and not flagged[0].passed and not flagged[0].blocking
    assert flagged[0].details["inner_density"] == 0 and flagged[0].details["outer_density"] > flagged[0].details["unit_median_outer"]


def test_references_block_only_when_marked():
    refs = {"lt": {"A": {"lat": 54.441473, "lon": 23.537020, "dist_m": 3425.6, "source": "demo", "blocking": True}},
            "external": [{"unit": "lt", "scenario": "A", "name": "Some article", "lat": 54.44, "lon": 23.54, "dist_m": 3000, "source": "https://example.org", "note": "counts paths too"}]}
    good = {"A": [{"unit": "lt", "poles": [_pole(54.4416, 23.5372, 3430.0)], "reason": None}]}
    results = references(good, refs)
    assert [(r.passed, r.blocking) for r in results] == [(True, True), (True, False)]
    bad = {"A": [{"unit": "lt", "poles": [_pole(54.50, 23.5372, 3430.0)], "reason": None}]}   # 6.5 km away
    assert [r.passed for r in references(bad, refs)][0] is False


def test_a_le_b_invariant_detects_violation(regions_dir):
    cfg = RegionConfig(**(load_region(regions_dir / "europe.yaml").__dict__ | {"expected_units": 1, "top_n": 1}))
    unit = Unit("lt", "LT", "Lithuania", 1, "lt", MultiPolygon([box(20, 53, 27, 57)]), False, 1)
    poles = {"A": [{"unit": "lt", "poles": [_pole(54.0, 24.0, 5000)], "reason": None}],
             "B": [{"unit": "lt", "poles": [_pole(54.2, 24.0, 4000)], "reason": None}]}
    results = {r.details.get("name"): r for r in invariants(poles, [unit], cfg, {"a_le_b_violations": 0})}
    assert not results["a_le_b_poles"].passed and results["a_le_b_grid"].passed and results["unit_count"].passed
    assert results["top_n_or_reason"].passed and results["separation"].passed and all(r.blocking for r in results.values())


def test_results_mark_blocking_correctly():
    r = CheckResult("holes", "lt", "A", False, False, {})
    assert r.to_dict() == {"check": "holes", "unit": "lt", "scenario": "A", "passed": False, "blocking": False, "details": {}}
```

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_checks.py -q` -> ImportError.

- [ ] **Step 2: Implement `poles/validate/checks.py`**

```python
"""Validation checks 1 to 7 (spec 6). Each returns CheckResults; the stage decides what blocks."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import rasterio
import shapely
import yaml
from pyogrio.raw import read
from pyproj import Geod, Transformer
from shapely.geometry.base import BaseGeometry
from shapely.prepared import prep
from shapely.strtree import STRtree

from ..classify import SET_A, SET_B
from ..config import RegionConfig
from ..grid import Frame
from ..poles import DEDUP_M, validate_poles_json
from ..units import Unit

GEOD = Geod(ellps="WGS84")
DEG_PER_M = 1.0 / 111_320.0
INNER_KM, OUTER_KM = 10.0, 30.0
SETS = {"A": SET_A, "B": SET_B}


@dataclass
class CheckResult:
    check: str
    unit: str
    scenario: str
    passed: bool
    blocking: bool
    details: dict

    def to_dict(self) -> dict:
        return asdict(self)


def _iter(poles: dict[str, list[dict]]):
    for scenario, entries in poles.items():
        for entry in entries:
            for p in entry["poles"]:
                yield scenario, entry["unit"], p


def _bbox(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    dlat = radius_m * DEG_PER_M
    dlon = dlat / max(0.05, np.cos(np.radians(lat)))
    return lon - dlon, lat - dlat, lon + dlon, lat + dlat


def _geodesic_min(lon: float, lat: float, geoms, segment_m: float, chunk: int = 2000) -> tuple[float, int]:
    best, vertices = np.inf, 0
    for start in range(0, len(geoms), chunk):
        dense = shapely.segmentize(geoms[start:start + chunk], segment_m * DEG_PER_M)
        coords = shapely.get_coordinates(dense)
        vertices += len(coords)
        if len(coords):
            _, _, d = GEOD.inv(np.full(len(coords), lon), np.full(len(coords), lat), coords[:, 0], coords[:, 1])
            best = min(best, float(d.min()))
    return best, vertices


def recheck(poles, tiles, tolerance: float = 0.005, log: logging.Logger | None = None) -> list[CheckResult]:
    """Check 1: geodesic distance on the WGS84 ellipsoid to road vertices densified at 1 m, against every way of the
    scenario within twice the claimed distance, drawn from the highways tiles (all tags) and re-filtered here."""
    out = []
    for scenario, unit, p in _iter(poles):
        rs = tiles.query(*_bbox(p["lat"], p["lon"], 2 * p["dist_m"]))
        keep = np.array([h in SETS[scenario] for h in rs.attrs["highway"]], dtype=bool) if len(rs) else np.zeros(0, bool)
        geoms = rs.geoms[keep]
        d, vertices = _geodesic_min(p["lon"], p["lat"], geoms, 1.0)
        rel = abs(d - p["dist_m"]) / p["dist_m"] if p["dist_m"] > 0 else (0.0 if d == 0 else np.inf)
        passed = bool(np.isfinite(d) and rel <= tolerance)
        if log:
            log.info("recheck %s %s #%d: claimed %.1f m, geodesic %.1f m (%.3f%%), %d ways, %d vertices", unit, scenario, p["rank"], p["dist_m"], d, rel * 100, len(geoms), vertices)
        out.append(CheckResult("recheck", unit, scenario, passed, True,
                               {"rank": p["rank"], "claimed_m": p["dist_m"], "geodesic_m": round(d, 2) if np.isfinite(d) else None,
                                "relative_error": round(rel, 6) if np.isfinite(rel) else None, "ways": int(len(geoms)), "vertices": vertices}))
    return out


def membership(poles, units: list[Unit], land_idx: Path, water_big: Path) -> list[CheckResult]:
    """Check 2: inside the unit polygon, on a land polygon, in no water polygon of 1 km2 or more."""
    by_code = {u.code: prep(u.geometry) for u in units}
    out = []
    for scenario, unit, p in _iter(poles):
        pt = shapely.Point(p["lon"], p["lat"])
        tiny = (p["lon"] - 1e-6, p["lat"] - 1e-6, p["lon"] + 1e-6, p["lat"] + 1e-6)
        _, _, lwkb, _ = read(str(land_idx), layer="land", bbox=tiny)
        _, _, wwkb, _ = read(str(water_big), layer="water", bbox=tiny)
        in_unit = bool(by_code[unit].contains(pt))
        on_land = bool(np.any(shapely.contains(shapely.from_wkb(lwkb), pt))) if len(lwkb) else False
        in_water = bool(np.any(shapely.contains(shapely.from_wkb(wwkb), pt))) if len(wwkb) else False
        out.append(CheckResult("membership", unit, scenario, in_unit and on_land and not in_water, True,
                               {"rank": p["rank"], "in_unit": in_unit, "on_land": on_land, "in_water": in_water}))
    return out


def edge_bound(poles, edge: BaseGeometry) -> list[CheckResult]:
    """Check 3: the pole must be farther from the data edge than its claimed distance."""
    boundary = [g for g in (edge.boundary.geoms if hasattr(edge.boundary, "geoms") else [edge.boundary])]
    out = []
    for scenario, unit, p in _iter(poles):
        d, _ = _geodesic_min(p["lon"], p["lat"], np.array(boundary, dtype=object), 100.0)
        out.append(CheckResult("edge_bound", unit, scenario, bool(d > p["dist_m"]), True,
                               {"rank": p["rank"], "claimed_m": p["dist_m"], "edge_m": round(d, 1)}))
    return out


def grid_shift_compare(unit: str, scenario: str, original: dict, shifted: dict | None, move_m: float = 500.0, rel: float = 0.01) -> CheckResult:
    """Check 4: the winner recomputed on a half-cell shifted grid must stay within move_m and rel."""
    if shifted is None:
        return CheckResult("grid_shift", unit, scenario, False, True, {"rank": original["rank"], "reason": "no pole on the shifted grid"})
    moved = GEOD.inv(original["lon"], original["lat"], shifted["lon"], shifted["lat"])[2]
    change = abs(shifted["dist_m"] - original["dist_m"]) / original["dist_m"] if original["dist_m"] else 0.0
    return CheckResult("grid_shift", unit, scenario, bool(moved <= move_m and change <= rel), True,
                       {"rank": original["rank"], "moved_m": round(moved, 1), "relative_change": round(change, 6),
                        "original_m": original["dist_m"], "shifted_m": shifted["dist_m"]})


def _ring_density(mask: np.ndarray, row: int, col: int, r_in_cells: float, r_out_cells: float) -> float:
    r = int(np.ceil(r_out_cells))
    r0, r1 = max(0, row - r), min(mask.shape[0], row + r + 1)
    c0, c1 = max(0, col - r), min(mask.shape[1], col + r + 1)
    rr, cc = np.mgrid[r0:r1, c0:c1]
    d = np.hypot(rr - row, cc - col)
    ring = (d > r_in_cells) & (d <= r_out_cells)
    n = int(ring.sum())
    return float(mask[r0:r1, c0:c1][ring].sum()) / n if n else 0.0


def holes(poles, road_masks: dict[str, Path], units_tif: Path, frame: Frame, units: list[Unit], top: int = 3, seed: int = 0) -> list[CheckResult]:
    """Check 5: an empty 0-10 km ring with a 10-30 km ring denser than the unit's median is a probable import gap."""
    to_frame = Transformer.from_crs("EPSG:4326", frame.crs, always_xy=True)
    inner, outer = INNER_KM * 1000 / frame.res, OUTER_KM * 1000 / frame.res
    by_code = {u.code: u for u in units}
    rng = np.random.default_rng(seed)
    with rasterio.open(units_tif) as uds:
        unit_raster = uds.read(1)
    out = []
    for scenario, mask_path in road_masks.items():
        with rasterio.open(mask_path) as ds:
            mask = ds.read(1).astype(bool)
        medians: dict[str, float] = {}
        for entry in poles.get(scenario, []):
            unit = entry["unit"]
            if unit not in medians:
                rows, cols = np.nonzero(unit_raster == by_code[unit].index)
                pick = rng.choice(len(rows), size=min(200, len(rows)), replace=False) if len(rows) else []
                medians[unit] = float(np.median([_ring_density(mask, rows[i], cols[i], inner, outer) for i in pick])) if len(pick) else 0.0
            for p in entry["poles"][:top]:
                x, y = to_frame.transform(p["lon"], p["lat"])
                row, col = int((frame.y1 - y) // frame.res), int((x - frame.x0) // frame.res)
                inner_d = _ring_density(mask, row, col, -1, inner)
                outer_d = _ring_density(mask, row, col, inner, outer)
                flagged = inner_d == 0 and outer_d > medians[unit]
                out.append(CheckResult("holes", unit, scenario, not flagged, False,
                                       {"rank": p["rank"], "inner_density": inner_d, "outer_density": outer_d, "unit_median_outer": medians[unit]}))
    return out


def load_refs(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def references(poles, refs: dict) -> list[CheckResult]:
    """Check 6: regression against the published Lithuania poles (blocking) and cited national poles (informative)."""
    out = []
    winners = {(s, e["unit"]): e["poles"] for s, entries in poles.items() for e in entries}
    for unit, per_scenario in refs.items():
        if unit == "external":
            continue
        for scenario, ref in per_scenario.items():
            top = winners.get((scenario, unit), [])
            if not top:
                out.append(CheckResult("reference", unit, scenario, False, bool(ref.get("blocking")), {"reason": "no pole", "source": ref["source"]}))
                continue
            p = top[0]
            moved = GEOD.inv(ref["lon"], ref["lat"], p["lon"], p["lat"])[2]
            change = abs(p["dist_m"] - ref["dist_m"]) / ref["dist_m"]
            out.append(CheckResult("reference", unit, scenario, bool(moved <= 500 and change <= 0.01), bool(ref.get("blocking")),
                                   {"source": ref["source"], "ref_m": ref["dist_m"], "ours_m": p["dist_m"], "moved_m": round(moved, 1), "relative_change": round(change, 6)}))
    for ref in refs.get("external", []):
        cands = winners.get((ref["scenario"], ref["unit"]), [])
        if not cands:
            out.append(CheckResult("reference", ref["unit"], ref["scenario"], False, False, {"name": ref["name"], "source": ref["source"], "reason": "no pole"}))
            continue
        dists = [GEOD.inv(ref["lon"], ref["lat"], p["lon"], p["lat"])[2] for p in cands]
        k = int(np.argmin(dists))
        change = abs(cands[k]["dist_m"] - ref["dist_m"]) / ref["dist_m"] if ref.get("dist_m") else None
        out.append(CheckResult("reference", ref["unit"], ref["scenario"], bool(dists[k] <= 5000 and (change is None or change <= 0.2)), False,
                               {"name": ref["name"], "source": ref["source"], "note": ref.get("note"), "ref_m": ref.get("dist_m"),
                                "nearest_rank": cands[k]["rank"], "ours_m": cands[k]["dist_m"], "moved_m": round(dists[k], 1)}))
    return out


def invariants(poles, units: list[Unit], cfg: RegionConfig, grid_meta: dict) -> list[CheckResult]:
    """Check 7 (the stage-2 part): A <= B, top_n or a reason, 10 km separation, unit count, JSON structure."""
    out = []
    a = {e["unit"]: e for e in poles.get("A", [])}
    b = {e["unit"]: e for e in poles.get("B", [])}
    out.append(CheckResult("invariant", "*", "*", grid_meta.get("a_le_b_violations", 1) == 0, True, {"name": "a_le_b_grid", "violations": grid_meta.get("a_le_b_violations")}))
    for u in units:
        pa, pb = a.get(u.code, {}).get("poles", []), b.get(u.code, {}).get("poles", [])
        ok = (not pa or not pb) or pa[0]["dist_m"] <= pb[0]["dist_m"] + 0.01
        out.append(CheckResult("invariant", u.code, "*", ok, True, {"name": "a_le_b_poles", "A": pa[0]["dist_m"] if pa else None, "B": pb[0]["dist_m"] if pb else None}))
        for scenario, entries in (("A", a), ("B", b)):
            entry = entries.get(u.code)
            ok = entry is not None and (len(entry["poles"]) == cfg.top_n or bool(entry["reason"]))
            out.append(CheckResult("invariant", u.code, scenario, ok, True, {"name": "top_n_or_reason", "count": len(entry["poles"]) if entry else 0, "reason": entry["reason"] if entry else None}))
            ps = entry["poles"] if entry else []
            worst = min((GEOD.inv(p["lon"], p["lat"], q["lon"], q["lat"])[2] for i, p in enumerate(ps) for q in ps[i + 1:]), default=np.inf)
            out.append(CheckResult("invariant", u.code, scenario, bool(worst >= DEDUP_M), True, {"name": "separation", "min_m": None if worst == np.inf else round(worst, 1)}))
    expected = cfg.expected_units
    out.append(CheckResult("invariant", "*", "*", expected is None or len(units) == expected, True, {"name": "unit_count", "expected": expected, "found": len(units)}))
    for scenario in ("A", "B"):
        try:
            validate_poles_json(poles.get(scenario, []), cfg.top_n)
            out.append(CheckResult("invariant", "*", scenario, True, True, {"name": "structure"}))
        except (ValueError, KeyError, TypeError) as e:
            out.append(CheckResult("invariant", "*", scenario, False, True, {"name": "structure", "error": str(e)}))
    return out
```

- [ ] **Step 3: `refs.yaml`**

`pipeline/poles/validate/refs.yaml` holds the Lithuania regression entries (blocking) and three to five cited national poles (informative). The implementer must verify every external URL by fetching it (WebFetch) and must only keep entries whose page states a location and a distance; note the definitional difference in `note` (most studies measure distance to any road including paths, or to settlements, or use a different road set). Candidates to verify, replace any that do not check out: an Ordnance Survey article on Britain's most remote spot from a road (unit `gb`), a Sveriges Radio or Lantmäteriet item on Sweden's most remote point from a road (`se`), a Yle or Maanmittauslaitos item for Finland (`fi`), a Kartverket or Aftenposten item for Norway (`no`), a Geografía Infinita article for Spain (`es`). Shape:

```yaml
# Reference poles for check 6 (spec 6.6). Top-level unit codes hold blocking regression entries
# (the published Lithuania demo values); `external` entries inform and never block.
lt:
  A: {lat: 54.441473, lon: 23.537020, dist_m: 3425.6, source: "site/data/spots.json (LT demo, OSM 2026-08-17, EPSG:3346, 5 m grid)", blocking: true}
  B: {lat: 53.995818, lon: 24.462993, dist_m: 6674.6, source: "site/data/spots.json (LT demo, OSM 2026-08-17, EPSG:3346, 5 m grid)", blocking: true}
external:
  - unit: gb
    scenario: A
    name: "<title of the article>"
    lat: 0.0
    lon: 0.0
    dist_m: 0
    source: "<verified URL>"
    note: "<how their definition differs: road set, year, method>"
```

(Replace the placeholder numbers with the article's values; an entry without a stated distance may set `dist_m: null`, in which case only the position is compared.)

- [ ] **Step 4: Run the tests, suite, commit**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_checks.py -q` -> 10 passed.

```bash
git add pipeline/poles/validate/__init__.py pipeline/poles/validate/checks.py pipeline/poles/validate/refs.yaml pipeline/tests/test_checks.py
git commit -m "validate: checks 1 to 7 (geodesic recheck, membership, edge bound, grid-shift compare, hole detector, references, invariants) and refs.yaml"
```

---

### Task 8: Report, contact sheet, and the validate stage (task 2.6), then the Europe validation run

**Files:**
- Create: `pipeline/poles/validate/report.py`, `pipeline/tests/test_report.py`
- Modify: `pipeline/poles/validate/__init__.py` (the stage), `pipeline/poles/stages.py` (register `validate`)

**Interfaces:**
- Consumes: every check from Task 7; `prepare`, `search_unit`, `UnitJob`, `load_countries`, `top_n_dedup` (Task 6); `poles.grid.create_raster`, `rasterize`, `tiled_edt`, `build_land_mask`, `write_float_tif`, `Frame`; `rasterize_units` (Task 3); `PolesError`.
- Produces: `class ValidationFailed(PolesError)`; `write_report_json(results: list[CheckResult], path: Path, extra: dict | None = None) -> dict` (returns the summary: `{"blocking_failures", "warnings", "per_check": {check: {"passed", "failed"}}}`); `write_report_html(results, units: list[Unit], path: Path, title: str)`; `tile_xy(lon, lat, z) -> tuple[float, float]` (fractional slippy tile coordinates); `fetch_esri_tile(z: int, x: int, y: int) -> bytes` (HTTPS, 3 retries, 20 s timeout, a descriptive User-Agent); `write_contact_sheet(poles: dict[str, list[dict]], units: list[Unit], results: list[CheckResult], path: Path, fetch_tile=fetch_esri_tile, zoom: int = 13, title: str = "")` (one card per unit and scenario in unit order, a 3x3 tile mosaic of data URIs centred on the winner with a crosshair, the distance, nearest way, nearest place, and every non-passing `holes` or `reference` result for that unit and scenario as a warning line; Esri attribution in the footer); `validate.run(cfg, ws, log) -> dict` (writes `validate/report.json`, `report.html`, `contact-sheet.html`; raises `ValidationFailed` after writing them when any blocking result failed); `shifted_poles(cfg, ws, prepared, log) -> dict[tuple[str, str], dict | None]` (check 4's rerun: winner per (scenario, unit) on the half-cell shifted grid).

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/test_report.py`:

```python
import base64
import json
import re

import pytest
from shapely.geometry import MultiPolygon, box

from poles.units import Unit
from poles.validate.checks import CheckResult
from poles.validate.report import tile_xy, write_contact_sheet, write_report_html, write_report_json

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def _units():
    return [Unit("aa", "A", "Alpha", 1, "aa", MultiPolygon([box(0, 0, 1, 1)]), False, 1),
            Unit("bb", "B", "Beta", 2, "bb", MultiPolygon([box(2, 0, 3, 1)]), True, 2)]


def _pole(lat, lon, d):
    return {"rank": 1, "lat": lat, "lon": lon, "dist_m": d, "nearest_way": {"id": 5, "highway": "track", "name": "Miško kelias", "ref": None, "country": "aa"},
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
    assert "Alpha" in html and "Beta" in html and "1 blocking failure" in html and "—" not in html


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
    assert "Esri" in html and "—" not in html
```

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_report.py -q` -> ImportError.

- [ ] **Step 2: Implement `poles/validate/report.py`**

```python
"""report.json, report.html and contact-sheet.html for the validate stage (spec 6.8)."""
from __future__ import annotations

import base64
import html
import json
import math
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from ..units import Unit
from .checks import CheckResult

ESRI_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
ESRI_ATTRIBUTION = "Imagery: Esri, Maxar, Earthstar Geographics, and the GIS User Community"
USER_AGENT = "poles-pipeline contact sheet (validation review page)"
CSS = """body{font:14px/1.4 system-ui,sans-serif;margin:24px;color:#222;background:#fafafa}h1{font-size:20px}table{border-collapse:collapse}
td,th{border:1px solid #ccc;padding:4px 8px;text-align:left}.fail{background:#fdd}.warn{background:#ffe9b3}.ok{background:#e6f4e6}
.card{display:inline-block;vertical-align:top;margin:8px;padding:8px;border:1px solid #ccc;background:#fff;width:784px}
.mosaic{position:relative;width:768px;height:768px;display:grid;grid-template-columns:repeat(3,256px)}.mosaic img{display:block;width:256px;height:256px}
.cross{position:absolute;width:24px;height:24px;margin:-12px 0 0 -12px;border:2px solid #ff0;border-radius:50%;box-shadow:0 0 0 2px #000}
.meta{margin-top:6px}.warning{color:#a60;font-weight:600}footer{margin-top:24px;color:#666}"""


def write_report_json(results: list[CheckResult], path: Path, extra: dict | None = None) -> dict:
    per_check: dict[str, dict[str, int]] = {}
    for r in results:
        slot = per_check.setdefault(r.check, {"passed": 0, "failed": 0})
        slot["passed" if r.passed else "failed"] += 1
    summary = {"blocking_failures": sum(1 for r in results if r.blocking and not r.passed),
               "warnings": sum(1 for r in results if not r.blocking and not r.passed), "per_check": per_check}
    payload = {**(extra or {}), "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "summary": summary,
               "results": [r.to_dict() for r in results]}
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return summary


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def write_report_html(results: list[CheckResult], units: list[Unit], path: Path, title: str) -> None:
    blocking = [r for r in results if r.blocking and not r.passed]
    warnings = [r for r in results if not r.blocking and not r.passed]
    names = {u.code: u.name_en or u.code for u in units}
    rows = []
    for r in sorted(results, key=lambda r: (r.unit, r.scenario, r.check)):
        cls = "ok" if r.passed else ("fail" if r.blocking else "warn")
        rows.append(f'<tr class="{cls}"><td>{html.escape(names.get(r.unit, r.unit))}</td><td>{r.scenario}</td><td>{r.check}</td>'
                    f'<td>{"pass" if r.passed else ("FAIL" if r.blocking else "warning")}</td><td><code>{html.escape(json.dumps(r.details, ensure_ascii=False, default=str))}</code></td></tr>')
    page = (f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title><style>{CSS}</style><h1>{html.escape(title)}</h1>"
            f"<p>{_plural(len(blocking), 'blocking failure')}, {_plural(len(warnings), 'warning')}, {len(results)} results over {len(units)} units.</p>"
            f"<table><tr><th>Unit</th><th>Scenario</th><th>Check</th><th>Result</th><th>Details</th></tr>{''.join(rows)}</table>")
    path.write_text(page, encoding="utf-8")


def tile_xy(lon: float, lat: float, z: int) -> tuple[float, float]:
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n
    return x, y


def fetch_esri_tile(z: int, x: int, y: int) -> bytes:
    req = urllib.request.Request(ESRI_URL.format(z=z, x=x, y=y), headers={"User-Agent": USER_AGENT})
    last: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1 + attempt)
    raise RuntimeError(f"tile {z}/{x}/{y} failed three times: {last}")


def _km(d_m: float) -> str:
    return f"{d_m / 1000:.2f} km"


def _mosaic(lon: float, lat: float, zoom: int, fetch_tile) -> str:
    fx, fy = tile_xy(lon, lat, zoom)
    cx, cy = int(fx), int(fy)
    imgs = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            data = base64.b64encode(fetch_tile(zoom, cx + dx, cy + dy)).decode("ascii")
            imgs.append(f'<img src="data:image/png;base64,{data}" alt="">')
    px = (fx - cx + 1) * 256
    py = (fy - cy + 1) * 256
    return f'<div class="mosaic">{"".join(imgs)}<div class="cross" style="left:{px:.0f}px;top:{py:.0f}px"></div></div>'


def write_contact_sheet(poles: dict[str, list[dict]], units: list[Unit], results: list[CheckResult], path: Path,
                        fetch_tile=fetch_esri_tile, zoom: int = 13, title: str = "") -> None:
    entries = {(s, e["unit"]): e for s, es in poles.items() for e in es}
    flagged: dict[tuple[str, str], list[str]] = {}
    for r in results:
        if r.passed or r.check not in ("holes", "reference"):
            continue
        text = "probable import gap: no road within 10 km, dense roads 10 to 30 km out" if r.check == "holes" \
            else f"reference {r.details.get('name') or r.details.get('source')}: {json.dumps({k: v for k, v in r.details.items() if k in ('ref_m', 'ours_m', 'moved_m', 'note')}, ensure_ascii=False)}"
        flagged.setdefault((r.scenario, r.unit), []).append(text)
    cards = []
    for u in units:
        for s in sorted(poles):
            e = entries.get((s, u.code))
            head = f"<h2>{html.escape(u.name_en or u.code)} ({u.code}) scenario {s}</h2>"
            if not e or not e["poles"]:
                reason = html.escape((e or {}).get("reason") or "no poles")
                cards.append(f'<div class="card">{head}<p class="warning">{reason}</p></div>')
                continue
            p = e["poles"][0]
            way, place = p["nearest_way"], p["nearest_place"] or {}
            way_txt = " ".join(str(v) for v in (way.get("highway"), way.get("name") or way.get("ref")) if v)
            lines = [f"<b>{_km(p['dist_m'])}</b> from the nearest drivable way at {p['lat']:.5f}, {p['lon']:.5f}",
                     f"nearest way: {html.escape(way_txt)} (osm way {way['id']}, {way.get('country')})",
                     f"nearest place: {html.escape(str(place.get('name')))} ({place.get('type')}, {_km(place['dist_m']) if place else ''})"]
            for w in flagged.get((s, u.code), []):
                lines.append(f'<span class="warning">{html.escape(w)}</span>')
            cards.append(f'<div class="card">{head}{_mosaic(p["lon"], p["lat"], zoom, fetch_tile)}<div class="meta">{"<br>".join(lines)}</div></div>')
    page = (f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title><style>{CSS}</style><h1>{html.escape(title)}</h1>"
            f"{''.join(cards)}<footer>{ESRI_ATTRIBUTION}. Map data: OpenStreetMap contributors, ODbL.</footer>")
    path.write_text(page, encoding="utf-8")
```

- [ ] **Step 3: Implement the stage in `poles/validate/__init__.py`**

```python
"""Stage validate (spec 6): every published pole is re-derived by an independent path; any blocking failure stops the run."""
from __future__ import annotations

import json
import logging
import math
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np
import rasterio
from shapely.ops import unary_union

from ..config import RegionConfig
from ..errors import PolesError
from ..extract import MARKER
from ..grid import TILE, Frame, build_land_mask, create_raster, rasterize, tiled_edt, write_float_tif
from ..poles import SCENARIOS, UnitJob, Prepared, prepare, search_unit
from ..poly import parse_poly
from ..roads import RoadTiles
from ..units import rasterize_units
from ..workspace import Workspace
from . import checks
from .report import write_contact_sheet, write_report_html, write_report_json

STAGE = "validate"


class ValidationFailed(PolesError):
    pass


def _done(path: Path) -> bool:
    return path.exists() and path.with_name(path.name + MARKER).exists()


def shifted_poles(cfg: RegionConfig, ws: Workspace, prepared: Prepared, log: logging.Logger) -> dict[tuple[str, str], dict | None]:
    """Check 4: recompute the coarse grid half a cell off in both axes and re-run the search for each unit's top 3."""
    out, classify_dir, grid_dir = ws.dir(STAGE), ws.dir("classify"), ws.dir("grid")
    tools_log = out / "tools.log"
    f = prepared.frame
    shifted = Frame(f.crs, f.res, f.x0 + f.res / 2, f.y1 + f.res / 2, f.width, f.height)
    (out / "frame_shift.json").write_text(json.dumps(shifted.to_dict()) + "\n", encoding="utf-8")
    overlap = math.ceil(cfg.max_distance_m / cfg.coarse_res_m)
    workers = int(os.environ.get("POLES_WORKERS", "0")) or None
    for s in SCENARIOS:
        dist_tif = out / f"dist_{s}_shift.tif"
        if _done(dist_tif):
            continue
        mask_tif = out / f"roads_{s}_shift.tif"
        create_raster(shifted, mask_tif)
        rasterize(classify_dir / f"roads_{s}.fgb", f"roads_{s}", mask_tif, log, tools_log, burn=1, all_touched=True)
        with rasterio.open(mask_tif) as ds:
            mask = ds.read(1).astype(bool)
        dist = tiled_edt(mask, cfg.coarse_res_m, overlap, TILE, workers, max_m=float(cfg.max_distance_m))
        del mask
        write_float_tif(dist_tif, dist, shifted)
        del dist
        dist_tif.with_name(dist_tif.name + MARKER).touch()
    land_tif, units_tif = out / "land_shift.tif", out / "units_shift.tif"
    if not _done(units_tif):
        build_land_mask(ws.shared_dir() / "land.vrt", ws.dir("extract") / "water.vrt", shifted, land_tif, 1_000_000, log, out)
        rasterize_units(ws.dir("poles") / "units.fgb", shifted, land_tif, units_tif, log, out)
        units_tif.with_name(units_tif.name + MARKER).touch()
    prep_shift = replace(prepared, frame=shifted, units_tif=units_tif)
    jobs = [UnitJob(cfg, prep_shift, u, s, out / f"dist_{s}_shift.tif", 3, ws.base / "log.txt") for s in SCENARIOS for u in prepared.units]
    result: dict[tuple[str, str], dict | None] = {}
    with ProcessPoolExecutor(max_workers=int(os.environ.get("POLES_WORKERS", "0")) or 4) as pool:
        for r in pool.map(search_unit, jobs):
            result[(r["scenario"], r["unit"])] = r["poles"][0] if r["poles"] else None
            log.info("shifted %s %s: %s", r["unit"], r["scenario"], f"{r['poles'][0]['dist_m']:.0f} m" if r["poles"] else "no pole")
    (out / "shifted_winners.json").write_text(json.dumps({f"{s}/{u}": p for (s, u), p in result.items()}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def run(cfg: RegionConfig, ws: Workspace, log: logging.Logger) -> dict:
    out, poles_dir, grid_dir, fetch_dir = ws.dir(STAGE), ws.dir("poles"), ws.dir("grid"), ws.dir("fetch")
    prepared = prepare(cfg, ws, log)
    poles = {s: json.loads((poles_dir / f"{s}.json").read_text(encoding="utf-8")) for s in SCENARIOS}
    snapshot = json.loads((fetch_dir / "snapshot.json").read_text(encoding="utf-8"))
    edge = unary_union([parse_poly(fetch_dir / s["poly"]) for s in snapshot["sources"]])
    tiles = RoadTiles(prepared.roads_dir)
    results: list[checks.CheckResult] = []
    log.info("check 1: independent geodesic recheck")
    results += checks.recheck(poles, tiles, log=log)
    log.info("check 2: membership")
    results += checks.membership(poles, prepared.units, prepared.land_idx, prepared.water_big)
    log.info("check 3: data-edge bound")
    results += checks.edge_bound(poles, edge)
    log.info("check 4: half-cell grid shift")
    shifted = shifted_poles(cfg, ws, prepared, log)
    for s in SCENARIOS:
        for e in poles[s]:
            if e["poles"]:
                results.append(checks.grid_shift_compare(e["unit"], s, e["poles"][0], shifted.get((s, e["unit"]))))
    log.info("check 5: hole detection")
    results += checks.holes(poles, {s: grid_dir / f"roads_{s}.tif" for s in SCENARIOS}, prepared.units_tif, prepared.frame, prepared.units)
    log.info("check 6: references")
    results += checks.references(poles, checks.load_refs(Path(__file__).with_name("refs.yaml")))
    log.info("check 7: invariants")
    results += checks.invariants(poles, prepared.units, cfg, ws.meta("grid"))
    title = f"{cfg.name} validation, snapshot {ws.snapshot}"
    summary = write_report_json(results, out / "report.json", {"region": cfg.id, "snapshot": ws.snapshot})
    write_report_html(results, prepared.units, out / "report.html", title)
    log.info("contact sheet: fetching satellite tiles")
    write_contact_sheet(poles, prepared.units, results, out / "contact-sheet.html", title=f"{cfg.name} contact sheet, snapshot {ws.snapshot}")
    log.info("validation: %d blocking failures, %d warnings", summary["blocking_failures"], summary["warnings"])
    if summary["blocking_failures"]:
        failed = [r for r in results if r.blocking and not r.passed]
        raise ValidationFailed(f"{len(failed)} blocking validation failure(s); see {out / 'report.html'}. First: "
                               f"{failed[0].check} {failed[0].unit} {failed[0].scenario} {failed[0].details}")
    return {"summary": summary, "results": len(results)}
```

Register in `stages.py` (`from . import validate; reg["validate"] = validate.run`). Add to `test_report.py`:

```python
def test_stage_exit_code_nonzero_on_blocking_failure(tmp_path, monkeypatch, regions_dir):
    from poles import cli
    from poles.validate import ValidationFailed
    def boom(cfg, ws, log):
        raise ValidationFailed("2 blocking validation failure(s)")
    monkeypatch.setattr(cli, "registry", lambda: {"validate": boom})
    rc = cli.main(["run", "europe", "--stage", "validate", "--snapshot", "2026-01-01", "--work", str(tmp_path), "--regions-dir", str(regions_dir)])
    assert rc == 1
```

- [ ] **Step 4: Run the tests, suite, commit**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_report.py -q` -> 4 passed; full suite green.

```bash
git add pipeline/poles/validate/__init__.py pipeline/poles/validate/report.py pipeline/poles/stages.py pipeline/tests/test_report.py
git commit -m "validate: stage with the seven checks, half-cell grid-shift rerun, report.json, report.html and the satellite contact sheet"
```

- [ ] **Step 5: Run the Europe validation in the background**

Stop colima first (`colima stop`) so the shifted EDT has its memory. Then:

```bash
cd pipeline && export PATH=/opt/homebrew/bin:$PATH && POLES_WORKERS=4 nohup caffeinate -i .venv/bin/poles run europe --snapshot 2026-08-19 --work ../work --stage validate > ../work/europe/2026-08-19/validate-run.log 2>&1 &
```

When it ends: read `validate/report.json` summary; every blocking failure is either a real bug (fix it, rerun) or a documented data fact (recorded in the issue). Record wall clock and the per-check counts for Task 9. Open `validate/contact-sheet.html` once in a browser yourself (it is a local file) and eyeball three cards before posting for the owner.

---

### Task 9: Docs, spec numbers, issues

**Files:**
- Modify: `docs/DECISIONS.md` (new entry "2026-08-21: Stage 2 implementation decisions"), `docs/EUROPE_SPEC.md` (section 3.3 table: poles and validate rows; section 2.1 `expected_units`), `docs/OVERVIEW.md` (status, NEXT-UP stage 3), `CLAUDE.local.md` (not committed: the run commands and timings learned), `pipeline/README.md` (the two new stages in one sentence)
- GitHub: comments and closure on #15, #16, #8.

- [ ] **Step 1: DECISIONS entry**

Append to `docs/DECISIONS.md` an entry headed `## 2026-08-21: Stage 2 implementation decisions` that carries the nine items from "Decisions fixed by this plan" in prose, each with the measured numbers that justified it (the FlatGeobuf limit: 42.6 M features read correctly, 63.9 M did not, ceiling set at 40 M, tiles of 5 degrees; the relation counts behind the assembler; the bound correction with the 600 m example; any change made during execution, including every `Ruling:` line from the SDD ledger). No em dashes.

- [ ] **Step 2: Spec 3.3 and 2.1**

Add rows `poles` and `validate` to the table in spec 3.3 with wall clock, peak RSS (from `done.json`), and disk after; add a sentence with the unit count, total refinements, slowest unit, and the validation summary (blocking failures, warnings, check 1's worst relative error). Set the `expected_units` cell of the spec 2.1 table to the count.

- [ ] **Step 3: OVERVIEW**

Status paragraph: stage 2 done with the date; what exists (`poles/A.json`, `B.json`, `validate/report.html`, `contact-sheet.html`); Lithuania's reproduced numbers. NEXT-UP: Stage 3 (#9), label it, write its plan from `docs/EUROPE_PLAN.md` Stage 3, start with task 3.1; note that the road tiles under `poles/roads/` are the input for the detail rasters and that check 7's class-table and HEAD parts belong to stage 3.

- [ ] **Step 4: Issues**

- #15: comment with the assembler summary (relation counts, which countries are `closed_by_edge`), tick the three boxes, close.
- #16: comment with the measured limit table and the tile structure, tick the boxes (the third box: no upstream issue filed yet; say so and leave that box unticked but explain, or file it if time allows and link it), close.
- #8: comment with the evidence for every checklist box (test count, unit list, Lithuania numbers, validation summary, timing), the contact sheet's local path and a note that it will be on R2 under `validation/` after stage 3; flag the sheet for the owner's review; remove `in-progress`; close.
- File new issues for anything found on the way that is not fixed (for example: an upstream GDAL issue for the index limit; units with fewer than `top_n` poles; reference entries that could not be verified).

- [ ] **Step 5: Commit**

```bash
git add docs/DECISIONS.md docs/EUROPE_SPEC.md docs/OVERVIEW.md pipeline/README.md
git commit -m "Stage 2 close-out: decisions, spec 3.3 numbers, OVERVIEW next-up stage 3"
```

## Self-review against the spec

- Spec 2.2 units (countries at level 2, unit_countries, territory mask, clipped to land, ISO codes, Russia out, Turkey and Georgia in, microstates in): Task 3 plus Task 2; land via the raster AND (decision 5).
- Spec 2.4 exact poles, 5 m step, local UTM: Task 5. Spec 3.2 stage 5 branch-and-bound, STRtree within `coarse * 1.2 + 1 km`, 25 m then 5 m, top_n, 10 km dedup, nearest way with country, nearest settlement, unit membership: Tasks 4, 5, 6. The bound formula is corrected (decision 4).
- Spec 3.2 stage 6 and section 6 checks 1 to 8: Task 7 (1, 2, 3, 4's comparison, 5, 6, 7's stage-2 part) and Task 8 (4's rerun, report.json, report.html, contact sheet, non-zero exit). Check 7's class-table and HEAD parts: stage 3 (decision 8).
- Plan tasks 2.1 to 2.6 tests: every named test appears (`test_territory_mask_removes_island_but_keeps_mainland`, `test_level4_units_take_country_from_container`, `test_unit_count_mismatch_fails`, `test_unit_raster_assigns_each_cell_to_one_unit`, `test_never_prunes_planted_maximum`, `test_dedup_2km` is replaced by `test_dedup_and_dominance_give_top_n_at_least_dedup_apart` under decision 4, `test_pad_grows_with_distance_from_centre`, `test_single_straight_road_known_offset`, `test_two_roads_midpoint`, `test_utm_zone_selection_including_norway_exception_not_applied`, `test_result_nearest_way_id_matches_closest_geometry`, `test_nearest_way_country_uses_all_countries_not_only_units`, `test_top_n_dedup_10km`, `test_stage_output_schema`, `test_recheck_agrees_within_tolerance_on_synthetic`, `test_recheck_catches_planted_error`, `test_edge_bound_fails_when_edge_closer_than_distance`, `test_a_le_b_invariant_detects_violation`, `test_hole_detector_flags_doughnut_and_passes_uniform`, `test_results_mark_blocking_correctly`, `test_report_json_has_every_check_for_every_unit`, `test_stage_exit_code_nonzero_on_blocking_failure`, `test_contact_sheet_lists_every_unit_once_per_scenario`).
- Issues #15 and #16: Tasks 2 and 1, closed in Task 9 with the measured numbers.
- Type consistency: `RoadSet.attrs` keys are `osm_id, highway, name, ref` everywhere (Tasks 1, 5, 6, 7); `Refined.payload` carries `(RefinedPole, UtmRoads)` from Task 6's refiner to its attribution; `Prepared` fields match between `prepare`, `search_unit`, and `shifted_poles`; `CheckResult` fields match the shared interfaces.
