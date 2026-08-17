"""Build the static data bundle for the interactive website (site/data/).

Everything the browser needs, in WGS-84 so Leaflet can use it directly:

  spots.json          ranked spots + local roads, [lat,lon]
  bands_{A,B}.geojson remoteness bands (>=1..4 km), holes preserved
  land.geojson        simplified Lithuania outline
  places.json         settlement search index [name, lat, lon, type]
  dist_{A,B}.png      100 m remoteness grid, 8-bit (px*50 = m, 255 = outside)
  grid.json           georeference for the PNGs (trivial lat/lon -> pixel)

Reads out/webdata.json, out/dist_*.npy, out/land.gpkg, data/places.geojsonl.
Writes only into site/data/.
"""
import json
import math
import time
from pathlib import Path

import numpy as np
import geopandas as gpd
import pyogrio
import shapely
from shapely.geometry import mapping, shape
from PIL import Image
from pyproj import Transformer
from rasterio.features import shapes as rio_shapes
from rasterio.transform import from_origin
from rasterio.warp import reproject, Resampling

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
OUT = BASE / "out"
SITE = BASE / "site" / "data"
CRS = 3346

DLON = 0.0015  # target grid step, deg (~100 m)
DLAT = 0.0009
PAD = 0.02
SCALE_M = 50  # PNG value * 50 = meters
NODATA = 255

to_wgs = Transformer.from_crs(CRS, 4326, always_xy=True)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def rnd(obj, nd=5):
    """Recursively round every float in a nested coordinate structure."""
    if isinstance(obj, float):
        return round(obj, nd)
    if isinstance(obj, (list, tuple)):
        return [rnd(v, nd) for v in obj]
    return obj


def dump(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    mb = path.stat().st_size / 1e6
    log(f"  wrote {path.relative_to(BASE)} ({mb:.2f} MB)")
    return mb


def to4326(geoms, nd=5):
    """List of LKS-94 shapely geoms -> one rounded GeoJSON MultiPolygon mapping."""
    gs = gpd.GeoSeries(geoms, crs=CRS).to_crs(4326)
    polys = []
    for g in gs:
        polys += list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
    m = mapping(shapely.MultiPolygon(polys))
    return {"type": "MultiPolygon", "coordinates": rnd(m["coordinates"], nd)}


# ------------------------------------------------------------------ A. spots
def build_spots(web):
    out = {}
    for tag, sc in web["scenarios"].items():
        spots = []
        for s in sc["spots"]:
            lat, lon = s["wgs84"]
            roads = []
            for r in s["roads"]:
                c = np.asarray(r["c"], dtype=float)
                lo, la = to_wgs.transform(c[:, 0], c[:, 1])
                ll = np.stack([la, lo], 1).round(5).tolist()
                roads.append({"ll": ll, "t": r["t"], "n": r["n"]})
            spots.append({
                "rank": s["rank"],
                "latlng": [round(lat, 6), round(lon, 6)],
                "distance_m": s["distance_m"],
                "near": s["near"],
                "protected": s["protected"],
                "osm_link": s["osm_link"],
                "nearest_road": s["nearest_road"],
                "roads": roads,
            })
        out[tag] = {"label": sc["label"], "ways": sc["ways"],
                    "road_km": sc["road_km"], "spots": spots}
    return dump(SITE / "spots.json", {"scenarios": out})


# ------------------------------------------------------------------ B. bands
def band_polys(dist, meta, dmax, tol):
    """Vectorize dist >= thr for each km threshold; interior rings preserved."""
    t = from_origin(meta["xmin"], meta["ymax"], meta["res"], meta["res"])
    feats = []
    for thr in [1000 * k for k in range(1, min(4, int(dmax // 1000)) + 1)]:
        m = dist >= thr  # -1 (outside land) is excluded for free
        polys = [shape(g) for g, _ in rio_shapes(m.astype(np.uint8), mask=m, transform=t)]
        min_a = 1.5e6 if thr == 1000 else 0.3e6
        polys = [p.simplify(tol) for p in polys if p.area >= min_a]
        polys = [p for p in polys if not p.is_empty]
        holes = sum(len(p.interiors) for p in polys)
        log(f"    {thr//1000} km: {len(polys)} polygons, {holes} holes")
        feats.append({"type": "Feature", "properties": {"km": thr // 1000},
                      "geometry": to4326(polys)})
        del m
    return feats


def build_bands(tag, dist, meta, dmax):
    tol = 80
    feats = band_polys(dist, meta, dmax, tol)
    path = SITE / f"bands_{tag}.geojson"
    mb = dump(path, {"type": "FeatureCollection", "features": feats})
    if mb > 1.5:
        tol = 120
        log(f"  bands_{tag} over 1.5 MB, re-running with simplify({tol})")
        feats = band_polys(dist, meta, dmax, tol)
        mb = dump(path, {"type": "FeatureCollection", "features": feats})
    return feats, mb, tol


# ------------------------------------------------------------------- C. land
def build_land():
    land = gpd.read_file(OUT / "land.gpkg").geometry.iloc[0].simplify(250)
    parts = land.geoms if land.geom_type == "MultiPolygon" else [land]
    keep = []
    for p in parts:
        if p.area < 2e6:
            continue
        ints = [r for r in p.interiors if shapely.Polygon(r).area >= 3e6]
        keep.append(shapely.Polygon(p.exterior, ints))
    log(f"  land: {len(keep)} parts, {sum(len(p.interiors) for p in keep)} holes")
    feat = {"type": "Feature", "properties": {}, "geometry": to4326(keep)}
    return dump(SITE / "land.geojson", feat)


# ----------------------------------------------------------------- D. places
def build_places():
    df = pyogrio.read_dataframe(DATA / "places.geojsonl", columns=["name", "place"])
    if df.crs is None:
        df = df.set_crs(4326)
    kinds = {"city": "c", "town": "t", "village": "v"}
    df = df[df["name"].notna() & df["place"].isin(kinds)]
    rows, seen = [], set()
    for name, place, geom in zip(df["name"], df["place"], df.geometry):
        if geom is None or geom.is_empty:
            continue
        p = geom if geom.geom_type == "Point" else geom.representative_point()
        key = (name, round(p.y, 3), round(p.x, 3))
        if key in seen:
            continue
        seen.add(key)
        rows.append([name, round(p.y, 5), round(p.x, 5), kinds[place]])
    rows.sort(key=lambda r: r[0])
    log(f"  places: {len(rows)} entries ({len(df) - len(rows)} duplicates dropped)")
    return dump(SITE / "places.json", rows), len(rows)


# ------------------------------------------------------- E. grid PNG + georef
def grid_spec():
    # admin boundary, not the land mask: it includes territorial waters, so the
    # grid covers the coast and offshore lookups land on real nodata pixels
    b = gpd.read_file(DATA / "lt-admin.gpkg").to_crs(4326).total_bounds
    west, south = b[0] - PAD, b[1] - PAD
    east, north = b[2] + PAD, b[3] + PAD
    w = int(math.ceil((east - west) / DLON))
    h = int(math.ceil((north - south) / DLAT))
    return {"west": round(west, 6), "north": round(north, 6),
            "dlon": DLON, "dlat": DLAT, "width": w, "height": h,
            "scale_m": SCALE_M, "nodata": NODATA}


def build_png(tag, dist, meta, g):
    dst = np.full((g["height"], g["width"]), -1.0, dtype=np.float32)
    reproject(
        source=dist,
        destination=dst,
        src_transform=from_origin(meta["xmin"], meta["ymax"], meta["res"], meta["res"]),
        src_crs=f"EPSG:{CRS}",
        src_nodata=-1.0,
        dst_transform=from_origin(g["west"], g["north"], DLON, DLAT),
        dst_crs="EPSG:4326",
        dst_nodata=-1.0,
        resampling=Resampling.nearest,
    )
    px = np.where(dst < 0, NODATA,
                  np.minimum(np.round(dst / SCALE_M), 254)).astype(np.uint8)
    del dst
    path = SITE / f"dist_{tag}.png"
    Image.fromarray(px, mode="L").save(path, optimize=True)
    valid = int((px != NODATA).sum())
    log(f"  wrote {path.relative_to(BASE)} ({path.stat().st_size/1e6:.2f} MB), "
        f"{valid} land px of {px.size}")
    del px
    return path.stat().st_size / 1e6


# -------------------------------------------------------------- validation
def px_at(img, g, lat, lon):
    """Same lookup the browser does; outside the raster counts as nodata."""
    col = int(math.floor((lon - g["west"]) / g["dlon"]))
    row = int(math.floor((g["north"] - lat) / g["dlat"]))
    if not (0 <= col < g["width"] and 0 <= row < g["height"]):
        return NODATA
    return int(img[row, col])


def main():
    SITE.mkdir(parents=True, exist_ok=True)
    web = json.loads((OUT / "webdata.json").read_text())

    log("A. spots.json")
    sizes = {"spots.json": build_spots(web)}

    log("C. land.geojson")
    sizes["land.geojson"] = build_land()

    log("D. places.json")
    sizes["places.json"], n_places = build_places()

    g = grid_spec()
    log(f"E. target grid {g['width']} x {g['height']} px "
        f"({g['width']*g['height']/1e6:.1f} Mpx)")
    sizes["grid.json"] = dump(SITE / "grid.json", g)

    bands = {}
    for tag in ("A", "B"):
        meta = json.loads((OUT / f"dist_{tag}.meta.json").read_text())
        log(f"scenario {tag}: loading dist_{tag}.npy {meta['shape']}")
        dist = np.load(OUT / f"dist_{tag}.npy")
        dmax = float(dist.max())
        log(f"  max distance {dmax:.1f} m")
        log(f"B. bands_{tag}.geojson")
        feats, mb, tol = build_bands(tag, dist, meta, dmax)
        bands[tag] = (feats, tol)
        sizes[f"bands_{tag}.geojson"] = mb
        log(f"E. dist_{tag}.png")
        sizes[f"dist_{tag}.png"] = build_png(tag, dist, meta, g)
        del dist

    # ------------------------------------------------------------ validation
    log("validation")
    spots = json.loads((SITE / "spots.json").read_text())["scenarios"]
    imgs = {t: np.asarray(Image.open(SITE / f"dist_{t}.png")) for t in ("A", "B")}
    for t, img in imgs.items():
        assert img.shape == (g["height"], g["width"]), f"{t} png shape {img.shape}"

    ok = True
    for t, expect in (("B", 6674.6), ("A", 3425.6)):
        lat, lon = spots[t]["spots"][0]["latlng"]
        v = px_at(imgs[t], g, lat, lon) * SCALE_M
        d = abs(v - expect)
        log(f"  {t} winner ({lat}, {lon}): png {v} m vs {expect} m -> delta {d:.0f} m")
        ok &= d < 300
        assert d < 300, f"{t} winner png readback off by {d:.0f} m"

    v = px_at(imgs["A"], g, 54.687, 25.28) * SCALE_M
    log(f"  Vilnius centre, scenario A: {v} m (expect < 400)")
    assert v < 400, f"Vilnius reads {v} m"

    for lat, lon in ((55.6, 20.6), (55.6, 20.8)):
        inside = g["west"] <= lon < g["west"] + g["width"] * g["dlon"]
        v = px_at(imgs["B"], g, lat, lon)
        log(f"  Baltic sea ({lat}, {lon}): {v} (expect {NODATA}"
            f"{', in raster' if inside else ', west of raster'})")
        assert v == NODATA, f"sea pixel is {v}, not nodata"

    for t, (feats, tol) in bands.items():
        assert feats, f"no band features for {t}"
        for f in feats:
            assert f["geometry"]["coordinates"], f"empty band {f['properties']['km']} km in {t}"
        kms = [f["properties"]["km"] for f in feats]
        assert 3 in kms, f"no 3 km band in {t}"
        log(f"  bands {t}: km {kms}, simplify tolerance {tol}")

    for t in ("A", "B"):
        f3 = next(f for f in bands[t][0] if f["properties"]["km"] == 3)
        holes = sum(len(p) - 1 for p in f3["geometry"]["coordinates"])
        log(f"  {t} 3 km band: {len(f3['geometry']['coordinates'])} polygons, "
            f"{holes} interior ring(s)" + (" (none)" if holes == 0 else ""))

    log(f"  places: {n_places} entries")
    total = sum(sizes.values())
    log("file sizes:")
    for k in sorted(sizes):
        log(f"  {k:22s} {sizes[k]:6.2f} MB")
    log(f"  {'TOTAL':22s} {total:6.2f} MB")
    assert total < 10, f"site/data is {total:.2f} MB, over the 10 MB budget"
    log("all checks passed")


if __name__ == "__main__":
    main()
