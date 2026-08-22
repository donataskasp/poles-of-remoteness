import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from poles.classes import EDGE, N_CLASSES, NODATA, ClassTable, default_edges

REPO = Path(__file__).resolve().parents[2]

BREAKPOINTS = [(0, 0), (49, 0), (50, 1), (2499, 49), (2500, 50), (9999, 124), (10000, 125), (29999, 204),
               (30000, 205), (59999, 234), (60000, 235), (239999, 252), (240000, 253), (250000, 253)]
BOUND_CLASSES = [0, 50, 253]

# The mirror check: the same edges, the same breakpoints and the same bounds through the JS module, once for
# the default table and once for a per-region table (the default edges doubled) built with makeClassTable.
NODE_SCRIPT = """
import {{ CLASS_EDGES, EDGE, NODATA, toClass, classLower, classUpper, makeClassTable }} from '{module}';
const dists = {dists};
const classes = {classes};
const doubled = makeClassTable(CLASS_EDGES.map((e) => 2 * e));
const jsonSafe = (v) => (Number.isFinite(v) ? v : 'inf');
const bounds = (lower, upper) => classes.map((c) => [lower(c), jsonSafe(upper(c))]);
const rejects = (edges) => {{
  try {{ makeClassTable(edges); return false; }} catch (err) {{ return err instanceof RangeError; }}
}};
console.log(JSON.stringify({{
  edges: CLASS_EDGES,
  edge: EDGE,
  nodata: NODATA,
  classes: dists.map((d) => toClass(d)),
  bounds: bounds(classLower, classUpper),
  doubledEdges: doubled.edges,
  doubledClasses: dists.map((d) => doubled.toClass(d)),
  doubledBounds: bounds(doubled.lower, doubled.upper),
  rejects: [rejects(CLASS_EDGES.slice(0, 10)), rejects([1, ...CLASS_EDGES.slice(1)]),
            rejects(CLASS_EDGES.map((e, i) => (i === 2 ? 0 : e)))],
}}));
"""


def bounds_of(table):
    """[[lower, upper], ...] for BOUND_CLASSES, with the JSON-safe 'inf' the node script also prints."""
    out = []
    for c in BOUND_CLASSES:
        hi = table.upper(c)
        out.append([table.lower(c), "inf" if math.isinf(hi) else hi])
    return out


def test_default_edges_shape():
    e = default_edges()
    assert len(e) == N_CLASSES == 254
    assert e[0] == 0 and e[-1] == 240000
    assert all(b > a for a, b in zip(e, e[1:]))
    assert EDGE == 254 and NODATA == 255


@pytest.mark.parametrize("dist,expected", BREAKPOINTS)
def test_breakpoints(dist, expected):
    assert int(ClassTable().to_class(dist)) == expected


def test_to_class_is_vectorised_uint8():
    out = ClassTable().to_class(np.array([0.0, 75.0, 250000.0], dtype=np.float32))
    assert out.dtype == np.uint8
    assert out.tolist() == [0, 1, 253]


def test_bounds_and_mid():
    t = ClassTable()
    assert t.lower(50) == 2500 and t.upper(50) == 2600 and t.mid(50) == 2550
    assert t.upper(253) == math.inf and t.lower(253) == 240000
    assert t.mid(0) == 25


def test_custom_edges():
    t = ClassTable([2 * e for e in default_edges()])
    assert int(t.to_class(5000)) == 50
    assert t.lower(50) == 5000 and t.upper(50) == 5200 and t.upper(253) == math.inf


def test_rejects_bad_inputs():
    with pytest.raises(ValueError):
        ClassTable().to_class(-1)
    with pytest.raises(ValueError):
        ClassTable().to_class(float("nan"))
    with pytest.raises(ValueError):
        ClassTable().to_class(np.array([1.0, math.inf]))
    with pytest.raises(ValueError):
        ClassTable([0, 10, 5] + [20 + i for i in range(251)])
    with pytest.raises(ValueError):
        ClassTable(list(range(10)))


def test_rejects_edges_not_starting_at_zero():
    with pytest.raises(ValueError):
        ClassTable([1] + default_edges()[1:])


@pytest.mark.parametrize("call", [lambda t: t.lower(254), lambda t: t.upper(255), lambda t: t.mid(-1),
                                  lambda t: t.lower(EDGE), lambda t: t.upper(NODATA)])
def test_rejects_classes_outside_the_table(call):
    with pytest.raises(ValueError):
        call(ClassTable())


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH; the JS mirror is checked by hand")
def test_js_mirror_matches_python():
    module = (REPO / "site" / "js" / "classes.js").as_uri()
    dists = [d for d, _ in BREAKPOINTS]
    script = NODE_SCRIPT.format(module=module, dists=json.dumps(dists), classes=json.dumps(BOUND_CLASSES))
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
    got = json.loads(out.stdout)
    default = ClassTable()
    doubled = ClassTable([2 * e for e in default_edges()])
    assert got["edges"] == default_edges()
    assert got["edge"] == EDGE and got["nodata"] == NODATA
    assert got["classes"] == [c for _, c in BREAKPOINTS] == default.to_class(dists).tolist()
    assert got["bounds"] == bounds_of(default)
    assert got["doubledEdges"] == doubled.edges
    assert got["doubledClasses"] == doubled.to_class(dists).tolist()
    assert got["doubledBounds"] == bounds_of(doubled)
    assert got["rejects"] == [True, True, True]  # wrong length, first edge not 0, not increasing
