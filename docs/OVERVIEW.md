# Overview: what works, what is not done

The re-orientation doc for sessions weeks apart. Read after CLAUDE.md, before touching anything. Update immediately when a feature lands or status changes, not at session end.

## Status (2026-08-20)

The LT-only site is a finished quick demo, live at the Cloudflare URL. Owner decision 2026-08-20: **it is disposable**. The Europe-wide version will be planned from scratch (superpowers brainstorming session) and may change or replace any part of the current code, data format, or serving setup. Do not build around the demo's structure.

**NEXT-UP**: Europe build planning session via the superpowers alias. Scaffolding (CI, issues, docs) is in place; the kickoff prompt comes from the owner.

## What works

- LT map with scenarios A and B, computed on a 50 m grid from a 2026-08-17 OSM snapshot; spots and distance bands published in `site/data/` (~5 MB)
- Compute pipeline `scripts/01..06` (download -> prepare -> compute -> report -> webdata -> sitedata); heavy inputs gitignored and regenerable
- Site: lt/en i18n, URL-hash state, satellite default basemap, mobile bottom pill, dark variant
- Analytics: edge logger to Workers Analytics Engine (ground truth since 2026-08-18), plus raw asset request counts for volume. The CF Web Analytics beacon was removed 2026-08-20 as redundant once the mirror was gone.
- Deploys: Cloudflare Worker via CI on push (since 2026-08-20, `deploy-cloudflare.yml`) with a post-deploy verify job. Cloudflare is the only target; the GitHub Pages mirror was removed 2026-08-20.
- Monitoring: UptimeRobot checks the live URL every 5 minutes with email alerts (since 2026-08-20)
- Launched 2026-08-17 via LinkedIn post

## Not done yet / parked (build only on owner's go)

- Europe-wide version: NEXT UP, planning first
- Custom domain (deferred until Europe makes the project permanent)
- Country selector, per-country leaderboards
- Stats viewer page for the Analytics Engine data
- Analytics retention snapshots (AE keeps ~3 months; ground truth starts 2026-08-18, first data at risk ~2026-11-18)
- Mobile app exercise (Expo, GPS remoteness compass)

## Known gaps (fold into Europe planning)

- No version stamp on the site, so CI verify jobs prove content is served, not that THIS commit is live; a `/version` route stamped at deploy would fix it
- No automated screenshot check for the desktop-byte-identical rule; it is a manual Playwright routine
