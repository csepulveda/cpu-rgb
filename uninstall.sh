#!/bin/sh
# Remove cpu-rgb (keeps /etc/cpu-rgb.conf and /etc/openrgb unless --purge is given).
set -eu
[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo ./uninstall.sh)" >&2; exit 1; }
systemctl disable --now cpu-rgb.service openrgb-server.service 2>/dev/null || true
rm -f /etc/systemd/system/cpu-rgb.service /etc/systemd/system/openrgb-server.service /usr/local/bin/cpu-rgb
systemctl daemon-reload
if [ "${1:-}" = "--purge" ]; then
    rm -rf /etc/cpu-rgb.conf /etc/openrgb
    echo "removed config as well"
fi
echo "cpu-rgb removed"
