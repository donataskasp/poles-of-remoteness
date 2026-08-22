# Development harness

Everything here is for developing the site locally and for the screenshot routine. Nothing in this directory is deployed; `dev/out/` is gitignored.

## One-time

- Node 22 or newer on PATH (`export PATH=/opt/homebrew/bin:$PATH`).
- A finished local publish run of a region under `work/<region>/<snapshot>/publish/` (the archives and detail rasters). The site JSON for development comes from it:
  `pipeline/.venv/bin/python dev/site-json.py --region europe --snapshot 2026-08-19`
  writes `dev/out/site/` with `r2_base` pointing at the dev server. Never point it at `site/data/`.

The dev JSON is the same shape the publish stage writes, with two differences: `r2_base` is the local dev server rather than R2, and the `verified` block is a placeholder. `regions.schema.json` requires an `https://` base, so the documents are built and validated with a placeholder and the local base is substituted afterwards.

## Run

`node dev/serve.mjs --site site --data dev/out/site --r2 work/europe/2026-08-19/publish --r2-prefix europe/2026-08-19 --port 8000`

Then open `http://localhost:8000/europe/lt`. The server serves the site with the SPA rule (extension-less paths get `index.html`), `/data/*` from `dev/out/site/` (falling back to `site/data/`), and `/r2/<region>/<snapshot>/*` from the publish directory with HTTP ranges, which is what the pmtiles library needs. A miss under `/data/` or `/r2/` is a 404, never the SPA page, so a wrong prefix fails loudly instead of feeding HTML to a parser expecting JSON or tile bytes.

## Tests

`node --test 'dev/tests/*.test.mjs'` runs the pure-logic suites (router, data, readout, palette, i18n, worker helpers, the dev server). CI runs the same command (`site-tests.yml`).

Keep the glob and keep it quoted. Node treats an explicit positional argument as a test file, not as a directory to search, so `node --test dev/tests/` fails with `Cannot find module .../dev/tests` (checked on Node 22, 24 and 26). Quoting leaves the expansion to Node rather than the shell, so the command behaves the same in zsh, bash and CI.

## Unit identity

Unit codes and their `country` are lowercase ISO codes and the two are equal for a country-level unit:

```
$ python3 -c "import json; u=json.load(open('dev/out/site/europe/units.json'))['units']; print(u[0]['code'], u[0]['country'], u[0]['A'])"
ad ad {'dist_m': 4963.65, 'lat': 42.48936, 'lon': 1.642551, 'rank': 33, 'withheld': 0}
```

The visitor fallback compares that `country` with the country in the Worker's meta tag case-insensitively, so neither side may assume a case.

## Screenshots

See `docs/screenshots/README.md`.
