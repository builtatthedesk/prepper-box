#!/bin/bash
# Turn a USB Wi-Fi adapter into the box's own Wi-Fi network ("prepper"): phones join it and the
# start page pops up. No internet is passed through. Run on the box:
#   sudo ./install.sh                 # picks the first Wi-Fi interface, asks for a password
#   sudo IF=wlan0 COUNTRY=GB ./install.sh   # COUNTRY = your 2-letter country code (Wi-Fi rules), default US
# Needs an adapter whose driver supports AP mode (check: iw list | grep -A8 'interface modes' shows "AP").
# Rollback: systemctl disable --now hostapd dnsmasq; rm /etc/systemd/network/10-prepper-ap.network
#           /etc/dnsmasq.d/prepper.conf /etc/systemd/system/dnsmasq.service.d/after-ap.conf; networkctl reload
set -euo pipefail
cd "$(dirname "$0")"
[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
IF=${IF:-$(iw dev 2>/dev/null | awk '$1=="Interface"{print $2; exit}')}
[ -n "$IF" ] || { echo "no Wi-Fi interface found (plug in the adapter, or set IF=...)"; exit 1; }
echo "hotspot interface: $IF"
read -rsp "Wi-Fi password for the 'prepper' network (8-63 characters): " PSK; echo
[ ${#PSK} -ge 8 ] && [ ${#PSK} -le 63 ] || { echo "password must be 8-63 characters"; exit 1; }
case "$PSK" in *"|"*|*"&"*|*"\\"*) echo "password cannot contain | & or a backslash"; exit 1;; esac
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq hostapd dnsmasq iw >/dev/null
systemctl stop dnsmasq 2>/dev/null || true             # package autostart would grab :53 on all ifaces
umask 077
sed "s|__IF__|$IF|; s|__CC__|${COUNTRY:-US}|; s|__PSK__|$PSK|" hostapd.conf > /etc/hostapd/hostapd.conf
umask 022
sed "s|__IF__|$IF|" 10-prepper-ap.network > /etc/systemd/network/10-prepper-ap.network
sed "s|__IF__|$IF|" dnsmasq-prepper.conf > /etc/dnsmasq.d/prepper.conf
mkdir -p /etc/systemd/system/dnsmasq.service.d
sed "s|__IF__|$IF|" dnsmasq-after-ap.conf > /etc/systemd/system/dnsmasq.service.d/after-ap.conf
grep -q '^DNSMASQ_EXCEPT' /etc/default/dnsmasq || echo 'DNSMASQ_EXCEPT="lo"' >> /etc/default/dnsmasq
systemctl enable --now systemd-networkd
networkctl reload
systemctl daemon-reload
systemctl unmask hostapd
systemctl enable --now hostapd
sleep 3
systemctl enable dnsmasq && systemctl restart dnsmasq
sleep 2
systemctl is-active hostapd dnsmasq
ip -br addr show "$IF"
echo "Join Wi-Fi 'prepper' and open http://10.42.0.1"
