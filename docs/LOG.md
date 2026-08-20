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
