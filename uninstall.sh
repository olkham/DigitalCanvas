#!/usr/bin/env bash
# Removes the Digital Canvas service and binary. Media, thumbnails and
# config.json in this folder are left untouched.
set -euo pipefail
SERVICE=digitalcanvas

if systemctl list-unit-files | grep -q "^$SERVICE.service"; then
  sudo systemctl disable --now $SERVICE.service || true
  sudo rm -f /etc/systemd/system/$SERVICE.service
  sudo systemctl daemon-reload
  sudo systemctl reset-failed || true
fi
sudo rm -f /usr/local/bin/digitalcanvas /etc/sudoers.d/digitalcanvas /etc/modules-load.d/digitalcanvas.conf
echo "Digital Canvas removed. Your media and config.json are still in $(cd "$(dirname "$0")" && pwd)."
echo "Delete the cache/ folder too if you want to reclaim the space used by thumbnails and optimised videos."
