#!/bin/bash
# Download OSM extracts for the Lithuania pole-of-remoteness computation.
# Sources: Geofabrik daily extracts. Poland is covered by its two border
# voivodeships (Podlaskie, Warmian-Masurian) instead of the full country.
set -euo pipefail
DATA="$(cd "$(dirname "$0")/../data" && pwd)"

urls=(
  "https://download.geofabrik.de/europe/lithuania-latest.osm.pbf"
  "https://download.geofabrik.de/europe/latvia-latest.osm.pbf"
  "https://download.geofabrik.de/europe/belarus-latest.osm.pbf"
  "https://download.geofabrik.de/europe/poland/podlaskie-latest.osm.pbf"
  "https://download.geofabrik.de/europe/poland/warminsko-mazurskie-latest.osm.pbf"
  "https://download.geofabrik.de/russia/kaliningrad-latest.osm.pbf"
)

for u in "${urls[@]}"; do
  f="$DATA/$(basename "$u")"
  if [ -s "$f" ]; then echo "have $(basename "$f")"; continue; fi
  echo "downloading $(basename "$f")"
  curl -sSL --fail --retry 3 -o "$f.part" "$u" && mv "$f.part" "$f"
done
date -u +"%Y-%m-%dT%H:%MZ" > "$DATA/snapshot-date.txt"
echo "all downloads done"
