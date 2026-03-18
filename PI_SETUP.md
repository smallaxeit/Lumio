# Lumio — Raspberry Pi Setup Guide

Tested on **Raspberry Pi 4** with **Raspberry Pi OS Bookworm** (64-bit Desktop) and the official **7" DSI touchscreen**.

---

## 1. Flash the OS

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/) to write **Raspberry Pi OS (64-bit) with Desktop** to your SD card.

In the Imager's advanced options before writing:
- Set hostname, username, and password
- **Enable SSH** — do this now or you'll lose remote access once the kiosk starts
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

Raspberry Pi OS Bookworm uses an externally managed Python — a virtual environment is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install kivy requests urllib3
```

For Supabase logging (optional):

```bash
pip install supabase
```

---

## 6. Authenticate with your Hue Bridge

Make sure your Hue Bridge is powered on and connected to the same network as the Pi.

```bash
source .venv/bin/activate   # if not already active
python hue_discovery.py
```

When prompted, **press the physical link button on top of the Hue Bridge**, then press Enter. The script saves your credentials to `hue_settings.json` and prints all discovered lights and rooms.

---

## 7. Grant display permissions

The app renders directly on the framebuffer (DRM/KMS) for true fullscreen. Your user needs to be in the `render` and `video` groups:

```bash
sudo usermod -a -G render,video <username>
```

Verify:

```bash
groups <username>
```

This takes effect after a reboot.

---

## 8. Install the systemd service

The repo includes a ready-made service file. Copy it to the systemd directory and edit it with your username:

```bash
sudo cp ~/lumio/lumio.service /etc/systemd/system/lumio.service
sudo nano /etc/systemd/system/lumio.service
```

Replace all instances of `<username>` with your Pi username (e.g. `pi`, `pi1`). Save and exit (`Ctrl+O`, `Ctrl+X`).

Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable lumio.service
sudo systemctl start lumio.service
```

The app will now launch automatically on every boot.

---

## 9. Test

Check the service is running:

```bash
sudo systemctl status lumio.service
```

View live logs:

```bash
journalctl -u lumio.service -f
```

---

## Remote Access & Support

### SSH (always available)

SSH works regardless of what is on the screen — use it as your primary management tool:

```bash
ssh <username>@<pi-ip>
```

Find the Pi's IP:

```bash
hostname -I
```

Set a static IP or DHCP reservation on your router so it doesn't change.

### VNC (desktop access)

VNC shows the X11 desktop session. Since Lumio runs on the framebuffer (not X11), you need to stop the service first:

```bash
# SSH in, then:
sudo systemctl stop lumio.service
sudo systemctl start lightdm
```

Then connect with your VNC client. When done:

```bash
sudo systemctl start lumio.service
# or just reboot
```

### Emergency terminal (no SSH)

Plug a keyboard into the Pi and press **Ctrl+Alt+F2** to switch to a virtual terminal outside the kiosk.

---

## Service Management

| Task | Command |
|---|---|
| Stop app | `sudo systemctl stop lumio.service` |
| Start app | `sudo systemctl start lumio.service` |
| Restart app | `sudo systemctl restart lumio.service` |
| Disable autostart | `sudo systemctl disable lumio.service` |
| Re-enable autostart | `sudo systemctl enable lumio.service` |
| Check status | `sudo systemctl status lumio.service` |
| Live logs | `journalctl -u lumio.service -f` |

---

## Troubleshooting

**`Could not queue pageflip: -13` in logs:**
Permission denied on the GPU device. Make sure your user is in the `render` and `video` groups (step 7) and reboot.

**Grey screen in VNC:**
Lumio renders on the framebuffer, not X11. Stop the service and start lightdm before connecting with VNC (see Remote Access above).

**App starts but won't connect to bridge:**
Verify the bridge IP hasn't changed — check your router's DHCP table and update `bridge_ip` in `hue_settings.json` if needed.

**Touch input not working:**
The official 7" DSI display registers as `mtdev` input. Kivy picks it up automatically. If not, check `dmesg | grep input` to find the device name.

**Screen rotation:**
If the display is mounted upside down, add to `/boot/firmware/config.txt`:

```
display_rotate=2
```

**Kivy fails to start (display not ready):**
Add a startup delay to the service file:

```ini
ExecStartPre=/bin/sleep 5
```
