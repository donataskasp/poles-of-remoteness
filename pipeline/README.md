# poles: the compute pipeline

One command per region: `poles run europe`. Stages `fetch, extract, classify, grid, poles, validate, publish` run in order, each resumable through `work/<region>/<snapshot>/<stage>/done.json`. `--stage X` runs one stage, `--force` reruns a finished one, `--snapshot YYYY-MM-DD` pins the snapshot (default: the primary source's Last-Modified date).

Local setup: `uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r requirements.txt -e .`; tools on PATH: osmium, ogr2ogr, ogrinfo, gdal_rasterize, gdalwarp, gdal_translate, gdaladdo, pmtiles. Tests: `.venv/bin/python -m pytest -q`. Container: `docker build -t poles pipeline/` then `docker run --rm -v "$PWD/work:/work" poles run europe --work /work`.

Regions live in `regions/<region>.yaml`; nothing in code names a region. Spec and plan: `docs/EUROPE_SPEC.md`, `docs/EUROPE_PLAN.md`.
