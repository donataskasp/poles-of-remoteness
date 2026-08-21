"""Admin areas from `boundaries.pbf`, assembled from whatever members the extract holds (issue #15).

osmium's area assembler (and therefore stage 1's `osmium export`) drops a relation as soon as one member
is missing, which loses every country with territory outside the extract: Spain (Canaries), France
(overseas), the Netherlands (Caribbean), Norway (Bouvet), Russia and Iran (cut by the edge). Here the
present outer ways are merged into rings; closed rings become polygons with the inner rings they
contain as holes; an open line (a ring cut by the data edge) is closed along the edge polygon and only
the faces holding the relation's admin_centre or label node are kept, which is how Russia west of the
Volga becomes a polygon for nearest-way attribution. Relations are read as OPL, way geometries through
`osmium export -n`, seed nodes through `osmium getid`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import shapely
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, polygonize, unary_union

from . import opl
from .osmium import osmium
from .shell import ToolError

ACCEPTED_TYPES = ("boundary", "multipolygon")
SEED_ROLES = ("admin_centre", "label")
OUTER_ROLES = ("outer", "")


@dataclass
class Relation:
    id: int
    tags: dict[str, str]
    members: list[tuple[str, int, str]]


@dataclass
class AdminArea:
    osm_id: int
    level: int
    code: str | None
    name: str | None
    name_en: str | None
    geometry: MultiPolygon
    complete: bool
    closed_by_edge: bool


def _osmium_tolerant(args: list, out: Path, log: logging.Logger, stderr_path: Path) -> None:
    """Run osmium, tolerating only the exit 1 that `getid` returns when a requested id is missing.

    Measured on osmium 1.19.1: a missing id exits 1, prints nothing and still writes everything it
    found, while a hard failure such as an unreadable input also exits 1, prints one error line and
    leaves an empty output file behind. Neither the exit code nor the output's existence separates the
    two, so what this invocation appended to the tool log decides: anything osmium printed re-raises.
    `out` is removed first, because work dirs persist across runs and a stale file from an earlier run
    must never be read back as this run's result.
    """
    out.unlink(missing_ok=True)
    before = stderr_path.stat().st_size if stderr_path.exists() else 0
    try:
        osmium(args, log, stderr_path=stderr_path)
    except ToolError as e:
        with open(stderr_path, "rb") as f:  # run_cmd echoes "$ <command>" before the command's own output
            f.seek(before)
            printed = [ln for ln in f.read().decode("utf-8", "replace").splitlines()
                       if ln.strip() and not ln.startswith("$ ")]
        if "command failed with exit 1:" not in str(e) or printed or not out.exists():
            raise


def read_relations(pbf: Path, levels: set[int], work: Path, log: logging.Logger) -> list[Relation]:
    """Administrative boundary relations at the wanted levels, as ids, tags and members."""
    work.mkdir(parents=True, exist_ok=True)
    out = work / "relations.opl"
    filters = [f"r/admin_level={level}" for level in sorted(levels)]
    osmium(["tags-filter", "--overwrite", "--omit-referenced", "-f", "opl", "-o", out, pbf, *filters], log,
           stderr_path=work / "tools.log")
    wanted = {str(level) for level in levels}
    rels: list[Relation] = []
    for line in out.read_text(encoding="utf-8").splitlines():
        if not line.startswith("r"):
            continue
        fields = line.split(" ")
        rid = int(fields[0][1:])
        tags = members = None
        for f in fields[1:]:
            if f.startswith("T"):
                tags = opl.parse_tags(f[1:])
            elif f.startswith("M"):
                members = opl.parse_members(f[1:])
        tags, members = tags or {}, members or []
        if tags.get("boundary") != "administrative" or tags.get("type") not in ACCEPTED_TYPES:
            continue
        if tags.get("admin_level") not in wanted:
            continue
        rels.append(Relation(rid, tags, members))
    return rels


def way_geometries(pbf: Path, way_ids: set[int], work: Path, log: logging.Logger) -> dict[int, LineString]:
    """Linestrings for the requested way ids that exist in the file (untagged ways included)."""
    if not way_ids:
        return {}
    work.mkdir(parents=True, exist_ok=True)
    cfg = work / "export-ways.json"
    cfg.write_text(json.dumps({"attributes": {"type": "@type", "id": "@id"}, "linear_tags": True, "area_tags": False}),
                   encoding="utf-8")
    seq = work / "ways.geojsonseq"
    osmium(["export", "--overwrite", "-n", "-f", "geojsonseq", "-c", cfg, "--geometry-types=linestring", "-o", seq, pbf],
           log, stderr_path=work / "tools.log")
    ways: dict[int, LineString] = {}
    with open(seq, encoding="utf-8") as f:
        for line in f:
            line = line.lstrip("\x1e").strip()
            if not line:
                continue
            feature = json.loads(line)
            props = feature["properties"]
            if props["@type"] != "way":  # ids are only unique per type, so never trust the flag alone
                continue
            wid = int(props["@id"])
            if wid in way_ids:
                ways[wid] = shapely.from_geojson(json.dumps(feature["geometry"]))
    seq.unlink(missing_ok=True)
    return ways


def seed_points(pbf: Path, node_ids: set[int], work: Path, log: logging.Logger) -> dict[int, Point]:
    """Positions of the requested node ids that exist in the file; missing ids are simply absent."""
    if not node_ids:
        return {}
    work.mkdir(parents=True, exist_ok=True)
    out = work / "seeds.opl"
    _osmium_tolerant(["getid", "--overwrite", "-f", "opl", "-o", out, pbf, *(f"n{n}" for n in sorted(node_ids))],
                     out, log, work / "tools.log")
    seeds: dict[int, Point] = {}
    for line in out.read_text(encoding="utf-8").splitlines():
        if not line.startswith("n"):
            continue
        fields = line.split(" ")
        x = y = None
        for f in fields[1:]:
            if f.startswith("x"):
                x = float(f[1:])
            elif f.startswith("y"):
                y = float(f[1:])
        if x is not None and y is not None:
            seeds[int(fields[0][1:])] = Point(x, y)
    return seeds


def _rings_and_open(lines: list[LineString]) -> tuple[list[Polygon], list[LineString]]:
    """Merge the lines end to end, then split the result into closed rings and leftover open lines."""
    if not lines:
        return [], []
    merged = linemerge(lines) if len(lines) > 1 else lines[0]
    parts = list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]
    rings = [Polygon(p.coords) for p in parts if p.is_ring and len(p.coords) >= 4]
    return rings, [p for p in parts if not p.is_ring]


def _member_lines(rel: Relation, ways: dict[int, LineString], roles: tuple[str, ...]) -> list[LineString]:
    return [ways[ref] for kind, ref, role in rel.members if kind == "w" and role in roles and ref in ways]


def _assemble(rel: Relation, ways: dict[int, LineString], seeds: dict[int, Point],
              edge: BaseGeometry | None) -> tuple[MultiPolygon | None, bool]:
    """The polygons of the relation plus whether any of them was closed along the data edge."""
    outers, open_lines = _rings_and_open(_member_lines(rel, ways, OUTER_ROLES))
    inners, _ = _rings_and_open(_member_lines(rel, ways, ("inner",)))
    polys: list[Polygon] = []
    for shell in outers:
        holes = [h for h in inners if shell.contains(h.representative_point())]
        polys.append(Polygon(shell.exterior.coords, [h.exterior.coords for h in holes]) if holes else shell)
    closed_by_edge = False
    if open_lines and edge is not None:
        seed_pts = [seeds[ref] for kind, ref, role in rel.members if kind == "n" and role in SEED_ROLES and ref in seeds]
        if seed_pts:
            noded = unary_union([*open_lines, edge.boundary])
            for face in polygonize(noded):
                if any(face.contains(s) for s in seed_pts):
                    polys.append(face)
                    closed_by_edge = True
    if not polys:
        return None, False
    geom = shapely.make_valid(unary_union(polys))
    if geom.geom_type == "Polygon":
        geom = MultiPolygon([geom])
    elif geom.geom_type == "GeometryCollection":
        geom = MultiPolygon([g for g in geom.geoms if g.geom_type == "Polygon"] +
                            [p for g in geom.geoms if g.geom_type == "MultiPolygon" for p in g.geoms])
    if geom.is_empty or geom.geom_type != "MultiPolygon":
        return None, False
    return geom, closed_by_edge


def assemble(rel: Relation, ways: dict[int, LineString], seeds: dict[int, Point],
             edge: BaseGeometry | None) -> MultiPolygon | None:
    """Polygons from the members present in `ways`, or None when they yield no area at all."""
    return _assemble(rel, ways, seeds, edge)[0]


def assemble_area(rel: Relation, ways: dict[int, LineString], seeds: dict[int, Point], edge: BaseGeometry | None,
                  code_tag: str) -> AdminArea | None:
    geom, closed_by_edge = _assemble(rel, ways, seeds, edge)
    if geom is None:
        return None
    # Way members only: a missing sub-relation or seed node says nothing about the outline's completeness.
    complete = all(ref in ways for kind, ref, _ in rel.members if kind == "w")
    return AdminArea(rel.id, int(rel.tags["admin_level"]), rel.tags.get(code_tag) or None, rel.tags.get("name"),
                     rel.tags.get("name:en") or rel.tags.get("name"), geom, complete, closed_by_edge)


def load_admin_areas(pbf: Path, levels: set[int], edge: BaseGeometry | None, work: Path, log: logging.Logger,
                     code_tags: dict[int, str]) -> list[AdminArea]:
    rels = read_relations(pbf, levels, work, log)
    way_ids = {ref for r in rels for kind, ref, _ in r.members if kind == "w"}
    node_ids = {ref for r in rels for kind, ref, role in r.members if kind == "n" and role in SEED_ROLES}
    ways = way_geometries(pbf, way_ids, work, log)
    seeds = seed_points(pbf, node_ids, work, log)
    log.info("boundaries: %d relations, %d of %d member ways present, %d seed nodes", len(rels), len(ways), len(way_ids), len(seeds))
    areas = []
    for rel in rels:
        # A level the caller did not map falls back to the country code tag, as the stage spec asks.
        area = assemble_area(rel, ways, seeds, edge, code_tags.get(int(rel.tags["admin_level"]), "ISO3166-1"))
        if area is None:
            log.warning("boundaries: relation %d (%s) yields no polygon from the present members", rel.id, rel.tags.get("name"))
            continue
        areas.append(area)
    return areas
