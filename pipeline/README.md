# poles: the compute pipeline

One command per region: `poles run europe`. Stages `fetch, extract, classify, grid, poles, validate, publish` run in order, each resumable through `work/<region>/<snapshot>/<stage>/done.json`. `--stage X` runs one stage, `--force` reruns a finished one, `--snapshot YYYY-MM-DD` pins the snapshot (default: the primary source's Last-Modified date).

Local setup: `uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r requirements.txt -e .`; tools on PATH: osmium, ogr2ogr, ogrinfo, gdal_rasterize, gdalwarp, gdal_translate, gdaladdo, pmtiles. Tests: `.venv/bin/python -m pytest -q`. Container: `docker build -t poles pipeline/` then `docker run --rm -v "$PWD/work:/work" poles run europe --work /work`. `tests/test_docs_pins.py` reads the repository docs and skips itself when they are absent (the CI image carries only `pipeline/`), so set `POLES_REPO_ROOT` to the checkout to run the pins from anywhere else.

`poles` searches every unit and scenario for the points farthest from a road, from the coarse grid down to an exact 5 m sweep in the local UTM zone, and writes `A.json` and `B.json` with the nearest road and settlement; `validate` re-derives every one of those numbers by an independent geodesic path, runs the membership, data-edge, grid-shift, hole, reference and invariant checks, writes `report.json`, `report.html` and `contact-sheet.html`, and exits non-zero on a blocking failure.

Regions live in `regions/<region>.yaml`; nothing in code names a region. A region may point `references:` at a file of reference poles beside it (Europe: `regions/europe-refs.yaml`) for check 6 to compare against; without the key check 6 reports that the config names no reference file and does not block. Spec and plan: `docs/EUROPE_SPEC.md`, `docs/EUROPE_PLAN.md`.

## Stages

`docs/diagrams/01-pipeline.md` draws what follows, including the files each stage opens. Paths below are relative to `work/<region>/<snapshot>/`; `shared/` is `work/shared/` and belongs to no region. Wall clock is the Europe run of record (snapshot 2026-08-19, M4 Pro, 24 GB, 4 workers); the full table with peak memory and disk is `docs/EUROPE_SPEC.md` 3.3.

| Stage | Reads | Writes | Europe wall clock |
|---|---|---|---|
| `fetch` | the `sources` and `supplement_sources` URLs, and the `.poly` beside each | `<name>-latest.osm.pbf` and its `.md5`, `<name>.poly`, `snapshot.json` | 12 min download, 58 s verification |
| `extract` | `fetch/<name>-latest.osm.pbf` | `filtered.pbf`, the thematic PBFs, a FlatGeobuf set per layer behind `highways.vrt`, `boundaries.vrt`, `places.vrt` and `water.vrt`, plus the land polygons once into `shared/land.vrt` | about 60 min from scratch, 259 s resumed |
| `classify` | `extract/highways.vrt` | `roads_A.fgb`, `roads_B.fgb` | 255 s |
| `grid` | `fetch/snapshot.json` and the primary `.poly` it names, which set the frame, `classify/roads_<S>.fgb`, `extract/water.vrt`, `shared/land.vrt` | `frame.json`, `roads_A.tif`, `roads_B.tif`, `dist_A.tif`, `dist_B.tif`, `land.tif`, `water_proj.fgb` | 402 s |
| `poles` | `extract/boundaries.pbf`, `highways.vrt`, `places.vrt`, `grid/frame.json`, `dist_<S>.tif`, `water_proj.fgb`, `shared/land.vrt`, `fetch/<name>.poly` for the data edge | `countries.fgb`, `units.fgb`, `units.tif`, `units_low.tif`, `units.json`, `land_idx.fgb`, `water_big.fgb`, the 5 degree road tiles under `roads/` behind their index `roads/tiles.json`, `results/<unit>-<scenario>.json`, `A.json`, `B.json`, `timing.json` | 834 s for 104 jobs on 4 workers, after a one-off 49 min for the road tiles |
| `validate` | `poles/A.json`, `B.json`, `units.json`, `units.fgb`, `water_big.fgb`, `roads/`, `grid/frame.json` and the four rasters | `frame_shift.json` and the half-shifted grid, `shifted_winners.json`, `report.json`, `report.html`, `contact-sheet.html` | 1,429 s |
| `publish` | `grid/dist_<S>.tif`, `land.tif`, `frame.json`, `fetch/<name>.poly`, `poles/A.json`, `B.json`, `units.json`, `roads/`, `validate/report.json` and the two HTML reports | `inputs.json` (the stamp the explore artefacts were built from), `inside.tif`, `edgeband.tif`, `explore_<S>.tif`, `A.pmtiles`, `B.pmtiles`, `detail/<unit>/<scenario>-<rank>.png` and `.json` under the stamp `detail/published.json`, then the R2 objects and the site JSON | 962 s local part, the upload on top |

## Region config keys

Every top-level key of `regions/<region>.yaml`, in the order the file uses. The loader in `poles/config.py` rejects an unknown key, a missing required one and a wrong type, so this table and that module are the same list. Defaults apply to the optional keys only.

| Key | Type | Meaning |
|---|---|---|
| `id` | string | the region id: every path, R2 key and URL segment is built from it (`europe`, `north-america`) |
| `name` | string | the region's display name, published in `regions.json` |
| `code` | string | the UN M49 area code (or an ISO 3166-1 alpha-2 code) the site localises the region's name from through `Intl.DisplayNames`: `"150"` Europe, `"003"` North America; quoted so YAML keeps the leading zero; `name` is the English fallback |
| `sources` | list of strings | the Geofabrik `-latest.osm.pbf` URLs that define the region; the `.poly` beside each is the data edge. At least one is required |
| `supplement_sources` | list of strings | extracts whose roads count but whose countries never become units. Default `[]` |
| `coarse_crs` | string | the equal-area CRS of the coarse grid, an EPSG code or a PROJ string |
| `coarse_res_m` | int | coarse grid resolution in metres |
| `unit_admin_level` | int | the OSM `admin_level` the units come from: 2 for countries, 4 for states and provinces |
| `unit_countries` | list of strings or null | the countries that yield units; null means every country in the extract. Default null |
| `unit_exclude` | list of strings | countries whose roads count but which never become units; always wins over `unit_countries`. Default `[]` |
| `unit_code_tag` | string | the boundary tag the unit code is read from (`ISO3166-1`, `ISO3166-2`), lowercased |
| `territory_mask` | list of `{name, bbox}` | lon/lat boxes `[west, south, east, north]` cut out of the units, so a country is scored on its main territory. Default `[]` |
| `edge_mask_m` | int | the band inside the data edge published as the edge class instead of a distance |
| `max_distance_m` | int | the cap of the distance transform: the grid saturates here, so it has to stay above the region's true maximum |
| `top_n` | int | how many poles are kept per unit and scenario |
| `detail_res_m` | int | the resolution of the per-pole detail raster |
| `detail_window_m` | int | the width of the window that raster covers |
| `class_table` | list of ints or null | per-region override of the class edges; null uses the default table of `docs/EUROPE_SPEC.md` 3.4. Default null |
| `expected_units` | int or null | the unit count the poles stage gates on, and validate's check 7 re-checks; null skips the gate. Default null |
| `transcontinental` | list of strings | unit codes flagged transcontinental in `units.json` and in the UI; the unit itself stays whole. Default `[]` |
| `references` | string or null | a reference-pole file beside this config for check 6; without it check 6 reports that and does not block. Default null |

## Publish

`publish` turns the finished grids, poles and validation into what the site serves. Per scenario it quantises the coarse distance grid into a one-byte class raster (the edge band from the union of the source `.poly` files buffered by `edge_mask_m`, NODATA off land and beyond that union), warps it to EPSG:3857 at the z9 resolution, cuts and packs a z0 to z9 pyramid and writes `A.pmtiles` and `B.pmtiles`. Per published pole it renders a `detail_res_m` raster over a `detail_window_m` window from the road tiles, as a grey PNG of class values with a JSON georeference sidecar. It then uploads the archives, the detail rasters and validation's `report.json`, `report.html` and `contact-sheet.html` to R2 under `<region>/<snapshot>/` with immutable cache headers, verifies every key with a HEAD and each archive with a 16 KiB range request, and only after that writes the site documents: `regions.json`, `manifest.json`, `<region>/units.json` and `<region>/units/<code>.json`. Poles that validation excluded are dropped and the remaining ranks recomputed, so the stage refuses to run without `validate/done.json`.

R2 is configured by environment. The secrets are file contents, never values in the environment; each file holds one line, mode 600, and lives outside the repository:

- `POLES_R2_ACCOUNT_ID`: the Cloudflare account id.
- `POLES_R2_BUCKET`: the bucket name, created if it does not exist.
- `POLES_R2_TOKEN_FILE`: file holding the Cloudflare API token with R2 admin read and write, used for bucket creation, the managed `r2.dev` domain and CORS.
- `POLES_R2_ACCESS_KEY_ID_FILE`: file holding the S3 access key id used for the uploads.
- `POLES_R2_SECRET_FILE`: file holding the S3 secret.
- `POLES_R2_BASE` (optional): the public base URL; when set it must equal the bucket's managed `r2.dev` domain, which the stage otherwise discovers.

Two flags belong to this stage: `--site-dir DIR` (default `$POLES_SITE_DIR` when set, otherwise the repository's `site/data`) names the directory that receives the site documents, and `--no-write-site` keeps them under the work directory only.

The local part runs before the R2 configuration is read, so a machine without the credentials still builds every artefact: without the variables the stage stops with a `PublishError` naming them, writes no `done.json`, and a rerun with them set resumes at the upload from the per-artefact markers. The stage stamps what the explore chain was built from in `publish/inputs.json` (the class table, `edge_mask_m`, and the size and modification time of every grid raster and source `.poly` behind it): a changed class table, a changed edge mask or a rebuilt grid raster clears the markers and the tile directories and rebuilds the explore layer, and the detail rasters rebuild on a changed class table or published set, while `--force` rebuilds everything including the tile directories and re-uploads every key. The site documents are written only after the verification, so `site/data` can never name an object that did not answer. Every document is validated against the JSON schemas in `poles/schemas/` before it is written; those schemas are the contract with the site, they carry `additionalProperties: false`, and changing one is a `docs/DECISIONS.md` entry.
