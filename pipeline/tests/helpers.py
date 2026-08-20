"""Write small FlatGeobuf layers from shapely geometries without pandas."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import shapely
from pyogrio.raw import write

_OGR_NAMES = {0: "Point", 1: "LineString", 3: "Polygon", 4: "MultiPoint", 5: "MultiLineString", 6: "MultiPolygon"}


def write_fgb(path: Path, layer: str, geoms, fields: dict[str, list], crs: str = "EPSG:4326",
              geometry_type: str | None = None) -> Path:
    geoms = list(geoms)
    geometry_type = geometry_type or _OGR_NAMES[shapely.get_type_id(geoms[0])]
    arrays = []
    for values in fields.values():
        if all(isinstance(v, (int, np.integer)) for v in values if v is not None) and any(v is not None for v in values):
            arrays.append(np.array(values, dtype=np.int64))
        else:
            arrays.append(np.array(values, dtype=object))
    write(str(path), geometry=np.array([shapely.to_wkb(g) for g in geoms], dtype=object), field_data=arrays,
          fields=list(fields), layer=layer, driver="FlatGeobuf", geometry_type=geometry_type, crs=crs)
    return path
