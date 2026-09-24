# Shared brief for every design option

You are building ONE redesign option of polesofremoteness.com as a fully working prototype. The owner will compare 8 options in the morning and pick one. Your option must be a real, clickable site on real data, not a picture, and committed all the way to its visual world. A safe, halfway rendition is the failure mode.

## Read first

- `PRODUCT.md` (repo root): product truth. Everything listed under "Core content and function" must still exist and work.
- The incumbent site: `site/index.html`, `site/css/app.css`, `site/js/*.js`. The current look is evidence of what the product is, NOT a style to keep. Screenshots of it: `design/shots/00-current/*.png` (open them).
- Craft floor, the quality bar and bans: `/Users/donatas.kasparavicius/personal/.claude-poles/skills/impeccable/reference/craft-floor.md`. Read it before writing CSS.

## Your sandbox

- Work ONLY inside your option directory `design/options/<NN-slug>/` (a full copy of `site/` minus `site/data/`). Never edit `site/`, `dev/`, `pipeline/`, other options, or anything else. No git commands that write (no add, commit, checkout, stash).
- Data: the server serves the real published data from `site/data/` and the rasters from https://data.polesofremoteness.com, so both regions work.
- Serve for manual poking: `node dev/serve.mjs --site design/options/<NN-slug> --data site/data --port <your port>` (run it in the background, kill it when done).
- Screenshots: `node design/tools/shoot.mjs --site design/options/<NN-slug> --out design/shots/<NN-slug> --port <your port>` writes 7 views (desktop LT light and dark, continent, detail zoom 13 with a tap readout, About dialog, phone, phone sheet open). Playwright is already installed (the script finds it). `--only a,b` limits views. Always run from the repo root `/Users/donatas.kasparavicius/Personal/pole-of-remoteness` with absolute paths if in doubt. Use ONLY your assigned port.
- Budget: build fully, then ONE full screenshot round, fix everything it shows in one batch, then at most ONE more round. Then stop. Open every PNG you write and look at it critically before claiming anything.

## What you may change

- `index.html`, `css/app.css` (rewrite it freely), and the JS render templates (`js/card.js`, `js/ranking.js`, `js/markers.js`, `js/app.js`, `js/map.js`, `js/readout.js`, `js/palette.js`) when the world needs a different structure. Keep behaviour: every control, the URL hash state, both regions, both languages, the phone bottom sheet (it can look completely different, but on <=720px the map must stay the main thing and the card must stay reachable), the About dialog, attribution text.
- Keep every element id and data attribute the JS depends on, or update the JS consistently.
- The remoteness layer colours come from CSS tokens `--band-1..6`, `--edge`, `--band-alpha` (read by `js/palette.js`), so recolouring the data is a CSS change. The satellite basemap tiles carry class `basemap` (Leaflet tile layer className), so a CSS `filter` on `.basemap` can restyle the imagery (for example desaturate or tint it) if your world needs it; satellite stays the default basemap unless your brief says otherwise.
- New UI strings: add them to `js/i18n.js` in BOTH `en` and `lt` (write natural Lithuanian). No em dashes anywhere (hard rule).
- Fonts: you may load faces from Google Fonts with a `<link>` in `index.html` for this mock (note in your notes which faces and weights, and their rough weight in KB; the production site has a 256 KB first-screen budget and would self-host). Avoid these reflex faces unless the brief names one: Fraunces, Playfair Display, Cormorant, Lora, Crimson, Newsreader, Syne, Space Grotesk, Space Mono, IBM Plex, Inter as display, DM Sans, DM Serif, Outfit, Plus Jakarta Sans, Instrument Sans. Choose faces like objects from your world.
- Icons: authored inline SVG in one consistent stroke, never emoji or unicode glyphs standing in for icons (the country flag emoji in the card and ranking are content and may stay or go as your world decides).

## Must hold

- Light and dark scheme both designed (`prefers-color-scheme`), unless your brief explicitly says the world is single-scheme; then say so in the notes as a trade.
- Phone 390x844 and desktop 1440x900 both composed, no horizontal scroll, text readable (contrast 4.5:1 body).
- Browser surfaces themed: selection colour, focus rings, scrollbars in the ranking, tabular numerals.
- No gradient text, no decorative glass, no eyebrow/kicker labels above headings, no hard offset shadows, no coloured thick side borders on cards.
- Voice: plain, precise, dry. Do not rewrite factual copy (headline sentence, About text) except where your world genuinely needs a label; never add claims.

## Deliver

1. The working option in `design/options/<NN-slug>/`.
2. Final screenshots in `design/shots/<NN-slug>/` (all 7 views, final state).
3. `design/briefs/<NN-slug>-notes.md`: 10 to 25 lines. The one-sentence thesis; what a visitor sees first; the signature detail; fonts and colours chosen; files changed and whether JS changed; any product change implied (new default basemap, dark-only, removed or moved controls); honest risks; what it would take to ship (self-hosting fonts, tests that would need updating in `dev/tests`).
4. Run the detector once at the end: `/Users/donatas.kasparavicius/personal/.claude-poles/skills/impeccable/scripts/impeccable detect --json design/options/<NN-slug>/index.html design/options/<NN-slug>/css/app.css` and fix what is mechanical; list anything left in the notes.

Your final reply to the orchestrator: the notes file content plus any problem you could not solve. Keep it under 400 words.
