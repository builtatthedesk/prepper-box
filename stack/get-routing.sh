#!/usr/bin/env bash
# Build the offline driving-directions tiles (Valhalla) OFF the prepper box, then copy them over.
# The box (8 GB RAM, 2 cores) only serves them; building needs real RAM and CPU.
#
# Run on any Docker host with ~16 GB RAM free and osmium-tool (e.g. a spare PC or a throwaway VM):
#   ./get-routing.sh /build/v2
#   cd /build/v2 && tar -cf - valhalla_tiles.tar valhalla.json admins.sqlite timezones.sqlite \
#       default_speeds.json file_hashes.txt | ssh you@prepper.local 'tar -xf - -C /srv/prepper/routing'
# then on the box: docker compose up -d routing landing   (compare sha256 of valhalla_tiles.tar first)
#
# The state extracts MUST be merged (osmium) into one file first. Fed separately, Valhalla imports the
# roads where they overlap at state lines twice, and routes there sprout dozens of bogus
# "Keep straight at the fork" steps.
#
# The image digest MUST match the `routing` service in docker-compose.yml: tiles are only
# guaranteed readable by the Valhalla version that built them. Change both together.
set -euo pipefail
OUT=${1:?usage: get-routing.sh <output dir>}
IMAGE=ghcr.io/valhalla/valhalla-scripted@sha256:e2078b638205fba6ef246d8ae731d7f197b346a0ebc74fb5f41b01db50504c90
G=https://download.geofabrik.de/north-america/us
STATES=${STATES:-"rhode-island"}   # Geofabrik US state names, space-separated

mkdir -p "$OUT" "$OUT.src"   # extracts live beside OUT so the builder sees only the merged file
SRCS=()
for s in $STATES; do   # always fresh: the -latest files change daily, so never resume or reuse one
  curl -fL -o "$OUT.src/$s.osm.pbf.part" "$G/$s-latest.osm.pbf"
  mv "$OUT.src/$s.osm.pbf.part" "$OUT.src/$s.osm.pbf"; SRCS+=("$OUT.src/$s.osm.pbf")
done
osmium merge "${SRCS[@]}" -o "$OUT/region.osm.pbf" --overwrite   # one copy of every border road
docker run --rm --name vbuild -v "$OUT":/custom_files \
  -e force_rebuild=True -e use_tiles_ignore_pbf=False \
  -e serve_tiles=False -e build_tar=True -e build_admins=True -e build_time_zones=True \
  -e build_elevation=False -e server_threads="$(nproc)" "$IMAGE"
# Tile cache is per worker and defaults to 1 GB; the box has 8 GB shared with Ollama/Photon/Kiwix.
sed -i 's/"max_cache_size": *[0-9]*/"max_cache_size": 250000000/' "$OUT/valhalla.json"
ls -la "$OUT"
