# Overview: what works, what is not done

The re-orientation doc for sessions weeks apart. Read after CLAUDE.md, before touching anything. Update immediately when a feature lands or status changes, not at session end.

## Status (2026-08-22)

The LT-only site is a finished quick demo, live at the Cloudflare URL, and **disposable** (owner decision 2026-08-20). The Europe version is being built on branch `europe` from the approved spec `docs/EUROPE_SPEC.md` and plan `docs/EUROPE_PLAN.md` (epic #6, stage issues #7 to #13). **Stage 1 (#7, pipeline foundation) is done**: the `pipeline/` package (region config, resumable `poles` CLI, fetch, extract, classify, grid), 97 pytest tests green locally and in CI inside the container, and Europe computed through the grid stage on the owner's Mac (snapshot 2026-08-19, about 1.5 h end to end; numbers in spec 3.3, tile-size measurement in spec 4.1). **Stage 2 (#8, poles and validation) is done 2026-08-22**: the `poles` and `validate` stages, 232 pytest tests green, and a clean Europe run (run 3) with 0 blocking failures. What exists on disk under `work/europe/2026-08-19/`: `poles/A.json` and `poles/B.json` (52 units, 918 poles with nearest road and nearest settlement), `poles/units.json`, the 5-degree road tiles under `poles/roads/`, and `validate/report.json`, `validate/report.html` and `validate/contact-sheet.html` (10.9 MB). Lithuania is reproduced from the continental run: A 3,426.0 m at 54.441478 N 23.537029 E against the published 3,425.6 m, B 6,675.9 m at 53.995841 N 24.463029 E against 6,674.6 m. **Open for the owner**: the contact sheet is waiting for a look, and with it the minimum-island-size question, because sub-cell offshore rocks legitimately win poles under the current rules (Finland A and B at Bogskar 52.8 km, Croatia B at Palagruza, Iceland at Kolbeinsey, Guernsey and Jersey skerries); the question is posted on #8 and does not block stage 3. `main` still serves the LT site untouched.

**NEXT-UP**: Stage 3 (#9), publish: class table, explore tiles, PMTiles, detail rasters, R2 upload, site JSON and manifest, on branch `europe`. Before coding: label #9 `in-progress`, write the step-level plan from `docs/EUROPE_PLAN.md` Stage 3, then start with task 3.1. Two carry-overs from stage 2: the road tiles under `work/europe/2026-08-19/poles/roads/` are the input for the 50 m detail rasters (do not rebuild them, they cost 49 minutes), and the parts of validation check 7 that were deferred belong here (the class table's monotonicity and round-trip, and a HEAD request on R2 for every object the manifest names). Stage 3 also owns the geodesic `area_km2` (#20) and uploading `contact-sheet.html` under `validation/`.

## What works

- Europe pipeline through validation (`pipeline/`, branch `europe`): `poles run europe` fetches and verifies the six Geofabrik PBFs, extracts highways, boundaries, places, water and land into FlatGeobuf layers, classifies roads into scenarios A and B, computes the 250 m distance grids (`work/europe/2026-08-19/grid/dist_A.tif`, `dist_B.tif`, `land.tif`, 28,588 x 23,625 cells, EPSG:3035) with a tiled exact transform, assembles 52 country units from the OSM boundary relations, searches each unit and scenario by branch-and-bound down to an exact 5 m sweep in the local UTM zone with nearest road and nearest settlement attribution, and validates every published pole against an independent geodesic path (report, contact sheet, non-zero exit on a blocking failure); every stage resumes from `done.json` and the long sub-steps from per-artefact `.ok` markers; the same code runs in the container (`pipeline/Dockerfile`) and CI (`pipeline-tests.yml`)
- LT map with scenarios A and B, computed on a 50 m grid from a 2026-08-17 OSM snapshot; spots and distance bands published in `site/data/` (~5 MB)
- Compute pipeline `scripts/01..06` (download -> prepare -> compute -> report -> webdata -> sitedata); heavy inputs gitignored and regenerable
- Site: lt/en i18n, URL-hash state, satellite default basemap, mobile bottom pill, dark variant
- Analytics: edge logger to Workers Analytics Engine (ground truth since 2026-08-18), plus raw asset request counts for volume. The CF Web Analytics beacon was removed 2026-08-20 as redundant once the mirror was gone.
- Deploys: Cloudflare Worker via CI on push (since 2026-08-20, `deploy-cloudflare.yml`) with a post-deploy verify job. Cloudflare is the only target; the GitHub Pages mirror was removed 2026-08-20.
- Monitoring: UptimeRobot checks the live URL every 5 minutes with email alerts (since 2026-08-20)
- Launched 2026-08-17 via LinkedIn post

## Not done yet / parked (build only on owner's go)

- Europe and North America version: stages 1 and 2 done (#7, #8); remaining stages: publish (#9), site on the preview worker (#10), North America (#11), cutover with name and domain (#12), automated refresh (#13, parked). Open pipeline follow-ups from the stage-2 run: #17 (road tile rebuild takes an hour), #18 (per-unit cache not invalidated by a grid rerun), #19 (edge bound flags poles behind open-sea legs of the extract edge), #20 (`area_km2` from geometry).
- Custom domain and the rename: part of the cutover stage (#12); the name is parked until then, owner wants help picking it; domain will be bought at Hostinger.
- Stats viewer page for the Analytics Engine data (parked, unchanged)
- Analytics retention snapshots (AE keeps ~3 months; ground truth starts 2026-08-18, first data at risk ~2026-11-18)
- Mobile app exercise (Expo, GPS remoteness compass): explicitly not v1; the spec keeps the data usable offline later

## Known gaps (addressed by the Europe plan)

- No version stamp on the site, so CI verify jobs prove content is served, not that THIS commit is live; `version.json` lands in stage 4 (#10)
- No automated screenshot check for the desktop-byte-identical rule; stage 4 commits reference screenshots and the routine
