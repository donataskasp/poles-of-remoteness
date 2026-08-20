# Europe version: implementation plan

> **For agentic workers:** execute one stage per session with superpowers:subagent-driven-development or superpowers:executing-plans. Before starting a stage, write its step-level plan (writing-plans) from this document and `docs/EUROPE_SPEC.md`, and label its GitHub issue `in-progress`. This document fixes scope, interfaces, tests, and acceptance criteria; it deliberately contains no implementation code (owner's rule for the planning session).

**Goal:** Ship the pole-of-remoteness map for Europe, then North America, as a static free-tier site backed by a region-agnostic, containerised, validated compute pipeline, without breaking the live Lithuania URL.

**Architecture:** A Python pipeline (`pipeline/`) turns a Geofabrik extract into exact per-unit poles plus a 250 m explore field, validates them, and publishes small JSON to git and tile archives to R2 under an immutable snapshot key. A plain HTML/CSS/JS site (`site/`) on Cloudflare Workers static assets reads the JSON and the PMTiles archives by range request. Publishing is a manifest commit.

**Tech stack:** Python 3.12, osmium-tool, GDAL, rasterio, scipy, shapely 2, pyproj, pmtiles CLI, pytest; Docker; Cloudflare Workers static assets, R2, Analytics Engine; Leaflet 1.9.4 and the pmtiles JS adapter, vendored; GitHub Actions; Playwright for screenshots.

**Spec:** `docs/EUROPE_SPEC.md` (approved 2026-08-20). The plan argues from the spec; read both.

## Global constraints

Copied from the spec and CLAUDE.md; every task inherits them.

- Privacy by design: no cookies, no IPs, no raw user agents, no client-side analytics, no identifiers, no consent banner.
- The owner runs nothing by hand; the only human steps are one-time setup and PR review.
- No em dashes anywhere: code comments, docs, commit messages, site copy, issue text.
- No secrets in the repo; tokens live in GitHub secrets or `~/personal/...` files with mode 600.
- Site: no build step, no bundler, no framework; dependencies vendored; ES modules are allowed.
- The build lives on branch `europe`; `main` keeps serving the LT site until the cutover stage. Never push to main before stage 6 except docs.
- Tests: real pytest for pipeline math; screenshots, not tests, for the site.
- Commit after every working change with small descriptive messages; stage explicit paths; repo-local identity (Donatas / gmail).
- GitHub Issues: one issue per stage under the epic; `in-progress` while a session works it; close with a comment.
- Docs cadence: OVERVIEW immediately on status change; DECISIONS on every significant call; LOG for big events.
- Region configs: nothing in code names Europe; `pipeline/regions/<region>.yaml` is the only place a region is described.
- Tag sets, class table, and accuracy tiers exactly as in spec sections 2.3, 3.4, and 2.4.
- Region, snapshot, and unit identifiers: `<region>` lowercase slug (`europe`, `north-america`); `<snapshot>` is `YYYY-MM-DD` of the primary extract's `Last-Modified`; unit codes lowercase ISO 3166-1 alpha-2 or ISO 3166-2 (`lt`, `us-ak`).

## Stage map

| Stage | Delivers | Depends on | Effort guess |
| --- | --- | --- | --- |
| 1 Pipeline foundation | config, CLI, container, fetch/extract/classify/grid, Europe grids computed, numbers recorded | spec | 2 sessions + 1 overnight run |
| 2 Poles and validation | units, candidates, refinement, attribution, eight checks, contact sheet, LT reproduced | 1 | 2 sessions |
| 3 Publish | class table, tiles, PMTiles, detail rasters, R2 upload, site JSON, manifest | 2 | 1 session |
| 4 Site | new site on the preview worker, full feature set, screenshots | 3 (JSON schema fixed) | 2-3 sessions |
| 5 North America | region config, run, validation review, region switch | 4 | 1 session + 1 overnight run |
| 6 Cutover | name, domain, R2 hostname, new worker, redirect, monitors, analytics, merge, docs | 5 (or 4, owner's call) | 1 session + owner's one-time steps |
| 7 Automated refresh (parked) | scheduled Hetzner run, PR with diff report | 6, owner's go | 1 session |

GitHub: epic #6, stages #7 to #13 in order.

Stage 4's skeleton (tasks 4.1-4.3) may start as soon as task 3.5 fixes the JSON schema, against the LT-sized Europe subset if the full run is not in yet.

## Repository layout after stage 4

```
pipeline/
  Dockerfile                     python 3.12 + osmium-tool + GDAL + pmtiles; ENTRYPOINT poles
  requirements.txt               pinned
  regions/europe.yaml            spec 2.1 table, Europe column
  regions/north-america.yaml     stage 5
  poles/__init__.py
  poles/cli.py                   `poles run <region> [--stage X] [--snapshot D] [--work DIR]`
  poles/config.py                RegionConfig, load_region()
  poles/workspace.py             Workspace: per-stage dirs and done-markers
  poles/fetch.py                 stage 1 fetch
  poles/extract.py               stage 2 extract (osmium)
  poles/classify.py              stage 3 classify (tag rules)
  poles/grid.py                  stage 4 grid (rasterize, tiled EDT)
  poles/units.py                 unit polygons, masks, unit raster
  poles/candidates.py            branch-and-bound
  poles/refine.py                exact refinement in UTM
  poles/attrib.py                nearest way, nearest settlement
  poles/poles.py                 stage 5 poles orchestrator
  poles/classes.py               ClassTable
  poles/validate/__init__.py     stage 6 orchestrator
  poles/validate/checks.py       checks 1-7
  poles/validate/report.py       report.json, report.html, contact-sheet.html
  poles/publish/__init__.py      stage 7 orchestrator
  poles/publish/raster.py        mask, quantise, warp, tile, pmtiles
  poles/publish/detail.py        50 m detail rasters
  poles/publish/sitedata.py      units.json, unit JSON, regions.json, manifest.json
  poles/publish/r2.py            upload, HEAD verification
  tests/                         pytest, synthetic fixtures only, no network
site/
  index.html
  css/app.css
  js/app.js                      boot, state, wiring
  js/router.js                   path + hash state
  js/data.js                     regions.json, units.json, unit JSON, manifest
  js/i18n.js                     dictionary + Intl.DisplayNames
  js/classes.js                  ClassTable decode (mirror of poles/classes.py)
  js/map.js                      Leaflet map, basemaps
  js/explore.js                  PMTiles layer + pixel readout
  js/detail.js                   detail raster overlay
  js/ranking.js                  bottom sheet / side panel
  js/card.js                     first-screen card and pole card
  vendor/leaflet/                1.9.4 as today
  vendor/pmtiles/                pmtiles JS adapter, pinned version in vendor/README
  data/regions.json
  data/manifest.json
  data/<region>/units.json
  data/<region>/units/<code>.json
worker.js                        assets + meta injection + AE logging
redirect/worker.js               stage 6: 301 for the old worker name
redirect/wrangler.jsonc
wrangler.jsonc                   envs: production, preview
.github/workflows/deploy-cloudflare.yml   extended: preview env on branch europe, version.json, perf budget
.github/workflows/pipeline-tests.yml      pytest on pushes touching pipeline/
work/                            gitignored; <region>/<snapshot>/<stage>/
```

`scripts/`, the old `site/data/*`, and the LT-specific parts of `worker.js` are deleted in stage 6, not before.

## Shared interfaces

Defined once here; tasks reference them by name. Types are Python unless marked JS.

- `RegionConfig` (dataclass, `poles/config.py`): `id, name, sources: list[str], supplement_sources: list[str], coarse_crs: str, coarse_res_m: int, unit_admin_level: int, unit_countries: list[str] | None, unit_exclude: list[str], unit_code_tag: str, territory_mask: list[dict], edge_mask_m: int, max_distance_m: int, top_n: int, detail_res_m: int, detail_window_m: int, class_table: list[int] | None, expected_units: int | None, transcontinental: list[str]`. `load_region(path) -> RegionConfig` validates types and required keys and raises `ConfigError` with the offending key.
- `Workspace` (`poles/workspace.py`): `Workspace(root, region, snapshot)`; `.dir(stage) -> Path` (created on demand); `.is_done(stage) -> bool`; `.mark_done(stage, meta: dict)`; `.meta(stage) -> dict`. Done-markers are `done.json` files with timestamps, durations, and peak RSS.
- Stage functions all share the signature `run(cfg: RegionConfig, ws: Workspace, log: Logger) -> None` and are idempotent: if `ws.is_done(stage)` they return immediately unless `--force`.
- `classify_highway(tags: dict[str, str]) -> tuple[bool, bool]` returns `(in_a, in_b)`.
- `tiled_edt(road_mask: np.ndarray[bool], res_m: float, overlap_cells: int, tile: int = 4096, workers: int | None = None) -> np.ndarray[float32]`, distances in metres, guaranteed equal to the untiled transform (spec 3.2 stage 4).
- `Candidate = (row: int, col: int, coarse_m: float)`; `candidates(dist: np.ndarray, unit_ids: np.ndarray, unit_id: int, res_m: float, pad_fn, best_lower_m: float) -> list[Candidate]`.
- `RefinedPole` (dataclass): `lat, lon, dist_m, way_id, x, y, utm_epsg`; `refine(x, y, src_crs, roads_tree: STRtree, roads_geoms, utm_epsg, half_m=250, steps=(25.0, 5.0)) -> RefinedPole`.
- `Pole` (dataclass, serialised to JSON): `rank, lat, lon, dist_m, nearest_way: {id, highway, name, ref, country}, nearest_place: {name, type, dist_m, lat, lon}, detail: str | None, warnings: list[str]`.
- `ClassTable` (`poles/classes.py` and `site/js/classes.js`): `edges: list[int]` (lower edges in metres, strictly increasing, first 0, length 254); `to_class(d_m) -> int` (0..253); `lower(c) -> int`; `upper(c) -> int | None` (None for 253); `mid(c) -> float`; constants `EDGE = 254`, `NODATA = 255`. `default_edges()` builds spec 3.4.
- `CheckResult` (dataclass): `check: str, unit: str, scenario: str, passed: bool, blocking: bool, details: dict`.
- Published JSON shapes (frozen in task 3.5, validated by `pipeline/tests/schemas/*.json`):
  - `regions.json`: `{ "regions": [ { "id", "name_en", "unit_level": 2|4, "snapshot", "r2_base", "class_edges": [...], "units_count" } ] }`
  - `<region>/units.json`: `{ "snapshot", "units": [ { "code", "name_en", "area_km2", "transcontinental": bool, "A": { "dist_m", "rank", "lat", "lon" }, "B": { "dist_m", "rank", "lat", "lon" } } ] }`
  - `<region>/units/<code>.json`: `{ "code", "name_en", "snapshot", "A": { "poles": [Pole...] }, "B": { "poles": [Pole...] } }`
  - `manifest.json`: `{ "regions": { "<region>": { "snapshot", "r2_base", "pbf_sha256": {url: sha}, "pbf_last_modified": {url: date}, "pipeline_commit", "published_at" } } }`
- R2 keys: `<region>/<snapshot>/A.pmtiles`, `B.pmtiles`, `detail/<code>/<scenario>-<rank>.png`, `detail/<code>/<scenario>-<rank>.json` (`{west, north, dlon, dlat, width, height}`), `validation/report.json`, `validation/report.html`, `validation/contact-sheet.html`.
- JS state (`router.js`): path `/`, `/<region>`, `/<region>/<unit>`; hash keys `z, lat, lon, s (A|B), b (sat|osm), l (en|lt)`; `parse(location) -> State`, `write(state, {replace})`.

---

## Stage 1: Pipeline foundation

Issue: #7 "Stage 1: pipeline foundation (config, CLI, container, fetch to grid)". Done when every acceptance criterion below is checked and the numbers are written into spec section 3.3.

### Task 1.1: Package skeleton, region config, workspace

**Files:** create `pipeline/requirements.txt`, `pipeline/poles/__init__.py`, `pipeline/poles/config.py`, `pipeline/poles/workspace.py`, `pipeline/regions/europe.yaml`, `pipeline/tests/test_config.py`, `pipeline/tests/test_workspace.py`, `pipeline/tests/conftest.py`; modify `.gitignore` (add `/work/`).

**Tests:**
- `test_load_europe_config_matches_spec_table`: every field of spec 2.1's Europe column round-trips through `load_region`.
- `test_missing_required_key_raises_config_error_naming_key`.
- `test_unit_countries_none_means_all_except_exclude`.
- `test_workspace_done_marker_roundtrip`: `mark_done` then `is_done` and `meta` return what was written.
- `test_workspace_dirs_are_per_region_snapshot_stage`.

**Verify:** `cd pipeline && python -m pytest -q`.

**Acceptance:** config loads the Europe YAML exactly as in the spec; tests pass; `work/` ignored.

### Task 1.2: CLI with resumable stages

**Files:** create `pipeline/poles/cli.py`, `pipeline/poles/stages.py` (ordered registry: `fetch, extract, classify, grid, poles, validate, publish`), `pipeline/tests/test_cli.py`; `pyproject.toml` or `setup.cfg` in `pipeline/` exposing the `poles` entry point.

**Tests:** `test_run_executes_stages_in_order_and_skips_done` with stub stage functions recorded in a list; `test_stage_flag_runs_single_stage`; `test_force_reruns_done_stage`; `test_unknown_region_fails_with_message`.

**Acceptance:** `poles run europe --stage fetch --work work/` resolves the region file and workspace; stub stages prove ordering, skipping, and `--force`.

### Task 1.3: fetch

**Files:** create `pipeline/poles/fetch.py`, `pipeline/tests/test_fetch.py`.

**Behaviour:** downloads each URL in `sources + supplement_sources` with resume support (`Range` on partial files), fetches `<url>.md5` as Geofabrik publishes it and verifies, records `sha256`, `Last-Modified`, size; snapshot id is the primary source's `Last-Modified` date unless `--snapshot` is given. Writes `fetch/snapshot.json`.

**Tests** (local HTTP server fixture, no network): `test_resume_partial_download`; `test_checksum_mismatch_raises_and_deletes_file`; `test_snapshot_id_from_last_modified`; `test_snapshot_json_lists_every_source`.

**Acceptance:** a real `poles run europe --stage fetch` completes on this machine with all six files and `snapshot.json` (this is the first overnight step; 34 GB).

### Task 1.4: extract

**Files:** create `pipeline/poles/extract.py`, `pipeline/poles/osmium.py` (thin subprocess wrapper that logs the exact command and fails loudly), `pipeline/tests/test_extract.py`, `pipeline/tests/fixtures/tiny.osm.pbf` (a hand-made extract a few KB in size containing: two highways of different classes, one admin_level 2 relation with ISO3166-1, one place node, one water polygon).

**Behaviour:** `osmium merge` of all sources into `merged.pbf` (or `osmium cat` if one source); `tags-filter w/highway` then `osmium export -f geojsonseq` piped into `ogr2ogr -f FlatGeobuf /vsistdin/` (osmium cannot write FlatGeobuf itself; piping avoids a 40 GB text intermediate) keeping `@id, highway, name, ref, ice_road, winter_road`; `tags-filter r/boundary=administrative` at the configured admin levels then export polygons with `admin_level, ISO3166-1, ISO3166-2, name, name:en`; `tags-filter n/place=city,town,village,hamlet,isolated_dwelling` to `places.fgb`; `tags-filter wr/natural=water` polygons to `water.fgb`; download osmdata `land-polygons-split-4326.zip` once into `work/shared/` with checksum, unzip to `land.fgb` via ogr2ogr.

**Tests:** `test_extract_tiny_fixture_produces_five_layers_with_expected_counts`; `test_osmium_failure_raises_with_command_in_message`.

**Acceptance:** Europe extract completes; layer row counts logged in `extract/done.json`.

### Task 1.5: classify

**Files:** create `pipeline/poles/classify.py`, `pipeline/tests/test_classify.py`.

**Behaviour:** `classify_highway` implements spec 2.3 exactly; `run` streams `highways.fgb` and writes `roads_A.fgb`, `roads_B.fgb` with `way_id, highway, name, ref`.

**Tests:** a table-driven test with at least: every set B class true/true (for A/B), `track` true/false, each excluded class false/false, `highway=unclassified` with `access=private` true/true (physical not legal), `highway=track` with `ice_road=yes` true/false, missing highway false/false, `highway=motorway_link` true/true, `proposed` false/false. Plus `test_run_writes_two_layers_with_subset_relation` (every B way is in A).

**Acceptance:** tests pass; Europe classify run logs counts for A and B.

### Task 1.6: grid (rasterize and tiled EDT)

**Files:** create `pipeline/poles/grid.py`, `pipeline/tests/test_grid.py`.

**Behaviour:** compute the region raster frame: bounds = union of source polygons reprojected to `coarse_crs`, snapped outward to `coarse_res_m`; `gdal_rasterize` each scenario's FGB to a GeoTIFF byte mask (`ALL_TOUCHED=YES`); `tiled_edt` per spec 3.2 stage 4 with overlap `max_distance_m / coarse_res_m`, tiles 4096, process pool over cores, doubled-overlap loop for unresolved cells, writes `dist_A.tif`, `dist_B.tif` float32 with the frame's geotransform; also rasterises `land.fgb` minus water polygons of at least 1 km² to `land.tif`. Records peak RSS and wall time per step in `grid/done.json`.

**Tests:** `test_tiled_equals_untiled_random_sparse_roads` (200x200 grid, 1% road cells, compare against `scipy.ndimage.distance_transform_edt` scaled by res); `test_tiled_equals_untiled_when_overlap_too_small_forces_doubling` (single road cell in a corner of a 300x300 grid, overlap 16); `test_frame_bounds_snap_outward_to_resolution`; `test_land_mask_subtracts_lakes_over_threshold_only`.

**Acceptance:** both Europe grids exist; `tiled_edt` on a 4096x4096 excerpt equals the untiled result bit for bit; peak RSS and wall time recorded in spec 3.3; A ≤ B holds on the full grid (quick numpy assertion in the log).

### Task 1.7: container and CI tests

**Files:** create `pipeline/Dockerfile`, `.github/workflows/pipeline-tests.yml`; modify `pipeline/requirements.txt` (pin with `pip freeze` inside the container).

**Behaviour:** image based on a GDAL image with Python 3.12, installs osmium-tool and the pmtiles CLI, copies `pipeline/`, `ENTRYPOINT ["poles"]`. CI workflow runs `pytest` in the image on pushes touching `pipeline/**`.

**Acceptance:** `docker build` succeeds on the Mac; `docker run ... poles run europe --stage classify --work /work` runs against a mounted `work/`; CI test workflow green on the `europe` branch.

### Task 1.8: throwaway tile-size measurement

**Files:** nothing committed except the numbers. A scratch script outside the repo quantises the existing LT 50 m grid (`out/` or `site/data/dist_A.png`) to the default class table, downsamples to 250 m, warps to EPSG:3857, builds z0-z9 tiles with `gdal2tiles` into MBTiles, converts with `pmtiles convert`, and records bytes per land tile at z9 and the total archive size per km² of land.

**Acceptance:** spec 4.1 gains the measured bytes per z9 land tile and the projected Europe and North America archive sizes, replacing the estimates; the scratch script is deleted.

### Stage 1 acceptance (issue checklist)

- [ ] `pytest` green locally and in CI
- [ ] `poles run europe` completes fetch, extract, classify, grid on this machine in one command
- [ ] `dist_A.tif`, `dist_B.tif`, `land.tif` exist with the expected frame; A ≤ B on the full grid
- [ ] runtime, peak RSS, and disk use per stage recorded in spec 3.3
- [ ] tile-size measurement recorded in spec 4.1
- [ ] container builds and runs the classify stage
- [ ] DECISIONS entry for anything that changed versus the spec

---

## Stage 2: Poles and validation

Issue: #8 "Stage 2: poles, attribution, validation, contact sheet; Lithuania reproduced".

### Task 2.1: units

**Files:** create `pipeline/poles/units.py`, `pipeline/tests/test_units.py`, `pipeline/regions/masks/europe.geojson` (territory mask polygons, hand-drawn generous boxes around the six territories).

**Behaviour:** select admin relations at `unit_admin_level` whose country (their own `ISO3166-1` at level 2, or the containing level-2 relation at level 4) is in `unit_countries` and not in `unit_exclude`; code from `unit_code_tag`, lowercased; subtract the territory mask; intersect with land; compute `area_km2`; flag `transcontinental` from an explicit list in the region config (`tr`, `ge` for Europe); write `units.fgb` and `units.tif` (int16 unit index on the coarse frame, 0 = none). Fail loudly if a unit has no `ISO` code or if the unit count differs from `expected_units` in the config.

**Tests:** `test_territory_mask_removes_island_but_keeps_mainland`; `test_level4_units_take_country_from_container`; `test_unit_count_mismatch_fails`; `test_unit_raster_assigns_each_cell_to_one_unit`.

**Acceptance:** Europe yields the configured count (set `expected_units` once counted and reviewed, listed in the issue comment with codes); `ru` absent; `tr` and `ge` present.

### Task 2.2: candidates (branch-and-bound)

**Files:** create `pipeline/poles/candidates.py`, `pipeline/tests/test_candidates.py`.

**Behaviour:** per unit, iterate cells of the unit in descending coarse value; maintain `best_lower_m` (updated after each refinement by the caller); emit cells while `coarse_m + 2 * half_diag * (1 + pad_fn(row, col)) >= best_lower_m`; `pad_fn` returns the LAEA scale error at the cell (from the cell's angular distance to the projection centre); enforce a 2 km dedup among emitted candidates; cap the emitted list at 500 per unit with a logged warning if the cap bites.

**Tests:** `test_never_prunes_planted_maximum` (random synthetic grids with a planted exact maximum off-centre within a cell, run the bound with a stub refiner that knows the truth, assert the true maximum is always refined); `test_dedup_2km`; `test_pad_grows_with_distance_from_centre`.

### Task 2.3: refine

**Files:** create `pipeline/poles/refine.py`, `pipeline/tests/test_refine.py`.

**Behaviour:** given a candidate in the coarse CRS, pick the UTM zone from its longitude (and hemisphere), transform a window of `half_m` around it plus the scenario's ways within `coarse_m * 1.2 + 1000` m (STRtree query on a bounding box), compute exact distances on a 25 m grid, take the max, repeat on a 5 m grid in a 50 m window around it; return `RefinedPole` including the nearest way id at the final point.

**Tests:** `test_single_straight_road_known_offset` (road along y = 0, window centred at y = 1000: result 1000 ± 2.5 m at the window edge); `test_two_roads_midpoint`; `test_utm_zone_selection_including_norway_exception_not_applied` (plain 6-degree zones; document that the Norway/Svalbard exceptions do not matter for distance); `test_result_nearest_way_id_matches_closest_geometry`.

### Task 2.4: attribution and the poles stage

**Files:** create `pipeline/poles/attrib.py`, `pipeline/poles/poles.py`, `pipeline/tests/test_attrib.py`, `pipeline/tests/test_poles_stage.py`.

**Behaviour:** `nearest_way` returns id, highway, name, ref, and the country (point-in-polygon of the way's nearest point against level-2 relations, including non-unit countries such as Russia); `nearest_place` returns the nearest `places.fgb` node by geodesic distance. `poles.run` loops units and scenarios, drives candidates and refine, deduplicates at 10 km, keeps `top_n`, and writes `poles/A.json`, `poles/B.json` as lists of `{unit, poles: [Pole...]}`. Logs per-unit timing.

**Tests:** `test_nearest_way_country_uses_all_countries_not_only_units`; `test_top_n_dedup_10km`; `test_stage_output_schema`.

**Acceptance:** Europe poles computed for both scenarios; Lithuania's A and B winners match the published values within 1% and 500 m (this is also check 6; confirm here first).

### Task 2.5: validation checks

**Files:** create `pipeline/poles/validate/__init__.py`, `pipeline/poles/validate/checks.py`, `pipeline/poles/validate/refs.yaml` (LT references plus three to five cited national poles with URLs and notes), `pipeline/tests/test_checks.py`.

**Behaviour:** checks 1-7 from spec section 6, each a function returning `list[CheckResult]`; `blocking` true for 1, 2, 3, 4, 7 and for check 6's LT entries; 5 and the external references in 6 are warnings. Check 1 uses `pyproj.Geod` against vertices densified at 1 m via `shapely.segmentize`, over all ways of the scenario within 2x the claimed distance from `highways.fgb` (not the classified subset, re-filtered inline to be independent). Check 4 recomputes the coarse grid shifted by half a cell (reuse `tiled_edt`) and re-runs refine for each unit's top 3.

**Tests** (synthetic): `test_recheck_agrees_within_tolerance_on_synthetic`; `test_recheck_catches_planted_error` (mutate a pole distance by 2%, expect failure); `test_edge_bound_fails_when_edge_closer_than_distance`; `test_a_le_b_invariant_detects_violation`; `test_hole_detector_flags_doughnut_and_passes_uniform`; `test_results_mark_blocking_correctly`.

### Task 2.6: report and contact sheet

**Files:** create `pipeline/poles/validate/report.py`, `pipeline/poles/validate/templates/report.html`, `pipeline/poles/validate/templates/contact-sheet.html`, `pipeline/tests/test_report.py`.

**Behaviour:** `report.json` lists every `CheckResult`; `report.html` is a single self-contained page summarising pass/fail per unit; `contact-sheet.html` shows, per unit and scenario, the winner on an Esri World Imagery static tile mosaic (z13, 3x3 tiles fetched at build time and inlined as data URIs so the page is self-contained), the distance, nearest road, and any warnings. The stage exits non-zero if any blocking check failed.

**Tests:** `test_report_json_has_every_check_for_every_unit`; `test_stage_exit_code_nonzero_on_blocking_failure`; `test_contact_sheet_lists_every_unit_once_per_scenario` (tile fetch stubbed).

### Stage 2 acceptance (issue checklist)

- [ ] `pytest` green
- [ ] Europe units: count matches config, codes listed in the issue, `ru` absent
- [ ] Lithuania A 3.43 km and B 6.67 km reproduced within 1% and 500 m
- [ ] validation run: zero blocking failures or each failure explained and fixed
- [ ] owner has opened `contact-sheet.html` and commented on the issue
- [ ] per-unit timing recorded; spec 3.3 updated

---

## Stage 3: Publish

Issue: #9 "Stage 3: class table, tiles, PMTiles, detail rasters, R2 upload, site JSON, manifest".

### Task 3.1: class table

**Files:** create `pipeline/poles/classes.py`, `pipeline/tests/test_classes.py`, `site/js/classes.js`, `site/js/classes.test.html` (a zero-dependency page that runs the same table cases in the browser and prints PASS/FAIL; opened once by hand, not a test suite).

**Tests:** `test_default_edges_match_spec_breakpoints` (254 entries; entry 49 is 2450; entry 50 is 2500; entry 124 is 9900; entry 125 is 10000; entry 204 is 29750; entry 205 is 30000; entry 234 is 59000; entry 235 is 60000; entry 252 is 230000; entry 253 is 240000); `test_roundtrip_lower_le_value_lt_upper` for 10,000 random distances; `test_reserved_values_never_returned`; `test_custom_edges_validated_strictly_increasing_from_zero`.

### Task 3.2: explore raster to PMTiles

**Files:** create `pipeline/poles/publish/raster.py`, `pipeline/tests/test_publish_raster.py`.

**Behaviour:** `quantise(dist, table, land, edge_dist)` returns uint8 with `NODATA` where not land and `EDGE` where `edge_dist < edge_mask_m`; writes a single-band uint8 GeoTIFF (value = class, no colour table); `gdalwarp` to EPSG:3857 at the z9 resolution (nearest neighbour, keeps class values intact); a small tiler (`tile_pyramid(warped_tif, out_mbtiles)`) reads 256x256 windows with rasterio at z9 and writes grayscale PNGs (Pillow mode `L`) into an MBTiles sqlite file directly, builds z8 down to z0 by mode-downsampling in numpy (never average, so a pixel is always a real class), skips all-NODATA tiles; `pmtiles convert` to `A.pmtiles`, `B.pmtiles`. Colours are applied in the browser.

**Tests:** `test_quantise_marks_water_nodata_and_edge_band`; `test_warp_preserves_class_values` (small synthetic raster round trip: every output value is in the input set); `test_downsample_uses_mode_not_average`; `test_tiler_skips_empty_tiles_and_writes_valid_mbtiles_schema`; `test_png_roundtrip_is_lossless` (encode a 256x256 class array, decode, compare).

**Acceptance:** both Europe archives built; sizes recorded in spec 4.1; `pmtiles show` reports z0-z9 and the expected tile count.

### Task 3.3: detail rasters

**Files:** create `pipeline/poles/publish/detail.py`, `pipeline/tests/test_detail.py`.

**Behaviour:** for every published pole, compute a 50 m grid (exact vector distances, STRtree, same roads as refine) over a `detail_window_m` square in EPSG:4326 with `dlat = 50 m` and `dlon = 50 m / cos(lat)`, quantise with the class table, write a grayscale PNG (value = class) plus the georeference JSON from the shared interfaces. Top 10 per unit per scenario.

**Tests:** `test_detail_georef_matches_window_and_latitude`; `test_detail_values_match_refined_distance_at_pole_pixel_within_one_class`.

### Task 3.4: R2 bucket and uploader

**Files:** create `pipeline/poles/publish/r2.py`, `pipeline/tests/test_r2.py`; document bucket setup in `CLAUDE.local.md` (bucket name, dev hostname, CORS JSON), never in the repo.

**Behaviour:** bucket created once via `wrangler r2 bucket create` (owner's OAuth token); uploader uses the S3-compatible API with an R2 access key stored at `~/personal/.cloudflare/r2-pipeline-key` (mode 600, written from the clipboard per the local rule), uploads every file under `publish/` to `<region>/<snapshot>/...` with immutable cache headers (`Cache-Control: public, max-age=31536000, immutable`), correct content types, and skips keys that already exist with the same size; `verify_head(base_url, keys)` requires 200 and `Accept-Ranges: bytes` on every key and a successful 206 on a 16 KB range of each `.pmtiles`.

**Tests** (moto or a local S3 stub): `test_upload_sets_immutable_cache_and_content_type`; `test_skip_existing_same_size`; `test_verify_head_fails_on_missing_key`.

**Acceptance:** Europe snapshot uploaded to the bucket; HEAD and range checks pass against the `r2.dev` hostname; CORS configured for `localhost` and the preview worker origin.

### Task 3.5: site JSON and manifest

**Files:** create `pipeline/poles/publish/sitedata.py`, `pipeline/tests/test_sitedata.py`, `pipeline/tests/schemas/regions.schema.json`, `units.schema.json`, `unit.schema.json`, `manifest.schema.json`.

**Behaviour:** writes the four JSON shapes from the shared interfaces into `publish/site/` and copies them into `site/data/` when `--write-site` is passed (default on the laptop; the refresh workflow of stage 7 commits them in a PR instead). Ranks computed on scenario A distance, ties broken by code. `manifest.json` merges per region (publishing North America later must not drop Europe).

**Tests:** `test_outputs_validate_against_schemas`; `test_rank_is_dense_on_A_distance`; `test_manifest_merge_keeps_other_regions`; `test_units_json_excludes_non_units`.

**Acceptance:** `site/data/europe/...`, `regions.json`, `manifest.json` committed on the branch; schemas frozen (any later change is a DECISIONS entry).

### Stage 3 acceptance (issue checklist)

- [ ] `pytest` green
- [ ] `poles run europe --stage publish` produces archives, detail rasters, site JSON, manifest, and uploads in one command
- [ ] every manifest reference answers HEAD with ranges on the dev hostname
- [ ] archive sizes and total R2 usage recorded in spec 4.1
- [ ] JSON schemas frozen

---

## Stage 4: Site

Issue: #10 "Stage 4: new site on the preview worker". Visual verification: Playwright screenshots at 390x844 (phone) and 1440x900 (desktop) kept under `site/screenshots/` and updated deliberately; the owner opens the preview URL on a real phone before the stage closes.

### Task 4.1: skeleton, vendoring, preview worker

**Files:** create new `site/index.html`, `site/css/app.css`, `site/js/app.js`, `site/vendor/pmtiles/` (pinned release, SRI-free since same-origin, version noted in `site/vendor/README.md`); modify `wrangler.jsonc` (add `env.preview` with worker name `<name>-preview` and `not_found_handling: "single-page-application"`), `.github/workflows/deploy-cloudflare.yml` (on push to `europe`: deploy `--env preview`; on push to `main`: production, unchanged until stage 6), `.github/dependabot.yml` unchanged.

**Behaviour:** an empty page with the map container, the design tokens, dark variant, and a `version.json` written by CI (`{"commit", "built_at"}`) into `site/` before deploy. Verify job: fetch `/version.json` on the preview URL and compare the commit; fetch the first-screen assets and assert total compressed bytes under 250 KB.

**Acceptance:** the preview worker serves the skeleton; `version.json` matches the pushed commit in CI; perf check present and passing.

### Task 4.2: router and data loading

**Files:** create `site/js/router.js`, `site/js/data.js`.

**Behaviour:** `router.parse` and `router.write` per the shared interfaces, including the visitor `<meta name="visitor" content="LT" | "US-AK">` fallback order from spec 5.3; `data.js` loads `regions.json`, then the region's `units.json`, then unit JSON lazily with an in-memory cache; all fetches relative to the site, R2 base from `regions.json`.

**Acceptance:** opening `/europe/lt#z=9&lat=..&lon=..&s=B` restores every state key; malformed paths fall back to Europe's winner without errors in the console.

### Task 4.3: map, basemaps, explore layer with readout

**Files:** create `site/js/map.js`, `site/js/explore.js`.

**Behaviour:** Leaflet map, Esri World Imagery default and OSM alternative with attributions (OSM ODbL, Esri, the site's data ODbL); `explore.js` is a Leaflet `GridLayer` whose `createTile` fetches the tile through `pmtiles.getZxy`, decodes it with `createImageBitmap` into a canvas, reads the grayscale class array once, keeps it on the tile element, and paints the colormap (light and dark palettes from the design tokens) into the visible canvas; `maxNativeZoom: 9`; on tap (mobile) or hover (desktop) it looks up the class under the point from the kept array and emits `{class, lower, upper, mid}` or `edge` or `nodata`; the readout formats "about 1.2 km" (one decimal under 10 km, integer above, "over 240 km" for class 253, "no data: edge of map data" for EDGE, nothing for NODATA). Switching scenario swaps the archive.

**Acceptance:** screenshots at continental and country zoom; tapping five known places gives readouts consistent with the detail JSON within one class.

### Task 4.4: detail overlay and pole card

**Files:** create `site/js/detail.js`, `site/js/card.js`.

**Behaviour:** at zoom 12 and above, when the view intersects a published pole's detail window, decode the grayscale detail PNG into a canvas, paint it with the same colormap, place it as an `ImageOverlay` (canvas data URL), and use its class array for the readout instead of the z9 tile; the pole card shows exact distance (two decimals), nearest road type and name, nearest settlement with its distance, coordinates, and the Google Maps link; marker per pole with rank.

**Acceptance:** screenshots at a pole; readout switches sources at the zoom threshold without flicker.

### Task 4.5: ranking

**Files:** create `site/js/ranking.js`; modify `site/css/app.css`.

**Behaviour:** bottom sheet on phones (collapsed handle, half, full), side panel on desktop; rows: flag (regional indicator from the code, or the state name for level-4 units), localised name, A distance bold, B small, rank; tapping flies to the pole and updates the path; current unit highlighted; the sheet never covers the attribution. Desktop layout stays byte-identical when phone styles change (sha256 of the desktop screenshot).

**Acceptance:** screenshots phone and desktop; 45 rows render under 50 ms on a mid-range phone (measured with Playwright's CDP tracing, recorded in the issue).

### Task 4.6: first screen, visitor meta, locate me

**Files:** modify `worker.js` (HTMLRewriter injects `<meta name="visitor">` from `request.cf.country` and `request.cf.regionCode` for HTML navigations; the AE log point moves to the same branch with the new blob order; nothing stored), `site/js/card.js`, `site/js/app.js`.

**Behaviour:** the first-screen card per spec 5.3 with the rank sentence; scenario toggle; "See the ranking" opens the sheet; "Locate me" calls `map.locate` on tap, drops a marker, pans, and shows the readout at that point; geolocation errors show a one-line message and nothing else.

**Acceptance:** opening `/` from a LT IP (owner's Android on mobile data) shows Lithuania; from the Mac's VPN exit shows Germany; `/europe/lt` always shows Lithuania; no network request carries coordinates (checked in devtools).

### Task 4.7: i18n

**Files:** create `site/js/i18n.js`; modify all UI modules to use `t()`.

**Behaviour:** dictionary `en` and `lt` with every UI string; unit and region names via `Intl.DisplayNames(lang, {type: 'region'})` with `name_en` fallback for level-4 units and unsupported browsers; language from hash, then localStorage, then `navigator.language`; `document.documentElement.lang` updated.

**Acceptance:** screenshots in both languages; no hard-coded English left (grep for quoted capitalised strings outside `i18n.js`).

### Task 4.8: About and analytics

**Files:** modify `site/index.html` (About section with the spec 5.7 content in both languages), `worker.js` (new AE dataset binding name from `wrangler.jsonc`, blobs: country, colo, referrer host, browser family, OS family, hostname, landing region, landing unit; skip bots and self-test rows as today), `wrangler.jsonc`.

**Acceptance:** the About section reads correctly in both languages; one preview visit produces one AE row in the new dataset with the expected blobs (checked with the analytics read token per `CLAUDE.local.md`); no IP or UA stored.

### Task 4.9: screenshot routine and owner phone check

**Files:** create `site/screenshots/README.md` (the Playwright routine as a script: `npm install playwright` in a scratch dir, `python3 -m http.server` on `site/`, the two viewports, sha256 comparison), `site/screenshots/*.png`.

**Acceptance:** reference screenshots committed; the owner has opened the preview URL on a phone and commented on the issue; OVERVIEW updated to say the preview exists.

### Stage 4 acceptance (issue checklist)

- [ ] preview worker live on every push to `europe`; `version.json` matches; perf budget enforced
- [ ] first screen, ranking, explore layer with readout, detail overlay, pole card, locate me, two languages, About, analytics
- [ ] reference screenshots committed, desktop byte-identical rule documented
- [ ] owner has used it on a phone
- [ ] nothing in `main` changed except docs

---

## Stage 5: North America

Issue: #11 "Stage 5: North America region run and region switch".

### Task 5.1: region config and masks

**Files:** create `pipeline/regions/north-america.yaml` (spec 2.1 column; `unit_countries: [us, ca]`; `expected_units: 64`; `max_distance_m: 400000`; `edge_mask_m: 50000`; `transcontinental: []`), `pipeline/regions/masks/north-america.geojson` (empty collection), `pipeline/poles/validate/refs.yaml` gains three cited US and Canadian references.

**Acceptance:** config loads; unit list reviewed in the issue (51 US including DC, 13 Canadian).

### Task 5.2: run and review

**Behaviour:** `poles run north-america` on this machine overnight (18 GB, tiled EDT with 1,600-cell overlap; record numbers); validation; contact sheet reviewed by the owner; publish to R2; `manifest.json` now has two regions.

**Acceptance:** zero blocking failures; Alaska tops the A ranking and the number passes check 1; spec 3.3 and 4.1 gain the North America numbers.

### Task 5.3: region switch in the site

**Files:** modify `site/js/ranking.js`, `site/js/card.js`, `site/js/router.js`, `site/js/i18n.js`.

**Behaviour:** a region control appears only when `regions.json` lists more than one region; switching changes path, ranking, explore archive, and the default view; level-4 units show the state name instead of a flag.

**Acceptance:** screenshots for `/north-america/us-ak`; opening `/` from a US visitor meta opens Alaska only if `regionCode` says AK, otherwise North America's winner.

### Stage 5 acceptance (issue checklist)

- [ ] North America snapshot published and verified on R2
- [ ] owner reviewed the contact sheet
- [ ] region switch live on the preview worker
- [ ] R2 usage total recorded; still inside 10 GB with headroom for a second snapshot of each region

---

## Stage 6: Cutover

Issue: #12 "Stage 6: name, domain, cutover, docs". Human one-time steps are marked (owner).

### Task 6.1: name

**Behaviour:** the owner and the session pick the name against the spec 8.1 requirements; availability checked at Hostinger by the owner; the worker name, I18N site title, `wrangler.jsonc`, the AE dataset name, the R2 bucket hostname plan, and README updated on the branch. DECISIONS entry.

### Task 6.2: domain and zone (owner)

**Behaviour:** domain bought at Hostinger; nameservers pointed at Cloudflare; zone added to the account on the free plan; the session verifies with `dig NS` and the Cloudflare API.

### Task 6.3: R2 hostname and CORS

**Behaviour:** `data.<domain>` connected to the bucket (custom domain on the bucket, proxied); CORS updated to the site origin only (dev origins removed); `regions.json` `r2_base` updated; HEAD and range checks rerun through the new hostname.

### Task 6.4: production worker and domain

**Files:** modify `wrangler.jsonc` (production env under the new name, custom domain route), `.github/workflows/deploy-cloudflare.yml` (production deploys from `main` under the new name; verify job hits the domain and `version.json`).

**Behaviour:** first production deploy from the branch by manual workflow dispatch to prove the path; live URL verified; then `europe` merged to `main` and the push deploy verified again.

### Task 6.5: redirect worker for the old name

**Files:** create `redirect/worker.js` (301 to `https://<domain>/europe/lt` for every path, no logging), `redirect/wrangler.jsonc` (worker name `atokiausia-lietuva`); modify `.github/workflows/deploy-cloudflare.yml` (deploy the redirect when `redirect/**` changes).

**Behaviour:** deployed only after task 6.4 is verified; `curl -I` on the old URL returns 301 with the new Location; the LinkedIn link is clicked once by the owner and lands on the Lithuania view.

### Task 6.6: monitors, analytics, cleanup

**Behaviour:** UptimeRobot monitor 803787678 retargeted to the new domain (v2 edit API); a new v3 monitor on the old URL expecting 301; the old AE dataset left to age out; `scripts/`, old `site/data/*`, and the LT-only worker code deleted in the merge; `README.md` rewritten for the new project; `.gitignore` reviewed.

### Task 6.7: docs and vault

**Behaviour:** OVERVIEW (status, what works, URLs), DECISIONS (cutover entries), LOG (launch entry), IDEAS (Europe and leaderboard sections marked shipped, everything else untouched), CLAUDE.md (layout, URLs, conventions), CLAUDE.local.md (bucket, dataset, monitors, hostnames); the vault page `wiki/projects/pole-of-remoteness.md` updated per the vault's own rules with a `Wiki-Op:` trailer.

### Stage 6 acceptance (issue checklist)

- [ ] new domain live, `version.json` matches `main`
- [ ] old URL returns 301 to `/europe/lt`; LinkedIn link works
- [ ] monitors retargeted and green; analytics rows arriving in the new dataset
- [ ] `main` contains only the new site and pipeline; old code gone from the tree
- [ ] all docs and the vault page updated
- [ ] owner's LinkedIn post (not a repo task; the stage closes without it)

---

## Stage 7: Automated refresh (parked until the owner says go)

Issue: #13 "Stage 7: scheduled refresh via Hetzner with a PR gate", labelled `parked`.

### Task 7.1: provisioning workflow

**Files:** create `.github/workflows/refresh.yml` (schedule yearly plus manual dispatch; inputs: region list), `pipeline/deploy/cloud-init.yaml`, `pipeline/deploy/run-remote.sh`.

**Behaviour:** the workflow creates a Hetzner Cloud server (16 vCPU, 32 GB, 360 GB disk) via the API with `HCLOUD_TOKEN` from GitHub secrets, passes cloud-init that installs Docker, pulls the pipeline image (built and pushed to GHCR by `pipeline-tests.yml` on `main`), runs `poles run <region>` with the R2 key from a secret, uploads, posts the validation summary back, and deletes the server in a `finally` step even on failure (a second "reaper" job lists servers older than 12 h with the project tag and deletes them).

### Task 7.2: diff report and PR

**Files:** create `pipeline/poles/publish/diff.py`, `pipeline/tests/test_diff.py`; modify `.github/workflows/refresh.yml`.

**Behaviour:** compares the new snapshot's `units.json` and unit JSON with the live manifest's: poles moved over 500 m, distance changes over 1%, rank changes, new or missing units; writes a markdown summary; the workflow opens a PR that updates `manifest.json` and the site JSON, attaches the summary and links to the contact sheet on R2. Merge deploys; nothing publishes without the merge.

**Tests:** `test_diff_reports_moved_poles_and_rank_changes`; `test_diff_empty_when_identical`.

### Stage 7 acceptance (issue checklist)

- [ ] a manual dispatch completes end to end for Europe and opens a PR
- [ ] the server is gone afterwards (verified via API) and the bill is under 1 EUR
- [ ] a failed run still deletes the server and reports the failure

---

## Self-review against the spec

Coverage: spec 2.1 regions (1.1, 5.1); 2.2 units and exclusions (2.1, 3.5); 2.3 definitions (1.5, 2.3, 2.4); 2.4 accuracy tiers (2.3, 3.2, 3.3, 4.3); 3 pipeline stages and tests (1.2-1.7, 2.x, 3.x); 3.3 resource envelope (1.6, 1.8, 5.2 record the numbers); 3.4 class table (3.1); 4.1 data layout and manifest (3.4, 3.5); 4.2 R2 hostname (3.4 dev, 6.3 production); 5.1-5.10 site (4.1-4.9, 5.3); 6 validation (2.5, 2.6); 7 cadence (snapshot everywhere, 7.x); 8 naming, domain, cutover (6.x); 9 not included (nothing here builds any of it); 10 stages (this document).

Interface consistency: `ClassTable` constants `EDGE`/`NODATA` are used by 3.2, 3.3, 4.3, 4.4; `Pole.detail` keys match the R2 key pattern used by 3.3 and 4.4; `router.js` hash keys match the state list in 4.2 and 4.6; `RegionConfig.expected_units` and `transcontinental` are in the shared interface and in spec 2.1; tiles and detail rasters are grayscale class values everywhere (3.2, 3.3, 4.3, 4.4), colours live only in the site's tokens.
