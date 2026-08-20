from poles.poly import parse_poly

SAMPLE = """europe
1
   0.0   0.0
   4.0   0.0
   4.0   4.0
   0.0   4.0
   0.0   0.0
END
!hole
   1.0   1.0
   2.0   1.0
   2.0   2.0
   1.0   2.0
   1.0   1.0
END
2
   10.0  10.0
   11.0  10.0
   11.0  11.0
   10.0  11.0
   10.0  10.0
END
END
"""


def test_parse_poly_with_hole_and_two_parts(tmp_path):
    p = tmp_path / "s.poly"
    p.write_text(SAMPLE)
    geom = parse_poly(p)
    assert abs(geom.area - (16 - 1 + 1)) < 1e-9
    assert geom.bounds == (0.0, 0.0, 11.0, 11.0)
    assert not geom.contains(__import__("shapely").Point(1.5, 1.5))
