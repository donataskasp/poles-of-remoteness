# Overview: what works, what is not done

The re-orientation doc for sessions weeks apart. Read after CLAUDE.md, before touching anything. Update immediately when a feature lands or status changes, not at session end.

## Status (2026-08-20)

The LT-only site is a finished quick demo, live at the Cloudflare URL, and **disposable** (owner decision 2026-08-20). The Europe version is **planned and approved**: spec `docs/EUROPE_SPEC.md`, staged plan `docs/EUROPE_PLAN.md`, epic #6 with stage issues #7 to #13. Nothing of it is built yet.

**NEXT-UP**: Stage 1 (#7), pipeline foundation, on branch `europe`. Before coding: label #7 `in-progress`, write the step-level plan from `docs/EUROPE_PLAN.md` Stage 1, then start with task 1.1. The first overnight step is the 34 GB Geofabrik download (task 1.3).

## What works

- LT map with scenarios A and B, computed on a 50 m grid from a 2026-08-17 OSM snapshot; spots and distance bands published in `site/data/` (~5 MB)
- Compute pipeline `scripts/01..06` (download -> prepare -> compute -> report -> webdata -> sitedata); heavy inputs gitignored and regenerable
- Site: lt/en i18n, URL-hash state, satellite default basemap, mobile bottom pill, dark variant
- Analytics: edge logger to Workers Analytics Engine (ground truth since 2026-08-18), plus raw asset request counts for volume. The CF Web Analytics beacon was removed 2026-08-20 as redundant once the mirror was gone.
- Deploys: Cloudflare Worker via CI on push (since 2026-08-20, `deploy-cloudflare.yml`) with a post-deploy verify job. Cloudflare is the only target; the GitHub Pages mirror was removed 2026-08-20.
- Monitoring: UptimeRobot checks the live URL every 5 minutes with email alerts (since 2026-08-20)
- Launched 2026-08-17 via LinkedIn post

## Not done yet / parked (build only on owner's go)

- Europe and North America version: planned, see the stage issues. Stage order: pipeline foundation (#7), poles and validation (#8), publish (#9), site on the preview worker (#10), North America (#11), cutover with name and domain (#12), automated refresh (#13, parked).
- Custom domain and the rename: part of the cutover stage (#12); the name is parked until then, owner wants help picking it; domain will be bought at Hostinger.
- Stats viewer page for the Analytics Engine data (parked, unchanged)
- Analytics retention snapshots (AE keeps ~3 months; ground truth starts 2026-08-18, first data at risk ~2026-11-18)
- Mobile app exercise (Expo, GPS remoteness compass): explicitly not v1; the spec keeps the data usable offline later

## Known gaps (addressed by the Europe plan)

- No version stamp on the site, so CI verify jobs prove content is served, not that THIS commit is live; `version.json` lands in stage 4 (#10)
- No automated screenshot check for the desktop-byte-identical rule; stage 4 commits reference screenshots and the routine
