# Stage 3: Publish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `publish` stage to the pipeline: the validated poles and coarse grids of a region become two PMTiles explore layers (uint8 class index tiles, z0 to z9), one 50 m detail raster per published pole, the site JSON set (`regions.json`, `<region>/units.json`, `<region>/units/<code>.json`) and `manifest.json`, uploaded to an R2 bucket and HEAD-verified, in one `poles run <region> --stage publish` command; then run its local part on the Europe snapshot.

**Architecture:** The stage reads only finished stage outputs (`grid/`, `poles/`, `validate/`, `fetch/`) and works in `publish/` behind `.ok` markers, one sub-step per artefact. The coarse distance rasters are quantised with the shared class table into uint8 class rasters (water and everything outside the region's data become NODATA, cells within `edge_mask_m` of the data edge become EDGE), warped to Web Mercator at the z9 resolution, cut into a z0 to z9 PNG pyramid by `gdal raster tile` (nearest at z9, mode for the overviews), packed into MBTiles and converted with `pmtiles`. Detail rasters are exact vector distances on a 50 m lattice in the pole's UTM zone, computed from the stage-2 road tiles in a process pool. Validation's exclusions are applied before anything per pole is built (#21). R2 access is configured by environment variables whose secrets live in files outside the repo; without them the stage builds every local artefact and stops with an error that names what is missing, and a rerun resumes at the upload.

**Tech Stack:** Python 3.12, numpy, rasterio, shapely 2, pyproj, pyogrio, jsonschema (new), boto3 (new, R2's S3 API), moto (new, tests only), sqlite3 from the standard library (MBTiles), `urllib` (Cloudflare REST and HEAD checks); GDAL 3.13.3 `gdalwarp`, `gdal raster tile` and `pmtiles` 1.31.2 as subprocesses through `poles.shell.run_cmd`; plain ES module JavaScript for the site-side class table.

**Spec:** `docs/EUROPE_SPEC.md` sections 3.2 (stage 7), 3.4 (class table), 3.5 (detail rasters), 4.1 (R2 layout and sizes), 4.2 (site data contract), 5 (validation artefacts), 6 (check 7); `docs/EUROPE_PLAN.md` Stage 3 (tasks 3.1 to 3.7), "Global constraints" and "Shared interfaces". Deviations are recorded in `docs/DECISIONS.md` under "2026-08-22: Stage 3 implementation decisions" (Task 9 writes the entry; the decisions are listed in "Decisions fixed by this plan" below and bind every task).

## Global Constraints

- No em dashes anywhere: code, comments, docs, commit messages, issue text, JSON strings.
- No secrets in the repo. Credentials are read from files named by environment variables; nothing under the repo ever holds a token, and no committed file names a local path outside the repo. Nothing in code names Europe; `pipeline/regions/<region>.yaml` is the only place a region is described.
- Tests: real pytest, synthetic fixtures only, no network (R2 is mocked with moto and a local stub server; HEAD checks run against the `http_server` fixture in `pipeline/tests/conftest.py`, which supports `Range`).
- Identifiers: `<region>` lowercase slug; `<snapshot>` `YYYY-MM-DD`; unit codes lowercase ISO 3166-1 alpha-2 (`lt`) or ISO 3166-2 (`us-ak`); scenarios `A` and `B` (`poles.classify.SCENARIOS`).
- Stage functions: `run(cfg: RegionConfig, ws: Workspace, log: logging.Logger) -> dict | None`; idempotent; the runner writes `done.json`. Sub-steps are guarded by `<artefact>.ok` markers exactly like `poles.extract._ensure` and `poles.validate._clear_markers` (cleared when `ws.forced`), so a crash resumes at the first missing piece.
- R2 key layout (spec 4.1): `<region>/<snapshot>/A.pmtiles`, `B.pmtiles`, `detail/<code>/<scenario>-<rank>.png` and `.json`, `validation/report.json`, `validation/report.html`, `validation/contact-sheet.html`. Immutable: `Cache-Control: public, max-age=31536000, immutable`.
- Class table (spec 3.4): 50 m steps to 2.5 km (classes 0 to 49), 100 m to 10 km (50 to 124), 250 m to 30 km (125 to 204), 1 km to 60 km (205 to 234), 10 km to 230 km (235 to 252), 253 = 240 km and beyond, 254 = edge-masked (EDGE), 255 = nodata (NODATA). One definition in Python, one mirror in JavaScript, a test that compares them.
- Detail rasters (spec 3.5): `detail_res_m` (50 m) lattice over `detail_window_m` (20 km) centred on the pole, georeferenced in EPSG:4326 with `dlat` = res in degrees of latitude and `dlon` = `dlat / cos(lat)`, values are class indexes, sidecar JSON `{west, north, dlon, dlat, width, height}`.
- Branch `europe` only. Commit after every green task with explicit paths, identity Donatas / donatas.kasparavicius@gmail.com (repo-local override; verify with `git config user.email` before the first commit). Never `git add -A`. `site/data/` is written only by the pipeline and committed together with the code that produced it.
- Python: `pipeline/.venv`. Run tests as `cd pipeline && .venv/bin/python -m pytest -q` (234 tests green at the start of this plan). New dependencies go into `pipeline/requirements.txt` pinned to the version `uv pip install --python .venv/bin/python <name>` resolves; install with `uv pip install --python .venv/bin/python -r requirements.txt -e .`. CLI tools from `/opt/homebrew/bin`; `export PATH=/opt/homebrew/bin:$PATH` in every shell. `node` is on PATH for the JavaScript mirror check.
- Work data: `work/europe/2026-08-19/` holds fetch, extract, classify, grid, poles, validate with `done.json`; **do not recompute them**. New outputs go to `work/europe/2026-08-19/publish/`. Disk: 56 GiB free at planning time. Memory: 24 GB machine; run with colima stopped; `POLES_WORKERS=4`.
- Long runs: background under `caffeinate -i`, logs under the work directory, never block the session on them.

## Measured facts the plan relies on

- Grid frame (`grid/frame.json`): `{"crs": "EPSG:3035", "res": 250, "x0": 434000, "y1": 6821250, "width": 28588, "height": 23625}` (675 M cells). `dist_A.tif` and `dist_B.tif` are float32 without a nodata value, saturated cells are exactly `250000.0` (= `max_distance_m`), DEFLATE, 512 by 512 blocks. `land.tif` is uint8 (1 = land cell, water of 1 km2 or more removed). `poles.grid.Frame` (fields `crs, res, x0, y1, width, height`, properties `x1, y0, transform`, `from_dict`), `grid.create_raster(frame, path, dtype, nodata)`, `grid.rasterize(src, layer, target_tif, log, tools_log, *, burn, all_touched, sql)` (gdal_rasterize, reprojects the layer on the fly) and `grid.GTIFF_OPTS = dict(driver="GTiff", tiled=True, blockxsize=512, blockysize=512, compress="deflate", bigtiff="IF_SAFER")` exist.
- There is no edge-distance raster. Check 3 of validation builds the data edge as the `unary_union` of every source `.poly` in `fetch/` (`poles.poly.parse_poly(path)`, file names in `fetch/snapshot.json` under `sources[*].poly`). `fetch/snapshot.json` is `{"region", "snapshot", "created_at", "sources": [{"url", "role", "file", "size", "md5", "sha256", "last_modified", "poly"}]}`.
- Stage-2 outputs under `poles/`: `A.json` and `B.json` (list of 52 `{"unit", "poles", "reason"}` records, a pole is `{rank, lat, lon, dist_m, nearest_way{id, highway, name, ref, country}, nearest_place{name, type, dist_m, lat, lon}, detail: null, warnings: []}`), read with `poles.validate.load_poles(poles_dir, top_n) -> dict[str, list[dict]]`; `units.json` `{"units": [{code, name, name_en, osm_id, country, index, area_km2, cells, transcontinental, closed_by_edge, bbox, window}]}` (area_km2 there is cell-count based, #20); `units.fgb` (EPSG:4326, fields `code, name, name_en, osm_id, country, idx, transcontinental, closed_by_edge`); `land_idx.fgb` (layer `land`) and `water_big.fgb` (layer `water`); road tiles in `poles/roads/` (116 FlatGeobuf tiles on a 5 degree lattice plus `tiles.json`, 28.9 GB) read through `poles.roads.RoadTiles(out_dir).query(west, south, east, north, where=None, columns=None) -> RoadSet` (`RoadSet.geoms` is an object array of shapely lines in EPSG:4326). `poles.refine.UtmRoads(roads, epsg)` projects a RoadSet to a UTM zone (`.geoms`, `.tree` STRtree or None when empty, `.epsg`); `poles.refine.RoadCache(tiles, where, pad_deg).get(w, s, e, n, epsg)` reuses the previous query when the new bbox lies inside it; `poles.refine.utm_epsg(lon, lat) -> int`; `poles.classify.where_clause(scenario)`. Tests build a tile set with `poles.roads.build_tiles(src, layer, out_dir, log, tile_deg=...)` from a FlatGeobuf written by `tests/helpers.write_fgb`; see `tests/test_roads.py::_roads`.
- Validate outputs: `validate/report.json` `{"region", "snapshot", "excluded": [...], "generated_at", "summary", "results"}`; an exclusion is `{"unit": "ge", "scenario": "A", "rank": 1, "lat", "lon", "dist_m", "details"}` and the identifying triple is `(scenario, unit, rank)` against the rank in `poles/<scenario>.json`. Run 3 of record has 9 exclusions (ge A 1, 6, 7; es B 1; ge B 5, 6, 9, 10; is B 9). `validate/report.html` and `validate/contact-sheet.html` (10.9 MB) exist.
- Config (`poles.config.RegionConfig`): `id, name, coarse_crs, coarse_res_m, edge_mask_m (50000), max_distance_m (250000), top_n (10), detail_res_m (50), detail_window_m (20000), unit_admin_level (2), expected_units (52), class_table (None)`.
- Workspace: `ws.dir(stage) -> Path` (creates `work/<region>/<snapshot>/<stage>/`), `ws.is_done(stage)`, `ws.base`, `ws.region`, `ws.snapshot`, `ws.forced`. Runner (`poles/runner.py`) sets `ws.forced` and writes `done.json` with `duration_s`, `peak_rss_*`, `disk_bytes` merged with the stage's dict. `poles/stages.py` has `ORDER` with `publish` last and `registry()` returning `None` for it. `poles/cli.py` uses argparse (`build_parser`, subcommand `run`).
- `poles.shell`: `require_tools(names)`, `run_cmd(argv, log, *, cwd, env, stdin_path, stdout_path, stderr_path) -> CmdResult(argv, returncode, duration_s, max_rss_bytes)` (raises on non-zero exit with the captured stderr), `dir_size(path)`.
- Tools: `gdalwarp` and `gdal raster tile` (GDAL 3.13.3; `gdal raster tile --help` lists the tiling scheme, zoom range, resampling, overview resampling, `--no-alpha`, `--skip-blank`, `--convention xyz|tms`, `--resume`, output format and a directory output); `pmtiles convert <in.mbtiles> <out.pmtiles>` and `pmtiles show <archive>` (1.31.2). Web Mercator z9: `Z9_RES = 40075016.68557849 / (256 * 512) = 305.74811314070234` m per pixel, world extent `+-20037508.342789244`, which is exactly `65536 * Z9_RES`, so `gdalwarp -tap` at that resolution aligns to the tile grid.
- `pipeline/tests/conftest.py` provides `log`, `cfg` (the Europe config), `regions_dir`, `http_server` (yields `(base_url, docroot, requests)`; its handler answers `HEAD`, sends `Accept-Ranges: bytes` and serves `Range` requests with 206). `tests/helpers.write_fgb(path, layer, geoms, fields, crs, geometry_type)`.
- R2 is not enabled on the Cloudflare account yet (API code 10042) and the stage-2 session posted the enabling steps on #9. The upload and HEAD verification therefore run after the owner's "R2 ready"; every other deliverable of this plan is built and tested now.

## Decisions fixed by this plan

1. **Tiler.** The explore pyramid is produced by GDAL's own `gdal raster tile` (spec 3.2 names it), not by a custom Python tiler as plan task 3.2 sketched: `gdalwarp` first warps the class raster to EPSG:3857 at `Z9_RES` with `-tap` and nearest resampling, then `gdal raster tile` cuts z9 with nearest and builds z8 to z0 with mode resampling into a PNG directory (xyz convention, no alpha), a Python packer writes the directory into MBTiles (TMS rows, blank tiles dropped) and `pmtiles convert` produces the archive. Mode ties resolve however GDAL resolves them; EDGE is an ordinary class for the overviews. DECISIONS entry in Task 9.
2. **Edge mask.** The data edge is the union of every source `.poly` (the same polygon check 3 uses). Its boundary buffered by `edge_mask_m` in the coarse CRS is rasterized all-touched on the frame: land cells in that band become EDGE; cells outside the union (the frame's 250 km margin reaches into North Africa, the Middle East and Russia beyond the extract) and water cells become NODATA. Everything else is the class of its distance, saturated cells landing in class 253.
3. **Exclusions (#21).** `publish` refuses to run without `validate/done.json`. It drops every `(scenario, unit, rank)` triple in `report.json`'s `excluded` list from the poles, renumbers the remaining poles of that unit and scenario from 1, and records the number dropped as `withheld` in both `units.json` and the unit file. An exclusion that matches no pole is an error ("rerun validate"). Detail rasters are keyed by the published rank.
4. **Detail rasters.** Pixel centres on the EPSG:4326 lattice of spec 3.5 are projected to the pole's UTM zone (`refine.utm_epsg`) and measured against the roads of that scenario (`classify.where_clause`) with the STRtree nearest query; pixels not on land (the `land_idx.fgb` minus `water_big.fgb` rule of `poles._allowed_factory`, without the unit restriction, so a neighbour's land shows its distances too) are NODATA, pixels inside the edge band are EDGE. Roads are queried for the window padded by `dist_m + half diagonal + 1000 m`. PNGs are written with rasterio's PNG driver (no new image library); one sidecar JSON per raster with exactly the six spec fields.
5. **R2 configuration by environment.** `POLES_R2_ACCOUNT_ID`, `POLES_R2_BUCKET`, `POLES_R2_TOKEN_FILE` (Cloudflare API token with R2 admin read and write, used for bucket creation, the managed `r2.dev` domain and CORS through the REST API), `POLES_R2_ACCESS_KEY_ID_FILE` and `POLES_R2_SECRET_FILE` (the S3 credential pair for uploads), optional `POLES_R2_BASE` (the public base URL; when set it must equal the managed domain the API reports). Secrets are file contents, never values in the environment. Missing variables or files raise `PublishError` naming them, after the local artefacts are built, and leave no `done.json`, so the rerun resumes at the upload.
6. **CORS.** Origins `*`, methods `GET` and `HEAD`, headers `*`, exposed `Content-Length, Content-Range, ETag, Accept-Ranges`, max age 86400. The bucket is public read-only data; an origin list would only need editing again at the preview and custom-domain steps.
7. **Upload and verify.** Upload set: the two archives, `detail/**`, and the three validation files; keys prefixed `<region>/<snapshot>/`; content types by extension; an object whose size already matches is skipped; 8 parallel uploads. Verification: HEAD on every key answers 200, and a 16 KiB range GET on each archive answers 206 (spec check 7). The base URL is the managed `r2.dev` domain until stage 6 puts a custom domain in front; `regions.json` carries it as `r2_base`.
8. **Site JSON is written last**, after verification, into `publish/site/` and copied into the site directory (`--site-dir`, default `<repo>/site/data`, `--no-write-site` to skip). `regions.json` and `manifest.json` are merged per region id with whatever already exists in the target directory, so a second region adds itself. Every file is validated against the JSON schemas in `pipeline/poles/schemas/` before it is written; the schemas are the frozen contract of spec 4.2 and carry `additionalProperties: false` at the top level.
9. **Unit area (#20)** is the geodesic area of the unit polygon in `units.fgb` (`pyproj.Geod(ellps="WGS84").geometry_area_perimeter`, absolute value, km2 rounded to one decimal), which includes inland water like published country areas do. `units.json` in `poles/` keeps its cell-based figure; the site files carry the geodesic one.
10. **Regional rank** per scenario: units ordered by their published rank-1 distance descending, dense ranks from 1, ties broken by unit code; a unit with no published pole in a scenario has `null` for that scenario.
11. **JavaScript mirror.** `site/js/classes.js` is an ES module without DOM dependencies (also importable by node); `site/js/classes.test.html` is the hand-opened browser check; the pytest suite runs node on the module and compares the edges when node is on PATH, otherwise skips with a message.
12. **Run of record.** Task 8 runs the stage's local part on the Europe snapshot now and records the numbers in spec 4.1; the upload and verification run once the owner reports R2 ready, as a rerun of the same command with the environment set. #9 stays open with exactly those boxes until then.

## File structure

- `pipeline/poles/classes.py` (new): the class table. `site/js/classes.js` and `site/js/classes.test.html` (new): its mirror.
- `pipeline/poles/publish/__init__.py` (new): the stage, `run()`, sub-step markers, the upload set.
- `pipeline/poles/publish/raster.py` (new): edge masks, quantisation, warp to Web Mercator.
- `pipeline/poles/publish/tiles.py` (new): `gdal raster tile`, MBTiles packer, `pmtiles` convert and show.
- `pipeline/poles/publish/detail.py` (new): detail rasters in a process pool.
- `pipeline/poles/publish/sitedata.py` (new): exclusions, ranks, areas, the four JSON documents, schema validation, merge and write.
- `pipeline/poles/publish/r2.py` (new): configuration, REST bucket setup, S3 uploads, HEAD verification.
- `pipeline/poles/schemas/regions.schema.json`, `units.schema.json`, `unit.schema.json`, `manifest.schema.json` (new).
- `pipeline/poles/stages.py`, `pipeline/poles/cli.py`, `pipeline/poles/workspace.py` (modified): registration, `--site-dir`, `--no-write-site`.
- `pipeline/requirements.txt` (modified): jsonschema, boto3, moto. `pipeline/pyproject.toml` (modified if package data needs listing so `schemas/*.json` ship with the package).
- Tests: `pipeline/tests/test_classes.py`, `test_publish_raster.py`, `test_publish_tiles.py`, `test_publish_detail.py`, `test_publish_sitedata.py`, `test_publish_r2.py`, `test_publish_stage.py` (new).
- Docs: `docs/EUROPE_SPEC.md` 4.1 numbers, `docs/DECISIONS.md`, `docs/OVERVIEW.md`, `docs/LOG.md`, `pipeline/README.md`, `docs/EUROPE_PLAN.md` stage-3 checklist.

---

### Task 1: Class table in Python and JavaScript

**Files:**
- Create: `pipeline/poles/classes.py`
- Create: `site/js/classes.js`, `site/js/classes.test.html`
- Test: `pipeline/tests/test_classes.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `poles.classes.EDGE = 254`, `NODATA = 255`, `N_CLASSES = 254`, `default_edges() -> list[int]` (254 lower edges, first 0, last 240000), `class ClassTable(edges: list[int] | None = None)` with `.edges`, `.to_class(dist_m) -> np.ndarray[uint8]` (scalar or array input, raises `ValueError` on negative or NaN), `.lower(c) -> int`, `.upper(c) -> float` (`math.inf` for 253), `.mid(c) -> float`. JS: `CLASS_EDGES`, `EDGE`, `NODATA`, `toClass(distM)`, `classLower(c)`, `classUpper(c)`.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/test_classes.py`:

```python
import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from poles.classes import EDGE, N_CLASSES, NODATA, ClassTable, default_edges

REPO = Path(__file__).resolve().parents[2]

BREAKPOINTS = [(0, 0), (49, 0), (50, 1), (2499, 49), (2500, 50), (9999, 124), (10000, 125), (29999, 204),
               (30000, 205), (59999, 234), (60000, 235), (239999, 252), (240000, 253), (250000, 253)]


def test_default_edges_shape():
    e = default_edges()
    assert len(e) == N_CLASSES == 254
    assert e[0] == 0 and e[-1] == 240000
    assert all(b > a for a, b in zip(e, e[1:]))
    assert EDGE == 254 and NODATA == 255


@pytest.mark.parametrize("dist,expected", BREAKPOINTS)
def test_breakpoints(dist, expected):
    assert int(ClassTable().to_class(dist)) == expected


def test_to_class_is_vectorised_uint8():
    out = ClassTable().to_class(np.array([0.0, 75.0, 250000.0], dtype=np.float32))
    assert out.dtype == np.uint8
    assert out.tolist() == [0, 1, 253]


def test_bounds_and_mid():
    t = ClassTable()
    assert t.lower(50) == 2500 and t.upper(50) == 2600 and t.mid(50) == 2550
    assert t.upper(253) == math.inf and t.lower(253) == 240000
    assert t.mid(0) == 25


def test_rejects_bad_inputs():
    with pytest.raises(ValueError):
        ClassTable().to_class(-1)
    with pytest.raises(ValueError):
        ClassTable([0, 10, 5] + [20 + i for i in range(251)])
    with pytest.raises(ValueError):
        ClassTable(list(range(10)))


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH; the JS mirror is checked by hand")
def test_js_mirror_matches_python():
    module = (REPO / "site" / "js" / "classes.js").as_uri()
    script = (f"import {{CLASS_EDGES, EDGE, NODATA, toClass}} from '{module}';"
              f"console.log(JSON.stringify({{edges: CLASS_EDGES, edge: EDGE, nodata: NODATA,"
              f" classes: {json.dumps([d for d, _ in BREAKPOINTS])}.map(toClass)}}))")
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
    got = json.loads(out.stdout)
    assert got["edges"] == default_edges()
    assert got["edge"] == EDGE and got["nodata"] == NODATA
    assert got["classes"] == [c for _, c in BREAKPOINTS]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_classes.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'poles.classes'`.

- [ ] **Step 3: Write the Python table**

`pipeline/poles/classes.py`:

```python
"""Distance class table shared by the explore tiles, the detail rasters and the site (spec 3.4).

Class c covers [edges[c], edges[c+1]) metres; the last real class, 253, is open-ended. Two reserved values
sit above the real classes: EDGE for cells whose distance is only a lower bound because the data ends within
edge_mask_m of them, NODATA for water and everything outside the region's data. site/js/classes.js mirrors
this file; tests/test_classes.py compares the two."""
from __future__ import annotations

import math

import numpy as np

EDGE = 254
NODATA = 255
N_CLASSES = 254  # real classes 0..253


def default_edges() -> list[int]:
    edges = list(range(0, 2_500, 50))                # 50 m steps to 2.5 km: classes 0..49
    edges += list(range(2_500, 10_000, 100))         # 100 m steps to 10 km: classes 50..124
    edges += list(range(10_000, 30_000, 250))        # 250 m steps to 30 km: classes 125..204
    edges += list(range(30_000, 60_000, 1_000))      # 1 km steps to 60 km: classes 205..234
    edges += list(range(60_000, 240_000, 10_000))    # 10 km steps to 240 km: classes 235..252
    edges.append(240_000)                            # class 253: 240 km and beyond
    return edges


class ClassTable:
    def __init__(self, edges: list[int] | None = None):
        e = [int(v) for v in (edges if edges is not None else default_edges())]
        if len(e) != N_CLASSES:
            raise ValueError(f"class table needs {N_CLASSES} lower edges, got {len(e)}")
        if e[0] != 0 or any(b <= a for a, b in zip(e, e[1:])):
            raise ValueError("class edges must start at 0 and increase strictly")
        self.edges = e
        self._arr = np.asarray(e, dtype=np.float64)

    def to_class(self, dist_m) -> np.ndarray:
        d = np.asarray(dist_m, dtype=np.float64)
        if np.any(np.isnan(d)) or np.any(d < 0):
            raise ValueError("distances must be finite and non-negative")
        return (np.searchsorted(self._arr, d, side="right") - 1).astype(np.uint8)

    def lower(self, c: int) -> int:
        return self.edges[c]

    def upper(self, c: int) -> float:
        return float(self.edges[c + 1]) if c + 1 < N_CLASSES else math.inf

    def mid(self, c: int) -> float:
        hi = self.upper(c)
        return (self.lower(c) + hi) / 2 if hi != math.inf else float(self.lower(c))
```

- [ ] **Step 4: Write the JavaScript mirror and its page**

`site/js/classes.js`:

```js
// Distance class table, the mirror of pipeline/poles/classes.py (spec 3.4). Keep both in step: the
// pipeline test suite compares them whenever node is on PATH.
export const EDGE = 254;
export const NODATA = 255;

function range(start, stop, step) {
  const out = [];
  for (let v = start; v < stop; v += step) out.push(v);
  return out;
}

export const CLASS_EDGES = [
  ...range(0, 2500, 50),
  ...range(2500, 10000, 100),
  ...range(10000, 30000, 250),
  ...range(30000, 60000, 1000),
  ...range(60000, 240000, 10000),
  240000,
];

// Class of a distance in metres: the last edge not above it.
export function toClass(distM) {
  if (!(distM >= 0)) throw new RangeError('distance must be a non-negative number');
  let lo = 0;
  let hi = CLASS_EDGES.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (CLASS_EDGES[mid] <= distM) lo = mid + 1; else hi = mid;
  }
  return lo - 1;
}

export function classLower(c) { return CLASS_EDGES[c]; }
export function classUpper(c) { return c + 1 < CLASS_EDGES.length ? CLASS_EDGES[c + 1] : Infinity; }
```

`site/js/classes.test.html` (open in a browser by hand; no framework):

```html
<!doctype html>
<meta charset="utf-8">
<title>classes.js check</title>
<pre id="out"></pre>
<script type="module">
  import { CLASS_EDGES, EDGE, NODATA, toClass, classUpper } from './classes.js';
  const cases = [[0, 0], [49, 0], [50, 1], [2499, 49], [2500, 50], [9999, 124], [10000, 125], [29999, 204],
    [30000, 205], [59999, 234], [60000, 235], [239999, 252], [240000, 253], [250000, 253]];
  const lines = [];
  let ok = CLASS_EDGES.length === 254 && CLASS_EDGES[0] === 0 && CLASS_EDGES[253] === 240000
    && EDGE === 254 && NODATA === 255 && classUpper(253) === Infinity;
  lines.push(`edges ${CLASS_EDGES.length}, first ${CLASS_EDGES[0]}, last ${CLASS_EDGES[253]}`);
  for (const [d, c] of cases) {
    const got = toClass(d);
    if (got !== c) ok = false;
    lines.push(`${d} m -> class ${got} (expected ${c})`);
  }
  lines.unshift(ok ? 'PASS' : 'FAIL');
  document.getElementById('out').textContent = lines.join('\n');
</script>
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_classes.py -q`
Expected: all pass including `test_js_mirror_matches_python` (node present). Also run `node --input-type=module -e "import('file://$PWD/../site/js/classes.js').then(m => console.log(m.CLASS_EDGES.length, m.toClass(240000)))"` from `pipeline/`: prints `254 253`.

- [ ] **Step 6: Commit**

```bash
git add pipeline/poles/classes.py pipeline/tests/test_classes.py site/js/classes.js site/js/classes.test.html
git commit -m "publish: distance class table in Python with its JavaScript mirror and a cross-check test (spec 3.4)"
```

---

### Task 2: Explore class rasters

**Files:**
- Create: `pipeline/poles/publish/__init__.py` (empty module docstring only; Task 7 fills it), `pipeline/poles/publish/raster.py`
- Test: `pipeline/tests/test_publish_raster.py`

**Interfaces:**
- Consumes: `poles.classes.ClassTable, EDGE, NODATA`; `poles.grid.Frame, create_raster, rasterize, GTIFF_OPTS`; `poles.poly.parse_poly`; `poles.shell.run_cmd`.
- Produces:
  - `Z9_RES = 40075016.68557849 / (256 * 512)`, `MERC_MAX = 20037508.342789244`.
  - `edge_polygon(fetch_dir: Path) -> BaseGeometry`: union of every `.poly` named in `fetch/snapshot.json`, EPSG:4326.
  - `edge_masks(edge_4326, frame: Frame, edge_mask_m: float, out_dir: Path, log, tools_log) -> tuple[Path, Path]`: writes and returns `out_dir/inside.tif` (1 inside the edge polygon) and `out_dir/edgeband.tif` (1 within `edge_mask_m` of its boundary), both uint8 on the frame; also writes `out_dir/edgeband_4326.wkb` (the band transformed back to EPSG:4326, for the detail rasters). Guarded by `.ok` markers on the two rasters.
  - `quantise(dist_tif: Path, land_tif: Path, inside_tif: Path, band_tif: Path, out_tif: Path, table: ClassTable, log) -> dict` with `{"cells": n, "nodata": n, "edge": n, "classed": n}`.
  - `warp_to_mercator(src_tif: Path, out_tif: Path, log, tools_log) -> Path`: gdalwarp to EPSG:3857 at `Z9_RES`, `-tap`, nearest, nodata 255, extent clamped to `+-MERC_MAX`.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/test_publish_raster.py`:

```python
import json
from pathlib import Path

import numpy as np
import rasterio
import shapely
from shapely.geometry import box

from poles.classes import EDGE, NODATA, ClassTable
from poles.grid import Frame, create_raster
from poles.publish import raster

# A small frame in EPSG:3035 around 24E 55N (Lithuania). 250 m cells.
FRAME = Frame(crs="EPSG:3035", res=250, x0=5_300_000, y1=3_660_000, width=40, height=32)


def _write(path: Path, data: np.ndarray, dtype: str, nodata=None):
    create_raster(FRAME, path, dtype, nodata)
    with rasterio.open(path, "r+") as ds:
        ds.write(data.astype(dtype), 1)


def test_quantise_applies_table_and_masks(tmp_path, log):
    dist = np.full((32, 40), 75.0, dtype=np.float32)       # class 1
    dist[0, :] = 250_000.0                                 # saturated: class 253
    dist[1, :] = 2_500.0                                   # class 50
    land = np.ones((32, 40), dtype=np.uint8)
    land[:, 0] = 0                                         # water column
    inside = np.ones((32, 40), dtype=np.uint8)
    inside[:, 39] = 0                                      # outside the data
    band = np.zeros((32, 40), dtype=np.uint8)
    band[31, :] = 1                                        # edge band row
    for name, arr, dt in [("dist", dist, "float32"), ("land", land, "uint8"), ("inside", inside, "uint8"), ("band", band, "uint8")]:
        _write(tmp_path / f"{name}.tif", arr, dt)
    out = tmp_path / "explore.tif"
    stats = raster.quantise(tmp_path / "dist.tif", tmp_path / "land.tif", tmp_path / "inside.tif", tmp_path / "band.tif",
                            out, ClassTable(), log)
    with rasterio.open(out) as ds:
        assert ds.nodatavals == (NODATA,) and ds.dtypes == ("uint8",) and ds.crs.to_string() == "EPSG:3035"
        cls = ds.read(1)
    assert cls[5, 5] == 1 and cls[0, 5] == 253 and cls[1, 5] == 50
    assert (cls[:, 0] == NODATA).all() and (cls[:, 39] == NODATA).all()
    assert cls[31, 5] == EDGE and cls[31, 0] == NODATA          # nodata wins over the band
    assert stats == {"cells": 32 * 40, "nodata": 64, "edge": 38, "classed": 32 * 40 - 64 - 38}


def test_edge_masks_band_hugs_the_boundary(tmp_path, log):
    # Edge polygon: the middle of the frame, as lon/lat. Band 1 km wide: a thin ring inside and outside it.
    from pyproj import Transformer
    to_ll = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    poly_3035 = box(FRAME.x0 + 2_000, FRAME.y0 + 2_000, FRAME.x1 - 2_000, FRAME.y1 - 2_000)
    edge_4326 = shapely.transform(poly_3035, lambda c: np.column_stack(to_ll.transform(c[:, 0], c[:, 1])))
    inside_tif, band_tif = raster.edge_masks(edge_4326, FRAME, 1_000, tmp_path, log, tmp_path / "tools.log")
    with rasterio.open(inside_tif) as ds:
        inside = ds.read(1)
    with rasterio.open(band_tif) as ds:
        band = ds.read(1)
    assert inside[16, 20] == 1 and inside[0, 0] == 0 and inside[31, 39] == 0
    assert band[16, 20] == 0                     # frame centre is 4 km from the boundary
    assert band[8, 20] == 1 and band[6, 20] == 1  # rows 7..8 straddle the northern boundary (y = y1 - 2 km)
    assert band[13, 20] == 0 and band[16, 20] == 0
    assert (tmp_path / "edgeband_4326.wkb").exists()
    assert (tmp_path / "inside.tif.ok").exists() and (tmp_path / "edgeband.tif.ok").exists()
    ring = shapely.from_wkb((tmp_path / "edgeband_4326.wkb").read_bytes())
    assert ring.contains(shapely.Point(to_ll.transform(FRAME.x0 + 2_000, FRAME.y0 + 4_000)))


def test_edge_polygon_unions_every_source(tmp_path):
    (tmp_path / "a.poly").write_text("a\n1\n  10 50\n  12 50\n  12 52\n  10 52\nEND\nEND\n")
    (tmp_path / "b.poly").write_text("b\n1\n  11 51\n  13 51\n  13 53\n  11 53\nEND\nEND\n")
    (tmp_path / "snapshot.json").write_text(json.dumps({"sources": [{"poly": "a.poly"}, {"poly": "b.poly"}]}))
    geom = raster.edge_polygon(tmp_path)
    assert geom.contains(shapely.Point(10.5, 50.5)) and geom.contains(shapely.Point(12.5, 52.5))
    assert abs(geom.area - 7.0) < 1e-9


def test_warp_to_mercator_is_tile_aligned(tmp_path, log):
    cls = np.random.default_rng(1).integers(0, 254, size=(32, 40), dtype=np.uint8)
    cls[:, 0] = NODATA
    _write(tmp_path / "explore.tif", cls, "uint8", nodata=NODATA)
    out = raster.warp_to_mercator(tmp_path / "explore.tif", tmp_path / "explore_3857.tif", log, tmp_path / "tools.log")
    with rasterio.open(out) as ds:
        assert ds.crs.to_string() == "EPSG:3857" and ds.nodatavals == (NODATA,) and ds.dtypes == ("uint8",)
        assert abs(ds.res[0] - raster.Z9_RES) < 1e-9 and abs(ds.res[1] - raster.Z9_RES) < 1e-9
        x0, y1 = ds.transform.c, ds.transform.f
        assert abs((x0 + raster.MERC_MAX) / raster.Z9_RES - round((x0 + raster.MERC_MAX) / raster.Z9_RES)) < 1e-6
        assert abs((raster.MERC_MAX - y1) / raster.Z9_RES - round((raster.MERC_MAX - y1) / raster.Z9_RES)) < 1e-6
        data = ds.read(1)
    assert set(np.unique(data)).issubset(set(np.unique(cls)) | {NODATA})
    assert (data != NODATA).sum() > 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_publish_raster.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'poles.publish'`.

- [ ] **Step 3: Implement the module**

`pipeline/poles/publish/__init__.py` for now:

```python
"""Publish stage: explore tiles, detail rasters, site JSON, R2 upload. The stage entry point lands in a later task."""
```

`pipeline/poles/publish/raster.py`:

```python
"""Explore class rasters: the coarse distance grid quantised with the class table, masked, and warped to
Web Mercator at the z9 resolution for the tiler."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import rasterio
import shapely
from pyogrio import write
from pyproj import Transformer
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from ..classes import EDGE, NODATA, ClassTable
from ..grid import GTIFF_OPTS, Frame, create_raster, rasterize
from ..poly import parse_poly
from ..shell import run_cmd

Z9_RES = 40075016.68557849 / (256 * 512)
MERC_MAX = 20037508.342789244
MARKER = ".ok"


def _done(path: Path) -> bool:
    return path.exists() and Path(str(path) + MARKER).exists()


def _mark(path: Path) -> None:
    Path(str(path) + MARKER).write_text("", encoding="utf-8")


def edge_polygon(fetch_dir: Path) -> BaseGeometry:
    """Union of every source extract polygon: the same data edge validation's check 3 measures against."""
    snapshot = json.loads((fetch_dir / "snapshot.json").read_text(encoding="utf-8"))
    polys = [parse_poly(fetch_dir / s["poly"]) for s in snapshot["sources"]]
    if not polys:
        raise ValueError(f"{fetch_dir / 'snapshot.json'}: no sources")
    return unary_union(polys)


def _project(geom: BaseGeometry, src: str, dst: str) -> BaseGeometry:
    tr = Transformer.from_crs(src, dst, always_xy=True)
    return shapely.transform(geom, lambda c: np.column_stack(tr.transform(c[:, 0], c[:, 1])))


def _polygon_fgb(geom: BaseGeometry, path: Path, crs: str) -> Path:
    write(str(path), geometry=np.array([shapely.to_wkb(geom)], dtype=object), field_data=[np.array([1], dtype=np.int32)],
          fields=["v"], layer="mask", driver="FlatGeobuf", geometry_type="MultiPolygon" if geom.geom_type == "MultiPolygon" else "Polygon", crs=crs)
    return path


def edge_masks(edge_4326: BaseGeometry, frame: Frame, edge_mask_m: float, out_dir: Path, log: logging.Logger,
               tools_log: Path) -> tuple[Path, Path]:
    """inside.tif: 1 where the cell lies inside the region's data. edgeband.tif: 1 within edge_mask_m of the data
    edge, where a distance is only a lower bound. The band is also kept in EPSG:4326 for the detail rasters."""
    inside_tif, band_tif = out_dir / "inside.tif", out_dir / "edgeband.tif"
    if _done(inside_tif) and _done(band_tif):
        return inside_tif, band_tif
    edge_proj = _project(edge_4326, "EPSG:4326", frame.crs)
    band_proj = edge_proj.boundary.buffer(edge_mask_m)
    (out_dir / "edgeband_4326.wkb").write_bytes(shapely.to_wkb(_project(band_proj, frame.crs, "EPSG:4326")))
    for geom, tif in ((edge_proj, inside_tif), (band_proj, band_tif)):
        fgb = _polygon_fgb(geom, out_dir / (tif.stem + ".fgb"), frame.crs)
        create_raster(frame, tif, "uint8", nodata=None)
        rasterize(fgb, "mask", tif, log, tools_log, burn=1, all_touched=True)
        _mark(tif)
        log.info("publish: %s written", tif.name)
    return inside_tif, band_tif


def quantise(dist_tif: Path, land_tif: Path, inside_tif: Path, band_tif: Path, out_tif: Path, table: ClassTable,
             log: logging.Logger) -> dict:
    """Class index per cell, block by block. NODATA off land and outside the data beats EDGE beats the class."""
    counts = {"cells": 0, "nodata": 0, "edge": 0, "classed": 0}
    with rasterio.open(dist_tif) as dist, rasterio.open(land_tif) as land, rasterio.open(inside_tif) as inside, \
            rasterio.open(band_tif) as band:
        profile = dict(dist.profile, dtype="uint8", count=1, nodata=NODATA, **GTIFF_OPTS)
        with rasterio.open(out_tif, "w", **profile) as out:
            for _, win in dist.block_windows(1):
                d = dist.read(1, window=win)
                cls = table.to_class(np.minimum(d, table.edges[-1]))
                on_band = band.read(1, window=win) == 1
                off = (land.read(1, window=win) == 0) | (inside.read(1, window=win) == 0)
                cls[on_band] = EDGE
                cls[off] = NODATA
                out.write(cls, 1, window=win)
                counts["cells"] += cls.size
                counts["nodata"] += int(off.sum())
                counts["edge"] += int((on_band & ~off).sum())
    counts["classed"] = counts["cells"] - counts["nodata"] - counts["edge"]
    log.info("publish: %s: %s", out_tif.name, counts)
    return counts


def _mercator_extent(src_tif: Path) -> tuple[float, float, float, float]:
    """Bounding box of the source footprint in EPSG:3857, sampled along its edge and clamped to the world."""
    with rasterio.open(src_tif) as ds:
        b, crs = ds.bounds, ds.crs.to_string()
    tr = Transformer.from_crs(crs, "EPSG:3857", always_xy=True)
    n = 200
    xs = np.concatenate([np.linspace(b.left, b.right, n), np.full(n, b.right), np.linspace(b.right, b.left, n), np.full(n, b.left)])
    ys = np.concatenate([np.full(n, b.bottom), np.linspace(b.bottom, b.top, n), np.full(n, b.top), np.linspace(b.top, b.bottom, n)])
    mx, my = tr.transform(xs, ys)
    mx, my = np.asarray(mx), np.asarray(my)
    ok = np.isfinite(mx) & np.isfinite(my)
    mx, my = np.clip(mx[ok], -MERC_MAX, MERC_MAX), np.clip(my[ok], -MERC_MAX, MERC_MAX)
    return float(mx.min()), float(my.min()), float(mx.max()), float(my.max())


def warp_to_mercator(src_tif: Path, out_tif: Path, log: logging.Logger, tools_log: Path) -> Path:
    """Nearest-neighbour warp to EPSG:3857 on the z9 pixel grid (-tap at Z9_RES), so the tiler cuts z9 without
    resampling. Class values are categories; any other resampling would invent classes."""
    if _done(out_tif):
        return out_tif
    w, s, e, n = _mercator_extent(src_tif)
    cmd = ["gdalwarp", "-overwrite", "-t_srs", "EPSG:3857", "-r", "near", "-tr", repr(Z9_RES), repr(Z9_RES), "-tap",
           "-te", repr(w), repr(s), repr(e), repr(n), "-ot", "Byte", "-dstnodata", str(NODATA),
           "-multi", "-wo", "NUM_THREADS=ALL_CPUS", "--config", "GDAL_CACHEMAX", "2048",
           "-co", "TILED=YES", "-co", "BLOCKXSIZE=512", "-co", "BLOCKYSIZE=512", "-co", "COMPRESS=DEFLATE", "-co", "BIGTIFF=IF_SAFER",
           src_tif, out_tif]
    res = run_cmd(cmd, log, stderr_path=tools_log)
    _mark(out_tif)
    log.info("publish: %s warped in %.0f s", out_tif.name, res.duration_s)
    return out_tif
```

`create_raster` with `nodata=None` must leave the raster without a nodata value; check `grid.create_raster` passes `nodata` straight to rasterio (it does) and that the source `dist_*.tif` profile has `nodata=None` (quantise overrides it). If `gdalwarp` reads the class raster's nodata of 255 and treats it as `-srcnodata`, that is wanted.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_publish_raster.py -q`
Expected: 4 passed. If `test_edge_masks_band_hugs_the_boundary` disagrees on a row index by one, check the arithmetic against the frame (row r covers y from `y1 - (r+1)*250` to `y1 - r*250`; the northern boundary sits at `y1 - 2000`, i.e. between rows 7 and 8, and the 1 km band spans rows 4 to 11 at all-touched), fix the implementation, not the expectations, unless the expectation is arithmetically wrong; say which in the report.

- [ ] **Step 5: Commit**

```bash
git add pipeline/poles/publish/__init__.py pipeline/poles/publish/raster.py pipeline/tests/test_publish_raster.py
git commit -m "publish: explore class rasters: edge masks from the source polygons, block-wise quantisation, warp to the z9 Mercator grid"
```

---

### Task 3: Tile pyramid, MBTiles packer, PMTiles archive

**Files:**
- Create: `pipeline/poles/publish/tiles.py`
- Test: `pipeline/tests/test_publish_tiles.py`

**Interfaces:**
- Consumes: `raster.Z9_RES`, `raster.MERC_MAX`, `classes.NODATA`, `shell.run_cmd`.
- Produces:
  - `MAX_ZOOM = 9`.
  - `tile_dir(src_3857: Path, out_dir: Path, log, tools_log) -> Path`: the `<z>/<x>/<y>.png` pyramid (xyz convention) via `gdal raster tile`.
  - `pack_mbtiles(tiles_dir: Path, mbtiles: Path, name: str, bounds_lonlat: tuple[float, float, float, float]) -> dict` `{"tiles": n, "per_zoom": {z: n}, "blank_skipped": n}`.
  - `convert_pmtiles(mbtiles: Path, pmtiles: Path, log, tools_log) -> Path`.
  - `pmtiles_info(pmtiles: Path, log) -> dict` `{"tiles": n, "min_zoom", "max_zoom", "tile_type"}` parsed from `pmtiles show`.
  - `lonlat_bounds(src_3857: Path) -> tuple` (west, south, east, north in degrees, clamped to latitude 85.0511).
  - `build(src_3857: Path, out_dir: Path, scenario: str, log, tools_log) -> dict`: chains the four with `.ok` markers on `out_dir/tiles_<scenario>` (marker file `tiles_<scenario>.ok`), `out_dir/<scenario>.mbtiles`, `out_dir/<scenario>.pmtiles`; returns `{"key_name": "<scenario>.pmtiles", "bytes": n, "tiles": n, "min_zoom": 0, "max_zoom": 9, "per_zoom": {...}, "blank_skipped": n, "tile_type": "png"}`.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/test_publish_tiles.py`:

```python
import sqlite3
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from poles.classes import NODATA
from poles.publish import tiles
from poles.publish.raster import MERC_MAX, Z9_RES

TILE_M = 256 * Z9_RES
# Four z9 tiles wide, two high, at tile columns 270..273 and rows 170..171 (Europe).
TX, TY = 270, 170


def _source(path: Path, seed=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    data = rng.integers(0, 254, size=(2 * 256, 4 * 256), dtype=np.uint8)
    data[:256, 256:512] = NODATA                      # tile (271, 170) is blank
    data[256:, :256] = 7                              # tile (270, 171) is one class
    data[256:258, :2] = 5                             # two-by-two block with three 5s and one 7 for the overview test
    data[257, 1] = 7
    transform = from_origin(-MERC_MAX + TX * TILE_M, MERC_MAX - TY * TILE_M, Z9_RES, Z9_RES)
    with rasterio.open(path, "w", driver="GTiff", width=data.shape[1], height=data.shape[0], count=1, dtype="uint8",
                       crs="EPSG:3857", transform=transform, nodata=NODATA, tiled=True, compress="deflate") as ds:
        ds.write(data, 1)
    return data


def _mbtile(mbtiles: Path, z: int, x: int, y: int) -> np.ndarray | None:
    con = sqlite3.connect(mbtiles)
    row = con.execute("SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                      (z, x, (1 << z) - 1 - y)).fetchone()
    con.close()
    if row is None:
        return None
    tmp = mbtiles.parent / f"read_{z}_{x}_{y}.png"
    tmp.write_bytes(row[0])
    with rasterio.open(tmp) as ds:
        return ds.read(1)


def test_tile_dir_cuts_z9_without_resampling(tmp_path, log):
    data = _source(tmp_path / "src.tif")
    out = tiles.tile_dir(tmp_path / "src.tif", tmp_path / "tiles", log, tmp_path / "tools.log")
    png = out / "9" / str(TX) / f"{TY}.png"
    assert png.exists()
    with rasterio.open(png) as ds:
        assert ds.count == 1 and ds.dtypes == ("uint8",)
        assert np.array_equal(ds.read(1), data[:256, :256])
    assert (out / "0").is_dir() and (out / "8").is_dir()


def test_pack_skips_blank_and_flips_rows(tmp_path, log):
    data = _source(tmp_path / "src.tif")
    out = tiles.tile_dir(tmp_path / "src.tif", tmp_path / "tiles", log, tmp_path / "tools.log")
    stats = tiles.pack_mbtiles(out, tmp_path / "A.mbtiles", "A", tiles.lonlat_bounds(tmp_path / "src.tif"))
    assert stats["per_zoom"][9] == 7 and stats["blank_skipped"] >= 1 or stats["per_zoom"][9] == 7
    assert _mbtile(tmp_path / "A.mbtiles", 9, TX + 1, TY) is None
    assert np.array_equal(_mbtile(tmp_path / "A.mbtiles", 9, TX, TY + 1), data[256:, :256])
    con = sqlite3.connect(tmp_path / "A.mbtiles")
    meta = dict(con.execute("SELECT name, value FROM metadata").fetchall())
    con.close()
    assert meta["format"] == "png" and meta["minzoom"] == "0" and meta["maxzoom"] == "9" and meta["name"] == "A"
    assert len(meta["bounds"].split(",")) == 4


def test_overviews_use_mode_not_average(tmp_path, log):
    _source(tmp_path / "src.tif")
    out = tiles.tile_dir(tmp_path / "src.tif", tmp_path / "tiles", log, tmp_path / "tools.log")
    z8 = out / "8" / str(TX // 2) / f"{(TY + 1) // 2}.png"
    with rasterio.open(z8) as ds:
        a = ds.read(1)
    # z9 tile (270, 171) maps to the bottom-left quarter of z8 tile (135, 85); its first 2x2 block is 5,5,5,7 -> 5.
    assert a[128, 0] == 5
    assert a[129, 1] == 7                           # a block of plain 7s stays 7
    vals = set(np.unique(a).tolist())
    assert vals.issubset(set(range(254)) | {NODATA}) and 6 not in vals


def test_build_chain_and_pmtiles_info(tmp_path, log):
    _source(tmp_path / "src.tif")
    meta = tiles.build(tmp_path / "src.tif", tmp_path, "A", log, tmp_path / "tools.log")
    assert (tmp_path / "A.pmtiles").exists() and meta["bytes"] == (tmp_path / "A.pmtiles").stat().st_size
    assert meta["max_zoom"] == 9 and meta["min_zoom"] == 0 and meta["tile_type"] == "png"
    assert meta["tiles"] == sum(meta["per_zoom"].values())
    for m in ("tiles_A.ok", "A.mbtiles.ok", "A.pmtiles.ok"):
        assert (tmp_path / m).exists()
    again = tiles.build(tmp_path / "src.tif", tmp_path, "A", log, tmp_path / "tools.log")
    assert again == meta


def test_pmtiles_info_parses_show_output():
    text = ("pmtiles spec version: 3\ntile type: png\nbounds: 9.8,50.1,12.3,52.2\nmin zoom: 0\nmax zoom: 9\n"
            "center: 11,51,5\naddressed tiles count: 42\ntile entries count: 42\ntile contents count: 40\n")
    assert tiles.parse_show(text) == {"tiles": 42, "min_zoom": 0, "max_zoom": 9, "tile_type": "png"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_publish_tiles.py -q`
Expected: FAIL, `ImportError: cannot import name 'tiles'`.

- [ ] **Step 3: Implement the module**

`pipeline/poles/publish/tiles.py`:

```python
"""Explore tile pyramid: gdal raster tile cuts the warped class raster into z0..z9 PNGs, a packer writes them
into MBTiles, pmtiles converts the archive. Class values are categories, so z9 is nearest and the overviews
are the mode of their four children."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer

from ..classes import NODATA
from ..shell import run_cmd
from .raster import MARKER, _done, _mark

MAX_ZOOM = 9
LAT_MAX = 85.0511287798066


def tile_dir(src_3857: Path, out_dir: Path, log: logging.Logger, tools_log: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["gdal", "raster", "tile", "--tiling-scheme", "WebMercatorQuad", "--min-zoom", "0", "--max-zoom", str(MAX_ZOOM),
           "--resampling", "nearest", "--overview-resampling", "mode", "--no-alpha", "--skip-blank",
           "--convention", "xyz", "--output-format", "PNG", "--resume", src_3857, out_dir]
    res = run_cmd(cmd, log, stderr_path=tools_log)
    log.info("publish: tiles of %s cut into %s in %.0f s", src_3857.name, out_dir.name, res.duration_s)
    return out_dir


def lonlat_bounds(src_3857: Path) -> tuple[float, float, float, float]:
    with rasterio.open(src_3857) as ds:
        b = ds.bounds
    tr = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    w, s = tr.transform(b.left, b.bottom)
    e, n = tr.transform(b.right, b.top)
    return float(w), float(max(s, -LAT_MAX)), float(e), float(min(n, LAT_MAX))


def pack_mbtiles(tiles_dir: Path, mbtiles: Path, name: str, bounds_lonlat: tuple[float, float, float, float]) -> dict:
    """Directory pyramid to MBTiles (TMS rows). Tiles that are entirely NODATA are dropped here whatever the
    tiler did, so the archive never carries an empty tile."""
    if mbtiles.exists():
        mbtiles.unlink()
    con = sqlite3.connect(mbtiles)
    con.executescript("CREATE TABLE metadata (name TEXT, value TEXT);"
                      "CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB);"
                      "CREATE UNIQUE INDEX tile_index ON tiles (zoom_level, tile_column, tile_row);")
    per_zoom: dict[int, int] = {}
    blank = 0
    for png in sorted(tiles_dir.rglob("*.png")):
        z, x, y = int(png.parent.parent.name), int(png.parent.name), int(png.stem)
        with rasterio.open(png) as ds:
            if (ds.read(1) == NODATA).all():
                blank += 1
                continue
        con.execute("INSERT INTO tiles VALUES (?, ?, ?, ?)", (z, x, (1 << z) - 1 - y, png.read_bytes()))
        per_zoom[z] = per_zoom.get(z, 0) + 1
    if not per_zoom:
        con.close()
        raise RuntimeError(f"{tiles_dir}: no non-blank tiles")
    zooms = sorted(per_zoom)
    meta = {"name": name, "format": "png", "type": "overlay", "version": "1",
            "description": f"{name}: distance class index per pixel, 254 edge, 255 nodata",
            "minzoom": str(zooms[0]), "maxzoom": str(zooms[-1]),
            "bounds": ",".join(f"{v:.6f}" for v in bounds_lonlat)}
    con.executemany("INSERT INTO metadata VALUES (?, ?)", list(meta.items()))
    con.commit()
    con.close()
    return {"tiles": sum(per_zoom.values()), "per_zoom": per_zoom, "blank_skipped": blank}


def convert_pmtiles(mbtiles: Path, pmtiles: Path, log: logging.Logger, tools_log: Path) -> Path:
    if pmtiles.exists():
        pmtiles.unlink()
    res = run_cmd(["pmtiles", "convert", mbtiles, pmtiles], log, stderr_path=tools_log)
    log.info("publish: %s converted in %.0f s", pmtiles.name, res.duration_s)
    return pmtiles


def parse_show(text: str) -> dict:
    def grab(label: str, cast=int):
        m = re.search(rf"^{label}:\s*(\S+)", text, re.MULTILINE)
        if not m:
            raise ValueError(f"pmtiles show: no '{label}' line in:\n{text}")
        return cast(m.group(1))
    return {"tiles": grab("addressed tiles count"), "min_zoom": grab("min zoom"), "max_zoom": grab("max zoom"),
            "tile_type": grab("tile type", str)}


def pmtiles_info(pmtiles: Path, log: logging.Logger) -> dict:
    out = pmtiles.parent / (pmtiles.name + ".show.txt")
    run_cmd(["pmtiles", "show", pmtiles], log, stdout_path=out)
    return parse_show(out.read_text(encoding="utf-8"))


def build(src_3857: Path, out_dir: Path, scenario: str, log: logging.Logger, tools_log: Path) -> dict:
    tiles_path = out_dir / f"tiles_{scenario}"
    mbtiles = out_dir / f"{scenario}.mbtiles"
    pmtiles = out_dir / f"{scenario}.pmtiles"
    stats_path = out_dir / f"{scenario}.mbtiles.json"
    if not _done(tiles_path):
        tile_dir(src_3857, tiles_path, log, tools_log)
        _mark(tiles_path)
    if not _done(mbtiles):
        stats = pack_mbtiles(tiles_path, mbtiles, scenario, lonlat_bounds(src_3857))
        stats_path.write_text(json.dumps(stats) + "\n", encoding="utf-8")
        _mark(mbtiles)
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    if not _done(pmtiles):
        convert_pmtiles(mbtiles, pmtiles, log, tools_log)
        _mark(pmtiles)
    info = pmtiles_info(pmtiles, log)
    return {"key_name": pmtiles.name, "bytes": pmtiles.stat().st_size, "tiles": info["tiles"],
            "min_zoom": info["min_zoom"], "max_zoom": info["max_zoom"], "tile_type": info["tile_type"],
            "per_zoom": {int(k): v for k, v in stats["per_zoom"].items()}, "blank_skipped": stats["blank_skipped"]}
```

`_done(tiles_path)` works on a directory because the marker is `tiles_<s>.ok` beside it and `exists()` is true for a directory. `raster.MARKER`, `_done`, `_mark` are shared; import them rather than copying.

Tool-option check: before trusting the argv, run `gdal raster tile --help` and `pmtiles show --help`. If GDAL 3.13 spells an option differently (for instance `-r` only, or `--of`), use the 3.13 spelling with the same meaning, and paste the final argv plus the help excerpt into the report. If `--skip-blank` with `--no-alpha` leaves all-255 tiles in the directory, the packer drops them anyway; the test on `_mbtile(..., TX + 1, TY) is None` is what must hold. If `pmtiles show` prints different labels than the fixture in `test_pmtiles_info_parses_show_output`, change `parse_show` and the fixture together to the real labels (`pmtiles show` on the test archive is the authority) and say so in the report.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_publish_tiles.py -q`
Expected: 5 passed. The overview test pins the mode behaviour; if GDAL's mode resolves the 5,5,5,7 block to something other than 5, that is a real finding: report it with the pixel values before changing anything.

- [ ] **Step 5: Commit**

```bash
git add pipeline/poles/publish/tiles.py pipeline/tests/test_publish_tiles.py
git commit -m "publish: tile pyramid with gdal raster tile, MBTiles packer that drops blank tiles, pmtiles archive and its info"
```

---

### Task 4: Detail rasters

**Files:**
- Create: `pipeline/poles/publish/detail.py`
- Test: `pipeline/tests/test_publish_detail.py`

**Interfaces:**
- Consumes: `classes.ClassTable, EDGE, NODATA`; `refine.UtmRoads, RoadCache, utm_epsg`; `roads.RoadTiles`; `classify.where_clause`; the `land_idx.fgb` and `water_big.fgb` reading pattern of `poles._allowed_factory` (pyogrio `read` with `bbox`, STRtree `within` queries); the published poles structure (`{"unit", "poles": [{rank, lat, lon, dist_m, ...}], "reason", "withheld"}` per scenario, produced by Task 5's `apply_exclusions`; this task only needs `unit`, `rank`, `lat`, `lon`, `dist_m`).
- Produces:
  - `Georef(west, north, dlon, dlat, width, height)` frozen dataclass with `to_dict()`.
  - `georef(lat: float, lon: float, res_m: float, window_m: float) -> Georef`.
  - `centres(g: Georef) -> tuple[np.ndarray, np.ndarray]` (lons of width, lats of height, pixel centres).
  - `classify_window(g, roads: UtmRoads, land_ok, edge_band, table) -> np.ndarray` (height by width, uint8).
  - `land_test(land_idx: Path, water_big: Path, bbox) -> callable(lons, lats) -> bool array`.
  - `write_detail(out_dir: Path, code: str, scenario: str, rank: int, arr, g) -> tuple[Path, Path]` (`<out_dir>/<code>/<scenario>-<rank>.png` and `.json`, JSON written last).
  - `DetailJob` dataclass `(region_dirs: dict[str, str], code, scenario, rank, lat, lon, dist_m, res_m, window_m, out_dir: str, edge_wkb: bytes)`; `render(job) -> dict` (worker entry, returns `{"code", "scenario", "rank", "png", "bytes", "seconds"}`).
  - `run_detail(cfg, ws, published: dict[str, list[dict]], table, edge_band_4326, log) -> dict` `{"count": n, "bytes": n, "seconds": s, "skipped": n}`.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/test_publish_detail.py`:

```python
import json
import math
from pathlib import Path

import numpy as np
import rasterio
import shapely
from pyproj import Transformer
from shapely.geometry import LineString, box

from poles.classes import EDGE, NODATA, ClassTable
from poles.publish import detail
from poles.refine import UtmRoads, utm_epsg
from poles.roads import RoadSet

LAT, LON = 55.0, 24.0


def _roads_through(lat, lon, epsg):
    """One east-west road 1 km south of (lat, lon), in the zone's UTM coordinates, as an EPSG:4326 RoadSet."""
    to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    to_ll = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    x, y = to_utm.transform(lon, lat)
    line = LineString([to_ll.transform(x - 50_000, y - 1_000), to_ll.transform(x + 50_000, y - 1_000)])
    return RoadSet(np.array([line], dtype=object), {"osm_id": np.array([1], dtype=object), "highway": np.array(["track"], dtype=object)})


def test_georef_matches_spec():
    g = detail.georef(60.0, 10.0, 50, 20_000)
    assert g.width == g.height == 400
    assert math.isclose(g.dlat, 50 / 111_320)
    assert math.isclose(g.dlon, g.dlat / math.cos(math.radians(60.0)))
    assert math.isclose(g.west, 10.0 - 200 * g.dlon) and math.isclose(g.north, 60.0 + 200 * g.dlat)
    assert set(g.to_dict()) == {"west", "north", "dlon", "dlat", "width", "height"}


def test_classify_window_distances_masks_and_bands():
    epsg = utm_epsg(LON, LAT)
    roads = UtmRoads(_roads_through(LAT, LON, epsg), epsg)
    g = detail.georef(LAT, LON, 50, 2_000)                      # 40 x 40 pixels
    lons, lats = detail.centres(g)
    assert len(lons) == 40 and len(lats) == 40
    band = box(g.west, g.north - 2 * g.dlat, g.west + 40 * g.dlon, g.north)   # the top two rows
    land_ok = lambda lo, la: np.asarray(lo) > g.west + 3 * g.dlon                 # first three columns are water
    arr = detail.classify_window(g, roads, land_ok, band, ClassTable())
    assert arr.shape == (40, 40) and arr.dtype == np.uint8
    assert (arr[0, 3:] == EDGE).all() and (arr[1, 3:] == EDGE).all()
    assert (arr[:, :3] == NODATA).all()
    centre = arr[20, 20]                                         # the pole itself sits 1 km from the road: class 20
    assert centre in (19, 20)
    assert arr[39, 20] < arr[20, 20] < arr[2, 20]                # distance grows northwards, away from the road


def test_write_and_read_back(tmp_path):
    g = detail.georef(LAT, LON, 50, 2_000)
    arr = np.arange(1600, dtype=np.uint16).reshape(40, 40).astype(np.uint8)
    png, js = detail.write_detail(tmp_path, "lt", "A", 3, arr, g)
    assert png == tmp_path / "lt" / "A-3.png" and js == tmp_path / "lt" / "A-3.json"
    with rasterio.open(png) as ds:
        assert ds.count == 1 and np.array_equal(ds.read(1), arr)
    assert json.loads(js.read_text()) == g.to_dict()


def test_land_test_uses_land_minus_big_water(tmp_path):
    from tests.helpers import write_fgb
    land = box(23.9, 54.9, 24.1, 55.1)
    water = box(24.0, 55.0, 24.05, 55.05)
    write_fgb(tmp_path / "land_idx.fgb", "land", [land], {"id": [1]})
    write_fgb(tmp_path / "water_big.fgb", "water", [water], {"id": [1]})
    ok = detail.land_test(tmp_path / "land_idx.fgb", tmp_path / "water_big.fgb", (23.8, 54.8, 24.2, 55.2))
    got = ok(np.array([23.95, 24.02, 24.5]), np.array([54.95, 55.02, 55.0]))
    assert got.tolist() == [True, False, False]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_publish_detail.py -q`
Expected: FAIL, `ImportError: cannot import name 'detail'`.

- [ ] **Step 3: Implement the module**

`pipeline/poles/publish/detail.py`:

```python
"""Detail rasters: exact vector distances on a 50 m lattice around each published pole (spec 3.5), computed in
the pole's UTM zone from the stage-2 road tiles, classed with the shared table, written as single-band PNGs
with a six-field georeference sidecar."""
from __future__ import annotations

import json
import logging
import math
import os
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import rasterio
import shapely
from pyogrio.raw import read
from pyproj import Transformer
from shapely import STRtree
from shapely.geometry.base import BaseGeometry

from ..classes import EDGE, NODATA, ClassTable
from ..classify import SCENARIOS, where_clause
from ..refine import RoadCache, UtmRoads, utm_epsg
from ..roads import RoadTiles

M_PER_DEG = 111_320.0


@dataclass(frozen=True)
class Georef:
    west: float
    north: float
    dlon: float
    dlat: float
    width: int
    height: int

    def to_dict(self) -> dict:
        return asdict(self)


def georef(lat: float, lon: float, res_m: float, window_m: float) -> Georef:
    dlat = res_m / M_PER_DEG
    dlon = dlat / math.cos(math.radians(lat))
    n = int(round(window_m / res_m))
    return Georef(west=lon - dlon * n / 2, north=lat + dlat * n / 2, dlon=dlon, dlat=dlat, width=n, height=n)


def centres(g: Georef) -> tuple[np.ndarray, np.ndarray]:
    lons = g.west + g.dlon * (np.arange(g.width) + 0.5)
    lats = g.north - g.dlat * (np.arange(g.height) + 0.5)
    return lons, lats


def land_test(land_idx: Path, water_big: Path, bbox: tuple[float, float, float, float]):
    """Point on a land polygon and in no water polygon of 1 km2 or more; the unit boundary does not matter here,
    a neighbour's land shows its distances too."""
    _, _, lwkb, _ = read(str(land_idx), layer="land", bbox=bbox)
    _, _, wwkb, _ = read(str(water_big), layer="water", bbox=bbox)
    land_tree = STRtree(shapely.from_wkb(lwkb)) if len(lwkb) else None
    water_tree = STRtree(shapely.from_wkb(wwkb)) if len(wwkb) else None

    def ok(lons, lats):
        lons, lats = np.asarray(lons, dtype=np.float64), np.asarray(lats, dtype=np.float64)
        out = np.zeros(len(lons), bool)
        if land_tree is None:
            return out
        pts = shapely.points(lons, lats)
        out[np.unique(land_tree.query(pts, predicate="within")[0])] = True
        if water_tree is not None:
            wet = np.zeros(len(lons), bool)
            wet[np.unique(water_tree.query(pts, predicate="within")[0])] = True
            out &= ~wet
        return out

    return ok


def classify_window(g: Georef, roads: UtmRoads, land_ok, edge_band: BaseGeometry | None, table: ClassTable) -> np.ndarray:
    if roads.tree is None:
        raise RuntimeError("detail window has no roads in reach; the pole's own nearest way should be inside it")
    lons, lats = centres(g)
    glon, glat = np.meshgrid(lons, lats)
    flat_lon, flat_lat = glon.ravel(), glat.ravel()
    tr = Transformer.from_crs("EPSG:4326", f"EPSG:{roads.epsg}", always_xy=True)
    x, y = tr.transform(flat_lon, flat_lat)
    pts = shapely.points(np.asarray(x), np.asarray(y))
    idx = roads.tree.nearest(pts)
    dist = shapely.distance(pts, roads.geoms[idx])
    cls = table.to_class(np.minimum(dist, table.edges[-1]))
    if edge_band is not None and not edge_band.is_empty:
        shapely.prepare(edge_band)
        cls[shapely.contains_xy(edge_band, flat_lon, flat_lat)] = EDGE
    cls[~land_ok(flat_lon, flat_lat)] = NODATA
    return cls.reshape(g.height, g.width)


def write_detail(out_dir: Path, code: str, scenario: str, rank: int, arr: np.ndarray, g: Georef) -> tuple[Path, Path]:
    d = out_dir / code
    d.mkdir(parents=True, exist_ok=True)
    png, js = d / f"{scenario}-{rank}.png", d / f"{scenario}-{rank}.json"
    with rasterio.open(png, "w", driver="PNG", width=g.width, height=g.height, count=1, dtype="uint8") as ds:
        ds.write(arr.astype(np.uint8), 1)
    aux = Path(str(png) + ".aux.xml")
    if aux.exists():
        aux.unlink()
    js.write_text(json.dumps(g.to_dict()) + "\n", encoding="utf-8")
    return png, js


@dataclass(frozen=True)
class DetailJob:
    roads_dir: str
    land_idx: str
    water_big: str
    out_dir: str
    code: str
    scenario: str
    poles: tuple            # ((rank, lat, lon, dist_m), ...) of one unit and scenario
    res_m: float
    window_m: float
    edge_wkb: bytes


_TILES: dict[str, RoadTiles] = {}


def _tiles(path: str) -> RoadTiles:
    if path not in _TILES:
        _TILES[path] = RoadTiles(Path(path))
    return _TILES[path]


def _pad_bbox(g: Georef, lat: float, pad_m: float) -> tuple[float, float, float, float]:
    dlat = pad_m / M_PER_DEG
    dlon = dlat / math.cos(math.radians(lat))
    return g.west - dlon, g.north - g.dlat * g.height - dlat, g.west + g.dlon * g.width + dlon, g.north + dlat


def render(job: DetailJob) -> dict:
    """One unit and scenario: its poles in rank order share the road cache."""
    t0 = time.monotonic()
    table = ClassTable()
    edge_band = shapely.from_wkb(job.edge_wkb) if job.edge_wkb else None
    cache = RoadCache(_tiles(job.roads_dir), where_clause(job.scenario), pad_deg=0.0)
    out_dir = Path(job.out_dir)
    done, total_bytes, skipped = [], 0, 0
    for rank, lat, lon, dist_m in job.poles:
        png, js = out_dir / job.code / f"{job.scenario}-{rank}.png", out_dir / job.code / f"{job.scenario}-{rank}.json"
        if png.exists() and js.exists():
            skipped += 1
            total_bytes += png.stat().st_size
            continue
        g = georef(lat, lon, job.res_m, job.window_m)
        half_diag = math.hypot(g.width * job.res_m, g.height * job.res_m) / 2
        bbox = _pad_bbox(g, lat, dist_m + half_diag + 1_000)
        roads = cache.get(*bbox, utm_epsg(lon, lat))
        land_ok = land_test(Path(job.land_idx), Path(job.water_big), _pad_bbox(g, lat, 1_000))
        arr = classify_window(g, roads, land_ok, edge_band, table)
        png, _ = write_detail(out_dir, job.code, job.scenario, rank, arr, g)
        total_bytes += png.stat().st_size
        done.append(rank)
    return {"code": job.code, "scenario": job.scenario, "rendered": done, "skipped": skipped, "bytes": total_bytes,
            "seconds": time.monotonic() - t0}


def run_detail(cfg, ws, published: dict[str, list[dict]], table: ClassTable, edge_band_4326: BaseGeometry | None,
               log: logging.Logger) -> dict:
    poles_dir, out_dir = ws.dir("poles"), ws.dir("publish") / "detail"
    out_dir.mkdir(parents=True, exist_ok=True)
    edge_wkb = shapely.to_wkb(edge_band_4326) if edge_band_4326 is not None else b""
    jobs = []
    for scenario in SCENARIOS:
        for unit in published[scenario]:
            if not unit["poles"]:
                continue
            jobs.append(DetailJob(str(poles_dir / "roads"), str(poles_dir / "land_idx.fgb"), str(poles_dir / "water_big.fgb"),
                                  str(out_dir), unit["unit"], scenario,
                                  tuple((p["rank"], p["lat"], p["lon"], p["dist_m"]) for p in unit["poles"]),
                                  cfg.detail_res_m, cfg.detail_window_m, edge_wkb))
    workers = int(os.environ.get("POLES_WORKERS", "0")) or 4
    t0 = time.monotonic()
    count = skipped = total_bytes = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for r in pool.map(render, jobs, chunksize=1):
            count += len(r["rendered"]) + r["skipped"]
            skipped += r["skipped"]
            total_bytes += r["bytes"]
            log.info("publish: detail %s %s: %d rendered, %d kept, %.0f s", r["code"], r["scenario"], len(r["rendered"]),
                     r["skipped"], r["seconds"])
    return {"count": count, "bytes": total_bytes, "seconds": round(time.monotonic() - t0, 1), "skipped": skipped}
```

`table.to_class(...)` takes the whole flat array at once; 160,000 points per window. `write_detail` removes the `.aux.xml` GDAL may leave beside a PNG so the upload set stays clean. Check how `poles.py` constructs the pool (`ProcessPoolExecutor` with a `spawn` or `fork` context) and use the same context here; say which in the report.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_publish_detail.py -q`
Expected: 4 passed. `test_land_test_uses_land_minus_big_water` imports `tests.helpers`; if the tests package is importable as `helpers` only (look at how `test_roads.py` imports it), match that form.

- [ ] **Step 5: Commit**

```bash
git add pipeline/poles/publish/detail.py pipeline/tests/test_publish_detail.py
git commit -m "publish: 50 m detail rasters per published pole from the road tiles, classed, with georeference sidecars"
```

---

### Task 5: Site data, exclusions, schemas

**Files:**
- Create: `pipeline/poles/publish/sitedata.py`; `pipeline/poles/schemas/regions.schema.json`, `units.schema.json`, `unit.schema.json`, `manifest.schema.json`
- Modify: `pipeline/requirements.txt` (add `jsonschema` pinned), `pipeline/pyproject.toml` (package data for `poles/schemas/*.json` if the package uses an explicit file list; check the existing `[tool.setuptools]` section and add `package-data = {"poles" = ["schemas/*.json"]}` only when needed)
- Test: `pipeline/tests/test_publish_sitedata.py`

**Interfaces:**
- Consumes: `classes.ClassTable`; the stage-2 poles structure; `units.json` entries; `units.fgb` geometries (pyogrio `read`); `fetch/snapshot.json` sources.
- Produces:
  - `apply_exclusions(poles: dict[str, list[dict]], excluded: list[dict]) -> dict[str, list[dict]]`: same shape, ranks renumbered, each unit record gains `"withheld": int`; raises `PolesError` when an exclusion matches nothing.
  - `unit_area_km2(geom) -> float`; `unit_geometries(units_fgb: Path) -> dict[str, BaseGeometry]`.
  - `regional_ranks(published_scenario: list[dict]) -> dict[str, int]`.
  - `build(region: dict, units_meta: list[dict], geoms: dict, published: dict, table: ClassTable, archives: dict, detail_meta: dict, verify_meta: dict, sources: list[dict], generated_at: str, pipeline_commit: str | None) -> SiteData` where `region = {"id", "name", "snapshot", "unit_level", "r2_base", "max_distance_m", "edge_mask_m", "detail_res_m", "detail_window_m"}` and `SiteData(regions_entry: dict, units_doc: dict, unit_docs: dict[str, dict], manifest_entry: dict)`.
  - `merge_regions(existing: dict | None, entry: dict) -> dict`; `merge_manifest(existing: dict | None, region_id: str, entry: dict, generated_at: str) -> dict`.
  - `validate_doc(name: str, doc: dict) -> None` (`name` in `regions, units, unit, manifest`; raises `PolesError` with the schema path of the first error).
  - `write_site(site: SiteData, out_dir: Path, region_id: str, generated_at: str) -> list[Path]`: merges with `out_dir/regions.json` and `out_dir/manifest.json` when present, validates everything, writes `regions.json`, `manifest.json`, `<region>/units.json`, `<region>/units/<code>.json`; returns the written paths.
  - Pole records in the unit file: the stage-2 record with `rank` renumbered and `detail` set to `"detail/<code>/<scenario>-<rank>"` (the key stem under `<r2_base>/<region>/<snapshot>/`; the site appends `.png` and `.json`).

- [ ] **Step 1: Add the dependency**

Run: `cd pipeline && uv pip install --python .venv/bin/python jsonschema`, then append `jsonschema==<resolved>` and every new transitive pin `uv pip freeze --python .venv/bin/python` shows that is absent from `requirements.txt` (keep the file sorted as it is now). Expected: `.venv/bin/python -c "import jsonschema; print(jsonschema.__version__)"` prints the version.

- [ ] **Step 2: Write the failing tests**

`pipeline/tests/test_publish_sitedata.py`:

```python
import json
from pathlib import Path

import pytest
from shapely.geometry import box

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
UNITS_META = [
    {"code": "lt", "name": "Lietuva", "name_en": "Lithuania", "osm_id": 72596, "country": "lt", "index": 1, "area_km2": 1.0,
     "cells": 10, "transcontinental": False, "closed_by_edge": False, "bbox": [20.9, 53.9, 26.9, 56.5], "window": [0, 0, 1, 1]},
    {"code": "lv", "name": "Latvija", "name_en": "Latvia", "osm_id": 72594, "country": "lv", "index": 2, "area_km2": 1.0,
     "cells": 10, "transcontinental": False, "closed_by_edge": False, "bbox": [20.9, 55.6, 28.3, 58.1], "window": [0, 0, 1, 1]},
    {"code": "mc", "name": "Monaco", "name_en": "Monaco", "osm_id": 1124039, "country": "mc", "index": 3, "area_km2": 0.0,
     "cells": 0, "transcontinental": False, "closed_by_edge": False, "bbox": [7.4, 43.7, 7.5, 43.8], "window": [0, 0, 1, 1]},
]
GEOMS = {"lt": box(21, 54, 27, 56.5), "lv": box(21, 55.6, 28, 58), "mc": box(7.4, 43.7, 7.45, 43.75)}
REGION = {"id": "testland", "name": "Testland", "snapshot": "2026-01-01", "unit_level": 2, "r2_base": "https://pub-x.r2.dev",
          "max_distance_m": 250000, "edge_mask_m": 50000, "detail_res_m": 50, "detail_window_m": 20000}
ARCHIVES = {"A": {"key_name": "A.pmtiles", "bytes": 10, "tiles": 3, "min_zoom": 0, "max_zoom": 9, "tile_type": "png", "per_zoom": {9: 1}, "blank_skipped": 0},
            "B": {"key_name": "B.pmtiles", "bytes": 10, "tiles": 3, "min_zoom": 0, "max_zoom": 9, "tile_type": "png", "per_zoom": {9: 1}, "blank_skipped": 0}}
SOURCES = [{"url": "https://example.org/x.pbf", "role": "primary", "file": "x.pbf", "size": 1, "md5": "a", "sha256": "b",
            "last_modified": "2026-01-01T00:00:00+00:00", "poly": "x.poly"}]


def _build(published=None):
    published = published or sitedata.apply_exclusions(POLES, [])
    return sitedata.build(REGION, UNITS_META, GEOMS, published, ClassTable(), ARCHIVES, {"count": 5, "bytes": 50},
                          {"at": "2026-01-02T00:00:00+00:00", "keys": 13, "range_ok": 2}, SOURCES,
                          "2026-01-02T00:00:00+00:00", "abc123")


def test_apply_exclusions_drops_reranks_and_counts():
    out = sitedata.apply_exclusions(POLES, [{"unit": "lt", "scenario": "A", "rank": 2, "lat": 0, "lon": 0, "dist_m": 0, "details": {}}])
    lt = out["A"][0]
    assert [p["rank"] for p in lt["poles"]] == [1, 2] and [p["dist_m"] for p in lt["poles"]] == [9000.0, 7000.0]
    assert lt["withheld"] == 1 and out["A"][1]["withheld"] == 0 and out["B"][0]["withheld"] == 0
    assert POLES["A"][0]["poles"][1]["rank"] == 2                      # input untouched


def test_apply_exclusions_refuses_unmatched():
    with pytest.raises(PolesError, match="rerun validate"):
        sitedata.apply_exclusions(POLES, [{"unit": "lt", "scenario": "A", "rank": 9, "lat": 0, "lon": 0, "dist_m": 0, "details": {}}])


def test_regional_ranks_dense_ties_by_code():
    published = sitedata.apply_exclusions(POLES, [])
    assert sitedata.regional_ranks(published["A"]) == {"lv": 1, "lt": 2}
    assert sitedata.regional_ranks(published["B"]) == {"lt": 1, "lv": 1}


def test_unit_area_is_geodesic():
    km2 = sitedata.unit_area_km2(box(0, 0, 1, 1))
    assert abs(km2 - 12308.0) / 12308.0 < 0.01


def test_build_documents():
    site = _build()
    assert site.regions_entry["id"] == "testland" and site.regions_entry["units_count"] == 3
    assert len(site.regions_entry["class_edges"]) == 254 and site.regions_entry["r2_base"] == REGION["r2_base"]
    units = {u["code"]: u for u in site.units_doc["units"]}
    assert units["lt"]["A"]["dist_m"] == 9000.0 and units["lt"]["A"]["rank"] == 2 and units["lt"]["A"]["withheld"] == 0
    assert units["mc"]["A"] is None and units["mc"]["B"] is None
    assert units["lt"]["area_km2"] > 60000 and units["lt"]["name_en"] == "Lithuania"
    lt = site.unit_docs["lt"]
    assert lt["A"]["poles"][0]["detail"] == "detail/lt/A-1" and lt["A"]["withheld"] == 0 and lt["A"]["reason"] is None
    assert site.unit_docs["mc"]["A"] == {"poles": [], "withheld": 0, "reason": "no land cell"}
    m = site.manifest_entry
    assert m["archives"]["A"]["key"] == "testland/2026-01-01/A.pmtiles" and m["detail"]["count"] == 5
    assert m["validation"]["report"] == "testland/2026-01-01/validation/report.json" and m["pipeline_commit"] == "abc123"
    assert m["sources"][0]["sha256"] == "b"


def test_every_document_validates():
    site = _build()
    sitedata.validate_doc("regions", sitedata.merge_regions(None, site.regions_entry))
    sitedata.validate_doc("units", site.units_doc)
    for doc in site.unit_docs.values():
        sitedata.validate_doc("unit", doc)
    sitedata.validate_doc("manifest", sitedata.merge_manifest(None, "testland", site.manifest_entry, "2026-01-02T00:00:00+00:00"))
    with pytest.raises(PolesError, match="regions"):
        sitedata.validate_doc("regions", {"schema_version": 1, "regions": [{"id": "x"}]})
    with pytest.raises(PolesError):
        bad = dict(site.units_doc)
        bad["extra"] = 1
        sitedata.validate_doc("units", bad)


def test_write_site_merges_other_regions(tmp_path):
    site = _build()
    (tmp_path / "regions.json").write_text(json.dumps({"schema_version": 1, "regions": [{"id": "other", "name": "Other"}]}))
    (tmp_path / "manifest.json").write_text(json.dumps({"schema_version": 1, "generated_at": "2025-01-01T00:00:00+00:00",
                                                         "regions": {"other": {"snapshot": "2025-01-01"}}}))
    paths = sitedata.write_site(site, tmp_path, "testland", "2026-01-02T00:00:00+00:00")
    regions = json.loads((tmp_path / "regions.json").read_text())
    assert [r["id"] for r in regions["regions"]] == ["other", "testland"]
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert set(manifest["regions"]) == {"other", "testland"} and manifest["generated_at"] == "2026-01-02T00:00:00+00:00"
    assert (tmp_path / "testland" / "units.json").exists() and (tmp_path / "testland" / "units" / "lt.json").exists()
    assert len(paths) == 2 + 1 + 3
    again = sitedata.write_site(site, tmp_path, "testland", "2026-01-03T00:00:00+00:00")
    assert [r["id"] for r in json.loads((tmp_path / "regions.json").read_text())["regions"]] == ["other", "testland"]
```

The merge tests deliberately put a partial `other` region in the existing files: the merge keeps foreign entries byte-for-byte and validates only the whole document's shape for the region it writes; `regions.schema.json` therefore lists required fields for every entry, so make the `other` entry in the test complete enough to validate, or relax the test fixture to a full entry. Decide by what the schema requires and keep the schema strict (every field the site needs is required).

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_publish_sitedata.py -q`
Expected: FAIL, `ImportError: cannot import name 'sitedata'`.

- [ ] **Step 4: Write the schemas**

`pipeline/poles/schemas/regions.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "regions.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "regions"],
  "properties": {
    "schema_version": {"const": 1},
    "regions": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["id", "name", "snapshot", "unit_level", "units_count", "r2_base", "class_edges", "max_distance_m",
                     "edge_mask_m", "detail_res_m", "detail_window_m"],
        "properties": {
          "id": {"type": "string", "pattern": "^[a-z][a-z0-9-]*$"},
          "name": {"type": "string"},
          "snapshot": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
          "unit_level": {"type": "integer"},
          "units_count": {"type": "integer"},
          "r2_base": {"type": "string", "pattern": "^https://"},
          "class_edges": {"type": "array", "minItems": 254, "maxItems": 254, "items": {"type": "integer"}},
          "max_distance_m": {"type": "number"},
          "edge_mask_m": {"type": "number"},
          "detail_res_m": {"type": "number"},
          "detail_window_m": {"type": "number"}
        }
      }
    }
  }
}
```

`units.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "<region>/units.json",
  "$defs": {
    "summary": {
      "type": ["object", "null"],
      "additionalProperties": false,
      "required": ["dist_m", "lat", "lon", "rank", "withheld"],
      "properties": {
        "dist_m": {"type": "number"}, "lat": {"type": "number"}, "lon": {"type": "number"},
        "rank": {"type": "integer", "minimum": 1}, "withheld": {"type": "integer", "minimum": 0}
      }
    }
  },
  "type": "object",
  "additionalProperties": false,
  "required": ["region", "snapshot", "units"],
  "properties": {
    "region": {"type": "string"},
    "snapshot": {"type": "string"},
    "units": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["code", "name", "name_en", "country", "area_km2", "bbox", "transcontinental", "closed_by_edge", "A", "B"],
        "properties": {
          "code": {"type": "string"}, "name": {"type": "string"}, "name_en": {"type": "string"},
          "country": {"type": ["string", "null"]}, "area_km2": {"type": "number"},
          "bbox": {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "number"}},
          "transcontinental": {"type": "boolean"}, "closed_by_edge": {"type": "boolean"},
          "A": {"$ref": "#/$defs/summary"}, "B": {"$ref": "#/$defs/summary"}
        }
      }
    }
  }
}
```

`unit.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "<region>/units/<code>.json",
  "$defs": {
    "pole": {
      "type": "object",
      "additionalProperties": false,
      "required": ["rank", "lat", "lon", "dist_m", "nearest_way", "nearest_place", "detail", "warnings"],
      "properties": {
        "rank": {"type": "integer", "minimum": 1}, "lat": {"type": "number"}, "lon": {"type": "number"},
        "dist_m": {"type": "number"},
        "nearest_way": {"type": "object", "required": ["id", "highway"], "properties": {
          "id": {"type": "integer"}, "highway": {"type": "string"}, "name": {"type": ["string", "null"]},
          "ref": {"type": ["string", "null"]}, "country": {"type": ["string", "null"]}}},
        "nearest_place": {"type": ["object", "null"], "required": ["name", "type", "dist_m", "lat", "lon"], "properties": {
          "name": {"type": "string"}, "type": {"type": "string"}, "dist_m": {"type": "number"},
          "lat": {"type": "number"}, "lon": {"type": "number"}}},
        "detail": {"type": "string", "pattern": "^detail/[a-z0-9-]+/[AB]-[0-9]+$"},
        "warnings": {"type": "array", "items": {"type": "string"}}
      }
    },
    "scenario": {
      "type": "object",
      "additionalProperties": false,
      "required": ["poles", "withheld", "reason"],
      "properties": {
        "poles": {"type": "array", "items": {"$ref": "#/$defs/pole"}},
        "withheld": {"type": "integer", "minimum": 0},
        "reason": {"type": ["string", "null"]}
      }
    }
  },
  "type": "object",
  "additionalProperties": false,
  "required": ["region", "snapshot", "code", "name", "name_en", "country", "area_km2", "bbox", "transcontinental",
               "closed_by_edge", "A", "B"],
  "properties": {
    "region": {"type": "string"}, "snapshot": {"type": "string"}, "code": {"type": "string"},
    "name": {"type": "string"}, "name_en": {"type": "string"}, "country": {"type": ["string", "null"]},
    "area_km2": {"type": "number"},
    "bbox": {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "number"}},
    "transcontinental": {"type": "boolean"}, "closed_by_edge": {"type": "boolean"},
    "A": {"$ref": "#/$defs/scenario"}, "B": {"$ref": "#/$defs/scenario"}
  }
}
```

`manifest.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "manifest.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "generated_at", "regions"],
  "properties": {
    "schema_version": {"const": 1},
    "generated_at": {"type": "string"},
    "regions": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "additionalProperties": false,
        "required": ["snapshot", "published_at", "r2_base", "pipeline_commit", "sources", "archives", "detail", "validation", "verified"],
        "properties": {
          "snapshot": {"type": "string"},
          "published_at": {"type": "string"},
          "r2_base": {"type": "string"},
          "pipeline_commit": {"type": ["string", "null"]},
          "sources": {"type": "array", "items": {"type": "object", "required": ["url", "role", "file", "size", "md5", "sha256", "last_modified"]}},
          "archives": {"type": "object", "additionalProperties": {"type": "object", "required": ["key", "bytes", "tiles", "min_zoom", "max_zoom"]}},
          "detail": {"type": "object", "required": ["count", "bytes"]},
          "validation": {"type": "object", "required": ["report", "report_html", "contact_sheet"]},
          "verified": {"type": "object", "required": ["at", "keys", "range_ok"]}
        }
      }
    }
  }
}
```

The `other` region in `test_write_site_merges_other_regions` must then be a complete entry to pass validation: give it the same fields as a real entry (copy `REGION` with `id: "other"` plus `units_count`, `class_edges`, and for the manifest a full entry with empty `archives`), so the test exercises the merge without bypassing the schema.

- [ ] **Step 5: Implement the module**

`pipeline/poles/publish/sitedata.py`:

```python
"""The site's JSON contract (spec 4.2): exclusions applied, ranks renumbered, geodesic unit areas, four documents
validated against the frozen schemas in poles/schemas and merged per region with what the site already holds."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path

import shapely
from jsonschema import Draft202012Validator
from pyogrio.raw import read
from pyproj import Geod
from shapely.geometry.base import BaseGeometry

from ..classes import ClassTable
from ..classify import SCENARIOS
from ..errors import PolesError

SCHEMA_VERSION = 1
SCHEMAS = Path(__file__).resolve().parent.parent / "schemas"
GEOD = Geod(ellps="WGS84")


@dataclass(frozen=True)
class SiteData:
    regions_entry: dict
    units_doc: dict
    unit_docs: dict[str, dict]
    manifest_entry: dict


def apply_exclusions(poles: dict[str, list[dict]], excluded: list[dict]) -> dict[str, list[dict]]:
    """Validation's refused poles leave the published set; the rest renumber from 1 within their unit (#21)."""
    drop = {(e["scenario"], e["unit"], int(e["rank"])) for e in excluded}
    seen = set()
    out: dict[str, list[dict]] = {}
    for scenario, units in poles.items():
        out[scenario] = []
        for u in units:
            kept = []
            for p in sorted(u["poles"], key=lambda p: p["rank"]):
                key = (scenario, u["unit"], int(p["rank"]))
                if key in drop:
                    seen.add(key)
                    continue
                kept.append(dict(copy.deepcopy(p), rank=len(kept) + 1))
            out[scenario].append({"unit": u["unit"], "poles": kept, "reason": u.get("reason"),
                                  "withheld": len(u["poles"]) - len(kept)})
    missing = sorted(drop - seen)
    if missing:
        raise PolesError(f"validate/report.json excludes poles that are not in poles/<scenario>.json: {missing}; rerun validate")
    return out


def unit_area_km2(geom: BaseGeometry) -> float:
    area, _ = GEOD.geometry_area_perimeter(geom)
    return round(abs(area) / 1e6, 1)


def unit_geometries(units_fgb: Path) -> dict[str, BaseGeometry]:
    _, _, wkb, fields = read(str(units_fgb), layer="units", columns=["code"])
    return {code: shapely.from_wkb(g) for code, g in zip(fields[0], wkb)}


def regional_ranks(published_scenario: list[dict]) -> dict[str, int]:
    best = [(u["poles"][0]["dist_m"], u["unit"]) for u in published_scenario if u["poles"]]
    best.sort(key=lambda t: (-t[0], t[1]))
    ranks, rank, prev = {}, 0, None
    for dist, code in best:
        if dist != prev:
            rank += 1
            prev = dist
        ranks[code] = rank
    return ranks


def _unit_summary(unit: dict, rank: int | None) -> dict | None:
    if not unit["poles"]:
        return None
    top = unit["poles"][0]
    return {"dist_m": top["dist_m"], "lat": top["lat"], "lon": top["lon"], "rank": rank, "withheld": unit["withheld"]}


def build(region: dict, units_meta: list[dict], geoms: dict[str, BaseGeometry], published: dict[str, list[dict]],
          table: ClassTable, archives: dict, detail_meta: dict, verify_meta: dict, sources: list[dict],
          generated_at: str, pipeline_commit: str | None) -> SiteData:
    rid, snapshot = region["id"], region["snapshot"]
    by_unit = {s: {u["unit"]: u for u in published[s]} for s in SCENARIOS}
    ranks = {s: regional_ranks(published[s]) for s in SCENARIOS}
    units_rows, unit_docs = [], {}
    for m in units_meta:
        code = m["code"]
        base = {"code": code, "name": m["name"], "name_en": m["name_en"], "country": m["country"],
                "area_km2": unit_area_km2(geoms[code]), "bbox": m["bbox"],
                "transcontinental": bool(m["transcontinental"]), "closed_by_edge": bool(m["closed_by_edge"])}
        row = dict(base)
        doc = {"region": rid, "snapshot": snapshot, **base}
        for s in SCENARIOS:
            u = by_unit[s].get(code, {"unit": code, "poles": [], "reason": "not searched", "withheld": 0})
            row[s] = _unit_summary(u, ranks[s].get(code))
            poles = [dict(p, detail=f"detail/{code}/{s}-{p['rank']}") for p in u["poles"]]
            doc[s] = {"poles": poles, "withheld": u["withheld"], "reason": u["reason"]}
        units_rows.append(row)
        unit_docs[code] = doc
    regions_entry = {"id": rid, "name": region["name"], "snapshot": snapshot, "unit_level": region["unit_level"],
                     "units_count": len(units_meta), "r2_base": region["r2_base"], "class_edges": list(table.edges),
                     "max_distance_m": region["max_distance_m"], "edge_mask_m": region["edge_mask_m"],
                     "detail_res_m": region["detail_res_m"], "detail_window_m": region["detail_window_m"]}
    prefix = f"{rid}/{snapshot}"
    manifest_entry = {"snapshot": snapshot, "published_at": generated_at, "r2_base": region["r2_base"],
                      "pipeline_commit": pipeline_commit, "sources": [dict(s) for s in sources],
                      "archives": {s: {"key": f"{prefix}/{a['key_name']}", "bytes": a["bytes"], "tiles": a["tiles"],
                                       "min_zoom": a["min_zoom"], "max_zoom": a["max_zoom"]} for s, a in archives.items()},
                      "detail": {"count": detail_meta["count"], "bytes": detail_meta["bytes"]},
                      "validation": {"report": f"{prefix}/validation/report.json", "report_html": f"{prefix}/validation/report.html",
                                     "contact_sheet": f"{prefix}/validation/contact-sheet.html"},
                      "verified": dict(verify_meta)}
    return SiteData(regions_entry, {"region": rid, "snapshot": snapshot, "units": units_rows}, unit_docs, manifest_entry)


def merge_regions(existing: dict | None, entry: dict) -> dict:
    regions = [r for r in (existing or {}).get("regions", []) if r.get("id") != entry["id"]]
    return {"schema_version": SCHEMA_VERSION, "regions": regions + [entry]}


def merge_manifest(existing: dict | None, region_id: str, entry: dict, generated_at: str) -> dict:
    regions = dict((existing or {}).get("regions", {}))
    regions[region_id] = entry
    return {"schema_version": SCHEMA_VERSION, "generated_at": generated_at, "regions": regions}


_validators: dict[str, Draft202012Validator] = {}


def validate_doc(name: str, doc: dict) -> None:
    if name not in _validators:
        schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        _validators[name] = Draft202012Validator(schema)
    err = next(iter(sorted(_validators[name].iter_errors(doc), key=lambda e: list(e.path))), None)
    if err is not None:
        where = "/".join(str(p) for p in err.path) or "<root>"
        raise PolesError(f"{name}.schema.json: {where}: {err.message}")


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise PolesError(f"{path}: not JSON ({exc}); fix or remove it before publishing") from exc


def _dump(path: Path, doc: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def write_site(site: SiteData, out_dir: Path, region_id: str, generated_at: str) -> list[Path]:
    regions = merge_regions(_read_json(out_dir / "regions.json"), site.regions_entry)
    manifest = merge_manifest(_read_json(out_dir / "manifest.json"), region_id, site.manifest_entry, generated_at)
    validate_doc("regions", regions)
    validate_doc("manifest", manifest)
    validate_doc("units", site.units_doc)
    for doc in site.unit_docs.values():
        validate_doc("unit", doc)
    written = [_dump(out_dir / "regions.json", regions), _dump(out_dir / "manifest.json", manifest),
               _dump(out_dir / region_id / "units.json", site.units_doc)]
    for code, doc in site.unit_docs.items():
        written.append(_dump(out_dir / region_id / "units" / f"{code}.json", doc))
    return written
```

`indent=1` keeps the unit files small but diffable. If `pyogrio.raw.read` with `columns=["code"]` returns fields in a different shape than `fields[0]`, adapt to what it returns (look at `poles._units_from_fgb`).

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_publish_sitedata.py -q`
Expected: 7 passed. Then `.venv/bin/python -m pytest -q` for the whole suite (no regressions from the new dependency).

- [ ] **Step 7: Commit**

```bash
git add pipeline/poles/publish/sitedata.py pipeline/poles/schemas pipeline/tests/test_publish_sitedata.py pipeline/requirements.txt pipeline/pyproject.toml
git commit -m "publish: site JSON documents with validation's exclusions applied, geodesic unit areas and frozen schemas (#20, #21)"
```

(Leave `pipeline/pyproject.toml` out of the `git add` if it did not need a change.)

---

### Task 6: R2 configuration, bucket setup, upload, verification

**Files:**
- Create: `pipeline/poles/publish/r2.py`
- Modify: `pipeline/requirements.txt` (add `boto3` and `moto` pinned, plus their new transitive pins)
- Test: `pipeline/tests/test_publish_r2.py`

**Interfaces:**
- Consumes: `poles.errors.PolesError`.
- Produces:
  - `class PublishError(PolesError)`.
  - `R2Config` frozen dataclass `(account_id, bucket, base: str | None, token_file: Path, key_id_file: Path, secret_file: Path)`; `R2Config.from_env(env: Mapping[str, str]) -> R2Config` raises `PublishError` listing every missing variable; `ENV_NAMES` dict; `read_secret(path: Path) -> str` (stripped, `PublishError` when missing or empty).
  - `ensure_bucket(cfg: R2Config, log, api_base: str = API_BASE) -> str`: create bucket (existing is fine), enable the managed `r2.dev` domain, set CORS; returns `https://<managed domain>`; `PublishError` when `cfg.base` is set and differs.
  - `s3_client(cfg: R2Config, endpoint_url: str | None = None)`.
  - `content_type(path: Path) -> str`; `CACHE_CONTROL`.
  - `upload_tree(client, bucket: str, items: list[tuple[Path, str]], log, workers: int = 8) -> dict` `{"uploaded": n, "skipped": n, "bytes": n}`.
  - `verify_head(base: str, keys: list[str], range_keys: list[str], log, workers: int = 8) -> dict` `{"at": iso, "keys": n, "range_ok": n}`; `PublishError` listing the first failures.

- [ ] **Step 1: Add the dependencies**

Run: `cd pipeline && uv pip install --python .venv/bin/python boto3 "moto[s3]"`, then pin `boto3`, `botocore`, `moto`, and every other new package from `uv pip freeze` into `requirements.txt` (sorted as the file is). Expected: `.venv/bin/python -c "import boto3, moto; print(boto3.__version__, moto.__version__)"` prints both.

- [ ] **Step 2: Write the failing tests**

`pipeline/tests/test_publish_r2.py`:

```python
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from poles.publish import r2
from poles.publish.r2 import PublishError, R2Config


def _files(tmp_path):
    for name, value in [("token", "tok-123"), ("key", "AKIAEXAMPLE"), ("secret", "s3cr3t")]:
        (tmp_path / name).write_text(value + "\n")
    return {"POLES_R2_ACCOUNT_ID": "acct", "POLES_R2_BUCKET": "poles-test", "POLES_R2_TOKEN_FILE": str(tmp_path / "token"),
            "POLES_R2_ACCESS_KEY_ID_FILE": str(tmp_path / "key"), "POLES_R2_SECRET_FILE": str(tmp_path / "secret")}


def test_config_from_env_names_every_missing_variable(tmp_path):
    with pytest.raises(PublishError) as exc:
        R2Config.from_env({})
    for name in ("POLES_R2_ACCOUNT_ID", "POLES_R2_BUCKET", "POLES_R2_TOKEN_FILE", "POLES_R2_ACCESS_KEY_ID_FILE", "POLES_R2_SECRET_FILE"):
        assert name in str(exc.value)
    cfg = R2Config.from_env(_files(tmp_path))
    assert cfg.bucket == "poles-test" and cfg.base is None and r2.read_secret(cfg.token_file) == "tok-123"
    with pytest.raises(PublishError, match="secret"):
        r2.read_secret(tmp_path / "nope")


class _Api(BaseHTTPRequestHandler):
    calls: list = []

    def _reply(self, result):
        body = json.dumps({"success": True, "errors": [], "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        _Api.calls.append(("POST", self.path, self.headers.get("Authorization"), json.loads(self.rfile.read(n) or b"{}")))
        self._reply({"name": "poles-test"})

    def do_PUT(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        _Api.calls.append(("PUT", self.path, self.headers.get("Authorization"), body))
        self._reply({"domain": "pub-abc.r2.dev", "enabled": True} if "domains" in self.path else {})

    def log_message(self, *a):
        pass


@pytest.fixture
def api():
    _Api.calls = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Api)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", _Api.calls
    finally:
        server.shutdown()
        t.join()
        server.server_close()


def test_ensure_bucket_creates_enables_domain_and_cors(tmp_path, api, log):
    base_url, calls = api
    cfg = R2Config.from_env(_files(tmp_path))
    base = r2.ensure_bucket(cfg, log, api_base=base_url)
    assert base == "https://pub-abc.r2.dev"
    assert [c[:2] for c in calls] == [("POST", "/accounts/acct/r2/buckets"),
                                      ("PUT", "/accounts/acct/r2/buckets/poles-test/domains/managed"),
                                      ("PUT", "/accounts/acct/r2/buckets/poles-test/cors")]
    assert all(c[2] == "Bearer tok-123" for c in calls)
    assert calls[0][3] == {"name": "poles-test"} and calls[1][3] == {"enabled": True}
    rule = calls[2][3]["rules"][0]
    assert rule["allowed"]["origins"] == ["*"] and set(rule["allowed"]["methods"]) == {"GET", "HEAD"}
    assert "Accept-Ranges" in rule["exposeHeaders"] and "Content-Range" in rule["exposeHeaders"]


def test_ensure_bucket_refuses_a_base_mismatch(tmp_path, api, log):
    base_url, _ = api
    env = dict(_files(tmp_path), POLES_R2_BASE="https://data.example.org")
    with pytest.raises(PublishError, match="pub-abc.r2.dev"):
        r2.ensure_bucket(R2Config.from_env(env), log, api_base=base_url)


@mock_aws
def test_upload_tree_skips_same_size_and_sets_headers(tmp_path, log):
    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket="b")
    a, b = tmp_path / "A.pmtiles", tmp_path / "x.json"
    a.write_bytes(b"\x00" * 1000)
    b.write_text("{}")
    items = [(a, "r/s/A.pmtiles"), (b, "r/s/x.json")]
    first = r2.upload_tree(client, "b", items, log)
    assert first == {"uploaded": 2, "skipped": 0, "bytes": 1002}
    head = client.head_object(Bucket="b", Key="r/s/A.pmtiles")
    assert head["ContentType"] == "application/octet-stream" and head["CacheControl"] == r2.CACHE_CONTROL
    assert client.head_object(Bucket="b", Key="r/s/x.json")["ContentType"] == "application/json"
    second = r2.upload_tree(client, "b", items, log)
    assert second == {"uploaded": 0, "skipped": 2, "bytes": 0}
    b.write_text('{"changed": true}')
    third = r2.upload_tree(client, "b", items, log)
    assert third == {"uploaded": 1, "skipped": 1, "bytes": len('{"changed": true}')}


def test_content_types():
    assert r2.content_type(Path("a.png")) == "image/png"
    assert r2.content_type(Path("a.html")) == "text/html; charset=utf-8"
    assert r2.content_type(Path("a.pmtiles")) == "application/octet-stream"


def test_verify_head_checks_every_key_and_ranges(http_server, log):
    base, docroot, requests = http_server
    (docroot / "r").mkdir()
    (docroot / "r" / "A.pmtiles").write_bytes(b"\x01" * 40_000)
    (docroot / "r" / "u.json").write_text("{}")
    out = r2.verify_head(base, ["r/A.pmtiles", "r/u.json"], ["r/A.pmtiles"], log)
    assert out["keys"] == 2 and out["range_ok"] == 1 and out["at"].endswith("+00:00")
    assert ("HEAD", "/r/A.pmtiles", None) in requests and ("GET", "/r/A.pmtiles", "bytes=0-16383") in requests
    with pytest.raises(PublishError, match="r/missing.png"):
        r2.verify_head(base, ["r/A.pmtiles", "r/missing.png"], [], log)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_publish_r2.py -q`
Expected: FAIL, `ImportError: cannot import name 'r2'`.

- [ ] **Step 4: Implement the module**

`pipeline/poles/publish/r2.py`:

```python
"""R2: bucket setup through Cloudflare's REST API (admin token), uploads through the S3 API (access key pair),
verification through the public URL. Configuration comes from the environment, secrets from files it names;
nothing here is region-specific and nothing is ever written into the repository."""
from __future__ import annotations

import json
import logging
import mimetypes
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from ..errors import PolesError

API_BASE = "https://api.cloudflare.com/client/v4"
CACHE_CONTROL = "public, max-age=31536000, immutable"
ENV_NAMES = {"account_id": "POLES_R2_ACCOUNT_ID", "bucket": "POLES_R2_BUCKET", "token_file": "POLES_R2_TOKEN_FILE",
             "key_id_file": "POLES_R2_ACCESS_KEY_ID_FILE", "secret_file": "POLES_R2_SECRET_FILE"}
ENV_BASE = "POLES_R2_BASE"
CONTENT_TYPES = {".pmtiles": "application/octet-stream", ".png": "image/png", ".json": "application/json",
                 ".html": "text/html; charset=utf-8"}
RANGE_BYTES = 16384


class PublishError(PolesError):
    pass


@dataclass(frozen=True)
class R2Config:
    account_id: str
    bucket: str
    base: str | None
    token_file: Path
    key_id_file: Path
    secret_file: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "R2Config":
        missing = [name for name in ENV_NAMES.values() if not env.get(name)]
        if missing:
            raise PublishError("R2 is not configured; set " + ", ".join(missing)
                               + " (the *_FILE variables name files holding the secrets; see pipeline/README.md)")
        base = env.get(ENV_BASE) or None
        return cls(env[ENV_NAMES["account_id"]], env[ENV_NAMES["bucket"]], base.rstrip("/") if base else None,
                   Path(env[ENV_NAMES["token_file"]]), Path(env[ENV_NAMES["key_id_file"]]), Path(env[ENV_NAMES["secret_file"]]))


def read_secret(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise PublishError(f"secret file {path} is unreadable ({exc.strerror})") from exc
    if not value:
        raise PublishError(f"secret file {path} is empty")
    return value


def _api(method: str, url: str, token: str, body: dict | None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        payload = json.loads(exc.read() or b"{}") if exc.headers.get("Content-Type", "").startswith("application/json") else {}
        codes = [e.get("code") for e in payload.get("errors", [])]
        if method == "POST" and url.endswith("/r2/buckets") and 10004 in codes:
            return payload                         # bucket already exists
        raise PublishError(f"{method} {url}: HTTP {exc.code} {payload.get('errors') or exc.reason}") from exc
    if not payload.get("success", True):
        raise PublishError(f"{method} {url}: {payload.get('errors')}")
    return payload


def ensure_bucket(cfg: R2Config, log: logging.Logger, api_base: str = API_BASE) -> str:
    token = read_secret(cfg.token_file)
    buckets = f"{api_base}/accounts/{cfg.account_id}/r2/buckets"
    _api("POST", buckets, token, {"name": cfg.bucket})
    domain = _api("PUT", f"{buckets}/{cfg.bucket}/domains/managed", token, {"enabled": True})
    managed = (domain.get("result") or {}).get("domain")
    if not managed:
        raise PublishError(f"managed domain response without a domain: {domain}")
    _api("PUT", f"{buckets}/{cfg.bucket}/cors", token, {"rules": [{
        "allowed": {"origins": ["*"], "methods": ["GET", "HEAD"], "headers": ["*"]},
        "exposeHeaders": ["Content-Length", "Content-Range", "ETag", "Accept-Ranges"], "maxAgeSeconds": 86400}]})
    base = f"https://{managed}"
    if cfg.base and cfg.base != base:
        raise PublishError(f"{ENV_BASE} is {cfg.base} but the bucket's managed domain is {base}")
    log.info("publish: bucket %s ready at %s", cfg.bucket, base)
    return base


def s3_client(cfg: R2Config, endpoint_url: str | None = None):
    return boto3.client("s3", endpoint_url=endpoint_url or f"https://{cfg.account_id}.r2.cloudflarestorage.com",
                        aws_access_key_id=read_secret(cfg.key_id_file), aws_secret_access_key=read_secret(cfg.secret_file),
                        region_name="auto", config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}))


def content_type(path: Path) -> str:
    return CONTENT_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _upload_one(client, bucket: str, path: Path, key: str) -> tuple[bool, int]:
    size = path.stat().st_size
    try:
        head = client.head_object(Bucket=bucket, Key=key)
        if head["ContentLength"] == size:
            return False, 0
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchKey", "NotFound"):
            raise
    client.upload_file(str(path), bucket, key, ExtraArgs={"ContentType": content_type(path), "CacheControl": CACHE_CONTROL})
    return True, size


def upload_tree(client, bucket: str, items: list[tuple[Path, str]], log: logging.Logger, workers: int = 8) -> dict:
    stats = {"uploaded": 0, "skipped": 0, "bytes": 0}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for done, size in pool.map(lambda it: _upload_one(client, bucket, it[0], it[1]), items):
            stats["uploaded" if done else "skipped"] += 1
            stats["bytes"] += size
    log.info("publish: upload to %s: %s", bucket, stats)
    return stats


def _head(url: str) -> tuple[int, dict]:
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers)


def _range(url: str) -> int:
    req = urllib.request.Request(url, headers={"Range": f"bytes=0-{RANGE_BYTES - 1}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status if len(resp.read()) == RANGE_BYTES else 0
    except urllib.error.HTTPError as exc:
        return exc.code


def verify_head(base: str, keys: list[str], range_keys: list[str], log: logging.Logger, workers: int = 8) -> dict:
    """Spec check 7: every published key answers HEAD 200; the archives answer a 16 KiB range with 206."""
    failures = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for key, (status, _) in zip(keys, pool.map(lambda k: _head(f"{base}/{k}"), keys)):
            if status != 200:
                failures.append(f"HEAD {key}: {status}")
        range_ok = 0
        for key, status in zip(range_keys, pool.map(lambda k: _range(f"{base}/{k}"), range_keys)):
            if status == 206:
                range_ok += 1
            else:
                failures.append(f"RANGE {key}: {status}")
    if failures:
        raise PublishError(f"{len(failures)} of {len(keys) + len(range_keys)} checks failed: " + "; ".join(failures[:10]))
    out = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "keys": len(keys), "range_ok": range_ok}
    log.info("publish: verified %d keys and %d ranges at %s", len(keys), range_ok, base)
    return out
```

Cloudflare's bucket-exists error code is 10004 in the R2 API today; if the live run in Task 8 shows a different code, treat "already exists" by message too and note it in DECISIONS. moto answers `head_object` on a missing key with code `404`; real R2 also answers `404`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_publish_r2.py -q`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add pipeline/poles/publish/r2.py pipeline/tests/test_publish_r2.py pipeline/requirements.txt
git commit -m "publish: R2 configuration from the environment, bucket setup over the REST API, S3 uploads with immutable headers, HEAD and range verification"
```

---

### Task 7: The publish stage, CLI flags, end-to-end test

**Files:**
- Modify: `pipeline/poles/publish/__init__.py` (the stage), `pipeline/poles/stages.py` (register), `pipeline/poles/cli.py` (`--site-dir`, `--no-write-site`), `pipeline/poles/workspace.py` (`site_dir` attribute)
- Test: `pipeline/tests/test_publish_stage.py`

**Interfaces:**
- Consumes: everything from Tasks 1 to 6 by the names given there; `validate.load_poles`; `grid.Frame.from_dict` on `grid/frame.json`; `fetch/snapshot.json`; `poles/units.json`, `units.fgb`, `land_idx.fgb`, `water_big.fgb`, `roads/`; `validate/report.json`, `report.html`, `contact-sheet.html`.
- Produces: `poles.publish.run(cfg, ws, log) -> dict`; `poles.publish.upload_set(ws, region_id, snapshot) -> list[tuple[Path, str]]`; `Workspace.site_dir: Path | None`; CLI `run` gains `--site-dir PATH` (default `$POLES_SITE_DIR` or `<repo>/site/data`, i.e. `Path(poles.__file__).resolve().parents[2] / "site" / "data"`) and `--no-write-site`.

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_publish_stage.py` builds a tiny but complete workspace. Use the real frame of `test_publish_raster.py` (40 by 32 cells at 250 m in EPSG:3035 near 24E 55N), one unit `lt` whose polygon covers the middle of the frame, one road, two poles per scenario, one exclusion, a road tile set built with `poles.roads.build_tiles`:

```python
import dataclasses
import json
import logging
import os
from pathlib import Path

import numpy as np
import pytest
import rasterio
import shapely
from pyproj import Transformer
from shapely.geometry import LineString, box

from poles.config import load_config
from poles.grid import Frame, create_raster
from poles.publish import r2 as r2mod
from poles import publish
from poles.roads import build_tiles
from poles.workspace import Workspace
from tests.helpers import write_fgb

FRAME = Frame(crs="EPSG:3035", res=250, x0=5_300_000, y1=3_660_000, width=40, height=32)


def _pole(rank, lat, lon, dist):
    return {"rank": rank, "lat": lat, "lon": lon, "dist_m": dist,
            "nearest_way": {"id": 1, "highway": "track", "name": None, "ref": None, "country": "lt"},
            "nearest_place": {"name": "Kaunas", "type": "city", "dist_m": 5000.0, "lat": 54.9, "lon": 23.9},
            "detail": None, "warnings": []}


@pytest.fixture
def workspace(tmp_path, regions_dir):
    cfg = dataclasses.replace(load_config(regions_dir / "europe.yaml"), edge_mask_m=1_000)   # the 10 km test frame must not be all edge band
    ws = Workspace(tmp_path / "work", cfg.id, "2026-01-01")
    to_ll = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    # fetch: one source polygon covering the frame minus a 1 km rim
    fetch = ws.dir("fetch")
    rim = box(FRAME.x0 + 1_000, FRAME.y0 + 1_000, FRAME.x1 - 1_000, FRAME.y1 - 1_000)
    ring = [to_ll.transform(x, y) for x, y in rim.exterior.coords]
    (fetch / "r.poly").write_text("r\n1\n" + "".join(f"  {lon} {lat}\n" for lon, lat in ring) + "END\nEND\n")
    (fetch / "snapshot.json").write_text(json.dumps({"region": cfg.id, "snapshot": "2026-01-01", "created_at": "x", "sources": [
        {"url": "https://example.org/r.pbf", "role": "primary", "file": "r.pbf", "size": 1, "md5": "m", "sha256": "s",
         "last_modified": "2026-01-01T00:00:00+00:00", "poly": "r.poly"}]}))
    # grid: distances rising northwards from a road along the southern frame edge; all land
    grid = ws.dir("grid")
    (grid / "frame.json").write_text(json.dumps(FRAME.to_dict()))
    rows = (np.arange(FRAME.height)[::-1] + 0.5) * FRAME.res
    dist = np.repeat(rows[:, None], FRAME.width, axis=1).astype(np.float32)
    for name in ("dist_A", "dist_B"):
        create_raster(FRAME, grid / f"{name}.tif", "float32", None)
        with rasterio.open(grid / f"{name}.tif", "r+") as ds:
            ds.write(dist, 1)
    create_raster(FRAME, grid / "land.tif", "uint8", None)
    with rasterio.open(grid / "land.tif", "r+") as ds:
        ds.write(np.ones((FRAME.height, FRAME.width), np.uint8), 1)
    # poles: unit lt in the middle, road along the south edge, two poles per scenario
    poles_dir = ws.dir("poles")
    unit_3035 = box(FRAME.x0 + 2_000, FRAME.y0 + 2_000, FRAME.x1 - 2_000, FRAME.y1 - 2_000)
    unit = shapely.transform(unit_3035, lambda c: np.column_stack(to_ll.transform(c[:, 0], c[:, 1])))
    write_fgb(poles_dir / "units.fgb", "units", [shapely.MultiPolygon([unit])],
              {"code": ["lt"], "name": ["Lietuva"], "name_en": ["Lithuania"], "osm_id": [72596], "country": ["lt"], "idx": [1],
               "transcontinental": [0], "closed_by_edge": [0]})
    (poles_dir / "units.json").write_text(json.dumps({"units": [{
        "code": "lt", "name": "Lietuva", "name_en": "Lithuania", "osm_id": 72596, "country": "lt", "index": 1, "area_km2": 1.0,
        "cells": 10, "transcontinental": False, "closed_by_edge": False, "bbox": list(unit.bounds), "window": [0, 0, 1, 1]}]}))
    land = shapely.transform(box(FRAME.x0, FRAME.y0, FRAME.x1, FRAME.y1), lambda c: np.column_stack(to_ll.transform(c[:, 0], c[:, 1])))
    write_fgb(poles_dir / "land_idx.fgb", "land", [land], {"id": [1]})
    write_fgb(poles_dir / "water_big.fgb", "water", [box(0, 0, 0.001, 0.001)], {"id": [1]})
    road = shapely.transform(LineString([(FRAME.x0 - 50_000, FRAME.y0), (FRAME.x1 + 50_000, FRAME.y0)]),
                             lambda c: np.column_stack(to_ll.transform(c[:, 0], c[:, 1])))
    write_fgb(poles_dir / "roads_src.fgb", "highways", [road], {"osm_id": [1], "highway": ["track"], "name": [None], "ref": [None]})
    build_tiles(poles_dir / "roads_src.fgb", "highways", poles_dir / "roads", logging.getLogger("t"), tile_deg=5.0)
    cx, cy = unit_3035.centroid.x, FRAME.y1 - 3_000
    lon1, lat1 = to_ll.transform(cx, cy)
    lon2, lat2 = to_ll.transform(cx + 1_000, cy - 500)
    d1, d2 = cy - FRAME.y0, cy - 500 - FRAME.y0
    for s in ("A", "B"):
        (poles_dir / f"{s}.json").write_text(json.dumps([{"unit": "lt", "poles": [_pole(1, lat1, lon1, d1), _pole(2, lat2, lon2, d2)], "reason": None}]))
    ws.mark_done("poles", {})
    # validate: rank 1 of scenario B withheld
    val = ws.dir("validate")
    (val / "report.json").write_text(json.dumps({"region": cfg.id, "snapshot": "2026-01-01", "generated_at": "x", "summary": {}, "results": [],
                                                 "excluded": [{"unit": "lt", "scenario": "B", "rank": 1, "lat": lat1, "lon": lon1, "dist_m": d1, "details": {}}]}))
    (val / "report.html").write_text("<p>report</p>")
    (val / "contact-sheet.html").write_text("<p>sheet</p>")
    ws.mark_done("validate", {})
    return cfg, ws


def test_refuses_without_validate(tmp_path, regions_dir, log):
    cfg = load_config(regions_dir / "europe.yaml")
    ws = Workspace(tmp_path / "work", cfg.id, "2026-01-01")
    with pytest.raises(Exception, match="validate"):
        publish.run(cfg, ws, log)


def test_builds_local_artefacts_then_names_the_missing_r2_config(workspace, log, monkeypatch):
    cfg, ws = workspace
    for name in r2mod.ENV_NAMES.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("POLES_WORKERS", "2")
    with pytest.raises(r2mod.PublishError, match="POLES_R2_ACCOUNT_ID"):
        publish.run(cfg, ws, log)
    out = ws.dir("publish")
    for name in ("explore_A.tif", "explore_A_3857.tif", "A.pmtiles", "explore_B.tif", "B.pmtiles"):
        assert (out / name).exists(), name
    assert (out / "detail" / "lt" / "A-1.png").exists() and (out / "detail" / "lt" / "A-2.json").exists()
    assert (out / "detail" / "lt" / "B-1.png").exists() and not (out / "detail" / "lt" / "B-2.png").exists()
    assert not ws.is_done("publish")
    with rasterio.open(out / "explore_A.tif") as ds:
        cls = ds.read(1)
    assert cls[16, 20] not in (254, 255) and cls[0, 20] == 255 and cls[2, 20] == 255   # rim outside the source polygon
    assert (out / "inside.tif.ok").exists()


def test_full_run_with_r2_mocked_writes_site_and_done(workspace, log, monkeypatch, tmp_path):
    cfg, ws = workspace
    for key, value in {"POLES_R2_ACCOUNT_ID": "acct", "POLES_R2_BUCKET": "b", "POLES_R2_TOKEN_FILE": str(tmp_path / "t"),
                       "POLES_R2_ACCESS_KEY_ID_FILE": str(tmp_path / "k"), "POLES_R2_SECRET_FILE": str(tmp_path / "s")}.items():
        monkeypatch.setenv(key, value)
    for f in ("t", "k", "s"):
        (tmp_path / f).write_text("x")
    monkeypatch.setenv("POLES_WORKERS", "2")
    uploaded, verified = [], {}
    monkeypatch.setattr(r2mod, "ensure_bucket", lambda cfg_, log_, api_base=None: "https://pub-test.r2.dev")
    monkeypatch.setattr(r2mod, "s3_client", lambda cfg_, endpoint_url=None: object())
    monkeypatch.setattr(r2mod, "upload_tree", lambda client, bucket, items, log_, workers=8: (uploaded.extend(items), {"uploaded": len(items), "skipped": 0, "bytes": 1})[1])
    monkeypatch.setattr(r2mod, "verify_head", lambda base, keys, range_keys, log_, workers=8: verified.update(base=base, keys=keys, range_keys=range_keys) or {"at": "2026-01-02T00:00:00+00:00", "keys": len(keys), "range_ok": len(range_keys)})
    ws.site_dir = tmp_path / "site_data"
    meta = publish.run(cfg, ws, log)
    keys = sorted(k for _, k in uploaded)
    assert f"{cfg.id}/2026-01-01/A.pmtiles" in keys and f"{cfg.id}/2026-01-01/detail/lt/A-1.png" in keys
    assert f"{cfg.id}/2026-01-01/validation/contact-sheet.html" in keys
    assert verified["base"] == "https://pub-test.r2.dev" and sorted(verified["keys"]) == keys
    assert verified["range_keys"] == [f"{cfg.id}/2026-01-01/A.pmtiles", f"{cfg.id}/2026-01-01/B.pmtiles"]
    site = ws.dir("publish") / "site"
    regions = json.loads((site / "regions.json").read_text())
    assert regions["regions"][0]["r2_base"] == "https://pub-test.r2.dev" and regions["regions"][0]["units_count"] == 1
    unit = json.loads((site / cfg.id / "units" / "lt.json").read_text())
    assert [p["rank"] for p in unit["B"]["poles"]] == [1] and unit["B"]["withheld"] == 1 and unit["A"]["withheld"] == 0
    assert unit["B"]["poles"][0]["detail"] == "detail/lt/B-1"
    assert (ws.site_dir / "regions.json").exists() and (ws.site_dir / cfg.id / "units.json").exists()
    assert meta["archives"]["A"]["max_zoom"] == 9 and meta["detail"]["count"] == 3 and meta["upload"]["uploaded"] == len(keys)
    assert meta["verify"]["keys"] == len(keys) and meta["r2_base"] == "https://pub-test.r2.dev"
    # the detail raster at the pole's own pixel agrees with the coarse grid to one class
    with rasterio.open(ws.dir("publish") / "detail" / "lt" / "A-1.png") as ds:
        arr = ds.read(1)
    from poles.classes import ClassTable
    d1 = json.loads((ws.dir("poles") / "A.json").read_text())[0]["poles"][0]["dist_m"]
    assert abs(int(arr[200, 200]) - int(ClassTable().to_class(d1))) <= 1


def test_cli_flags(monkeypatch):
    from poles.cli import build_parser
    args = build_parser().parse_args(["run", "europe", "--stage", "publish", "--site-dir", "/x/site/data", "--no-write-site"])
    assert args.site_dir == "/x/site/data" and args.no_write_site is True
    args = build_parser().parse_args(["run", "europe"])
    assert args.no_write_site is False and args.site_dir.endswith(os.path.join("site", "data"))
```

`test_refuses_without_validate` matches any exception mentioning `validate`; the stage raises `PolesError`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_publish_stage.py -q`
Expected: FAIL, `AttributeError: module 'poles.publish' has no attribute 'run'` (and the CLI test fails on the unknown flag).

- [ ] **Step 3: Implement the stage**

`pipeline/poles/publish/__init__.py`:

```python
"""Publish stage (spec 3.2 stage 7): explore archives, detail rasters, site JSON and manifest, uploaded to R2 and
verified, from the finished grid, poles and validate stages. Every artefact is behind a marker; the stage may be
rerun after any crash or after the R2 configuration appears and continues where it stopped."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import shapely

from ..classes import ClassTable
from ..classify import SCENARIOS
from ..config import RegionConfig
from ..errors import PolesError
from ..grid import Frame
from ..shell import dir_size, require_tools
from ..validate import load_poles
from ..workspace import Workspace
from . import detail, r2, raster, sitedata, tiles

MARKERS = raster.MARKER


def _clear_markers(out: Path, log: logging.Logger) -> None:
    gone = [p for p in out.glob(f"*{MARKERS}")]
    for p in gone:
        p.unlink()
    if gone:
        log.info("publish: forced, cleared %d sub-step marker(s)", len(gone))


def upload_set(ws: Workspace, region_id: str, snapshot: str) -> list[tuple[Path, str]]:
    out, prefix = ws.dir("publish"), f"{region_id}/{snapshot}"
    items = [(out / f"{s}.pmtiles", f"{prefix}/{s}.pmtiles") for s in SCENARIOS]
    for p in sorted((out / "detail").rglob("*")):
        if p.is_file() and p.suffix in (".png", ".json"):
            items.append((p, f"{prefix}/detail/{p.parent.name}/{p.name}"))
    val = ws.dir("validate")
    for name in ("report.json", "report.html", "contact-sheet.html"):
        items.append((val / name, f"{prefix}/validation/{name}"))
    return items


def _pipeline_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10,
                             cwd=Path(__file__).resolve().parent)
        return (out.stdout.strip() or None) if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def run(cfg: RegionConfig, ws: Workspace, log: logging.Logger) -> dict:
    require_tools(["gdalwarp", "gdal", "pmtiles"])
    if not ws.is_done("validate"):
        raise PolesError("publish needs a finished validate stage (validate/done.json is missing): run it first (#21)")
    out = ws.dir("publish")
    if ws.forced:
        _clear_markers(out, log)
    tools_log = out / "tools.log"
    t0 = time.monotonic()
    meta: dict = {}

    report = json.loads((ws.dir("validate") / "report.json").read_text(encoding="utf-8"))
    published = sitedata.apply_exclusions(load_poles(ws.dir("poles"), cfg.top_n), report["excluded"])
    meta["withheld"] = sum(u["withheld"] for s in SCENARIOS for u in published[s])
    table = ClassTable(cfg.class_table) if cfg.class_table else ClassTable()

    # 1. explore class rasters and archives
    frame = Frame.from_dict(json.loads((ws.dir("grid") / "frame.json").read_text(encoding="utf-8")))
    edge = raster.edge_polygon(ws.dir("fetch"))
    inside_tif, band_tif = raster.edge_masks(edge, frame, cfg.edge_mask_m, out, log, tools_log)
    meta["archives"], meta["raster"] = {}, {}
    for s in SCENARIOS:
        cls_tif = out / f"explore_{s}.tif"
        stats_path = out / f"explore_{s}.json"
        if not raster._done(cls_tif):
            stats = raster.quantise(ws.dir("grid") / f"dist_{s}.tif", ws.dir("grid") / "land.tif", inside_tif, band_tif, cls_tif, table, log)
            stats_path.write_text(json.dumps(stats) + "\n", encoding="utf-8")
            raster._mark(cls_tif)
        meta["raster"][s] = json.loads(stats_path.read_text(encoding="utf-8"))
        merc = raster.warp_to_mercator(cls_tif, out / f"explore_{s}_3857.tif", log, tools_log)
        meta["archives"][s] = tiles.build(merc, out, s, log, tools_log)

    # 2. detail rasters
    band_4326 = shapely.from_wkb((out / "edgeband_4326.wkb").read_bytes())
    meta["detail"] = detail.run_detail(cfg, ws, published, table, band_4326, log)

    # 3. upload and verify
    r2cfg = r2.R2Config.from_env(os.environ)
    base = r2.ensure_bucket(r2cfg, log)
    items = upload_set(ws, cfg.id, ws.snapshot)
    meta["upload"] = r2.upload_tree(r2.s3_client(r2cfg), r2cfg.bucket, items, log)
    keys = [k for _, k in items]
    meta["verify"] = r2.verify_head(base, keys, [f"{cfg.id}/{ws.snapshot}/{s}.pmtiles" for s in SCENARIOS], log)
    meta["r2_base"] = base

    # 4. site documents, merged with what the site already holds
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    snapshot = json.loads((ws.dir("fetch") / "snapshot.json").read_text(encoding="utf-8"))
    units_meta = json.loads((ws.dir("poles") / "units.json").read_text(encoding="utf-8"))["units"]
    region = {"id": cfg.id, "name": cfg.name, "snapshot": ws.snapshot, "unit_level": cfg.unit_admin_level, "r2_base": base,
              "max_distance_m": cfg.max_distance_m, "edge_mask_m": cfg.edge_mask_m, "detail_res_m": cfg.detail_res_m,
              "detail_window_m": cfg.detail_window_m}
    site = sitedata.build(region, units_meta, sitedata.unit_geometries(ws.dir("poles") / "units.fgb"), published, table,
                          meta["archives"], meta["detail"], meta["verify"], snapshot["sources"], generated_at, _pipeline_commit())
    targets = [out / "site"] + ([ws.site_dir] if ws.site_dir else [])
    meta["site_files"] = [str(p) for target in targets for p in sitedata.write_site(site, Path(target), cfg.id, generated_at)]
    meta["site_dir"] = str(ws.site_dir) if ws.site_dir else None
    meta["publish_bytes"] = dir_size(out)
    meta["seconds"] = round(time.monotonic() - t0, 1)
    log.info("publish: done in %.0f s, %d withheld, %s", meta["seconds"], meta["withheld"], {s: a["bytes"] for s, a in meta["archives"].items()})
    return meta
```

`Workspace.__init__` gains `self.site_dir: Path | None = None`. `stages.registry()` adds `from . import publish; reg["publish"] = publish.run`. `cli.py`: `r.add_argument("--site-dir", default=os.environ.get("POLES_SITE_DIR") or str(Path(__file__).resolve().parents[2] / "site" / "data"), help="directory that receives the site JSON (default: the repository's site/data or $POLES_SITE_DIR)")`, `r.add_argument("--no-write-site", action="store_true", help="keep the site JSON under the work directory only")`, and where the workspace is created: `ws.site_dir = None if args.no_write_site else Path(args.site_dir)`. Check `poles/__init__.py` exists so `parents[2]` of `cli.py` is the repo root (`pipeline/poles/cli.py` -> `pipeline/poles` -> `pipeline` -> repo).

The stage needs `cfg.class_table` to be `None` or a list of 254 edges; `RegionConfig` already carries `class_table` (null for Europe).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_publish_stage.py -q`, then the whole suite `.venv/bin/python -m pytest -q`.
Expected: all green. The stage test drives real `gdal_rasterize`, `gdalwarp`, `gdal raster tile`, `pmtiles` and a two-process pool; it should take well under a minute. If `ws.mark_done` needs a different signature, use the one in `workspace.py`.

- [ ] **Step 5: Run the CLI once against the test workspace for the usage text**

Run: `cd pipeline && .venv/bin/poles run --help`
Expected: the two new flags appear with their help text.

- [ ] **Step 6: Commit**

```bash
git add pipeline/poles/publish/__init__.py pipeline/poles/stages.py pipeline/poles/cli.py pipeline/poles/workspace.py pipeline/tests/test_publish_stage.py
git commit -m "publish: the stage: class rasters, archives, detail, R2 upload and verification, site JSON; --site-dir and --no-write-site"
```

---

### Task 8: Europe run of the local part, numbers into the spec

**Files:**
- Modify: `docs/EUROPE_SPEC.md` section 4.1 (sizes) and 3.3 (publish timing row), `docs/EUROPE_PLAN.md` stage 3 checklist
- Work data: `work/europe/2026-08-19/publish/`

This task runs the stage on the real snapshot without R2 configuration: it must build `explore_A.tif`, `explore_B.tif`, the two `_3857` rasters, both archives and every detail raster, then stop with `PublishError` naming the R2 variables. Nothing under `fetch/`, `extract/`, `classify/`, `grid/`, `poles/` or `validate/` is touched.

- [ ] **Step 1: Preconditions**

Run: `colima status` (expected: not running; if running, `colima stop`), `df -g /Users | tail -1` (expected: at least 20 GiB free), `ls work/europe/2026-08-19/validate/done.json work/europe/2026-08-19/poles/roads/tiles.json` (both present).

- [ ] **Step 2: Launch the run in the background**

```bash
cd <repo>/pipeline
export PATH=/opt/homebrew/bin:$PATH
unset POLES_R2_ACCOUNT_ID POLES_R2_BUCKET POLES_R2_TOKEN_FILE POLES_R2_ACCESS_KEY_ID_FILE POLES_R2_SECRET_FILE POLES_R2_BASE
nohup env POLES_WORKERS=4 caffeinate -i .venv/bin/poles run europe --snapshot 2026-08-19 --work ../work --stage publish --no-write-site \
  > ../work/europe/2026-08-19/publish-run.log 2>&1 &
echo $!
```

Then return to the orchestrator with the PID and the log path; do not wait in the subagent. The orchestrator polls the log at intervals (`tail -3`), never more often than every ten minutes. Expected order in the log: `inside.tif written`, `edgeband.tif written`, `explore_A.tif: {...}`, `explore_A_3857.tif warped in N s`, `tiles of explore_A_3857.tif cut ... in N s`, `A.pmtiles converted in N s`, the same for B, then one `detail <code> <scenario>: ...` line per unit and scenario, then the `PublishError` naming `POLES_R2_ACCOUNT_ID`. Exit code 1 is the expected outcome of this run.

- [ ] **Step 3: Record the numbers**

From the log and the files: quantise time and the `{"cells", "nodata", "edge", "classed"}` counts per scenario; warp time; tile time; `A.pmtiles` and `B.pmtiles` sizes (`ls -l`), `pmtiles show` tile counts per archive; detail count, bytes and seconds (`du -sh work/europe/2026-08-19/publish/detail`, `find ... -name '*.png' | wc -l`); peak memory from the log's stage line if the run reached it (it will not, since the stage raised; take `ps` samples during the run or `/usr/bin/time -l` is not available for a background job, so report what the log gives and the `du` of `publish/`).

Sanity checks on the artefacts, all expected to pass:
- `gdalinfo -stats work/europe/2026-08-19/publish/explore_A.tif | grep -i "STATISTICS_M"`: minimum 0, maximum 255.
- NODATA share of the frame between 40 % and 75 % (sea plus the margin outside the extract); EDGE share of land cells a few percent; `classed` cells at least 300 M. Anything outside these ranges is a finding to report, not to adjust.
- `pmtiles show A.pmtiles`: max zoom 9, min zoom 0, tile type png, addressed tiles in the tens of thousands.
- One detail raster inspected with `gdalinfo -stats` (a Lithuanian pole, `detail/lt/A-1.png`): min and max within 0..255, most values real classes; `detail/lt/A-1.json` has six fields and `width == height == 400`.
- The Lithuanian A-1 detail's centre pixel `[200, 200]` class equals `ClassTable().to_class(dist_m)` of the published pole within one class (a five-line python check).

Write the numbers into `docs/EUROPE_SPEC.md` 4.1 (replace the estimates for the archive sizes, the detail raster total, and the total R2 footprint; note that the upload figure is pending) and into the 3.3 timing table as a `publish (local part)` row; tick the stage-3 boxes in `docs/EUROPE_PLAN.md` that this run satisfies (archives, detail, site JSON and manifest are produced; not the R2 boxes).

- [ ] **Step 4: Commit**

```bash
git add docs/EUROPE_SPEC.md docs/EUROPE_PLAN.md
git commit -m "Spec 4.1 and 3.3: measured publish artefact sizes and timings from the Europe 2026-08-19 run (upload pending R2)"
```

---

### Task 9: Docs close-out

**Files:**
- Modify: `docs/DECISIONS.md`, `docs/OVERVIEW.md`, `docs/LOG.md`, `pipeline/README.md`, `CLAUDE.md` (only if the layout section needs the `publish` mention; the `pipeline/` line already covers the CLI)

- [ ] **Step 1: DECISIONS entry "2026-08-22: Stage 3 implementation decisions"**

One bullet per item of "Decisions fixed by this plan" (1 to 12) in the same voice as the stage-2 entry: what was decided, why, what it costs if wrong. Mention #19 in the edge-mask bullet (the edge band is the `.poly` boundary, not the true data edge of partial neighbours), #20 in the area bullet, #21 in the exclusions bullet. No em dashes.

- [ ] **Step 2: OVERVIEW, LOG, README**

- `docs/OVERVIEW.md`: stage 3 status line "local part done 2026-08-22 (archives, detail rasters, site JSON); upload and verification wait for R2 on the account"; the NEXT-UP block names the R2 rerun and stage 4 (#10); the test count.
- `docs/LOG.md`: one line for stage 3's local completion with the archive sizes.
- `pipeline/README.md`: a "Publish" section: what the stage produces, the six environment variables with one line each (the secret files live outside the repository; no paths), `--site-dir` and `--no-write-site`, the rerun-after-R2 behaviour, and the schema files as the site contract.

- [ ] **Step 3: Whole suite and commit**

Run: `cd pipeline && .venv/bin/python -m pytest -q` (expected: green, count reported).

```bash
git add docs/DECISIONS.md docs/OVERVIEW.md docs/LOG.md pipeline/README.md
git commit -m "Stage 3 docs: decisions entry, overview status, log line, README publish section"
```

---

## Self-review notes

- Spec coverage: 3.2 stage 7 (Task 7), 3.4 (Task 1), 3.5 (Task 4), 4.1 keys and sizes (Tasks 6, 7, 8), 4.2 contract (Task 5), 5 validation artefacts uploaded (Task 7 `upload_set`), 6 check 7 monotonic table (Task 1 `ClassTable.__init__` refuses non-monotonic edges), HEAD and range verification (Task 6), schema validation before writing (Task 5). The acceptance list of plan task 3.7 ("every manifest reference answers HEAD with ranges on the dev hostname") is fulfilled by the R2 rerun after the owner's step; the plan says so in Decision 12.
- Type consistency: `tiles.build` returns the dict `sitedata.build` consumes under `archives[s]` (`key_name, bytes, tiles, min_zoom, max_zoom`); `detail.run_detail` returns `count, bytes` consumed by the manifest; `r2.verify_head` returns `at, keys, range_ok` consumed by `verified`; `apply_exclusions` output carries `withheld` consumed by `_unit_summary` and the unit documents; `raster._done`, `_mark`, `MARKER` are imported by `tiles.py` and the stage.
