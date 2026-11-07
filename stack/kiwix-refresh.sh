#!/bin/sh
# Restart Kiwix when the set of finished ZIMs changes (cron, every 10 min).
. /opt/prepper/.env 2>/dev/null || true; D=${DATA:-/srv/prepper}
Z=$D/zim; X=/srv/usb/extra/zim; S=$D/.zimlist
# names AND mtimes (a rebuilt ZIM keeps its name); X also changes when the USB drive is (un)plugged
now=$(ls -l --time-style=+%s "$Z"/*.zim "$X"/*.zim 2>/dev/null | md5sum)
[ "$now" = "$(cat "$S" 2>/dev/null)" ] && exit 0
echo "$now" > "$S" && docker restart prepper-kiwix-1 >/dev/null
