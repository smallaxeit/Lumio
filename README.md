# Lumio

[![GitHub](https://img.shields.io/badge/GitHub-smallaxeit%2Flumio-181717?logo=github)](https://github.com/smallaxeit/lumio) [![Version](https://img.shields.io/badge/version-v0.6.3-blue)](https://github.com/smallaxeit/lumio/releases/tag/v0.6.3) ![Date](https://img.shields.io/badge/updated-2026--06--06-lightgrey)

A touchscreen Philips Hue controller built with Python and Kivy, designed for a Raspberry Pi 4 with the official 7" display. Runs as a local full-screen panel — no cloud, no browser, no subscription.

[Target hardware: Raspberry Pi 4 + 7" touchscreen](https://www.raspberrypi.com/app/uploads/2023/05/Display-Tilt-Angle.jpg)

```bash
git clone https://github.com/smallaxeit/lumio.git
cd lumio
pip install kivy requests urllib3
python hue_discovery.py   # one-time setup — press button on bridge when prompted
python lumio.py
```

---

## Features

**Lighting**
- Room grid with on/off toggle and brightness slider
- Real-time updates via Hue CLIP v2 SSE event stream
- Per-room light detail (long-press a room card)
- Room reordering via ▲▼ per-card buttons in sort mode — reliable on Pi touchscreen with no gesture jitter
- Event logging (on/off, brightness, source, timestamp) to `hue_log.jsonl`

**Header**
- ☰ hamburger button (left) — opens the settings popup
- Local weather — current temp + condition, refreshes every 15 min, shown just right of the hamburger
  - Location detected automatically via IP geolocation on first run (no API key needed)
  - Tap the weather text to open the full weather detail card
- ↕ sort button (right, always visible) — tap to enter sort mode; becomes ✔ to exit

**Weather detail**
- Current temp (large), condition, wind speed
- 5-day forecast starting with Today — high/low, condition, precipitation chance, weather icon per day
- Tap Today or any forecast day for a full 24-hour breakdown with temp, condition, precip %, wind
- Today's hourly view starts at the current hour (past hours hidden)

**Settings (☰ button)**
- Light/dark theme toggle — persists across restarts
- Screen brightness slider (Pi backlight, persists across restarts)
- Show/hide weather toggle
- Advanced section (collapsible): Enable Logging, Show Sync Errors
- Per-room controls: show/hide in grid + include/exclude from All Off

---

## Requirements

### Hardware
- Raspberry Pi 4 (any RAM)
- [Official Raspberry Pi 7" Touchscreen](https://www.raspberrypi.com/products/raspberry-pi-touch-display/) (800×480)
- **Philips Hue Bridge v2** (the square white bridge) — on the same local network as the Pi

### Software
- Python 3.9+
- pip packages:

```bash
pip install kivy requests urllib3
```

---

## Hue Bridge Setup

Lumio talks to your lights through a **Philips Hue Bridge** — a small hub that connects to your router via Ethernet and controls all your Hue bulbs over Zigbee. You need a **v2 bridge** (square shape, released 2016+).

### What you need before running Lumio

1. **Hue Bridge v2** plugged into your router with an Ethernet cable and powered on
2. At least one Hue bulb paired to the bridge (done via the official Hue app)
3. Your rooms set up in the Hue app — Lumio mirrors whatever room/zone structure you've defined there
4. The bridge and the Pi (or dev machine) on the **same local network**

> The Hue app is only needed for initial bulb pairing and room setup. Once that's done, Lumio takes over and the Hue app is optional.

### Finding your bridge IP

Lumio's discovery script handles this automatically using Philips' mDNS broadcast. If auto-discovery fails (some router configs block mDNS), find the IP manually:

- Check your router's DHCP client list for a device named `Philips-hue`
- Or open the Hue app → **Settings → My Hue system → Hue Bridge → Network** — the IP is listed there

### One-time authentication

The Hue API requires a one-time button-press to grant API access. Lumio's setup script walks you through this automatically (see Setup step 3 below).

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/smallaxeit/lumio.git
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
python lumio.py
```

**Raspberry Pi (fullscreen):**

```bash
python lumio.py
```

The app runs directly on the framebuffer — true fullscreen with no desktop chrome. See [PI_SETUP.md](PI_SETUP.md) for autostart via systemd.

---

## Configuration

All settings are stored in `hue_settings.json` (auto-created, never committed):

| Key | Set by | Description |
|---|---|---|
| `bridge_ip` | `hue_discovery.py` | Local IP of your Hue Bridge |
| `username` | `hue_discovery.py` | Hue API key |
| `hidden_rooms` | Settings popup | Room IDs hidden from the grid |
| `exempt_rooms` | Settings popup | Room IDs excluded from the All Off button |
| `room_order` | Sort mode (▲▼) | Saved card order |
| `dark_mode` | Theme toggle | `true` = dark, `false` = light |
| `screen_brightness` | Settings popup | Pi backlight level (10–255) |
| `show_weather` | Settings popup | `true` / `false` |
| `latitude` | Auto (IP geolocation) | Used for weather — set on first run |
| `longitude` | Auto (IP geolocation) | Used for weather — set on first run |
| `city` | Auto (IP geolocation) | Displayed in weather card |
| `logging_enabled` | Settings popup | `true` / `false` — disables all logging |
| `log_max_mb` | Manual | Max local log size in MB before oldest entries are trimmed (default `5`) |
| `supabase_url` | Manual | Your Supabase project URL (optional — see below) |
| `supabase_key` | Manual | Your Supabase anon or service role key (optional) |

See `hue_settings.example.json` for the expected structure.

---

## Usage

| Action | Result |
|---|---|
| Tap a card | Toggle room on/off |
| Drag the slider | Adjust room brightness |
| Tap ↕ (header right) | Enter sort mode — sliders hidden, ▲▼ shown on each card |
| Tap ▲ or ▼ on a card | Move that card one row up or down; order saves immediately |
| Tap ✔ (replaces ↕ in sort mode) | Exit sort mode |
| ☰ button | Open settings popup |
| Dark Mode toggle (in settings) | Toggle dark/light theme (saved automatically) |
| Tap weather text | Open weather detail card |
| Tap Today or a forecast day | Open 24-hour hourly breakdown for that day |

---

## Weather

Lumio fetches local weather from **[Open-Meteo](https://open-meteo.com/)** — a free, open-source weather API that requires no account or API key.

### Location detection

On first launch, Lumio calls `http://ip-api.com/json` to determine your approximate location from your public IP address. The returned latitude, longitude, and city name are saved to `hue_settings.json` and reused on every subsequent start — no repeated geolocation calls.

If IP geolocation fails (offline, VPN, restrictive network), the weather feature simply stays hidden with no error. You can manually add coordinates to `hue_settings.json`:

```json
"latitude": 40.7128,
"longitude": -74.0060,
"city": "New York"
```

### What's shown

- **Header** — `72°F  Partly cloudy` (updates every 15 minutes)
- **Weather card** — tap the header text to open:
  - Current temp, condition, wind speed
  - 5-day forecast starting with Today — high/low, condition, precip chance, and a weather icon per tile
- **Day detail** — tap Today or any forecast day for a full 24-hour hourly view; Today's view starts at the current hour

### Disabling weather

Toggle **Show Weather** off in the ⚙ settings popup. The weather loop pauses immediately and the header clears.

---

## Supabase Logging (optional)

Lumio can sync your event log to a [Supabase](https://supabase.com) database. This is entirely optional — the app runs fine without it. When enabled, events are always written locally first (`hue_log.jsonl`) and synced to Supabase in the background. If the Pi is offline, entries queue locally and sync when connectivity returns. Successfully synced entries are removed from the local file.

### 1. Create a Supabase project

1. Go to [supabase.com](https://supabase.com) and sign in
2. Click **New project**, give it a name (e.g. `lumio`), choose a region close to you, set a database password
3. Wait for the project to provision (~1 min)

### 2. Create the `hue_log` table

In your project, open the **SQL Editor** and run:

```sql
create table hue_log (
  id         bigint generated always as identity primary key,
  ts         text,
  event      text,
  source     text,
  room       text,
  room_id    text,
  bri_pct    integer,
  owner_type text,
  detail     text,
  light      text,
  light_id   text
);
```

### 3. Get your credentials

In your project dashboard:

- **Project URL** — Settings → API → Project URL (looks like `https://xxxxxxxxxxxx.supabase.co`)
- **API key** — Settings → API → Project API keys → `anon` `public` key

> The anon key is safe for local-only use. If you want to restrict inserts to authenticated clients, enable RLS on the table and create a policy — but for a private Pi on your home network the anon key is fine.

### 4. Install the client library

```bash
pip install supabase
```

### 5. Add credentials to `hue_settings.json`

```json
"supabase_url": "https://xxxxxxxxxxxx.supabase.co",
"supabase_key": "your-anon-key-here"
```

Lumio will detect the credentials on next launch and start syncing automatically. No restart needed if you add credentials while the app is running — they take effect on the next app start.

### Disabling logging

Toggle **Enable Logging** off in the ⚙ settings popup. This stops all logging immediately — no new entries are written locally or sent to Supabase. Existing local entries are not deleted.

---

## Event Log

All light changes are written to `hue_log.jsonl` (one JSON object per line). This file is excluded from git.

**Room-level event:**
```json
{"ts":"2026-03-07T14:30:01.123Z","room":"Den","room_id":"3","event":"on","bri_pct":80,"source":"lumio"}
```

**External change (physical switch, voice, app):**
```json
{"ts":"2026-03-07T14:31:10.789Z","room":"Kitchen","room_id":"5","event":"off","bri_pct":0,"source":"external","owner_type":"device"}
```

**Source values:**

| Value | Meaning |
|---|---|
| `lumio` | Changed from this app |
| `external` + `device` | Physical switch or button |
| `external` + `app_instance` | Hue app, voice assistant, third-party |
| `external` + `bridge_home` | Schedule or automation |
| `system` | App start/stop, bridge connect/disconnect, errors |

---

## Security

**Your local network info is never stored in this repo.**

- `hue_settings.json` — contains your bridge IP, API key, and approximate location (lat/lon/city from IP geolocation). Listed in `.gitignore`. Never committed.
- `hue_log.jsonl` — contains usage data. Listed in `.gitignore`. Never committed.
- The Hue API key is a local-only credential. It only works on your LAN and grants control of your lights — it is not a password to any Philips account.
- The lat/lon stored for weather is approximate (city-level, derived from your public IP). No precise location data is used or stored.
- If you need to revoke Hue access, delete the API key from the Hue app under **Settings → My Hue system → Apps**.

---

## Project Structure

```
lumio/
├── lumio.py                # Entry point — RoomGrid, ErrorScreen, LumioApp
├── theme.py                # Palette, mutable color container (C), shared constants
├── ui_cards.py             # RoomCard, LightRow, RoomDetailModal
├── ui_panels.py            # SettingsPopup, WeatherModal, DayDetailModal, HeaderBar
├── lumio_api.py            # HueAPI — Hue local REST + CLIP v2 SSE client
├── lumio_log.py            # Event logging (local JSONL) and Supabase sync
├── lumio_weather.py        # Open-Meteo weather fetching and IP geolocation
├── lumio_brightness.py     # Pi backlight brightness read/write
├── hue_discovery.py        # Bridge discovery and authentication (one-time setup)
├── assets/
│   └── weather/            # Meteocons PNG icons (MIT) — mapped to WMO weather codes
├── hue_settings.example.json  # Settings template (safe to commit)
├── hue_settings.json       # Your credentials and preferences (git-ignored)
├── hue_log.jsonl           # Event log (git-ignored)
├── PI_SETUP.md             # Raspberry Pi environment setup guide
├── Lumio.sln               # Visual Studio solution
├── Lumio.pyproj            # Visual Studio Python project
└── .gitignore
```

---

## Raspberry Pi Setup

See **[PI_SETUP.md](PI_SETUP.md)** for a full walkthrough: OS install, dependencies, cloning the repo, Hue authentication, fullscreen config, and auto-start on boot.

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
git tag -a v0.2.0 -m "Add clock, weather, brightness control, theme persistence"
git push origin v0.2.0
```

### Changelog

## [0.6.3] - 2026-06-06
### Changed
- Sort ▲▼ buttons are now side-by-side (▲ left, ▼ right) and larger (20sp) — better touch targets on Pi
- Long-press to enter sort mode removed entirely; ↕ header button is the only entry point
- ▲▼ buttons now use the symbol font (Segoe UI Symbol / DejaVu Sans) so glyphs render on both Windows and Pi

## [0.6.2] - 2026-06-06
### Changed
- Sort mode now uses ▲▼ per-card buttons instead of long-press-to-swap — eliminates touch-jitter failures on Pi framebuffer
- ↕ sort button is now always visible in the header right (was hidden until sort mode was active); tap to enter, becomes ✔ to exit
- Weather label font bumped to 19sp for easier reading

## [0.6.1] - 2026-06-06
### Fixed
- Room sort replaced drag-to-reorder with long-press-to-swap — eliminates visual artifacts and unresponsive cards caused by unreliable touch grab on Pi framebuffer. Long-press card A to select (highlights blue), long-press card B to swap; long-press selected card to deselect.

## [0.6.0] - 2026-03-26
### Added
- Today tile added as the first card in the 5-day forecast grid (day 6 dropped to keep the grid at 5 tiles)
- Weather icons (Meteocons, MIT) — small PNG icon in each forecast tile and in the day detail header, mapped to WMO weather codes
- Full 24-hour hourly forecast — previously limited to 6am–10pm; today's view starts at the current hour, future days show all 24 hours

## [0.5.1] - 2026-03-12
### Fixed
- Drag-to-reorder on Pi touchscreen — long-press now grabs the touch immediately so subsequent move events route to the drag handler instead of ScrollView, fixing the cascade/freeze behaviour
- All 10 rooms now fit on the 480px display without requiring a scroll (header 50px, cards 80px)

### Changed
- Room card layout redesigned: horizontal split — left 70% holds room name + brightness slider, right 30% is a dedicated ON/OFF button inset with padding; slider and button no longer overlap, reducing accidental presses
- Weather text in header: larger (16sp), bold, full-contrast colour — easier to read and tap
- Header ☰ button colour raised to full contrast
- `.venv/` added to `.gitignore` to prevent the virtual environment from being indexed or committed

## [0.5.0] - 2026-03-09
### Changed
- Split `hue_app.py` into eight focused modules: `lumio.py`, `theme.py`, `ui_cards.py`, `ui_panels.py`, `lumio_api.py`, `lumio_log.py`, `lumio_weather.py`, `lumio_brightness.py`
- Entry point renamed from `hue_app.py` to `lumio.py`
- Settings button changed from ⚙ to ☰; weather label moved immediately right of it
- Dark/light mode toggle moved into the settings popup (removed standalone ☾/☀ header button)
- Sort mode entered by long-pressing a card; ✔ button in header exits sort mode (was a separate ✎ header button always visible)

## [0.4.1] - 2026-03-09
### Fixed
- Main grid and settings scrolling — removed touch grab from `RoomCard` and rewrote `_TappableRow` without `ButtonBehavior` so `ScrollView` can scroll freely
- SSE state changes now immediately reflected in UI without waiting for API round-trip
- Slider no longer triggers API or turns lights on when the room is off
- Weather and day-detail modals pinned to top of screen — no dead space above card
- Settings popup pinned to top — Done button fully visible
- Theme icon (☾/☀) now correct on startup when dark mode is saved
- Pi backlight path auto-detected (`rpi_backlight` or `10-0045`); falls back to `sudo tee` if direct write is blocked by permissions

### Changed
- Sort/reorder button icon changed from ✎ to ⇅
- Settings button moved to far right of header
- Clock removed from header (code preserved, commented out)
- Pi: fullscreen mode and cursor hidden when `DEV_WINDOW_SIZE = None`

## [0.4.0] - 2026-03-07
### Added
- ⏻ All Off button in header — turns off all non-exempt rooms in one tap
- Per-room "All Off" column in settings — uncheck to exempt a room from the All Off button
- `exempt_rooms` key in `hue_settings.json`

## [0.3.0] - 2026-03-07
### Added
- Optional Supabase sync — events write to `hue_log.jsonl` locally first, then sync to Supabase in the background; local entries removed after successful upload
- Log file size cap (`log_max_mb`, default 5 MB) — oldest entries trimmed automatically on startup
- Enable Logging toggle in settings — disables all logging when off
- `supabase_url`, `supabase_key`, `logging_enabled`, `log_max_mb` keys in `hue_settings.json`

## [0.2.0] - 2026-03-07
### Added
- Live clock in header (left side)
- Local weather in header (right side) — temp + condition, tappable
- Weather detail card — 5-day forecast with precip chance
- Hourly day detail — tap any forecast day for 6am–10pm breakdown
- Screen brightness slider in settings (Pi backlight)
- Show/hide weather toggle in settings
- Dark/light theme now persists across restarts

## [0.1.0] - 2026-03-07
### Added
- Initial release — room grid, SSE, logging

Create a **GitHub Release** from each tag to attach release notes and make versions browsable at `github.com/smallaxeit/lumio/releases`.

---

## License

MIT
