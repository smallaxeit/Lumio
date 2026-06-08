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

- `WeatherKiosk(FloatLayout)` — public surface: `update(data, lat, lon)`,
  constructed with `on_back` callable. Layers (back to front): `_SkyBackground`
  → `_CloudLayer` → `_SunMoonArc` → `_PrecipLayer` → foreground content column
  (a `_GlassCard` hero "current conditions" card, a `_GlassCard` stats row, and
  a 5-day forecast strip reusing `_DayCol`/`get_icon_path`). Tapping a forecast
  day opens the existing `DayDetailModal` unchanged.
- No separate header bar — the hero card *is* the kiosk's only chrome: its top
  row folds in the back arrow (top-left) and a live clock + "Updated H:MMam"
  stamp (top-right), with the big current-conditions row (icon, temp, condition,
  "feels like", mini Humidity/Wind stats) filling the rest of the card. No city
  label — the kiosk only ever shows local conditions, so naming the place was
  redundant chrome.
- `_STATS` is a fixed 4-tile row — UV Index, Gusts, Pressure, Sunrise · Sunset.
  Humidity and Wind moved out of the grid into mini-stat columns inside the
  hero card; Visibility and Cloud Cover were dropped from display entirely
  (still fetched for the ambient layers, just not shown as tiles) — see the
  Sixth-pass log entry for why.
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
- 🔧 Fourth pass — structural rebuild from a cleaner mockup ("not even close to
  the visual I provided... ask questions"). Walked through the new mockup with
  the user before touching code:
  - **Header bar removed entirely.** No more separate `_build_header` row —
    the city label is gone too ("gone, dont need, you always assume local
    conditions") and the favorite-room toggle chips were dropped from the
    kiosk altogether (`_FavToggle`/`set_favorites`/`_kiosk_favorites` and
    their constants deleted as dead code, along with the now-unused
    `threading`/`mainthread`/`log_event`/`_mark_huecontrol` imports).
  - **Current-conditions card became the kiosk's only "chrome"**, folding in
    what the header used to own: a thin top row inside the card holds the `←`
    back button (left) and the clock + "Updated H:MM" (right, plain text on
    the card's navy glass — the blue box around the clock in the mockup was
    confirmed to be a Paint selection-marquee artifact, not a design intent).
    Below that, the existing icon/temp/condition/mini-stats row.
  - **"Clear" now sits beside "83°F"** instead of stacked under it: split the
    old single centered `text_col` into a left-anchored `_temp_lbl` (width
    bound to `texture_size` so it hugs the digits for both "73°F" and
    "100°F" — no ragged gap sized for the longest case) plus a small two-line
    `cond_col` (`_cond_lbl` over `_feels_lbl`) immediately to its right —
    matches the mockup's `[icon][BIG temp][Clear / Feels like]` row.
  - Card height grew 110→152px to fit the new top row; the separate header's
    52px + spacing freed up more than that, and the remainder plus the
    forecast-strip work below absorbed it — net layout sums to the kiosk's
    full content height with zero leftover slack.
- 🔧 Fifth pass — fill the freed space ("lot of dead space at the top, shift
  up and fill, expand bottom tiles too... bottom font still needs increased,
  bold, and love"):
  - `_forecast` strip grew 136→184px — absorbs the ~48px that used to sit as
    dead space above the header. The three card heights (152 + 96 + 184) now
    sum exactly to the kiosk's available content height, so the hero card
    sits flush at the top with no gap.
  - `_DayCol` tiles enlarged to fill the bigger strip and read bolder: day
    name 13→16sp, icon 34→42px, condition/precip 12→14sp, high temp 17→20sp,
    low temp 13→15sp (now also bold, matching the rest of the tile's weight).
    Padding grew 6→16px top/bottom and spacing 2→4px so the larger content
    fills the taller tile rather than floating in extra blank space —
    `_DayCol.minimum_height` (180px) now lands ~4px under the 184px cell, so
    nothing overflows the `_GlassCard` background (the clipping bug from the
    third pass doesn't recur).
- 🔧 Sixth pass — stats card cleanup, from a screenshot the user re-edited
  in Paint ("you have elements i removed... this, only this, this is the
  way... biggie size all that, so much whitespace"):
  - Dropped `Visibility` and `Cloud Cover` from `_STATS` — down to four:
    UV Index, Gusts, Pressure, Sunrise · Sunset (the underlying `cloud_pct`
    data still feeds the ambient sky/cloud layers; only the tile display was
    removed). Grid went `cols=3` (3×2, two cells empty) → `cols=4` (one full
    row, no empty cells — "what there are no empty cells?").
  - Caption/value text enlarged to fill the now-roomier single-row cells:
    caption 10→13sp (height 14→20), value 15→24sp (height 22→36), with
    `spacing=4` added between them — fills the card's existing 96px height
    instead of leaving it looking sparse.
- 🔧 Seventh pass — overflow fix, bigger arrow, bolder stat tiles ("overflow
  text... arrow needs to be much bigger... weather tile font needs to be much
  larger and bold... it's a tiny ass screen"):
  - **Sunrise · Sunset overflow fixed.** At the stats card's shared 26sp, the
    string `"6:00 AM  →  8:56 PM"` ran past its grid cell into the card's
    border. That stat now gets its own smaller size (16sp) plus a
    width-bound `text_size`/`halign='center'`/`shorten=True` safety net —
    confirmed via runtime measurement that it renders at its full text, not
    truncated, comfortably inside its 178px-wide cell with margin to spare.
  - **Back arrow grew 22sp/44×34px → 34sp/70×46px** — "much bigger" was a
    direct, unambiguous ask for a touch target on an 800×480 screen; the top
    row grew 34→46px and the hero card +12 (152→164) to fit it.
  - **Stat captions went from 13sp/regular → 15sp/bold** (the one element in
    that card still small and un-bold — "weather tile font needs to be much
    larger and bold"); values for the three short stats bumped 24→26sp.
    Stats card height gave back the hero's +12 (96→84, tighter padding
    8→6 top/bottom) — the three card heights (164+84+184) still sum to
    exactly the kiosk's content height with zero slack.
- 🔧 Eighth pass — hero fill/centering + forecast tile font sweep ("top
  hero... fill the space, go so much bigger, center horizontal and
  vertical, increase font... forecast tiles, day headers... need to be
  much larger... all the fonts, the 'rain 80%' etc, its all tiny, biggie
  size!" — stats card confirmed good as-is, untouched):
  - **Hero card "fill + center."** Temp 52→62sp, icon bbox 110→128px,
    condition 18→22sp (now bold), feels-like 13→16sp, mini-stat caption
    14sp/value 26sp (was 12/22). `cond_col` and each `_add_mini_stat`
    column got `Widget(size_hint_y=1)` flex spacers bookending their
    label block — without them, a vertical `BoxLayout`'s unfilled slack
    lands above the first child, so "Clear / Feels like" and "Humidity /
    75%" sat low against the card floor instead of vertically centered
    beside the full-height temp/icon ("center horizontal and vertical").
  - **Fixed a self-inflicted `_temp_lbl` wrap bug** the 62sp bump
    exposed: its old `text_size=(self.width, None)` binding created a
    feedback loop with the `texture_size→width` binding — at the larger
    size "70°F" no longer fit the seed `width=120`, got wrapped to two
    lines, and the wrapped width then capped itself at 120 forever
    (measured `texture_size=[120, 146]`, i.e. two lines). Removed the
    `text_size`/`halign`/`valign` entirely — with no `text_size`, Kivy
    just centers the natural single-line texture in the widget's box on
    both axes (which is what `halign="left", valign="middle"` were
    trying to do anyway), and the `texture_size→width` binding can't
    self-trap. Confirmed via runtime measurement: single line,
    `texture_size=[130, 73]`, comfortably inside the 92px row.
  - **Forecast tiles, full font sweep**: day header 16→20sp, icon
    42→44px, condition/precip ("Overcast 23%" etc) 14→18sp, high
    20→24sp, low 15→18sp. Padding/spacing trimmed (16/4 → 8/3) to fund
    it — `_DayCol.minimum_height` lands at 178 against the 184px cell
    (6px buffer), confirmed via runtime measurement and screenshot: no
    clipping, every line reads noticeably bigger and bolder.
- 🔧 Ninth pass — overflow fix from the "like this big" temp bump (an
  annotated screenshot circling "68°F" at roughly double its on-screen
  size; landed at 115sp, up from 88):
  - **Horizontal overflow fixed.** At 115sp the temp alone claims ~240px
    of `main_row`'s ~720px budget — `cond_col`, which had been sizing
    itself freely to its text, plus the mini-stat columns no longer fit;
    "Wind" rendered off the right edge of the card. Rewrote `cond_col` to
    a **fixed width (145px)** with `shorten=True, shorten_from='right'`
    and a `text_size=(width, height)` binding — the same pattern the
    'sun' stat already used for the same reason (overflow text). 145px
    fits every common condition string without truncating ("Partly
    cloudy", "Mostly clear", "Heavy showers"); rare long ones now ellipsis
    instead of blowing out the layout.
  - **Mini-stats narrowed 110→80px** (`_add_mini_stat` gained a `width=`
    parameter) — between the much wider temp and the now fixed-width
    condition block, the row had no spare room for them at their old size.
  - Verified via runtime measurement: zero overflow, "Wind" flush inside
    the card's right edge.
- 🔧 Tenth pass — sun-arc reposition ("shift up, can the lines still be
  kind of sharp?"):
  - `_SunMoonArc._HORIZON` raised **60 → 100**. At low sun elevation (near
    sunrise/sunset) the glow's lowest point on the arc sat right behind
    the forecast strip's corner, poking out from under the glass card
    instead of glowing softly through the gap above it — raising the
    floor moves that low point into the gap between the forecast and
    stats cards instead.
  - "the lines... sharp" confirmed as a check that raising `_HORIZON`
    wouldn't blur or thin the glow rings/path — it doesn't; their alpha
    and stroke width are untouched, only the arc's vertical travel range
    changes.
- 🔧 Eleventh pass — hero "shift up + center" (clarified via
  `AskUserQuestion` from "temp and F and words next to up and center in
  the hero" → user picked "shift the text cluster up + center it"):
  - **`_temp_lbl` re-anchored to the top of the row.** Replaced its old
    `text_size`-driven centering with a `temp_col` wrapper: a vertical
    `BoxLayout` (width bound to the label's `texture_size`-driven width)
    holding the label followed by a trailing `Widget(size_hint_y=1)` flex
    spacer — the established "top-anchor via trailing flex spacer"
    pattern, confirmed empirically earlier this session (a vertical
    `BoxLayout`'s unfilled slack lands above its first child unless
    something downstream claims it).
  - **New, more robust `_temp_lbl` sizing**: rather than track only
    `width` off `texture_size` (the Eighth-pass fix — see above), this
    pass binds the label's whole `size` to `texture_size` (both width
    *and* height). With no leftover bbox on either axis, there's nothing
    left for Kivy to center the glyph texture within — eliminating the
    wrap-trap class of bug at its root rather than patching around it.
  - **`cond_col` top-anchored to match** — gained the same trailing
    `Widget(size_hint_y=1)` spacer so "Mostly clear / Feels like 71°"
    sits level with the top of "72°F" instead of vertically centered
    against the full-height icon.
  - **Centered the {temp, condition} cluster as a group** — flanked
    `temp_col`/`cond_col` with `Widget(size_hint_x=1)` flex spacers on
    each side, drifting the pair toward `main_row`'s horizontal middle
    instead of hugging the icon's left edge ("center ... as a group").
  - Funded the new spacers (without re-tripping the Ninth-pass overflow)
    by narrowing further: icon **114→106px**, mini-stats **80→76px**,
    `main_row` spacing **12→11**.
  - Verified via runtime measurement: `mini_wind` right edge = `main_row`
    right edge = 760.0px (flush, zero overflow); both flex-spacer pairs
    measure ≈5.5px each — symmetric, confirming true horizontal centering.
