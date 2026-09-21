"""Indian National Air Quality Index (CPCB) helpers.

Category breakpoints follow the Central Pollution Control Board scale:

    0-50     Good
    51-100   Satisfactory
    101-200  Moderate
    201-300  Poor
    301-400  Very Poor
    401-500  Severe
"""

from __future__ import annotations

from typing import List, Tuple

AQI_MIN = 0.0
AQI_MAX = 500.0

_CATEGORIES: List[Tuple[float, str, str]] = [
    (50.0, "good", "Good"),
    (100.0, "satisfactory", "Satisfactory"),
    (200.0, "moderate", "Moderate"),
    (300.0, "poor", "Poor"),
    (400.0, "very_poor", "Very Poor"),
    (500.0, "severe", "Severe"),
]

# PM2.5 (ug/m3) breakpoints -> AQI sub-index breakpoints, per CPCB.
_PM25_BREAKPOINTS: List[Tuple[float, float, float, float]] = [
    (0.0, 30.0, 0.0, 50.0),
    (30.0, 60.0, 51.0, 100.0),
    (60.0, 90.0, 101.0, 200.0),
    (90.0, 120.0, 201.0, 300.0),
    (120.0, 250.0, 301.0, 400.0),
    (250.0, 500.0, 401.0, 500.0),
]

CATEGORY_KEYS = [key for _, key, _ in _CATEGORIES]


def clamp_aqi(value: float) -> float:
    """Clamp an AQI value into the valid 0-500 range."""
    if value != value:  # NaN guard
        return AQI_MIN
    return max(AQI_MIN, min(AQI_MAX, float(value)))


def aqi_category(value: float) -> str:
    """Return the machine-readable CPCB category key for ``value``."""
    aqi = clamp_aqi(value)
    for upper, key, _ in _CATEGORIES:
        if aqi <= upper:
            return key
    return _CATEGORIES[-1][1]


def aqi_category_label(value: float) -> str:
    """Return the human-readable CPCB category label for ``value``."""
    key = aqi_category(value)
    for _, candidate, label in _CATEGORIES:
        if candidate == key:
            return label
    return _CATEGORIES[-1][2]


def pm25_to_aqi(concentration_ug_m3: float) -> float:
    """Convert a PM2.5 concentration to the CPCB AQI sub-index."""
    conc = max(0.0, float(concentration_ug_m3))
    for c_low, c_high, i_low, i_high in _PM25_BREAKPOINTS:
        if conc <= c_high:
            return round(((i_high - i_low) / (c_high - c_low)) * (conc - c_low) + i_low, 1)
    return AQI_MAX


def aqi_to_pm25(aqi: float) -> float:
    """Approximate inverse of :func:`pm25_to_aqi`, useful for synthetic data."""
    value = clamp_aqi(aqi)
    for c_low, c_high, i_low, i_high in _PM25_BREAKPOINTS:
        if value <= i_high:
            return round(((c_high - c_low) / (i_high - i_low)) * (value - i_low) + c_low, 1)
    return 500.0
