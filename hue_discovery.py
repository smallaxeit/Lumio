#!/usr/bin/env python3
"""
Philips Hue Bridge Discovery & Authentication
Discovers and prints all lights, rooms/groups, and scenes from a Hue Bridge.
Saves credentials to hue_config.json after first authentication.
"""

import json
import os
import sys
import time
import requests

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "hue_settings.json")
APP_NAME = "hue_discovery"
DEVICE_NAME = "python_client"


# ── Bridge Discovery ──────────────────────────────────────────────────────────

def discover_bridge():
    """Find a Hue Bridge on the local network via Philips' cloud discovery."""
    print("Discovering Hue Bridge on local network...")
    try:
        resp = requests.get("https://discovery.meethue.com/", timeout=5)
        resp.raise_for_status()
        bridges = resp.json()
        if bridges:
            ip = bridges[0]["internalipaddress"]
            print(f"  Found bridge at {ip}")
            return ip
    except requests.RequestException as exc:
        print(f"  Cloud discovery failed ({exc}), trying mDNS fallback...")

    # Fallback: N-UPnP local scan
    try:
        resp = requests.get("https://www.meethue.com/api/nupnp", timeout=5)
        resp.raise_for_status()
        bridges = resp.json()
        if bridges:
            ip = bridges[0]["internalipaddress"]
            print(f"  Found bridge via N-UPnP at {ip}")
            return ip
    except requests.RequestException:
        pass

    print("  Could not auto-discover bridge.")
    ip = input("Enter bridge IP address manually: ").strip()
    return ip if ip else None


# ── Authentication ────────────────────────────────────────────────────────────

def load_config():
    """Load saved bridge config, or return None if not found."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return None


def save_config(ip, username):
    """Persist bridge IP and API username, preserving any existing app settings."""
    existing = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                existing = json.load(f)
        except Exception:
            pass
    existing["bridge_ip"] = ip
    existing["username"]  = username
    with open(CONFIG_FILE, "w") as f:
        json.dump(existing, f, indent=2)
    print(f"  Credentials saved to {CONFIG_FILE}")


def authenticate(bridge_ip):
    """
    Perform the bridge button-press authentication flow.
    Returns the API username (key) on success.
    """
    url = f"http://{bridge_ip}/api"
    payload = {"devicetype": f"{APP_NAME}#{DEVICE_NAME}"}

    print(f"\nPress the link button on your Hue Bridge now...")
    print("Waiting up to 30 seconds for button press.")

    for attempt in range(30):
        time.sleep(1)
        try:
            resp = requests.post(url, json=payload, timeout=5)
            data = resp.json()
        except requests.RequestException as exc:
            print(f"  Network error: {exc}")
            continue

        result = data[0] if isinstance(data, list) and data else {}

        if "success" in result:
            username = result["success"]["username"]
            print(f"  Authenticated! Username: {username}")
            return username

        error = result.get("error", {})
        error_type = error.get("type")

        if error_type == 101:
            # Button not yet pressed — keep waiting
            dots = "." * ((attempt % 3) + 1)
            print(f"\r  Waiting for button press{dots}   ", end="", flush=True)
        else:
            print(f"\n  Authentication error: {error.get('description', result)}")
            sys.exit(1)

    print("\n  Timed out waiting for button press.")
    sys.exit(1)


def get_credentials():
    """Return (bridge_ip, username), authenticating if needed."""
    config = load_config()
    if config:
        ip = config.get("bridge_ip")
        username = config.get("username")
        if ip and username:
            print(f"Using saved credentials for bridge at {ip}")
            return ip, username

    ip = discover_bridge()
    if not ip:
        print("No bridge IP available. Exiting.")
        sys.exit(1)

    username = authenticate(ip)
    save_config(ip, username)
    return ip, username


# ── API Helpers ───────────────────────────────────────────────────────────────

def api_get(bridge_ip, username, endpoint):
    """GET /api/<username>/<endpoint> and return parsed JSON."""
    url = f"http://{bridge_ip}/api/{username}/{endpoint}"
    resp = requests.get(url, timeout=5)
    resp.raise_for_status()
    return resp.json()


# ── Display Helpers ───────────────────────────────────────────────────────────

def print_header(title):
    width = 60
    print(f"\n{'═' * width}")
    print(f"  {title}")
    print(f"{'═' * width}")


def brightness_bar(bri):
    """Render a small ASCII bar for brightness (0–254)."""
    filled = round((bri / 254) * 10)
    return f"[{'█' * filled}{'░' * (10 - filled)}] {bri}/254"


def color_mode_label(state):
    mode = state.get("colormode")
    if mode == "ct":
        ct = state.get("ct", 0)
        kelvin = round(1_000_000 / ct) if ct else 0
        return f"Color Temp  {ct} mired (~{kelvin}K)"
    if mode == "xy":
        xy = state.get("xy", [0, 0])
        return f"XY Color    ({xy[0]:.4f}, {xy[1]:.4f})"
    if mode == "hs":
        hue = state.get("hue", 0)
        sat = state.get("sat", 0)
        return f"Hue/Sat     hue={hue}  sat={sat}"
    return ""


# ── Printers ──────────────────────────────────────────────────────────────────

def print_lights(lights):
    print_header(f"LIGHTS  ({len(lights)} total)")
    for light_id, light in sorted(lights.items(), key=lambda x: int(x[0])):
        state = light.get("state", {})
        on = state.get("on", False)
        bri = state.get("bri", 0)
        reachable = state.get("reachable", False)
        name = light.get("name", "Unknown")
        model = light.get("modelid", "")
        ltype = light.get("type", "")
        product = light.get("productname", "")

        status = "ON " if on else "OFF"
        reach = "" if reachable else "  [UNREACHABLE]"

        print(f"\n  [{light_id:>2}]  {name}")
        print(f"        Status   : {status}{reach}")
        if on and bri is not None:
            print(f"        Brightness: {brightness_bar(bri)}")
        color_label = color_mode_label(state)
        if color_label:
            print(f"        {color_label}")
        print(f"        Type     : {ltype}")
        if product:
            print(f"        Product  : {product}  ({model})")
        else:
            print(f"        Model    : {model}")


def print_groups(groups):
    print_header(f"ROOMS / GROUPS  ({len(groups)} total)")
    for group_id, group in sorted(groups.items(), key=lambda x: int(x[0])):
        name = group.get("name", "Unknown")
        gtype = group.get("type", "")
        room_class = group.get("class", "")
        lights = group.get("lights", [])
        action = group.get("action", {})
        state = group.get("state", {})

        all_on = state.get("all_on", False)
        any_on = state.get("any_on", False)

        if all_on:
            on_label = "ALL ON"
        elif any_on:
            on_label = "PARTIAL"
        else:
            on_label = "ALL OFF"

        header = f"  [{group_id:>2}]  {name}"
        if room_class:
            header += f"  ({room_class})"
        print(f"\n{header}")
        print(f"        Type     : {gtype}   Status: {on_label}")
        print(f"        Lights   : {', '.join(lights) if lights else 'none'}")

        bri = action.get("bri")
        if bri is not None:
            print(f"        Brightness: {brightness_bar(bri)}")
        color_label = color_mode_label(action)
        if color_label:
            print(f"        {color_label}")


def print_scenes(scenes, groups):
    print_header(f"SCENES  ({len(scenes)} total)")

    # Group scenes by their group/room
    by_group = {}
    for scene_id, scene in scenes.items():
        gid = scene.get("group", "0")
        by_group.setdefault(gid, []).append((scene_id, scene))

    for group_id, scene_list in sorted(by_group.items(), key=lambda x: int(x[0])):
        group_name = groups.get(group_id, {}).get("name", f"Group {group_id}")
        print(f"\n  {group_name}:")
        for scene_id, scene in sorted(scene_list, key=lambda x: x[1].get("name", "")):
            scene_name = scene.get("name", "Unknown")
            scene_type = scene.get("type", "")
            lights = scene.get("lights", [])
            light_count = len(lights)
            print(f"    • [{scene_id[:8]}]  {scene_name:<30}  {light_count} light(s)  [{scene_type}]")

    # Scenes not associated with any group
    ungrouped = [(sid, sc) for sid, sc in scenes.items() if "group" not in sc]
    if ungrouped:
        print(f"\n  (No group):")
        for scene_id, scene in sorted(ungrouped, key=lambda x: x[1].get("name", "")):
            scene_name = scene.get("name", "Unknown")
            lights = scene.get("lights", [])
            print(f"    • [{scene_id[:8]}]  {scene_name:<30}  {len(lights)} light(s)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("╔══════════════════════════════════════════╗")
    print("║       Philips Hue Bridge Discovery       ║")
    print("╚══════════════════════════════════════════╝\n")

    bridge_ip, username = get_credentials()

    print(f"\nFetching data from bridge at {bridge_ip}...")

    try:
        lights = api_get(bridge_ip, username, "lights")
        groups = api_get(bridge_ip, username, "groups")
        scenes = api_get(bridge_ip, username, "scenes")
    except requests.RequestException as exc:
        print(f"Error communicating with bridge: {exc}")
        sys.exit(1)

    # Sanity-check for auth failure (bridge returns list with error)
    for resource_name, resource in [("lights", lights), ("groups", groups)]:
        if isinstance(resource, list) and resource and "error" in resource[0]:
            err = resource[0]["error"]
            print(f"Bridge API error on {resource_name}: {err.get('description')}")
            print("Try deleting hue_settings.json and re-running to re-authenticate.")
            sys.exit(1)

    print_lights(lights)
    print_groups(groups)
    print_scenes(scenes, groups)

    print(f"\n{'═' * 60}")
    print(f"  Summary: {len(lights)} lights · {len(groups)} groups · {len(scenes)} scenes")
    print(f"{'═' * 60}\n")


if __name__ == "__main__":
    main()
