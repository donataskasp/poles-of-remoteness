"""Render deliverables from out/results.json:
  out/results.md  - human-readable report with named locations
  out/map.html    - interactive folium map (winners, runner-ups, remoteness
                    isoline bands, local road overlay)
"""
import json
import math
from pathlib import Path

import numpy as np
import geopandas as gpd
import pyogrio
import shapely
from shapely.geometry import Point, shape
import folium
from pyproj import Transformer
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

# dataviz palette: scenario A = blue sequential ramp, scenario B = orange ramp
RAMP = {
    "A": ["#9ec5f4", "#5598e7", "#256abf", "#184f95"],
    "B": ["#f7c5ab", "#f09468", "#eb6834", "#c24618"],
}
MARKER = {"A": "#2a78d6", "B": "#eb6834"}
ICON_COLOR = {"A": "blue", "B": "orange"}
ROAD_PUBLIC, ROAD_TRACK = "#52514e", "#898781"

T = Transformer.from_crs(4326, CRS, always_xy=True)

results = json.loads((OUT / "results.json").read_text())
snapshot = (DATA / "snapshot-date.txt").read_text().strip()

for _sc in results["scenarios"].values():
    for _s in [_sc["winner"], *_sc["runners_up"]]:
        _s["nearest_road"] = {
            k: (None if isinstance(v, float) and math.isnan(v) else v)
            for k, v in _s["nearest_road"].items()
        }

# ------------------------------------------------------- naming helpers
def load_named(path, extra_cols):
    fields = pyogrio.read_info(path)["fields"]
    cols = [c for c in extra_cols if c in fields]
    df = pyogrio.read_dataframe(path, columns=cols)
    if df.crs is None:
        df = df.set_crs(4326)
    return df.to_crs(CRS)

places = load_named(DATA / "places.geojsonl", ["name", "place"])
places = places[places["name"].notna()].reset_index(drop=True)
prot = load_named(DATA / "protected.geojsonl", ["name", "protect_class", "leisure"])
prot = prot[prot["name"].notna()].reset_index(drop=True)

WINDS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

def describe(spot_):
    p = Point(*spot_["lks94"])
    d = shapely.distance(places.geometry.values, p)
    i = int(np.argmin(d))
    pl = places.iloc[i]
    dx = p.x - pl.geometry.x
    dy = p.y - pl.geometry.y
    wind = WINDS[int(((math.degrees(math.atan2(dx, dy)) + 22.5) % 360) // 45)]
    inside = prot[prot.contains(p)].copy()
    inside["a"] = inside.geometry.area
    areas = list(dict.fromkeys(inside.sort_values("a")["name"].tolist()))[:2]
    spot_["near"] = f"{d[i]/1000:.1f} km {wind} of {pl['name']}"
    spot_["protected"] = areas
    return spot_

for sc in results["scenarios"].values():
    sc["winner"] = describe(sc["winner"])
    sc["runners_up"] = [describe(s) for s in sc["runners_up"]]

# ------------------------------------------------------- results.md
def gmaps(s):
    lat, lon = s["wgs84"]
    return f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}&t=k"

def road_str(r):
    bits = [f"`highway={r['highway']}`"]
    if r["surface"]:
        bits.append(f"surface={r['surface']}")
    if r["name"]:
        bits.append(f'"{r["name"]}"')
    if r["ref"]:
        bits.append(r["ref"])
    bits.append(f"in {r['country']}")
    return ", ".join(bits) + f" ([way {r['osm_way']}]({r['url']}))"

def spot_block(s, title):
    lat, lon = s["wgs84"]
    lines = [
        f"### {title}: {s['distance_m']/1000:.2f} km from the nearest road",
        "",
        f"- **Where:** {s['near']}" + (f", inside {', '.join(s['protected'])}" if s["protected"] else ""),
        f"- **WGS84:** {lat:.6f}, {lon:.6f} · **LKS-94:** {s['lks94'][0]:.0f}, {s['lks94'][1]:.0f}",
        f"- **Nearest road:** {road_str(s['nearest_road'])}",
        f"- [OpenStreetMap]({s['osm_link']}) · [Google Maps (satellite)]({gmaps(s)})",
        "",
    ]
    return "\n".join(lines)

md = [
    "# Lithuania's pole of remoteness",
    "",
    f"The point on Lithuanian land farthest from any drivable road, roads in all "
    f"neighboring countries included. Water (sea, lagoon, lakes > 0.5 km²) excluded "
    f"from candidate locations. OSM data snapshot: {snapshot}.",
    "",
]
for tag, sc in results["scenarios"].items():
    md += [
        f"## Scenario {tag}: {sc['label']}",
        "",
        f"Road network: {sc['ways']:,} ways, {sc['road_km']:,} km.",
        "",
        spot_block(sc["winner"], "Winner"),
    ]
    md += ["### Runners-up (mutually > 10 km apart)", "",
           "| # | km to road | Where | Coordinates | Nearest road |",
           "|---|---|---|---|---|"]
    for i, s in enumerate(sc["runners_up"], 2):
        lat, lon = s["wgs84"]
        where = s["near"] + (f" ({s['protected'][0]})" if s["protected"] else "")
        md.append(f"| {i} | {s['distance_m']/1000:.2f} | {where} | "
                  f"[{lat:.5f}, {lon:.5f}]({s['osm_link']}) | "
                  f"{s['nearest_road']['highway']}, {s['nearest_road']['country']} |")
    md.append("")

v = results["verification_cross_border"]
md += [
    "## Verification",
    "",
    f"- Cross-border road data survived clipping: {v['by_roads_near_cepkeliai']} Belarusian "
    f"ways near Čepkeliai, {v['pl_roads_near_kalvarija']} Polish ways near Kalvarija.",
    f"- Border-strip roads within 1.2 km of the LT–BY border at Čepkeliai (patrol-road check): "
    f"{json.dumps(results['verification_patrol_road']['breakdown'], ensure_ascii=False)}.",
    "- Winners verified on land and inside Lithuania; exact vector re-check and 1 m densified "
    "nearest-way check both agree with reported distances.",
    f"- Sanity: scenario A distance ≤ scenario B distance: {results['sanity_A_le_B']}.",
    "",
]
(OUT / "results.md").write_text("\n".join(md))
print("wrote results.md")

# ------------------------------------------------------- map
def isoline_bands(tag, dmax):
    """Vectorize >=1km, >=2km ... bands from the coarse distance grid."""
    meta = json.loads((OUT / f"dist_{tag}.meta.json").read_text())
    dist = np.load(OUT / f"dist_{tag}.npy")
    t = from_origin(meta["xmin"], meta["ymax"], meta["res"], meta["res"])
    bands = []
    for thr in [1000 * k for k in range(1, min(4, int(dmax // 1000)) + 1)]:
        m = (dist >= thr).astype(np.uint8)
        polys = [shape(g) for g, val in rio_shapes(m, mask=m.astype(bool), transform=t)]
        polys = [p.simplify(40) for p in polys if p.area >= 0.3e6]
        gs = gpd.GeoSeries(polys, crs=CRS).to_crs(4326)
        bands.append((thr, gs))
    del dist
    return bands

def local_roads(s, half_km=6.0):
    lat, lon = s["wgs84"]
    dlat = half_km / 111.32
    dlon = half_km / (111.32 * math.cos(math.radians(lat)))
    bbox = (lon - dlon, lat - dlat, lon + dlon, lat + dlat)
    frames = []
    for f in DATA.glob("*-roads.geojsonl"):
        fields = pyogrio.read_info(f)["fields"]
        cols = [c for c in ("highway", "name") if c in fields]
        try:
            df = pyogrio.read_dataframe(f, columns=cols, bbox=bbox)
        except Exception:
            continue
        if len(df):
            frames.append(df)
    if not frames:
        return None
    df = gpd.GeoDataFrame(__import__("pandas").concat(frames, ignore_index=True))
    df = df[df["highway"].isin(SET_B | {"track"})]
    df.geometry = df.geometry.simplify(0.00005)
    return df

winners = [results["scenarios"][t]["winner"]["wgs84"] for t in ("A", "B")]
center = [sum(w[0] for w in winners) / 2, sum(w[1] for w in winners) / 2]
m = folium.Map(location=center, zoom_start=9, tiles="OpenStreetMap", control_scale=True)
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Esri World Imagery", name="Satellite (Esri)", show=False,
).add_to(m)

for tag, sc in results["scenarios"].items():
    grp = folium.FeatureGroup(name=f"Scenario {tag} bands ({sc['label']})", show=(tag == "A"))
    for i, (thr, gs) in enumerate(isoline_bands(tag, sc["winner"]["distance_m"])):
        color = RAMP[tag][i]
        folium.GeoJson(
            gs.__geo_interface__,
            style_function=lambda f, c=color: {
                "color": c, "weight": 1, "fillColor": c, "fillOpacity": 0.30},
            tooltip=f"≥ {thr/1000:.0f} km from a road (scenario {tag})",
        ).add_to(grp)
    grp.add_to(m)

def popup_html(s, title):
    lat, lon = s["wgs84"]
    r = s["nearest_road"]
    road = f"{r['highway']}" + (f" ({r['surface']})" if r["surface"] else "")
    if r["name"]:
        road += f" “{r['name']}”"
    pa = f"<br>Protected area: {', '.join(s['protected'])}" if s["protected"] else ""
    return (
        f"<b>{title}</b><br>"
        f"<b>{s['distance_m']/1000:.2f} km</b> to the nearest road<br>"
        f"{s['near']}{pa}<br>"
        f"Nearest road: {road}, {r['country']} "
        f"(<a href='{r['url']}' target='_blank'>way</a>)<br>"
        f"{lat:.5f}, {lon:.5f} · "
        f"<a href='{gmaps(s)}' target='_blank'>Google satellite</a>"
    )

for tag, sc in results["scenarios"].items():
    grp = folium.FeatureGroup(name=f"Scenario {tag} spots", show=True)
    w = sc["winner"]
    folium.Marker(
        w["wgs84"], icon=folium.Icon(color=ICON_COLOR[tag], icon="star"),
        popup=folium.Popup(popup_html(w, f"Scenario {tag} winner"), max_width=320),
        tooltip=f"{tag}: {w['distance_m']/1000:.2f} km",
    ).add_to(grp)
    for i, s in enumerate(sc["runners_up"], 2):
        folium.CircleMarker(
            s["wgs84"], radius=7, color=MARKER[tag], fill=True, fill_opacity=0.85,
            popup=folium.Popup(popup_html(s, f"Scenario {tag} · #{i}"), max_width=320),
            tooltip=f"{tag} #{i}: {s['distance_m']/1000:.2f} km",
        ).add_to(grp)
    grp.add_to(m)

roads_grp = folium.FeatureGroup(name="Roads near the winners", show=True)
seen = set()
for tag in ("A", "B"):
    w = results["scenarios"][tag]["winner"]
    key = tuple(np.round(w["wgs84"], 2))
    if key in seen:
        continue
    seen.add(key)
    df = local_roads(w)
    if df is None:
        continue
    for is_track, color, dash in ((False, ROAD_PUBLIC, None), (True, ROAD_TRACK, "4 4")):
        sub = df[(df["highway"] == "track") == is_track]
        if not len(sub):
            continue
        folium.GeoJson(
            sub.geometry.__geo_interface__,
            style_function=lambda f, c=color, d=dash: {
                "color": c, "weight": 1.5, "dashArray": d},
        ).add_to(roads_grp)
roads_grp.add_to(m)

folium.LayerControl(collapsed=False).add_to(m)
m.save(OUT / "map.html")
print("wrote map.html")
