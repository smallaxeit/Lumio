#!/usr/bin/env python3
"""
Lumio — Kivy touchscreen app for Raspberry Pi 4
Room grid with on/off toggle, brightness slider, and drag-to-reorder.
Optimised for the official 7" Pi touchscreen (800×480).

Requirements:
    pip install kivy requests

Run on Pi (fullscreen):
    DISPLAY=:0 python hue_app.py
"""

import json
import os
import platform
import threading
import time
import uuid
from datetime import datetime

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from supabase import create_client as _sb_create
    _SUPABASE_LIB = True
except ImportError:
    _SUPABASE_LIB = False

DEV_WINDOW_SIZE = (800, 480)   # set None on Pi to use display native size

# Configure Kivy before importing anything else from kivy
from kivy.config import Config
Config.set('input', 'mouse', 'mouse,disable_multitouch')
Config.set('input', 'wm_touch', 'wm_touch')
Config.set('input', 'wm_pen',   'wm_pen')
if DEV_WINDOW_SIZE:
    Config.set('graphics', 'width',     str(DEV_WINDOW_SIZE[0]))
    Config.set('graphics', 'height',    str(DEV_WINDOW_SIZE[1]))
    Config.set('graphics', 'resizable', '0')

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.modalview import ModalView
from kivy.uix.popup import Popup
from kivy.uix.slider import Slider
from kivy.uix.scrollview import ScrollView

# ── App config ────────────────────────────────────────────────────────────────

SETTINGS_FILE    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hue_settings.json")
LOG_FILE         = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hue_log.jsonl")
BACKLIGHT_PATH   = "/sys/class/backlight/rpi_backlight/brightness"
REFRESH_INTERVAL = 10
CARD_HEIGHT      = 82
CARD_SPACING     = 4
CARD_COLS        = 2

# ── Palettes ──────────────────────────────────────────────────────────────────

PALETTE_LIGHT = dict(
    BG          = (0.94, 0.94, 0.96, 1),
    HEADER_BG   = (0.98, 0.98, 1.00, 1),
    CARD_OFF    = (1.00, 1.00, 1.00, 1),
    CARD_ON     = (0.88, 0.94, 1.00, 1),
    CARD_TARGET = (0.78, 0.88, 1.00, 1),
    BTN_ON      = (0.00, 0.48, 1.00, 1),
    BTN_OFF     = (0.50, 0.50, 0.56, 1),
    BTN_EDIT    = (0.40, 0.20, 0.78, 1),
    TEXT        = (0.11, 0.11, 0.12, 1),
    TEXT_ON     = (0.11, 0.11, 0.12, 1),
    SUBTEXT     = (0.43, 0.43, 0.46, 1),
    ERROR       = (0.86, 0.20, 0.18, 1),
)

PALETTE_DARK = dict(
    BG          = (0.05, 0.05, 0.08, 1),
    HEADER_BG   = (0.08, 0.08, 0.13, 1),
    CARD_OFF    = (0.11, 0.11, 0.17, 1),
    CARD_ON     = (0.10, 0.18, 0.32, 1),
    CARD_TARGET = (0.10, 0.24, 0.42, 1),
    BTN_ON      = (0.00, 0.48, 1.00, 1),
    BTN_OFF     = (0.18, 0.18, 0.28, 1),
    BTN_EDIT    = (0.40, 0.20, 0.78, 1),
    TEXT        = (0.93, 0.93, 0.97, 1),
    TEXT_ON     = (0.60, 0.82, 1.00, 1),
    SUBTEXT     = (0.42, 0.42, 0.56, 1),
    ERROR       = (0.88, 0.28, 0.28, 1),
)

_DARK_MODE = False

def set_theme(palette: dict):
    global C_BG, C_HEADER_BG, C_CARD_OFF, C_CARD_ON, C_CARD_TARGET
    global C_BTN_ON, C_BTN_OFF, C_BTN_EDIT, C_TEXT, C_TEXT_ON, C_SUBTEXT, C_ERROR
    C_BG          = palette['BG']
    C_HEADER_BG   = palette['HEADER_BG']
    C_CARD_OFF    = palette['CARD_OFF']
    C_CARD_ON     = palette['CARD_ON']
    C_CARD_TARGET = palette['CARD_TARGET']
    C_BTN_ON      = palette['BTN_ON']
    C_BTN_OFF     = palette['BTN_OFF']
    C_BTN_EDIT    = palette['BTN_EDIT']
    C_TEXT        = palette['TEXT']
    C_TEXT_ON     = palette['TEXT_ON']
    C_SUBTEXT     = palette['SUBTEXT']
    C_ERROR       = palette['ERROR']

set_theme(PALETTE_LIGHT)


# ── Symbol font (for moon/sun icons) ──────────────────────────────────────────

def _find_symbol_font() -> str:
    candidates = {
        'Windows': 'C:/Windows/Fonts/seguisym.ttf',
        'Linux':   '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        'Darwin':  '/System/Library/Fonts/Apple Symbols.ttf',
    }
    path = candidates.get(platform.system(), '')
    return path if path and os.path.exists(path) else ''

SYMBOL_FONT = _find_symbol_font()


# ── Settings persistence ───────────────────────────────────────────────────────

def load_settings() -> dict:
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"hidden_rooms": [], "room_order": []}

def save_settings(settings: dict) -> None:
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f)


# ── Event logger ───────────────────────────────────────────────────────────────

_log_lock           = threading.Lock()
_logging_enabled    = True
_huecontrol_recent  = {}   # gid → time.time() of last HueControl command
_sse_log_recent     = {}   # gid → time.time() of last external SSE log


def _mark_huecontrol(gid: str) -> None:
    _huecontrol_recent[gid] = time.time()


def _is_huecontrol_recent(gid: str, window: float = 10.0) -> bool:
    return (time.time() - _huecontrol_recent.get(gid, 0)) < window


def _should_log_sse(gid: str, window: float = 5.0) -> bool:
    """True if enough time has passed since we last logged an external SSE event for this gid."""
    now = time.time()
    if now - _sse_log_recent.get(gid, 0) < window:
        return False
    _sse_log_recent[gid] = now
    return True
_supabase_client = None
_outbox_wake     = threading.Event()
_outbox_started  = False
_on_sync_error   = None   # callable(msg) registered by RoomGrid


def init_logging(settings: dict) -> None:
    """Initialise logging subsystem from settings. Call once at startup."""
    global _logging_enabled, _supabase_client, _outbox_started
    _logging_enabled = settings.get("logging_enabled", True)
    if not _logging_enabled:
        return
    _trim_log_file(settings.get("log_max_mb", 5))
    url = settings.get("supabase_url", "")
    key = settings.get("supabase_key", "")
    if url and key and _SUPABASE_LIB:
        try:
            _supabase_client = _sb_create(url, key)
            print("[logging] Supabase client initialised")
        except Exception as exc:
            print(f"[logging] Supabase init failed: {exc}")
            _supabase_client = None
    if _supabase_client and not _outbox_started:
        _outbox_started = True
        threading.Thread(target=_outbox_worker, daemon=True).start()


def _trim_log_file(max_mb: float = 5.0) -> None:
    """Trim oldest JSONL entries if the log file exceeds max_mb."""
    max_bytes = int(max_mb * 1024 * 1024)
    with _log_lock:
        if not os.path.exists(LOG_FILE):
            return
        if os.path.getsize(LOG_FILE) <= max_bytes:
            return
        try:
            with open(LOG_FILE) as f:
                lines = [l for l in f if l.strip()]
            while lines and sum(len(l.encode()) for l in lines) > max_bytes:
                lines.pop(0)
            with open(LOG_FILE, "w") as f:
                f.writelines(lines)
            print(f"[logging] log trimmed to {len(lines)} entries")
        except Exception as exc:
            print(f"[logging] trim failed: {exc}")


def _outbox_worker() -> None:
    """Background thread: drain JSONL outbox into Supabase every 60s or on wake."""
    while True:
        _outbox_wake.wait(timeout=60)
        _outbox_wake.clear()
        if _supabase_client and _logging_enabled:
            _flush_to_supabase()


def _flush_to_supabase() -> None:
    """Read JSONL entries, batch-insert into Supabase, remove sent entries on success."""
    with _log_lock:
        if not os.path.exists(LOG_FILE):
            return
        try:
            with open(LOG_FILE) as f:
                raw_lines = [l.strip() for l in f if l.strip()]
        except Exception:
            return

    if not raw_lines:
        return

    entries, lids = [], []
    for line in raw_lines:
        try:
            e = json.loads(line)
            lids.append(e.get("_lid"))
            entries.append({k: v for k, v in e.items() if k != "_lid"})
        except Exception:
            pass

    if not entries:
        return

    try:
        _supabase_client.table("hue_log").insert(entries).execute()
    except Exception as exc:
        print(f"[logging] Supabase flush failed: {exc}")
        if _on_sync_error:
            _on_sync_error(str(exc))
        return

    sent = set(lids)
    with _log_lock:
        try:
            with open(LOG_FILE) as f:
                current = [l.strip() for l in f if l.strip()]
            remaining = []
            for line in current:
                try:
                    if json.loads(line).get("_lid") not in sent:
                        remaining.append(line)
                except Exception:
                    remaining.append(line)
            with open(LOG_FILE, "w") as f:
                for line in remaining:
                    f.write(line + "\n")
        except Exception as exc:
            print(f"[logging] JSONL cleanup failed: {exc}")


def log_event(room: str, room_id: str, event: str, bri_pct: int,
              source: str, owner_type: str = None, ts: str = None, **extra) -> None:
    """Append one JSONL line to hue_log.jsonl (thread-safe)."""
    if not _logging_enabled:
        return
    entry = {
        "_lid":    str(uuid.uuid4()),
        "ts":      ts or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "room":    room,
        "room_id": room_id,
        "event":   event,
        "bri_pct": bri_pct,
        "source":  source,
    }
    if owner_type:
        entry["owner_type"] = owner_type
    entry.update(extra)
    with _log_lock:
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    if _supabase_client:
        _outbox_wake.set()


def log_system(event: str, detail: str = None) -> None:
    """Append a system-level event (connect, disconnect, error, start, stop)."""
    if not _logging_enabled:
        return
    entry = {
        "_lid":   str(uuid.uuid4()),
        "ts":     datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "event":  event,
        "source": "system",
    }
    if detail:
        entry["detail"] = detail
    with _log_lock:
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    if _supabase_client:
        _outbox_wake.set()


def rooms_ordered(groups: dict, order: list) -> list:
    """Return Room-type groups in the given order; unknowns appended alphabetically."""
    all_rooms = {gid: g for gid, g in groups.items() if g.get("type") == "Room"}
    ordered   = [(gid, all_rooms[gid]) for gid in order if gid in all_rooms]
    seen      = {gid for gid, _ in ordered}
    for gid, g in sorted(all_rooms.items(), key=lambda x: x[1].get("name", "")):
        if gid not in seen:
            ordered.append((gid, g))
    return ordered


# ── Screen brightness ─────────────────────────────────────────────────────────

def get_brightness() -> int:
    """Read current backlight brightness (0–255). Returns 200 on dev machines."""
    try:
        with open(BACKLIGHT_PATH) as f:
            return int(f.read().strip())
    except Exception:
        return 200

def set_brightness(value: int) -> None:
    """Write backlight brightness (10–255). Silent no-op on dev machines."""
    try:
        with open(BACKLIGHT_PATH, "w") as f:
            f.write(str(max(10, min(255, int(value)))))
    except Exception:
        pass


# ── Weather ────────────────────────────────────────────────────────────────────

_WMO_CODES = {
    0: "Clear",
    1: "Mostly clear",   2: "Partly cloudy",        3: "Overcast",
    45: "Foggy",         48: "Icy fog",
    51: "Light drizzle", 53: "Drizzle",              55: "Heavy drizzle",
    61: "Light rain",    63: "Rain",                 65: "Heavy rain",
    71: "Light snow",    73: "Snow",                 75: "Heavy snow",    77: "Sleet",
    80: "Showers",       81: "Rain showers",         82: "Heavy showers",
    85: "Snow showers",  86: "Heavy snow showers",
    95: "Thunderstorm",  96: "Thunderstorm + hail",  99: "Heavy thunderstorm",
}

_WMO_SHORT = {
    0: "Clear",      1: "Mostly Clr", 2: "P. Cloudy",  3: "Overcast",
    45: "Foggy",     48: "Icy Fog",
    51: "Drizzle",   53: "Drizzle",   55: "Drizzle",
    61: "Lt. Rain",  63: "Rain",      65: "Rain",
    71: "Lt. Snow",  73: "Snow",      75: "Snow",      77: "Sleet",
    80: "Showers",   81: "Showers",   82: "Showers",
    85: "Sn Shower", 86: "Sn Shower",
    95: "T-Storm",   96: "T-Storm",   99: "T-Storm",
}

def _fetch_weather(lat: float, lon: float) -> dict:
    """Return weather dict with current + 5-day forecast, or None on error."""
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&current_weather=true"
            "&daily=temperature_2m_max,temperature_2m_min,weathercode,precipitation_probability_max"
            "&temperature_unit=fahrenheit&wind_speed_unit=mph"
            "&timezone=auto&forecast_days=6"
        )
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        body = r.json()
        cw   = body["current_weather"]
        temp = round(cw["temperature"])
        code = int(cw["weathercode"])
        cond = _WMO_CODES.get(code, "")

        daily = []
        d = body.get("daily", {})
        precip_list = d.get("precipitation_probability_max", [])
        for i, date_str in enumerate(d.get("time", [])):
            wcode  = int(d["weathercode"][i])
            precip = int(precip_list[i]) if i < len(precip_list) and precip_list[i] is not None else 0
            daily.append({
                "date":       date_str,
                "day":        datetime.fromisoformat(date_str).strftime("%a"),
                "high":       round(d["temperature_2m_max"][i]),
                "low":        round(d["temperature_2m_min"][i]),
                "condition":  _WMO_CODES.get(wcode, ""),
                "cond_short": _WMO_SHORT.get(wcode, ""),
                "precip_pct": precip,
            })

        return {
            "label":     f"{temp}°F  {cond}" if cond else f"{temp}°F",
            "temp":      temp,
            "condition": cond,
            "wind_mph":  round(cw["windspeed"]),
            "daily":     daily,
        }
    except Exception:
        return None

def _fetch_hourly(lat: float, lon: float, date_str: str) -> list:
    """Fetch hourly forecast for a single date (6am–10pm). Returns list of dicts or None."""
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&hourly=temperature_2m,weathercode,precipitation_probability,windspeed_10m"
            "&temperature_unit=fahrenheit&wind_speed_unit=mph"
            f"&timezone=auto&start_date={date_str}&end_date={date_str}"
        )
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        h = r.json()["hourly"]
        precip_list = h.get("precipitation_probability", [])
        hours = []
        for i, ts in enumerate(h.get("time", [])):
            dt     = datetime.fromisoformat(ts)
            precip = int(precip_list[i]) if i < len(precip_list) and precip_list[i] is not None else 0
            hours.append({
                "hour":       dt.hour,
                "time":       dt.strftime("%I %p").lstrip("0"),
                "temp":       round(h["temperature_2m"][i]),
                "condition":  _WMO_CODES.get(int(h["weathercode"][i]), ""),
                "precip_pct": precip,
                "wind_mph":   round(h["windspeed_10m"][i]),
            })
        return hours
    except Exception:
        return None


def _resolve_location(settings: dict) -> tuple:
    """Return (lat, lon) from saved settings or IP geolocation. Updates settings in-place."""
    if settings.get("latitude") and settings.get("longitude"):
        return float(settings["latitude"]), float(settings["longitude"])
    try:
        r = requests.get("http://ip-api.com/json", timeout=6)
        r.raise_for_status()
        data = r.json()
        if data.get("status") == "success":
            lat, lon = data["lat"], data["lon"]
            settings["latitude"]  = lat
            settings["longitude"] = lon
            settings["city"]      = data.get("city", "")
            save_settings(settings)
            return lat, lon
    except Exception:
        pass
    return None, None


# ── Hue API wrapper ───────────────────────────────────────────────────────────

class HueAPI:
    """Minimal Hue local REST client."""

    def __init__(self):
        if not os.path.exists(SETTINGS_FILE):
            raise FileNotFoundError(
                f"Settings not found: {SETTINGS_FILE}\n"
                "Run hue_discovery.py first to authenticate."
            )
        with open(SETTINGS_FILE) as fh:
            cfg = json.load(fh)
        if not cfg.get("bridge_ip") or not cfg.get("username"):
            raise FileNotFoundError(
                "Bridge credentials missing from hue_settings.json.\n"
                "Run hue_discovery.py first to authenticate."
            )
        self.ip       = cfg["bridge_ip"]
        self.username = cfg["username"]
        self._base    = f"http://{self.ip}/api/{self.username}"

    def get_groups(self) -> dict:
        r = requests.get(f"{self._base}/groups", timeout=4)
        r.raise_for_status()
        return r.json()

    def set_group_on(self, group_id: str, on: bool) -> None:
        requests.put(
            f"{self._base}/groups/{group_id}/action",
            json={"on": on}, timeout=4,
        )

    def set_group_brightness(self, group_id: str, bri: int) -> None:
        """Set brightness (1–254), turning the group on in the same call."""
        requests.put(
            f"{self._base}/groups/{group_id}/action",
            json={"on": True, "bri": max(1, min(254, bri))},
            timeout=4,
        )

    def get_light(self, light_id: str) -> dict:
        r = requests.get(f"{self._base}/lights/{light_id}", timeout=4)
        r.raise_for_status()
        return r.json()

    def set_light_on(self, light_id: str, on: bool) -> None:
        requests.put(
            f"{self._base}/lights/{light_id}/state",
            json={"on": on}, timeout=4,
        )

    def set_light_brightness(self, light_id: str, bri: int) -> None:
        requests.put(
            f"{self._base}/lights/{light_id}/state",
            json={"on": True, "bri": max(1, min(254, bri))}, timeout=4,
        )

    def get_group(self, group_id: str) -> dict:
        r = requests.get(f"{self._base}/groups/{group_id}", timeout=4)
        r.raise_for_status()
        return r.json()

    def event_stream(self):
        """Generator yielding parsed CLIP v2 SSE event lists. Reconnects on error."""
        url     = f"https://{self.ip}/eventstream/clip/v2"
        headers = {"hue-application-key": self.username, "Accept": "text/event-stream"}
        while True:
            try:
                with requests.get(url, headers=headers, stream=True,
                                  verify=False, timeout=(5, None)) as resp:
                    yield {"_sse": "connected"}
                    for line in resp.iter_lines():
                        if line and line.startswith(b"data:"):
                            try:
                                yield json.loads(line[5:].strip())
                            except json.JSONDecodeError:
                                pass
            except Exception as exc:
                yield {"_sse": "disconnected", "_error": str(exc)}
            time.sleep(5)


# ── LightRow ──────────────────────────────────────────────────────────────────

class LightRow(BoxLayout):
    """Individual-light control row used inside RoomDetailModal."""

    SLIDER_DEBOUNCE = 0.35

    def __init__(self, light_id: str, data: dict, api,
                 room_name: str = "", room_id: str = "", **kwargs):
        super().__init__(
            orientation="vertical",
            padding=[12, 6, 10, 6],
            spacing=2,
            size_hint_y=None,
            height=CARD_HEIGHT,
            **kwargs,
        )
        self.light_id   = light_id
        self.api        = api
        self._room_name = room_name
        self._room_id   = room_id
        self._pending   = False
        self._slider_ev = None
        self._updating  = False

        state        = data.get("state", {})
        self._is_on  = state.get("on", False)
        self._bri    = state.get("bri", 254)
        self._name   = data.get("name", "Light")

        with self.canvas.before:
            self._bg_color = Color(*self._card_rgba())
            self._bg_rect  = RoundedRectangle(radius=[8], pos=self.pos, size=self.size)
        self.bind(pos=self._sync_bg, size=self._sync_bg)

        top = BoxLayout(orientation="horizontal", spacing=8, size_hint_y=0.52)

        self.name_lbl = Label(
            text=self._name,
            font_size="16sp",
            bold=True,
            color=self._name_rgba(),
            halign="left",
            valign="middle",
            size_hint_x=0.68,
        )
        self.name_lbl.bind(size=lambda w, _: setattr(w, "text_size", (w.width, None)))

        self.btn = Button(
            text="ON" if self._is_on else "OFF",
            font_size="14sp",
            bold=True,
            size_hint_x=0.32,
            background_normal="",
            background_down="",
            background_color=C_BTN_ON if self._is_on else C_BTN_OFF,
            color=(1, 1, 1, 1),
        )
        self.btn.bind(on_release=self._handle_toggle)

        top.add_widget(self.name_lbl)
        top.add_widget(self.btn)

        bri_row = BoxLayout(orientation="horizontal", size_hint_y=0.48, spacing=4)
        self.slider = Slider(
            min=1, max=254, value=self._bri,
            cursor_size=(28, 28),
        )
        self.slider.bind(value=self._on_slider_move)
        self.pct_lbl = Label(
            text=f"{round(self._bri / 254 * 100)}%",
            font_size="13sp",
            color=C_SUBTEXT,
            size_hint=(None, 1),
            width=40,
            halign="right",
            valign="middle",
        )
        self.pct_lbl.bind(size=lambda w, _: setattr(w, "text_size", (w.width, None)))
        bri_row.add_widget(self.slider)
        bri_row.add_widget(self.pct_lbl)

        self.add_widget(top)
        self.add_widget(bri_row)

    def _card_rgba(self):
        return C_CARD_ON if self._is_on else C_CARD_OFF

    def _name_rgba(self):
        return C_TEXT_ON if self._is_on else C_TEXT

    def _sync_bg(self, *_):
        self._bg_rect.pos  = self.pos
        self._bg_rect.size = self.size

    def _handle_toggle(self, *_):
        if self._pending:
            return
        self._pending = True
        new_state = not self._is_on
        self._apply_on_state(new_state)
        threading.Thread(target=self._send_toggle, args=(new_state,), daemon=True).start()

    def _send_toggle(self, new_state: bool):
        _mark_huecontrol(self._room_id)
        try:
            self.api.set_light_on(self.light_id, new_state)
            log_event(self._room_name, self._room_id,
                      "on" if new_state else "off",
                      round(self._bri / 254 * 100), "lumio",
                      light=self._name, light_id=self.light_id)
        except Exception as exc:
            print(f"[{self._name}] toggle error: {exc}")
            log_system("error", f"light toggle {self._name} ({self.light_id}): {exc}")
            self._apply_on_state(not new_state)
        finally:
            self._pending = False

    def _on_slider_move(self, _slider, value):
        if self._updating:
            return
        self._bri = int(value)
        self.pct_lbl.text = f"{round(value / 254 * 100)}%"
        if self._slider_ev:
            self._slider_ev.cancel()
        self._slider_ev = Clock.schedule_once(
            lambda _dt: threading.Thread(
                target=self._send_brightness, args=(self._bri,), daemon=True
            ).start(),
            self.SLIDER_DEBOUNCE,
        )

    def _send_brightness(self, bri: int):
        _mark_huecontrol(self._room_id)
        try:
            self.api.set_light_brightness(self.light_id, bri)
            log_event(self._room_name, self._room_id,
                      "brightness", round(bri / 254 * 100), "lumio",
                      light=self._name, light_id=self.light_id)
            if not self._is_on:
                Clock.schedule_once(lambda _: self._apply_on_state(True), 0)
        except Exception as exc:
            print(f"[{self._name}] brightness error: {exc}")
            log_system("error", f"light brightness {self._name} ({self.light_id}): {exc}")

    def _apply_on_state(self, on: bool):
        self._is_on               = on
        self._bg_color.rgba       = self._card_rgba()
        self.name_lbl.color       = self._name_rgba()
        self.btn.text             = "ON" if on else "OFF"
        self.btn.background_color = C_BTN_ON if on else C_BTN_OFF


# ── RoomDetailModal ────────────────────────────────────────────────────────────

class RoomDetailModal(ModalView):
    """Per-light controls opened on long-press of a room card."""

    def __init__(self, room_name: str, room_id: str, light_ids: list, api, **kwargs):
        super().__init__(
            background_color=(0, 0, 0, 0.55),
            size_hint=(0.92, 0.88),
            **kwargs,
        )
        self.api       = api
        self.room_name = room_name
        self.room_id   = room_id
        self.light_ids = light_ids

        card = BoxLayout(orientation="vertical", padding=[14, 12, 14, 12], spacing=8)
        with card.canvas.before:
            Color(*C_BG)
            self._card_rect = RoundedRectangle(radius=[16], pos=card.pos, size=card.size)
        card.bind(
            pos=lambda *_: setattr(self._card_rect, "pos", card.pos),
            size=lambda *_: setattr(self._card_rect, "size", card.size),
        )

        # Header
        hdr = BoxLayout(orientation="horizontal", size_hint_y=None, height=44)
        hdr.add_widget(Label(
            text=room_name,
            font_size="20sp",
            bold=True,
            color=C_TEXT,
            halign="left",
        ))
        close_btn = Button(
            text="×",
            font_size="24sp",
            size_hint=(None, 1),
            width=44,
            background_normal="",
            background_down="",
            background_color=(0, 0, 0, 0),
            color=C_SUBTEXT,
        )
        close_btn.bind(on_release=lambda _: self.dismiss())
        hdr.add_widget(close_btn)
        card.add_widget(hdr)

        # Light list
        scroll = ScrollView(do_scroll_x=False, bar_width=4)
        self._light_list = GridLayout(cols=1, spacing=CARD_SPACING, size_hint_y=None)
        self._light_list.bind(minimum_height=self._light_list.setter("height"))
        self._light_list.add_widget(Label(
            text="Loading…", color=C_SUBTEXT, size_hint_y=None, height=60,
        ))
        scroll.add_widget(self._light_list)
        card.add_widget(scroll)

        self.add_widget(card)
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        results = []
        for lid in self.light_ids:
            try:
                results.append((lid, self.api.get_light(lid)))
            except Exception as exc:
                print(f"[detail] light {lid}: {exc}")
        self._populate(results)

    @mainthread
    def _populate(self, lights):
        self._light_list.clear_widgets()
        for lid, data in lights:
            self._light_list.add_widget(
                LightRow(lid, data, self.api,
                         room_name=self.room_name, room_id=self.room_id)
            )
        if not lights:
            self._light_list.add_widget(Label(
                text="No lights found", color=C_SUBTEXT, size_hint_y=None, height=60,
            ))


# ── DragGhost ─────────────────────────────────────────────────────────────────

class DragGhost(BoxLayout):
    """
    Semi-transparent floating card that follows the finger during a drag.
    Added directly to Window so it renders above everything.
    """

    def __init__(self, name: str, w: float, h: float, **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint=(None, None),
            size=(w, h),
            **kwargs,
        )
        with self.canvas.before:
            Color(0.00, 0.48, 1.00, 1.00)
            self._rect = RoundedRectangle(radius=[10], pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)
        self.add_widget(Label(
            text=f"⠿  {name}",
            font_size="18sp",
            bold=True,
            color=(1, 1, 1, 1),
        ))

    def _upd(self, *_):
        self._rect.pos  = self.pos
        self._rect.size = self.size


# ── RoomCard ──────────────────────────────────────────────────────────────────

class RoomCard(BoxLayout):
    """
    Vertical two-row card:
        ┌────────────────────────────────────┐
        │  Room Name              [ ON/OFF ] │  ← top row
        │  [══════════ slider ══════════════]│  ← brightness (hidden in edit mode)
        └────────────────────────────────────┘
    """

    SLIDER_DEBOUNCE = 0.35   # seconds after last slider move before calling API

    def __init__(self, group_id: str, group: dict, api: HueAPI, **kwargs):
        super().__init__(
            orientation="vertical",
            padding=[12, 6, 10, 6],
            spacing=2,
            **kwargs,
        )
        self.group_id      = group_id
        self.api           = api
        self._pending      = False
        self._slider_ev    = None
        self._updating     = False
        self._in_edit      = False
        self._lp_event     = None       # long-press timer
        self._long_pressed = False      # suppress button release after long press
        self._lp_ox = self._lp_oy = 0  # touch origin for move threshold

        state  = group.get("state", {})
        action = group.get("action", {})
        self._is_on     = state.get("any_on", False)
        self._light_ids = group.get("lights", [])
        self._room_name = group.get("name", "Room")
        self._bri       = action.get("bri", 254)

        # Rounded background
        with self.canvas.before:
            self._bg_color = Color(*self._card_rgba())
            self._bg_rect  = RoundedRectangle(radius=[10], pos=self.pos, size=self.size)
        self.bind(pos=self._sync_bg, size=self._sync_bg)

        # ── top row ──────────────────────────────────────────────────────────
        top = BoxLayout(orientation="horizontal", spacing=8, size_hint_y=0.52)

        self.name_lbl = Label(
            text=self._room_name,
            font_size="17sp",
            bold=True,
            color=self._name_rgba(),
            halign="left",
            valign="middle",
            size_hint_x=0.68,
        )
        self.name_lbl.bind(size=lambda w, _: setattr(w, "text_size", (w.width, None)))

        self.btn = Button(
            text="ON" if self._is_on else "OFF",
            font_size="15sp",
            bold=True,
            size_hint_x=0.32,
            background_normal="",
            background_down="",
            background_color=C_BTN_ON if self._is_on else C_BTN_OFF,
            color=(1, 1, 1, 1),
        )
        self.btn.bind(on_release=self._handle_toggle)

        top.add_widget(self.name_lbl)
        top.add_widget(self.btn)

        # ── brightness slider ─────────────────────────────────────────────────
        bri_row = BoxLayout(orientation="horizontal", size_hint_y=0.48, spacing=4)
        self.slider = Slider(
            min=1,
            max=254,
            value=self._bri,
            cursor_size=(28, 28),
        )
        self.slider.bind(value=self._on_slider_move)
        self.pct_lbl = Label(
            text=f"{round(self._bri / 254 * 100)}%",
            font_size="13sp",
            color=C_SUBTEXT,
            size_hint=(None, 1),
            width=40,
            halign="right",
            valign="middle",
        )
        self.pct_lbl.bind(size=lambda w, _: setattr(w, "text_size", (w.width, None)))
        bri_row.add_widget(self.slider)
        bri_row.add_widget(self.pct_lbl)

        self.add_widget(top)
        self.add_widget(bri_row)

    # ── canvas helpers ────────────────────────────────────────────────────────

    def _card_rgba(self):
        return C_CARD_ON if self._is_on else C_CARD_OFF

    def _name_rgba(self):
        return C_TEXT_ON if self._is_on else C_TEXT

    def _sync_bg(self, *_):
        self._bg_rect.pos  = self.pos
        self._bg_rect.size = self.size

    def turn_off(self):
        """Called by All Off — turns off this room if it's currently on."""
        if not self._is_on:
            return
        self._apply_on_state(False)
        threading.Thread(target=self._send_off, daemon=True).start()

    def _send_off(self):
        _mark_huecontrol(self.group_id)
        try:
            self.api.set_group_on(self.group_id, False)
            log_event(self._room_name, self.group_id, "off", 0, "lumio")
        except Exception as exc:
            print(f"[{self._room_name}] all-off error: {exc}")
            Clock.schedule_once(lambda _: self._apply_on_state(True), 0)

    # ── long-press → room detail ──────────────────────────────────────────────

    def on_touch_down(self, touch):
        if not self._in_edit and self.collide_point(*touch.pos):
            self._lp_ox, self._lp_oy = touch.pos
            self._lp_event = Clock.schedule_once(self._do_long_press, 0.5)
            touch.grab(self)
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if touch.grab_current is self and self._lp_event:
            if abs(touch.x - self._lp_ox) > 10 or abs(touch.y - self._lp_oy) > 10:
                self._lp_event.cancel()
                self._lp_event = None
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            if self._lp_event:
                self._lp_event.cancel()
                self._lp_event = None
        return super().on_touch_up(touch)

    def _do_long_press(self, dt):
        self._lp_event     = None
        self._long_pressed = True
        RoomDetailModal(
            room_name=self._room_name,
            room_id=self.group_id,
            light_ids=self._light_ids,
            api=self.api,
        ).open()

    # ── edit mode ─────────────────────────────────────────────────────────────

    def set_edit_mode(self, edit: bool):
        self._in_edit         = edit
        self.slider.opacity   = 0 if edit else 1
        self.pct_lbl.opacity  = 0 if edit else 1
        self.slider.disabled  = edit
        self.name_lbl.color   = C_TEXT if edit else self._name_rgba()

    def highlight_as_target(self, active: bool):
        """Show or clear the drop-target highlight colour."""
        self._bg_color.rgba = C_CARD_TARGET if active else self._card_rgba()

    # ── on/off toggle ─────────────────────────────────────────────────────────

    def _handle_toggle(self, *_):
        if self._in_edit or self._pending:
            return
        if self._long_pressed:
            self._long_pressed = False
            return
        self._pending = True
        new_state = not self._is_on
        self._apply_on_state(new_state)   # optimistic update
        threading.Thread(
            target=self._send_toggle, args=(new_state,), daemon=True
        ).start()

    def _send_toggle(self, new_state: bool):
        _mark_huecontrol(self.group_id)
        try:
            self.api.set_group_on(self.group_id, new_state)
            log_event(self._room_name, self.group_id,
                      "on" if new_state else "off",
                      round(self._bri / 254 * 100), "lumio")
        except Exception as exc:
            print(f"[{self._room_name}] toggle error: {exc}")
            log_system("error", f"room toggle {self._room_name} ({self.group_id}): {exc}")
            self._apply_on_state(not new_state)
        finally:
            self._pending = False

    # ── brightness slider ─────────────────────────────────────────────────────

    def _on_slider_move(self, _slider, value):
        if self._updating or self._in_edit:
            return
        self._bri = int(value)
        self.pct_lbl.text = f"{round(value / 254 * 100)}%"
        if self._slider_ev:
            self._slider_ev.cancel()
        self._slider_ev = Clock.schedule_once(
            lambda _dt: threading.Thread(
                target=self._send_brightness, args=(self._bri,), daemon=True
            ).start(),
            self.SLIDER_DEBOUNCE,
        )

    def _send_brightness(self, bri: int):
        _mark_huecontrol(self.group_id)
        try:
            self.api.set_group_brightness(self.group_id, bri)
            log_event(self._room_name, self.group_id,
                      "brightness", round(bri / 254 * 100), "lumio")
            if not self._is_on:
                Clock.schedule_once(lambda _: self._apply_on_state(True), 0)
        except Exception as exc:
            print(f"[{self._room_name}] brightness error: {exc}")
            log_system("error", f"room brightness {self._room_name} ({self.group_id}): {exc}")

    # ── background refresh ────────────────────────────────────────────────────

    @mainthread
    def apply_group(self, group: dict):
        if self._pending or self._slider_ev:
            return      # don't overwrite in-flight user actions
        self._light_ids = group.get("lights", self._light_ids)
        self._is_on     = group.get("state", {}).get("any_on", False)
        bri = group.get("action", {}).get("bri", self._bri)
        self._apply_on_state(self._is_on)
        self._set_slider(bri)

    def _set_slider(self, bri: int):
        """Update slider position without triggering an API call."""
        self._updating    = True
        self.slider.value = bri
        self._bri         = bri
        self._updating    = False
        self.pct_lbl.text = f"{round(bri / 254 * 100)}%"

    def _apply_on_state(self, on: bool):
        self._is_on               = on
        self._bg_color.rgba       = self._card_rgba()
        self.name_lbl.color       = C_TEXT if self._in_edit else self._name_rgba()
        self.btn.text             = "ON" if on else "OFF"
        self.btn.background_color = C_BTN_ON if on else C_BTN_OFF

    def refresh_colors(self):
        self._bg_color.rgba       = self._card_rgba()
        self.name_lbl.color       = C_TEXT if self._in_edit else self._name_rgba()
        self.btn.background_color = C_BTN_ON if self._is_on else C_BTN_OFF


# ── SettingsPopup ─────────────────────────────────────────────────────────────

class _TappableRow(ButtonBehavior, BoxLayout):
    """BoxLayout that fires on_release like a Button."""


class SettingsPopup(ModalView):
    """Modal settings panel — room visibility toggles."""

    ROW_HEIGHT = 54

    def __init__(self, all_rooms: list, hidden_rooms: set, on_save,
                 brightness: int = 200, show_weather: bool = True,
                 logging_enabled: bool = True, show_sync_errors: bool = True,
                 exempt_rooms: set = None, **kwargs):
        super().__init__(
            background_color=(0, 0, 0, 0.55),
            size_hint=(0.90, 0.92),
            **kwargs,
        )
        self._on_save          = on_save
        self._visible          = {gid: gid not in hidden_rooms for gid, _ in all_rooms}
        self._included         = {gid: gid not in (exempt_rooms or set()) for gid, _ in all_rooms}
        self._rows             = {}   # gid → (bg, show_check, name_lbl, alloff_check)
        self._show_weather     = show_weather
        self._logging_enabled  = logging_enabled
        self._show_sync_errors = show_sync_errors
        self._adv_open         = False

        card = BoxLayout(orientation='vertical', padding=[14, 12, 14, 12], spacing=8)
        with card.canvas.before:
            Color(*C_BG)
            self._card_rect = RoundedRectangle(radius=[16], pos=card.pos, size=card.size)
        card.bind(
            pos=lambda *_: setattr(self._card_rect, 'pos', card.pos),
            size=lambda *_: setattr(self._card_rect, 'size', card.size),
        )

        # Header
        hdr = BoxLayout(orientation='horizontal', size_hint_y=None, height=44)
        hdr.add_widget(Label(
            text="Settings",
            font_size="18sp",
            bold=True,
            color=C_TEXT,
            halign="left",
        ))
        close_btn = Button(
            text="×",
            font_size="24sp",
            size_hint=(None, 1),
            width=44,
            background_normal="",
            background_down="",
            background_color=(0, 0, 0, 0),
            color=C_SUBTEXT,
        )
        close_btn.bind(on_release=lambda _: self.dismiss())
        hdr.add_widget(close_btn)
        card.add_widget(hdr)

        # Single scrollable content area (everything except header + done button)
        scroll = ScrollView(do_scroll_x=False, bar_width=4)
        inner = GridLayout(cols=1, spacing=8, size_hint_y=None)
        inner.bind(minimum_height=inner.setter('height'))

        # Brightness
        bri_lbl = Label(
            text="Screen Brightness",
            font_size="14sp",
            bold=True,
            color=C_SUBTEXT,
            halign="left",
            size_hint_y=None,
            height=26,
        )
        bri_lbl.bind(size=lambda w, _: setattr(w, "text_size", (w.width, None)))
        inner.add_widget(bri_lbl)

        bri_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=38, spacing=6)
        self._bri_slider = Slider(min=10, max=255, value=brightness, cursor_size=(22, 22))
        self._bri_pct    = Label(
            text=f"{round(brightness / 255 * 100)}%",
            font_size="13sp",
            color=C_SUBTEXT,
            size_hint=(None, 1),
            width=44,
        )
        self._bri_slider.bind(value=self._on_bri_change)
        bri_row.add_widget(self._bri_slider)
        bri_row.add_widget(self._bri_pct)
        inner.add_widget(bri_row)

        # Weather toggle
        wx_row = _TappableRow(
            orientation='horizontal',
            size_hint_y=None,
            height=self.ROW_HEIGHT,
            padding=[12, 0, 12, 0],
            spacing=10,
        )
        with wx_row.canvas.before:
            self._wx_bg   = Color(*(C_CARD_ON if show_weather else C_CARD_OFF))
            wx_rect       = RoundedRectangle(radius=[8], pos=wx_row.pos, size=wx_row.size)
        wx_row.bind(
            pos=lambda w, _: setattr(wx_rect, 'pos', w.pos),
            size=lambda w, _: setattr(wx_rect, 'size', w.size),
            on_release=lambda _: self._toggle_weather(),
        )
        self._wx_name = Label(
            text="Show Weather",
            font_size="15sp", bold=True,
            color=C_TEXT if show_weather else C_SUBTEXT,
            halign='left', valign='middle',
        )
        self._wx_name.bind(size=lambda w, _: setattr(w, 'text_size', (w.width, None)))
        self._wx_check = Label(
            text="✓" if show_weather else "",
            font_name=SYMBOL_FONT or 'Roboto',
            font_size="18sp", bold=True, color=C_BTN_ON,
            size_hint=(None, 1), width=36,
            halign='center', valign='middle',
        )
        wx_row.add_widget(self._wx_name)
        wx_row.add_widget(self._wx_check)
        inner.add_widget(wx_row)

        # Advanced: wrapper holds header + content; expands by add/remove of content
        self._adv_wrapper = BoxLayout(
            orientation='vertical',
            size_hint_y=None,
            height=36,
            spacing=4,
        )

        adv_hdr = _TappableRow(
            orientation='horizontal',
            size_hint_y=None,
            height=36,
            padding=[12, 0, 12, 0],
        )
        with adv_hdr.canvas.before:
            Color(*C_CARD_OFF)
            adv_hdr_rect = RoundedRectangle(radius=[8], pos=adv_hdr.pos, size=adv_hdr.size)
        adv_hdr.bind(
            pos=lambda w, _: setattr(adv_hdr_rect, 'pos', w.pos),
            size=lambda w, _: setattr(adv_hdr_rect, 'size', w.size),
            on_release=lambda _: self._toggle_advanced(),
        )
        self._adv_lbl = Label(
            text="▸  Advanced",
            font_size="13sp", bold=True,
            color=C_SUBTEXT,
            halign='left', valign='middle',
        )
        self._adv_lbl.bind(size=lambda w, _: setattr(w, 'text_size', (w.width, None)))
        adv_hdr.add_widget(self._adv_lbl)
        self._adv_wrapper.add_widget(adv_hdr)

        # Advanced content — built now, added to wrapper only when expanded
        _row_h = self.ROW_HEIGHT
        self._adv_content = BoxLayout(
            orientation='vertical',
            size_hint_y=None,
            height=_row_h * 2 + 4,
            spacing=4,
        )

        # Enable Logging toggle
        log_row = _TappableRow(
            orientation='horizontal',
            size_hint_y=None,
            height=_row_h,
            padding=[12, 0, 12, 0],
            spacing=10,
        )
        with log_row.canvas.before:
            self._log_bg = Color(*(C_CARD_ON if logging_enabled else C_CARD_OFF))
            log_rect     = RoundedRectangle(radius=[8], pos=log_row.pos, size=log_row.size)
        log_row.bind(
            pos=lambda w, _: setattr(log_rect, 'pos', w.pos),
            size=lambda w, _: setattr(log_rect, 'size', w.size),
            on_release=lambda _: self._toggle_logging(),
        )
        self._log_name = Label(
            text="Enable Logging",
            font_size="15sp", bold=True,
            color=C_TEXT if logging_enabled else C_SUBTEXT,
            halign='left', valign='middle',
        )
        self._log_name.bind(size=lambda w, _: setattr(w, 'text_size', (w.width, None)))
        self._log_check = Label(
            text="✓" if logging_enabled else "",
            font_name=SYMBOL_FONT or 'Roboto',
            font_size="18sp", bold=True, color=C_BTN_ON,
            size_hint=(None, 1), width=36,
            halign='center', valign='middle',
        )
        log_row.add_widget(self._log_name)
        log_row.add_widget(self._log_check)
        self._adv_content.add_widget(log_row)

        # Show sync errors toggle
        sync_row = _TappableRow(
            orientation='horizontal',
            size_hint_y=None,
            height=_row_h,
            padding=[12, 0, 12, 0],
            spacing=10,
        )
        with sync_row.canvas.before:
            self._sync_bg = Color(*(C_CARD_ON if show_sync_errors else C_CARD_OFF))
            sync_rect     = RoundedRectangle(radius=[8], pos=sync_row.pos, size=sync_row.size)
        sync_row.bind(
            pos=lambda w, _: setattr(sync_rect, 'pos', w.pos),
            size=lambda w, _: setattr(sync_rect, 'size', w.size),
            on_release=lambda _: self._toggle_sync_errors(),
        )
        self._sync_name = Label(
            text="Show Sync Errors",
            font_size="15sp", bold=True,
            color=C_TEXT if show_sync_errors else C_SUBTEXT,
            halign='left', valign='middle',
        )
        self._sync_name.bind(size=lambda w, _: setattr(w, 'text_size', (w.width, None)))
        self._sync_check = Label(
            text="✓" if show_sync_errors else "",
            font_name=SYMBOL_FONT or 'Roboto',
            font_size="18sp", bold=True, color=C_BTN_ON,
            size_hint=(None, 1), width=36,
            halign='center', valign='middle',
        )
        sync_row.add_widget(self._sync_name)
        sync_row.add_widget(self._sync_check)
        self._adv_content.add_widget(sync_row)

        inner.add_widget(self._adv_wrapper)

        # Displayed Rooms header row with column labels
        rooms_hdr = BoxLayout(orientation='horizontal', size_hint_y=None, height=26)
        rooms_main_lbl = Label(
            text="Displayed Rooms",
            font_size="14sp", bold=True,
            color=C_SUBTEXT,
            halign="left", valign="middle",
        )
        rooms_main_lbl.bind(size=lambda w, _: setattr(w, "text_size", (w.width, None)))
        rooms_hdr.add_widget(rooms_main_lbl)
        rooms_hdr.add_widget(Label(
            text="Show", font_size="11sp", color=C_SUBTEXT,
            halign="center", size_hint=(None, 1), width=44,
        ))
        rooms_hdr.add_widget(Label(
            text="All Off", font_size="11sp", color=C_SUBTEXT,
            halign="center", size_hint=(None, 1), width=44,
        ))
        inner.add_widget(rooms_hdr)

        room_list = GridLayout(cols=1, spacing=CARD_SPACING, size_hint_y=None)
        room_list.bind(minimum_height=room_list.setter('height'))
        for gid, group in all_rooms:
            room_list.add_widget(self._make_row(gid, group.get('name', 'Room')))
        inner.add_widget(room_list)

        scroll.add_widget(inner)
        card.add_widget(scroll)

        # Done button
        done_btn = Button(
            text="Done",
            size_hint_y=None,
            height=48,
            background_normal="",
            background_down="",
            background_color=C_BTN_ON,
            color=(1, 1, 1, 1),
            bold=True,
            font_size="15sp",
        )
        done_btn.bind(on_release=self._save_and_close)
        card.add_widget(done_btn)

        self.add_widget(card)

    def _make_row(self, gid, name):
        visible  = self._visible[gid]
        included = self._included[gid]

        row = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=self.ROW_HEIGHT,
            padding=[12, 0, 4, 0],
            spacing=0,
        )
        with row.canvas.before:
            bg = Color(*(C_CARD_ON if visible else C_CARD_OFF))
            rect = RoundedRectangle(radius=[8], pos=row.pos, size=row.size)
        row.bind(
            pos=lambda w, _: setattr(rect, 'pos', w.pos),
            size=lambda w, _: setattr(rect, 'size', w.size),
        )

        name_lbl = Label(
            text=name,
            font_size="15sp", bold=True,
            color=C_TEXT if visible else C_SUBTEXT,
            halign='left', valign='middle',
        )
        name_lbl.bind(size=lambda w, _: setattr(w, 'text_size', (w.width, None)))

        show_cell = _TappableRow(size_hint=(None, 1), width=44)
        show_cell.bind(on_release=lambda inst, g=gid: self._toggle_show(g))
        show_check = Label(
            text="✓" if visible else "",
            font_name=SYMBOL_FONT or 'Roboto',
            font_size="18sp", bold=True, color=C_BTN_ON,
            halign='center', valign='middle',
        )
        show_cell.add_widget(show_check)

        alloff_cell = _TappableRow(size_hint=(None, 1), width=44)
        alloff_cell.bind(on_release=lambda inst, g=gid: self._toggle_alloff(g))
        alloff_check = Label(
            text="✓" if included else "",
            font_name=SYMBOL_FONT or 'Roboto',
            font_size="18sp", bold=True, color=C_BTN_ON,
            halign='center', valign='middle',
        )
        alloff_cell.add_widget(alloff_check)

        row.add_widget(name_lbl)
        row.add_widget(show_cell)
        row.add_widget(alloff_cell)

        self._rows[gid] = (bg, show_check, name_lbl, alloff_check)
        return row

    def _toggle_show(self, gid):
        self._visible[gid] = not self._visible[gid]
        visible = self._visible[gid]
        bg, show_check, name_lbl, alloff_check = self._rows[gid]
        bg.rgba         = C_CARD_ON if visible else C_CARD_OFF
        show_check.text = "✓" if visible else ""
        name_lbl.color  = C_TEXT if visible else C_SUBTEXT

    def _toggle_alloff(self, gid):
        self._included[gid] = not self._included[gid]
        self._rows[gid][3].text = "✓" if self._included[gid] else ""

    def _on_bri_change(self, _, value):
        self._bri_pct.text = f"{round(value / 255 * 100)}%"
        set_brightness(int(value))

    def _toggle_weather(self):
        self._show_weather     = not self._show_weather
        self._wx_bg.rgba       = C_CARD_ON if self._show_weather else C_CARD_OFF
        self._wx_check.text    = "✓" if self._show_weather else ""
        self._wx_name.color    = C_TEXT if self._show_weather else C_SUBTEXT

    def _toggle_advanced(self):
        self._adv_open = not self._adv_open
        if self._adv_open:
            self._adv_wrapper.add_widget(self._adv_content)
            self._adv_wrapper.height = 36 + 4 + self._adv_content.height
            self._adv_lbl.text = "▾  Advanced"
        else:
            self._adv_wrapper.remove_widget(self._adv_content)
            self._adv_wrapper.height = 36
            self._adv_lbl.text = "▸  Advanced"

    def _toggle_logging(self):
        self._logging_enabled  = not self._logging_enabled
        self._log_bg.rgba      = C_CARD_ON if self._logging_enabled else C_CARD_OFF
        self._log_check.text   = "✓" if self._logging_enabled else ""
        self._log_name.color   = C_TEXT if self._logging_enabled else C_SUBTEXT

    def _toggle_sync_errors(self):
        self._show_sync_errors = not self._show_sync_errors
        self._sync_bg.rgba     = C_CARD_ON if self._show_sync_errors else C_CARD_OFF
        self._sync_check.text  = "✓" if self._show_sync_errors else ""
        self._sync_name.color  = C_TEXT if self._show_sync_errors else C_SUBTEXT

    def _save_and_close(self, *_):
        hidden = {gid for gid, vis in self._visible.items() if not vis}
        exempt = {gid for gid, inc in self._included.items() if not inc}
        self._on_save(hidden, int(self._bri_slider.value), self._show_weather,
                      self._logging_enabled, self._show_sync_errors, exempt)
        self.dismiss()


# ── WeatherModal ──────────────────────────────────────────────────────────────

class WeatherModal(ModalView):
    """Full weather detail card — always dark navy regardless of app theme."""

    _BG      = (0.07, 0.10, 0.20, 1)   # deep navy overlay tint
    _CARD    = (0.10, 0.14, 0.26, 1)   # card background
    _TEMP    = (0.95, 0.75, 0.25, 1)   # amber/gold — current temp
    _TEXT    = (0.92, 0.94, 1.00, 1)   # near-white text
    _SUB     = (0.52, 0.60, 0.82, 1)   # muted blue-grey subtext
    _DAY_BG  = (0.13, 0.18, 0.32, 1)   # day column background

    def __init__(self, data: dict, city: str, lat=None, lon=None, **kwargs):
        super().__init__(
            background_color=(0, 0, 0, 0.70),
            size_hint=(0.85, 0.82),
            **kwargs,
        )
        self._lat = lat
        self._lon = lon

        card = BoxLayout(orientation='vertical', padding=[20, 16, 20, 16], spacing=10)
        with card.canvas.before:
            Color(*self._CARD)
            c_rect = RoundedRectangle(radius=[20], pos=card.pos, size=card.size)
        card.bind(
            pos=lambda *_: setattr(c_rect, 'pos', card.pos),
            size=lambda *_: setattr(c_rect, 'size', card.size),
        )

        # ── header row: city + close ─────────────────────────────────────────
        hdr = BoxLayout(orientation='horizontal', size_hint_y=None, height=36)
        city_lbl = Label(
            text=city or "Weather",
            font_size="16sp", bold=True,
            color=self._TEXT,
            halign="left", valign="middle",
        )
        city_lbl.bind(size=lambda w, _: setattr(w, 'text_size', (w.width, None)))
        close_btn = Button(
            text="×", font_size="22sp",
            size_hint=(None, 1), width=40,
            background_normal="", background_down="",
            background_color=(0, 0, 0, 0),
            color=self._SUB,
        )
        close_btn.bind(on_release=lambda _: self.dismiss())
        hdr.add_widget(city_lbl)
        hdr.add_widget(close_btn)
        card.add_widget(hdr)

        # ── current temp (big) ───────────────────────────────────────────────
        card.add_widget(Label(
            text=f"{data['temp']}°F",
            font_size="68sp", bold=True,
            color=self._TEMP,
            size_hint_y=None, height=90,
        ))

        # ── condition ────────────────────────────────────────────────────────
        card.add_widget(Label(
            text=data['condition'],
            font_size="20sp",
            color=self._TEXT,
            size_hint_y=None, height=30,
        ))

        # ── wind ─────────────────────────────────────────────────────────────
        card.add_widget(Label(
            text=f"Wind  {data['wind_mph']} mph",
            font_size="14sp",
            color=self._SUB,
            size_hint_y=None, height=22,
        ))

        # ── spacer ───────────────────────────────────────────────────────────
        card.add_widget(BoxLayout(size_hint_y=None, height=6))

        # ── 5-day forecast row (skip index 0 = today) ────────────────────────
        forecast = GridLayout(cols=5, size_hint_y=None, height=114, spacing=6)
        for day in data['daily'][1:6]:
            col = _DayCol(orientation='vertical', spacing=2, padding=[0, 6, 0, 6])
            with col.canvas.before:
                Color(*self._DAY_BG)
                d_rect = RoundedRectangle(radius=[8], pos=col.pos, size=col.size)
            col.bind(
                pos=lambda w, _, r=d_rect: setattr(r, 'pos', w.pos),
                size=lambda w, _, r=d_rect: setattr(r, 'size', w.size),
            )
            if self._lat and self._lon:
                col.bind(on_release=lambda inst, d=day: self._open_day_detail(d))
            cond_text = day['cond_short']
            if day.get('precip_pct', 0) > 0:
                cond_text += f"  {day['precip_pct']}%"
            col.add_widget(Label(text=day['day'],        font_size="12sp", bold=True, color=self._SUB))
            col.add_widget(Label(text=cond_text,         font_size="11sp",            color=self._TEXT))
            col.add_widget(Label(text=f"{day['high']}°", font_size="15sp", bold=True, color=self._TEMP))
            col.add_widget(Label(text=f"{day['low']}°",  font_size="12sp",            color=self._SUB))
            forecast.add_widget(col)
        card.add_widget(forecast)

        self.add_widget(card)

    def _open_day_detail(self, day: dict):
        DayDetailModal(
            day_name=day['day'],
            date_str=day['date'],
            lat=self._lat,
            lon=self._lon,
        ).open()


class _DayCol(ButtonBehavior, BoxLayout):
    """Tappable day column in the weather forecast grid."""


# ── DayDetailModal ─────────────────────────────────────────────────────────────

class DayDetailModal(ModalView):
    """Hourly forecast for a tapped day — dark navy, same style as WeatherModal."""

    _CARD   = (0.10, 0.14, 0.26, 1)
    _TEMP   = (0.95, 0.75, 0.25, 1)
    _TEXT   = (0.92, 0.94, 1.00, 1)
    _SUB    = (0.52, 0.60, 0.82, 1)
    _ROW_A  = (0.12, 0.17, 0.30, 1)
    _ROW_B  = (0.09, 0.13, 0.24, 1)
    _PRECIP = (0.45, 0.70, 1.00, 1)
    ROW_H   = 44

    def __init__(self, day_name: str, date_str: str, lat: float, lon: float, **kwargs):
        super().__init__(
            background_color=(0, 0, 0, 0.80),
            size_hint=(0.85, 0.88),
            **kwargs,
        )
        self._lat      = lat
        self._lon      = lon
        self._date_str = date_str

        card = BoxLayout(orientation='vertical', padding=[20, 16, 20, 16], spacing=10)
        with card.canvas.before:
            Color(*self._CARD)
            c_rect = RoundedRectangle(radius=[20], pos=card.pos, size=card.size)
        card.bind(
            pos=lambda *_: setattr(c_rect, 'pos', card.pos),
            size=lambda *_: setattr(c_rect, 'size', card.size),
        )

        # ── header ───────────────────────────────────────────────────────────
        hdr = BoxLayout(orientation='horizontal', size_hint_y=None, height=36)
        dt = datetime.fromisoformat(date_str)
        date_lbl = Label(
            text=f"{dt.strftime('%A')}  ·  {dt.strftime('%b')} {dt.day}",
            font_size="16sp", bold=True,
            color=self._TEXT,
            halign="left", valign="middle",
        )
        date_lbl.bind(size=lambda w, _: setattr(w, 'text_size', (w.width, None)))
        close_btn = Button(
            text="×", font_size="22sp",
            size_hint=(None, 1), width=40,
            background_normal="", background_down="",
            background_color=(0, 0, 0, 0),
            color=self._SUB,
        )
        close_btn.bind(on_release=lambda _: self.dismiss())
        hdr.add_widget(date_lbl)
        hdr.add_widget(close_btn)
        card.add_widget(hdr)

        # ── content: loading → hourly rows ───────────────────────────────────
        self._content = BoxLayout(orientation='vertical')
        self._content.add_widget(Label(
            text="Loading…", font_size="16sp", color=self._SUB,
        ))
        card.add_widget(self._content)
        self.add_widget(card)

        threading.Thread(target=self._do_fetch, daemon=True).start()

    def _do_fetch(self):
        self._populate(_fetch_hourly(self._lat, self._lon, self._date_str))

    @mainthread
    def _populate(self, hours):
        self._content.clear_widgets()
        if not hours:
            self._content.add_widget(Label(
                text="Could not load forecast.", font_size="15sp", color=self._SUB,
            ))
            return

        scroll   = ScrollView(do_scroll_x=False, bar_width=4)
        row_list = GridLayout(cols=1, size_hint_y=None, spacing=3)
        row_list.bind(minimum_height=row_list.setter('height'))

        for i, h in enumerate([x for x in hours if 6 <= x['hour'] <= 22]):
            row = BoxLayout(
                orientation='horizontal',
                size_hint_y=None, height=self.ROW_H,
                padding=[10, 0, 10, 0], spacing=8,
            )
            with row.canvas.before:
                Color(*(self._ROW_A if i % 2 == 0 else self._ROW_B))
                r_rect = RoundedRectangle(radius=[6], pos=row.pos, size=row.size)
            row.bind(
                pos=lambda w, _, r=r_rect: setattr(r, 'pos', w.pos),
                size=lambda w, _, r=r_rect: setattr(r, 'size', w.size),
            )
            row.add_widget(Label(
                text=h['time'], font_size="13sp", bold=True, color=self._SUB,
                size_hint=(None, 1), width=64, text_size=(64, None),
                halign="left", valign="middle",
            ))
            row.add_widget(Label(
                text=f"{h['temp']}°F", font_size="14sp", bold=True, color=self._TEMP,
                size_hint=(None, 1), width=62, text_size=(62, None),
                halign="left", valign="middle",
            ))
            cond_lbl = Label(
                text=h['condition'], font_size="13sp", color=self._TEXT,
                size_hint_x=1, halign="left", valign="middle",
            )
            cond_lbl.bind(size=lambda w, _: setattr(w, 'text_size', (w.width, None)))
            row.add_widget(cond_lbl)
            row.add_widget(Label(
                text=f"{h['precip_pct']}%" if h.get('precip_pct', 0) > 0 else "",
                font_size="13sp", color=self._PRECIP,
                size_hint=(None, 1), width=46, text_size=(46, None),
                halign="right", valign="middle",
            ))
            row.add_widget(Label(
                text=f"{h['wind_mph']} mph", font_size="12sp", color=self._SUB,
                size_hint=(None, 1), width=58, text_size=(58, None),
                halign="right", valign="middle",
            ))
            row_list.add_widget(row)

        scroll.add_widget(row_list)
        self._content.add_widget(scroll)


class _WeatherBtn(ButtonBehavior, Label):
    """Tappable Label — fires on_release when tapped."""


# ── HeaderBar ─────────────────────────────────────────────────────────────────

class HeaderBar(BoxLayout):
    """Top bar: clock | weather/status | Settings | Edit | Theme icon."""

    def __init__(self, on_edit_toggle, on_theme_toggle, on_settings_open,
                 on_weather_tap=None, on_all_off=None, **kwargs):
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height=44,
            padding=[8, 4, 8, 4],
            spacing=6,
            **kwargs,
        )
        with self.canvas.before:
            self._hdr_color = Color(*C_HEADER_BG)
            self._rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)

        self._weather_text  = ""    # last known weather string
        self._status_revert = None  # pending Clock event to restore weather after status
        self._lp_event      = None  # long-press timer for clock exit
        self._lp_touch_uid  = None

        self.clock_lbl = Label(
            text=self._now_str(),
            font_size="14sp",
            color=C_SUBTEXT,
            halign="right",
            valign="middle",
            size_hint=(None, 0.85),
            width=88,
        )
        self.clock_lbl.bind(size=lambda w, _: setattr(w, "text_size", (w.width, None)))
        self.add_widget(self.clock_lbl)

        if on_all_off:
            self.alloff_btn = Button(
                text="⏻",
                font_name=SYMBOL_FONT or 'Roboto',
                font_size="20sp",
                size_hint=(None, 0.85),
                width=46,
                background_normal="",
                background_down="",
                background_color=(0, 0, 0, 0),
                color=C_SUBTEXT,
            )
            self.alloff_btn.bind(on_release=lambda _: on_all_off())
            self.add_widget(self.alloff_btn)
        else:
            self.alloff_btn = None

        self.weather_lbl = _WeatherBtn(
            text="",
            font_size="13sp",
            color=C_SUBTEXT,
            halign="right",
            valign="middle",
            size_hint=(1, 0.85),
        )
        self.weather_lbl.bind(size=lambda w, _: setattr(w, "text_size", (w.width, None)))
        if on_weather_tap:
            self.weather_lbl.bind(on_release=lambda _: on_weather_tap())
        self.add_widget(self.weather_lbl)

        self.settings_btn = Button(
            text="⚙",
            font_name=SYMBOL_FONT or 'Roboto',
            font_size="20sp",
            size_hint=(None, 0.85),
            width=46,
            background_normal="",
            background_down="",
            background_color=(0, 0, 0, 0),
            color=C_SUBTEXT,
        )
        self.settings_btn.bind(on_release=lambda _: on_settings_open())

        self.edit_btn = Button(
            text="✎",
            font_name=SYMBOL_FONT or 'Roboto',
            font_size="20sp",
            size_hint=(None, 0.85),
            width=46,
            background_normal="",
            background_down="",
            background_color=(0, 0, 0, 0),
            color=C_SUBTEXT,
        )
        self.edit_btn.bind(on_release=lambda _: on_edit_toggle())

        self.theme_btn = Button(
            text="☾",
            font_name=SYMBOL_FONT or 'Roboto',
            font_size="20sp",
            size_hint=(None, 0.85),
            width=46,
            background_normal="",
            background_down="",
            background_color=(0, 0, 0, 0),
            color=C_SUBTEXT,
        )
        self.theme_btn.bind(on_release=lambda _: on_theme_toggle())

        self.add_widget(self.settings_btn)
        self.add_widget(self.edit_btn)
        self.add_widget(self.theme_btn)

        Clock.schedule_interval(self._tick_clock, 1)

    @staticmethod
    def _now_str() -> str:
        return datetime.now().strftime("%I:%M %p").lstrip("0")

    def _tick_clock(self, _dt):
        self.clock_lbl.text = self._now_str()

    def on_touch_down(self, touch):
        if self.clock_lbl.collide_point(*touch.pos):
            self._lp_touch_uid = touch.uid
            self._lp_event = Clock.schedule_once(self._do_exit, 1.5)
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        if touch.uid == self._lp_touch_uid:
            if self._lp_event:
                self._lp_event.cancel()
                self._lp_event = None
            self._lp_touch_uid = None
        return super().on_touch_up(touch)

    def _do_exit(self, _dt):
        from kivy.app import App
        log_system("app_stop")
        App.get_running_app().stop()

    def set_weather(self, text: str):
        self._weather_text = text
        if self._status_revert is None:
            self.weather_lbl.text  = text
            self.weather_lbl.color = C_SUBTEXT

    def set_status(self, text: str, color=None):
        if self._status_revert:
            self._status_revert.cancel()
        self.weather_lbl.text  = text
        self.weather_lbl.color = color or C_SUBTEXT
        self._status_revert = Clock.schedule_once(self._revert_to_weather, 3)

    def _revert_to_weather(self, _dt):
        self._status_revert    = None
        self.weather_lbl.text  = self._weather_text
        self.weather_lbl.color = C_SUBTEXT

    def _upd(self, *_):
        self._rect.pos  = self.pos
        self._rect.size = self.size

    def set_edit_active(self, active: bool):
        self.edit_btn.color = C_BTN_EDIT if active else C_SUBTEXT
        self.edit_btn.text  = "✔" if active else "✎"

    def set_theme_label(self, dark_mode: bool):
        self.theme_btn.text  = "☀" if dark_mode else "☾"
        self.theme_btn.color = C_SUBTEXT

    def refresh_colors(self):
        self._hdr_color.rgba    = C_HEADER_BG
        self.clock_lbl.color    = C_SUBTEXT
        self.weather_lbl.color  = C_SUBTEXT
        if self.alloff_btn:
            self.alloff_btn.color = C_SUBTEXT
        self.settings_btn.color = C_SUBTEXT
        self.edit_btn.color     = C_SUBTEXT
        self.theme_btn.color    = C_SUBTEXT


# ── RoomGrid ──────────────────────────────────────────────────────────────────

class RoomGrid(BoxLayout):
    """
    Root widget.

    Normal mode : Header + scrollable 2-col card grid.
    Edit mode   : Scrolling disabled; cards draggable to reorder.
                  Sliders hidden. New order saved to hue_settings.json on drop.
    """

    def __init__(self, api: HueAPI, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.api         = api
        self.cards       = {}        # gid → RoomCard
        self._busy         = True
        self._edit_mode    = False
        self._settings     = load_settings()

        global _DARK_MODE
        _DARK_MODE = self._settings.get("dark_mode", False)
        set_theme(PALETTE_DARK if _DARK_MODE else PALETTE_LIGHT)
        Window.clearcolor = C_BG
        self._all_rooms    = []        # all (gid, group) from last fetch
        self._last_groups  = {}       # raw groups dict from last fetch
        self._light_to_group = {}     # light_id → group_id (for SSE routing)
        self._sse_started  = False
        self._last_weather      = ""
        self._last_weather_data = None
        self._weather_wake      = threading.Event()

        # Drag state
        self._drag_card     = None
        self._drag_ghost    = None
        self._drag_target   = None
        self._drag_touch_uid = None     # uid of the active drag touch

        with self.canvas.before:
            self._bg_color_inst = Color(*C_BG)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(
            pos=lambda *_: setattr(self._bg, "pos", self.pos),
            size=lambda *_: setattr(self._bg, "size", self.size),
        )

        self.header = HeaderBar(
            on_edit_toggle=self._toggle_edit,
            on_theme_toggle=self._toggle_theme,
            on_settings_open=self._open_settings,
            on_weather_tap=self._open_weather,
            on_all_off=self._all_off,
        )
        self.add_widget(self.header)

        self.scroll = ScrollView(do_scroll_x=False, bar_width=4, bar_color=C_SUBTEXT)
        self.grid = GridLayout(
            cols=CARD_COLS,
            spacing=CARD_SPACING,
            padding=[6, 4, 6, 4],
            size_hint_y=None,
        )
        self.grid.bind(minimum_height=self.grid.setter("height"))
        self.scroll.add_widget(self.grid)
        self.add_widget(self.scroll)

        global _on_sync_error
        _on_sync_error = self._on_supabase_error

        set_brightness(self._settings.get("screen_brightness", 200))
        threading.Thread(target=self._initial_load, daemon=True).start()
        Clock.schedule_interval(self._refresh_tick, REFRESH_INTERVAL)
        threading.Thread(target=self._weather_loop, daemon=True).start()

    # ── theme ─────────────────────────────────────────────────────────────────

    def _toggle_theme(self):
        global _DARK_MODE
        _DARK_MODE = not _DARK_MODE
        set_theme(PALETTE_DARK if _DARK_MODE else PALETTE_LIGHT)
        self._settings["dark_mode"] = _DARK_MODE
        threading.Thread(target=save_settings, args=(self._settings,), daemon=True).start()
        self._refresh_colors()

    @mainthread
    def _refresh_colors(self):
        Window.clearcolor            = C_BG
        self._bg_color_inst.rgba     = C_BG
        self.header.refresh_colors()
        self.header.set_theme_label(_DARK_MODE)
        self.header.set_edit_active(self._edit_mode)
        for card in self.cards.values():
            card.refresh_colors()

    # ── Supabase error feedback ────────────────────────────────────────────────

    @mainthread
    def _on_supabase_error(self, msg: str):
        print(f"[logging] Supabase sync failed: {msg}")
        if self._settings.get("show_sync_errors", True):
            self.header.set_status("⚠ Supabase sync failed", color=C_ERROR)

    # ── weather ───────────────────────────────────────────────────────────────

    def _weather_loop(self):
        lat, lon = _resolve_location(self._settings)
        if lat is None:
            return
        while True:
            if self._settings.get("show_weather", True):
                data = _fetch_weather(lat, lon)
                if data:
                    self._last_weather      = data["label"]
                    self._last_weather_data = data
                    self._update_weather(data["label"])
            self._weather_wake.wait(timeout=900)
            self._weather_wake.clear()

    @mainthread
    def _update_weather(self, text: str):
        self.header.set_weather(text)

    def _open_weather(self):
        if not self._last_weather_data:
            return
        WeatherModal(
            data=self._last_weather_data,
            city=self._settings.get("city", ""),
            lat=self._settings.get("latitude"),
            lon=self._settings.get("longitude"),
        ).open()

    # ── edit mode ─────────────────────────────────────────────────────────────

    def _toggle_edit(self):
        self._edit_mode = not self._edit_mode
        self.header.set_edit_active(self._edit_mode)
        self.scroll.do_scroll_y = not self._edit_mode
        for card in self.cards.values():
            card.set_edit_mode(self._edit_mode)

    # ── settings ──────────────────────────────────────────────────────────────

    def _open_settings(self):
        if not self._all_rooms:
            return
        hidden           = set(self._settings.get("hidden_rooms", []))
        brightness       = self._settings.get("screen_brightness", get_brightness())
        show_weather     = self._settings.get("show_weather", True)
        logging_enabled  = self._settings.get("logging_enabled", True)
        show_sync_errors = self._settings.get("show_sync_errors", True)
        exempt_rooms     = set(self._settings.get("exempt_rooms", []))
        SettingsPopup(
            all_rooms=self._all_rooms,
            hidden_rooms=hidden,
            on_save=self._on_settings_save,
            brightness=brightness,
            show_weather=show_weather,
            logging_enabled=logging_enabled,
            show_sync_errors=show_sync_errors,
            exempt_rooms=exempt_rooms,
        ).open()

    def _on_settings_save(self, hidden_rooms: set, brightness: int,
                          show_weather: bool, logging_enabled: bool,
                          show_sync_errors: bool, exempt_rooms: set):
        global _logging_enabled
        prev_show = self._settings.get("show_weather", True)
        self._settings["hidden_rooms"]       = list(hidden_rooms)
        self._settings["screen_brightness"]  = brightness
        self._settings["show_weather"]       = show_weather
        self._settings["logging_enabled"]    = logging_enabled
        self._settings["show_sync_errors"]   = show_sync_errors
        self._settings["exempt_rooms"]       = list(exempt_rooms)
        _logging_enabled = logging_enabled
        threading.Thread(target=save_settings, args=(self._settings,), daemon=True).start()
        if not show_weather:
            self._update_weather("")          # clear label immediately
        elif not prev_show:
            if self._last_weather:
                self._update_weather(self._last_weather)
            self._weather_wake.set()          # wake loop to fetch fresh data
        if self._last_groups:
            self._build_grid(self._last_groups)

    def _all_off(self):
        exempt = set(self._settings.get("exempt_rooms", []))
        for gid, card in self.cards.items():
            if gid not in exempt:
                card.turn_off()

    # ── touch / drag ──────────────────────────────────────────────────────────

    def on_touch_down(self, touch):
        if self._edit_mode:
            card = self._card_at(touch.pos)
            if card:
                self._begin_drag(card, touch)
                self._drag_touch_uid = touch.uid
                return True         # consume — children don't see this touch
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self._drag_touch_uid is not None and touch.uid == self._drag_touch_uid:
            self._update_drag(touch)
            return True             # consume before ScrollView can interfere
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if self._drag_touch_uid is not None and touch.uid == self._drag_touch_uid:
            self._end_drag(touch)
            self._drag_touch_uid = None
            return True
        return super().on_touch_up(touch)

    def _card_at(self, win_pos):
        """Return the RoomCard under a window-space coordinate, or None."""
        for card in self.cards.values():
            if card.collide_point(*card.parent.to_widget(*win_pos)):
                return card
        return None

    def _begin_drag(self, card, touch):
        self._drag_card  = card
        card.opacity     = 0.25

        ghost = DragGhost(card._room_name, card.width, card.height)
        ghost.center = touch.pos
        Window.add_widget(ghost)
        self._drag_ghost = ghost
        print(f"[drag] started: {card._room_name}")

    def _update_drag(self, touch):
        if self._drag_ghost:
            self._drag_ghost.center = touch.pos

        # Determine which card the ghost is hovering over
        target = self._card_at(touch.pos)
        if target is self._drag_card:
            target = None

        if target is not self._drag_target:
            if self._drag_target:
                self._drag_target.highlight_as_target(False)
            self._drag_target = target
            if target:
                target.highlight_as_target(True)

    def _end_drag(self, touch):
        # Remove ghost
        if self._drag_ghost:
            Window.remove_widget(self._drag_ghost)
            self._drag_ghost = None

        self._drag_card.opacity = 1.0

        # Swap positions if a valid target was found
        if self._drag_target:
            self._drag_target.highlight_as_target(False)
            self._swap_cards(self._drag_card, self._drag_target)

        self._drag_card   = None
        self._drag_target = None

    def _reading_order(self):
        """Grid children are stored back-to-front; return front-to-back."""
        return list(reversed(self.grid.children))

    def _swap_cards(self, card_a, card_b):
        ordered = self._reading_order()     # includes any padding BoxLayout
        ia, ib  = ordered.index(card_a), ordered.index(card_b)
        ordered[ia], ordered[ib] = ordered[ib], ordered[ia]

        self.grid.clear_widgets()
        for w in ordered:
            self.grid.add_widget(w)

        new_order = [w.group_id for w in self._reading_order() if isinstance(w, RoomCard)]
        self._settings["room_order"] = new_order
        threading.Thread(target=save_settings, args=(self._settings,), daemon=True).start()

    # ── load & refresh ────────────────────────────────────────────────────────

    def _initial_load(self):
        try:
            groups = self.api.get_groups()
            self._build_grid(groups)
        except Exception as exc:
            self._on_error(str(exc))

    @mainthread
    def _build_grid(self, groups: dict):
        self._last_groups = groups
        self._all_rooms   = rooms_ordered(groups, self._settings.get("room_order", []))

        hidden  = set(self._settings.get("hidden_rooms", []))
        visible = [(gid, g) for gid, g in self._all_rooms if gid not in hidden]

        self.grid.clear_widgets()
        self.cards.clear()

        for gid, group in visible:
            card = RoomCard(gid, group, self.api, size_hint_y=None, height=CARD_HEIGHT)
            self.cards[gid] = card
            self.grid.add_widget(card)

        if len(visible) % CARD_COLS != 0:
            self.grid.add_widget(BoxLayout())   # pad to even columns

        # Rebuild light → group map for SSE routing
        self._light_to_group = {}
        for gid, group in self._all_rooms:
            for lid in group.get("lights", []):
                self._light_to_group[lid] = gid

        self._busy = False

        if not self._sse_started:
            self._sse_started = True
            threading.Thread(target=self._sse_listener, daemon=True).start()

    def _refresh_tick(self, _dt):
        if self._busy or self._edit_mode:
            return
        threading.Thread(target=self._do_refresh, daemon=True).start()

    def _do_refresh(self):
        try:
            groups = self.api.get_groups()
            self._apply_refresh(groups)
        except Exception as exc:
            self._on_error(str(exc))

    @mainthread
    def _apply_refresh(self, groups: dict):
        for gid, card in self.cards.items():
            if gid in groups:
                card.apply_group(groups[gid])

    @mainthread
    def _on_error(self, msg: str):
        self.header.set_status(f"⚠ {msg[:50]}", color=C_ERROR)
        print(f"[Lumio] error: {msg}")

    # ── SSE real-time listener ─────────────────────────────────────────────────

    def _sse_listener(self):
        """Background thread: streams CLIP v2 events and refreshes affected groups."""
        print("[SSE] listener started")
        for events in self.api.event_stream():
            if isinstance(events, dict):
                status = events.get("_sse")
                if status == "connected":
                    log_system("sse_connected")
                elif status == "disconnected":
                    log_system("sse_disconnected", events.get("_error"))
                continue
            if not isinstance(events, list):
                continue
            # affected: gid → {owner_type, ts, on (bool|None), bri_pct (int|None)}
            affected = {}
            for event in events:
                ct = event.get("creationtime")
                for item in event.get("data", []):
                    id_v1      = item.get("id_v1", "")
                    owner_type = item.get("owner", {}).get("rtype")
                    on_val     = item.get("on",      {}).get("on")       # bool or None
                    bri_raw    = item.get("dimming", {}).get("brightness") # 0-100 float or None
                    bri_pct    = round(bri_raw) if bri_raw is not None else None

                    gid = None
                    if id_v1.startswith("/lights/"):
                        lid = id_v1.split("/")[-1]
                        gid = self._light_to_group.get(lid)
                    elif id_v1.startswith("/groups/"):
                        g = id_v1.split("/")[-1]
                        if g in self.cards:
                            gid = g

                    if gid and gid not in affected:
                        affected[gid] = {
                            "owner_type": owner_type, "ts": ct,
                            "on": on_val, "bri_pct": bri_pct,
                        }

            for gid, meta in affected.items():
                if not _is_huecontrol_recent(gid) and _should_log_sse(gid):
                    card = self.cards.get(gid)
                    if card:
                        bri_pct = meta["bri_pct"] if meta["bri_pct"] is not None \
                                  else round(card._bri / 254 * 100)
                        if meta["on"] is not None:
                            log_event(card._room_name, gid,
                                      "on" if meta["on"] else "off",
                                      bri_pct, "external",
                                      meta["owner_type"], meta["ts"])
                        elif meta["bri_pct"] is not None:
                            log_event(card._room_name, gid, "brightness",
                                      bri_pct, "external",
                                      meta["owner_type"], meta["ts"])
                threading.Thread(
                    target=self._refresh_group, args=(gid,), daemon=True
                ).start()

    def _refresh_group(self, gid: str):
        try:
            group = self.api.get_group(gid)
            card  = self.cards.get(gid)
            if card:
                card.apply_group(group)
        except Exception as exc:
            print(f"[SSE] refresh group {gid}: {exc}")
            log_system("error", f"refresh group {gid}: {exc}")


# ── Error screen ──────────────────────────────────────────────────────────────

class ErrorScreen(BoxLayout):
    """Shown when hue_config.json is missing or unreadable."""

    def __init__(self, message: str, **kwargs):
        super().__init__(orientation="vertical", padding=40, **kwargs)
        with self.canvas.before:
            Color(*C_BG)
            self._r = Rectangle(pos=self.pos, size=self.size)
        self.bind(
            pos=lambda *_: setattr(self._r, "pos", self.pos),
            size=lambda *_: setattr(self._r, "size", self.size),
        )
        self.add_widget(Label(
            text="[b]Lumio[/b]", markup=True,
            font_size="28sp", color=C_TEXT, size_hint_y=0.3,
        ))
        self.add_widget(Label(
            text=message, font_size="16sp", color=C_ERROR,
            halign="center", valign="middle",
        ))


# ── App ───────────────────────────────────────────────────────────────────────

class HueApp(App):
    title = "Lumio"

    def build(self):
        cfg = load_settings()
        init_logging(cfg)
        log_system("app_start")
        Window.clearcolor = C_BG
        try:
            api = HueAPI()
        except FileNotFoundError as exc:
            return ErrorScreen(str(exc))
        return RoomGrid(api=api)

    def on_stop(self):
        log_system("app_stop")


if __name__ == "__main__":
    HueApp().run()
