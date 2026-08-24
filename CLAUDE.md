# Poles of remoteness

Interactive map of the places farthest from any drivable road in Europe and North America, computed from OpenStreetMap data. Grew out of the Lithuania-only weekend build kept under `scripts/`.

- Live: https://polesofremoteness.com (Cloudflare Workers, the only deploy target; www and the old `atokiausia-lietuva` workers.dev URL 301 here)

Orient first: read docs/OVERVIEW.md (what works, what is not done, where things are), then docs/diagrams/README.md (how the pieces connect), then docs/DECISIONS.md only when a past choice needs context.

## Scenarios

- **A**: distance to any drivable way, forest tracks included
- **B**: distance to public roads only, tracks excluded

## Layout

- `pipeline/`: the region-agnostic compute pipeline (`poles` CLI, see `pipeline/README.md`). Work data under `work/` is gitignored and regenerable from the snapshot identity.
- `scripts/`: the original Lithuania-only build with its own README; kept for the story, not developed.
- `site/`: the deployed website. Plain HTML/CSS/JS, no build step, no framework. Vendored Leaflet 1.9.4. `site/data/` holds the published results and MUST stay in git (the root `.gitignore` entry is `/data/`, root-anchored on purpose).
- `worker.js` + `wrangler.jsonc`: production worker `polesofremoteness` on the domain (www answers a 301 to the apex): serves `site/` as static assets and logs one privacy-clean view per page to Workers Analytics Engine (dataset `poles_views`, blob order documented in the file). No IPs, no raw user agents, no cookies.
- `redirect/`: the old worker name `atokiausia-lietuva`, a permanent redirect to `/europe/lt`; keeps the LinkedIn launch link alive forever.
- `.github/workflows/deploy-cloudflare.yml`: pushes touching `site/**`, `worker.js`, `wrangler.jsonc`, `redirect/**` or the workflow deploy production plus the redirect worker from main and the preview worker from any other branch, then verify the live URL.

## Site conventions

- All text goes through the I18N dict (lt + en) in `js/app.js`; browser language picks the default, hash/localStorage override.
- URL hash carries state (scenario, spot, position, basemap, lang); satellite is the default basemap.
- Design tokens in `:root` with a `prefers-color-scheme` dark variant.
- Mobile (<=720px) shows the readout as a bottom-anchored pill; desktop layout must not change when touching mobile styles (verify with byte-identical screenshots).

## Working rules

- **Push back when something seems wrong, risky, or suboptimal**, even if the owner sounds confident. Explore the option space, then end on one clear recommendation. Repeated questions are a request for rigour, not a cue to cave.
- **Tasks live in GitHub Issues** (donataskasp/poles-of-remoteness). One issue per task with acceptance criteria ("what does done look like"). Label `in-progress` when starting work, remove the label and close with a comment when finishing. Search the board before filing so you do not duplicate. Risks, gaps, and improvement ideas spotted mid-task get captured as issues immediately, not just mentioned in conversation.
- **Delegate discrete hands-on work to subagents** when it preserves main-thread context for orchestration; always review a subagent's diff before committing. Small fixes inline are fine.
- **Git**: commit after every working change with small descriptive messages; stage explicit paths, never `git add -A`. This repo has a local identity override (Donatas / gmail); the global identity is the work one. Verify the author on the first commit of a session.

## Deploying

- **CI deploys on push** (`deploy-cloudflare.yml`): main deploys production and then the redirect worker, other branches deploy the preview; paths `site/**`, `worker.js`, `wrangler.jsonc`, `redirect/**`, the workflow. The verify job polls `version.json` until it carries the pushed commit. Needs repo secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`. Manual fallback: `npx --yes wrangler deploy` from the repo root.
- After pushing anything that deploys, watch the run to conclusion (`gh run watch`); a red verify job is a real outage signal, fix it immediately.
- The edge may serve briefly cached HTML after a deploy; use a cache-buster query param before concluding a deploy failed. New worker versions also take a few seconds to roll out.
- The verify job proves the pushed commit is live via `version.json`; whether a specific change renders right still needs a human or /ship style grep.

## Docs cadence

Each doc has a trigger and a moment. "Same commit" means the doc change travels with the code change that caused it.

| Doc | Trigger | When |
|---|---|---|
| `docs/OVERVIEW.md` | a stage lands, a region is built or published, something starts or stops working | same commit |
| `docs/DECISIONS.md` | a design choice is made, reversed, or deviates from the spec | same commit; a reversal is a new entry, never a deletion |
| `docs/diagrams/` | a stage, artefact, site data source, route, or deploy path changes (the trigger table is in `docs/diagrams/README.md`) | same commit; a stale diagram is worse than none |
| `pipeline/README.md` | a CLI flag, stage, environment variable, or region config key changes | same commit (`pipeline/tests/test_docs_pins.py` enforces stages and keys) |
| `docs/LOG.md` | a big event only: a stage closed, a region live, a domain or rename | at stage close |
| `docs/IDEAS.md` | an idea is parked or picked up | when it happens |
| `README.md` | the published results or the reproduce steps change | at stage close |

At session close: fix only the doc drift this session caused, and verify any number a doc asserts (grid resolution, feature counts, timings, unit counts) by running the count or grep, never by eye.

## What not to do

- Do not add features not asked for; parked roadmap items stay parked until the owner says go.
- Do not refactor working code while fixing a bug.
- Do not hand-edit anything under `site/data/`; published results come from the pipeline in `scripts/`, and data plus the code that produced it are committed together.
- Do not skip the visual check on UI changes; a rendered screenshot is the test suite here.

## Hard rules

- No em dashes anywhere: site copy, docs, commit messages.
- No secrets in this repo, ever (public since 2026-08-24, and history is forever). Operational notes with local paths live in `CLAUDE.local.md`, which is gitignored. Never commit `.claude/` or `CLAUDE.local.md`.
- Keep the no-build-step property; do not introduce bundlers or frameworks.
- Never commit with the work identity; never `git push --force` to main.

## Europe and North America build (approved 2026-08-20, cut over 2026-08-24)

- Spec `docs/EUROPE_SPEC.md`, staged plan `docs/EUROPE_PLAN.md`, kickoff brief `docs/EUROPE_KICKOFF.md`; epic #6 with stage issues #7 to #13. Stages 1 to 6 are done; `europe` merged to `main` at the cutover and `main` is the working branch again. Stage 7 (automated refresh, #13) stays parked.
- Each remaining task: label its issue `in-progress`, plan first, then implement.
- Region configs are the only place a region is described; nothing in code names Europe.
- Stage status lives in `docs/OVERVIEW.md` (stage 1 done 2026-08-21). Stages proceed one after another without waiting for the owner's review between them (owner decision 2026-08-21); stop only at the genuinely human steps: picking the name, buying the domain, pointing nameservers, and anything irreversible on the live site. Owner-review items such as the contact sheet are posted to the stage issue and flagged, not blocked on.

## Roadmap (parked, build only on owner's go)

- Self-serve stats viewer page for the Analytics Engine data
- Analytics retention snapshots (AE keeps ~3 months)
- Mobile app exercise (Expo, GPS remoteness compass, offline; no backend)

## Docs

- `docs/OVERVIEW.md`: what works, what is not done, where things are; read first
- `docs/diagrams/README.md`: index of the Mermaid diagrams (the pipeline, the site's data flow, deploys and hosting), who each one is for, and the trigger table saying what to update when the code moves
- `docs/EUROPE_SPEC.md` and `docs/EUROPE_PLAN.md`: the approved design and staged plan for the Europe build; `docs/EUROPE_KICKOFF.md` is the brief that produced them
- `docs/DECISIONS.md`: dated decision log with rationale; append, don't relitigate
- `docs/IDEAS.md`: parked plans (app, stats viewer, extra scenarios); build only on owner's go
- `docs/LOG.md`: sparse project log of big events
