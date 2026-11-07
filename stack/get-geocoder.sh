#!/usr/bin/env bash
# Offline address search: Photon (komoot) + the prebuilt US database dump (GraphHopper).
#   DATA=/srv/prepper ./get-geocoder.sh      # resumable; ~10.6 GB download, ~30+ GB unpacked
set -euo pipefail
DATA=${DATA:?set DATA}; P=$DATA/photon; mkdir -p "$P/.dl"
PHOTON_VER=1.3.0                       # pairs with the "1.0" dump format
U=https://download1.graphhopper.com/public/north-america/usa
F=photon-db-usa-1.0-latest.tar.bz2

[ -f "$P/photon-$PHOTON_VER.jar" ] || curl -fL -o "$P/photon-$PHOTON_VER.jar" \
  "https://github.com/komoot/photon/releases/download/$PHOTON_VER/photon-$PHOTON_VER.jar"

if [ ! -d "$P/photon_data" ]; then
  aria2c -q -c -x8 -s8 -k10M --max-tries=20 --retry-wait=15 -d "$P/.dl" -o "$F" "$U/$F"
  want=$(curl -sL "$U/$F.md5" | cut -d' ' -f1)
  got=$(md5sum "$P/.dl/$F" | cut -d' ' -f1)
  [ "$want" = "$got" ] || { echo "!! md5 mismatch ($got != $want)"; exit 1; }
  echo "md5 ok, unpacking"
  rm -rf "$P/.unpack" && mkdir "$P/.unpack"
  pbzip2 -cd "$P/.dl/$F" | tar x -C "$P/.unpack"
  mv "$P/.unpack/photon_data" "$P/photon_data" && rm -rf "$P/.unpack" "$P/.dl/$F"
fi
echo "ok geocoder ready: $(du -sh "$P/photon_data" | cut -f1)"
