"""lumio_weather.py — Weather fetching via Open-Meteo and IP geolocation."""

from datetime import datetime

import requests

from theme import save_settings

_WMO_CODES = {
    0: "Clear",
    1: "Mostly clear",   2: "Partly cloudy",        3: "Overcast",
    45: "Foggy",         48: "Icy fog",
    51: "Light drizzle", 53: "Drizzle",              55: "Heavy drizzle",
    61: "Light rain",    63: "Rain",                 65: "Heavy rain",
    71: "Light snow",    73: "Snow",                 75: "Heavy snow",    77: "Sleet",
    80: "Showers",       81: "Rain showers",         82: "Heavy showers",
    85: "Snow showers",  86: "Heavy snow showers",
    95: "Thunderstorm",  96: "Thunderstorm + hail",  99: "Heavy thunderstorm",
}

_WMO_SHORT = {
    0: "Clear",      1: "Mostly Clr", 2: "P. Cloudy",  3: "Overcast",
    45: "Foggy",     48: "Icy Fog",
    51: "Drizzle",   53: "Drizzle",   55: "Drizzle",
    61: "Lt. Rain",  63: "Rain",      65: "Rain",
    71: "Lt. Snow",  73: "Snow",      75: "Snow",      77: "Sleet",
    80: "Showers",   81: "Showers",   82: "Showers",
    85: "Sn Shower", 86: "Sn Shower",
    95: "T-Storm",   96: "T-Storm",   99: "T-Storm",
}


def _fetch_weather(lat: float, lon: float) -> dict:
    """Return weather dict with current + 5-day forecast, or None on error."""
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&current_weather=true"
            "&daily=temperature_2m_max,temperature_2m_min,weathercode,precipitation_probability_max"
            "&temperature_unit=fahrenheit&wind_speed_unit=mph"
            "&timezone=auto&forecast_days=6"
        )
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        body = r.json()
        cw   = body["current_weather"]
        temp = round(cw["temperature"])
        code = int(cw["weathercode"])
        cond = _WMO_CODES.get(code, "")

        daily = []
        d = body.get("daily", {})
        precip_list = d.get("precipitation_probability_max", [])
        for i, date_str in enumerate(d.get("time", [])):
            wcode  = int(d["weathercode"][i])
            precip = int(precip_list[i]) if i < len(precip_list) and precip_list[i] is not None else 0
            daily.append({
                "date":       date_str,
                "day":        datetime.fromisoformat(date_str).strftime("%a"),
                "high":       round(d["temperature_2m_max"][i]),
                "low":        round(d["temperature_2m_min"][i]),
                "condition":  _WMO_CODES.get(wcode, ""),
                "cond_short": _WMO_SHORT.get(wcode, ""),
                "precip_pct": precip,
            })

        return {
            "label":     f"{temp}°F  {cond}" if cond else f"{temp}°F",
            "temp":      temp,
            "condition": cond,
            "wind_mph":  round(cw["windspeed"]),
            "daily":     daily,
        }
    except Exception:
        return None


def _fetch_hourly(lat: float, lon: float, date_str: str) -> list:
    """Fetch hourly forecast for a single date (6am–10pm). Returns list of dicts or None."""
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&hourly=temperature_2m,weathercode,precipitation_probability,windspeed_10m"
            "&temperature_unit=fahrenheit&wind_speed_unit=mph"
            f"&timezone=auto&start_date={date_str}&end_date={date_str}"
        )
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        h = r.json()["hourly"]
        precip_list = h.get("precipitation_probability", [])
        hours = []
        for i, ts in enumerate(h.get("time", [])):
            dt     = datetime.fromisoformat(ts)
            precip = int(precip_list[i]) if i < len(precip_list) and precip_list[i] is not None else 0
            hours.append({
                "hour":       dt.hour,
                "time":       dt.strftime("%I %p").lstrip("0"),
                "temp":       round(h["temperature_2m"][i]),
                "condition":  _WMO_CODES.get(int(h["weathercode"][i]), ""),
                "precip_pct": precip,
                "wind_mph":   round(h["windspeed_10m"][i]),
            })
        return hours
    except Exception:
        return None


def _resolve_location(settings: dict) -> tuple:
    """Return (lat, lon) from saved settings or IP geolocation. Updates settings in-place."""
    if settings.get("latitude") and settings.get("longitude"):
        return float(settings["latitude"]), float(settings["longitude"])
    try:
        r = requests.get("http://ip-api.com/json", timeout=6)
        r.raise_for_status()
        data = r.json()
        if data.get("status") == "success":
            lat, lon = data["lat"], data["lon"]
            settings["latitude"]  = lat
            settings["longitude"] = lon
            settings["city"]      = data.get("city", "")
            save_settings(settings)
            return lat, lon
    except Exception:
        pass
    return None, None
