# Atokiausia Lietuva: pole of remoteness

Interactive map of the places in Lithuania farthest from any drivable road, computed from OpenStreetMap data on a 50 m grid.

- Live: https://atokiausia-lietuva.donatas-kasparavicius.workers.dev (Cloudflare Workers, the only deploy target)

Orient first: read docs/OVERVIEW.md (what works, what is not done, current status), then docs/DECISIONS.md if a past choice needs context.

## Scenarios

- **A**: distance to any drivable way, forest tracks included
- **B**: distance to public roads only, tracks excluded

## Layout

- `scripts/`: Python compute pipeline (OSM extract -> distance grids -> spots/bands). Heavy inputs and grids are gitignored and regenerable.
- `pipeline/` (branch `europe`): the region-agnostic Europe pipeline (`poles` CLI, see `pipeline/README.md`); replaces `scripts/` at cutover. Work data under `work/` is gitignored and regenerable from the snapshot identity.
- `site/`: the deployed website. Plain HTML/CSS/JS, no build step, no framework. Vendored Leaflet 1.9.4. `site/data/` holds the published results and MUST stay in git (the root `.gitignore` entry is `/data/`, root-anchored on purpose).
- `worker.js` + `wrangler.jsonc`: Cloudflare Worker: serves `site/` as static assets; GET requests to `/` also log one privacy-clean view to Workers Analytics Engine (dataset `atokiausia_views`, blob order documented in the file). No IPs, no raw user agents, no cookies.
- `.github/workflows/deploy-cloudflare.yml`: deploys the Worker on pushes to main touching `site/**`, `worker.js`, or `wrangler.jsonc`, then verifies the live URL.

## Site conventions

- All text goes through the I18N dict (lt + en) in `js/app.js`; browser language picks the default, hash/localStorage override.
- URL hash carries state (scenario, spot, position, basemap, lang); satellite is the default basemap.
- Design tokens in `:root` with a `prefers-color-scheme` dark variant.
- Mobile (<=720px) shows the readout as a bottom-anchored pill; desktop layout must not change when touching mobile styles (verify with byte-identical screenshots).

## Working rules

- **Push back when something seems wrong, risky, or suboptimal**, even if the owner sounds confident. Explore the option space, then end on one clear recommendation. Repeated questions are a request for rigour, not a cue to cave.
- **Tasks live in GitHub Issues** (donataskasp/atokiausia-lietuva). One issue per task with acceptance criteria ("what does done look like"). Label `in-progress` when starting work, remove the label and close with a comment when finishing. Search the board before filing so you do not duplicate. Risks, gaps, and improvement ideas spotted mid-task get captured as issues immediately, not just mentioned in conversation.
- **Delegate discrete hands-on work to subagents** when it preserves main-thread context for orchestration; always review a subagent's diff before committing. Small fixes inline are fine.
- **Git**: commit after every working change with small descriptive messages; stage explicit paths, never `git add -A`. This repo has a local identity override (Donatas / gmail); the global identity is the work one. Verify the author on the first commit of a session.

## Deploying

- **CI deploys on push to main** touching `site/**`, `worker.js`, or `wrangler.jsonc` (`deploy-cloudflare.yml`), then verifies the live URL. Needs repo secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`. Manual fallback: `npx --yes wrangler deploy` from the repo root.
- After pushing anything that deploys, watch the run to conclusion (`gh run watch`); a red verify job is a real outage signal, fix it immediately.
- The workers.dev edge may serve briefly cached HTML after a deploy; use a cache-buster query param before concluding a deploy failed. New worker versions also take a few seconds to roll out.
- The CI verify jobs are content-presence checks only (no version stamp on the site yet); freshness still needs a human or /ship style grep for the specific change.

## Docs cadence

- `docs/OVERVIEW.md`: update immediately when what-works or project status changes; this is the re-orientation doc for sessions weeks apart.
- `docs/DECISIONS.md`: dated decision log with rationale; append immediately when a significant decision lands, never delete; a reversal is a new entry.
- `docs/IDEAS.md`: parked plans; build only on owner's go.
- `docs/LOG.md`: sparse project log of big events only, not a changelog.

## What not to do

- Do not add features not asked for; parked roadmap items stay parked until the owner says go.
- Do not refactor working code while fixing a bug.
- Do not hand-edit anything under `site/data/`; published results come from the pipeline in `scripts/`, and data plus the code that produced it are committed together.
- Do not skip the visual check on UI changes; a rendered screenshot is the test suite here.

## Hard rules

- No em dashes anywhere: site copy, docs, commit messages.
- No secrets in this repo, ever (private since 2026-08-20, but visibility can change and history is forever). Operational notes with local paths live in `CLAUDE.local.md`, which is gitignored. Never commit `.claude/` or `CLAUDE.local.md`.
- Keep the no-build-step property; do not introduce bundlers or frameworks.
- Never commit with the work identity; never `git push --force` to main.

## Europe and North America build (approved 2026-08-20)

- Spec `docs/EUROPE_SPEC.md`, staged plan `docs/EUROPE_PLAN.md`, kickoff brief `docs/EUROPE_KICKOFF.md`; epic #6 with stage issues #7 to #13.
- **Build on branch `europe`, never on `main` before the cutover stage**; `main` keeps serving the live LT site. Each stage: label its issue `in-progress`, write the step-level plan from `docs/EUROPE_PLAN.md` first, then implement.
- Region configs are the only place a region is described; nothing in code names Europe.
- Stage status lives in `docs/OVERVIEW.md` (stage 1 done 2026-08-21). Stages proceed one after another without waiting for the owner's review between them (owner decision 2026-08-21); stop only at the genuinely human steps: picking the name, buying the domain, pointing nameservers, and anything irreversible on the live site. Owner-review items such as the contact sheet are posted to the stage issue and flagged, not blocked on.

## Roadmap (parked, build only on owner's go)

- Custom domain and rename: stage 6 of the Europe plan (#12), name still to be picked
- Self-serve stats viewer page for the Analytics Engine data
- Analytics retention snapshots (AE keeps ~3 months)
- Mobile app exercise (Expo, GPS remoteness compass, offline; no backend)

## Docs

- `docs/OVERVIEW.md`: what works, what is not done, current status; read first
- `docs/EUROPE_SPEC.md` and `docs/EUROPE_PLAN.md`: the approved design and staged plan for the Europe build; `docs/EUROPE_KICKOFF.md` is the brief that produced them
- `docs/DECISIONS.md`: dated decision log with rationale; append, don't relitigate
- `docs/IDEAS.md`: parked plans (app, stats viewer, extra scenarios); build only on owner's go
- `docs/LOG.md`: sparse project log of big events
