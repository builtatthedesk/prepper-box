#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu Server (24.04 or newer, x86-64). From the cloned repo:
#   sudo ./setup.sh
# Installs Docker and tools, copies stack/ to /opt/prepper, starts every service, downloads the
# small AI model, and adds the cron job that picks up new library books. Safe to re-run: it updates
# /opt/prepper in place and never touches downloaded content.
# Then fill it with content (hours to days of downloading): see README, "Fill it".
#
# Options (environment): DATA=/srv/prepper (where content goes; pick the big disk)
#                        MODEL=llama3.2:3b (any Ollama model; 3B-4B suits 8 GB RAM, no GPU)
# Rollback: cd /opt/prepper && docker compose down; rm -rf /opt/prepper /etc/cron.d/prepper
#           /etc/systemd/network/10-netplan-*.network.d/fallback-ip.conf; networkctl reload
#           (content in $DATA is left alone; delete it by hand if you want the space back)
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run with sudo: sudo ./setup.sh"; exit 1; }
REPO=$(cd "$(dirname "$0")" && pwd)
APP=/opt/prepper
# A re-run keeps the earlier choices unless new ones are given.
if [ -f "$APP/.env" ]; then
  OLD_DATA=$(sed -n "s/^DATA=//p" "$APP/.env"); OLD_MODEL=$(sed -n "s/^MODEL=//p" "$APP/.env")
fi
DATA=${DATA:-${OLD_DATA:-/srv/prepper}}
MODEL=${MODEL:-${OLD_MODEL:-llama3.2:3b}}
U=$(id -un 1000 2>/dev/null) || { echo "expected a normal user with uid 1000 (the one made during install)"; exit 1; }
[ "$(uname -m)" = x86_64 ] || echo "warning: only tested on x86-64; the pmtiles download below is x86-64"

echo "== packages"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker.io docker-compose-v2 aria2 curl tmux rsync \
  avahi-daemon zim-tools ocrmypdf poppler-utils python3 pbzip2 >/dev/null
systemctl enable --now docker avahi-daemon >/dev/null
usermod -aG docker "$U"

if ! command -v pmtiles >/dev/null; then   # map extract tool (Protomaps)
  t=$(mktemp -d)
  curl -fsSL -o "$t/p.tgz" https://github.com/protomaps/go-pmtiles/releases/download/v1.31.2/go-pmtiles_1.31.2_Linux_x86_64.tar.gz
  tar -xzf "$t/p.tgz" -C "$t" pmtiles && install -m755 "$t/pmtiles" /usr/local/bin/pmtiles
  rm -rf "$t"
fi

echo "== stack -> $APP, content -> $DATA"
mkdir -p "$APP"
rsync -a --exclude .env "$REPO/stack/" "$APP/"
printf 'DATA=%s\nMODEL=%s\n' "$DATA" "$MODEL" > "$APP/.env"
chmod +x "$APP"/*.sh "$APP"/hotspot/install.sh "$APP"/kolibri/import-channels.sh

# Map viewer code + fonts/icons, served from this box so the map works with no internet.
L=$APP/landing/maps/lib; mkdir -p "$L" "$APP/landing/maps/data"   # data = mount point for the map files
for u in maplibre-gl@5.24.0/dist/maplibre-gl.js maplibre-gl@5.24.0/dist/maplibre-gl.css \
         pmtiles@4.5.0/dist/pmtiles.js @protomaps/basemaps@5.7.2/dist/basemaps.js; do
  [ -s "$L/$(basename "$u")" ] || curl -fsSL -o "$L/$(basename "$u")" "https://unpkg.com/$u"
done
A=$APP/landing/maps/assets
if [ ! -d "$A/fonts" ]; then
  mkdir -p "$A"
  curl -fsSL https://github.com/protomaps/basemaps-assets/archive/refs/heads/main.tar.gz | tar -xz -C "$A" --strip-components=1
fi

# Content folders. The board and Kolibri containers run as uid 1000, so they own theirs.
mkdir -p "$DATA"/{zim,maps,board,kolibri,ollama,open-webui,photon,routing,shelf/pdf,ham}
chown 1000:1000 "$DATA" "$DATA"/{zim,maps,board,kolibri,photon,routing,shelf,shelf/pdf,ham}

# Wired fallback address: with no router (cable straight to a laptop, or a plain switch) the box
# gives itself 169.254.10.10 after about a minute. With a router, DHCP wins and nothing changes.
# Needs netplan's systemd-networkd renderer (Ubuntu Server's default); picks the first wired port.
NETF=$(grep -l -E '^Name=(en|eth)' /run/systemd/network/10-netplan-*.network 2>/dev/null | head -1 || true)
if [ -n "$NETF" ]; then
  mkdir -p "/etc/systemd/network/$(basename "$NETF").d"
  printf '[Network]\nLinkLocalAddressing=yes\nIPv4LLStartAddress=169.254.10.10\n' \
    > "/etc/systemd/network/$(basename "$NETF").d/fallback-ip.conf"
  networkctl reload
  echo "wired fallback address 169.254.10.10 on $(sed -n 's/^Name=//p' "$NETF" | head -1)"
else
  echo "note: wired fallback address not set up (no systemd-networkd wired config found)"
fi

echo "== starting services (first run downloads ~5 GB of container images)"
cd "$APP"
docker compose up -d --build

# Restart Kiwix whenever a new book finishes downloading (every 10 min).
echo '*/10 * * * * root /opt/prepper/kiwix-refresh.sh' > /etc/cron.d/prepper

echo "== AI model $MODEL"
for _ in $(seq 30); do docker compose exec -T ollama ollama list >/dev/null 2>&1 && break; sleep 2; done
docker compose exec -T ollama ollama pull "$MODEL" || echo "!! model download failed; re-run setup.sh later"

IP=$(hostname -I | awk '{print $1}')
cat <<EOF

Done. Open http://$IP/ (or http://$(hostname).local/) from another computer on this network.
The library, map and directions stay empty until you download content (until then the
kiwix, geocoder and routing containers show "Restarting"; that's expected). Next, as $U:
  tmux new -s content 'DATA=$DATA /opt/prepper/get-content.sh 2>&1 | tee $DATA/get-content.log'
  DATA=$DATA /opt/prepper/get-maps.sh
See README "Fill it" for the rest (address search, courses, manuals, hotspot, backups).
Log out and back in once so '$U' can run docker without sudo.
EOF
