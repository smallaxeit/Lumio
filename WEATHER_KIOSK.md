# Weather Kiosk — design & build notes

> **Standing reminder:** keep this file (and the README feature list / screenshots)
> in sync with the code — update it *as part of* the same change that touches the
> kiosk's data fields, visuals, or wiring, not as an afterthought.

## Overview
A full-screen "ambient" weather view, reachable from the existing `WeatherModal`
popup via an expand button. Both stay available — the popup is for a quick glance,
the kiosk is for leaving the screen on weather as a standalone display, with a
one-tap way back to the room grid.

"Ambient" was chosen over a sourced-art / illustrated style because it's generated
procedurally in Kivy: no images to license or maintain, lighter on the Pi4, and —
the actual win — it reacts live to real data (sky color shifts with the real
sunrise/sunset and cloud cover, the sun/moon arc tracks actual elapsed daylight).

## Data fields (lumio_weather.py `_fetch_weather`)
Switched from Open-Meteo's legacy `current_weather=true` to the richer `current=`
parameter list (same endpoint, no extra request). New fields returned in the
weather dict and what they drive:

| Field | Source param | Powers |
|---|---|---|
| `feels_like` | `apparent_temperature` | current-conditions card |
| `humidity` | `relative_humidity_2m` | stat tile |
| `uv_index` | `uv_index` | stat tile + category label (Low/Moderate/High/Very High/Extreme) |
| `pressure_in` | `pressure_msl` (converted hPa→inHg) | stat tile |
| `visibility_mi` | `visibility` (converted m→mi) | stat tile |
| `cloud_pct` | `cloud_cover` | stat tile, sky desaturation, cloud layer opacity |
| `wind_gusts` | `wind_gusts_10m` | stat tile |
| `is_day` | `is_day` | (kept for reference; ambient layers compute day/night locally from sunrise/sunset so they stay correct between data refreshes) |
| `sunrise` / `sunset` / `*_label` | `daily.sunrise[0]` / `daily.sunset[0]` | sun/moon arc, sky gradient, sunrise→sunset stat strip |
| `wcode` (current) | `weathercode` | icon, precipitation layer intensity |

`_fetch_hourly` is unchanged.

## Architecture
New module `ui_weather_kiosk.py` (mirrors the `ui_cards.py`/`ui_panels.py` split):

- `WeatherKiosk(FloatLayout)` — public surface: `update(data, city, lat, lon)`
  and `set_favorites(rooms, api)`. Layers (back to front): `_SkyBackground` →
  `_CloudLayer` → `_SunMoonArc` → `_PrecipLayer` → foreground content column
  (`_GlassCard` panels: current conditions, stat grid, 5-day forecast strip
  reusing `_DayCol`/`get_icon_path`). Tapping a forecast day opens the existing
  `DayDetailModal` unchanged.
- `_FavToggle(Button)` — compact on/off chip for a "favorite" room, shown in
  the header next to the city name. Mirrors `RoomCard`'s toggle flow exactly
  (optimistic UI, threaded `set_group_on`, `log_event`/`_mark_huecontrol`,
  rollback on error) so a kiosk tap behaves identically to a grid-card tap.
- Always rendered in the same dark-navy palette as `WeatherModal`, regardless of
  app theme — consistent ambient look day or night.
- A single `Clock.schedule_interval(..., 60)` ticks the live clock and recomputes
  the sky gradient + sun/moon arc position from the current time — keeps the scene
  advancing smoothly between weather data refreshes (cadence set by
  `weather_poll_seconds` in `hue_settings.json`, default 120s).

## Toggle wiring
- Header weather label still opens `WeatherModal` exactly as before.
- `WeatherModal` gained a small expand/fullscreen icon button next to its `×`
  close button — promotes straight to the kiosk.
- `RoomGrid` (lumio.py) owns a lazily-built `WeatherKiosk` and swaps it in for
  `header` + `scroll` (same `clear_widgets`/`add_widget` pattern as sort mode),
  restoring them on the kiosk's back-arrow tap. SSE/weather/Supabase threads stay
  anchored in `RoomGrid` throughout — nothing is torn down.

## Light favorites — shipped
What started as a deferred "future idea" (1-2 on/off-only quick-toggle buttons
for frequently-used rooms, no slider) shipped directly into the header: the
kiosk always shows toggles for the **first two entries in the user's
`room_order`** (`hue_settings.json` — "top two per the local config"), each a
compact `_FavToggle` chip colored amber when on / navy when off. See the build
log below for the final design.

## Build notes / progress log
- ✅ Data layer switched to `current=` params (lumio_weather.py) — verified
  against the live API; new dict has `feels_like`, `humidity`, `uv_index`,
  `pressure_in`, `visibility_mi`, `cloud_pct`, `wind_gusts`, `is_day`,
  `sunrise(_label)`, `sunset(_label)`.
- ✅ `ui_weather_kiosk.py` written: `WeatherKiosk` + `_SkyBackground` (gradient
  bands), `_SunMoonArc` (sine arc + glow rings), `_CloudLayer`/`_Cloud` (drift via
  ping-pong `Animation`), `_PrecipLayer` (rain/snow particles, idle when dry),
  `_GlassCard`, current/stats/forecast cards. Single 60s tick drives clock + sky
  + arc; `update()` refreshes data-bound parts on the existing weather-poll cadence.
- ✅ Toggle wired: `WeatherModal` (ui_panels.py) gained `on_expand` + a `⛶`
  header button; `RoomGrid` (lumio.py) holds a lazily-built `self._kiosk` and
  swaps `header`+`scroll` ↔ kiosk via `_show_weather_kiosk`/`_show_room_grid`;
  `_update_weather` now also pushes fresh data into a mounted kiosk.
- ✅ Verified end-to-end in the 800×480 dev window by driving the live app
  (real `on_release` dispatch on the mounted widgets, not import-and-call):
  popup → ⛶ expand → kiosk → ← back → repeated a second time, plus a forecast-
  day tap opening `DayDetailModal` over the kiosk. No exceptions either
  direction; `⛶`/`←` render correctly via `SYMBOL_FONT`; sky gradient, sun arc,
  drifting clouds, and stat grid all populate with live data and look right
  for the time of day/conditions at test time (mid-morning, overcast).
- 🔧 Fix from verification: `_clock_lbl` was colored `_SUB` (designed for the
  dark-navy `WeatherModal`), which nearly disappeared against a light daytime
  sky — changed to `_TEXT` to match the city label and stay readable across
  every sky color/time of day.
- ✅ README feature bullets (Weather Kiosk section) + screenshot
  (`assets/screenshots/weather-kiosk.png`) added; changelog bumped to v0.7.0.
- ✅ Weather poll interval changed from a hardcoded 15 min to a configurable
  `weather_poll_seconds` key in `hue_settings.json` (default `120` = 2 min, per
  user request — 15 min "needs to be way more often"). `_weather_loop`
  (lumio.py) now reads `self._settings.get("weather_poll_seconds", 120)` for
  its wait timeout instead of a literal `900`. Key added to both
  `hue_settings.json` and `hue_settings.example.json`.
- 🔧 Code-review pass: dropped `uv_index_max`/daily `uv_max` — fetched but never
  rendered anywhere (genuine dead data; the table above only ever documented
  the *current* `uv_index`, which does power the stat tile). `_PrecipLayer` now
  rebinds to `size` and rebuilds drops on the first real layout pass — it was
  the only ambient layer that didn't follow that pattern, so a `set_condition`
  call landing before the kiosk was added to its parent (still at Kivy's
  placeholder 100×100 size) could leave rain/snow clustered in a corner of the
  real 800×480 canvas for a few seconds. `WeatherModal`'s `⛶` handler is now a
  named `_on_expand_tap` method instead of a tuple-comma lambda, matching the
  rest of the file's `on_release` style.
- 🔧 UI feedback pass after first real-world look at the screenshot:
  - Fixed the broken `→` between the sunrise/sunset times — the `sun` stat's
    value `Label` was missing `font_name=SYMBOL_FONT`, so the arrow rendered
    as a tofu glyph (looked like a stray "x" between the two times).
  - `_GlassCard`/`_CARD` fills bumped from ~50% to ~88% alpha — at the lower
    alpha the `_SunMoonArc` glow bled through from behind and washed out
    whatever stat tile it happened to be sitting behind as a smudge. Still
    reads as "glass" via the lighter border `Line`; just no longer lets the
    ambient layer behind it bleed through into card text.
  - Current-conditions card reworked to use the full kiosk width: humidity
    and wind moved out of the stat grid into compact mini-stat columns
    (`_add_mini_stat`) next to the temp/condition block — smaller than the
    headline temp, spread across the card instead of clustering against the
    icon. Stat grid dropped from 8 tiles/4 cols to 6 tiles/3 cols (no more
    duplication) now that humidity/wind live in the current-conditions card.
  - Back arrow (`←`) and the popup's `⛶`/`×` buttons enlarged for touch —
    back arrow grew from 44×36 to 64×52 (20sp→28sp); popup buttons from
    40×36 to 56×52 (`⛶` 18sp→22sp, `×` 22sp→26sp, `×` enlarged to match `⛶`
    per "x... can't be tiny if expand area is larger").
- ✅ Light favorites shipped: `_FavToggle` chips in the kiosk header showing
  the first two `room_order` entries as on/off toggles (amber = on, navy =
  off). `RoomGrid._kiosk_favorites()` (lumio.py) reads `room_order` +
  `_last_groups` for `(gid, name, any_on)`; `WeatherKiosk.set_favorites()`
  rebuilds the chips only when the room set changes, otherwise just syncs
  their on/off color so an in-flight tap isn't clobbered. Refreshed on the
  same cadence as weather data (`_push_weather_to_kiosk`).
- 🔧 Second UI feedback pass (fonts, alignment, last-update):
  - City label 17sp→22sp, `_FavToggle` chips 12sp→14sp (width 88→92 to match),
    clock label 16sp→20sp — all already bold, just larger ("font larger and a
    little more bold").
  - Header clock became a two-line `clock_col`: `_clock_lbl` (20sp, bold) with
    a small `_updated_lbl` ("Updated H:MM AM/PM", 11sp, muted) stacked beneath
    it. `WeatherKiosk._last_update` is stamped in `update()` and rendered each
    minute alongside the live clock in `_on_tick`.
  - City label restructured into `city_col`, a column shaped like `clock_col`
    (28px label + 18px spacer, both bottom-anchored) so its baseline lines up
    with the clock's baseline instead of centering across the full header
    height while the clock bottom-anchors within its own sub-row ("align the
    city and time text horizontally, that looks horrible").
  - Current-conditions temp/condition/feels-like switched from `halign="left"`
    to `"center"` — the text column sits in open space between the icon and
    mini-stats, so left-aligned text hugged the icon ("temp is still way
    left").
  - Weather icon's box widened 84→110px. The image is height-constrained
    (~90px) and Kivy centers a texture within its widget's bbox, so the wider
    box both renders the icon a bit larger (no longer width-clipped at 84) and
    visibly centers it between the card's left edge and the temp block
    ("visual... centered between temp and left alignment... bigger would fill
    the space better").
  - `_updated_lbl` color: caught mid-pass that `_SUB`'s blue-gray (tuned for
    the dark glass cards) nearly vanishes directly over the bright daytime
    sky. Tried a translucent-white `_SUB_SKY` first; superseded one round
    later by solid `_TEXT` per explicit ask ("last updated time and label
    needs to be white font") — see below. `_SUB_SKY` removed as dead code.
- 🔧 Third pass — mockup-driven sizing (user supplied an edited screenshot:
  "just a mockup, needs aligned and cleaned up... in general some larger
  elements"):
  - `_updated_lbl` → solid `_TEXT` (white), not muted — explicit ask.
  - Current-conditions temp/condition/feels-like bumped 40/16/13sp →
    46/18/14sp ("in general some larger elements").
  - Forecast-tile text enlarged and the precip line made bold to match the
    day-header's weight: day header 11→13sp, condition/precip line 10→12sp
    (now bold), high temp 15→17sp, low temp 12→13sp ("make the text a little
    larger and bold like the day header and 'rain 34%' etc").
  - That bump pushed `_DayCol.minimum_height` from 128 to 134px against an
    unchanged 118px strip — `_GlassCard`'s rounded-rect background is bound to
    `col.size`, so the overflowing day-header label rendered above the card,
    directly over the lighter sky (looked clipped/faded, like `_SUB` text on
    sky — same family of bug). Grew `_forecast` 118→136px, borrowing from the
    ~46px of slack already sitting above the header (BoxLayout's unfilled
    space lands at the top when no child has `size_hint_y=1`).
