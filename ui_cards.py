"""ui_cards.py — Room card and per-light detail modal."""

import threading

from kivy.clock import Clock, mainthread
from kivy.graphics import Color, RoundedRectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider

from theme import C, CARD_HEIGHT, CARD_SPACING, SYMBOL_FONT
from lumio_log import log_event, log_system, _mark_huecontrol


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
            background_color=C.BTN_ON if self._is_on else C.BTN_OFF,
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
            color=C.SUBTEXT,
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
        return C.CARD_ON if self._is_on else C.CARD_OFF

    def _name_rgba(self):
        return C.TEXT_ON if self._is_on else C.TEXT

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
        self.btn.background_color = C.BTN_ON if on else C.BTN_OFF


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
            Color(*C.BG)
            self._card_rect = RoundedRectangle(radius=[16], pos=card.pos, size=card.size)
        card.bind(
            pos=lambda *_: setattr(self._card_rect, "pos", card.pos),
            size=lambda *_: setattr(self._card_rect, "size", card.size),
        )

        hdr = BoxLayout(orientation="horizontal", size_hint_y=None, height=44)
        hdr.add_widget(Label(
            text=room_name,
            font_size="20sp",
            bold=True,
            color=C.TEXT,
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
            color=C.SUBTEXT,
        )
        close_btn.bind(on_release=lambda _: self.dismiss())
        hdr.add_widget(close_btn)
        card.add_widget(hdr)

        scroll = ScrollView(do_scroll_x=False, bar_width=4)
        self._light_list = GridLayout(cols=1, spacing=CARD_SPACING, size_hint_y=None)
        self._light_list.bind(minimum_height=self._light_list.setter("height"))
        self._light_list.add_widget(Label(
            text="Loading…", color=C.SUBTEXT, size_hint_y=None, height=60,
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
                text="No lights found", color=C.SUBTEXT, size_hint_y=None, height=60,
            ))


# ── RoomCard ──────────────────────────────────────────────────────────────────

class RoomCard(BoxLayout):
    """
    Vertical two-row card:
        ┌────────────────────────────────────┐
        │  Room Name              [ ON/OFF ] │  ← top row
        │  [══════════ slider ══════════════]│  ← brightness (hidden in edit mode)
        └────────────────────────────────────┘
    """

    SLIDER_DEBOUNCE = 0.35

    def __init__(self, group_id: str, group: dict, api,
                 on_long_press=None, **kwargs):
        super().__init__(
            orientation="horizontal",
            padding=0,
            spacing=0,
            **kwargs,
        )
        self.group_id       = group_id
        self.api            = api
        self._on_long_press = on_long_press   # callback: enter sort mode
        self._pending       = False
        self._slider_ev     = None
        self._updating      = False
        self._in_edit       = False
        self._lp_event      = None       # long-press timer
        self._lp_touch_uid  = None       # track touch without grabbing
        self._long_pressed  = False      # suppress button release after long press
        self._lp_ox = self._lp_oy = 0   # touch origin for move threshold

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

        # Right panel: ON/OFF button with vertical padding so it sits inset in the card
        right = BoxLayout(
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
        right.add_widget(self.btn)

        self.add_widget(left)
        self.add_widget(right)

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

    # ── long-press → sort mode ────────────────────────────────────────────────

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._lp_ox, self._lp_oy = touch.pos
            self._lp_touch_uid = touch.uid
            self._lp_event = Clock.schedule_once(self._do_long_press, 0.5)
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self._lp_event and touch.uid == self._lp_touch_uid:
            if abs(touch.x - self._lp_ox) > 10 or abs(touch.y - self._lp_oy) > 10:
                self._lp_event.cancel()
                self._lp_event = None
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.uid == self._lp_touch_uid:
            self._lp_touch_uid = None
            if self._lp_event:
                self._lp_event.cancel()
                self._lp_event = None
        return super().on_touch_up(touch)

    def _do_long_press(self, dt):
        self._lp_event     = None
        self._long_pressed = True
        if self._on_long_press:
            self._on_long_press(self)
        else:
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
        self.name_lbl.color   = C.TEXT if edit else self._name_rgba()

    def highlight_as_target(self, active: bool):
        """Show or clear the drop-target highlight colour."""
        self._bg_color.rgba = C.CARD_TARGET if active else self._card_rgba()

    # ── on/off toggle ─────────────────────────────────────────────────────────

    def _handle_toggle(self, *_):
        if self._in_edit or self._pending:
            return
        if self._long_pressed:
            self._long_pressed = False
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
        self._bg_color.rgba       = self._card_rgba()
        self.name_lbl.color       = C.TEXT if self._in_edit else self._name_rgba()
        self.btn.background_color = C.BTN_ON if self._is_on else C.BTN_OFF
