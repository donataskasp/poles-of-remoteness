# Europe build: kickoff brief

The prompt used to open the Europe planning session (superpowers alias, 2026-08-20). Kept so the framing survives a restart and so later sessions can see what was asked for.

---

Read `CLAUDE.md`, `docs/OVERVIEW.md`, `docs/DECISIONS.md`, and `docs/IDEAS.md` before you respond to anything.

I want to plan the Europe-wide version of this project. This is architectural work: a new subsystem, new data scale, probably a new serving model. Use the brainstorming skill on its full architectural path (questions, approaches, sectioned design, written spec) and then writing-plans. Do not write implementation code in this session. I want to end with a spec and a plan I have approved, not with code.

## What exists today, and how much of it is sacred

None of it. The Lithuania-only site is a weekend demo. It works and it is live, but it was built fast to see if the idea was interesting, and it was. Every part of it (the compute pipeline in `scripts/`, the published data format in `site/data/`, the Leaflet frontend, the worker) can be redesigned, replaced, or deleted. Do not preserve any of it for compatibility, and do not treat the current file layout as the shape the Europe version should take. If the right answer is a clean rebuild, say so.

The one thing I do care about: the LT site stays live and working while the Europe version is built. Plan the cutover deliberately rather than breaking the live map halfway through.

## The goal

Extend "the point farthest from any drivable road" from Lithuania to Europe, and keep the result a static, free-to-host, fast-on-mobile website. The interesting output is not just one continental winner: it is every country's pole, comparisons between them, and the ability to explore the map.

## Constraints, and how open they are

`docs/DECISIONS.md` records these. They are current positions, not laws. Almost all of them were decided for a weekend demo serving 5 MB of data about one small country, and some will not survive Europe scale. Question them. What I do not want is a silent workaround: if a constraint should go, name it and argue it, and I will decide.

The two I would defend hardest, because they are about what the project IS rather than how it was convenient to build:

- **Privacy by design**: no cookies, no IPs, no client-side analytics, nothing that needs a consent banner.
- **I run nothing by hand.** If a step needs a human to remember it, it will not happen. Automate it or design it away.

The rest earned their place at demo scale and should be re-examined honestly:

- Static files only, no build step, no bundler, no framework, dependencies vendored. Note that generating a tile pyramid is already a build step in everything but name, so if Europe needs a generation stage, say that plainly rather than pretending a Makefile is not a build system.
- Free hosting tier, no server to babysit, no backend, no database. I would like to keep this, but if the data volume genuinely breaks it, I want the real cost of the alternative rather than a contorted design that technically fits.
- Source stays private, the site is the public artifact.
- No em dashes anywhere, including commit messages. Not negotiable, but it is only a style rule.

## Open questions the design has to answer

Do not treat this as a checklist to fill in mechanically. It is what I currently think is unresolved. Add what I have missed, and tell me which of these are actually the load-bearing decisions.

1. **Scope, and whether "Europe" is even the right first target.** Where does Europe end (Turkey, Caucasus, Russia west of the Urals, Iceland, the islands)? Does the answer change data volume enough to matter?

2. **The USA question, which I want you to take seriously rather than defer.** The United States is probably where most of the eventual audience is, and it has genuinely spectacular remoteness, so there is a real argument for building it into v1 rather than treating it as a sequel. My instinct: make the pipeline region-agnostic from day one, ship Europe first, then add North America as a data run rather than a rewrite. Adding a region later is cheap if regions are a parameter and brutally expensive if the architecture assumed one continent. Specifically, the parked design assumes EPSG:3035, which is Europe-only by construction, so a continental CRS strategy that generalises is a v1 decision even if US data is a v2 delivery.

   There is also a product problem worth solving early: Alaska. Remoteness there is on a different scale entirely (plausibly hundreds of kilometres from a road, against 3.4 km for Lithuania's winner). One global leaderboard would be permanently won by Alaska and would make every European entry look trivial, which argues for per-country and per-region framing rather than a single headline number. Tell me whether you agree, and whether the honest recommendation is Europe-first-but-portable, both at once, or something else. Include what North America does to the compute budget, the storage bill, and the timeline.

3. **Definition consistency across borders.** Roads outside the extract still count, tagging conventions differ by country, and some places map forest tracks obsessively while others do not. What does "drivable" mean continent-wide, and how much does scenario A vs B survive the move?
4. **Coastlines, islands, and water.** The LT version subtracted sea and large lakes. At continental scale this is a much bigger problem, and islands may produce trivially "remote" winners that are not interesting.
5. **Compute strategy.** The parked idea is a 250 m continental pass in EPSG:3035 then local UTM refinement. Is that right? What is the actual runtime and peak memory, and does it fit a 24 GB M-series MacBook or does it need a rented box? If rented, what does one full run cost?
6. **Data volume and serving.** LT publishes about 5 MB. Europe will not. PMTiles with HTTP range requests is the parked plan. Verify it against real numbers, and check what Cloudflare's free tier actually allows for asset size and count, since a plan that does not fit the free tier breaks a core constraint.
7. **Where the data lives.** Published results currently sit in git. That does not survive a jump to gigabytes. Git LFS, R2, or something else, and what that does to reproducibility and to the private-repo decision.
8. **Validation.** The LT version had explicit verification steps (winner on land, exact re-check, cross-border roads present). At continental scale, how do I know a computed pole is actually correct rather than a projection artifact or a hole in the data? This one matters more than it looks: a wrong headline number is the failure mode that would embarrass the project publicly.
9. **Update cadence.** OSM changes constantly. Is this a one-shot snapshot, or does it re-run? If it re-runs, that is an automation design, not a manual chore.
10. **The product.** Country selector and per-country leaderboards are parked ideas. What is the actual hero experience for someone arriving from a link on their phone?
11. **Naming and URLs.** "Atokiausia Lietuva" stops being accurate. See the naming section in `docs/IDEAS.md`: the rename, the custom domain, and the analytics dataset name move together, and the current workers.dev URL is linked from a public LinkedIn post.

## What I want out of this session

1. A written spec committed under `docs/`, covering scope, method, pipeline, serving, UI, validation, and update cadence.
2. An implementation plan split into stages that can each ship independently, each with acceptance criteria.
3. Those stages filed as GitHub issues (an epic plus children, labels `epic` and `in-progress` exist) so the work survives between sessions weeks apart.
4. A dated `docs/DECISIONS.md` entry for every significant call, including the ones where you talked me out of something.
5. An explicit list of what this plan deliberately does NOT include, and why. The mobile app in `docs/IDEAS.md` belongs on that list: it is a real intention, not a fantasy, and its one genuinely app-shaped feature is offline GPS remoteness, which needs the published data to be usable on a device with no signal. It is definitely NOT v1 and I do not want an hour spent building toward it now. What I do want is a sentence in the spec on whether any v1 data-format choice would make it impossible later, so the option stays open for free.

## How I want you to work

- Stop and get my approval before any implementation. That gate is the point of this session.
- Push back. If something I have assumed is wrong, or a parked idea does not survive contact with the numbers, say so early rather than designing around it politely.
- Recommend. Do not hand me a menu of five options and ask me to pick; explore the space, then tell me what you would do and why.
- Where a number settles an argument (file size, runtime, memory, tile count, cost), go get the number. A throwaway spike that measures the real PBF is cheaper than an architecture built on a guess. Label anything throwaway as throwaway.
- Subagents cost real money and I can see the burn rate. Use them where work is genuinely parallel, not as a default.
- Do the build on a branch, not on main. The live site is served from main.
- On tests: I want real tests for the pipeline math, where a wrong number is invisible and would poison published data. I do not want tests for Leaflet wiring or copy, where the honest check is a rendered screenshot. Do not let the TDD skill argue me into the second category.

Start by reading the docs, then ask me your questions.
