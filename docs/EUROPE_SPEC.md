# Europe version: design spec

Status: written 2026-08-20 in the Europe planning session, from the kickoff brief in `docs/EUROPE_KICKOFF.md`. Every choice below was discussed and agreed with the owner in that session; the rationale is recorded in `docs/DECISIONS.md` under the same date. The staged plan that implements this spec is `docs/EUROPE_PLAN.md`; the stages are tracked as GitHub issues under the Europe epic (#6, stages #7 to #13).

The LT-only site is a disposable demo. Nothing here preserves its code, data format, or layout for compatibility. What is preserved: the LT site stays live and untouched until the cutover stage, and its public URL never breaks.

## 1. Goal

Extend "the point farthest from any drivable road" from Lithuania to Europe, then North America, as a static, free-to-host, fast-on-mobile website. The product is every unit's pole (one per country in Europe, one per state or province in North America), the ranking between them, and an explore layer that gives a remoteness number for any place on the map.

Two invariants define the project and are not up for renegotiation:

- **Privacy by design.** No cookies, no IP addresses, no raw user agents, no client-side analytics, no unique identifiers, nothing that needs a consent banner.
- **The owner runs nothing by hand.** Every recurring step is automated or designed away. The only human steps are one-time setup (buying the domain, pointing nameservers) and reviewing a pull request before data goes live.

## 2. Scope

### 2.1 Regions

A **region** is a config file, not a code path. Nothing in the pipeline or the site names Europe. A region config declares:

| Field | Europe | North America |
| --- | --- | --- |
| `sources` | Geofabrik `europe-latest.osm.pbf` (32.4 GB on 2026-08-20) | Geofabrik `north-america-latest.osm.pbf` (18.0 GB) |
| `supplement_sources` (roads count, no units) | Geofabrik `armenia`, `azerbaijan`, `iran`, `iraq`, `syria` (about 1.5 GB together) | none |
| `edge_polygon` | union of all source polygons | union of all source polygons |
| `coarse_crs` | `EPSG:3035` (LAEA centred 52N 10E) | `+proj=laea +lat_0=50 +lon_0=-100 +datum=WGS84 +units=m` |
| `coarse_res_m` | 250 | 250 |
| `unit_admin_level` | 2 (countries) | 4 (states and provinces) |
| `unit_countries` | all in extract except RU | US, CA (MX is a config change) |
| `unit_code` | ISO 3166-1 alpha-2, lowercase | ISO 3166-2, lowercase (`us-ak`) |
| `territory_mask` | Svalbard, Jan Mayen, Franz Josef Land, Novaya Zemlya, Azores, Madeira, Rockall | none (the unit list is explicit) |
| `edge_mask_m` | 50,000 | 50,000 |
| `max_distance_m` | 250,000 (was 150,000; raised 2026-08-20 so saturation stays inside class 253, see DECISIONS) | 400,000 |
| `top_n` | 10 | 10 |
| `expected_units` | 52 (counted on the 2026-08-19 snapshot in stage 2) | 64 (51 US incl. DC, 13 CA) |
| `transcontinental` | `tr`, `ge` | none |
| `detail_res_m` / `detail_window_m` | 50 / 20,000 | 50 / 20,000 |

Europe ships first. North America is the stage immediately after Europe passes validation, on the same branch, before or after public launch at the owner's discretion. Regions never share a ranking.

### 2.2 Units and the leaderboard

- A unit is an OSM admin boundary relation at the region's admin level, restricted to `unit_countries`, minus the territory mask, clipped to land. Units carry the ISO code from the relation's `ISO3166-1` or `ISO3166-2` tag.
- **Main territory only.** The territory mask removes remote islands that would top the list with zero roads and teach nothing (Svalbard alone would win Europe at over 100 km). Microstates stay in; a 140 m pole is a legitimate entry.
- **Russia is not a unit** in any ranking, top list, or selector. Its roads count in full, so Finnish, Baltic, and Ukrainian poles are scored honestly, and the explore layer covers whatever of western Russia the extract contains (the Europe extract stops at 46.75E, roughly the Volga), so the map has no hole.
- Turkey and Georgia are units, whole, flagged transcontinental in the UI. Cyprus, Iceland, Faroe, UK, Ukraine, Belarus, Moldova, and the Balkans are units. Canaries and Greenland are not in the Europe extract and are out.
- Contested borders (Crimea, Kosovo, Transnistria, Northern Cyprus) are **as mapped in OSM**, footnoted in the About section. OSM is the project's sole source and the project does not redraw politics.
- North America v1 units are the 50 US states plus DC and the 13 Canadian provinces and territories. Alaska tops its own board, which is the point of per-unit framing.

### 2.3 Definitions

- **Scenario A (headline)**: distance to any drivable way, forest tracks included. A can only under-report (an extra mapped track shrinks the number; it never makes it wrong), which makes it the defensible public claim.
- **Scenario B (secondary)**: distance to roads with `highway=track` excluded. Published alongside A; the A-to-B gap per unit is itself a finding and is shown.
- **Tag sets**, fixed in code and covered by tests. Set B: `motorway trunk primary secondary tertiary unclassified residential living_street service road busway` and the `_link` variants. Set A: set B plus `track`. Excluded from both regardless of other tags: `path footway cycleway bridleway steps pedestrian corridor proposed construction abandoned razed platform raceway bus_guideway escape elevator`, and any way with `highway` absent. Ways tagged `ice_road=yes` or `winter_road=yes` are included when their `highway` value is in the set. Ferry routes are not roads.
- **Physical, not legal.** Access tags (`access`, `motor_vehicle`, `private`) are ignored. A gated estate road is still a road.
- **Water does not block.** Distance is straight-line to the nearest drivable way. A roadless island is only as remote as the far shore's road.
- **Land** is the prebuilt OSM land polygons (osmdata.openstreetmap.de) minus OSM `natural=water` polygons of 1 km² or more. Bogs and wetlands stay in. The explore field over sea and large lakes is no-data.
- **Data edge.** Within `edge_mask_m` of the extract's edge polygon, distances are overestimates because roads beyond the edge do not exist in the data. The explore layer masks that band, and no pole may be published whose distance to the nearest edge is smaller than its claimed distance. A land edge is wherever the union of source polygons meets land. For Europe that is the Volga cut and, without supplements, Turkey's and Georgia's borders with Syria, Iraq, Iran, Armenia, and Azerbaijan; the Europe config therefore lists those five countries as `supplement_sources`, whose roads count but which contribute no units, so Turkey and Georgia are scored honestly. For North America the Mexico-Guatemala and Mexico-Belize borders are land edges, which matters only if Mexico becomes a unit country.

### 2.4 Accuracy, by tier

| What | Resolution | Accuracy |
| --- | --- | --- |
| Published poles | exact vector distance, 5 m search step, local UTM | metres; limited by OSM's drawing of the road, not by any grid |
| Detail rasters around poles | 50 m, 20 km square, top 10 per unit per scenario | same as the LT demo |
| Explore layer everywhere | 250 m in the region's equal-area projection | about ±0.2 km, plus up to 2% projection error at Europe's edges (5% in Alaska); shown as "about 1.2 km", one decimal under 10 km, integer above |

Moving the continental layer to 100 m is a one-line config change with roughly 4x the tile storage; it is revisited once real archive sizes are measured, not before.

## 3. Pipeline

### 3.1 Shape

A new `pipeline/` directory replaces `scripts/` (which is deleted at cutover). Python 3.12 package `poles` with a CLI, pinned `requirements.txt`, a `Dockerfile` so the laptop now and a rented box later run the identical thing, and `pipeline/regions/<region>.yaml`. Tools: osmium-tool, GDAL, scipy, shapely, pyproj, rasterio, pmtiles. Working data lives in `work/<region>/<snapshot>/` (gitignored, about 70 GB for Europe, regenerable from the snapshot identity).

One command per region: `poles run europe`. Seven stages, each resumable and idempotent, each writing outputs to disk so a crash at hour four does not restart hour one. Stages can be run individually (`poles run europe --stage grid`).

### 3.2 Stages

1. **fetch**: download `sources` and `supplement_sources`, verify the published checksums, record checksums and `Last-Modified` dates. Those are the snapshot identity `<region>/<YYYY-MM-DD>`.
2. **extract**: osmium merges the sources and pulls: all `highway=*` ways (as a highways PBF, then FlatGeobuf with `id`, `highway`, `name`, `ref`, `ice_road`, `winter_road`); admin boundary relations at `unit_admin_level` plus level 2 for `unit_countries`; settlement nodes (`place=city|town|village|hamlet|isolated_dwelling`); `natural=water` polygons of 1 km² or more. Land polygons are downloaded from osmdata (split, WGS84 variant).
3. **classify**: each way gets `set_a` and `set_b` booleans from the tag rules in 2.3. Output is a FlatGeobuf per scenario. Pure table logic, unit-tested.
4. **grid**: roads rasterised at `coarse_res_m` in `coarse_crs` over the extract bbox plus a margin of `max_distance_m`. Euclidean distance transform, **tiled with an exactness guarantee**: tiles of 4096 cells with overlap `max_distance_m / coarse_res_m`; any cell whose result is at least the overlap is unresolved and its tile is recomputed with doubled overlap until none remain or the overlap reaches `max_distance_m`, beyond which the cell is set to `max_distance_m` ("at least this far"; exact below the cap, see DECISIONS 2026-08-20). Runs on all cores. A single-array fallback exists for debugging. Output: float32 GeoTIFF per scenario, plus the land mask and unit-id raster at the same grid.
5. **poles**: per unit and scenario, branch-and-bound over the coarse grid: a cell is refined only if `coarse_value + 2 * half_diagonal * (1 + distortion_pad) >= best_confirmed_lower_bound`, where the pad is the LAEA scale error at that cell (2% at 2,500 km from centre). Refinement: exact vector distances (STRtree over the scenario's ways within `coarse_value * 1.2 + 1 km`) at 25 m then 5 m in the cell's UTM zone, as in the LT method. Top `top_n` per unit per scenario, deduplicated at 10 km, each with nearest way (id, highway, name, ref, country), nearest settlement (name, type, distance, coordinates), and unit membership.
6. **validate**: section 6. Writes `validation/report.json`, `report.html`, and `contact-sheet.html`. Any failure stops the run before publish.
7. **publish**: explore field masked at the data edge and over water, quantised to 8-bit classes (3.4), warped to EPSG:3857, tiled z0-z9 as single-band 8-bit PNG whose pixel value is the class (colours are applied client-side, so the readout is exact and palettes can change without regenerating tiles), packed into one PMTiles archive per scenario; detail rasters rendered for every published pole; everything uploaded to R2 under the immutable snapshot key; `units.json`, per-unit JSON, and `manifest.json` written into `site/data/`. Upload is part of the command, not a separate step.

### 3.3 Resource envelope

Machine: M4 Pro, 12 cores, 24 GB, 233 GB free before the run. Measured on the first full Europe run (snapshot 2026-08-19, stage 1, 2026-08-20/21) and on the stage-2 run of record (run 3, 2026-08-22), one command, laptop kept awake with `caffeinate`:

| Stage | Wall clock | Peak RSS | Disk after |
| --- | --- | --- | --- |
| fetch | download 12 min at about 50 MB/s (34.8 GB Europe plus 0.5 GB supplements), verification 58 s | 75 MB | 35.3 GB |
| extract | about 60 min from scratch: per-source combined filters 3.6 min, merge 102 s, highways filter 97 s, highways GeoJSONSeq export 30 to 50 min (single-threaded osmium, 37.7 GB of text), chunk conversion 3 min with 6 ogr2ogr processes, boundaries, places, water, land about 5 min; 259 s when resumed from the markers | osmium export 11 GB; each ogr2ogr chunk about 1.5 GB | 50.1 GB (filtered.pbf 10.2, highways.pbf 8.7, 141 highway chunks 24, water 3.8, boundaries 1.2, places 0.3) plus 2.3 GB of shared land polygons |
| classify | 255 s | about 1 GB | 30.9 GB (roads_A 74,664,480 ways, roads_B 57,262,375) |
| grid | 402 s: rasterize A 146 s and B 87 s, EDT 52 s and 50 s with 6 workers, land mask 58 s, A <= B check 10 s | gdal_rasterize 14.8 GB (A); EDT parent 6.2 GB plus 3.1 GB per worker | 4.5 GB (dist_A 0.34 GB, dist_B 0.37 GB compressed float32, masks) |
| poles | 834 s for 104 jobs (52 units x 2 scenarios) on 4 workers, including the unit rebuild; the road tiles are a one-off 49 min before it | 2.4 GB parent plus 6.6 GB cumulative across the 4 workers | 30.8 GB (road tiles 27, land index 1.4, countries and units 0.06, water 0.5) |
| validate | 1,429 s: check 1 recheck 375 s, check 3 edge bound 118 s, check 4 grid shift 859 s (the half-shifted grid is recomputed and every unit re-searched), check 5 holes 15 s, checks 2, 6 and 7 under a second, contact sheet 62 s with a warm tile cache (438 s cold) | 2.0 GB parent plus 8.9 GB cumulative across the workers | 0.79 GB (shifted grids 0.7, `contact-sheet.html` 10.9 MB, `report.html` 0.77 MB) |

Stage 2 adds about 38 minutes to the run. The search covered 52 units and 918 poles with 27,349 refinements; the slowest job was Luxembourg A at 318 s and 3,588 refinements (a wide plateau of low-relief farmland), and 12 of the 104 jobs passed the 500-refinement warning without approaching the 20,000 hard failure. Validation of run 3: 0 blocking failures and 17 warnings, check 1 918 of 918 with a worst relative error of 0.056 % (Greece B rank 5, 48,082.35 m claimed against 48,055.61 m geodesic, and 27.8 m is the largest absolute difference anywhere), check 2 918 of 918, check 3 909 of 918 with 9 poles excluded at the data edge (7 in Georgia, Spain B rank 1 on Alboran, Iceland B rank 9 in Hornstrandir), check 4 104 of 104 with no plateau ties needed, check 5 6 hole warnings on Guernsey and Jersey skerries, check 6 Lithuania reproduced (A 3,426.0 m against the published 3,425.6 m, B 6,675.9 m against 6,674.6 m) with 2 informative external references failing on their own road-set definitions, check 7 264 of 264 invariants. Total disk under `work/europe/2026-08-19/` after both stages is about 142 GB.

About 1.5 hours end to end including the download; the planning estimate of 4-5 hours was pessimistic because osmium and the tiled transform are fast and the download ran at 50 MB/s. The frame is 28,588 x 23,625 cells (675 M) at 250 m with the 250 km margin (the planning figure of 440 M ignored the margin and underestimated the bbox); the transform ran as 42 tiles with overlap 1000 cells and needed no doubling; 371 M (A) and 377 M (B) cells are saturated at 250 km, all sea or beyond the data edge; road cells 58.6 M (A) and 33.9 M (B); land cells inside the frame 308 M (19.3 M km2, the frame reaches into North Africa, the Middle East and Russia beyond the extract). Total disk about 123 GB for Europe (the planning figure was 70 GB); `filtered.pbf` and the thematic PBFs (about 19 GB) are only needed for reruns. Memory rule learned: EDT workers take 3.1 GB each at this window, so 4 workers is the safe default on 24 GB (`POLES_WORKERS` overrides); gdal_rasterize in single-pass mode is the other memory peak. The same classify stage run inside the container on the Mac (colima, virtiofs mount of `work/`) took 1166 s against 255 s natively with identical counts: the container is for portability and CI, the native venv for speed on this machine.

A rented Hetzner box (16 vCPU, 32 GB, about 0.10 EUR/h) does a full run for under 1 EUR and pulls the extract in minutes; the container makes the two interchangeable. GitHub-hosted runners (14 GB disk) cannot run the compute and are used only as orchestrator and deployer.

### 3.4 Class table

The explore layer and detail rasters store one byte per pixel: a class index whose lower edge is the distance. Default table (per-region override allowed): 50 m steps to 2.5 km (classes 0-49), 100 m steps to 10 km (50-124), 250 m steps to 30 km (125-204), 1 km steps to 60 km (205-234), 10 km steps from 60 km to 230 km (235-252), class 253 is "240 km or more", 254 is edge-masked, 255 is no-data. The table ships in `regions.json` so the site decodes without hard-coding it. Monotonicity and round-trip are unit-tested.

### 3.5 Tests

Real tests for the pipeline math, where a wrong number is invisible and would poison published data; no tests for Leaflet wiring or copy, where the honest check is a rendered screenshot. pytest, run in CI on every push touching `pipeline/`:

- tag classification against a table of tagged ways, including the exclusions and `ice_road`/`winter_road`
- class table monotonic, round-trip, and edge-mask/no-data reserved values
- tiled distance transform equals untiled on synthetic grids, including a case that forces the doubled-overlap path
- refinement returns the known answer for a synthetic geometry (single straight road, point at known offset) in a UTM zone
- branch-and-bound never prunes the true maximum on synthetic grids with planted maxima
- unit assignment, territory mask, land clip, and edge-distance bound on synthetic polygons
- manifest schema and published JSON schema

## 4. Serving and data layout

### 4.1 Where data lives

- **Git** (private repo): the site, `site/data/regions.json` (region list, class tables, snapshot per region), `site/data/<region>/units.json` (one row per unit: code, English fallback name, area, top-1 per scenario with rank), `site/data/<region>/units/<code>.json` (top 10 per scenario with all attributes and detail raster references), `site/data/manifest.json`. A few MB in total.
- **R2** (public bucket, read-only to the world): `<region>/<snapshot>/A.pmtiles`, `B.pmtiles`, `detail/<code>/<scenario>-<rank>.png` with a `.json` georeference sidecar, `validation/` (report and contact sheet). Measured 2026-08-20 (stage 1, task 1.8) from the Lithuania 25 m grid quantised to the class table, downsampled to 250 m, tiled z0-z9 in EPSG:3857 as 8-bit grey PNG, packed with `pmtiles convert`: z9 tiles average 6.3 KB (A) and 6.5 KB (B), at most about 20 KB; z0-z8 add 0.57x the z9 bytes; the archive costs 15.2 (A) and 15.9 (B) bytes per km2 of land. Projected explore-layer archives: Europe about 155 MB (A) plus 162 MB (B) on an assumed 10.2 M km2 of land (to be replaced by the grid's measured land area), North America about 372 MB plus 389 MB on 24.5 M km2; detail rasters come on top. Two snapshots retained per region stays well inside the free 10 GB. Lithuania lies entirely in the fine 50 m and 100 m class bands, so the figure is conservative for remote terrain. Tooling notes for stage 3: `gdal raster tile --no-alpha` writes true single-band grey tiles (the MBTiles driver path adds an alpha band, 27% larger), and `gdaladdo` cannot build MBTiles overviews below z5, so the z0-z9 pyramid comes from `gdal raster tile`.
- **Nowhere**: PBFs, road geometries, float grids. Regenerable from the snapshot identity.

`manifest.json` records, per region, the live snapshot key, the PBF checksum and date, the pipeline git commit, and the R2 base URL. **Publishing is a manifest commit; rollback is a revert.** This is how "data and the code that produced it are committed together" survives the move out of git.

### 4.2 How the browser reaches R2

The bucket is served through its own hostname on the project's zone (`data.<domain>`), with CORS allowing the site origin and `Range` requests. That path is unmetered, cached at Cloudflare's edge, and free; it is deliberately **not** proxied through the worker, whose invocations are metered at 100k per day on the free tier and would be exhausted by one busy evening of tile requests. Until the domain exists, the bucket's `r2.dev` hostname serves development and the preview worker.

A visit pulls 30-100 tiles. R2's free 10 M reads a month count only cache misses.

### 4.3 Limits verified 2026-08-20

- Workers static assets: 20,000 files per version, 25 MiB per file, free and paid alike; requests to assets are free and unlimited. Tile archives therefore cannot be static assets.
- R2 free tier: 10 GB-month storage, 1 M Class A, 10 M Class B operations per month, egress free.
- Workers free tier: 100k worker invocations per day; `run_worker_first` routes return 429 past that instead of falling back to assets.

## 5. Site

### 5.1 Stack

Plain HTML/CSS/JS, no bundler, no framework, vendored Leaflet 1.9.4 and the pmtiles JavaScript library (used only to fetch tiles by range request; a Leaflet `GridLayer` paints them). The site has no build step; the data has one, and it is the pipeline. Design tokens in `:root` with a `prefers-color-scheme` dark variant. MapLibre GL is the named fallback if the canvas tile layer disappoints on phones; it is not used in v1.

### 5.2 URLs

Paths carry what people share: `/`, `/<region>`, `/<region>/<unit>` (`/europe/lt`, `/north-america/us-ak`). The hash carries map state as today: position, zoom, scenario, basemap, language. Static assets are served with single-page-application not-found handling so every path resolves to `index.html`.

### 5.3 First screen

One card over the satellite map, already flown to the right place:

> 🇱🇹 Lithuania's remotest point is **3.4 km** from anything drivable. #31 of 45 in Europe.

Below it: scenario toggle (A default), "See the ranking", "Locate me". The opening unit is, in order: the path; else the visitor's own unit, when the request's country code (Europe) or country plus ISO 3166-2 region code (North America) matches one; else the winner of the region whose `unit_countries` contains the visitor's country; else Europe's winner. Cloudflare supplies country and region code on every request; for HTML navigations the worker writes them into the page as one `<meta>` tag, never stores them, and never sends them anywhere. The old workers.dev URL redirects to `/europe/lt`.

"Locate me" uses the browser geolocation API on tap (opt-in, browser prompt, coordinates used client-side only to pan the map and read the tile under the marker). Nothing leaves the device.

### 5.4 Ranking

A bottom sheet on mobile, a side panel on desktop: every unit of the current region sorted by scenario A distance, B in small type beside it, flag and localised name, tap to fly to that pole. Russia absent. Microstates at the bottom. No cross-region ranking.

### 5.5 Map

- Explore layer on by default: the scenario's PMTiles archive as coloured bands (same palette family as the LT demo), `maxNativeZoom` 9, overzoomed above that. Tap or hover anywhere: the readout decodes the tile pixel under the point into "about X km" using the class table. Edge-masked pixels read "no data: edge of map data"; water reads nothing.
- Near a pole, at zoom 12 and above, the unit's 50 m detail raster for that pole overlays the continental layer.
- Each pole shows distance (exact, two decimals), nearest road (type and name), nearest settlement, coordinates, and an "open in Google Maps" link.
- Basemaps: Esri World Imagery default, OpenStreetMap one tap away, as today. Attribution: OSM contributors (ODbL) for data, Esri for imagery, the site's own published data under ODbL.

### 5.6 Languages

English default, Lithuanian when the browser prefers it; hash and localStorage override as today. Country and region names come from `Intl.DisplayNames` in the active language; only UI strings live in the I18N dictionary. Adding a language later is one dictionary.

### 5.7 About, version, analytics

- About section: definitions of A and B, the physical-not-legal rule, the track-mapping caveat and why A is the headline, contested borders as mapped in OSM, the data-edge mask, accuracy tiers, snapshot date, and licences.
- `/version.json` written by CI at deploy with the commit SHA and build time. The deploy workflow's verify job compares it with the pushed commit, closing the "CI proves content, not freshness" gap.
- Analytics: the same edge logger pattern, a new Analytics Engine dataset, one data point per HTML navigation. Blobs: country, colo, referrer host (www-stripped), browser family, OS family, hostname, landing region, landing unit. No IPs, no raw user agents, no identifiers. The dataset name is chosen with the site name.

### 5.8 Performance budget

First screen under 250 KB compressed (HTML, CSS, JS, Leaflet, pmtiles adapter, `regions.json`, `units.json` for one region) plus a handful of tiles. The verify job fails the deploy if the budget is exceeded.

### 5.9 Visual check

Rendered screenshots via the existing Playwright routine are the UI test suite. Desktop and mobile reference screenshots are kept in the repo and compared per change. The preview worker (5.10) lets the owner open the branch on a real phone at any time.

### 5.10 Deployment

- `main` deploys the live site, as today, via `deploy-cloudflare.yml` on pushes touching `site/**`, `worker.js`, or `wrangler.jsonc`.
- The `europe` branch deploys a **preview worker** (`<name>-preview`, wrangler environment `preview`) via the same workflow, reading data from the R2 dev hostname.
- The worker serves static assets, injects the visitor-country meta tag and logs the analytics point for HTML navigations (`run_worker_first` on `/` and `/<region>*` paths without file extensions), and nothing else.

## 6. Validation

Pipeline stage 6. Any failure blocks publishing. Results are written to `validation/report.json` (machine-readable, one entry per check per unit), `report.html`, and `contact-sheet.html`, and uploaded with the snapshot.

1. **Independent re-check of every published pole** by a second code path that shares nothing with the first: geodesic distance on the WGS84 ellipsoid (pyproj `Geod`) to road vertices densified at 1 m, no raster, no projection, against every way of the scenario within twice the claimed distance, drawn from the full regional highways file so cross-border roads are present by construction. Tolerance 0.5%.
2. **On land, in its unit, not in water**: point-in-polygon against the unit polygon, the land polygons, and the water polygons.
3. **Data-edge bound**: distance from the pole to the extract edge polygon must exceed the claimed distance. A failing unit is flagged and not published; the report names it.
4. **Grid-shift sensitivity**: the coarse grid is computed a second time with a half-cell offset in both axes (minutes, tiled), and stage 5 re-run for each unit's full `top_n` against it. The check passes when the winner's distance changes by no more than `max(1%, 10 m)`; a winner that moves far while its distance agrees within that tolerance is a plateau tie, recorded and non-blocking. A distance outside the tolerance is an artifact and the unit fails. (The original rule, "moves more than 500 m or changes by more than 1%", failed on plateaus and on microstates where 1% is a metre; see DECISIONS 2026-08-22.)
5. **Hole detection**: for every top-3 candidate, compare road density in the 0-10 km ring against the 10-30 km ring. An empty inner ring with a dense outer ring (ratio threshold set in config, default outer density above the unit median and inner zero) is flagged as a probable import gap for human review; it does not block on its own but appears on the contact sheet with a warning.
6. **Reference values**: the Europe run must reproduce Lithuania's published poles (A 3.43 km at Žuvintas, B 6.67 km in Čepkeliai) within 1% and 500 m. Three to five externally cited national poles, with sources, are compared in the report with their definitional differences noted; they inform, they do not block.
7. **Invariants**: A ≤ B at every published pole and every grid cell; every unit has `top_n` poles or a documented reason; poles within a unit are at least 10 km apart; the unit count equals the region config's expectation; the class table is monotonic; every object the manifest references answers a HEAD request on R2 after upload; published JSON validates against its schema.
8. **Contact sheet**: one satellite thumbnail per unit's winner per scenario, with the number, the nearest road, and any warnings from checks 5 and 6. A human reviews it in the pull request before the manifest is merged. This is the one human step in the flow; it cannot be forgotten because the PR is the reminder.

## 7. Update cadence

- **v1 is a dated snapshot.** The site shows "OSM as of <date>" and the pipeline reproduces it from the snapshot identity. Poles move over years, not weeks.
- **Automated refresh is a later stage, designed now, switched on later.** A scheduled GitHub Actions workflow provisions a Hetzner Cloud server via its API from a secret token, runs the container for each region, uploads to R2 under the new snapshot key, destroys the server, and opens a pull request that updates `manifest.json` and carries the validation report and a diff against the live snapshot ("11 poles moved more than 500 m, 2 units changed rank, 0 failures"). Publish happens on merge, never automatically. Expected cost under 1 EUR per region per run. Cadence when enabled: yearly.
- On-demand re-runs in the meantime are the same one command on the laptop.

## 8. Naming, domain, and cutover

### 8.1 Naming

The site name is **parked by the owner** and decided before the cutover stage starts; the owner wants help picking it. Requirements fixed now: English-first, language-neutral, short, says remoteness. "Atokiausia Lietuva" survives as the Lithuanian-language title of `/europe/lt`. Until then the spec, plan, and code use `<name>` where the name goes, and nothing user-facing is built that would need renaming beyond the I18N dictionary and the worker name.

### 8.2 Domain

Bought at Hostinger (where the owner's domains are). A Worker custom domain and an R2 custom hostname both require the zone's DNS on Cloudflare, so the one-time step after purchase is pointing the nameservers at Cloudflare while the registration stays at Hostinger. Cloudflare zone on the free plan.

### 8.3 Cutover sequence

Ordered so the old URL never returns an error:

1. Domain bought; nameservers to Cloudflare; zone active.
2. R2 bucket gets the `data.<domain>` hostname with CORS for the site origin; the snapshot is uploaded; the manifest points at it.
3. New worker deployed under the new name with the domain attached; `/version.json` and the content checks pass on the live URL.
4. The old worker `atokiausia-lietuva` is replaced by a five-line permanent redirect (301) to `https://<domain>/europe/lt`. The LinkedIn post's link keeps working forever.
5. UptimeRobot: the existing monitor retargeted to the new URL; a second monitor on the redirect URL expecting a 301.
6. Analytics: the new dataset receives traffic; the old one is left to age out.
7. `europe` merged to `main`; `scripts/`, the old `site/data/`, and the LT-only worker code deleted from the tree (history keeps them).
8. Docs: OVERVIEW, DECISIONS, LOG, README, CLAUDE.md and CLAUDE.local.md updated; the vault project page updated per its rules.
9. The owner's LinkedIn post.

## 9. Not included, and why

- **The mobile app.** Real intention, not v1. Everything published is plain files (tile archives, detail rasters, class table, unit JSON) with nothing computed server-side, so offline GPS remoteness later is a client reading the same tiles from local storage. No v1 format choice closes that door.
- **Automated refresh**: designed in section 7, built as a later stage.
- **Russia as a unit**: owner decision; roads and explore coverage only.
- **Cross-region rankings**: Alaska against Lithuania teaches nothing.
- **Place-name search, share-image generation, more than two languages**: cheap later, not needed to launch.
- **The stats viewer page, analytics retention snapshots, extra scenario toggles, marketing follow-ups**: stay parked in `docs/IDEAS.md`.
- **Vector tiles and MapLibre GL**: named fallback only.
- **A finer-than-250 m continental layer**: gigabytes for detail nobody sees at that zoom; revisited with real numbers.
- **Legal-access semantics**: physical drivability only, by design.
- **Mexico, Central America, Canaries, Greenland, overseas territories**: outside the v1 unit lists; Mexico is a config change.

## 10. Stages

Each stage ships independently and has its own acceptance criteria; `docs/EUROPE_PLAN.md` expands them into tasks.

1. **Pipeline foundation**: region config, CLI, container, tests, stages fetch through grid run on Europe on this machine. Done when both Europe grids exist, the tiled transform matches untiled on a sample, runtime and peak memory are recorded in this spec, and a throwaway measurement of tile archive size from the LT grid is recorded.
2. **Poles and validation**: stages poles and validate; Lithuania reproduced within tolerance; contact sheet for all Europe units reviewed by the owner.
3. **Publish**: class table, tiles, PMTiles, detail rasters, R2 upload to the dev hostname, manifest and site JSON written; every manifest reference answers HEAD.
4. **Site**: the new site on the `europe` branch with the preview worker live; first screen, ranking, explore layer with readout, detail overlay, pole card, i18n, About, `/version.json`, performance budget enforced; owner has opened it on a phone.
5. **North America**: region config, boundaries, run, validation, contact sheet reviewed; region switch visible in the site.
6. **Cutover**: section 8, including the name.
7. **Automated refresh** (parked until the owner says go): section 7.
