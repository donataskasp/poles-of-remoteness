# Decision log

Dated, append-only. Newest at the bottom. Each entry: what was decided and why, so future sessions do not relitigate.

## 2026-08-16/17: Computation

- **OSM as the single road source**, snapshot 2026-08-17. Distances are to mapped ways; unmapped private tracks exist in reality. Neighbouring countries' roads count, so border spots are scored honestly.
- **Two scenarios instead of one**: A (any drivable way, tracks included) answers "how far from anything drivable", B (tracks excluded) answers "how far from real roads". Both are legitimate and they crown different poles, which is the interesting finding.
- **25 m coarse pass + 5 m refinement** (EPSG:3346, EDT then exact vector distances; see README). The published web raster is a separate 50 m grid, small enough to ship (site/data ~5 MB).

## 2026-08-17: Site and hosting

- **Plain HTML/CSS/JS, no build step, vendored Leaflet 1.9.4.** Longevity and zero maintenance beat framework comfort for a site this size; any future session can edit it without a toolchain.
- **Cloudflare Workers (static assets) as primary, GitHub Pages as mirror.** Static serving on Workers is free and unlimited; Pages is the redundancy and the CI exercise. Both deploy from the same repo.
- **Public repo under the personal GitHub account** (donataskasp), with a repo-local git identity so work identity never leaks into commits.
- **workers.dev URL lock-in accepted for now.** A custom domain (~10 EUR/yr) is deliberately deferred until the Europe version makes the project permanent.

## 2026-08-17/18: UI (v2-v5)

- Satellite is the **default basemap** (bogs and forests read better); OSM a click away.
- Map controls live in a **floating top-right cluster** (basemap, bands toggle, legend, selected-spot readout); clicking the brand resets the map; language defaults to the browser (lt if the browser says lt, else en), hash and localStorage override.
- **Mobile (<=720px) collapses the readout into a bottom-anchored pill** above the attribution. Rule established: mobile-only changes must leave desktop byte-identical (verify with sha256 screenshots).

## 2026-08-18: Analytics

- **Three layers, each honest about what it sees**: raw asset requests (volume, sees everyone, coarse), CF Web Analytics beacon (referrers/countries but blocked by Brave/uBlock, treat as a sample), and the **edge logger as ground truth**: the worker writes one Analytics Engine data point per GET of `/`.
- **GDPR by design, not by banner**: no IPs, no raw user agents, no cookies, no unique identifiers. Consequence accepted: we count page loads, not unique visitors. Browser/OS stored as coarse families; referrer stored as www-stripped host only.
- **Beacon kept anyway**: costs nothing and is the only signal for the GitHub Pages mirror, which has no server side.
- **Workers Analytics Engine over a VPS or self-hosted analytics**: free tier (100k writes/day) is ~1000x headroom, no server to babysit, and blockers cannot see server-side logging at all.

## 2026-08-20: Project structure

- Split out of the life-hub Claude session into a dedicated `claude-poles` session with isolated config. Knowledge split: CLAUDE.md (public, technical), CLAUDE.local.md (gitignored, operational), docs/ (this folder).

## 2026-08-20: Scaffolding before the Europe build

- **The LT-only site is a demo, not a foundation.** The Europe version gets a from-scratch planning pass (superpowers brainstorming); nothing in the current code, data format, or serving setup is sacred. Decided to plan properly first rather than accrete onto the demo.
- **CI deploys Cloudflare on push** (`deploy-cloudflare.yml`, wrangler-action, secrets in repo settings). Replaces manual `wrangler deploy` as the primary path, killing the "pushed but forgot to deploy the primary" failure mode; manual stays as fallback. Both workflows gained post-deploy verify jobs (content-presence only until a version stamp exists).
- **GitHub Issues adopted as the task tracker** with the keenquote discipline: acceptance criteria, `in-progress` label while a session works an issue, search before filing. Labels created: in-progress, dependencies, ci, epic.
- **Keenquote scaffolding reused where it fits**: dependabot (github-actions ecosystem only, no npm by design), docs/OVERVIEW.md as the re-orientation doc, expanded CLAUDE.md working rules, /ship and /session-close local skills. VPS machinery, marketing skills, and daily-log cadence deliberately not copied.
- **Monitoring: UptimeRobot, not a CI canary.** A scheduled workflow that files an issue on failure was considered and rejected: it checks twice a day instead of every 5 minutes, it cannot self-heal (the realistic failures are Cloudflare being down, which we cannot fix, or a bad deploy, which the deploy workflow's verify job already catches), and a GitHub-hosted canary is a poor judge of the GitHub Pages mirror. Two external monitors instead, one per live URL, 5-minute interval, email alerts. Both URLs are monitored because they fail independently and the mirror is the fallback.

## 2026-08-20: Drop the Pages mirror, repo goes private

- **GitHub Pages mirror removed** (site unpublished, `pages.yml` deleted, monitor deleted). It was built as redundancy plus a CI exercise; the exercise is done and Cloudflare now has real CI with post-deploy verification, so what remained was a second URL nobody used (owner: "nobody has that link, and even I never opened it"). Reverses the 2026-08-17 two-target decision. Cloudflare is now the only deploy target.
- **Repo made private.** The 2026-08-17 public-repo decision was made when the repo held a weekend demo with nothing to protect. The Europe build will carry substantially more work and original thinking, and the product being shared is the map and the app, not the source. Dropping Pages removed the only technical blocker (Pages on a free account requires a public repo; Cloudflare deploys from CI with an API token regardless of visibility).
- Consequence accepted: Actions minutes become metered on a private repo (2000/month free, current usage is a few minutes per deploy). The no-secrets-in-repo rule stays in force regardless of visibility.

## 2026-08-20: Drop the CF Web Analytics beacon

- **Beacon removed from `site/index.html`.** Its one unique value was covering the GitHub Pages mirror, which no longer exists, so it was fully redundant with the edge logger. It also undercounted badly (Brave, uBlock, and AdGuard block it, which made the owner's own visits invisible), while the edge logger records country, referrer, browser family, and OS family server-side where no blocker can interfere. Removing it drops one third-party request from every page load and leaves a single honest analytics source instead of three partial ones. Reverses the 2026-08-18 "beacon kept anyway" decision, whose stated reason was mirror coverage.
