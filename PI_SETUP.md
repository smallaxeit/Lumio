# Lumio — Raspberry Pi Setup Guide

Tested on **Raspberry Pi 4** with **Raspberry Pi OS Bookworm** (64-bit Desktop) and the official **7" DSI touchscreen**.

---

## 1. Flash the OS

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/) to write **Raspberry Pi OS (64-bit) with Desktop** to your SD card.

In the Imager's advanced options (gear icon) before writing:
- Set hostname, username, and password
- Enable SSH
- Configure Wi-Fi if not using Ethernet

Boot the Pi and connect via SSH or directly with a keyboard/monitor.

---

## 2. Update the system

```bash
sudo apt update && sudo apt upgrade -y
```

---

## 3. Install system dependencies for Kivy

```bash
sudo apt install -y \
  python3-pip python3-dev python3-venv \
  libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev \
  libgles2-mesa-dev libgl1-mesa-dev \
  libmtdev-dev libjpeg-dev \
  xclip xsel
```

---

## 4. Clone the repo

```bash
cd ~
git clone https://github.com/smallaxeit/lumio.git
cd lumio
```

---

## 5. Create a virtual environment and install packages

Raspberry Pi OS Bookworm uses an externally managed Python — a virtual environment is the cleanest approach.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install kivy requests urllib3
```

For Supabase logging (optional):

```bash
pip install supabase
```

> The venv only needs to be activated once per terminal session. The autostart script below activates it automatically.

---

## 6. Authenticate with your Hue Bridge

Make sure your Hue Bridge is powered on and connected to the same network as the Pi.

```bash
source .venv/bin/activate   # if not already active
python hue_discovery.py
```

When prompted, **press the physical link button on top of the Hue Bridge**, then press Enter. The script saves your credentials to `hue_settings.json` and prints all discovered lights and rooms.

---

## 7. Configure for fullscreen

Open `hue_app.py` and change line 32:

```python
# Before (dev mode):
DEV_WINDOW_SIZE = (800, 480)

# After (Pi fullscreen):
DEV_WINDOW_SIZE = None
```

---

## 8. Test the app

From the Pi desktop terminal (or SSH with a display):

```bash
cd ~/lumio
source .venv/bin/activate
DISPLAY=:0 python hue_app.py
```

The app should launch fullscreen on the touchscreen. Touch and slider input should work out of the box with the official DSI display.

> If running headless over SSH, you need `DISPLAY=:0` to target the Pi's own screen. If you're running the command directly in a terminal on the Pi desktop, `DISPLAY=:0` can be omitted.

---

## 9. Auto-start on boot

Create an autostart entry so Lumio launches automatically when the desktop loads.

```bash
mkdir -p ~/.config/autostart
nano ~/.config/autostart/lumio.desktop
```

Paste the following (adjust username if not `pi`):

```ini
[Desktop Entry]
Type=Application
Name=Lumio
Exec=/home/pi/lumio/.venv/bin/python /home/pi/lumio/hue_app.py
Environment=DISPLAY=:0
X-GNOME-Autostart-enabled=true
```

Save and exit (`Ctrl+O`, `Ctrl+X`). Lumio will now launch on every boot after the desktop loads.

> **Hide the taskbar** for a cleaner kiosk look: right-click the taskbar → Panel Settings → Advanced → check "Minimise panel when not in use" or set size to 0.

---

## 10. Returning to the desktop

Lumio has no close button by design. To exit:

- **Long-press the clock** (top-left, 1.5 seconds) — cleanly exits the app
- Or SSH in and run `pkill -f hue_app.py`

---

## Troubleshooting

{"hidden_rooms": [], "bridge_ip": "192.168.0.145", "username": "H2c2I0IYrqHx0830BiZedvPJTuhuvDcpxfLhyf1v", "room_order": ["1", "83", "6", "82", "84", "85", "4", "2", "5", "3"], "latitude": 40.0732, "longitude": -82.4017, "city": "Newark", "dark_mode": true, "screen_brightness": 200, "show_weather": true, "logging_enabled": true, "log_max_mb": 5, "supabase_url": "https://bbzdxoruflcfuwpqekar.supabase.co", "supabase_key": "sb_publishable_4VhzicZzlVuMnbEaotI_cQ_MHUFqnVV", "show_sync_errors": true, "exempt_rooms": ["5", "2"]}

**Kivy fails to find a display:**
Make sure the desktop has fully loaded before Lumio tries to start. Add a short delay to the autostart if needed:

```ini
Exec=bash -c "sleep 5 && /home/pi/lumio/.venv/bin/python /home/pi/lumio/hue_app.py"
```

**Touch input not working:**
The official 7" DSI display registers as `mtdev` input. Kivy picks it up automatically. If not, check `dmesg | grep input` to find the device name.

**Screen rotation:**
If the display is mounted upside down, add to `/boot/firmware/config.txt`:

```
display_rotate=2
```

**App won't connect to bridge:**
Verify the bridge IP hasn't changed — check your router's DHCP table and update `bridge_ip` in `hue_settings.json` if needed.
