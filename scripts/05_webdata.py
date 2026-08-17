"""Extract a compact JSON bundle for the self-contained web page:
land outline, remoteness bands, ranked spots with local roads, city labels.
All coordinates in LKS-94 meters, rounded, as [[x,y],...] rings/lines.
"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import pyogrio
import shapely
from shapely.geometry import Point, shape
from rasterio.features import shapes as rio_shapes
from rasterio.transform import from_origin

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
OUT = BASE / "out"
CRS = 3346

SET_B = {
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
    "residential", "living_street", "service", "road",
    "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",
}

results = json.loads((OUT / "results.json").read_text())

def clean_road(r):
    return {k: (None if isinstance(v, float) and math.isnan(v) else v)
            for k, v in r.items()}

def load(path, cols):
    fields = pyogrio.read_info(path)["fields"]
    df = pyogrio.read_dataframe(path, columns=[c for c in cols if c in fields])
    if df.crs is None:
        df = df.set_crs(4326)
    return df.to_crs(CRS)

# ---------------------------------------------------------------- land
def rings(geom, min_hole=0.0):
    """Polygon/multipolygon -> list of rings, each [[x,y],...] in whole meters."""
    out = []
    polys = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
    for p in polys:
        keep = [p.exterior] + [r for r in p.interiors
                               if shapely.Polygon(r).area >= min_hole]
        for ring in keep:
            out.append(np.asarray(ring.coords).round(0).astype(int).tolist())
    return out

land = gpd.read_file(OUT / "land.gpkg").geometry.iloc[0]
land_s = land.simplify(250)
land_s = shapely.MultiPolygon(
    [p for p in (land_s.geoms if land_s.geom_type == "MultiPolygon" else [land_s])
     if p.area > 2e6])
land_rings = rings(land_s, min_hole=3e6)

# ---------------------------------------------------------------- bands
def bands_for(tag, dmax):
    meta = json.loads((OUT / f"dist_{tag}.meta.json").read_text())
    dist = np.load(OUT / f"dist_{tag}.npy")
    t = from_origin(meta["xmin"], meta["ymax"], meta["res"], meta["res"])
    out = []
    for thr in [1000 * k for k in range(1, min(4, int(dmax // 1000)) + 1)]:
        m = (dist >= thr).astype(np.uint8)
        polys = [shape(g) for g, _ in rio_shapes(m, mask=m.astype(bool), transform=t)]
        min_a = 1.5e6 if thr == 1000 else 0.3e6
        polys = [p.simplify(80) for p in polys if p.area >= min_a]
        rr = []
        for p in polys:
            rr += rings(p)
        out.append({"km": thr // 1000, "rings": rr})
    del dist
    return out

# ---------------------------------------------------------------- naming
places = load(DATA / "places.geojsonl", ["name", "place"])
places = places[places["name"].notna()].reset_index(drop=True)
prot = load(DATA / "protected.geojsonl", ["name"])
prot = prot[prot["name"].notna()].reset_index(drop=True)
WINDS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

def describe(s):
    p = Point(*s["lks94"])
    d = shapely.distance(places.geometry.values, p)
    i = int(np.argmin(d))
    pl = places.iloc[i]
    wind = WINDS[int(((math.degrees(math.atan2(p.x - pl.geometry.x,
                                               p.y - pl.geometry.y)) + 22.5) % 360) // 45)]
    inside = prot[prot.contains(p)].copy()
    inside["a"] = inside.geometry.area
    names = list(dict.fromkeys(inside.sort_values("a")["name"].tolist()))[:2]
    s["near"] = f"{d[i]/1000:.1f} km {wind} of {pl['name']}"
    s["protected"] = names
    return s

# ---------------------------------------------------------------- local roads
def local_roads(s, half_m=6500, nearest_id=None):
    x, y = s["lks94"]
    frames = []
    for f in DATA.glob("*-roads.geojsonl"):
        fields = pyogrio.read_info(f)["fields"]
        cols = [c for c in ("@id", "highway") if c in fields]
        # bbox filter needs dataset CRS (4326)
        lat, lon = s["wgs84"]
        dlat = half_m / 111_320
        dlon = half_m / (111_320 * math.cos(math.radians(lat)))
        try:
            df = pyogrio.read_dataframe(
                f, columns=cols, bbox=(lon - dlon, lat - dlat, lon + dlon, lat + dlat))
        except Exception:
            continue
        if len(df):
            frames.append(df)
    df = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True))
    if df.crs is None:
        df = df.set_crs(4326)
    df = df.to_crs(CRS)
    df = df[df["highway"].isin(SET_B | {"track"})]
    clipbox = shapely.box(x - half_m, y - half_m, x + half_m, y + half_m)
    df.geometry = df.geometry.intersection(clipbox)
    df = df[~df.geometry.is_empty]
    lines = []
    for _, row in df.iterrows():
        geoms = row.geometry.geoms if row.geometry.geom_type == "MultiLineString" \
            else [row.geometry]
        for g in geoms:
            if g.geom_type != "LineString":
                continue
            is_nearest = nearest_id and int(row.get("@id", 0)) == nearest_id
            if g.length < 150 and not is_nearest:
                continue
            c = np.asarray(g.simplify(30).coords).round(0).astype(int).tolist()
            lines.append({
                "c": c,
                "t": 1 if row["highway"] == "track" else 0,
                "n": 1 if is_nearest else 0,
            })
    return lines

# ---------------------------------------------------------------- assemble
web = {"crs": "EPSG:3346", "land": land_rings, "scenarios": {}}

cities = load(DATA / "places.geojsonl", ["name", "place"])
cities = cities[cities["place"] == "city"]
web["cities"] = [
    {"name": r["name"], "xy": [int(r.geometry.x), int(r.geometry.y)]}
    for _, r in cities.iterrows() if r["name"]
]

for tag, sc in results["scenarios"].items():
    spots = []
    for rank, s in enumerate([sc["winner"], *sc["runners_up"]], 1):
        s = dict(s)
        s["nearest_road"] = clean_road(s["nearest_road"])
        s = describe(s)
        s["rank"] = rank
        # radius must always reach past the nearest road so it can be highlighted
        s["roads"] = local_roads(s, half_m=max(6500, s["distance_m"] + 1200),
                                 nearest_id=s["nearest_road"]["osm_way"])
        spots.append(s)
    web["scenarios"][tag] = {
        "label": sc["label"], "ways": sc["ways"], "road_km": sc["road_km"],
        "bands": bands_for(tag, sc["winner"]["distance_m"]),
        "spots": spots,
    }

out_path = OUT / "webdata.json"
out_path.write_text(json.dumps(web, ensure_ascii=False, separators=(",", ":")))
print(f"wrote {out_path} ({out_path.stat().st_size/1e6:.2f} MB)")
for tag, sc in web["scenarios"].items():
    n = sum(len(b["rings"]) for b in sc["bands"])
    r = sum(len(s["roads"]) for s in sc["spots"])
    print(f"  {tag}: {n} band rings, {r} road lines")
print(f"  land rings: {len(land_rings)}, cities: {len(web['cities'])}")
