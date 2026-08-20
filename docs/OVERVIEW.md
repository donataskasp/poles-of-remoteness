# Overview: what works, what is not done

The re-orientation doc for sessions weeks apart. Read after CLAUDE.md, before touching anything. Update immediately when a feature lands or status changes, not at session end.

## Status (2026-08-21)

The LT-only site is a finished quick demo, live at the Cloudflare URL, and **disposable** (owner decision 2026-08-20). The Europe version is being built on branch `europe` from the approved spec `docs/EUROPE_SPEC.md` and plan `docs/EUROPE_PLAN.md` (epic #6, stage issues #7 to #13). **Stage 1 (#7, pipeline foundation) is done**: the `pipeline/` package (region config, resumable `poles` CLI, fetch, extract, classify, grid), 97 pytest tests green locally and in CI inside the container, and Europe computed through the grid stage on the owner's Mac (snapshot 2026-08-19, about 1.5 h end to end; numbers in spec 3.3, tile-size measurement in spec 4.1). `main` still serves the LT site untouched.

**NEXT-UP**: Stage 2 (#8), poles and validation, on branch `europe`. Before coding: label #8 `in-progress`, write the step-level plan from `docs/EUROPE_PLAN.md` Stage 2, then start with task 2.1 (units). Read #15 (ES, FR, NL, NO country polygons do not assemble from the extract; 116,979 boundary polygons include island ways, filter `osm_type = 'r'`) and #16 (road layers are unindexed; a 101 M-feature indexed FlatGeobuf is unreadable in GDAL 3.13) first; both change task 2.1 and 2.3. Every layer is opened through its `<layer>.vrt` handle (see DECISIONS 2026-08-20, stage 1).

## What works

- Europe pipeline through grid (`pipeline/`, branch `europe`): `poles run europe` fetches and verifies the six Geofabrik PBFs, extracts highways, boundaries, places, water and land into FlatGeobuf layers, classifies roads into scenarios A and B, and computes the 250 m distance grids (`work/europe/2026-08-19/grid/dist_A.tif`, `dist_B.tif`, `land.tif`, 28,588 x 23,625 cells, EPSG:3035) with a tiled exact transform; every stage resumes from `done.json` and the extract from per-artefact `.ok` markers; the same code runs in the container (`pipeline/Dockerfile`) and CI (`pipeline-tests.yml`)
- LT map with scenarios A and B, computed on a 50 m grid from a 2026-08-17 OSM snapshot; spots and distance bands published in `site/data/` (~5 MB)
- Compute pipeline `scripts/01..06` (download -> prepare -> compute -> report -> webdata -> sitedata); heavy inputs gitignored and regenerable
- Site: lt/en i18n, URL-hash state, satellite default basemap, mobile bottom pill, dark variant
- Analytics: edge logger to Workers Analytics Engine (ground truth since 2026-08-18), plus raw asset request counts for volume. The CF Web Analytics beacon was removed 2026-08-20 as redundant once the mirror was gone.
- Deploys: Cloudflare Worker via CI on push (since 2026-08-20, `deploy-cloudflare.yml`) with a post-deploy verify job. Cloudflare is the only target; the GitHub Pages mirror was removed 2026-08-20.
- Monitoring: UptimeRobot checks the live URL every 5 minutes with email alerts (since 2026-08-20)
- Launched 2026-08-17 via LinkedIn post

## Not done yet / parked (build only on owner's go)

- Europe and North America version: stage 1 done (#7); remaining stages: poles and validation (#8), publish (#9), site on the preview worker (#10), North America (#11), cutover with name and domain (#12), automated refresh (#13, parked). Stage-2 inputs filed from the stage-1 run: #15 (missing country polygons), #16 (spatial access to 75 M roads).
- Custom domain and the rename: part of the cutover stage (#12); the name is parked until then, owner wants help picking it; domain will be bought at Hostinger.
- Stats viewer page for the Analytics Engine data (parked, unchanged)
- Analytics retention snapshots (AE keeps ~3 months; ground truth starts 2026-08-18, first data at risk ~2026-11-18)
- Mobile app exercise (Expo, GPS remoteness compass): explicitly not v1; the spec keeps the data usable offline later

## Known gaps (addressed by the Europe plan)

- No version stamp on the site, so CI verify jobs prove content is served, not that THIS commit is live; `version.json` lands in stage 4 (#10)
- No automated screenshot check for the desktop-byte-identical rule; stage 4 commits reference screenshots and the routine
