#!/bin/sh
# cpu-rgb installer. Run as root: sudo ./install.sh
set -eu
cd "$(dirname "$0")"

[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo ./install.sh)" >&2; exit 1; }
command -v openrgb >/dev/null || { echo "openrgb not found in PATH; install OpenRGB first" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 not found" >&2; exit 1; }

install -Dm755 cpu-rgb.py /usr/local/bin/cpu-rgb
install -Dm644 systemd/openrgb-server.service /etc/systemd/system/openrgb-server.service
install -Dm644 systemd/cpu-rgb.service /etc/systemd/system/cpu-rgb.service

if [ ! -f /etc/cpu-rgb.conf ]; then
    install -Dm644 cpu-rgb.conf.example /etc/cpu-rgb.conf
    echo "installed default config to /etc/cpu-rgb.conf"
else
    echo "keeping existing /etc/cpu-rgb.conf"
fi

# OpenRGB server config dir. Reuse the invoking user's zone sizes / profiles if present,
# so that ARGB headers resized in the GUI keep their size for the server.
mkdir -p /etc/openrgb
user_home=$(getent passwd "${SUDO_USER:-root}" | cut -d: -f6)
for f in sizes.ors OpenRGB.json; do
    if [ -f "$user_home/.config/OpenRGB/$f" ] && [ ! -e "/etc/openrgb/$f" ]; then
        cp "$user_home/.config/OpenRGB/$f" "/etc/openrgb/$f"
        echo "copied $f from $user_home/.config/OpenRGB to /etc/openrgb"
    fi
done

systemctl daemon-reload
systemctl enable --now openrgb-server.service cpu-rgb.service
echo
echo "cpu-rgb installed and started."
echo "  status : systemctl status cpu-rgb"
echo "  logs   : journalctl -u cpu-rgb -f"
echo "  config : /etc/cpu-rgb.conf   (apply with: systemctl reload cpu-rgb)"
