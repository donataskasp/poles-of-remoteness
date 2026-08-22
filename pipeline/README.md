# poles: the compute pipeline

One command per region: `poles run europe`. Stages `fetch, extract, classify, grid, poles, validate, publish` run in order, each resumable through `work/<region>/<snapshot>/<stage>/done.json`. `--stage X` runs one stage, `--force` reruns a finished one, `--snapshot YYYY-MM-DD` pins the snapshot (default: the primary source's Last-Modified date).

Local setup: `uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r requirements.txt -e .`; tools on PATH: osmium, ogr2ogr, ogrinfo, gdal_rasterize, gdalwarp, gdal_translate, gdaladdo, pmtiles. Tests: `.venv/bin/python -m pytest -q`. Container: `docker build -t poles pipeline/` then `docker run --rm -v "$PWD/work:/work" poles run europe --work /work`.

`poles` searches every unit and scenario for the points farthest from a road, from the coarse grid down to an exact 5 m sweep in the local UTM zone, and writes `A.json` and `B.json` with the nearest road and settlement; `validate` re-derives every one of those numbers by an independent geodesic path, runs the membership, data-edge, grid-shift, hole, reference and invariant checks, writes `report.json`, `report.html` and `contact-sheet.html`, and exits non-zero on a blocking failure.

Regions live in `regions/<region>.yaml`; nothing in code names a region. A region may point `references:` at a file of reference poles beside it (Europe: `regions/europe-refs.yaml`) for check 6 to compare against; without the key check 6 reports that the config names no reference file and does not block. Spec and plan: `docs/EUROPE_SPEC.md`, `docs/EUROPE_PLAN.md`.
