"""ui_cards.py — Room card widget."""

import threading

from kivy.clock import Clock, mainthread
from kivy.graphics import Color, RoundedRectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.slider import Slider

from theme import C, CARD_HEIGHT, SYMBOL_FONT
from lumio_log import log_event, log_system, _mark_huecontrol



# ── RoomCard ──────────────────────────────────────────────────────────────────

class RoomCard(BoxLayout):
    """
    Two-row card.  Normal mode:
        ┌────────────────────────────────────┐
        │  Room Name              [ ON/OFF ] │
        │  [══════════ slider ══════════════]│
        └────────────────────────────────────┘
    Sort mode (ON/OFF and slider replaced):
        ┌────────────────────────────────────┐
        │  Room Name             [ ▲ ] [ ▼ ] │
        │                                    │
        └────────────────────────────────────┘
    """

    SLIDER_DEBOUNCE = 0.35

    def __init__(self, group_id: str, group: dict, api,
                 on_move=None, **kwargs):
        super().__init__(
            orientation="horizontal",
            padding=0,
            spacing=0,
            **kwargs,
        )
        self.group_id    = group_id
        self.api         = api
        self._on_move_cb = on_move   # callback(card, "up"|"down")
        self._pending    = False
        self._slider_ev  = None
        self._updating   = False
        self._in_edit    = False

        state  = group.get("state", {})
        action = group.get("action", {})
        self._is_on     = state.get("any_on", False)
        self._light_ids = group.get("lights", [])
        self._room_name = group.get("name", "Room")
        self._bri       = action.get("bri", 254)

        with self.canvas.before:
            self._bg_color = Color(*self._card_rgba())
            self._bg_rect  = RoundedRectangle(radius=[10], pos=self.pos, size=self.size)
        self.bind(pos=self._sync_bg, size=self._sync_bg)

        # Left panel: room name (top) + brightness slider (bottom)
        left = BoxLayout(
            orientation="vertical",
            size_hint_x=0.70,
            padding=[12, 6, 6, 6],
            spacing=2,
        )

        self.name_lbl = Label(
            text=self._room_name,
            font_size="17sp",
            bold=True,
            color=self._name_rgba(),
            halign="left",
            valign="middle",
            size_hint_y=0.52,
        )
        self.name_lbl.bind(size=lambda w, _: setattr(w, "text_size", (w.width, None)))

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
            color=C.SUBTEXT,
            size_hint=(None, 1),
            width=40,
            halign="right",
            valign="middle",
        )
        self.pct_lbl.bind(size=lambda w, _: setattr(w, "text_size", (w.width, None)))
        bri_row.add_widget(self.slider)
        bri_row.add_widget(self.pct_lbl)

        left.add_widget(self.name_lbl)
        left.add_widget(bri_row)

        # Right panel: ON/OFF button (normal) or ▲▼ arrows (sort mode)
        self._right = BoxLayout(
            orientation="vertical",
            size_hint_x=0.30,
            padding=[4, 10, 8, 10],
        )
        self.btn = Button(
            text="ON" if self._is_on else "OFF",
            font_size="15sp",
            bold=True,
            background_normal="",
            background_down="",
            background_color=C.BTN_ON if self._is_on else C.BTN_OFF,
            color=(1, 1, 1, 1),
        )
        self.btn.bind(on_release=self._handle_toggle)
        self._right.add_widget(self.btn)

        # Sort arrows panel — swapped in when sort mode is active; ▲ left, ▼ right
        self._sort_panel = BoxLayout(orientation="horizontal", spacing=4)
        self._up_btn = Button(text="▲", font_name=SYMBOL_FONT or 'Roboto',
                              font_size="20sp", bold=True,
                              background_normal="", background_down="",
                              background_color=C.BTN_OFF, color=(1, 1, 1, 1))
        self._dn_btn = Button(text="▼", font_name=SYMBOL_FONT or 'Roboto',
                              font_size="20sp", bold=True,
                              background_normal="", background_down="",
                              background_color=C.BTN_OFF, color=(1, 1, 1, 1))
        self._up_btn.bind(on_release=lambda _: self._emit_move("up"))
        self._dn_btn.bind(on_release=lambda _: self._emit_move("down"))
        self._sort_panel.add_widget(self._up_btn)
        self._sort_panel.add_widget(self._dn_btn)

        self.add_widget(left)
        self.add_widget(self._right)

    # ── canvas helpers ────────────────────────────────────────────────────────

    def _card_rgba(self):
        return C.CARD_ON if self._is_on else C.CARD_OFF

    def _name_rgba(self):
        return C.TEXT_ON if self._is_on else C.TEXT

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

    # ── edit mode ─────────────────────────────────────────────────────────────

    def set_edit_mode(self, edit: bool):
        self._in_edit = edit
        self._right.clear_widgets()
        if edit:
            self._right.add_widget(self._sort_panel)
            self.slider.opacity  = 0
            self.pct_lbl.opacity = 0
            self.slider.disabled = True
            self.name_lbl.color  = C.TEXT
        else:
            self._right.add_widget(self.btn)
            self.slider.opacity  = 1
            self.pct_lbl.opacity = 1
            self.slider.disabled = False
            self.name_lbl.color  = self._name_rgba()

    def _emit_move(self, direction: str):
        if self._on_move_cb:
            self._on_move_cb(self, direction)

    # ── on/off toggle ─────────────────────────────────────────────────────────

    def _handle_toggle(self, *_):
        if self._in_edit or self._pending:
            return
        self._pending = True
        new_state = not self._is_on
        self._apply_on_state(new_state)
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
        if not self._is_on:
            return   # update local display only; don't call API when light is off
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
            return
        self._light_ids = group.get("lights", self._light_ids)
        self._is_on     = group.get("state", {}).get("any_on", False)
        bri = group.get("action", {}).get("bri", self._bri)
        self._apply_on_state(self._is_on)
        self._set_slider(bri)

    @mainthread
    def apply_sse_state(self, on, bri_pct):
        """Immediately reflect a known SSE state change without an API round-trip."""
        if self._pending:
            return
        if on is not None:
            self._apply_on_state(on)
        if bri_pct is not None:
            self._set_slider(round(bri_pct / 100 * 254))

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
        self.name_lbl.color       = C.TEXT if self._in_edit else self._name_rgba()
        self.btn.text             = "ON" if on else "OFF"
        self.btn.background_color = C.BTN_ON if on else C.BTN_OFF

    def refresh_colors(self):
        self._bg_color.rgba         = self._card_rgba()
        self.name_lbl.color         = C.TEXT if self._in_edit else self._name_rgba()
        self.btn.background_color   = C.BTN_ON if self._is_on else C.BTN_OFF
        self._up_btn.background_color = C.BTN_OFF
        self._dn_btn.background_color = C.BTN_OFF
