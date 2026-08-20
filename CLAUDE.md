# Atokiausia Lietuva — pole of remoteness

Interactive map of the places in Lithuania farthest from any drivable road, computed from OpenStreetMap data on a 50 m grid.

- Live: https://atokiausia-lietuva.donatas-kasparavicius.workers.dev (primary, Cloudflare Workers)
- Mirror: https://donataskasp.github.io/atokiausia-lietuva/ (GitHub Pages, deployed by CI)

## Scenarios

- **A**: distance to any drivable way, forest tracks included
- **B**: distance to public roads only, tracks excluded

## Layout

- `scripts/` — Python compute pipeline (OSM extract -> distance grids -> spots/bands). Heavy inputs and grids are gitignored and regenerable.
- `site/` — the deployed website. Plain HTML/CSS/JS, no build step, no framework. Vendored Leaflet 1.9.4. `site/data/` holds the published results and MUST stay in git (the root `.gitignore` entry is `/data/`, root-anchored on purpose).
- `worker.js` + `wrangler.jsonc` — Cloudflare Worker: serves `site/` as static assets; GET requests to `/` also log one privacy-clean view to Workers Analytics Engine (dataset `atokiausia_views`, blob order documented in the file). No IPs, no raw user agents, no cookies.
- `.github/workflows/pages.yml` — deploys `site/` to GitHub Pages on pushes to main that touch `site/**`.

## Site conventions

- All text goes through the I18N dict (lt + en) in `js/app.js`; browser language picks the default, hash/localStorage override.
- URL hash carries state (scenario, spot, position, basemap, lang); satellite is the default basemap.
- Design tokens in `:root` with a `prefers-color-scheme` dark variant.
- Mobile (<=720px) shows the readout as a bottom-anchored pill; desktop layout must not change when touching mobile styles (verify with byte-identical screenshots).

## Deploying

- Cloudflare: `npx --yes wrangler deploy` from the repo root.
- GitHub Pages: push to main (only `site/**` changes trigger the workflow).
- Verify against BOTH live URLs. The workers.dev edge may serve briefly cached HTML after a deploy; use a cache-buster query param before concluding a deploy failed. New worker versions also take a few seconds to roll out; verification requests fired immediately after deploy can hit the old version.

## Hard rules

- No em dashes anywhere: site copy, docs, commit messages.
- No secrets in this repo, ever (it is public). Operational notes with local paths live in `CLAUDE.local.md`, which is gitignored.
- Keep the no-build-step property; do not introduce bundlers or frameworks.

## Roadmap (parked, build only on owner's go)

- Europe-wide version (30 GB Geofabrik PBF, 250 m continental pass in EPSG:3035, local UTM refinement, PMTiles for serving) plus a custom domain when it lands
- Country selector and per-country leaderboards
- Self-serve stats viewer page for the Analytics Engine data
- Analytics retention snapshots (AE keeps ~3 months)
- Mobile app exercise (Expo, GPS remoteness compass, offline; no backend)

## Docs

- `docs/DECISIONS.md` — dated decision log with rationale; append, don't relitigate
- `docs/IDEAS.md` — parked plans (Europe, app, stats viewer); build only on owner's go
- `docs/LOG.md` — sparse project log of big events
