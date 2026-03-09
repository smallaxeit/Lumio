"""lumio_brightness.py — Raspberry Pi backlight brightness control."""

import os

_BACKLIGHT_CANDIDATES = [
    "/sys/class/backlight/rpi_backlight/brightness",
    "/sys/class/backlight/10-0045/brightness",
    "/sys/class/backlight/backlight/brightness",
]
BACKLIGHT_PATH = next(
    (p for p in _BACKLIGHT_CANDIDATES if os.path.exists(p)),
    _BACKLIGHT_CANDIDATES[0],
)


def get_brightness() -> int:
    """Read current backlight brightness (0–255). Returns 200 on dev machines."""
    try:
        with open(BACKLIGHT_PATH) as f:
            return int(f.read().strip())
    except Exception:
        return 200


def set_brightness(value: int) -> None:
    """Write backlight brightness (10–255). Tries direct write then sudo tee."""
    v = str(max(10, min(255, int(value))))
    try:
        with open(BACKLIGHT_PATH, "w") as f:
            f.write(v)
    except PermissionError:
        try:
            import subprocess
            subprocess.run(["sudo", "tee", BACKLIGHT_PATH],
                           input=v.encode(), capture_output=True)
        except Exception as exc:
            print(f"[brightness] sudo tee failed: {exc}")
    except Exception as exc:
        print(f"[brightness] {exc}")
