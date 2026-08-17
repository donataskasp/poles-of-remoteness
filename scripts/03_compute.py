"""Compute Lithuania's pole of remoteness.

Finds the point on Lithuanian LAND territory that maximizes distance to the
nearest drivable road, counting roads in neighboring countries. Two road
definitions are computed:

  Scenario A ("any drivable way")  - includes highway=track
  Scenario B ("public roads")      - same set without track

Method: 25 m rasterized road mask + euclidean distance transform for candidate
zones, then exact vector distances on a 5 m grid (STRtree) around each
candidate. Outputs out/results.json plus float32 distance grids for mapping.
"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import pyogrio
import shapely
from shapely.geometry import box, Point
from shapely.ops import polygonize
from shapely.strtree import STRtree
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.transform import from_origin
from scipy.ndimage import distance_transform_edt

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
OUT = BASE / "out"
OUT.mkdir(exist_ok=True)

CRS = 3346  # LKS-94, meters
RES = 25.0  # coarse raster resolution, m
MARGIN = 15_000.0  # raster margin beyond LT bounds; valid while max dist < margin
REFINE_HALF = 250.0  # refinement window half-size, m
REFINE_STEP = 5.0
DEDUP_COARSE = 2_000.0
DEDUP_FINAL = 10_000.0
LAKE_MIN_M2 = 0.5e6

COUNTRIES = {
    "lithuania": "Lithuania",
    "latvia": "Latvia",
    "belarus": "Belarus",
    "podlaskie": "Poland",
    "warminsko-mazurskie": "Poland",
    "kaliningrad": "Russia (Kaliningrad)",
}

SET_B = {
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
    "residential", "living_street", "service", "road",
    "motorway_link", "trunk_link", "primary_link", "secondary_link",
    "tertiary_link",
}
SET_A = SET_B | {"track"}

T = Transformer.from_crs(4326, CRS, always_xy=True)
to_wgs = Transformer.from_crs(CRS, 4326, always_xy=True)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- load roads
def load_roads():
    frames = []
    for name, country in COUNTRIES.items():
        path = DATA / f"{name}-roads.geojsonl"
        fields = pyogrio.read_info(path)["fields"]
        want = [c for c in ("@id", "highway", "surface", "name", "ref") if c in fields]
        df = pyogrio.read_dataframe(path, columns=want)
        df["country"] = country
        frames.append(df)
        log(f"  {name}: {len(df)} highway ways")
    roads = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True))
    if roads.crs is None:
        roads = roads.set_crs(4326)
    roads = roads.to_crs(CRS)
    roads = roads[roads.geometry.length > 0].reset_index(drop=True)
    return roads


# ------------------------------------------------------------- land mask
def build_land(bbox_poly):
    lt = gpd.read_file(DATA / "lt-admin.gpkg").geometry.iloc[0]

    coast = pyogrio.read_dataframe(DATA / "coastline.geojsonl", columns=[])
    if coast.crs is None:
        coast = coast.set_crs(4326)
    coast = coast.to_crs(CRS)
    lines = shapely.intersection(coast.geometry.values, bbox_poly)
    lines = [g for g in lines if not g.is_empty]
    faces = list(polygonize(shapely.unary_union(lines + [bbox_poly.boundary])))
    log(f"  coastline polygonize: {len(faces)} faces")

    def pt(lon, lat):
        return Point(*T.transform(lon, lat))

    sea_probes = [pt(20.75, 55.75), pt(21.15, 55.45)]  # Baltic, Curonian Lagoon
    land_probes = [pt(25.28, 54.687), pt(21.005, 55.303), pt(21.38, 55.295)]  # Vilnius, Nida, Rusne
    sea_faces = [f for f in faces if any(f.contains(p) for p in sea_probes)]
    assert sea_faces, "no sea faces found - coastline polygonization failed"
    for f in sea_faces:
        assert not any(f.contains(p) for p in land_probes), \
            "a face contains both sea and land probes - coastline has a gap"
    sea = shapely.unary_union(sea_faces)
    assert sea.area / 1e6 > 3_000, f"sea implausibly small: {sea.area/1e6:.0f} km2"

    land = lt.difference(sea)

    water = pyogrio.read_dataframe(DATA / "water.geojsonl", columns=[])
    if water.crs is None:
        water = water.set_crs(4326)
    water = water.to_crs(CRS)
    big = water.geometry[water.geometry.area >= LAKE_MIN_M2]
    log(f"  water bodies >= 0.5 km2: {len(big)}")
    land = land.difference(shapely.unary_union(big.values))

    a = land.area / 1e6
    log(f"  land mask area: {a:.0f} km2")
    assert 61_000 < a < 67_000, f"implausible land area {a:.0f} km2"
    gpd.GeoSeries([land], crs=CRS).to_file(OUT / "land.gpkg", driver="GPKG")
    return lt, land


# ----------------------------------------------------- coarse EDT + candidates
def coarse_candidates(tag, geoms, land, bounds):
    xmin, ymin, xmax, ymax = bounds
    w = int(np.ceil((xmax - xmin) / RES))
    h = int(np.ceil((ymax - ymin) / RES))
    transform = from_origin(xmin, ymax, RES, RES)
    log(f"  raster {w} x {h} = {w*h/1e6:.0f} Mpx")

    road_r = rasterize(
        ((g, 1) for g in geoms), out_shape=(h, w), transform=transform,
        fill=0, all_touched=True, dtype="uint8",
    )
    dist = distance_transform_edt(road_r == 0, sampling=RES)
    del road_r
    land_r = rasterize(
        [(land, 1)], out_shape=(h, w), transform=transform, fill=0, dtype="uint8"
    ).astype(bool)
    dist[~land_r] = -1.0

    np.save(OUT / f"dist_{tag}.npy", dist.astype(np.float32))
    (OUT / f"dist_{tag}.meta.json").write_text(json.dumps(
        {"xmin": xmin, "ymax": ymax, "res": RES, "shape": [h, w], "crs": CRS}))

    dmax = float(dist.max())
    log(f"  coarse max distance: {dmax:.0f} m")
    thr = max(600.0, 0.30 * dmax)
    ys, xs = np.where(dist > thr)
    vals = dist[ys, xs]
    order = np.argsort(-vals)
    coords = np.stack([xmin + (xs + 0.5) * RES, ymax - (ys + 0.5) * RES], 1)[order]
    vals = vals[order]

    kept, alive, pos = [], np.ones(len(vals), bool), 0
    while len(kept) < 80 and pos < len(vals):
        if not alive[pos]:
            pos += 1
            continue
        c = coords[pos]
        kept.append((c[0], c[1], float(vals[pos])))
        alive &= ((coords - c) ** 2).sum(1) >= DEDUP_COARSE ** 2
    del dist
    log(f"  {len(kept)} coarse candidates (>{thr:.0f} m, {DEDUP_COARSE/1000:.0f} km apart)")
    return kept


# ------------------------------------------------------------- refinement
def refine(tree, land, cx, cy):
    ax = np.arange(cx - REFINE_HALF, cx + REFINE_HALF + 1, REFINE_STEP)
    ay = np.arange(cy - REFINE_HALF, cy + REFINE_HALF + 1, REFINE_STEP)
    gx, gy = np.meshgrid(ax, ay)
    pts = shapely.points(gx.ravel(), gy.ravel())
    on_land = shapely.contains(land, pts)
    pts = pts[on_land]
    if len(pts) == 0:
        return None
    idx, dists = tree.query_nearest(pts, return_distance=True, all_matches=False)
    # one pair per input point; order by input index
    d = np.full(len(pts), np.inf)
    d[idx[0]] = dists
    best = int(np.argmax(d))
    p = pts[best]
    return float(p.x), float(p.y), float(d[best])


def nearest_road_info(tree, roads, x, y):
    idx, dist = tree.query_nearest(Point(x, y), return_distance=True, all_matches=False)
    row = roads.iloc[int(idx[0])]
    oid = int(row.get("@id", -1))
    return {
        "osm_way": oid,
        "url": f"https://www.openstreetmap.org/way/{oid}",
        "highway": row.get("highway"),
        "surface": None if str(row.get("surface")) == "None" else row.get("surface"),
        "name": None if str(row.get("name")) == "None" else row.get("name"),
        "ref": None if str(row.get("ref")) == "None" else row.get("ref"),
        "country": row["country"],
    }


def spot(tree, roads, x, y, dist_m):
    lon, lat = to_wgs.transform(x, y)
    return {
        "lks94": [round(x, 1), round(y, 1)],
        "wgs84": [round(lat, 6), round(lon, 6)],
        "distance_m": round(dist_m, 1),
        "osm_link": f"https://www.openstreetmap.org/?mlat={lat:.6f}&mlon={lon:.6f}#map=13/{lat:.6f}/{lon:.6f}",
        "nearest_road": nearest_road_info(tree, roads, x, y),
    }


# ------------------------------------------------------------- verification
def verify_winner(tree, land, lt, x, y, reported):
    p = Point(x, y)
    assert land.contains(p), "winner not on land mask"
    assert lt.contains(p), "winner not inside Lithuania"
    # exact re-check: all geoms within reported+100 m, min distance must match
    near = tree.geometries[tree.query(p.buffer(reported + 100))]
    dmin = float(shapely.distance(near, p).min())
    assert abs(dmin - reported) < 0.01, f"distance mismatch {dmin} vs {reported}"
    # densified nearest way: min over ~1 m vertices must agree within 1.5 m
    idx, _ = tree.query_nearest(p, return_distance=True, all_matches=False)
    seg = shapely.segmentize(tree.geometries[int(idx[0])], 1.0)
    vd = float(np.min(shapely.distance(shapely.points(shapely.get_coordinates(seg)), p)))
    assert abs(vd - reported) < 1.5, f"densified check {vd} vs {reported}"
    return {"exact_recheck_m": round(dmin, 2), "densified_vertex_min_m": round(vd, 2)}


def verify_cross_border(roads):
    def deg_box(lo1, la1, lo2, la2):
        cs = [T.transform(lo, la) for lo, la in
              [(lo1, la1), (lo2, la1), (lo2, la2), (lo1, la2)]]
        return shapely.Polygon(cs)

    by_box = deg_box(24.40, 53.88, 24.70, 53.955)  # BY side, south of Cepkeliai
    pl_box = deg_box(22.60, 54.10, 23.20, 54.35)   # PL side, near Kalvarija
    by_n = int((roads[roads.country == "Belarus"].intersects(by_box)).sum())
    pl_n = int((roads[roads.country == "Poland"].intersects(pl_box)).sum())
    assert by_n > 0, "no Belarusian roads near Cepkeliai - clipping lost cross-border data"
    assert pl_n > 0, "no Polish roads near Kalvarija - clipping lost cross-border data"
    return {"by_roads_near_cepkeliai": by_n, "pl_roads_near_kalvarija": pl_n}


def check_patrol_road(roads_a, lt):
    """Is the LT-BY border-barrier patrol road mapped along Cepkeliai's south edge?"""
    zone = shapely.Polygon([T.transform(lo, la) for lo, la in
                            [(24.30, 53.90), (24.80, 53.90), (24.80, 54.05), (24.30, 54.05)]])
    border = lt.boundary.intersection(zone)
    if border.is_empty:
        return {"note": "no border segment in probe zone"}
    strip = border.buffer(1_200)
    hits = roads_a[roads_a.intersects(strip)]
    kinds = hits.groupby(["country", "highway"]).size()
    return {
        "roads_within_1200m_of_border": int(len(hits)),
        "breakdown": {f"{c}/{h}": int(n) for (c, h), n in kinds.items()},
    }


# ------------------------------------------------------------------ main
def main():
    log("loading roads")
    roads = load_roads()
    log(f"total {len(roads)} ways")

    lt_admin = gpd.read_file(DATA / "lt-admin.gpkg").geometry.iloc[0]
    b = lt_admin.bounds
    bounds = (b[0] - MARGIN, b[1] - MARGIN, b[2] + MARGIN, b[3] + MARGIN)
    bbox_poly = box(*bounds)

    log("building land mask")
    lt, land = build_land(bbox_poly)
    shapely.prepare(land)
    shapely.prepare(lt)

    results = {"crs_note": "lks94 = EPSG:3346 [x_east, y_north] m; wgs84 = [lat, lon]",
               "scenarios": {}}
    results["verification_cross_border"] = verify_cross_border(roads)
    log(f"cross-border ok: {results['verification_cross_border']}")

    for tag, hset, label in (
        ("A", SET_A, "any drivable way (incl. track)"),
        ("B", SET_B, "public roads (no track)"),
    ):
        log(f"scenario {tag}: {label}")
        sub = roads[roads["highway"].isin(hset)].reset_index(drop=True)
        km = float(sub.geometry.length.sum() / 1000)
        log(f"  {len(sub)} ways, {km:,.0f} km")

        cands = coarse_candidates(tag, sub.geometry.values, land, bounds)

        tree = STRtree(sub.geometry.values)
        refined = []
        for cx, cy, cv in cands:
            r = refine(tree, land, cx, cy)
            if r:
                refined.append(r)
        refined.sort(key=lambda t: -t[2])
        log(f"  refined best: {refined[0][2]:.0f} m")

        top, taken = [], []
        for x, y, d in refined:
            if all((x - tx) ** 2 + (y - ty) ** 2 >= DEDUP_FINAL ** 2 for tx, ty in taken):
                top.append(spot(tree, sub, x, y, d))
                taken.append((x, y))
            if len(top) == 6:
                break

        wx, wy, wd = refined[0]
        ver = verify_winner(tree, land, lt, wx, wy, wd)
        if tag == "A":
            patrol = check_patrol_road(sub, lt)
            log(f"  patrol road check: {patrol}")
            results["verification_patrol_road"] = patrol

        results["scenarios"][tag] = {
            "label": label, "ways": len(sub), "road_km": round(km),
            "winner": top[0], "runners_up": top[1:],
            "verification": ver,
        }

    a = results["scenarios"]["A"]["winner"]["distance_m"]
    bmax = results["scenarios"]["B"]["winner"]["distance_m"]
    assert a <= bmax + 0.01, f"sanity fail: A ({a}) > B ({bmax})"
    results["sanity_A_le_B"] = True

    (OUT / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    log("wrote out/results.json")
    for tag in ("A", "B"):
        w = results["scenarios"][tag]["winner"]
        log(f"scenario {tag}: {w['distance_m']} m at {w['wgs84']} "
            f"(nearest: {w['nearest_road']['highway']} in {w['nearest_road']['country']})")


if __name__ == "__main__":
    main()
