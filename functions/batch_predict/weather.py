"""Meteorological feature providers.

``OpenMeteoWeatherProvider`` calls the Open-Meteo forecast API, which is free
for non-commercial use and requires no API key, making it a natural fit for a
zero-cost architecture. ``SyntheticWeatherProvider`` returns deterministic
climatological values for offline development and tests. Both return the same
dictionary shape expected by ``vayusetu_ml.features``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import math
from typing import Any, Dict, Optional, Protocol

import requests

from vayusetu_common.retry import is_transient_error, retry_with_backoff

logger = logging.getLogger(__name__)

WEATHER_KEYS = (
    "temperature_c",
    "humidity_pct",
    "wind_speed_ms",
    "wind_direction_deg",
    "precipitation_mm",
    "pressure_hpa",
    "boundary_layer_height_m",
)


class WeatherProvider(Protocol):
    name: str

    def current(self, latitude: float, longitude: float, at: dt.datetime) -> Optional[Dict[str, float]]: ...


def _round_cell(latitude: float, longitude: float, step: float = 0.25) -> tuple[float, float]:
    return round(round(latitude / step) * step, 2), round(round(longitude / step) * step, 2)


class SyntheticWeatherProvider:
    """Deterministic weather derived from location, month and hour."""

    name = "synthetic"

    def current(self, latitude: float, longitude: float, at: dt.datetime) -> Dict[str, float]:
        month = at.month
        local_hour = (at.hour + 5.5) % 24
        winter = month in (11, 12, 1, 2)
        monsoon = month in (6, 7, 8, 9)
        digest = hashlib.sha256(f"{round(latitude, 1)}:{round(longitude, 1)}:{at.date()}".encode()).digest()
        noise = [(b / 255.0 - 0.5) for b in digest[:5]]
        temperature = (16.0 if winter else 30.0) + 6.0 * math.sin((local_hour - 9) / 24 * 2 * math.pi) + noise[0] * 4
        humidity = (85.0 if monsoon else (62.0 if winter else 42.0)) + noise[1] * 15
        wind = max(0.2, (1.6 if winter else 3.2) + noise[2] * 2.0)
        rain = max(0.0, 3.0 + noise[3] * 6) if monsoon else 0.0
        blh = max(80.0, (320.0 if winter else 900.0) * (0.5 if local_hour < 7 or local_hour > 20 else 1.4) + noise[4] * 150)
        return {
            "temperature_c": round(temperature, 1),
            "humidity_pct": round(min(100.0, max(5.0, humidity)), 1),
            "wind_speed_ms": round(wind, 2),
            "wind_direction_deg": round((digest[5] / 255.0) * 360.0, 1),
            "precipitation_mm": round(rain, 2),
            "pressure_hpa": round(1012.0 + (6.0 if winter else -4.0), 1),
            "boundary_layer_height_m": round(blh, 0),
        }


class OpenMeteoWeatherProvider:
    """Fetch current conditions and boundary layer height from Open-Meteo."""

    name = "open-meteo"
    BASE_URL = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, timeout_seconds: float = 8.0, session: Optional[requests.Session] = None, fallback: Optional[WeatherProvider] = None) -> None:
        self.timeout_seconds = timeout_seconds
        self._session = session or requests.Session()
        self._cache: Dict[tuple[float, float, str], Dict[str, float]] = {}
        self._fallback = fallback or SyntheticWeatherProvider()

    def current(self, latitude: float, longitude: float, at: dt.datetime) -> Dict[str, float]:
        cell = _round_cell(latitude, longitude)
        cache_key = (cell[0], cell[1], at.strftime("%Y-%m-%dT%H"))
        if cache_key in self._cache:
            return self._cache[cache_key]
        try:
            weather = self._fetch(cell[0], cell[1], at)
        except Exception as exc:  # noqa: BLE001 - weather is a soft dependency
            logger.warning("Open-Meteo unavailable for %s (%s); using synthetic weather", cell, exc)
            weather = self._fallback.current(latitude, longitude, at)
        self._cache[cache_key] = weather
        return weather

    @retry_with_backoff(max_attempts=3, base_delay=1.0, max_delay=6.0, retry_on=(requests.RequestException, RuntimeError), should_retry=is_transient_error, operation_name="open_meteo")
    def _fetch(self, latitude: float, longitude: float, at: dt.datetime) -> Dict[str, float]:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,relative_humidity_2m,precipitation,surface_pressure,wind_speed_10m,wind_direction_10m",
            "hourly": "boundary_layer_height",
            "forecast_days": 1,
            "wind_speed_unit": "ms",
            "timezone": "UTC",
        }
        response = self._session.get(self.BASE_URL, params=params, timeout=self.timeout_seconds)
        if response.status_code >= 400:
            error = RuntimeError(f"Open-Meteo returned HTTP {response.status_code}")
            error.status_code = response.status_code  # type: ignore[attr-defined]
            raise error
        payload: Dict[str, Any] = response.json()
        current = payload.get("current") or {}
        hourly = payload.get("hourly") or {}
        blh = _pick_hourly(hourly, "boundary_layer_height", at)
        weather = {
            "temperature_c": float(current.get("temperature_2m", 26.0)),
            "humidity_pct": float(current.get("relative_humidity_2m", 55.0)),
            "wind_speed_ms": float(current.get("wind_speed_10m", 2.5)),
            "wind_direction_deg": float(current.get("wind_direction_10m", 270.0)),
            "precipitation_mm": float(current.get("precipitation", 0.0)),
            "pressure_hpa": float(current.get("surface_pressure", 1010.0)),
            "boundary_layer_height_m": float(blh if blh is not None else 800.0),
        }
        return weather


def _pick_hourly(hourly: Dict[str, Any], key: str, at: dt.datetime) -> Optional[float]:
    times = hourly.get("time") or []
    values = hourly.get(key) or []
    if not times or not values:
        return None
    target = at.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:00")
    for index, stamp in enumerate(times):
        if stamp == target and index < len(values) and values[index] is not None:
            return float(values[index])
    for value in values:
        if value is not None:
            return float(value)
    return None


def build_weather_provider(name: str) -> WeatherProvider:
    if name.lower() in {"open-meteo", "openmeteo", "open_meteo"}:
        return OpenMeteoWeatherProvider()
    return SyntheticWeatherProvider()
