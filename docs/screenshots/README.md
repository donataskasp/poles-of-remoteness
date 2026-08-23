# Screenshots

The UI test suite. Regenerate with `node dev/screenshots.mjs` from the repo root (see `dev/README.md` for
the Playwright setup); the script serves `site/` against the local run of record, stubs the basemap tiles
with a flat grey tile so the images are deterministic, and writes this set:

| File | Viewport | View |
|---|---|---|
| desktop-lt.png | 1440x900 | /europe/lt, scenario A, English |
| desktop-lt-lang-lt.png | 1440x900 | same, Lithuanian |
| desktop-lt-b.png | 1440x900 | scenario B |
| desktop-continent.png | 1440x900 | zoomed out to the continent (explore layer only) |
| desktop-detail.png | 1440x900 | zoom 13 on pole 1 with the detail overlay and a readout |
| desktop-about.png | 1440x900 | the About dialog |
| phone-lt.png | 390x844 | /europe/lt, sheet collapsed |
| phone-lt-lang-lt.png | 390x844 | same, Lithuanian |
| phone-ranking.png | 390x844 | sheet at half height |
| phone-about.png | 390x844 | the About dialog, Lithuanian |

Rule: a change that touches only phone styles must leave every `desktop-*.png` byte-identical
(`shasum -a 256 docs/screenshots/desktop-*.png` before and after). A UI change is not done until the
affected images are regenerated, read, and committed with the code.

The desktop six are byte-identical run to run, so the rule is a hash comparison. The phone shots are not
quite: a marker's antialiased border can move by up to 5 of 255 on about fifteen pixels between runs
(measured over five runs of the full set, `phone-lt.png` and `phone-lt-lang-lt.png`), which is Chromium
rendering noise and not a state difference. Compare those by eye, or by a diff that tolerates a few
low-amplitude pixels.

The grey where the map should be is the stubbed basemap: the site's own layers (the coloured explore
classes, the detail overlay, the numbered markers) are the real thing, drawn from the local publish
directory, and nothing in the set depends on Esri or OpenStreetMap being reachable.
