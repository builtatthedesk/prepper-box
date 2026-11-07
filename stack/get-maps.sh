#!/usr/bin/env bash
# Offline map tiles cut from the Protomaps daily planet build (OpenStreetMap data).
#   DATA=/srv/prepper ./get-maps.sh
# world.pmtiles: whole planet, country and city level (zoom 0-7), ~190 MB.
# usa.pmtiles:   full street detail for BBOX. Default = continental US + southern Canada, ~19 GB.
#   BBOX=-80,40.4,-71.8,45.1 DATA=/srv/prepper ./get-maps.sh   # a smaller area (minlon,minlat,maxlon,maxlat)
# (The detail file is called usa.pmtiles whatever area it covers; the map page looks for that name.)
# Skips a file that's already there; delete it to fetch a fresh one.
set -euo pipefail
DATA=${DATA:?set DATA}; M=$DATA/maps; mkdir -p "$M"
BBOX=${BBOX:--125,24,-66.5,50}
B=$(curl -fsSL https://build-metadata.protomaps.dev/builds.json | grep -oE '"key":"[0-9]{8}\.pmtiles"' | tail -1 | cut -d'"' -f4)
[ -n "$B" ] || { echo "couldn't find the latest Protomaps build"; exit 1; }
SRC=https://build.protomaps.com/$B
echo "Protomaps build $B"
if [ ! -s "$M/world.pmtiles" ]; then
  pmtiles extract "$SRC" "$M/.world.pmtiles" --maxzoom=7 --download-threads=8 && mv "$M/.world.pmtiles" "$M/world.pmtiles"
fi
if [ ! -s "$M/usa.pmtiles" ]; then
  pmtiles extract "$SRC" "$M/.usa.pmtiles" --bbox="$BBOX" --download-threads=8 && mv "$M/.usa.pmtiles" "$M/usa.pmtiles"
fi
ls -lh "$M"
