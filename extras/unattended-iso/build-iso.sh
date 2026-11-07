#!/usr/bin/env bash
# OPTIONAL. Remaster the Ubuntu Server ISO into a hands-off installer, for a box you only reach
# through a KVM (boot it as virtual media) or that has no keyboard and screen.
# ⚠️ The resulting ISO ERASES the largest internal disk of whatever boots it, with no prompt.
#   (It refuses to wipe a disk that already holds a finished prepper install.)
#
#   ./build-iso.sh ubuntu-26.04.1-live-server-amd64.iso
#   USER_NAME=pat TZ_NAME=America/Chicago PUBKEY=~/.ssh/id_ed25519.pub ./build-iso.sh <base.iso>
# Needs xorriso and openssl (Linux or WSL). Asks for the new user's password.
# Output: prepper-WIPES-DISK.iso next to the base ISO.
#
# Known problem: some KVMs (seen on a TinyPilot) only expose the first ~2.2 GB of an ISO, and
# xorriso puts the added files at the END of the image, so the installer can't read them and
# stops at a grub> prompt. If that happens, use the normal install in the README instead.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
BASE=${1:?usage: build-iso.sh <ubuntu-live-server.iso>}
USER_NAME=${USER_NAME:-prepper}
TZ_NAME=${TZ_NAME:-America/New_York}
PUBKEY=${PUBKEY:-$HOME/.ssh/id_ed25519.pub}
OUT=$(dirname "$BASE")/prepper-WIPES-DISK.iso
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

[ -f "$PUBKEY" ] || { echo "no SSH public key at $PUBKEY (set PUBKEY=...)"; exit 1; }
read -rsp "password for user '$USER_NAME': " pw; echo
hash=$(openssl passwd -6 -stdin <<<"$pw"); unset pw
key=$(tr -d '\r\n' < "$PUBKEY")
mkdir -p "$WORK/nocloud"
sed -e "s|__PASSWORD_HASH__|$hash|" -e "s|__SSH_PUBKEY__|$key|" \
    -e "s|__USER__|$USER_NAME|g" -e "s|__TZ__|$TZ_NAME|" \
  "$HERE/user-data.tmpl" > "$WORK/nocloud/user-data"
touch "$WORK/nocloud/meta-data"
grep -q '__PASSWORD_HASH__\|__SSH_PUBKEY__\|__USER__\|__TZ__' "$WORK/nocloud/user-data" && { echo "template not filled"; exit 1; }

# grub.cfg: short timeout, add autoinstall + nocloud datasource to every casper kernel line
xorriso -osirrox on -indev "$BASE" -extract /boot/grub/grub.cfg "$WORK/grub.cfg" 2>/dev/null
chmod u+w "$WORK/grub.cfg"
sed -i -e 's/^set timeout=.*/set timeout=3/' \
  -e 's|\(linux\s\+/casper/vmlinuz\)\(.*\)---|\1\2autoinstall ds=nocloud\\;s=/cdrom/nocloud/ ---|' \
  "$WORK/grub.cfg"
grep -q 'autoinstall ds=nocloud' "$WORK/grub.cfg" || { echo "grub.cfg patch failed"; exit 1; }

rm -f "$OUT"
xorriso -indev "$BASE" -outdev "$OUT" \
  -map "$WORK/nocloud" /nocloud \
  -map "$WORK/grub.cfg" /boot/grub/grub.cfg \
  -boot_image any replay 2>&1 | tail -3
ls -l "$OUT"
