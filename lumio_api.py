"""lumio_api.py — Minimal Philips Hue local REST + SSE client."""

import json
import time

import requests

from theme import SETTINGS_FILE


class HueAPI:
    """Minimal Hue local REST client."""

    def __init__(self):
        import os
        if not os.path.exists(SETTINGS_FILE):
            raise FileNotFoundError(
                f"Settings not found: {SETTINGS_FILE}\n"
                "Run hue_discovery.py first to authenticate."
            )
        with open(SETTINGS_FILE) as fh:
            cfg = json.load(fh)
        if not cfg.get("bridge_ip") or not cfg.get("username"):
            raise FileNotFoundError(
                "Bridge credentials missing from hue_settings.json.\n"
                "Run hue_discovery.py first to authenticate."
            )
        self.ip       = cfg["bridge_ip"]
        self.username = cfg["username"]
        self._base    = f"http://{self.ip}/api/{self.username}"

    def get_groups(self) -> dict:
        r = requests.get(f"{self._base}/groups", timeout=4)
        r.raise_for_status()
        return r.json()

    def set_group_on(self, group_id: str, on: bool) -> None:
        requests.put(
            f"{self._base}/groups/{group_id}/action",
            json={"on": on}, timeout=4,
        )

    def set_group_brightness(self, group_id: str, bri: int) -> None:
        """Set brightness (1–254), turning the group on in the same call."""
        requests.put(
            f"{self._base}/groups/{group_id}/action",
            json={"on": True, "bri": max(1, min(254, bri))},
            timeout=4,
        )

    def get_light(self, light_id: str) -> dict:
        r = requests.get(f"{self._base}/lights/{light_id}", timeout=4)
        r.raise_for_status()
        return r.json()

    def set_light_on(self, light_id: str, on: bool) -> None:
        requests.put(
            f"{self._base}/lights/{light_id}/state",
            json={"on": on}, timeout=4,
        )

    def set_light_brightness(self, light_id: str, bri: int) -> None:
        requests.put(
            f"{self._base}/lights/{light_id}/state",
            json={"on": True, "bri": max(1, min(254, bri))}, timeout=4,
        )

    def get_group(self, group_id: str) -> dict:
        r = requests.get(f"{self._base}/groups/{group_id}", timeout=4)
        r.raise_for_status()
        return r.json()

    def event_stream(self):
        """Generator yielding parsed CLIP v2 SSE event lists. Reconnects on error."""
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        url     = f"https://{self.ip}/eventstream/clip/v2"
        headers = {"hue-application-key": self.username, "Accept": "text/event-stream"}
        while True:
            try:
                with requests.get(url, headers=headers, stream=True,
                                  verify=False, timeout=(5, None)) as resp:
                    yield {"_sse": "connected"}
                    for line in resp.iter_lines():
                        if line and line.startswith(b"data:"):
                            try:
                                yield json.loads(line[5:].strip())
                            except json.JSONDecodeError:
                                pass
            except Exception as exc:
                yield {"_sse": "disconnected", "_error": str(exc)}
            time.sleep(5)
