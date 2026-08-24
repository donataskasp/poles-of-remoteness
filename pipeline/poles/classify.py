"""Stage classify: scenario membership from highway tags (spec 2.3), applied to highways.vrt with ogr2ogr.

The input is the extract stage's VRT handle, not a FlatGeobuf: above MERGE_MAX_FEATURES the layer lives
as unindexed chunks behind that VRT, and OGRSQL runs over the union either way. The outputs carry no
spatial index either (issue #16): Europe's 101,461,002 highways merged into a FlatGeobuf with a 4.33 GB
packed R-tree that GDAL 3.13 refused to read back, failing on the first feature with "Invalid size
detected: feature", while 4 M feature files read perfectly. Nothing in stage 1 needs the index anyway,
since the grid stage rasterises these layers in one full pass.
"""
from __future__ import annotations

import logging

from pyogrio import read_info

from .config import RegionConfig
from .shell import require_tools, run_cmd
from .workspace import Workspace

STAGE = "classify"

_BASE = ("motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
         "living_street", "service", "road", "busway")
_LINKS = ("motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link")
SET_B: frozenset[str] = frozenset(_BASE + _LINKS)
SET_A: frozenset[str] = SET_B | {"track"}
# Listed for documentation and tests; anything outside SET_A is excluded regardless of other tags.
EXCLUDED: frozenset[str] = frozenset(("path", "footway", "cycleway", "bridleway", "steps", "pedestrian", "corridor",
                                      "proposed", "construction", "abandoned", "razed", "platform", "raceway",
                                      "bus_guideway", "escape", "elevator"))


def classify_highway(tags: dict[str, str]) -> tuple[bool, bool]:
    """(in_a, in_b). Physical drivability only: access tags are ignored; ice and winter roads count when their
    highway value is in the set; a way without a highway tag is in neither."""
    hw = tags.get("highway")
    if hw is None:
        return (False, False)
    return (hw in SET_A, hw in SET_B)


def where_clause(scenario: str) -> str:
    members = {"A": SET_A, "B": SET_B}[scenario]
    return "highway IN (" + ", ".join(f"'{h}'" for h in sorted(members)) + ")"


def run(cfg: RegionConfig, ws: Workspace, log: logging.Logger) -> dict:
    require_tools(["ogr2ogr"])
    src = ws.dir("extract") / "highways.vrt"
    out_dir = ws.dir(STAGE)
    counts: dict[str, int] = {}
    for scenario in ("A", "B"):
        out = out_dir / f"roads_{scenario}.fgb"
        out.unlink(missing_ok=True)
        sql = f"SELECT osm_id AS way_id, highway, name, ref FROM highways WHERE {where_clause(scenario)}"
        run_cmd(["ogr2ogr", "-f", "FlatGeobuf", out, src, "-sql", sql, "-nln", f"roads_{scenario}",
                 "-lco", "SPATIAL_INDEX=NO"], log, stderr_path=out_dir / "tools.log")
        # force_feature_count: an unindexed layer that ends up empty reports -1 otherwise.
        counts[f"roads_{scenario}"] = int(read_info(str(out), force_feature_count=True)["features"])
        log.info("roads_%s: %d ways", scenario, counts[f"roads_{scenario}"])
    if counts["roads_B"] > counts["roads_A"]:
        raise RuntimeError(f"B has more ways than A ({counts}); the tag sets are broken")
    return counts
