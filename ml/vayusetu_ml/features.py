"""Feature specification shared by training and inference.

An *observation* is one aggregation cell (geohash) at one point in time. It
fuses three signal families:

* Gemini vision metrics averaged across the citizen images in the cell;
* Sentinel-5P / MODIS satellite metrics from Google Earth Engine;
* meteorological drivers (Open-Meteo in production, synthetic in tests).

Temporal context (hour of day, month, weekday) is derived from the observation
timestamp so callers never need to compute cyclical encodings themselves.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional

import numpy as np
import pandas as pd

TARGET_COLUMN = "aqi_12h"

# Raw (non-derived) inputs accepted from callers. Missing values are imputed
# with the defaults below, which represent a typical Indian urban baseline.
RAW_INPUT_DEFAULTS: Dict[str, float] = {
    # Gemini vision metrics (cell averages)
    "haze_index": 0.45,
    "visibility_km": 4.0,
    "smoke_ratio": 0.0,
    "dust_ratio": 0.0,
    "open_burning_ratio": 0.0,
    "fog_ratio": 0.0,
    "vehicle_density_score": 0.4,
    "construction_activity_score": 0.2,
    "industrial_emission_score": 0.1,
    "vision_aqi_estimate": 150.0,
    "vision_confidence": 0.6,
    "report_count": 1.0,
    # Satellite metrics
    "aer_ai": 0.8,
    "no2_tropospheric_mol_m2": 0.00008,
    "co_column_mol_m2": 0.035,
    "aod_047": 0.5,
    # Weather metrics
    "temperature_c": 26.0,
    "humidity_pct": 55.0,
    "wind_speed_ms": 2.5,
    "wind_direction_deg": 270.0,
    "precipitation_mm": 0.0,
    "pressure_hpa": 1010.0,
    "boundary_layer_height_m": 800.0,
    # Location context
    "latitude": 22.0,
    "longitude": 78.0,
}

DERIVED_COLUMNS: List[str] = [
    "hour_sin",
    "hour_cos",
    "month_sin",
    "month_cos",
    "day_of_week",
    "is_weekend",
    "is_winter",
    "no2_scaled",
    "co_scaled",
    "wind_u",
    "wind_v",
    "stagnation_index",
    "combustion_signal",
    "log_report_count",
]

# The exact, ordered feature list consumed by the model. Changing this list is
# a model-breaking change and requires retraining.
FEATURE_COLUMNS: List[str] = [
    "haze_index",
    "visibility_km",
    "smoke_ratio",
    "dust_ratio",
    "open_burning_ratio",
    "fog_ratio",
    "vehicle_density_score",
    "construction_activity_score",
    "industrial_emission_score",
    "vision_aqi_estimate",
    "vision_confidence",
    "log_report_count",
    "aer_ai",
    "no2_scaled",
    "co_scaled",
    "aod_047",
    "temperature_c",
    "humidity_pct",
    "wind_speed_ms",
    "wind_u",
    "wind_v",
    "precipitation_mm",
    "pressure_hpa",
    "boundary_layer_height_m",
    "stagnation_index",
    "combustion_signal",
    "hour_sin",
    "hour_cos",
    "month_sin",
    "month_cos",
    "day_of_week",
    "is_weekend",
    "is_winter",
    "latitude",
    "longitude",
]


@dataclass
class FeatureVector:
    """A single observation ready for feature engineering."""

    timestamp: dt.datetime
    values: Dict[str, float] = field(default_factory=dict)

    def as_row(self) -> Dict[str, Any]:
        row: Dict[str, Any] = dict(self.values)
        row["timestamp"] = self.timestamp
        return row


def default_feature_values() -> Dict[str, float]:
    return dict(RAW_INPUT_DEFAULTS)


def _to_float(value: Any, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def _to_timestamp(value: Any) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(float(value), tz=dt.timezone.utc)
    if isinstance(value, str) and value:
        parsed = pd.Timestamp(value)
        if parsed.tzinfo is None:
            parsed = parsed.tz_localize("UTC")
        return parsed.to_pydatetime()
    if isinstance(value, pd.Timestamp):
        ts = value if value.tzinfo else value.tz_localize("UTC")
        return ts.to_pydatetime()
    return dt.datetime.now(tz=dt.timezone.utc)


def coerce_observation(record: Mapping[str, Any]) -> FeatureVector:
    """Validate and impute a raw observation mapping into a :class:`FeatureVector`."""
    values: Dict[str, float] = {}
    for key, default in RAW_INPUT_DEFAULTS.items():
        values[key] = _to_float(record.get(key), default)

    # Ranges: keep the model inside the domain it was trained on.
    values["haze_index"] = min(1.0, max(0.0, values["haze_index"]))
    values["visibility_km"] = min(50.0, max(0.0, values["visibility_km"]))
    for ratio in ("smoke_ratio", "dust_ratio", "open_burning_ratio", "fog_ratio", "vision_confidence"):
        values[ratio] = min(1.0, max(0.0, values[ratio]))
    for score in ("vehicle_density_score", "construction_activity_score", "industrial_emission_score"):
        values[score] = min(1.0, max(0.0, values[score]))
    values["vision_aqi_estimate"] = min(500.0, max(0.0, values["vision_aqi_estimate"]))
    values["report_count"] = max(1.0, values["report_count"])
    values["humidity_pct"] = min(100.0, max(0.0, values["humidity_pct"]))
    values["wind_speed_ms"] = max(0.0, values["wind_speed_ms"])
    values["precipitation_mm"] = max(0.0, values["precipitation_mm"])
    values["boundary_layer_height_m"] = max(50.0, values["boundary_layer_height_m"])

    timestamp = _to_timestamp(record.get("timestamp") or record.get("observed_at") or record.get("generated_at"))
    return FeatureVector(timestamp=timestamp, values=values)


def _derive(frame: pd.DataFrame) -> pd.DataFrame:
    timestamps = pd.to_datetime(frame["timestamp"], utc=True)
    # Indian Standard Time drives the diurnal cycle of traffic and boundary layer.
    local = timestamps.dt.tz_convert("Asia/Kolkata")
    hour = local.dt.hour + local.dt.minute / 60.0
    month = local.dt.month

    frame["hour_sin"] = np.sin(2 * np.pi * hour / 24.0)
    frame["hour_cos"] = np.cos(2 * np.pi * hour / 24.0)
    frame["month_sin"] = np.sin(2 * np.pi * (month - 1) / 12.0)
    frame["month_cos"] = np.cos(2 * np.pi * (month - 1) / 12.0)
    frame["day_of_week"] = local.dt.dayofweek.astype(float)
    frame["is_weekend"] = (frame["day_of_week"] >= 5).astype(float)
    frame["is_winter"] = month.isin([11, 12, 1, 2]).astype(float)

    # Satellite columns are tiny numbers in mol/m^2; scale to O(1) for readability.
    frame["no2_scaled"] = frame["no2_tropospheric_mol_m2"] * 1.0e5
    frame["co_scaled"] = frame["co_column_mol_m2"] * 1.0e2

    radians = np.deg2rad(frame["wind_direction_deg"])
    frame["wind_u"] = -frame["wind_speed_ms"] * np.sin(radians)
    frame["wind_v"] = -frame["wind_speed_ms"] * np.cos(radians)

    # Low wind, shallow boundary layer and no rain -> pollutants accumulate.
    frame["stagnation_index"] = (
        1.0 / (1.0 + frame["wind_speed_ms"]) * (1000.0 / frame["boundary_layer_height_m"].clip(lower=50.0))
    ) * np.exp(-frame["precipitation_mm"] / 2.0)

    frame["combustion_signal"] = (
        0.5 * frame["smoke_ratio"] + 0.3 * frame["open_burning_ratio"] + 0.2 * frame["industrial_emission_score"]
    )
    frame["log_report_count"] = np.log1p(frame["report_count"])
    return frame


def build_feature_frame(observations: Iterable[Mapping[str, Any] | FeatureVector]) -> pd.DataFrame:
    """Return a DataFrame with exactly ``FEATURE_COLUMNS`` in order."""
    rows: List[Dict[str, Any]] = []
    for item in observations:
        vector = item if isinstance(item, FeatureVector) else coerce_observation(item)
        rows.append(vector.as_row())
    if not rows:
        return pd.DataFrame(columns=FEATURE_COLUMNS)
    frame = pd.DataFrame(rows)
    frame = _derive(frame)
    return frame[FEATURE_COLUMNS].astype(float)


def confidence_score(report_count: float, vision_confidence: float, has_satellite: bool, has_weather: bool) -> float:
    """Heuristic forecast confidence in [0.3, 0.95] based on evidence density."""
    density = min(1.0, math.log1p(max(0.0, report_count)) / math.log1p(25.0))
    score = 0.3 + 0.35 * density + 0.15 * min(1.0, max(0.0, vision_confidence))
    if has_satellite:
        score += 0.1
    if has_weather:
        score += 0.05
    return round(min(0.95, max(0.3, score)), 3)


def category_for(aqi: float) -> str:
    """CPCB category key for a predicted AQI value."""
    if aqi <= 50:
        return "good"
    if aqi <= 100:
        return "satisfactory"
    if aqi <= 200:
        return "moderate"
    if aqi <= 300:
        return "poor"
    if aqi <= 400:
        return "very_poor"
    return "severe"


def describe_feature_columns() -> List[Dict[str, Optional[str]]]:
    """Human-readable feature documentation for the model info endpoint."""
    descriptions = {
        "haze_index": "Mean Gemini haze index across the cell (0 clear to 1 opaque).",
        "visibility_km": "Mean Gemini visibility estimate.",
        "smoke_ratio": "Share of reports with visible smoke.",
        "dust_ratio": "Share of reports with visible dust.",
        "open_burning_ratio": "Share of reports with open burning.",
        "fog_ratio": "Share of reports with fog or mist (moisture, not particulates).",
        "vision_aqi_estimate": "Mean Gemini AQI estimate.",
        "aer_ai": "Sentinel-5P UV aerosol index.",
        "no2_scaled": "Sentinel-5P tropospheric NO2 column, scaled by 1e5.",
        "co_scaled": "Sentinel-5P CO column, scaled by 1e2.",
        "aod_047": "MODIS MAIAC aerosol optical depth at 470 nm.",
        "stagnation_index": "Composite of low wind, shallow boundary layer and dry conditions.",
        "combustion_signal": "Weighted combination of smoke, burning and industrial cues.",
    }
    return [{"name": name, "description": descriptions.get(name)} for name in FEATURE_COLUMNS]
