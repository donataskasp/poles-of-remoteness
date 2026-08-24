# Ideas and parked plans

Everything here is **parked**: build only on the owner's explicit go. Captured 2026-08-20 from the founding session so the thinking survives.

## Europe version (the big one)

**Specified and approved 2026-08-20**: `docs/EUROPE_SPEC.md` and `docs/EUROPE_PLAN.md`, epic #6. The sketch below is the pre-planning thinking, kept for history; where it differs from the spec, the spec wins (notably: the coarse projection is a per-region proj string, not EPSG:3035 by construction; settlements ship inside each pole's JSON instead of a sharded lookup; archives live on R2 behind the bucket's own hostname).

The design as first thought through:

- Input: Geofabrik `europe` PBF (~30 GB). Compute runs locally or on a rented box; only outputs get published.
- Pass 1: continental grid at 250 m in EPSG:3035 (ETRS89-LAEA, the EU standard equal-area CRS).
- Pass 2: refine each candidate region 25 m then 5 m in its local UTM zone.
- Coastlines/land from prebuilt OSM land polygons rather than deriving them.
- Serving stays tiny despite huge data: tile pyramid or PMTiles, fetched via HTTP range requests, so the browser only ever downloads the tiles in view. The site remains static files on the free tier.
- Settlement/nearest-place lookup sharded per country.
- Launch together with a **custom domain**; that is the moment URL permanence starts mattering.

## Naming and URLs (decide with the domain, not before; now stage 6, issue #12)

Done 2026-08-24 (stage 6): the rename happened once, as designed. polesofremoteness.com is the primary URL; the worker rename broke no public link because the old workers.dev name lives on as a permanent redirect; the analytics series restarted as `poles_views`; the repo is `poles-of-remoteness`. The considerations that shaped it, kept for the record:

- Worker name in `wrangler.jsonc` is what generates the workers.dev hostname; changing it changes the primary URL and **breaks the LinkedIn launch post link**, which is currently the project's only inbound traffic source. A custom domain absorbs this permanently: point the domain at the worker, and future renames never break a public link again.
- Repo rename is cheap (GitHub redirects the old path) and now touches nothing user-facing, since the repo is private and serves no site.
- The Analytics Engine dataset name (`atokiausia_views`) is the analytics history. Renaming it starts a new series; keeping it under an old name is ugly but preserves continuity. Decide deliberately.
- Site title, i18n strings, README, and the UptimeRobot monitors all follow.

(Resolved 2026-08-20: the Pages mirror was removed and the repo made private, so only the Cloudflare URL and the domain matter for the rename.)

## Site features

- Country selector + per-country pole leaderboard ("every country's most remote point"): **absorbed into the Europe spec as the hero**; no longer parked.
- More scenario toggles were brainstormed in an earlier session (pre-compaction); re-run that brainstorm before the next feature round rather than trusting memory.
- Self-serve stats viewer: a `/stats-<random-suffix>` route on the worker that queries Analytics Engine server-side (read token as a worker secret, never client-side) and renders daily views, countries, referrers, devices. Unguessable URL, works from a phone.
- Analytics retention snapshots: AE keeps ~3 months, so a scheduled job should append daily aggregates to a file in the repo if launch-era history is worth keeping.

## Mobile app (exercise, not product)

Honest premise: little unique value on its own; the point is learning the publish pipeline end to end. The one genuinely app-shaped feature: **offline GPS remoteness**, since the remotest spots by definition have no signal.

- Stack: Expo (one codebase, cloud builds). Bundle the 5 MB grid + offline tiles; read GPS on-device.
- Features, all server-free: live "remoteness compass" (distance and bearing to nearest road), personal record ("deepest ever: X km"), top-poles visit checklist with badges, a buzz when crossing into a deep band.
- Publishing reality check: Google Play $25 once but new personal accounts need a ~12-tester closed test for 14 continuous days before public release; Apple $99/yr, human review, and guideline 4.2 rejects bare website wrappers (the GPS/offline feature is what clears that bar).
- Running costs: zero. Everything on-device; data updates ship via store updates or a static fetch from the existing free hosting. Rule of thumb recorded: features about you and your phone are free forever; features about you and other people need a backend.

## Marketing follow-ups

- The Europe build is a natural second LinkedIn post; the app a third. Launch pattern observed: ~60% of all traffic in the first hour, one-day half-life, so publish when people are online (evening worked).

## Distance to anything (owner idea, 2026-08-20)

Not only "how far from any road" but "how far from any shop, building, bus stop, pub, railway station". The pipeline is already shaped for it: a scenario is a tag filter over OSM objects followed by the same tiled distance transform, so each new layer is one more filter in the extract stage (points work like lines) plus one grid run (about an hour for Europe) and one more tile archive (about 155 MB per layer at 250 m, measured 2026-08-20). The extract stage currently drops everything but roads, borders, settlements, and water, so adding a layer means keeping one more tag class there. Open questions when this is picked up: which features people would actually care about, whether a layer ranks per unit like roads do or is explore-only, and the storage budget on R2 (each layer is another archive per snapshot). Parked until the road version has shipped.
