"""ui_panels.py — SettingsPopup, WeatherModal, DayDetailModal, HeaderBar."""

import threading
from datetime import datetime

from kivy.clock import Clock, mainthread
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider

from theme import C, _TappableRow, _WeatherBtn, _DayCol, CARD_SPACING, SYMBOL_FONT
from lumio_brightness import set_brightness
from lumio_weather import _fetch_hourly, get_icon_path


# ── SettingsPopup ─────────────────────────────────────────────────────────────

class SettingsPopup(ModalView):
    """Modal settings panel — brightness, weather, advanced, room visibility."""

    ROW_HEIGHT = 54

    def __init__(self, all_rooms: list, hidden_rooms: set, on_save,
                 on_theme_toggle=None, dark_mode: bool = False,
                 brightness: int = 200, show_weather: bool = True,
                 logging_enabled: bool = True, show_sync_errors: bool = True,
                 exempt_rooms: set = None, **kwargs):
        super().__init__(
            background_color=(0, 0, 0, 0.55),
            size_hint=(0.90, 0.93),
            pos_hint={'center_x': 0.5, 'top': 0.99},
            **kwargs,
        )
        self._on_save          = on_save
        self._on_theme_toggle  = on_theme_toggle
        self._dark_mode        = dark_mode
        self._visible          = {gid: gid not in hidden_rooms for gid, _ in all_rooms}
        self._included         = {gid: gid not in (exempt_rooms or set()) for gid, _ in all_rooms}
        self._rows             = {}   # gid → (bg, show_check, name_lbl, alloff_check)
        self._show_weather     = show_weather
        self._logging_enabled  = logging_enabled
        self._show_sync_errors = show_sync_errors
        self._adv_open         = False

        card = BoxLayout(orientation='vertical', padding=[14, 8, 14, 8], spacing=6)
        with card.canvas.before:
            self._card_bg = Color(*C.BG)
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

        # Single scrollable content area (everything except header + done button)
        scroll = ScrollView(do_scroll_x=False, bar_width=4)
        inner = GridLayout(cols=1, spacing=8, size_hint_y=None)
        inner.bind(minimum_height=inner.setter('height'))

        # Brightness
        bri_lbl = Label(
            text="Screen Brightness",
            font_size="14sp",
            bold=True,
            color=C.SUBTEXT,
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
            color=C.SUBTEXT,
            size_hint=(None, 1),
            width=44,
        )
        self._bri_slider.bind(value=self._on_bri_change)
        bri_row.add_widget(self._bri_slider)
        bri_row.add_widget(self._bri_pct)
        inner.add_widget(bri_row)

        # Dark Mode + Weather — compact side-by-side toggles
        toggle_row = BoxLayout(
            orientation='horizontal',
            size_hint_y=None, height=38,
            spacing=8,
        )

        theme_btn = _TappableRow(
            orientation='horizontal',
            padding=[10, 0, 10, 0], spacing=6,
        )
        with theme_btn.canvas.before:
            self._theme_bg = Color(*(C.CARD_ON if dark_mode else C.CARD_OFF))
            theme_rect = RoundedRectangle(radius=[8], pos=theme_btn.pos, size=theme_btn.size)
        theme_btn.bind(
            pos=lambda w, _: setattr(theme_rect, 'pos', w.pos),
            size=lambda w, _: setattr(theme_rect, 'size', w.size),
            on_release=lambda _: self._toggle_theme(),
        )
        self._theme_check = Label(
            text="✓" if dark_mode else "",
            font_name=SYMBOL_FONT or 'Roboto',
            font_size="15sp", bold=True, color=C.BTN_ON,
            size_hint=(None, 1), width=20,
            halign='center', valign='middle',
        )
        self._theme_name = Label(
            text="Dark Mode",
            font_size="13sp", bold=True,
            color=C.TEXT if dark_mode else C.SUBTEXT,
            halign='left', valign='middle',
        )
        self._theme_name.bind(size=lambda w, _: setattr(w, 'text_size', (w.width, None)))
        theme_btn.add_widget(self._theme_check)
        theme_btn.add_widget(self._theme_name)
        toggle_row.add_widget(theme_btn)

        wx_btn = _TappableRow(
            orientation='horizontal',
            padding=[10, 0, 10, 0], spacing=6,
        )
        with wx_btn.canvas.before:
            self._wx_bg = Color(*(C.CARD_ON if show_weather else C.CARD_OFF))
            wx_rect     = RoundedRectangle(radius=[8], pos=wx_btn.pos, size=wx_btn.size)
        wx_btn.bind(
            pos=lambda w, _: setattr(wx_rect, 'pos', w.pos),
            size=lambda w, _: setattr(wx_rect, 'size', w.size),
            on_release=lambda _: self._toggle_weather(),
        )
        self._wx_check = Label(
            text="✓" if show_weather else "",
            font_name=SYMBOL_FONT or 'Roboto',
            font_size="15sp", bold=True, color=C.BTN_ON,
            size_hint=(None, 1), width=20,
            halign='center', valign='middle',
        )
        self._wx_name = Label(
            text="Weather",
            font_size="13sp", bold=True,
            color=C.TEXT if show_weather else C.SUBTEXT,
            halign='left', valign='middle',
        )
        self._wx_name.bind(size=lambda w, _: setattr(w, 'text_size', (w.width, None)))
        wx_btn.add_widget(self._wx_check)
        wx_btn.add_widget(self._wx_name)
        toggle_row.add_widget(wx_btn)

        inner.add_widget(toggle_row)

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
            Color(*C.CARD_OFF)
            adv_hdr_rect = RoundedRectangle(radius=[8], pos=adv_hdr.pos, size=adv_hdr.size)
        adv_hdr.bind(
            pos=lambda w, _: setattr(adv_hdr_rect, 'pos', w.pos),
            size=lambda w, _: setattr(adv_hdr_rect, 'size', w.size),
            on_release=lambda _: self._toggle_advanced(),
        )
        self._adv_lbl = Label(
            text="▸  Advanced",
            font_size="13sp", bold=True,
            color=C.SUBTEXT,
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
            self._log_bg = Color(*(C.CARD_ON if logging_enabled else C.CARD_OFF))
            log_rect     = RoundedRectangle(radius=[8], pos=log_row.pos, size=log_row.size)
        log_row.bind(
            pos=lambda w, _: setattr(log_rect, 'pos', w.pos),
            size=lambda w, _: setattr(log_rect, 'size', w.size),
            on_release=lambda _: self._toggle_logging(),
        )
        self._log_name = Label(
            text="Enable Logging",
            font_size="15sp", bold=True,
            color=C.TEXT if logging_enabled else C.SUBTEXT,
            halign='left', valign='middle',
        )
        self._log_name.bind(size=lambda w, _: setattr(w, 'text_size', (w.width, None)))
        self._log_check = Label(
            text="✓" if logging_enabled else "",
            font_name=SYMBOL_FONT or 'Roboto',
            font_size="18sp", bold=True, color=C.BTN_ON,
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
            self._sync_bg = Color(*(C.CARD_ON if show_sync_errors else C.CARD_OFF))
            sync_rect     = RoundedRectangle(radius=[8], pos=sync_row.pos, size=sync_row.size)
        sync_row.bind(
            pos=lambda w, _: setattr(sync_rect, 'pos', w.pos),
            size=lambda w, _: setattr(sync_rect, 'size', w.size),
            on_release=lambda _: self._toggle_sync_errors(),
        )
        self._sync_name = Label(
            text="Show Sync Errors",
            font_size="15sp", bold=True,
            color=C.TEXT if show_sync_errors else C.SUBTEXT,
            halign='left', valign='middle',
        )
        self._sync_name.bind(size=lambda w, _: setattr(w, 'text_size', (w.width, None)))
        self._sync_check = Label(
            text="✓" if show_sync_errors else "",
            font_name=SYMBOL_FONT or 'Roboto',
            font_size="18sp", bold=True, color=C.BTN_ON,
            size_hint=(None, 1), width=36,
            halign='center', valign='middle',
        )
        sync_row.add_widget(self._sync_name)
        sync_row.add_widget(self._sync_check)
        self._adv_content.add_widget(sync_row)

        # Displayed Rooms header row with column labels
        rooms_hdr = BoxLayout(orientation='horizontal', size_hint_y=None, height=26)
        rooms_main_lbl = Label(
            text="Displayed Rooms",
            font_size="14sp", bold=True,
            color=C.SUBTEXT,
            halign="left", valign="middle",
        )
        rooms_main_lbl.bind(size=lambda w, _: setattr(w, "text_size", (w.width, None)))
        rooms_hdr.add_widget(rooms_main_lbl)
        rooms_hdr.add_widget(Label(
            text="Show", font_size="14sp", bold=True, color=C.SUBTEXT,
            halign="center", size_hint=(None, 1), width=58,
        ))
        rooms_hdr.add_widget(Label(
            text="All Off", font_size="14sp", bold=True, color=C.SUBTEXT,
            halign="center", size_hint=(None, 1), width=58,
        ))
        inner.add_widget(rooms_hdr)

        room_list = GridLayout(cols=1, spacing=CARD_SPACING, size_hint_y=None)
        room_list.bind(minimum_height=room_list.setter('height'))
        for gid, group in all_rooms:
            room_list.add_widget(self._make_row(gid, group.get('name', 'Room')))
        inner.add_widget(room_list)

        inner.add_widget(self._adv_wrapper)

        scroll.add_widget(inner)
        card.add_widget(scroll)

        # Done button
        done_btn = Button(
            text="Done",
            size_hint_y=None,
            height=48,
            background_normal="",
            background_down="",
            background_color=C.BTN_ON,
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
            padding=[12, 0, 12, 0],
            spacing=0,
        )
        with row.canvas.before:
            bg   = Color(*(C.CARD_ON if visible else C.CARD_OFF))
            rect = RoundedRectangle(radius=[8], pos=row.pos, size=row.size)
        row.bind(
            pos=lambda w, _: setattr(rect, 'pos', w.pos),
            size=lambda w, _: setattr(rect, 'size', w.size),
        )

        name_lbl = Label(
            text=name,
            font_size="15sp", bold=True,
            color=C.TEXT if visible else C.SUBTEXT,
            halign='left', valign='middle',
        )
        name_lbl.bind(size=lambda w, _: setattr(w, 'text_size', (w.width, None)))

        show_cell = _TappableRow(size_hint=(None, 1), width=58)
        show_cell.bind(on_release=lambda inst, g=gid: self._toggle_show(g))
        show_check = Label(
            text="✓" if visible else "",
            font_name=SYMBOL_FONT or 'Roboto',
            font_size="18sp", bold=True, color=C.BTN_ON,
            halign='center', valign='middle',
        )
        show_cell.add_widget(show_check)

        alloff_cell = _TappableRow(size_hint=(None, 1), width=58)
        alloff_cell.bind(on_release=lambda inst, g=gid: self._toggle_alloff(g))
        alloff_check = Label(
            text="✓" if included else "",
            font_name=SYMBOL_FONT or 'Roboto',
            font_size="18sp", bold=True, color=C.BTN_ON,
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
        bg.rgba         = C.CARD_ON if visible else C.CARD_OFF
        show_check.text = "✓" if visible else ""
        name_lbl.color  = C.TEXT if visible else C.SUBTEXT

    def _toggle_alloff(self, gid):
        self._included[gid]     = not self._included[gid]
        self._rows[gid][3].text = "✓" if self._included[gid] else ""

    def _on_bri_change(self, _, value):
        self._bri_pct.text = f"{round(value / 255 * 100)}%"
        set_brightness(int(value))

    def _toggle_weather(self):
        self._show_weather  = not self._show_weather
        self._wx_bg.rgba    = C.CARD_ON if self._show_weather else C.CARD_OFF
        self._wx_check.text = "✓" if self._show_weather else ""
        self._wx_name.color = C.TEXT if self._show_weather else C.SUBTEXT

    def _toggle_theme(self):
        self._dark_mode = not self._dark_mode
        if self._on_theme_toggle:
            self._on_theme_toggle()   # mutates C first
        self._refresh_popup_colors()

    def _refresh_popup_colors(self):
        """Re-apply current C values to all settings popup elements."""
        self._card_bg.rgba     = C.BG
        self._theme_bg.rgba    = C.CARD_ON if self._dark_mode else C.CARD_OFF
        self._theme_check.text = "✓" if self._dark_mode else ""
        self._theme_name.color = C.TEXT if self._dark_mode else C.SUBTEXT
        self._wx_bg.rgba       = C.CARD_ON if self._show_weather else C.CARD_OFF
        self._wx_name.color    = C.TEXT if self._show_weather else C.SUBTEXT
        self._log_bg.rgba      = C.CARD_ON if self._logging_enabled else C.CARD_OFF
        self._log_name.color   = C.TEXT if self._logging_enabled else C.SUBTEXT
        self._sync_bg.rgba     = C.CARD_ON if self._show_sync_errors else C.CARD_OFF
        self._sync_name.color  = C.TEXT if self._show_sync_errors else C.SUBTEXT
        for gid, (bg, show_check, name_lbl, alloff_check) in self._rows.items():
            visible = self._visible[gid]
            bg.rgba        = C.CARD_ON if visible else C.CARD_OFF
            name_lbl.color = C.TEXT if visible else C.SUBTEXT

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
        self._logging_enabled = not self._logging_enabled
        self._log_bg.rgba     = C.CARD_ON if self._logging_enabled else C.CARD_OFF
        self._log_check.text  = "✓" if self._logging_enabled else ""
        self._log_name.color  = C.TEXT if self._logging_enabled else C.SUBTEXT

    def _toggle_sync_errors(self):
        self._show_sync_errors = not self._show_sync_errors
        self._sync_bg.rgba     = C.CARD_ON if self._show_sync_errors else C.CARD_OFF
        self._sync_check.text  = "✓" if self._show_sync_errors else ""
        self._sync_name.color  = C.TEXT if self._show_sync_errors else C.SUBTEXT

    def _save_and_close(self, *_):
        hidden = {gid for gid, vis in self._visible.items() if not vis}
        exempt = {gid for gid, inc in self._included.items() if not inc}
        self._on_save(hidden, int(self._bri_slider.value), self._show_weather,
                      self._logging_enabled, self._show_sync_errors, exempt)
        self.dismiss()


# ── WeatherModal ──────────────────────────────────────────────────────────────

class WeatherModal(ModalView):
    """Full weather detail card — always dark navy regardless of app theme."""

    _BG     = (0.07, 0.10, 0.20, 1)
    _CARD   = (0.10, 0.14, 0.26, 1)
    _TEMP   = (0.95, 0.75, 0.25, 1)
    _TEXT   = (0.92, 0.94, 1.00, 1)
    _SUB    = (0.52, 0.60, 0.82, 1)
    _DAY_BG = (0.13, 0.18, 0.32, 1)

    def __init__(self, data: dict, city: str, lat=None, lon=None, **kwargs):
        super().__init__(
            background_color=(0, 0, 0, 0.70),
            size_hint=(0.92, 0.88),
            pos_hint={'center_x': 0.5, 'top': 1.0},
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

        # Header: city + close
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

        # Current temp (big)
        card.add_widget(Label(
            text=f"{data['temp']}°F",
            font_size="68sp", bold=True,
            color=self._TEMP,
            size_hint_y=None, height=90,
        ))

        # Condition
        card.add_widget(Label(
            text=data['condition'],
            font_size="20sp",
            color=self._TEXT,
            size_hint_y=None, height=30,
        ))

        # Wind
        card.add_widget(Label(
            text=f"Wind  {data['wind_mph']} mph",
            font_size="14sp",
            color=self._SUB,
            size_hint_y=None, height=22,
        ))

        # Spacer
        card.add_widget(BoxLayout(size_hint_y=None, height=6))

        # 5-day forecast row — index 0 = Today, 1-4 = next four days
        forecast = GridLayout(cols=5, size_hint_y=None, height=130, spacing=6)
        for idx, day in enumerate(data['daily'][0:5]):
            col = _DayCol(orientation='vertical', spacing=2, padding=[0, 6, 0, 6])
            with col.canvas.before:
                Color(*self._DAY_BG)
                d_rect = RoundedRectangle(radius=[8], pos=col.pos, size=col.size)
            col.bind(
                pos=lambda w, _, r=d_rect: setattr(r, 'pos', w.pos),
                size=lambda w, _, r=d_rect: setattr(r, 'size', w.size),
            )
            if self._lat and self._lon:
                col.bind(on_release=lambda inst, d=day, i=idx: self._open_day_detail(d, i == 0))
            day_label = "Today" if idx == 0 else day['day']
            col.add_widget(Label(text=day_label, font_size="11sp", bold=True, color=self._SUB,
                                 size_hint_y=None, height=18))
            icon_path = get_icon_path(day.get('wcode', -1))
            if icon_path:
                col.add_widget(Image(source=icon_path, size_hint_y=None, height=32,
                                     allow_stretch=True, keep_ratio=True))
            else:
                col.add_widget(BoxLayout(size_hint_y=None, height=32))
            cond_text = day['cond_short']
            if day.get('precip_pct', 0) > 0:
                cond_text += f"  {day['precip_pct']}%"
            col.add_widget(Label(text=cond_text,         font_size="10sp", color=self._TEXT,
                                 size_hint_y=None, height=16))
            col.add_widget(Label(text=f"{day['high']}°", font_size="15sp", bold=True, color=self._TEMP,
                                 size_hint_y=None, height=22))
            col.add_widget(Label(text=f"{day['low']}°",  font_size="12sp", color=self._SUB,
                                 size_hint_y=None, height=18))
            forecast.add_widget(col)
        card.add_widget(forecast)

        self.add_widget(card)

    def _open_day_detail(self, day: dict, is_today: bool = False):
        DayDetailModal(
            day_name="Today" if is_today else day['day'],
            date_str=day['date'],
            lat=self._lat,
            lon=self._lon,
            wmo_code=day.get('wcode', -1),
            is_today=is_today,
        ).open()


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

    def __init__(self, day_name: str, date_str: str, lat: float, lon: float,
                 wmo_code: int = -1, is_today: bool = False, **kwargs):
        super().__init__(
            background_color=(0, 0, 0, 0.80),
            size_hint=(0.92, 0.93),
            pos_hint={'center_x': 0.5, 'top': 0.99},
            **kwargs,
        )
        self._lat      = lat
        self._lon      = lon
        self._date_str = date_str
        self._is_today = is_today

        card = BoxLayout(orientation='vertical', padding=[20, 16, 20, 16], spacing=10)
        with card.canvas.before:
            Color(*self._CARD)
            c_rect = RoundedRectangle(radius=[20], pos=card.pos, size=card.size)
        card.bind(
            pos=lambda *_: setattr(c_rect, 'pos', card.pos),
            size=lambda *_: setattr(c_rect, 'size', card.size),
        )

        # Header row: icon + date label + close button
        hdr = BoxLayout(orientation='horizontal', size_hint_y=None, height=48, spacing=8)
        icon_path = get_icon_path(wmo_code)
        if icon_path:
            hdr.add_widget(Image(source=icon_path, size_hint=(None, 1), width=44,
                                 allow_stretch=True, keep_ratio=True))
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

        # Content: loading → hourly rows
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

        current_hour = datetime.now().hour if self._is_today else -1
        for i, h in enumerate([x for x in hours if x['hour'] >= current_hour]):
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


# ── HeaderBar ─────────────────────────────────────────────────────────────────

class HeaderBar(BoxLayout):
    """Top bar: ☰ settings | weather/status label | ↕ sort-toggle (always visible)."""

    def __init__(self, on_edit_toggle, on_theme_toggle, on_settings_open,
                 on_weather_tap=None, on_all_off=None, **kwargs):
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height=50,
            padding=[8, 4, 8, 4],
            spacing=6,
            **kwargs,
        )
        with self.canvas.before:
            self._hdr_color = Color(*C.HEADER_BG)
            self._rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)

        self._weather_text  = ""    # last known weather string
        self._status_revert = None  # pending Clock event to restore weather after status

        self.alloff_btn = None
        self.theme_btn  = None   # theme toggle moved into settings popup

        # ☰ hamburger — far left
        self.settings_btn = Button(
            text="☰",
            font_name=SYMBOL_FONT or 'Roboto',
            font_size="22sp",
            size_hint=(None, 0.85),
            width=46,
            background_normal="",
            background_down="",
            background_color=(0, 0, 0, 0),
            color=C.TEXT,
        )
        self.settings_btn.bind(on_release=lambda _: on_settings_open())

        # Weather label — just right of hamburger, fills remaining space
        self.weather_lbl = _WeatherBtn(
            text="",
            font_size="19sp",
            bold=True,
            color=C.TEXT,
            halign="left",
            valign="middle",
            size_hint=(1, 0.85),
        )
        self.weather_lbl.bind(size=lambda w, _: setattr(w, "text_size", (w.width, None)))
        if on_weather_tap:
            self.weather_lbl.bind(on_release=lambda _: on_weather_tap())

        # Sort toggle button — always visible; ↕ enters sort mode, ✔ exits it
        self.edit_btn = Button(
            text="↕",
            font_name=SYMBOL_FONT or 'Roboto',
            font_size="20sp",
            size_hint=(None, 0.85),
            width=46,
            opacity=1,
            disabled=False,
            background_normal="",
            background_down="",
            background_color=(0, 0, 0, 0),
            color=C.BTN_EDIT,
        )
        self.edit_btn.bind(on_release=lambda _: on_edit_toggle())

        self.add_widget(self.settings_btn)
        self.add_widget(self.weather_lbl)
        self.add_widget(self.edit_btn)

    def set_weather(self, text: str):
        self._weather_text = text
        if self._status_revert is None:
            self.weather_lbl.text  = text
            self.weather_lbl.color = C.TEXT

    def set_status(self, text: str, color=None):
        if self._status_revert:
            self._status_revert.cancel()
        self.weather_lbl.text  = text
        self.weather_lbl.color = color or C.SUBTEXT
        self._status_revert = Clock.schedule_once(self._revert_to_weather, 3)

    def _revert_to_weather(self, _dt):
        self._status_revert    = None
        self.weather_lbl.text  = self._weather_text
        self.weather_lbl.color = C.TEXT

    def _upd(self, *_):
        self._rect.pos  = self.pos
        self._rect.size = self.size

    def set_edit_active(self, active: bool):
        self.edit_btn.text = "✔" if active else "↕"

    def set_theme_label(self, dark_mode: bool):
        pass  # theme toggle moved into settings popup

    def refresh_colors(self):
        self._hdr_color.rgba    = C.HEADER_BG
        self.weather_lbl.color  = C.TEXT
        self.settings_btn.color = C.TEXT
