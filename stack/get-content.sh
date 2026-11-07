#!/usr/bin/env bash
# Download the offline library into $DATA/zim, sized to the free space on $DATA.
#   DATA=/srv/prepper ./get-content.sh          # resumable; re-run any time
# Tier 1 (always, ~15 GB): medicine, repair, water/food/shelter, travel, practical Q&A.
# Tier 2 (biggest Wikipedia that fits, leaving 20 GB spare): maxi 119G > nopic 49G > mini 13G.
# Tier 3 (only if lots of room left): Wiktionary, Electronics SE, Gutenberg (206G), Khan Academy (180G),
# Crash Course (23G), TED-Ed (6G).
set -uo pipefail
DATA=${DATA:?set DATA}; Z=$DATA/zim; mkdir -p "$Z/.dl"
B=https://download.kiwix.org/zim
SPARE=$((20*1024**3))

latest() {  # latest <dir> <prefix>  -> file name of the newest dated ZIM
  curl -sL "$B/$1/" | grep -oE "href=\"$2_[0-9]{4}-[0-9]{2}\.zim\"" | cut -d'"' -f2 | sort | tail -1
}
size_of() { curl -sIL "$B/$1/$2" | awk 'tolower($1)=="content-length:"{v=$2} END{print v+0}' | tr -d '\r'; }
free_b() { df -B1 --output=avail "$DATA" | tail -1; }

get() {  # get <dir> <prefix>
  local f; f=$(latest "$1" "$2")
  [ -n "$f" ] || { echo "!! no file for $1/$2"; return 1; }
  ls "$Z"/"$2"_*.zim >/dev/null 2>&1 && { echo "== have $2 ($(ls "$Z"/"$2"_*.zim | xargs -n1 basename))"; return 0; }
  local sz; sz=$(size_of "$1" "$f")
  if [ "$sz" -gt $(( $(free_b) - SPARE )) ]; then echo "-- skip $f ($((sz/1024**3)) GB, not enough room)"; return 2; fi
  echo ">> $f ($((sz/1024**2)) MB)"
  # aria2c follows Kiwix's metalink (several mirrors, 8 connections); single-stream curl
  # capped at ~2.6 MB/s. Downloads land in $Z/.dl (aria2 preallocates the full size, so
  # Kiwix must not see them) and move into $Z only once complete. Resumable.
  aria2c -q -c -x8 -s8 -k10M --follow-metalink=mem --max-tries=20 --retry-wait=15 \
    --auto-file-renaming=false --summary-interval=0 -d "$Z/.dl" "$B/$1/$f" \
    && [ -f "$Z/.dl/$f" ] && ! [ -f "$Z/.dl/$f.aria2" ] || { echo "!! download failed: $f"; return 1; }
  # Only a checksum-verified file enters the library.
  local want; want=$(curl -sL "$B/$1/$f.sha256" | grep -oE '^[0-9a-f]{64}')
  if [ -n "$want" ] && [ "$(sha256sum "$Z/.dl/$f" | cut -d' ' -f1)" != "$want" ]; then
    echo "!! sha256 mismatch, deleting: $f"; rm -f "$Z/.dl/$f"; return 1
  fi
  mv "$Z/.dl/$f" "$Z/$f" && echo "ok $f"
}

T1=(
  "other mdwiki_en_all_maxi"                     # WikiProject Medicine (offline medical encyclopedia)
  "wikipedia wikipedia_en_medicine_maxi"
  "other zimgit-post-disaster_en"
  "other zimgit-water_en"
  "other zimgit-food-preparation_en"
  "other zimgit-medicine_en"
  "other zimgit-knots_en"
  "other energypedia_en_all_maxi"
  "ifixit ifixit_en_all"
  "wikivoyage wikivoyage_en_all_maxi"
  "stack_exchange diy.stackexchange.com_en_all"
  "stack_exchange outdoors.stackexchange.com_en_all"
  "stack_exchange cooking.stackexchange.com_en_all"
  "stack_exchange gardening.stackexchange.com_en_all"
  "stack_exchange ham.stackexchange.com_en_all"
  "stack_exchange mechanics.stackexchange.com_en_all"
  "stack_exchange sustainability.stackexchange.com_en_all"
  "wikibooks wikibooks_en_all_maxi"
  "other gardenology.org_en_all"                 # plant encyclopedia, ~107 MB
)
for p in "${T1[@]}"; do get $p; done

# Tier 2: one Wikipedia, the biggest that fits
if ! ls "$Z"/wikipedia_en_all_*.zim >/dev/null 2>&1; then
  get wikipedia wikipedia_en_all_maxi || get wikipedia wikipedia_en_all_nopic || get wikipedia wikipedia_en_all_mini
fi

T3=(
  "wiktionary wiktionary_en_all_nopic"
  "stack_exchange electronics.stackexchange.com_en_all"
  "gutenberg gutenberg_en_all"
  "other khanacademy_en_all"                      # Khan Academy w/ videos, ~180 GB
  "other crashcourse_en_all"                      # Crash Course video lessons, ~23 GB
  "ted ted_mul_ted-ed"                            # TED-Ed short animated lessons, ~6 GB
)
for p in "${T3[@]}"; do get $p; done
echo "done. $(ls "$Z"/*.zim 2>/dev/null | wc -l) ZIMs, $(du -sh "$Z" | cut -f1); free $(( $(free_b)/1024**3 )) GB"
