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


def test_rejects_bad_inputs():
    with pytest.raises(ValueError):
        ClassTable().to_class(-1)
    with pytest.raises(ValueError):
        ClassTable([0, 10, 5] + [20 + i for i in range(251)])
    with pytest.raises(ValueError):
        ClassTable(list(range(10)))


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH; the JS mirror is checked by hand")
def test_js_mirror_matches_python():
    module = (REPO / "site" / "js" / "classes.js").as_uri()
    script = (f"import {{CLASS_EDGES, EDGE, NODATA, toClass}} from '{module}';"
              f"console.log(JSON.stringify({{edges: CLASS_EDGES, edge: EDGE, nodata: NODATA,"
              f" classes: {json.dumps([d for d, _ in BREAKPOINTS])}.map(toClass)}}))")
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
    got = json.loads(out.stdout)
    assert got["edges"] == default_edges()
    assert got["edge"] == EDGE and got["nodata"] == NODATA
    assert got["classes"] == [c for _, c in BREAKPOINTS]
