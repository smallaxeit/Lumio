#!/usr/bin/env python3
"""
lumio.py — Lumio Kivy touchscreen app for Raspberry Pi 4.
Room grid with on/off toggle, brightness slider, and ▲▼ sort mode.
Optimised for the official 7" Pi touchscreen (800×480).

Requirements:
    pip install kivy requests

Run on Pi (fullscreen):
    DISPLAY=:0 python lumio.py
"""

import threading

# ── Kivy config — must happen before any other kivy imports ───────────────────

DEV_WINDOW_SIZE = (800, 480)   # set None on Pi to use display native size

from kivy.config import Config
Config.set('input', 'mouse', 'mouse,disable_multitouch')
Config.set('input', 'wm_touch', 'wm_touch')
Config.set('input', 'wm_pen',   'wm_pen')
if DEV_WINDOW_SIZE:
    Config.set('graphics', 'width',     str(DEV_WINDOW_SIZE[0]))
    Config.set('graphics', 'height',    str(DEV_WINDOW_SIZE[1]))
    Config.set('graphics', 'resizable', '0')
else:
    Config.set('graphics', 'fullscreen',  'auto')
    Config.set('graphics', 'show_cursor', '0')

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView

# ── Project modules ───────────────────────────────────────────────────────────

from theme import (
    C, set_theme, PALETTE_DARK, PALETTE_LIGHT,
    CARD_COLS, CARD_SPACING, CARD_HEIGHT, REFRESH_INTERVAL,
    load_settings, save_settings, rooms_ordered,
)
from lumio_api import HueAPI
from lumio_log import (
    init_logging, log_system, log_event,
    _is_huecontrol_recent, _should_log_sse,
)
import lumio_log
from lumio_brightness import set_brightness, get_brightness
from lumio_weather import _fetch_weather, _resolve_location
from ui_cards import RoomCard
from ui_panels import SettingsPopup, WeatherModal, HeaderBar
from ui_weather_kiosk import WeatherKiosk


# ── RoomGrid ──────────────────────────────────────────────────────────────────

class RoomGrid(BoxLayout):
    """
    Root widget.

    Normal mode : Header + scrollable 2-col card grid.
    Edit mode   : Scrolling disabled; sliders replaced by ▲▼ arrows per card.
                  Tap ▲/▼ to move a card one row up/down in its column.
                  New order saved to hue_settings.json on each move.
    """

    def __init__(self, api: HueAPI, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.api           = api
        self.cards         = {}     # gid → RoomCard
        self._busy         = True
        self._edit_mode    = False
        self._settings     = load_settings()
        self._dark_mode    = self._settings.get("dark_mode", False)

        set_theme(PALETTE_DARK if self._dark_mode else PALETTE_LIGHT)
        Window.clearcolor = C.BG

        self._all_rooms       = []   # all (gid, group) from last fetch
        self._last_groups     = {}   # raw groups dict from last fetch
        self._light_to_group  = {}   # light_id → group_id (for SSE routing)
        self._sse_started     = False
        self._last_weather      = ""
        self._last_weather_data = None
        self._weather_wake      = threading.Event()
        self._kiosk             = None   # WeatherKiosk, built lazily on first expand

        with self.canvas.before:
            self._bg_color_inst = Color(*C.BG)
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
            # on_all_off=self._all_off,  # All Off button — enable if needed
        )
        self.header.set_theme_label(self._dark_mode)
        self.add_widget(self.header)

        self.scroll = ScrollView(
            do_scroll_x=False,
            bar_width=4,
            bar_color=C.SUBTEXT,
            size_hint_y=1,
            always_overscroll=False,
        )
        self.grid = GridLayout(
            cols=CARD_COLS,
            spacing=CARD_SPACING,
            padding=[6, 4, 6, 4],
            size_hint_y=None,
        )
        self.grid.bind(minimum_height=self.grid.setter("height"))
        self.scroll.add_widget(self.grid)
        self.add_widget(self.scroll)

        # Register Supabase error callback in lumio_log module
        lumio_log._on_sync_error = self._on_supabase_error

        set_brightness(self._settings.get("screen_brightness", 200))
        threading.Thread(target=self._initial_load, daemon=True).start()
        Clock.schedule_interval(self._refresh_tick, REFRESH_INTERVAL)
        threading.Thread(target=self._weather_loop, daemon=True).start()

    # ── theme ─────────────────────────────────────────────────────────────────

    def _toggle_theme(self):
        self._dark_mode = not self._dark_mode
        set_theme(PALETTE_DARK if self._dark_mode else PALETTE_LIGHT)
        self._settings["dark_mode"] = self._dark_mode
        threading.Thread(target=save_settings, args=(self._settings,), daemon=True).start()
        self._refresh_colors()

    @mainthread
    def _refresh_colors(self):
        Window.clearcolor        = C.BG
        self._bg_color_inst.rgba = C.BG
        self.header.refresh_colors()
        self.header.set_theme_label(self._dark_mode)
        self.header.set_edit_active(self._edit_mode)
        for card in self.cards.values():
            card.refresh_colors()

    # ── Supabase error feedback ────────────────────────────────────────────────

    @mainthread
    def _on_supabase_error(self, msg: str):
        print(f"[logging] Supabase sync failed: {msg}")
        if self._settings.get("show_sync_errors", True):
            self.header.set_status("⚠ Supabase sync failed", color=C.ERROR)

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
            self._weather_wake.wait(timeout=self._settings.get("weather_poll_seconds", 120))
            self._weather_wake.clear()

    @mainthread
    def _update_weather(self, text: str):
        self.header.set_weather(text)
        if self._kiosk is not None and self._kiosk.parent is not None:
            self._push_weather_to_kiosk()

    def _open_weather(self):
        if not self._last_weather_data:
            return
        WeatherModal(
            data=self._last_weather_data,
            city=self._settings.get("city", ""),
            lat=self._settings.get("latitude"),
            lon=self._settings.get("longitude"),
            on_expand=self._show_weather_kiosk,
        ).open()

    def _push_weather_to_kiosk(self):
        self._kiosk.update(
            data=self._last_weather_data,
            city=self._settings.get("city", ""),
            lat=self._settings.get("latitude"),
            lon=self._settings.get("longitude"),
        )
        self._kiosk.set_favorites(self._kiosk_favorites(), self.api)

    def _kiosk_favorites(self):
        """Top entries from the configured room order — the kiosk's quick
        on/off toggles ('always take the top two per the local config')."""
        favorites = []
        for gid in self._settings.get("room_order", []):
            group = self._last_groups.get(gid)
            if group:
                favorites.append((gid, group.get("name", "?"),
                                  group.get("state", {}).get("any_on", False)))
            if len(favorites) == 2:
                break
        return favorites

    def _show_weather_kiosk(self):
        if not self._last_weather_data:
            return
        if self._kiosk is None:
            self._kiosk = WeatherKiosk(on_back=self._show_room_grid)
        self._push_weather_to_kiosk()
        self.remove_widget(self.header)
        self.remove_widget(self.scroll)
        self.add_widget(self._kiosk)

    def _show_room_grid(self):
        if self._kiosk is not None:
            self.remove_widget(self._kiosk)
        self.add_widget(self.header)
        self.add_widget(self.scroll)

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
            on_theme_toggle=self._toggle_theme,
            dark_mode=self._dark_mode,
            brightness=brightness,
            show_weather=show_weather,
            logging_enabled=logging_enabled,
            show_sync_errors=show_sync_errors,
            exempt_rooms=exempt_rooms,
        ).open()

    def _on_settings_save(self, hidden_rooms: set, brightness: int,
                          show_weather: bool, logging_enabled: bool,
                          show_sync_errors: bool, exempt_rooms: set):
        prev_show = self._settings.get("show_weather", True)
        self._settings["hidden_rooms"]      = list(hidden_rooms)
        self._settings["screen_brightness"] = brightness
        self._settings["show_weather"]      = show_weather
        self._settings["logging_enabled"]   = logging_enabled
        self._settings["show_sync_errors"]  = show_sync_errors
        self._settings["exempt_rooms"]      = list(exempt_rooms)
        lumio_log._logging_enabled = logging_enabled
        threading.Thread(target=save_settings, args=(self._settings,), daemon=True).start()
        if not show_weather:
            self._update_weather("")
        elif not prev_show:
            if self._last_weather:
                self._update_weather(self._last_weather)
            self._weather_wake.set()
        if self._last_groups:
            self._build_grid(self._last_groups)

    def _all_off(self):
        exempt = set(self._settings.get("exempt_rooms", []))
        for gid, card in self.cards.items():
            if gid not in exempt:
                card.turn_off()

    def _reading_order(self):
        """Grid children are stored back-to-front; return front-to-back."""
        return list(reversed(self.grid.children))

    def _move_card(self, card, direction: str):
        """Move card one row up or down in its column (called by ▲▼ buttons)."""
        cards = [w for w in self._reading_order() if isinstance(w, RoomCard)]
        idx = cards.index(card)
        new_idx = idx + (-CARD_COLS if direction == "up" else CARD_COLS)
        if new_idx < 0 or new_idx >= len(cards):
            return
        full = self._reading_order()
        ia, ib = full.index(cards[idx]), full.index(cards[new_idx])
        full[ia], full[ib] = full[ib], full[ia]
        self.grid.clear_widgets()
        for w in full:
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
            card = RoomCard(gid, group, self.api,
                            on_move=self._move_card,
                            size_hint_y=None, height=CARD_HEIGHT)
            self.cards[gid] = card
            self.grid.add_widget(card)

        if len(visible) % CARD_COLS != 0:
            self.grid.add_widget(BoxLayout())   # pad to even columns

        if self._edit_mode:
            for card in self.cards.values():
                card.set_edit_mode(True)

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
        self.header.set_status(f"⚠ {msg[:50]}", color=C.ERROR)
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
                    on_val     = item.get("on",      {}).get("on")
                    bri_raw    = item.get("dimming", {}).get("brightness")
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
                card = self.cards.get(gid)
                if not _is_huecontrol_recent(gid):
                    if card and (meta["on"] is not None or meta["bri_pct"] is not None):
                        card.apply_sse_state(meta["on"], meta["bri_pct"])
                    if _should_log_sse(gid) and card:
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
    """Shown when hue_settings.json is missing or credentials are invalid."""

    def __init__(self, message: str, **kwargs):
        super().__init__(orientation="vertical", padding=40, **kwargs)
        from kivy.graphics import Rectangle as _Rect
        with self.canvas.before:
            Color(*C.BG)
            self._r = _Rect(pos=self.pos, size=self.size)
        self.bind(
            pos=lambda *_: setattr(self._r, "pos", self.pos),
            size=lambda *_: setattr(self._r, "size", self.size),
        )
        self.add_widget(Label(
            text="[b]Lumio[/b]", markup=True,
            font_size="28sp", color=C.TEXT, size_hint_y=0.3,
        ))
        self.add_widget(Label(
            text=message, font_size="16sp", color=C.ERROR,
            halign="center", valign="middle",
        ))


# ── App ───────────────────────────────────────────────────────────────────────

class LumioApp(App):
    title = "Lumio"

    def build(self):
        cfg = load_settings()
        init_logging(cfg)
        log_system("app_start")
        Window.clearcolor = C.BG
        try:
            api = HueAPI()
        except FileNotFoundError as exc:
            return ErrorScreen(str(exc))
        return RoomGrid(api=api)

    def on_stop(self):
        log_system("app_stop")


if __name__ == "__main__":
    LumioApp().run()
