# Self-hosted fonts

No request goes to Google Fonts at runtime: these files are served from the site's own origin. The `@font-face` rules live at the top of `css/app.css`, one per face and subset, with the same `unicode-range` Google uses, so a browser fetches the latin-ext file only when a character from that range is on screen (Lithuanian letters, OSM place names).

| Family | Faces | Files | Licence |
|---|---|---|---|
| Libre Caslon Text | 400, 400 italic | `libre-caslon-text-{400,400-italic}-{latin,latin-ext}.woff2` | SIL OFL 1.1 |
| Libre Franklin | 400 to 600 (one variable file per subset, wght axis 100 to 900) | `libre-franklin-var-{latin,latin-ext}.woff2` | SIL OFL 1.1 |

Source: the woff2 files Google Fonts serves for `https://fonts.googleapis.com/css2?family=Libre+Caslon+Text:ital,wght@0,400;0,700;1,400&family=Libre+Franklin:wght@400;600&display=swap` to a current Chrome User-Agent (Libre Caslon Text v5, Libre Franklin v20), downloaded 2026-09-29. Only the latin and latin-ext subsets are kept; every latin-ext file covers ą č ę ė į š ų ū ž and their capitals.

Licence: `OFL.txt` (both families are under the SIL Open Font License 1.1). Upstream: https://github.com/thundernixon/Libre-Caslon and https://github.com/googlefonts/Libre-Franklin.

The 700 weight of Libre Caslon Text was dropped on 2026-09-29 for the first-screen budget; the titles it set are regular roman caps now.
