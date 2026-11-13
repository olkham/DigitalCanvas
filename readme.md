# Digital Canvas

A fast, lightweight digital photo frame for the Raspberry Pi (or any Linux or Windows machine with a screen). It runs photo and video slideshows with smooth GPU crossfades, and comes with a modern web control panel, MQTT, Plex "now playing" artwork, automatic brightness and rotation, and an on/off schedule.

> Much of this project, including this Go rewrite, was written with AI assistance. Review it before relying on it.

- **One small binary.** It's written in pure Go with no Python, OpenCV or numpy runtime. It cross-compiles for Pi (arm64/armv7/armv6), x86 Linux and Windows.
- **The GPU does the pixel work.** Crossfades, rotation and scaling are composited by the browser's GPU compositor, and video is decoded in hardware. The CPU does no per-frame work.
- **Bounded memory.** Images are pre-scaled once to screen size and cached on disk. Memory no longer grows with the library.
- **Push, not poll.** The UI and display receive changes over Server-Sent Events. Sensors are read at 1–2 Hz, and MQTT publishes only on change.
- **Drop-in replacement.** It uses the same `config.json`, `images/` and `thumbnails/` folders, the same HTTP endpoints and the same MQTT topics.

---

## How it works

```
 phone / laptop ── HTTP + SSE ──┐
 Home Assistant ── MQTT ────────┤     ┌────────────────────────────────────┐
 Plex server ───── webhook ─────┼────▶│  digitalcanvas  (single Go binary)  │── DDC/CI ──▶ monitor power/brightness
 scripts / curl ── legacy API ──┘     │  player · library · config · web UI │── I²C ─────▶ VEML7700 light, BMI160 accel
                                      └─────────────────┬──────────────────┘
                                         SSE: "show X"  │  ▲ "video ended", screen size, keys
                                      ┌─────────────────▼──┴───────────────┐
                                      │  Chromium kiosk  →  /display page   │  opacity crossfade + CSS rotation on the
                                      │  (launched and supervised by the    │  GPU, <video> on the hardware decoder
                                      │   binary; restarts it if it dies)   │
                                      └────────────────────────────────────┘
```

The server owns all state: what's showing, the timers, pause reasons and the queue. The display page only renders slides as two stacked layers and fades the top one in. Any browser can open `/display` to mirror the canvas on another screen.

### Why it's lighter than the Python version

| | Python version | This version |
|---|---|---|
| Crossfade | `cv2.addWeighted` on full-resolution frames, then cv2→PIL→Tk conversion, targeting 60 fps on the CPU | One CSS opacity transition composited by the GPU |
| Video | OpenCV software decode, per-frame Lanczos resize and two colour conversions into Tk | Hardware decode in the browser. HEVC, 10-bit, 4K, AVI and MKV are converted once, in the background, to screen-sized H.264 (using the Pi's hardware encoder where available) |
| Memory | Every image shown keeps a processed frame (~6 MB at 1080p) plus a quality-100 JPEG of the original, so memory grows with the library | Screen-sized renditions on disk and nothing held per image. The server measured 37 MB working set |
| Idle wake-ups | Sensor loop at 10 Hz, publishing two MQTT messages per pass. The web UI polls once a second | Accelerometer 2 Hz, light 1 Hz, schedule every 10 s. Events are pushed |
| Startup | Re-reads every file header (and opens every video) on each boot | Metadata cache: 8 items scanned in 1 ms, nothing re-processed |
| Uploads | 12 MP photos decoded and resized on the Pi | The browser downscales before uploading; the Pi only stores the result |
| Dependencies | Python, OpenCV, numpy, Pillow, Flask, paho, Tk (hundreds of MB) | One ~9 MB static binary. Optional ffmpeg and Chromium (preinstalled on Raspberry Pi OS desktop) |

Measured on the development machine while running a 1080p slideshow with a display and the control panel connected: the server used under 0.1% of one CPU core and a 37 MB working set. The kiosk browser is the largest consumer, typically 150–300 MB on a Pi. That's comparable to the old app's baseline, but it stays flat instead of growing, and it uses a fraction of the CPU.

---

## Feature parity

Everything the Python app did is still here. Several things that were broken there now work.

| Feature (original) | Status in this version |
|---|---|
| Image slideshow (png, jpg, jpeg, bmp, webp) with interval and crossfade duration | ✅ Crossfade is GPU-composited. Transition can be fractional (e.g. 1.5 s) |
| Video playback (mp4, mov, avi, webm, mkv, gif). Plays to the end, then advances; loops while paused | ✅ Same behaviour, plus `m4v`. Unsupported codecs are transcoded once. GIFs show for at least the interval |
| Fit (blurred, darkened backdrop) or fill (crop) | ✅ The backdrop is pre-blurred once per image, not per frame |
| Rotation 0/90/180/270 and auto-rotation from a BMI160 accelerometer | ✅ An ambiguous reading (device flat) keeps the current rotation instead of snapping to 0 |
| Orientation filter (portrait / landscape / both) | ✅ Also drives the gallery, as before |
| Playback mode sequential / random | ✅ **`random` now actually works** (shuffled order, never the same item twice in a row) |
| Fullscreen / windowed | ✅ The kiosk browser is relaunched in the chosen mode |
| Keyboard: ← → next/previous, `f` fullscreen, `s` scale, `p` pause, `r` resume, `a` rotate, `q`/`Esc` quit | ✅ Same keys, plus `Space` to toggle play/pause. `q`/`Esc` only quit from the canvas' own kiosk window |
| Web UI: gallery, live highlight of the current image, click to show, delete, view original, upload files or URL, device name, themes (all 8), every setting | ✅ Redesigned (see below) |
| Startup: rename files to UUIDs, create missing thumbnails, delete orphan thumbnails | ✅ Thumbnails are now EXIF-orientation aware and sharper (320 px) |
| Upload downscaling to the "max useful size" and `.webp` handling | ✅ WebP and BMP are really converted to JPEG (the original only renamed them) |
| `display_now` (multipart file, form `image` base64, raw base64 body) | ✅ Raw image bytes and `data:` URLs are also accepted |
| `/canvas` returns the current frame as JPEG | ✅ Rendered on demand with the same rotation, fit or fill and backdrop |
| MQTT control and state topics | ✅ **Exact topic matching.** The original's substring matching made `auto_rotation` also fire `rotation` and crash. `frame_interval`, `transition_duration` and `media_orientation_filter` were broken and now work |
| Plex webhook: show artwork on play/resume, optional pause, resume on stop/pause | ✅ Falls back to the webhook's attached thumbnail. A user's manual pause is no longer undone by Plex stopping |
| Auto brightness from a VEML7700 with min/max calibration | ✅ If no sensor is present it does nothing (the original's simulation drove brightness to 0) |
| Monitor power and brightness over DDC/CI (Linux and Windows) | ✅ Pure Go. Without DDC/CI the display is blanked, and you can configure power commands |
| On/off schedule (`time_on`/`time_off`) that pauses and resumes the slideshow | ✅ **Windows that cross midnight (e.g. 18:00–02:00) now work**, and the correct state is applied at startup. There's a separate `schedule_enabled` toggle, and turning the schedule off while it has the screen off brings the screen back |
| Reboot / shutdown (Raspberry Pi only) | ✅ Plus "restart app" |
| `GET /configure` reloads `config.json` from disk; `POST /configure` | ✅ `POST /configure` crashed in the original and now works |
| `/slideshow/delete` | ✅ Deletes the current item (it called a non-existent method before) |
| Loading page while starting | Not needed: the server answers immediately and thumbnails fill in live |

**New:** a responsive control panel for phone and desktop with a live preview and countdown, drag and drop, paste-to-upload, bulk select and delete, upload progress, and the original filename shown as the title. Also new: MQTT username/password and `status` availability topic (LWT), `<topic>/<command>/set` aliases, extra MQTT commands (`select`, `brightness`, `power`, `display_now`, `playback_mode`), an idle screen that shows the panel's URL when the library is empty, a folder watcher that picks up files copied into `images/` (Samba/scp) without a restart, protection against cross-site requests from other web pages, and atomic config writes (no corrupted `config.json` after a power cut).

---

## Install on a Raspberry Pi

Raspberry Pi OS with desktop (Bookworm or later) is recommended: it already has Chromium, and the app finds the Wayland or X11 session by itself.

```sh
git clone https://github.com/olkham/DigitalCanvas.git
cd DigitalCanvas
./install.sh            # or ./install.sh -y for no questions
```

The installer:

1. uses `dist/digitalcanvas-linux-<arch>` if present, otherwise builds it (downloading Go to `~/.cache` only if needed)
2. installs `ffmpeg`, `chromium` and `i2c-tools` if missing
3. enables I²C and the DDC/CI buses, adds you to the `i2c`, `video` and `render` groups, and allows the web UI to reboot or shut down (only those two commands) without a password
4. optionally turns off desktop screen blanking
5. creates and starts the `digitalcanvas` systemd service. If the Python version's `digital_canvas` service exists, it's disabled

To skip building on the Pi, build on any PC and copy the binary across, or download one from the GitHub Releases page into `dist/`:

```sh
./scripts/build.sh                    # or scripts\build.ps1 on Windows
scp dist/digitalcanvas-linux-arm64 pi@frame:~/DigitalCanvas/dist/
```

### Migrating from the Python version

Run `./install.sh` in the same folder. Your `config.json`, `images/` and `thumbnails/` are reused as they are. New settings are appended with defaults, and old 200 px thumbnails are regenerated once in the background. The Python code now lives in [`legacy/python/`](legacy/python/); delete it once you're happy.

### Raspberry Pi OS Lite (no desktop)

Install a minimal kiosk compositor and let it run the browser. Set `"display_browser": "none"` so the app doesn't launch its own:

```sh
sudo apt install cage chromium
sudo tee /etc/systemd/system/digitalcanvas-kiosk.service <<'EOF'
[Unit]
Description=Digital Canvas kiosk
After=digitalcanvas.service systemd-user-sessions.service
[Service]
User=pi
PAMName=login
TTYPath=/dev/tty1
StandardInput=tty
ExecStart=/usr/bin/cage -s -- chromium --kiosk --noerrdialogs --autoplay-policy=no-user-gesture-required http://127.0.0.1:7000/display
Restart=always
[Install]
WantedBy=graphical.target
EOF
sudo systemctl enable --now digitalcanvas-kiosk
```

In this mode `f` and `q` have no effect, because cage is always fullscreen.

## Run on Windows

```powershell
scripts\build.ps1
dist\digitalcanvas-windows-amd64.exe -config config.json
# start automatically at logon:
powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1
```

The app launches Chrome or Edge in kiosk mode with its own profile, so your normal browser is unaffected. Monitor brightness and power use the Windows monitor-configuration API.

---

## Using it

Open `http://<device-ip>:7000` from any device on the network. When the library is empty, the canvas itself shows this address.

- **Add media:** use **Add media**, drag files anywhere onto the page, paste an image, add from a URL, or copy files into `images/` (picked up within about a minute). Large photos are downscaled in your browser before upload.
- **Gallery:** click to show an item now. Hover (or tap **⋯** on touch devices) to open the original or delete it. Use **Select**, or long-press on touch, for bulk delete.
- **Settings** (gear icon) has these sections: Slideshow, Display, Screen (power, brightness, schedule), Theme, Integrations (MQTT, Plex, video optimisation), and System (device name, diagnostics, restart, reboot, shutdown).

Keyboard on the canvas screen:

| Key | Action |
|---|---|
| ← / → | Previous / next |
| `p` / `r` / Space | Pause / resume / toggle |
| `s` | Toggle fit ↔ fill |
| `a` | Rotate 90° |
| `f` | Toggle fullscreen ↔ windowed |
| `q` / `Esc` | Quit (only the kiosk window can quit the app) |

**Videos:** H.264 MP4/MOV files that fit the screen play directly. Everything else (HEVC from phones, 10-bit, 4K, AVI, MKV, MPEG-4 Part 2) is converted once to screen-sized H.264 in the background (shown as "Optimising…"). The Pi's hardware encoder is used when available. This needs `ffmpeg`, and you can turn it off under *Integrations → Videos*. Videos play muted, as in the original.

---

## Configuration

Settings live in `config.json` next to the binary's working directory (`-config` sets the path). Every setting can be changed live from the UI, `PATCH /api/config` or MQTT. The file is written atomically and edits made by hand are picked up by `GET /configure`.

| Key | Default | Notes |
|---|---|---|
| `image_folder`, `thumbnail_folder` | `images`, `thumbnails` | Relative to the config file. Restart to apply |
| `frame_interval` | `10` | Seconds each photo is shown (after its crossfade). Videos play to the end |
| `transition_duration` | `5` | Crossfade seconds (`0` = cut) |
| `media_orientation_filter` | `both` | `both`, `landscape`, `portrait` |
| `playback_mode` | `sequential` | `sequential` (date added) or `random` |
| `display_mode` | `fullscreen` | `fullscreen` or `windowed` |
| `scale_mode` | `fit` | `fit` (blurred backdrop) or `fill` (crop) |
| `rotation` | `0` | `0`, `90`, `180`, `270` (clockwise) |
| `auto_rotation` | `true` | Needs a BMI160 |
| `auto_brightness` | `true` | Needs a VEML7700 and a DDC/CI monitor |
| `light_sensor_min_reading`, `light_sensor_max_reading` | `0`, `1000` | Lux mapped to 0 % and 100 % brightness |
| `schedule_enabled`, `time_on`, `time_off` | `true`, `06:00`, `22:00` | Screen off and slideshow paused outside the window. Equal times also disable it |
| `web_interface_port` | `7000` | Restart to apply |
| `mqtt_broker`, `mqtt_port`, `mqtt_topic` | `localhost`, `1883`, `digital-canvas-<id>` | IP address or hostname |
| `mqtt_username`, `mqtt_password` | empty | Optional |
| `device_name` | `digital-canvas-<id>` | |
| `theme` | `dark-theme` | `dark`, `light`, `darcula`, `warm-sunset`, `ocean-breeze`, `autumn-leaves`, `winter-wonderland`, `spring-blossom` (each with a `-theme` suffix) |
| `plex_port`, `allow_plex`, `pause_when_plex_playing` | `32400`, `true`, `true` | |
| `display_browser` | `auto` | `auto` (Chromium/Chrome/Edge/Firefox), `none`, or a path |
| `screen_on_command`, `screen_off_command` | empty | Shell commands used when DDC/CI isn't available. If empty, `wlr-randr`, `xset` or `vcgencmd` is tried |
| `transcode_videos` | `true` | Background H.264 optimisation |
| `i2c_bus` | `1` | Sensor bus |

Command-line flags: `-config path`, `-simulate` (never touch the monitor, sensors or system power), `-no-browser`, `-listen addr`, `-log file`, `-version`.

---

## HTTP API

### JSON API (used by the web UI)

| Method & path | Body / notes |
|---|---|
| `GET /api/state` | Config, current slide, playback, status, media, host info |
| `GET /api/events` | Server-Sent Events: `hello`, `slide`, `playback`, `config`, `status`, `power`, `media.add`, `media.update`, `media.remove` |
| `GET /api/media` · `GET /api/info` | |
| `POST /api/media` | multipart `file` (repeatable) and/or `image_url` |
| `POST /api/media/url` | `{"url": "https://…"}` |
| `POST /api/media/{name}/show` · `DELETE /api/media/{name}` · `POST /api/media/delete` | Bulk: `{"names": [...]}` |
| `POST /api/command` | `{"action": "next" \| "previous" \| "pause" \| "resume" \| "toggle" \| "select" \| "rotate" \| "toggle_scale" \| "reload_display", "value": "…"}` |
| `PATCH /api/config` | Any subset of the configuration keys. Returns `422` with per-key errors |
| `POST /api/monitor` | `{"power": true}`, `{"brightness": 0-100}` (sets manual), `{"auto": true}` |
| `POST /api/system` | `{"action": "restart" \| "reboot" \| "shutdown"}` |
| `GET /media/{name}` · `/media/{name}/display` · `/media/{name}/bg` · `/thumbnails/{name}` · `/canvas` | Files: original, screen-sized rendition (or optimised video), backdrop, thumbnail, current frame |

### Original endpoints (unchanged)

These are kept for existing scripts and Home Assistant `rest_command`s, with the same form fields and response codes as before:

`POST /display_now` · `POST /upload` · `GET /uploads/<file>` · `GET /thumbnails/<file>` · `POST /update_device_name` · `POST /delete` · `POST /select` · `GET /current_image_name` · `GET /canvas` · `POST /configure/mqtt` · `POST /configure/app` · `GET|POST /configure/display` (`display_mode`, `media_orientation_filter`, `scale_mode`, `rotation` (`-1` = auto), `brightness` (`-1` = auto), `power`, `time_on`, `time_off`) · `POST /configure/slideshow` · `POST /configure/plex` · `GET|POST /configure` · `POST /slideshow/next|previous|delete|quit` · `POST /plex_hook` · `POST /power_control`

```sh
curl -X POST -F file=@photo.jpg http://frame:7000/display_now     # show now, don't keep
curl -X POST -d filename=<name> http://frame:7000/select
curl http://frame:7000/canvas -o now.jpg
```

Requests that change state from another site's web page are rejected (`Origin` check). Non-browser clients such as curl, Plex and Home Assistant are unaffected. There is no authentication, as before: keep the device on a trusted network.

---

## MQTT

All topics sit below `mqtt_topic` (e.g. `1/office/canvas`). Commands may also be sent to `<topic>/<command>/set`.

| Command topic | Payload |
|---|---|
| `slideshow` | `next`, `previous`, `pause`, `resume`, `toggle`, `quit` |
| `select` | media file name |
| `rotation` | `0`, `90`, `180`, `270` |
| `scale_mode` · `display_mode` · `theme` · `media_orientation_filter` · `playback_mode` | as in the configuration |
| `frame_interval` · `transition_duration` | seconds |
| `auto_brightness` · `auto_rotation` · `plex` · `schedule_enabled` | `on` / `off` |
| `brightness` | `0`–`100` or `auto` |
| `power` | `on` / `off` |
| `time_on` · `time_off` | `HH:MM` |
| `display_now` | image URL or base64 |

Published: `current_image` (on change), `available_images` (JSON list, retained), `config` (JSON, on connect and on change, password redacted), `light_sensor` and `screen_brightness` (while auto brightness runs, on change plus every 30 s), `status` (`online`/`offline`, retained, last will).

## Plex

In Plex go to *Settings → Webhooks → Add webhook* and enter `http://<device-ip>:7000/plex_hook` (shown with a copy button under *Integrations*). On `media.play`/`media.resume` the canvas fetches the poster from the Plex server that sent the webhook (`plex_port`), falling back to the image attached to the webhook. On `media.stop`/`media.pause` it resumes the slideshow, but only if Plex was the one that paused it.

## Hardware

- **Light sensor:** VEML7700 at `0x10` on I²C bus 1 (pins 3/5).
- **Accelerometer:** BMI160 at `0x69` (or `0x68`).
- **Monitor control:** any monitor with DDC/CI over HDMI or DisplayPort (enable DDC/CI in the monitor's menu). On Linux this needs `i2c-dev` and the `i2c` group, which the installer handles. Monitors without DDC/CI, such as the official Pi touch displays, are blanked instead, or controlled with `screen_on_command`/`screen_off_command`.

Missing hardware is detected and reported under *Settings → System*; nothing else is affected.

---

## Development

```sh
go test ./...                                   # unit tests
go run ./cmd/digitalcanvas -simulate -no-browser  # then open http://localhost:7000 and /display
./scripts/build.sh                              # cross-compile every target into dist/
```

| Path | Contents |
|---|---|
| `cmd/digitalcanvas` | entry point, flags, restart |
| `internal/app` | wiring; every action (UI, legacy API, MQTT, keyboard) is implemented once here |
| `internal/player` | slideshow state machine: queue, shuffle, timers, pause reasons |
| `internal/media` | library, metadata cache, thumbnails, renditions, ffmpeg, folder watcher |
| `internal/imaging` | EXIF, resizing, blurred backdrops, canvas composition (pure Go) |
| `internal/config` | `config.json` schema, coercion, validation, atomic writes |
| `internal/mqttc`, `internal/hub` | MQTT bridge, SSE fan-out |
| `internal/monitor`, `internal/sensors` | DDC/CI (Linux i2c-dev, Windows dxva2), VEML7700/BMI160 |
| `internal/kiosk`, `internal/sysinfo` | browser supervisor, host facts |
| `web/static` | control panel and display page, embedded into the binary |

## Troubleshooting

- **Black screen, but the web UI works:** check `journalctl -u digitalcanvas -f` for `kiosk:` lines. With no desktop session the app waits for one ("waiting for a graphical session"). See the Lite section above.
- **A video shows "Optimising…" for a long time:** large 4K/HEVC clips take minutes on a Pi. Progress is in the log.
- **Brightness or power has no effect:** enable DDC/CI in the monitor's menu, check `i2cdetect -l` lists the HDMI buses, and reboot after installing (group membership).
- **Changing the port or folders:** these need *Settings → System → Restart app*.

## License

MIT. See [LICENSE](LICENSE).
