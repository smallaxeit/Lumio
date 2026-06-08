"""ui_weather_kiosk.py — full-screen ambient weather kiosk.

Procedurally-drawn alternative to the WeatherModal popup: a sky gradient that
shifts with time of day and cloud cover, a sun/moon arc tracking real elapsed
daylight, drifting clouds, and rain/snow accents — layered behind glass-style
data cards. Always rendered in WeatherModal's dark-navy palette, day or night,
so the look stays consistent regardless of the app theme.
"""

import math
import random
from datetime import datetime, timedelta

from kivy.animation import Animation
from kivy.clock import Clock
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
from ui_panels import DayDetailModal

# ── Palette (always dark navy, matches WeatherModal) ───────────────────────────

_TEXT   = (0.92, 0.94, 1.00, 1)
_SUB    = (0.52, 0.60, 0.82, 1)
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
    # 60 → 100 ("shift up") — at low sun-elevation (near sunrise/sunset) the
    # glow's lowest point sat right behind the forecast strip's corner,
    # poking out from under the glass card instead of glowing softly through
    # the gap above it. Raising the floor moves that low point into the gap
    # between the forecast and stats cards. The glow rings/path keep their
    # own alpha and width untouched ("lines... sharp") — only its travel
    # range changes, not how crisply it's drawn.
    _HORIZON    = 100

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

    # Scales bumped ~35% across the board ("bigger clouds or some or
    # whatever it is too" — the drifting puffs were reading as faint smudges
    # against the sky gradient, easy to miss on a small screen).
    # (rel_x, rel_y, scale, sway_px, half-cycle seconds)
    _LAYOUT = (
        (0.10, 0.74, 1.35, 70, 70),
        (0.56, 0.60, 0.95, 55, 95),
        (0.32, 0.86, 0.78, 45, 120),
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


# ── Weather kiosk ──────────────────────────────────────────────────────────────

class WeatherKiosk(FloatLayout):
    """Full-screen ambient weather view, swapped in over the room grid."""

    # Visibility/Cloud Cover dropped per the user's edited mockup ("you have
    # elements i removed... this, only this, this is the way") — four stats
    # now fill a single row exactly, no empty grid cells.
    _STATS = (
        ('uv',         'UV Index'),
        ('gusts',      'Gusts'),
        ('pressure',   'Pressure'),
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
        self._build_current_card(content)
        self._build_stats_card(content)

        # 184 (not 136) absorbed the ~48px that used to sit as dead space
        # above the hero card once the header bar was removed ("lot of dead
        # space at the top, shift up and fill, expand bottom tiles too").
        # Trimmed back 6px here to help fund the hero card's bigger arrow —
        # 178 is this strip's exact content minimum (_DayCol's
        # minimum_height; see _rebuild_forecast), so cells size to fit with
        # zero slack but nothing left over to clip. The three card heights
        # still sum exactly to the kiosk's available content height.
        self._forecast = GridLayout(cols=5, size_hint_y=None, height=178, spacing=6)
        content.add_widget(self._forecast)

        self.add_widget(content)

    # -- construction helpers --------------------------------------------------

    def _build_current_card(self, content):
        # Single hero card — folds in what used to be a separate header bar
        # (back arrow top-left, clock/"Updated" top-right; no city label, the
        # kiosk only ever shows local conditions) above the current-conditions
        # row, per the user's mockup ("no need for header bar, it is gone").
        card = _GlassCard(orientation='vertical', size_hint_y=None, height=178, spacing=6)

        # Arrow grew again — 22sp/44px → 34sp/70px still wasn't enough
        # ("for the 17th time... please make the back arrow bigger").
        # Jumping straight to 50sp/95px this round instead of another timid
        # step — the glyph now slightly overflows this row's height, which
        # reads as more prominent rather than clipped (Label textures aren't
        # stencil-clipped to their widget's box). Row only grew 46→48; the
        # rest of the card's +14 went to `main_row` below it, where the temp
        # needed the room far more ("the temp needs to fill that top
        # space... bigger temp, come on, all the way to the top, fill it").
        # Funded by trimming the stats card and forecast strip (both now sit
        # exactly on their content minimums — see their comments below).
        # Trimmed again, 48→40 — the user circled the temp on a screenshot
        # ("like this big") at roughly double its 88sp size, and `main_row`
        # needed every spare pixel it could get to support that.
        top_row = BoxLayout(orientation='horizontal', size_hint_y=None, height=40)
        back_btn = Button(
            text="←", font_name=SYMBOL_FONT or 'Roboto', font_size="50sp",
            size_hint=(None, 1), width=95,
            background_normal="", background_down="",
            background_color=(0, 0, 0, 0), color=_TEXT,
        )
        back_btn.bind(on_release=lambda _w: self._on_back and self._on_back())
        top_row.add_widget(back_btn)
        top_row.add_widget(Widget())  # spacer — pushes the clock to the right edge

        # Both lines bumped ("make both time and updated time larger") —
        # next to the now much-bigger arrow they were reading as an
        # afterthought crammed into the corner.
        clock_col = BoxLayout(orientation='vertical', size_hint=(None, 1), width=145)
        self._clock_lbl = Label(text="", font_size="20sp", bold=True, color=_TEXT,
                                size_hint_y=None, height=19,
                                halign="right", valign="bottom")
        self._updated_lbl = Label(text="", font_size="15sp", color=_TEXT,
                                  size_hint_y=None, height=16,
                                  halign="right", valign="top")
        for lbl in (self._clock_lbl, self._updated_lbl):
            lbl.bind(size=lambda w, _v: setattr(w, 'text_size', (w.width, None)))
            clock_col.add_widget(lbl)
        top_row.add_widget(clock_col)
        card.add_widget(top_row)

        # Spacing trimmed 20→12→11 — the row's width budget is far tighter
        # now that the temp alone claims ~240px (up from ~145px before "like
        # this big"); every other element in this row had to give back some
        # room, and the two new centering spacers add a 6th gap, or "Wind"
        # would render outside the card entirely.
        main_row = BoxLayout(orientation='horizontal', spacing=11)
        # Width trimmed to (just over) its rendered size — `keep_ratio`
        # constrains it to the row's height anyway, so the old wider bbox
        # was pure budget waste once the temp needed every spare pixel.
        # Shaved another 8 (114→106) to fund the centering spacers below
        # ("center ... in the hero") without re-tripping the overflow this
        # row already fights at 115sp.
        self._icon_img = Image(size_hint=(None, 1), width=106, allow_stretch=True, keep_ratio=True)
        main_row.add_widget(self._icon_img)

        # Big temp beside the icon, with condition + "feels like" stacked as
        # their own two-line block to its right — matches the mockup, where
        # "Clear" sits level with "83°F" rather than stacked beneath it.
        # 52→62→70→88→115sp. The user circled "68°F" on a screenshot at
        # roughly double its 88sp size and wrote "like this big" — done
        # arguing about it, just matching the box. `main_row` grew to 112px
        # (taking another 8 from `top_row`, which is now nothing but an
        # overflowing arrow and a two-line clock anyway), but 115sp's
        # ~136px texture is still taller than that — it'll overflow into
        # the card's padding above and below. Deliberate: a Label's texture
        # isn't stencil-clipped to its widget box, so the overflow renders
        # as "this number dominates the card" rather than "this number got
        # cut off" — which is exactly what was asked for.
        self._temp_lbl = Label(text="", font_size="115sp", bold=True, color=_TEMP,
                               size_hint=(None, None))
        # Both dimensions track the rendered texture exactly — no `text_size`
        # binding (deliberately, unlike the other labels in this file): with
        # one, the wrap-width chases the texture-driven widget width in a
        # feedback loop — at 62sp "70°F" no longer fit a fixed seed width and
        # got caught wrapping into two lines. Sizing the *widget* to its
        # texture sidesteps that entirely: there's no leftover bbox left for
        # Kivy to center the glyphs within, so the plain top-anchored wrapper
        # below ("temp and F ... up ... in the hero") places it exactly where
        # asked with zero wrap risk.
        self._temp_lbl.bind(texture_size=lambda w, ts: setattr(w, 'size', tuple(ts)))

        # temp_col / cond_col both hug the TOP of the row now (trailing
        # spacer absorbs the slack beneath each) instead of sitting centered
        # against the full-height icon — "temp and F and [condition] words
        # ... up ... in the hero". Flex spacers flank the {temp, condition}
        # pair so it drifts toward the row's horizontal middle rather than
        # hugging the icon's edge — "and center ... as a group". This row was
        # already nearly at its width budget (that's what the last overflow
        # fix was about), so the icon and mini-stats each gave back a few
        # more pixels to fund real (if modest) slack for these spacers
        # without pushing "Wind" back off the card.
        temp_col = BoxLayout(orientation='vertical', size_hint=(None, 1))
        self._temp_lbl.bind(width=lambda w, width: setattr(temp_col, 'width', width))
        temp_col.add_widget(self._temp_lbl)
        temp_col.add_widget(Widget(size_hint_y=1))
        main_row.add_widget(Widget(size_hint_x=1))
        main_row.add_widget(temp_col)

        # Fixed width + `shorten` — the same pattern the 'sun' stat label
        # uses below, for the same reason ("overflow text") — rather than
        # a texture-tracking width: at 115sp the temp alone claims ~240px of
        # this row's ~720px budget, so cond_col can't be left to size itself
        # freely any more. "Thunderstorm + hail" at 22sp would run past 200px
        # and shove "Wind" off the edge of the card. 145px comfortably fits
        # every common condition without truncating ("Partly cloudy",
        # "Mostly clear", "Heavy showers"); the rare long ones get an
        # ellipsis instead of an overflowed layout.
        cond_col = BoxLayout(orientation='vertical', spacing=2, size_hint=(None, 1), width=145)
        self._cond_lbl = Label(text="", font_size="22sp", bold=True, color=_TEXT,
                               size_hint_y=None, height=30, halign="left", valign="middle",
                               shorten=True, shorten_from='right')
        self._feels_lbl = Label(text="", font_size="16sp", color=_SUB,
                                size_hint_y=None, height=24, halign="left", valign="middle",
                                shorten=True, shorten_from='right')
        for lbl in (self._cond_lbl, self._feels_lbl):
            lbl.bind(size=lambda w, _v: setattr(w, 'text_size', (w.width, w.height)))
            cond_col.add_widget(lbl)
        cond_col.add_widget(Widget(size_hint_y=1))
        main_row.add_widget(cond_col)
        main_row.add_widget(Widget(size_hint_x=1))

        # Narrowed 110→80→76 — between the much wider temp and the
        # fixed-width condition block, the row has no spare room for these
        # without "Wind" rendering off the card's edge. They anchor flush to
        # the row's right edge now (no trailing spacer) — "move humidity and
        # wind left" already pulled them off the corner where they fought the
        # clock; anchoring right keeps them put as a stable landmark while
        # the temp/condition cluster floats in the middle.
        self._mini_humidity = self._add_mini_stat(main_row, "Humidity", width=76)
        self._mini_wind     = self._add_mini_stat(main_row, "Wind", width=76)
        card.add_widget(main_row)
        content.add_widget(card)

    def _add_mini_stat(self, card, caption, width=110):
        # Bumped 12/22sp → 14/26sp ("increase font") and the same flex-spacer
        # trick as cond_col centers caption+value vertically against the
        # full-height temp/icon instead of sitting low against the card floor.
        col = BoxLayout(orientation='vertical', size_hint_x=None, width=width, spacing=2)
        col.add_widget(Widget(size_hint_y=1))
        col.add_widget(Label(text=caption, font_size="14sp", color=_SUB,
                             size_hint_y=None, height=20, halign='center', valign='middle'))
        value = Label(text="—", font_size="26sp", bold=True, color=_TEXT,
                      size_hint_y=None, height=34, halign='center', valign='middle')
        col.add_widget(value)
        col.add_widget(Widget(size_hint_y=1))
        card.add_widget(col)
        return value

    def _build_stats_card(self, content):
        # Gives back another 8px to fund the hero card's bigger arrow row.
        # 76 lands exactly on this card's content minimum (64px grid row +
        # 12px top/bottom padding) — zero slack, but nothing here grows
        # dynamically (the 'sun' label's text_size is bound to a fixed
        # (width, height), not (width, None) — no wrap-trap risk), so a
        # tight fit doesn't mean a clipped one.
        card = _GlassCard(size_hint_y=None, height=76, padding=[14, 6, 14, 6])
        grid = GridLayout(cols=4, spacing=4)
        card.add_widget(grid)
        self._stat_labels = {}
        for key, caption in self._STATS:
            # Captions were the one thing in this card still small/un-bold —
            # "weather tile font needs to be much larger and bold" — brought
            # them up to match the weight of the values above them.
            col = BoxLayout(orientation='vertical', spacing=4)
            col.add_widget(Label(text=caption, font_size="15sp", bold=True, color=_SUB,
                                 size_hint_y=None, height=22))
            # 'sun' renders a → arrow glyph — needs SYMBOL_FONT or it shows as tofu.
            # Its value is also by far the longest string ("6:00 AM → 8:56 PM"),
            # so it gets its own smaller size + a width-bound text_size —
            # otherwise it overflows past the card's right edge at the same
            # 26sp the other three stats use ("overflow text").
            if key == 'sun':
                value = Label(text="—", font_size="16sp", bold=True, color=_TEXT,
                              font_name=SYMBOL_FONT or 'Roboto', halign='center', valign='middle',
                              size_hint_y=None, height=38, shorten=True, shorten_from='right')
                value.bind(size=lambda w, _v: setattr(w, 'text_size', (w.width, w.height)))
            else:
                value = Label(text="—", font_size="26sp", bold=True, color=_TEXT,
                              font_name='Roboto', size_hint_y=None, height=38)
            col.add_widget(value)
            grid.add_widget(col)
            self._stat_labels[key] = value
        content.add_widget(card)

    # -- public interface -------------------------------------------------------

    def update(self, data: dict, lat=None, lon=None):
        if not data:
            return
        self._data = data
        self._last_update = datetime.now()
        self._lat, self._lon = lat, lon

        self._icon_img.source = get_icon_path(data.get('wcode', -1)) or ""
        self._temp_lbl.text  = f"{data['temp']}°F"
        self._cond_lbl.text  = data.get('condition', '')
        self._feels_lbl.text = f"Feels like {data.get('feels_like', data['temp'])}°"
        self._mini_humidity.text = f"{data.get('humidity', '—')}%"
        self._mini_wind.text     = f"{data.get('wind_mph', '—')} mph"

        uv = data.get('uv_index', 0)
        s = self._stat_labels
        s['uv'].text       = f"{uv:g}  {_uv_category(uv)}"
        s['gusts'].text    = f"{data.get('wind_gusts', '—')} mph"
        s['pressure'].text = f"{data.get('pressure_in', '—')} in"
        s['sun'].text      = f"{data.get('sunrise_label', '—')}  →  {data.get('sunset_label', '—')}"

        self._rebuild_forecast(data.get('daily', [])[:5])
        self._clouds.set_cloud_pct(data.get('cloud_pct', 0))
        self._precip.set_condition(data.get('wcode', -1))
        self._start_ticking()

    # -- forecast strip ----------------------------------------------------------

    def _rebuild_forecast(self, days):
        self._forecast.clear_widgets()
        for idx, day in enumerate(days):
            # Padding/spacing trimmed (16/4 → 8/3) to bankroll the across-the-
            # board font bump below ("all the fonts... its all tiny, biggie
            # size!") without pushing minimum_height past the 184px cell.
            col = _DayCol(orientation='vertical', spacing=3, padding=[0, 8, 0, 8])
            with col.canvas.before:
                Color(*_CARD)
                rect = RoundedRectangle(radius=[10], pos=col.pos, size=col.size)
            col.bind(
                pos=lambda w, _v, r=rect: setattr(r, 'pos', w.pos),
                size=lambda w, _v, r=rect: setattr(r, 'size', w.size),
            )
            if self._lat and self._lon:
                col.bind(on_release=lambda _inst, d=day, today=(idx == 0): self._open_day_detail(d, today))

            # Another full size pass — every label in the tile bumped
            # ("forecast tiles, day headers... need to be much larger" /
            # "all the fonts, the 'rain 80%' etc, its all tiny, biggie size!").
            label = "Today" if idx == 0 else day['day']
            col.add_widget(Label(text=label, font_size="20sp", bold=True, color=_SUB,
                                 size_hint_y=None, height=26))
            icon_path = get_icon_path(day.get('wcode', -1))
            if icon_path:
                col.add_widget(Image(source=icon_path, size_hint_y=None, height=44,
                                     allow_stretch=True, keep_ratio=True))
            else:
                col.add_widget(BoxLayout(size_hint_y=None, height=44))
            cond_text = day['cond_short']
            if day.get('precip_pct', 0) > 0:
                cond_text += f"  {day['precip_pct']}%"
            col.add_widget(Label(text=cond_text, font_size="18sp", bold=True, color=_TEXT,
                                 size_hint_y=None, height=24))
            col.add_widget(Label(text=f"{day['high']}°", font_size="24sp", bold=True,
                                 color=_TEMP, size_hint_y=None, height=32))
            col.add_widget(Label(text=f"{day['low']}°", font_size="18sp", bold=True, color=_SUB,
                                 size_hint_y=None, height=24))
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
