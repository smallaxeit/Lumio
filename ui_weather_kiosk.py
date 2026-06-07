"""ui_weather_kiosk.py — full-screen ambient weather kiosk.

Procedurally-drawn alternative to the WeatherModal popup: a sky gradient that
shifts with time of day and cloud cover, a sun/moon arc tracking real elapsed
daylight, drifting clouds, and rain/snow accents — layered behind glass-style
data cards. Always rendered in WeatherModal's dark-navy palette, day or night,
so the look stays consistent regardless of the app theme.
"""

import math
import random
import threading
from datetime import datetime, timedelta

from kivy.animation import Animation
from kivy.clock import Clock, mainthread
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.widget import Widget

from theme import SYMBOL_FONT, _DayCol
from lumio_weather import get_icon_path
from lumio_log import log_event, _mark_huecontrol
from ui_panels import DayDetailModal

# ── Palette (always dark navy, matches WeatherModal) ───────────────────────────

_TEXT   = (0.92, 0.94, 1.00, 1)
_SUB    = (0.52, 0.60, 0.82, 1)
# _SUB reads fine on the dark glass cards but nearly disappears directly over
# the bright daytime sky (similar blue-gray hue/luminosity) — translucent white
# stays legible at any time of day for header text like "Updated H:MM AM/PM".
_SUB_SKY = (0.92, 0.94, 1.00, 0.55)
_TEMP   = (0.95, 0.75, 0.25, 1)
# Card fills are nearly opaque on purpose — at lower alpha the sun/moon glow
# bleeds through from behind and washes out the text as a smudge mid-card.
_CARD   = (0.12, 0.16, 0.29, 0.88)

# Sky gradient stops — (top_rgb, bottom_rgb), blended by time of day + desaturated
# toward gray by cloud cover. Night wraps both ends of the day.
_SKY_NIGHT = ((0.04, 0.05, 0.12), (0.10, 0.11, 0.22))
_SKY_DAWN  = ((0.18, 0.20, 0.40), (0.95, 0.62, 0.45))
_SKY_DAY   = ((0.27, 0.55, 0.92), (0.68, 0.84, 0.97))
_SKY_DUSK  = ((0.20, 0.18, 0.40), (0.92, 0.50, 0.38))
_SKY_OVERCAST_MIX = (0.55, 0.58, 0.62)

_TWILIGHT_MIN = 45   # minutes of dawn/dusk blending either side of sunrise/sunset
_BAND_COUNT   = 10   # gradient bands

_SNOW_CODES = {71, 73, 75, 77, 85, 86}
_PRECIP_INTENSITY = {   # current weathercode -> 0..1 visual density
    51: 0.30, 53: 0.45, 55: 0.60,
    61: 0.35, 63: 0.60, 65: 0.85,
    71: 0.30, 73: 0.50, 75: 0.75, 77: 0.40,
    80: 0.40, 81: 0.60, 82: 0.85,
    85: 0.40, 86: 0.70,
    95: 0.70, 96: 0.85, 99: 1.00,
}

_UV_BANDS = ((3, "Low"), (6, "Moderate"), (8, "High"), (11, "Very High"))


def _uv_category(uv: float) -> str:
    for ceiling, name in _UV_BANDS:
        if uv < ceiling:
            return name
    return "Extreme"


# ── Color helpers ──────────────────────────────────────────────────────────────

def _lerp(a, b, t):
    return a + (b - a) * t

def _lerp_rgb(c1, c2, t):
    return tuple(_lerp(a, b, t) for a, b in zip(c1, c2))

def _mix_toward(rgb, target, amount):
    return tuple(_lerp(c, t, amount) for c, t in zip(rgb, target))


def _sky_stops(now: datetime, sunrise: datetime, sunset: datetime, cloud_pct: int):
    """Return (top_rgb, bottom_rgb) blended across night->dawn->day->dusk->night
    for the given moment, then desaturated toward gray by cloud cover."""
    tw = timedelta(minutes=_TWILIGHT_MIN)

    if sunrise - tw <= now < sunrise:
        t = (now - (sunrise - tw)) / tw
        top = _lerp_rgb(_SKY_NIGHT[0], _SKY_DAWN[0], t)
        bot = _lerp_rgb(_SKY_NIGHT[1], _SKY_DAWN[1], t)
    elif sunrise <= now < sunrise + tw:
        t = (now - sunrise) / tw
        top = _lerp_rgb(_SKY_DAWN[0], _SKY_DAY[0], t)
        bot = _lerp_rgb(_SKY_DAWN[1], _SKY_DAY[1], t)
    elif sunrise + tw <= now < sunset - tw:
        top, bot = _SKY_DAY
    elif sunset - tw <= now < sunset:
        t = (now - (sunset - tw)) / tw
        top = _lerp_rgb(_SKY_DAY[0], _SKY_DUSK[0], t)
        bot = _lerp_rgb(_SKY_DAY[1], _SKY_DUSK[1], t)
    elif sunset <= now < sunset + tw:
        t = (now - sunset) / tw
        top = _lerp_rgb(_SKY_DUSK[0], _SKY_NIGHT[0], t)
        bot = _lerp_rgb(_SKY_DUSK[1], _SKY_NIGHT[1], t)
    else:
        top, bot = _SKY_NIGHT

    amount = min(max(cloud_pct, 0), 100) / 100 * 0.45
    return _mix_toward(top, _SKY_OVERCAST_MIX, amount), _mix_toward(bot, _SKY_OVERCAST_MIX, amount)


def _is_daytime(now: datetime, sunrise: datetime, sunset: datetime) -> bool:
    return sunrise <= now < sunset


def _arc_fraction(now: datetime, sunrise: datetime, sunset: datetime, is_day: bool) -> float:
    """Fraction (0..1) of the way through the current day/night arc, based on
    real elapsed time. Night arc spans sunset -> next sunrise (approximated by
    +/- 24h on today's sunrise/sunset, which drift by only minutes day to day)."""
    if is_day:
        start, end = sunrise, sunset
    elif now < sunrise:
        start, end = sunset - timedelta(days=1), sunrise
    else:
        start, end = sunset, sunrise + timedelta(days=1)
    span = (end - start).total_seconds()
    if span <= 0:
        return 0.5
    return max(0.0, min(1.0, (now - start).total_seconds() / span))


# ── Sky gradient ───────────────────────────────────────────────────────────────

class _SkyBackground(Widget):
    """Full-bleed vertical gradient, drawn as stacked horizontal color bands."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._bands = []
        with self.canvas:
            for _ in range(_BAND_COUNT):
                color = Color(*_SKY_NIGHT[0], 1)
                rect  = Rectangle(pos=(0, 0), size=(1, 1))
                self._bands.append((color, rect))
        self.bind(pos=self._reflow, size=self._reflow)

    def _reflow(self, *_a):
        n = len(self._bands)
        if self.width <= 0 or self.height <= 0:
            return
        band_h = self.height / n
        for i, (_color, rect) in enumerate(self._bands):
            rect.pos  = (self.x, self.top - (i + 1) * band_h)
            rect.size = (self.width, band_h + 1)   # +1 to hide seams

    def set_stops(self, top_rgb, bottom_rgb):
        n = len(self._bands)
        for i, (color, _rect) in enumerate(self._bands):
            t = i / max(n - 1, 1)
            r, g, b = _lerp_rgb(top_rgb, bottom_rgb, t)
            color.rgba = (r, g, b, 1)


# ── Sun / moon arc ─────────────────────────────────────────────────────────────

class _SunMoonArc(Widget):
    """A glowing circle that travels a sine arc between sunrise and sunset (or
    the mirrored night arc), positioned by real elapsed-time fraction."""

    _SUN_GLOW  = (1.00, 0.80, 0.45)
    _MOON_GLOW = (0.75, 0.82, 0.95)
    _PATH_RGBA = (1, 1, 1, 0.12)
    _RINGS     = ((70, 0.16), (46, 0.28), (26, 1.0))   # (diameter, alpha)

    _MARGIN     = 70
    _ARC_HEIGHT = 130
    _HORIZON    = 60

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._frac = 0.5
        self._rings = []
        with self.canvas:
            Color(*self._PATH_RGBA)
            self._path = Line(points=[], width=1.4)
            for diameter, alpha in self._RINGS:
                color  = Color(*self._SUN_GLOW, alpha)
                circle = Ellipse(size=(diameter, diameter))
                self._rings.append((color, circle, diameter, alpha))
        self.bind(pos=self._redraw, size=self._redraw)

    def set_position(self, frac: float, is_day: bool):
        self._frac = max(0.0, min(1.0, frac))
        glow = self._SUN_GLOW if is_day else self._MOON_GLOW
        for color, _circle, _diam, alpha in self._rings:
            color.rgba = (*glow, alpha)
        self._redraw()

    def _point(self, f):
        x = self.x + self._MARGIN + f * (self.width - 2 * self._MARGIN)
        y = self.y + self._HORIZON + math.sin(math.pi * f) * self._ARC_HEIGHT
        return x, y

    def _redraw(self, *_a):
        if self.width <= 0 or self.height <= 0:
            return
        pts = []
        for i in range(33):
            x, y = self._point(i / 32)
            pts += [x, y]
        self._path.points = pts

        x, y = self._point(self._frac)
        for _color, circle, diameter, _alpha in self._rings:
            circle.pos  = (x - diameter / 2, y - diameter / 2)
            circle.size = (diameter, diameter)


# ── Drifting clouds ────────────────────────────────────────────────────────────

class _Cloud(Widget):
    """A soft cloud made of overlapping translucent ellipses."""

    _PUFFS = (   # (dx, dy, w, h) in local units, scaled by `scale`
        (10, 14, 90, 40),
        (55, 24, 75, 34),
        (0,  22, 64, 30),
        (75,  8, 56, 28),
    )

    def __init__(self, scale=1.0, **kwargs):
        super().__init__(size_hint=(None, None), **kwargs)
        self._scale = scale
        self.size = (150 * scale, 70 * scale)
        with self.canvas:
            self._color = Color(1, 1, 1, 0)
            self._ellipses = [Ellipse(size=(w * scale, h * scale)) for _, _, w, h in self._PUFFS]
        self.bind(pos=self._reflow, size=self._reflow)

    def _reflow(self, *_a):
        for ellipse, (dx, dy, w, h) in zip(self._ellipses, self._PUFFS):
            ellipse.pos  = (self.x + dx * self._scale, self.y + dy * self._scale)
            ellipse.size = (w * self._scale, h * self._scale)

    def set_alpha(self, alpha):
        self._color.a = alpha


class _CloudLayer(Widget):
    """2-3 clouds drifting slowly side to side; opacity follows cloud cover."""

    # (rel_x, rel_y, scale, sway_px, half-cycle seconds)
    _LAYOUT = (
        (0.10, 0.74, 1.00, 70, 70),
        (0.56, 0.60, 0.72, 55, 95),
        (0.32, 0.86, 0.55, 45, 120),
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._clouds = []
        for rel_x, rel_y, scale, sway, duration in self._LAYOUT:
            cloud = _Cloud(scale=scale)
            self.add_widget(cloud)
            self._clouds.append({
                'widget': cloud, 'rel_x': rel_x, 'rel_y': rel_y,
                'sway': sway, 'duration': duration, 'animating': False,
            })
        self.bind(pos=self._reflow, size=self._reflow)

    def _reflow(self, *_a):
        if self.width <= 0 or self.height <= 0:
            return
        for c in self._clouds:
            if not c['animating']:
                c['widget'].pos = (self.x + c['rel_x'] * self.width,
                                   self.y + c['rel_y'] * self.height)
                self._start_drift(c)

    def _start_drift(self, c):
        c['animating'] = True
        widget, sway, duration = c['widget'], c['sway'], c['duration']
        base_x = widget.x

        def _go_back(*_a):
            back = Animation(x=base_x, duration=duration, t='in_out_sine')
            back.bind(on_complete=_go_forward)
            back.start(widget)

        def _go_forward(*_a):
            fwd = Animation(x=base_x + sway, duration=duration, t='in_out_sine')
            fwd.bind(on_complete=_go_back)
            fwd.start(widget)

        _go_forward()

    def set_cloud_pct(self, pct: int):
        alpha = 0.10 + min(max(pct, 0), 100) / 100 * 0.45
        for c in self._clouds:
            c['widget'].set_alpha(alpha)


# ── Precipitation (rain / snow) ────────────────────────────────────────────────

class _PrecipLayer(Widget):
    """Falling rain lines / snow dots; idle (no canvas, no clock) when dry."""

    _RAIN_RGB   = (0.65, 0.78, 1.00)
    _SNOW_RGB   = (0.92, 0.95, 1.00)
    _DROP_COUNT = 46

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._color = None
        self._drops = []
        self._kind  = None
        self._ev    = None
        self._wcode = -1
        self._built_size = (0, 0)
        self.bind(size=self._on_resize)

    def _on_resize(self, *_a):
        # Rebuild on the first real layout pass — `set_condition` may have run
        # while the layer still had its placeholder (100x100) size, which would
        # otherwise leave drops clustered in a corner of the real canvas.
        if self._kind is not None:
            self.set_condition(self._wcode)

    def set_condition(self, wcode: int):
        self._wcode = wcode
        intensity = _PRECIP_INTENSITY.get(wcode, 0)
        if intensity <= 0 or self.width <= 0 or self.height <= 0:
            self._stop()
            return
        kind = 'snow' if wcode in _SNOW_CODES else 'rain'
        if kind != self._kind or (self.width, self.height) != self._built_size:
            self._build(kind)
            self._built_size = (self.width, self.height)
        base_alpha = 0.55 if kind == 'rain' else 0.70
        self._color.a = base_alpha * max(intensity, 0.25)
        if self._ev is None:
            self._ev = Clock.schedule_interval(self._step, 1 / 30)

    def _build(self, kind):
        self._stop()
        self._kind = kind
        rgb = self._SNOW_RGB if kind == 'snow' else self._RAIN_RGB
        with self.canvas:
            self._color = Color(*rgb, 0)
            for _ in range(self._DROP_COUNT):
                x = self.x + random.uniform(0, self.width)
                y = self.y + random.uniform(0, self.height)
                if kind == 'rain':
                    instr = Line(points=[x, y, x - 6, y - 16], width=1.4)
                    speed = random.uniform(160, 280)
                else:
                    r = random.uniform(1.5, 3.5)
                    instr = Ellipse(pos=(x - r, y - r), size=(r * 2, r * 2))
                    speed = random.uniform(35, 75)
                self._drops.append({'instr': instr, 'x': x, 'y': y, 'speed': speed, 'kind': kind})

    def _step(self, dt):
        if self.height <= 0:
            return
        for d in self._drops:
            d['y'] -= d['speed'] * dt
            if d['y'] < self.y - 20:
                d['y'] = self.top + random.uniform(0, 50)
                d['x'] = random.uniform(self.x, self.right)
            instr = d['instr']
            if d['kind'] == 'rain':
                instr.points = [d['x'], d['y'], d['x'] - 6, d['y'] - 16]
            else:
                r = instr.size[0] / 2
                instr.pos = (d['x'] - r, d['y'] - r)

    def _stop(self):
        if self._ev is not None:
            self._ev.cancel()
            self._ev = None
        self.canvas.clear()
        self._drops = []
        self._color = None
        self._kind  = None
        self._built_size = (0, 0)


# ── Glass card ─────────────────────────────────────────────────────────────────

class _GlassCard(BoxLayout):
    """Nearly-opaque rounded panel over the ambient sky — see _CARD comment:
    too translucent and the sun/moon glow bleeds through as a smudge."""

    _FILL   = (0.13, 0.17, 0.30, 0.88)
    _BORDER = (0.62, 0.72, 0.92, 0.28)

    def __init__(self, **kwargs):
        kwargs.setdefault('padding', [16, 10, 16, 10])
        kwargs.setdefault('spacing', 6)
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*self._FILL)
            self._fill = RoundedRectangle(radius=[16], pos=self.pos, size=self.size)
            Color(*self._BORDER)
            self._border = Line(rounded_rectangle=(*self.pos, *self.size, 16), width=1.2)
        self.bind(pos=self._redraw, size=self._redraw)

    def _redraw(self, *_a):
        self._fill.pos  = self.pos
        self._fill.size = self.size
        self._border.rounded_rectangle = (self.x, self.y, self.width, self.height, 16)


# ── Favorite-room quick toggles ────────────────────────────────────────────────

_FAV_ON       = (0.95, 0.75, 0.25, 1)   # amber — matches _TEMP, reads as "on"
_FAV_OFF      = (0.20, 0.27, 0.42, 1)   # muted navy — reads as "off"
_FAV_ON_TEXT  = (0.12, 0.12, 0.16, 1)


class _FavToggle(Button):
    """Compact on/off toggle for one favorite room. Mirrors RoomCard's toggle
    flow — optimistic UI, threaded API call, event log, rollback on error —
    so a kiosk tap behaves identically to a grid-card tap."""

    def __init__(self, gid, name, is_on, api, **kwargs):
        super().__init__(
            font_size="14sp", bold=True,
            size_hint=(None, 1), width=92,
            background_normal="", background_down="",
            **kwargs,
        )
        self.gid      = gid
        self._name    = name
        self._api     = api
        self._is_on   = is_on
        self._pending = False
        self._refresh()
        self.bind(on_release=self._handle_toggle)

    def set_state(self, is_on):
        if not self._pending:
            self._is_on = is_on
            self._refresh()

    def _refresh(self):
        self.text             = self._name
        self.background_color = _FAV_ON if self._is_on else _FAV_OFF
        self.color            = _FAV_ON_TEXT if self._is_on else _TEXT

    def _handle_toggle(self, *_a):
        if self._pending:
            return
        self._pending = True
        new_state     = not self._is_on
        self._is_on   = new_state
        self._refresh()
        threading.Thread(target=self._send_toggle, args=(new_state,), daemon=True).start()

    def _send_toggle(self, new_state):
        _mark_huecontrol(self.gid)
        try:
            self._api.set_group_on(self.gid, new_state)
            log_event(self._name, self.gid, "on" if new_state else "off", None, "lumio")
        except Exception as exc:
            print(f"[kiosk-favorite] toggle error for {self._name}: {exc}")
            Clock.schedule_once(lambda _dt: self._rollback(not new_state), 0)
        finally:
            self._pending = False

    @mainthread
    def _rollback(self, is_on):
        self._is_on = is_on
        self._refresh()


# ── Weather kiosk ──────────────────────────────────────────────────────────────

class WeatherKiosk(FloatLayout):
    """Full-screen ambient weather view, swapped in over the room grid."""

    _STATS = (
        ('uv',         'UV Index'),
        ('gusts',      'Gusts'),
        ('pressure',   'Pressure'),
        ('visibility', 'Visibility'),
        ('clouds',     'Cloud Cover'),
        ('sun',        'Sunrise · Sunset'),
    )

    def __init__(self, on_back=None, **kwargs):
        super().__init__(**kwargs)
        self._on_back = on_back
        self._lat = self._lon = None
        self._data = None
        self._last_update = None
        self._tick_ev = None

        # Ambient layers, back to front
        self._sky    = _SkyBackground(size_hint=(1, 1))
        self._clouds = _CloudLayer(size_hint=(1, 1))
        self._arc    = _SunMoonArc(size_hint=(1, 1))
        self._precip = _PrecipLayer(size_hint=(1, 1))
        for layer in (self._sky, self._clouds, self._arc, self._precip):
            self.add_widget(layer)

        content = BoxLayout(orientation='vertical', size_hint=(1, 1),
                            padding=[24, 14, 24, 14], spacing=10)
        self._build_header(content)
        self._build_current_card(content)
        self._build_stats_card(content)

        self._forecast = GridLayout(cols=5, size_hint_y=None, height=118, spacing=6)
        content.add_widget(self._forecast)

        self.add_widget(content)

    # -- construction helpers --------------------------------------------------

    def _build_header(self, content):
        hdr = BoxLayout(orientation='horizontal', size_hint_y=None, height=52, spacing=10)
        back_btn = Button(
            text="←", font_name=SYMBOL_FONT or 'Roboto', font_size="28sp",
            size_hint=(None, 1), width=64,
            background_normal="", background_down="",
            background_color=(0, 0, 0, 0), color=_TEXT,
        )
        back_btn.bind(on_release=lambda _w: self._on_back and self._on_back())

        # Stacked in a column shaped like clock_col (28 + 18) so its text sits
        # on the same baseline as the clock above "Updated" instead of centering
        # in the full header height while the clock bottom-anchors in its row
        # ("align the city and time text, horizontally, that looks horrible").
        city_col = BoxLayout(orientation='vertical')
        self._city_lbl = Label(text="", font_size="22sp", bold=True, color=_TEXT,
                               size_hint_y=None, height=28,
                               halign="left", valign="bottom")
        self._city_lbl.bind(size=lambda w, _v: setattr(w, 'text_size', (w.width, None)))
        city_col.add_widget(self._city_lbl)
        city_col.add_widget(Widget(size_hint_y=None, height=18))

        # Quick on/off toggles for the user's top-configured rooms — populated
        # by set_favorites(); empty (width 0) until then so it takes no space.
        self._fav_box = BoxLayout(orientation='horizontal', size_hint=(None, 1),
                                  width=0, spacing=8)
        self._fav_buttons = {}

        # Current time (large) + "Updated H:MM AM/PM" (small) stacked beneath it
        clock_col = BoxLayout(orientation='vertical', size_hint=(None, 1), width=130)
        self._clock_lbl = Label(text="", font_size="20sp", bold=True, color=_TEXT,
                                size_hint_y=None, height=28,
                                halign="right", valign="bottom")
        self._updated_lbl = Label(text="", font_size="11sp", color=_SUB_SKY,
                                  size_hint_y=None, height=18,
                                  halign="right", valign="top")
        for lbl in (self._clock_lbl, self._updated_lbl):
            lbl.bind(size=lambda w, _v: setattr(w, 'text_size', (w.width, None)))
            clock_col.add_widget(lbl)

        hdr.add_widget(back_btn)
        hdr.add_widget(city_col)
        hdr.add_widget(self._fav_box)
        hdr.add_widget(clock_col)
        content.add_widget(hdr)

    def _build_current_card(self, content):
        card = _GlassCard(orientation='horizontal', size_hint_y=None, height=110, spacing=20)
        # Box wider than the icon's rendered size (height-constrained, ~90px) —
        # Image centers its texture within the bbox, so the extra width reads as
        # the icon sitting centered between the card's left edge and the temp,
        # rather than flush against the edge ("visual... centered between temp
        # and left alignment... and bigger would fill the space better").
        self._icon_img = Image(size_hint=(None, 1), width=110, allow_stretch=True, keep_ratio=True)
        card.add_widget(self._icon_img)

        # Centered (not left-anchored) — this column spans the open space between
        # the icon and the mini-stats, so left-aligned text hugged the icon and
        # left a lopsided gap on the right.
        text_col = BoxLayout(orientation='vertical', spacing=2)
        self._temp_lbl = Label(text="", font_size="40sp", bold=True, color=_TEMP,
                               size_hint_y=None, height=48, halign="center", valign="middle")
        self._cond_lbl = Label(text="", font_size="16sp", color=_TEXT,
                               size_hint_y=None, height=24, halign="center", valign="middle")
        self._feels_lbl = Label(text="", font_size="13sp", color=_SUB,
                                size_hint_y=None, height=20, halign="center", valign="middle")
        for lbl in (self._temp_lbl, self._cond_lbl, self._feels_lbl):
            lbl.bind(size=lambda w, _v: setattr(w, 'text_size', (w.width, None)))
            text_col.add_widget(lbl)
        card.add_widget(text_col)

        # Secondary readouts spread across the card's right half — smaller than
        # the headline temp, so the card uses the full kiosk width instead of
        # clustering everything against the icon on the left.
        self._mini_humidity = self._add_mini_stat(card, "Humidity")
        self._mini_wind     = self._add_mini_stat(card, "Wind")
        content.add_widget(card)

    def _add_mini_stat(self, card, caption):
        col = BoxLayout(orientation='vertical', size_hint_x=None, width=110, spacing=2)
        col.add_widget(Label(text=caption, font_size="12sp", color=_SUB,
                             size_hint_y=None, height=18, halign='center', valign='middle'))
        value = Label(text="—", font_size="22sp", bold=True, color=_TEXT,
                      size_hint_y=None, height=30, halign='center', valign='middle')
        col.add_widget(value)
        card.add_widget(col)
        return value

    def _build_stats_card(self, content):
        card = _GlassCard(size_hint_y=None, height=96, padding=[14, 8, 14, 8])
        grid = GridLayout(cols=3, spacing=4)
        card.add_widget(grid)
        self._stat_labels = {}
        for key, caption in self._STATS:
            col = BoxLayout(orientation='vertical')
            col.add_widget(Label(text=caption, font_size="10sp", color=_SUB,
                                 size_hint_y=None, height=14))
            # 'sun' renders a → arrow glyph — needs SYMBOL_FONT or it shows as tofu
            font_name = (SYMBOL_FONT or 'Roboto') if key == 'sun' else 'Roboto'
            value = Label(text="—", font_size="15sp", bold=True, color=_TEXT,
                          font_name=font_name, size_hint_y=None, height=22)
            col.add_widget(value)
            grid.add_widget(col)
            self._stat_labels[key] = value
        content.add_widget(card)

    # -- public interface -------------------------------------------------------

    def update(self, data: dict, city: str, lat=None, lon=None):
        if not data:
            return
        self._data = data
        self._last_update = datetime.now()
        self._lat, self._lon = lat, lon

        self._city_lbl.text  = city or "Weather"
        self._icon_img.source = get_icon_path(data.get('wcode', -1)) or ""
        self._temp_lbl.text  = f"{data['temp']}°F"
        self._cond_lbl.text  = data.get('condition', '')
        self._feels_lbl.text = f"Feels like {data.get('feels_like', data['temp'])}°"
        self._mini_humidity.text = f"{data.get('humidity', '—')}%"
        self._mini_wind.text     = f"{data.get('wind_mph', '—')} mph"

        uv = data.get('uv_index', 0)
        s = self._stat_labels
        s['uv'].text         = f"{uv:g}  {_uv_category(uv)}"
        s['gusts'].text      = f"{data.get('wind_gusts', '—')} mph"
        s['pressure'].text   = f"{data.get('pressure_in', '—')} in"
        s['visibility'].text = f"{data.get('visibility_mi', '—')} mi"
        s['clouds'].text     = f"{data.get('cloud_pct', '—')}%"
        s['sun'].text        = f"{data.get('sunrise_label', '—')}  →  {data.get('sunset_label', '—')}"

        self._rebuild_forecast(data.get('daily', [])[:5])
        self._clouds.set_cloud_pct(data.get('cloud_pct', 0))
        self._precip.set_condition(data.get('wcode', -1))
        self._start_ticking()

    def set_favorites(self, rooms, api):
        """rooms: [(group_id, name, is_on), ...] — the kiosk's quick on/off
        toggles. Rebuilds only when the set of rooms changes; otherwise just
        syncs button state so an in-flight tap isn't clobbered mid-toggle."""
        if not rooms or api is None:
            self._fav_box.clear_widgets()
            self._fav_buttons = {}
            self._fav_box.width = 0
            return
        if set(self._fav_buttons) != {gid for gid, _name, _on in rooms}:
            self._fav_box.clear_widgets()
            self._fav_buttons = {}
            self._fav_box.width = len(rooms) * 92 + (len(rooms) - 1) * self._fav_box.spacing
            for gid, name, is_on in rooms:
                btn = _FavToggle(gid, name, is_on, api)
                self._fav_box.add_widget(btn)
                self._fav_buttons[gid] = btn
        else:
            for gid, _name, is_on in rooms:
                self._fav_buttons[gid].set_state(is_on)

    # -- forecast strip ----------------------------------------------------------

    def _rebuild_forecast(self, days):
        self._forecast.clear_widgets()
        for idx, day in enumerate(days):
            col = _DayCol(orientation='vertical', spacing=2, padding=[0, 6, 0, 6])
            with col.canvas.before:
                Color(*_CARD)
                rect = RoundedRectangle(radius=[10], pos=col.pos, size=col.size)
            col.bind(
                pos=lambda w, _v, r=rect: setattr(r, 'pos', w.pos),
                size=lambda w, _v, r=rect: setattr(r, 'size', w.size),
            )
            if self._lat and self._lon:
                col.bind(on_release=lambda _inst, d=day, today=(idx == 0): self._open_day_detail(d, today))

            label = "Today" if idx == 0 else day['day']
            col.add_widget(Label(text=label, font_size="11sp", bold=True, color=_SUB,
                                 size_hint_y=None, height=18))
            icon_path = get_icon_path(day.get('wcode', -1))
            if icon_path:
                col.add_widget(Image(source=icon_path, size_hint_y=None, height=34,
                                     allow_stretch=True, keep_ratio=True))
            else:
                col.add_widget(BoxLayout(size_hint_y=None, height=34))
            cond_text = day['cond_short']
            if day.get('precip_pct', 0) > 0:
                cond_text += f"  {day['precip_pct']}%"
            col.add_widget(Label(text=cond_text, font_size="10sp", color=_TEXT,
                                 size_hint_y=None, height=16))
            col.add_widget(Label(text=f"{day['high']}°", font_size="15sp", bold=True,
                                 color=_TEMP, size_hint_y=None, height=22))
            col.add_widget(Label(text=f"{day['low']}°", font_size="12sp", color=_SUB,
                                 size_hint_y=None, height=18))
            self._forecast.add_widget(col)

    def _open_day_detail(self, day, is_today=False):
        DayDetailModal(
            day_name="Today" if is_today else day['day'],
            date_str=day['date'],
            lat=self._lat, lon=self._lon,
            wmo_code=day.get('wcode', -1),
            is_today=is_today,
        ).open()

    # -- ambient ticking ----------------------------------------------------------

    def _start_ticking(self):
        if self._tick_ev is None:
            self._tick_ev = Clock.schedule_interval(self._on_tick, 60)
        self._on_tick(0)

    def _on_tick(self, _dt):
        self._clock_lbl.text = datetime.now().strftime("%I:%M %p").lstrip("0")
        if self._last_update:
            self._updated_lbl.text = "Updated " + self._last_update.strftime("%I:%M %p").lstrip("0")
        if self._data:
            self._update_ambient()

    def _update_ambient(self):
        now = datetime.now()
        sunrise, sunset = self._sun_times()
        is_day = _is_daytime(now, sunrise, sunset)

        top, bottom = _sky_stops(now, sunrise, sunset, self._data.get('cloud_pct', 0))
        self._sky.set_stops(top, bottom)
        self._arc.set_position(_arc_fraction(now, sunrise, sunset, is_day), is_day)

    def _sun_times(self):
        try:
            return (datetime.fromisoformat(self._data['sunrise']),
                    datetime.fromisoformat(self._data['sunset']))
        except (KeyError, ValueError, TypeError):
            now = datetime.now()
            return (now.replace(hour=6, minute=30, second=0, microsecond=0),
                    now.replace(hour=20, minute=30, second=0, microsecond=0))
