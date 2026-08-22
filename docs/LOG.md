# Project log

Sparse, dated, append-only. Big events only.

## 2026-08-16/17: Built

Computed both scenarios from a 2026-08-17 OSM snapshot; built the bilingual interactive site (Leaflet, no build step); five UI iterations same weekend.

## 2026-08-17: Launched

Repo made public, deployed to Cloudflare Workers + GitHub Pages (through a GitHub major outage; background retry loops carried the Pages deploy). LinkedIn post ~22:00 EEST.

Headline results: **A: 3.43 km** (Žuvintas bog), **B: 6.67 km** (Čepkeliai interior). Top spots in both scenarios are almost all strict reserves and raised bogs: Čepkeliai, Žuvintas, Kamanos.

## 2026-08-18: Analytics

CF Web Analytics beacon added, then the server-side edge logger (Workers Analytics Engine) after discovering the beacon is blocked by the owner's own browsers. AE enabled on the account; end-to-end verified. First precisely-logged real visitor: an iPhone in Lithuania via the LinkedIn app.

## 2026-08-20: First traffic review; own session

Three-day tally: ~20-25 page opens by other people, ~60% in the launch hour, all referred traffic from LinkedIn, iPhone-in-LinkedIn-app the dominant device. Decayed to ~1 visitor/day. Project moved from the life-hub Claude session to its own `claude-poles` session; CLAUDE.md, CLAUDE.local.md, and docs/ written as the durable memory.

## 2026-08-20: Project scaffolding, and the demo declared disposable

Second session of the day. Decided the LT-only site is a demo to plan away from, not a foundation. Built the scaffolding the Europe build will need: CI deploys to Cloudflare on push with post-deploy verification (manual `wrangler deploy` demoted to fallback), GitHub Issues adopted as the task tracker, dependabot, pinned `requirements.txt`, expanded CLAUDE.md working rules, `docs/OVERVIEW.md` as the re-orientation doc, and `/ship` plus `/session-close` skills.

Three things were removed rather than added: the GitHub Pages mirror (a second URL nobody opened), its uptime monitor, and the CF Web Analytics beacon (redundant once the mirror went). The repo went private in the same pass, since Pages was the only thing requiring it to be public. External uptime monitoring now covers the one live URL. Session ended with the Europe kickoff brief written to `docs/EUROPE_KICKOFF.md`.

## 2026-08-20: Europe planned

Third session of the day, the first in the dedicated `claude-poles` session with the superpowers brainstorming path. Fetched the real numbers first (32 GB Europe extract ending at the Volga, Cloudflare's 20,000-file and 25 MiB asset caps, R2's 10 GB free tier), then settled the load-bearing calls: poles plus a continental explore layer as the hero, countries' main territories as units, Russia as roads only, scenario A as the headline, a dated snapshot with refresh parked, Europe first with North America straight after on a region-agnostic pipeline, R2 for the archives with publishing as a manifest commit. Spec (`docs/EUROPE_SPEC.md`) and staged plan (`docs/EUROPE_PLAN.md`) written and approved; epic #6 with stage issues #7 to #13 filed. No code written, by design.

## 2026-08-21: Stage 1 of Europe done, first continental grids computed

Pipeline foundation built on branch `europe` in one long session (spec to code to real data): the `poles` package with config, resumable CLI, fetch, extract, classify, grid, container and CI, 97 tests. Europe (snapshot 2026-08-19) computed through the grid stage on the Mac in about 1.5 hours, not the 4-5 planned. Two tool limits found on the real data and designed around (GDAL's GeoJSONSeq reader memory, a FlatGeobuf index limit near 100 M features); two stage-2 issues filed (#15, #16). Stages now proceed without waiting for owner review between them.

## 2026-08-22: Stage 2 of Europe done, 918 poles found and validated

The `poles` and `validate` stages landed on branch `europe` with 234 tests. Three Europe runs on the 2026-08-19 snapshot: the first two aborted on Bjornoya and Rockall, which taught the territory mask that sub-cell rocks far offshore are candidate cells too; run 3 passed every blocking check with 0 failures, 52 country units, 918 poles with nearest road and settlement, and Lithuania reproduced from the continental grid within 0.02 % of the published demo. The contact sheet and the offshore-rock question went to the owner on #8; nine poles are excluded by the data-edge check and stage 3 consumes that list.

## 2026-08-22: Stage 3 of Europe, local part done

Stage 3 built everything the site will read and stopped at the one human step. The Europe snapshot now has its explore layer as two PMTiles archives (`A.pmtiles` 114.2 MB, `B.pmtiles` 128.3 MB, z0 to z9, one class byte per pixel) and 909 detail rasters at 50 m with their georeference sidecars (13.6 MB), which is 268.6 MB per snapshot in R2 once the three validation artefacts are counted. Nothing has been uploaded: R2 is not enabled on the Cloudflare account, so the run stopped as designed with the five environment variables named, and the upload, the HEAD verification and the `site/data` commit follow the owner's R2 enablement as a rerun of the same command.
