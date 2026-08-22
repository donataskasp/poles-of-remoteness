# poles: the compute pipeline

One command per region: `poles run europe`. Stages `fetch, extract, classify, grid, poles, validate, publish` run in order, each resumable through `work/<region>/<snapshot>/<stage>/done.json`. `--stage X` runs one stage, `--force` reruns a finished one, `--snapshot YYYY-MM-DD` pins the snapshot (default: the primary source's Last-Modified date).

Local setup: `uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r requirements.txt -e .`; tools on PATH: osmium, ogr2ogr, ogrinfo, gdal_rasterize, gdalwarp, gdal_translate, gdaladdo, pmtiles. Tests: `.venv/bin/python -m pytest -q`. Container: `docker build -t poles pipeline/` then `docker run --rm -v "$PWD/work:/work" poles run europe --work /work`.

`poles` searches every unit and scenario for the points farthest from a road, from the coarse grid down to an exact 5 m sweep in the local UTM zone, and writes `A.json` and `B.json` with the nearest road and settlement; `validate` re-derives every one of those numbers by an independent geodesic path, runs the membership, data-edge, grid-shift, hole, reference and invariant checks, writes `report.json`, `report.html` and `contact-sheet.html`, and exits non-zero on a blocking failure.

Regions live in `regions/<region>.yaml`; nothing in code names a region. A region may point `references:` at a file of reference poles beside it (Europe: `regions/europe-refs.yaml`) for check 6 to compare against; without the key check 6 reports that the config names no reference file and does not block. Spec and plan: `docs/EUROPE_SPEC.md`, `docs/EUROPE_PLAN.md`.

## Publish

`publish` turns the finished grids, poles and validation into what the site serves. Per scenario it quantises the coarse distance grid into a one-byte class raster (the edge band from the union of the source `.poly` files buffered by `edge_mask_m`, NODATA off land and beyond that union), warps it to EPSG:3857 at the z9 resolution, cuts and packs a z0 to z9 pyramid and writes `A.pmtiles` and `B.pmtiles`. Per published pole it renders a `detail_res_m` raster over a `detail_window_m` window from the road tiles, as a grey PNG of class values with a JSON georeference sidecar. It then uploads the archives, the detail rasters and validation's `report.json`, `report.html` and `contact-sheet.html` to R2 under `<region>/<snapshot>/` with immutable cache headers, verifies every key with a HEAD and each archive with a 16 KiB range request, and only after that writes the site documents: `regions.json`, `manifest.json`, `<region>/units.json` and `<region>/units/<code>.json`. Poles that validation excluded are dropped and the remaining ranks recomputed, so the stage refuses to run without `validate/done.json`.

R2 is configured by environment. The secrets are file contents, never values in the environment; each file holds one line, mode 600, and lives outside the repository:

- `POLES_R2_ACCOUNT_ID`: the Cloudflare account id.
- `POLES_R2_BUCKET`: the bucket name, created if it does not exist.
- `POLES_R2_TOKEN_FILE`: file holding the Cloudflare API token with R2 admin read and write, used for bucket creation, the managed `r2.dev` domain and CORS.
- `POLES_R2_ACCESS_KEY_ID_FILE`: file holding the S3 access key id used for the uploads.
- `POLES_R2_SECRET_FILE`: file holding the S3 secret.
- `POLES_R2_BASE` (optional): the public base URL; when set it must equal the bucket's managed `r2.dev` domain, which the stage otherwise discovers.

Two flags belong to this stage: `--site-dir DIR` (default the repository's `site/data`, or `$POLES_SITE_DIR`) names the directory that receives the site documents, and `--no-write-site` keeps them under the work directory only.

The local part runs before the R2 configuration is read, so a machine without the credentials still builds every artefact: without the variables the stage stops with a `PublishError` naming them, writes no `done.json`, and a rerun with them set resumes at the upload from the per-artefact markers. The site documents are written only after the verification, so `site/data` can never name an object that did not answer. Every document is validated against the JSON schemas in `poles/schemas/` before it is written; those schemas are the contract with the site, they carry `additionalProperties: false`, and changing one is a `docs/DECISIONS.md` entry.
