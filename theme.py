"""
theme.py — shared palette, color container, UI constants, and settings I/O.
All UI modules import `C` from here; set_theme() mutates it in-place so every
module sees the new colors immediately without re-importing.
"""

import json
import os
import platform

# ── File paths ─────────────────────────────────────────────────────────────────

_DIR          = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(_DIR, "hue_settings.json")
LOG_FILE      = os.path.join(_DIR, "hue_log.jsonl")

# ── Grid / layout constants ────────────────────────────────────────────────────

CARD_HEIGHT      = 80
CARD_SPACING     = 4
CARD_COLS        = 2
REFRESH_INTERVAL = 10

# ── Palettes ───────────────────────────────────────────────────────────────────

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

# ── Mutable color container ────────────────────────────────────────────────────

class _C:
    """Mutable theme color container. Import as `from theme import C`.
    Attributes are mutated in-place by set_theme() so all modules stay in sync."""
    BG          = PALETTE_LIGHT['BG']
    HEADER_BG   = PALETTE_LIGHT['HEADER_BG']
    CARD_OFF    = PALETTE_LIGHT['CARD_OFF']
    CARD_ON     = PALETTE_LIGHT['CARD_ON']
    CARD_TARGET = PALETTE_LIGHT['CARD_TARGET']
    BTN_ON      = PALETTE_LIGHT['BTN_ON']
    BTN_OFF     = PALETTE_LIGHT['BTN_OFF']
    BTN_EDIT    = PALETTE_LIGHT['BTN_EDIT']
    TEXT        = PALETTE_LIGHT['TEXT']
    TEXT_ON     = PALETTE_LIGHT['TEXT_ON']
    SUBTEXT     = PALETTE_LIGHT['SUBTEXT']
    ERROR       = PALETTE_LIGHT['ERROR']

C = _C()

def set_theme(palette: dict) -> None:
    C.BG          = palette['BG']
    C.HEADER_BG   = palette['HEADER_BG']
    C.CARD_OFF    = palette['CARD_OFF']
    C.CARD_ON     = palette['CARD_ON']
    C.CARD_TARGET = palette['CARD_TARGET']
    C.BTN_ON      = palette['BTN_ON']
    C.BTN_OFF     = palette['BTN_OFF']
    C.BTN_EDIT    = palette['BTN_EDIT']
    C.TEXT        = palette['TEXT']
    C.TEXT_ON     = palette['TEXT_ON']
    C.SUBTEXT     = palette['SUBTEXT']
    C.ERROR       = palette['ERROR']

# ── Symbol font ────────────────────────────────────────────────────────────────

def _find_symbol_font() -> str:
    candidates = {
        'Windows': 'C:/Windows/Fonts/seguisym.ttf',
        'Linux':   '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        'Darwin':  '/System/Library/Fonts/Apple Symbols.ttf',
    }
    path = candidates.get(platform.system(), '')
    return path if path and os.path.exists(path) else ''

SYMBOL_FONT = _find_symbol_font()

# ── Settings I/O ───────────────────────────────────────────────────────────────

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

# ── Room ordering utility ──────────────────────────────────────────────────────

def rooms_ordered(groups: dict, order: list) -> list:
    """Return Room-type groups in the given order; unknowns appended alphabetically."""
    all_rooms = {gid: g for gid, g in groups.items() if g.get("type") == "Room"}
    ordered   = [(gid, all_rooms[gid]) for gid in order if gid in all_rooms]
    seen      = {gid for gid, _ in ordered}
    for gid, g in sorted(all_rooms.items(), key=lambda x: x[1].get("name", "")):
        if gid not in seen:
            ordered.append((gid, g))
    return ordered

# ── Shared Kivy helpers ────────────────────────────────────────────────────────
# Defined here so both ui_cards and ui_panels can import without circular deps.

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.label import Label


class _TappableRow(BoxLayout):
    """BoxLayout that fires on_release on tap without grabbing the touch.
    Replacing ButtonBehavior so parent ScrollViews can still scroll freely."""

    __events__ = ('on_release',)

    def on_release(self):
        pass

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._tap_uid = touch.uid
            self._tap_ox  = touch.x
            self._tap_oy  = touch.y
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        if getattr(self, '_tap_uid', None) == touch.uid:
            self._tap_uid = None
            if (abs(touch.x - self._tap_ox) < 20
                    and abs(touch.y - self._tap_oy) < 20
                    and self.collide_point(*touch.pos)):
                self.dispatch('on_release')
        return super().on_touch_up(touch)


class _WeatherBtn(ButtonBehavior, Label):
    """Tappable Label — fires on_release when tapped."""


class _DayCol(ButtonBehavior, BoxLayout):
    """Tappable day column in the weather forecast grid."""
