# Lithuania's pole of remoteness

Finds the point on Lithuanian land farthest from any drivable road. Roads in
Latvia, Belarus, Poland, and Kaliningrad count too, so a spot near the border
is only as remote as the nearest foreign road. Two definitions:

- **Scenario A** - any drivable way, forest/field tracks included
- **Scenario B** - public-style roads only (`highway=track` excluded)

## Results (OSM snapshot 2026-08-17)

- **A: 3.43 km**, Žuvintas biosphere reserve bog (54.441473, 23.537020).
  Čepkeliai is second at 3.41 km - the mapped border patrol tracks along its
  southern edge cap its score once tracks count.
- **B: 6.67 km**, Čepkelių raistas interior (53.995818, 24.462993).

Full ranking, coordinates, and nearest-road identities: `out/results.md`.

**Live interactive map**: https://atokiausia-lietuva.donatas-kasparavicius.workers.dev
The site itself lives in `site/`; `out/map.html` is the older compute-time
preview.

## Reproduce

```
scripts/01_download.sh   # ~860 MB from Geofabrik (LT, LV, BY, 2 PL voivodeships, Kaliningrad)
scripts/02_prepare.sh    # osmium: clip to LT+20 km, filter highway=*, export layers
.venv/bin/python scripts/03_compute.py   # both scenarios + verification -> out/results.json
.venv/bin/python scripts/04_report.py    # -> out/results.md, out/map.html
```

Dependencies: `brew install osmium-tool`; Python 3.12 venv from
`requirements.txt` (pinned with pip freeze).

## Method

1. Everything in EPSG:3346 (LKS-94, meters).
2. Land mask: OSM admin_level=2 polygon minus sea/lagoon (coastline ways
   polygonized, faces classified by probe points) minus lakes ≥ 0.5 km².
   Result: 63,884 km². Bogs and wetlands stay in.
3. Coarse pass: roads rasterized at 25 m over LT bounds + 15 km
   (16,880 x 12,581 px), `scipy.ndimage.distance_transform_edt`, top 80
   candidate cells ≥ 2 km apart.
4. Refinement: exact vector distances (shapely STRtree) on a 5 m grid in a
   500 m window around each candidate.
5. Verification: cross-border roads present after clipping; winner on land and
   in LT; independent exact re-check plus 1 m densified nearest-way check;
   A ≤ B.

## Runtime and footprint

On an M-series MacBook (24 GB RAM): downloads are the slow part; prepare ~2
min; compute ~90 s total for both scenarios (EDT peak memory a few GB).
Disk: ~1 GB raw PBF, ~250 MB derived layers, 2x 810 MB float32 distance
grids in `out/` (deletable, only used for map isolines).
