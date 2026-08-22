# Vendored libraries

No build step: these files are served as they are and updated by hand.

| Library | Version | File | Licence | Source |
|---|---|---|---|---|
| Leaflet | 1.9.4 | `leaflet/leaflet.js`, `leaflet/leaflet.css`, `leaflet/images/` | BSD-2-Clause | https://github.com/Leaflet/Leaflet/releases/tag/v1.9.4 |
| pmtiles | 4.5.0 | `pmtiles/pmtiles.js` (the `dist/pmtiles.js` IIFE bundle, global `pmtiles`) | BSD-3-Clause | https://www.npmjs.com/package/pmtiles/v/4.5.0 |

pmtiles is used only to fetch tiles by HTTP range request (`new pmtiles.PMTiles(url)`, `getHeader()`, `getZxy(z, x, y)`); a Leaflet `GridLayer` in `js/explore.js` paints them. Same origin is not required: R2 answers with CORS.
