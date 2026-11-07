#!/usr/bin/env bash
# Import Kolibri channels into the running kolibri container (resumable; re-run any time).
#   cd /opt/prepper && kolibri/import-channels.sh 2>&1 | tee -a /srv/prepper/kolibri-import.log
# Sizes as published on Kolibri Studio, 2026-11-03.
cd /opt/prepper
. ./.env 2>/dev/null || true
CHANNELS=(
  "197934f144305350b5820c7c4dd8e194  PhET Interactive Simulations (1.1 GB)"
  "1d8f6d84618153c18c695d85074952a7  CK-12 (6.7 GB)"
  "fc47aee82e0153e2a30197d3fdee1128  OpenStax (2.1 GB)"
  "d288129b13ce437f9e5150ad72d7b476  BCcampus Open Textbooks (1.2 GB)"
  "8b28761bac075deeb66adc6c80ef119c  Osmosis.org (5.2 GB)"
  "e409b964366a59219c148f2aaa741f43  Blockly Games (0.3 GB)"
  "b62c5c2139a65fb2aaf68987a25b28a1  Goalkicker Tech Books (0.5 GB)"
  "7ec3b2ad48925d639592954e2298618f  HP LIFE Courses (0.8 GB)"
  "3e464ee12f6a50a781cddf59147b48b1  Sikana English (15.8 GB)"
  "d6e3b856125f5e6aa5fb40c8b112d5e9  EngageNY (7.8 GB)"
  "c9d7f950ab6b5a1199e3d6c10d7f0103  Khan Academy US curriculum (67.8 GB)"
)
for row in "${CHANNELS[@]}"; do
  id=${row%% *}; name=${row#*  }
  echo "=== $(date -Is) $name"
  docker compose exec -T kolibri kolibri manage importchannel network "$id" \
    && docker compose exec -T kolibri kolibri manage importcontent network "$id" \
    && echo "ok $name" || echo "!! failed $name"
  echo "free: $(df -h --output=avail "${DATA:-/srv/prepper}" | tail -1)"
done
echo "=== $(date -Is) all done"
