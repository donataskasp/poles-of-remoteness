"""Build the 20 km buffered Lithuania polygon (WGS84 GeoJSON) used by
`osmium extract` to clip the country PBFs. Reads the admin_level=2 boundary
exported from the Lithuania extract by 02_prepare.sh."""
import json
import sys

import geopandas as gpd

src, dst = sys.argv[1], sys.argv[2]

gdf = gpd.read_file(src)
lt = gdf[
    (gdf.get("boundary") == "administrative")
    & (gdf.get("admin_level") == "2")
    & (gdf.get("ISO3166-1") == "LT")
]
assert len(lt) == 1, f"expected exactly one LT admin_level=2 area, got {len(lt)}"

geom = lt.to_crs(3346).geometry.iloc[0]
area_km2 = geom.area / 1e6
# admin polygon includes territorial sea, so it is larger than the 65.3k land figure
assert 60_000 < area_km2 < 80_000, f"implausible LT admin area: {area_km2:.0f} km2"

buffered = geom.buffer(20_000).simplify(100)
out = gpd.GeoSeries([buffered], crs=3346).to_crs(4326)
out.to_file(dst, driver="GeoJSON")

# keep the unbuffered boundary for the compute step
lt.to_crs(3346).to_file(dst.replace("buffer.geojson", "lt-admin.gpkg"), driver="GPKG")
print(f"LT admin area {area_km2:.0f} km2 (incl. territorial waters); buffer written")
