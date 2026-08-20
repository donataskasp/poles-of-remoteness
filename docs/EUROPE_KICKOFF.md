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

## Constraints that are already decided

These come from `docs/DECISIONS.md` and are not open unless you have a strong, specific reason, in which case argue it explicitly rather than quietly working around it:

- Static files only. No build step, no bundler, no framework, dependencies vendored.
- Free hosting tier, no server to babysit, no backend, no database.
- Privacy by design: no cookies, no IPs, no client-side analytics, nothing that needs a consent banner.
- Source stays private; the site is the public artifact.
- I run nothing by hand. If a step needs a human to remember it, it will not happen. Automate it or design it away.
- No em dashes anywhere, including commit messages.

## Open questions the design has to answer

Do not treat this as a checklist to fill in mechanically. It is what I currently think is unresolved. Add what I have missed, and tell me which of these are actually the load-bearing decisions.

1. **Scope.** All of Europe, or a defined subset? Where does "Europe" end (Turkey, Caucasus, Russia west of the Urals, Iceland, the islands)? Does the answer change the data volume enough to matter?
2. **Definition consistency across borders.** Roads outside the extract still count, tagging conventions differ by country, and some places map forest tracks obsessively while others do not. What does "drivable" mean continent-wide, and how much does scenario A vs B survive the move?
3. **Coastlines, islands, and water.** The LT version subtracted sea and large lakes. At continental scale this is a much bigger problem, and islands may produce trivially "remote" winners that are not interesting.
4. **Compute strategy.** The parked idea is a 250 m continental pass in EPSG:3035 then local UTM refinement. Is that right? What is the actual runtime and peak memory, and does it fit a 24 GB M-series MacBook or does it need a rented box? If rented, what does one full run cost?
5. **Data volume and serving.** LT publishes about 5 MB. Europe will not. PMTiles with HTTP range requests is the parked plan. Verify it against real numbers, and check what Cloudflare's free tier actually allows for asset size and count, since a plan that does not fit the free tier breaks a core constraint.
6. **Where the data lives.** Published results currently sit in git. That does not survive a jump to gigabytes. Git LFS, R2, or something else, and what that does to reproducibility and to the private-repo decision.
7. **Validation.** The LT version had explicit verification steps (winner on land, exact re-check, cross-border roads present). At continental scale, how do I know a computed pole is actually correct rather than a projection artifact or a hole in the data? This one matters more than it looks: a wrong headline number is the failure mode that would embarrass the project publicly.
8. **Update cadence.** OSM changes constantly. Is this a one-shot snapshot, or does it re-run? If it re-runs, that is an automation design, not a manual chore.
9. **The product.** Country selector and per-country leaderboards are parked ideas. What is the actual hero experience for someone arriving from a link on their phone?
10. **Naming and URLs.** "Atokiausia Lietuva" stops being accurate. See the naming section in `docs/IDEAS.md`: the rename, the custom domain, and the analytics dataset name move together, and the current workers.dev URL is linked from a public LinkedIn post.

## What I want out of this session

1. A written spec committed under `docs/`, covering scope, method, pipeline, serving, UI, validation, and update cadence.
2. An implementation plan split into stages that can each ship independently, each with acceptance criteria.
3. Those stages filed as GitHub issues (an epic plus children, labels `epic` and `in-progress` exist) so the work survives between sessions weeks apart.
4. A dated `docs/DECISIONS.md` entry for every significant call, including the ones where you talked me out of something.
5. An explicit list of what this plan deliberately does NOT include, and why.

## How I want you to work

- Stop and get my approval before any implementation. That gate is the point of this session.
- Push back. If something I have assumed is wrong, or a parked idea does not survive contact with the numbers, say so early rather than designing around it politely.
- Recommend. Do not hand me a menu of five options and ask me to pick; explore the space, then tell me what you would do and why.
- Where a number settles an argument (file size, runtime, memory, tile count, cost), go get the number. A throwaway spike that measures the real PBF is cheaper than an architecture built on a guess. Label anything throwaway as throwaway.
- Subagents cost real money and I can see the burn rate. Use them where work is genuinely parallel, not as a default.
- Do the build on a branch, not on main. The live site is served from main.
- On tests: I want real tests for the pipeline math, where a wrong number is invisible and would poison published data. I do not want tests for Leaflet wiring or copy, where the honest check is a rendered screenshot. Do not let the TDD skill argue me into the second category.

Start by reading the docs, then ask me your questions.
