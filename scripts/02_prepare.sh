#!/bin/bash
# Prepare vector layers from the raw PBF extracts:
#   1. Lithuania admin_level=2 boundary -> 20 km buffer polygon (clip mask)
#   2. Per-country: clip to buffer, filter highway=* ways, export GeoJSONSeq
#   3. Water polygons (natural=water) from the clipped Lithuania extract
#   4. Coastline lines from the UNCLIPPED LT/LV/Kaliningrad extracts
#      (unclipped so the sea/lagoon faces polygonize cleanly across borders)
set -euo pipefail
BASE="$(cd "$(dirname "$0")/.." && pwd)"
DATA="$BASE/data"
PY="$BASE/.venv/bin/python"
CFG="$BASE/scripts/export-config.json"
cd "$DATA"

echo "== boundary =="
if [ ! -s buffer.geojson ]; then
  osmium tags-filter -O lithuania-latest.osm.pbf r/admin_level=2 -o adm2.pbf
  osmium export -O adm2.pbf -c "$CFG" --geometry-types=polygon -o adm2.geojson
  "$PY" "$BASE/scripts/make_buffer.py" adm2.geojson buffer.geojson
fi

echo "== roads per country =="
declare -a names=(lithuania latvia belarus podlaskie warminsko-mazurskie kaliningrad)
for n in "${names[@]}"; do
  [ -s "$n-roads.geojsonl" ] && { echo "have $n-roads"; continue; }
  echo "-- $n"
  osmium extract -O -p buffer.geojson "$n-latest.osm.pbf" -o "$n-clip.pbf"
  osmium tags-filter -O "$n-clip.pbf" w/highway -o "$n-hw.pbf"
  osmium export -O "$n-hw.pbf" -c "$CFG" --geometry-types=linestring \
    -o "$n-roads.geojsonl" -f geojsonseq
done

echo "== water (from clipped LT) =="
if [ ! -s water.geojsonl ]; then
  osmium tags-filter -O lithuania-clip.pbf wr/natural=water -o water.pbf
  osmium export -O water.pbf -c "$CFG" --geometry-types=polygon \
    -o water.geojsonl -f geojsonseq
fi

echo "== coastline (unclipped sources) =="
if [ ! -s coastline.geojsonl ]; then
  for n in lithuania latvia kaliningrad; do
    osmium tags-filter -O "$n-latest.osm.pbf" w/natural=coastline -o "$n-coast.pbf"
  done
  osmium merge -O lithuania-coast.pbf latvia-coast.pbf kaliningrad-coast.pbf -o coast.pbf
  osmium export -O coast.pbf --geometry-types=linestring -o coastline.geojsonl -f geojsonseq
fi

echo "prepare done"
ls -lh "$DATA"/*.geojsonl
