#!/usr/bin/env bash
# Digital Canvas installer for Raspberry Pi OS / Debian.
#
#   ./install.sh            interactive
#   ./install.sh -y         accept all defaults (unattended)
#
# Media and config.json stay in this folder; the binary goes to
# /usr/local/bin and a systemd service starts it at boot.
set -euo pipefail

YES=0
[ "${1:-}" = "-y" ] && YES=1
DIR="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="${SUDO_USER:-$(id -un)}"
USER_ID="$(id -u "$USER_NAME")"
SERVICE=digitalcanvas
GO_VERSION=1.27.4

say()  { printf '\033[1;35m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }
ask()  { # ask "question" default(y/n)
  local def=$2 ans
  [ $YES = 1 ] && { [ "$def" = y ]; return; }
  read -r -p "$1 [$( [ "$def" = y ] && echo Y/n || echo y/N )] " ans || true
  ans=${ans:-$def}
  [[ "$ans" =~ ^[Yy] ]]
}

if [ "$(id -u)" = 0 ] && [ -z "${SUDO_USER:-}" ]; then
  warn "Run this as your normal user (it uses sudo where needed)."
  exit 1
fi

case "$(uname -m)" in
  aarch64|arm64) ARCH=arm64; GOARCH=arm64; GOARM= ;;
  armv7l) ARCH=armv7; GOARCH=arm; GOARM=7 ;;
  armv6l) ARCH=armv6; GOARCH=arm; GOARM=6 ;;
  x86_64) ARCH=amd64; GOARCH=amd64; GOARM= ;;
  *) warn "Unsupported architecture $(uname -m)"; exit 1 ;;
esac

# ---- 1. binary ---------------------------------------------------------
BIN=""
if [ -x "$DIR/dist/digitalcanvas-linux-$ARCH" ]; then
  BIN="$DIR/dist/digitalcanvas-linux-$ARCH"
  say "Using prebuilt $BIN"
else
  GO=$(command -v go || true)
  if [ -n "$GO" ] && ! "$GO" version | grep -Eq 'go1\.(2[6-9]|[3-9][0-9])'; then
    GO=""  # too old (Debian's packaged Go is)
  fi
  if [ -z "$GO" ]; then
    GOROOT_DL="$HOME/.cache/digitalcanvas/go"
    if [ ! -x "$GOROOT_DL/bin/go" ]; then
      say "Downloading Go $GO_VERSION (used only to build; ~70 MB)"
      mkdir -p "$HOME/.cache/digitalcanvas"
      curl -fsSL "https://go.dev/dl/go$GO_VERSION.linux-$GOARCH.tar.gz" | tar -C "$HOME/.cache/digitalcanvas" -xz
    fi
    GO="$GOROOT_DL/bin/go"
  fi
  say "Building with $("$GO" version)"
  mkdir -p "$DIR/dist"
  (cd "$DIR" && CGO_ENABLED=0 GOARCH=$GOARCH GOARM=$GOARM "$GO" build -trimpath \
     -ldflags "-s -w -X main.version=$(git -C "$DIR" describe --tags --always --dirty 2>/dev/null || echo dev)" \
     -o "dist/digitalcanvas-linux-$ARCH" ./cmd/digitalcanvas)
  BIN="$DIR/dist/digitalcanvas-linux-$ARCH"
fi
sudo install -m 0755 "$BIN" /usr/local/bin/digitalcanvas
say "Installed /usr/local/bin/digitalcanvas ($(/usr/local/bin/digitalcanvas -version))"

# ---- 2. packages -------------------------------------------------------
PKGS=()
command -v ffmpeg >/dev/null || PKGS+=(ffmpeg)
if ! command -v chromium-browser >/dev/null && ! command -v chromium >/dev/null; then
  if apt-cache show chromium >/dev/null 2>&1; then PKGS+=(chromium); else PKGS+=(chromium-browser); fi
fi
command -v i2cdetect >/dev/null || PKGS+=(i2c-tools)
if [ ${#PKGS[@]} -gt 0 ]; then
  if ask "Install ${PKGS[*]} (video thumbnails/optimisation, the display browser, I2C tools)?" y; then
    sudo apt-get update -q
    sudo apt-get install -y -q "${PKGS[@]}"
  fi
fi

# ---- 3. hardware access ------------------------------------------------
if command -v raspi-config >/dev/null; then
  sudo raspi-config nonint do_i2c 0 || true          # enable I2C (sensors)
fi
echo i2c-dev | sudo tee /etc/modules-load.d/digitalcanvas.conf >/dev/null  # DDC/CI buses
sudo modprobe i2c-dev 2>/dev/null || true
for g in i2c video render gpio; do
  getent group $g >/dev/null && sudo usermod -aG $g "$USER_NAME"
done

# Allow the web UI's Reboot/Shut down buttons (and nothing else) without a password.
SUDOERS=/etc/sudoers.d/digitalcanvas
TMP=$(mktemp)
echo "$USER_NAME ALL=(root) NOPASSWD: /usr/sbin/shutdown, /usr/sbin/reboot, /sbin/shutdown, /sbin/reboot" > "$TMP"
if sudo visudo -cf "$TMP" >/dev/null; then sudo install -m 0440 "$TMP" "$SUDOERS"; fi
rm -f "$TMP"

if command -v raspi-config >/dev/null && ask "Stop the desktop from blanking the screen? (recommended for a photo frame)" y; then
  sudo raspi-config nonint do_blanking 1 || true
fi

# ---- 4. service --------------------------------------------------------
if ask "Start Digital Canvas automatically at boot?" y; then
  sudo tee /etc/systemd/system/$SERVICE.service >/dev/null <<EOF
[Unit]
Description=Digital Canvas photo frame
After=network-online.target
Wants=network-online.target

[Service]
User=$USER_NAME
Group=$USER_NAME
WorkingDirectory=$DIR
# The app finds the desktop session (Wayland or X11) by itself and launches
# the kiosk browser as soon as it is available; web UI and MQTT start at once.
Environment=XDG_RUNTIME_DIR=/run/user/$USER_ID
ExecStart=/usr/local/bin/digitalcanvas -config $DIR/config.json
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  # Replace the Python version's service if present.
  if systemctl list-unit-files | grep -q '^digital_canvas.service'; then
    say "Disabling the old Python service (digital_canvas)"
    sudo systemctl disable --now digital_canvas.service || true
  fi
  sudo systemctl daemon-reload
  sudo systemctl enable $SERVICE.service
  sudo systemctl restart $SERVICE.service
  sleep 2
  systemctl --no-pager --lines=5 status $SERVICE.service || true
fi

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
PORT=$(grep -o '"web_interface_port": *[0-9]*' "$DIR/config.json" 2>/dev/null | grep -o '[0-9]*$' || echo 7000)
say "Done. Control panel: http://${IP:-<this-pi>}:${PORT:-7000}"
say "Logs: journalctl -u $SERVICE -f"
if id -nG "$USER_NAME" | grep -qvw i2c; then
  warn "Log out and back in (or reboot) once so the new group memberships apply."
fi
