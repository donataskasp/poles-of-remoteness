# Product

<!-- impeccable:product-schema 1 -->

Inferred from the repository on 2026-09-24 (docs/OVERVIEW.md, docs/EUROPE_SPEC.md, the site, the owner's standing rules); the owner was not available to confirm. Every line below is repo evidence, not an interview answer.

## Platform

web

## Stack

Plain HTML, CSS and ES modules under `site/`, no build step and no framework (a hard rule). Vendored Leaflet 1.9.4 and pmtiles 4.5.0. Served as static assets by a Cloudflare Worker on polesofremoteness.com; data JSON in `site/data/`, raster archives and detail rasters on R2.

## Purpose

An interactive map of the place in every country (Europe) and every state, province and territory (North America) that lies farthest from any drivable road: its pole of remoteness. Computed from OpenStreetMap by the pipeline in this repo. A pure-interest hobby project; no monetisation, no growth features.

## Users and scene

- Curious general visitors arriving from a LinkedIn post or a shared link, mostly on phones, spending a minute or two: "how far from a road can you get in my country, and where is it?"
- Outdoor and map people who dig into a specific pole: coordinates, nearest road, nearest settlement, the satellite view around it.
- Owner, 2026-09-24: both audiences weigh equally; the satellite basemap stays the default (tinting it is fine).
- Landing is on the visitor's own country (coarse geolocation from the edge), so the first screen is personal.

## Core content and function (must survive any redesign)

- The map is the product: satellite basemap by default (street map alternative), the coloured remoteness layer in six distance bands (1, 2.5, 5, 10, 20, 50 km), numbered pole markers, a 50 m detail overlay from zoom 12, tap-to-read the distance anywhere.
- The card: headline sentence ("Lithuania: the remotest point is 3.43 km from anything drivable."), rank in the region, the scenario switch (A: any drivable way, tracks included; B: public roads only), the islands toggle, "See the ranking", "Locate me", the ten poles with distance, island area, nearest road, nearest settlement, coordinates and a Google Maps link.
- The ranking of every unit in the region by the active scenario, the other scenario in small type.
- Region switch (Europe, North America), language switch (EN, LT), the About dialog (method, what counts as a road, caveats, accuracy, licence), OSM and imagery attribution.
- URL state: `/<region>/<unit>` path, the rest in the hash (scenario, pole, position, basemap, islands, language).

## Constraints

- Every string in both English and Lithuanian through the I18N dictionary.
- Light and dark schemes.
- Phone (<=720px): the map fills the screen, the card and ranking live in a bottom sheet.
- First screen under a 256 KB budget (CI measures it).
- No em dashes in any copy. No cookies, no tracking beyond a privacy-clean view count.

## Voice

Plain, precise, a little dry; numbers stated exactly with their caveats. Never hype.
