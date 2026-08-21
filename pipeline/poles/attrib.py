"""Attribution of a refined pole: nearest way with its country, nearest settlement (spec 3.2 stage 5)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import shapely
from pyogrio.raw import read
from pyproj import Geod
from shapely.strtree import STRtree

from .boundaries import AdminArea
from .refine import RefinedPole, UtmRoads

GEOD = Geod(ellps="WGS84")


def clean_text(value) -> str | None:
    """OGR nulls arrive as None or as a float nan depending on the field's dtype; both mean absent."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return str(value)


class Places:
    """Every place node of the extract in memory, for the nearest-settlement lookup of a pole.

    The whole layer is loaded once (1.8 M points over a continent, about 300 MB on disk) because a pole
    lands anywhere and the lookup runs a few hundred times per run; a per-lookup bbox read would reopen
    the file every time. The candidate shortlist is planar with a cosine scale so it is a cheap array
    operation, and only the shortlist is measured geodesically, which is what the published number is.
    """

    def __init__(self, path: Path, layer: str = "places"):
        meta, _, wkb, fields = read(str(path), layer=layer, columns=["name", "name:en", "place"])
        by = dict(zip(meta["fields"], fields))
        pts = shapely.from_wkb(wkb)
        self.lon = shapely.get_x(pts)
        self.lat = shapely.get_y(pts)
        self.name = np.where(np.asarray(by["name:en"], dtype=object) != None, by["name:en"], by["name"])  # noqa: E711
        self.kind = np.asarray(by["place"], dtype=object)

    def nearest(self, lon: float, lat: float, k: int = 64) -> dict | None:
        if len(self.lon) == 0:
            return None
        scale = np.cos(np.radians(lat))
        planar = ((self.lon - lon) * scale) ** 2 + (self.lat - lat) ** 2
        idx = np.argpartition(planar, min(k, len(planar) - 1))[:k]
        _, _, dist = GEOD.inv(np.full(len(idx), lon), np.full(len(idx), lat), self.lon[idx], self.lat[idx])
        j = idx[int(np.argmin(dist))]
        return {"name": self.name[j], "type": str(self.kind[j]), "dist_m": round(float(dist.min()), 1),
                "lat": round(float(self.lat[j]), 6), "lon": round(float(self.lon[j]), 6)}


class Countries:
    """Every level-2 area with a country code, units and non-units alike, for point-in-country lookups.

    A pole near a border can have its nearest way on the other side, and a country that supplies roads
    but no unit still has to name itself, so this is built from all the areas, not from the unit list.
    """

    def __init__(self, areas: list[AdminArea]):
        self.areas = [a for a in areas if a.level == 2 and a.code]
        self.tree = STRtree([a.geometry for a in self.areas]) if self.areas else None

    def code_at(self, lon: float, lat: float) -> str | None:
        if self.tree is None:
            return None
        p = shapely.Point(lon, lat)
        for i in self.tree.query(p, predicate="intersects"):
            return self.areas[int(i)].code.lower()
        return None


def nearest_way(roads: UtmRoads, pole: RefinedPole, countries: Countries) -> dict:
    """Tags of the way the refinement measured against, plus the country of its nearest point to the pole."""
    attrs = roads.roads.attrs
    i = pole.way_index
    way_utm = roads.geoms[i]
    on_way = shapely.shortest_line(way_utm, shapely.Point(pole.x, pole.y)).coords[0]
    lon, lat = roads.to_lonlat.transform(on_way[0], on_way[1])
    return {"id": int(attrs["osm_id"][i]), "highway": clean_text(attrs["highway"][i]), "name": clean_text(attrs["name"][i]),
            "ref": clean_text(attrs["ref"][i]), "country": countries.code_at(lon, lat)}


def pole_record(rank: int, pole: RefinedPole, way: dict, place: dict | None) -> dict:
    """One published pole. `detail` and `warnings` are filled by later stages, never here."""
    return {"rank": rank, "lat": round(pole.lat, 6), "lon": round(pole.lon, 6), "dist_m": round(pole.dist_m, 2),
            "nearest_way": way, "nearest_place": place, "detail": None, "warnings": []}
