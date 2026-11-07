#!/bin/sh
# Nightly mirror of the prepper box onto a USB drive (/srv/usb/backup). Root cron: /etc/cron.d/prepper-backup.
# Restore: plug the drive into any Linux box, see RESTORE.txt on the drive.
# Live SQLite files (Kolibri, Open WebUI) are copied while running: fine for a spare, not transactional.
set -eu
U=/srv/usb; B=$U/backup
mountpoint -q "$U" || { echo "$U not mounted - skipping"; exit 0; }   # never fill the root disk
# --delete mirrors deletions; refuse if the source looks empty (would wipe the backup).
. /opt/prepper/.env 2>/dev/null || true; D=${DATA:-/srv/prepper}
# Never mirror an empty or unmounted content folder over a good backup (--delete would wipe it).
[ "$(ls "$D"/zim/*.zim 2>/dev/null | wc -l)" -ge 1 ] || { echo "no ZIMs in $D/zim - refusing"; exit 1; }
mkdir -p "$B"
{
  echo "start $(date -Is)"
  rsync -aHAX --delete --exclude /routing.old/ "$D/" "$B/srv-prepper/"
  rsync -aHAX --delete --exclude __pycache__/ /opt/prepper/ "$B/opt-prepper/"
  crontab -u "$(id -un 1000)" -l > "$B/user.crontab" 2>/dev/null || true
  cp /etc/fstab /etc/cron.d/prepper-backup "$B/" 2>/dev/null || true
  cp /opt/prepper/RESTORE.txt "$U/RESTORE.txt" 2>/dev/null || true
  echo "done  $(date -Is)"
} > "$B/last-run.log.tmp" 2>&1 && mv "$B/last-run.log.tmp" "$B/last-run.log"
