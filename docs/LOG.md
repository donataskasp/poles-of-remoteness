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
