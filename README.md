# Lumio

A touchscreen Philips Hue controller built with Python and Kivy, designed for a Raspberry Pi 4 with the official 7" display. Runs as a local full-screen panel — no cloud, no browser, no subscription.

![Target hardware: Raspberry Pi 4 + 7" touchscreen](https://www.raspberrypi.com/app/uploads/2023/05/Display-Tilt-Angle.jpg)

---

## Features

- Room grid with on/off toggle and brightness slider
- Real-time updates via Hue CLIP v2 SSE event stream
- Per-room light detail (long-press a room card)
- Drag-to-reorder rooms
- Show/hide rooms via settings
- Light/dark theme toggle
- Event logging (on/off, brightness, source, timestamp) to `hue_log.jsonl`

---

## Requirements

### Hardware
- Raspberry Pi 4 (any RAM)
- [Official Raspberry Pi 7" Touchscreen](https://www.raspberrypi.com/products/raspberry-pi-touch-display/) (800×480)
- Philips Hue Bridge (v2 square bridge) on the same local network

### Software
- Python 3.9+
- pip packages:

```bash
pip install kivy requests urllib3
```

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/yourusername/lumio.git
cd lumio
```

### 2. Install dependencies

```bash
pip install kivy requests urllib3
```

### 3. Authenticate with your Hue Bridge

Run the discovery script. It will find your bridge automatically and walk you through the one-time button-press authentication:

```bash
python hue_discovery.py
```

- When prompted, **press the physical link button on top of your Hue Bridge**
- The script will save your credentials to `hue_settings.json`
- It will then print all your lights, rooms, and scenes so you can verify everything is detected

> `hue_settings.json` is in `.gitignore` — it will never be committed. Each user creates their own.

### 4. Run the app

**Development (windowed, 800×480):**
```bash
python hue_app.py
```

**Raspberry Pi (fullscreen):**

Set `DEV_WINDOW_SIZE = None` at the top of `hue_app.py`, then:
```bash
DISPLAY=:0 python hue_app.py
```

Or add to `/etc/rc.local` to launch on boot.

---

## Configuration

All settings are stored in `hue_settings.json` (auto-created, never committed):

| Key | Description |
|---|---|
| `bridge_ip` | Local IP of your Hue Bridge |
| `username` | Hue API key (created during setup) |
| `hidden_rooms` | Room IDs hidden from the grid |
| `room_order` | Saved drag-to-reorder sequence |

See `hue_settings.example.json` for the expected structure.

---

## Usage

| Action | Result |
|---|---|
| Tap a card | Toggle room on/off |
| Drag the slider | Adjust room brightness |
| Long-press a card | Open per-light controls |
| ✎ button | Enter reorder mode — drag cards |
| ⚙ button | Settings — show/hide rooms |
| ☾/☀ button | Toggle dark/light theme |

---

## Event Log

All light changes are written to `hue_log.jsonl` (one JSON object per line). This file is excluded from git.

**Room-level event:**
```json
{"ts":"2026-03-07T14:30:01.123Z","room":"Den","room_id":"3","event":"on","bri_pct":80,"source":"HueControl"}
```

**External change (physical switch, voice, app):**
```json
{"ts":"2026-03-07T14:31:10.789Z","room":"Kitchen","room_id":"5","event":"off","bri_pct":0,"source":"external","owner_type":"device"}
```

**Source values:**

| Value | Meaning |
|---|---|
| `HueControl` | Changed from this app |
| `external` + `device` | Physical switch or button |
| `external` + `app_instance` | Hue app, voice assistant, third-party |
| `external` + `bridge_home` | Schedule or automation |
| `system` | App start/stop, bridge connect/disconnect, errors |

---

## Security

**Your local network info is never stored in this repo.**

- `hue_settings.json` — contains your bridge IP and API key. Listed in `.gitignore`. Never committed.
- `hue_log.jsonl` — contains usage data. Listed in `.gitignore`. Never committed.
- The Hue API key is a local-only credential. It only works on your LAN and grants control of your lights — it is not a password to any Philips account.
- If you need to revoke access, delete the API key from the Hue app under **Settings → My Hue system → Apps**.

---

## Project Structure

```
lumio/
├── hue_app.py              # Main Kivy application
├── hue_discovery.py        # Bridge discovery and authentication
├── hue_settings.example.json  # Settings template (safe to commit)
├── hue_settings.json       # Your credentials and preferences (git-ignored)
├── hue_log.jsonl           # Event log (git-ignored)
├── Lumio.sln               # Visual Studio solution
├── Lumio.pyproj            # Visual Studio Python project
└── .gitignore
```

---

## Pi Auto-Start (optional)

To launch Lumio on boot, add to `/etc/rc.local` before `exit 0`:

```bash
DISPLAY=:0 python /home/pi/lumio/hue_app.py &
```

Or use a systemd service for cleaner process management.

---

## Development

Built and edited in **VS Code** with the following recommended extensions:

| Extension | Purpose |
|---|---|
| [Python](https://marketplace.visualstudio.com/items?itemName=ms-python.python) | Linting, IntelliSense, debugging |
| [Markdown All in One](https://marketplace.visualstudio.com/items?itemName=yzhang.markdown-all-in-one) | README preview, formatting, shortcuts |
| [GitLens](https://marketplace.visualstudio.com/items?itemName=eamodio.gitlens) | Inline blame, history, revision comparison |

---

## Versioning

This project follows [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`

| Increment | When |
|---|---|
| `PATCH` (0.1.**1**) | Bug fix, small tweak |
| `MINOR` (0.**2**.0) | New feature, backward compatible |
| `MAJOR` (**1**.0.0) | Breaking change or major redesign |

### Tagging a release

```bash
git tag -a v0.1.0 -m "Initial release — room grid, SSE, logging"
git push origin v0.1.0
```

### Changelog

Keep a `CHANGELOG.md` alongside this file. Suggested format:

```
## [0.2.0] - 2026-04-01
### Added
- Scene support
### Fixed
- Dark mode contrast in edit mode

## [0.1.0] - 2026-03-07
### Added
- Initial release
```

Create a **GitHub Release** from each tag to attach release notes and make versions browsable at `github.com/yourusername/lumio/releases`.

---

## License

MIT
