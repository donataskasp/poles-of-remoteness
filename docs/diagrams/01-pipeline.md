# 01: the pipeline

## At a glance

```mermaid
flowchart LR
    osm[(Geofabrik PBF + .poly)] --> fetch --> extract --> classify --> grid --> poles --> validate --> publish
    publish --> r2[(R2 bucket)]
    publish -.-> sitedata[(site/data JSON documents)]
    cfg[pipeline/regions/region.yaml] --> fetch
```

One `poles run <region> --snapshot <date>` runs the stages in this order; each stage writes `done.json` in its directory under `work/<region>/<snapshot>/` and is skipped next time unless `--force`.

The dashed arrow is the site documents: `publish` writes them into the repository's `site/data/` unless `--no-write-site`, and `--site-dir` (or `POLES_SITE_DIR`) sends them somewhere else, which is how the dev harness feeds a local site.

## Detailed view

One diagram per stage. Every path is relative to `work/<region>/<snapshot>/`, except `shared/`, which is `work/shared/` and belongs to no region. Each name below is in the code and in a run on disk: the Europe snapshot for `fetch`, `grid`, `poles`, `validate` and `publish`, the North America one for `extract` and `classify`. Long sub-steps carry a `<file>.ok` marker beside the file, which is how a crashed stage resumes at the first missing piece. One name is in the code and in no run yet: `publish/inputs.json`, the stamp added after the Europe publish, which adopts a run that predates it rather than rebuilding it.

### fetch

Downloads every source and supplement, verifies the Geofabrik md5, and records the snapshot identity that names the whole run.

```mermaid
flowchart LR
    cfg["region.yaml: sources, supplement_sources"] --> fetch["fetch.py"]
    gf[("download.geofabrik.de")] --> fetch
    fetch --> pbf[("fetch/[name]-latest.osm.pbf and .md5")]
    fetch --> poly[("fetch/[name].poly")]
    fetch --> snap[("fetch/snapshot.json")]
```

### extract

Filters and merges the PBFs with osmium, then exports each layer to FlatGeobuf. The handle every later stage opens is `<layer>.vrt`, never the FlatGeobuf behind it: above the merge cap a layer lives as unindexed chunks and the VRT unions them.

```mermaid
flowchart LR
    pbf[("fetch/[name]-latest.osm.pbf")] --> osmium["osmium filter and merge"]
    osmium --> filtered[("extract/filtered.pbf")]
    filtered --> thematic[("extract/highways.pbf, boundaries.pbf, places.pbf, water.pbf")]
    thematic --> fgb[("extract/highways.part-NNNN.fgb, boundaries.fgb, places.fgb, water.fgb")]
    fgb --> vrt[("extract/highways.vrt, boundaries.vrt, places.vrt, water.vrt")]
    osmdata[("osmdata.openstreetmap.de land polygons")] --> landfgb[("shared/land.fgb behind shared/land.vrt")]
```

### classify

Scenario membership from the highway tags, one ogr2ogr pass per scenario over the union behind `highways.vrt`.

```mermaid
flowchart LR
    hv[("extract/highways.vrt")] --> classify["classify.py, OGRSQL on the highway tag"]
    classify --> ra[("classify/roads_A.fgb")]
    classify --> rb[("classify/roads_B.fgb")]
```

### grid

The raster frame, the road masks, the tiled exact Euclidean distance transform, and the land mask.

```mermaid
flowchart LR
    cfg["region.yaml: coarse_crs, coarse_res_m, max_distance_m"] --> frame[("grid/frame.json")]
    snap[("fetch/snapshot.json")] --> poly[("fetch/[name].poly, the primary sources")] --> frame
    roads[("classify/roads_A.fgb, roads_B.fgb")] --> rast["gdal_rasterize"]
    frame --> rast
    rast --> rtif[("grid/roads_A.tif, roads_B.tif")]
    rtif --> edt["tiled exact distance transform"]
    edt --> dist[("grid/dist_A.tif, dist_B.tif")]
    landv[("shared/land.vrt")] --> mask["land minus water of at least the minimum area"]
    waterv[("extract/water.vrt")] --> mask
    mask --> lt[("grid/land.tif, grid/water_proj.fgb")]
```

### poles

`prepare` builds everything the searches share, then one process per unit and scenario runs the branch and bound down to an exact 5 m sweep in the local UTM zone and attributes the nearest road and settlement.

```mermaid
flowchart LR
    bpbf[("extract/boundaries.pbf")] --> prepare["prepare"]
    poly[("fetch/[name].poly, the data edge")] --> prepare
    frame[("grid/frame.json")] --> prepare
    landv[("shared/land.vrt")] --> prepare
    wp[("grid/water_proj.fgb")] --> prepare
    prepare --> units[("poles/countries.fgb, units.fgb, units.json, units.tif, units_low.tif, land_idx.fgb, water_big.fgb")]
    hv[("extract/highways.vrt")] --> tiling["5 degree road tiles, built once"]
    tiling --> rtiles[("poles/roads/t_[west]_[south].fgb, indexed by poles/roads/tiles.json")]
    units --> search["search_unit, one unit and scenario per process"]
    dist[("grid/dist_A.tif, dist_B.tif")] --> search
    rtiles --> search
    places[("extract/places.vrt")] --> search
    search --> res[("poles/results/[unit]-[scenario].json")]
    res --> ab[("poles/A.json, poles/B.json, poles/timing.json")]
```

### validate

Seven checks that re-derive every published pole by an independent path. Check 4 recomputes the whole grid half a cell shifted, which is why this stage has the grid stage's memory profile. A pole whose nearest road may lie outside the extract is excluded rather than fatal; anything else that blocks stops the run after the three reports are written.

```mermaid
flowchart LR
    ab[("poles/A.json, B.json, units.json, units.fgb, water_big.fgb")] --> checks["checks 1 to 7"]
    gridin[("grid/frame.json, dist_A.tif, dist_B.tif, roads_A.tif, roads_B.tif")] --> checks
    rtiles[("poles/roads/")] --> checks
    checks --> shift[("validate/frame_shift.json, dist_[S]_shift.tif, roads_[S]_shift.tif, units_shift.tif, shifted_winners.json")]
    checks --> rep[("validate/report.json, report.html, contact-sheet.html")]
    basemap[("basemap tiles cached under validate/tiles/")] --> rep
```

### publish

Quantises the grids into one class byte per pixel, cuts the explore archives, renders a detail raster per published pole, uploads everything to R2 and verifies it, and only then writes the site documents. It refuses to run without `validate/done.json`.

```mermaid
flowchart LR
    poly[("fetch/[name].poly")] --> masks["publish/inside.tif, edgeband.tif, edgeband_4326.wkb"]
    gridin[("grid/dist_A.tif, dist_B.tif, land.tif, frame.json")] --> quant["quantise to the class table"]
    masks --> quant
    quant --> expl[("publish/explore_[S].tif, explore_[S]_3857.tif")]
    quant --> stamp[("publish/inputs.json, what the explore artefacts were built from")]
    expl --> cut["tile cut and MBTiles pack"]
    cut --> arch[("publish/A.pmtiles, B.pmtiles")]
    rtiles[("poles/roads/")] --> det["detail rasters at detail_res_m over detail_window_m"]
    det --> dpng[("publish/detail/[unit]/[S]-[rank].png and .json")]
    det --> dstamp[("publish/detail/published.json, the pole set the directory was built for")]
    arch --> up["upload over S3, then HEAD and range verify"]
    dpng --> up
    val[("validate/report.json, report.html, contact-sheet.html")] --> up
    up --> r2[("R2 bucket")]
    up --> site[("site/data/regions.json, manifest.json, [region]/units.json, [region]/units/[code].json")]
```

## What leaves the machine

Everything under `work/` is regenerable and gitignored. Two things travel:

| Destination | Keys or paths | Written by |
|---|---|---|
| R2 bucket | `<region>/<snapshot>/A.pmtiles` and `B.pmtiles`, `<region>/<snapshot>/detail/<unit>/<scenario>-<rank>.png` and `.json`, `<region>/<snapshot>/validation/report.json`, `report.html` and `contact-sheet.html` | `poles/publish/r2.py`, immutable cache headers, every key verified with a HEAD and each archive with a range request |
| git | `site/data/regions.json`, `site/data/manifest.json`, `site/data/<region>/units.json`, `site/data/<region>/units/<code>.json` | `poles/publish/sitedata.py`, validated against `poles/schemas/` before the write, and only after the R2 verification passed |

Reflects the code at Stage 5 close (2026-08-23).
