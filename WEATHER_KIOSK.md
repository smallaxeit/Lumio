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

- `WeatherKiosk(FloatLayout)` — public surface: `update(data, city, lat, lon)`.
  Layers (back to front): `_SkyBackground` → `_CloudLayer` → `_SunMoonArc` →
  `_PrecipLayer` → foreground content column (`_GlassCard` panels: current
  conditions, stat grid, 5-day forecast strip reusing `_DayCol`/`get_icon_path`).
  Tapping a forecast day opens the existing `DayDetailModal` unchanged.
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

## Future idea (deferred — not built yet)
**Light favorites on the kiosk**: 1-2 small on/off-only quick-toggle buttons
(no brightness slider) for frequently-used rooms, placed wherever the final
ambient layout leaves room. Revisit once the kiosk is in daily use and we can see
what real estate remains.

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
