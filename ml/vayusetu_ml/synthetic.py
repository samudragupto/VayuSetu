"""Synthetic data generation for training, testing and demonstrations.

The generator encodes a simplified but physically motivated model of urban air
pollution in Indian cities: seasonal baselines, diurnal traffic cycles, wind and
rain dispersion, boundary layer trapping, biomass burning episodes and the
relationship between haze, aerosol optical depth and PM2.5. It is deliberately
noisy so that the resulting XGBoost model learns robust rather than trivial
relationships.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional

import numpy as np

from vayusetu_ml.features import TARGET_COLUMN


@dataclass(frozen=True)
class City:
    name: str
    latitude: float
    longitude: float
    baseline_aqi: float
    winter_multiplier: float
    industrial_share: float


INDIAN_CITIES: List[City] = [
    City("New Delhi", 28.6139, 77.2090, 190.0, 1.9, 0.25),
    City("Ghaziabad", 28.6692, 77.4538, 205.0, 1.9, 0.35),
    City("Kanpur", 26.4499, 80.3319, 175.0, 1.8, 0.40),
    City("Lucknow", 26.8467, 80.9462, 165.0, 1.8, 0.20),
    City("Patna", 25.5941, 85.1376, 170.0, 1.7, 0.15),
    City("Kolkata", 22.5726, 88.3639, 140.0, 1.5, 0.30),
    City("Mumbai", 19.0760, 72.8777, 105.0, 1.3, 0.30),
    City("Pune", 18.5204, 73.8567, 95.0, 1.3, 0.20),
    City("Ahmedabad", 23.0225, 72.5714, 130.0, 1.4, 0.35),
    City("Jaipur", 26.9124, 75.7873, 135.0, 1.5, 0.15),
    City("Hyderabad", 17.3850, 78.4867, 95.0, 1.2, 0.25),
    City("Bengaluru", 12.9716, 77.5946, 80.0, 1.1, 0.15),
    City("Chennai", 13.0827, 80.2707, 85.0, 1.1, 0.30),
    City("Chandigarh", 30.7333, 76.7794, 125.0, 1.7, 0.10),
]


def _season_factor(month: int, winter_multiplier: float) -> float:
    """Return a seasonal multiplier peaking in November-January."""
    # Cosine centred on mid-December (month 12).
    phase = (month - 12) / 12.0 * 2 * math.pi
    winter_weight = (math.cos(phase) + 1.0) / 2.0  # 1.0 in December, ~0 in June
    monsoon_penalty = 0.55 if month in (7, 8, 9) else 1.0
    return (1.0 + (winter_multiplier - 1.0) * winter_weight) * monsoon_penalty


def _diurnal_factor(hour: float) -> float:
    """Traffic peaks and nocturnal boundary layer trapping."""
    morning = math.exp(-((hour - 8.5) ** 2) / 6.0)
    evening = math.exp(-((hour - 20.0) ** 2) / 8.0)
    night_trap = 0.25 if hour < 6 or hour >= 22 else 0.0
    return 0.85 + 0.35 * morning + 0.45 * evening + night_trap


class SyntheticObservationGenerator:
    """Generate fused observations with a 12-hour-ahead AQI label."""

    def __init__(self, seed: int = 42, cities: Optional[List[City]] = None) -> None:
        self.rng = np.random.default_rng(seed)
        self.cities = cities or INDIAN_CITIES

    def _weather(self, city: City, timestamp: dt.datetime, severity: float) -> Dict[str, float]:
        month = timestamp.month
        hour = timestamp.hour
        is_monsoon = month in (6, 7, 8, 9)
        winter = month in (11, 12, 1, 2)
        base_temp = 14.0 if winter else (30.0 if not is_monsoon else 28.0)
        temp = base_temp + 6.0 * math.sin((hour - 9) / 24 * 2 * math.pi) + self.rng.normal(0, 2.0)
        temp += (28.0 - abs(city.latitude)) * 0.2
        humidity = (85.0 if is_monsoon else (60.0 if winter else 40.0)) + self.rng.normal(0, 8.0)
        wind = max(0.1, self.rng.gamma(2.0, 1.4) * (0.6 if winter else 1.0))
        rain = float(self.rng.exponential(4.0)) if (is_monsoon and self.rng.random() < 0.45) else (float(self.rng.exponential(1.0)) if self.rng.random() < 0.05 else 0.0)
        blh = max(80.0, (350.0 if winter else 900.0) * (0.5 if hour < 7 or hour > 20 else 1.4) + self.rng.normal(0, 120.0))
        pressure = 1012.0 + (6.0 if winter else -4.0) + self.rng.normal(0, 2.0)
        return {
            "temperature_c": round(temp, 1),
            "humidity_pct": round(min(100.0, max(5.0, humidity)), 1),
            "wind_speed_ms": round(wind, 2),
            "wind_direction_deg": round(float(self.rng.uniform(0, 360)), 1),
            "precipitation_mm": round(rain, 2),
            "pressure_hpa": round(pressure, 1),
            "boundary_layer_height_m": round(blh, 0),
        }

    def _current_aqi(self, city: City, timestamp: dt.datetime, weather: Dict[str, float], episode: float) -> float:
        season = _season_factor(timestamp.month, city.winter_multiplier)
        diurnal = _diurnal_factor(timestamp.hour + timestamp.minute / 60.0)
        dispersion = 1.0 / (1.0 + 0.25 * weather["wind_speed_ms"])
        rain_washout = math.exp(-weather["precipitation_mm"] / 3.0)
        trapping = math.sqrt(1000.0 / weather["boundary_layer_height_m"])
        aqi = city.baseline_aqi * season * diurnal * (0.6 + 0.8 * dispersion) * (0.5 + 0.5 * rain_washout) * (0.7 + 0.5 * trapping)
        aqi *= 1.0 + episode
        aqi *= float(self.rng.lognormal(0.0, 0.12))
        return float(min(500.0, max(15.0, aqi)))

    def _vision_metrics(self, aqi: float, weather: Dict[str, float], city: City, episode: float) -> Dict[str, float]:
        haze = min(1.0, max(0.0, aqi / 480.0 + self.rng.normal(0, 0.06)))
        visibility = max(0.2, 14.0 * math.exp(-aqi / 130.0) + self.rng.normal(0, 0.6))
        humid_fog = 1.0 if (weather["humidity_pct"] > 88 and weather["temperature_c"] < 16 and self.rng.random() < 0.6) else 0.0
        smoke = float(np.clip(episode * 0.9 + self.rng.normal(0.05, 0.08), 0.0, 1.0))
        burning = float(np.clip(episode * 0.7 + self.rng.normal(0.0, 0.05), 0.0, 1.0))
        dust = float(np.clip(0.15 + 0.3 * (aqi > 200) + self.rng.normal(0, 0.1), 0.0, 1.0))
        return {
            "haze_index": round(haze, 3),
            "visibility_km": round(visibility, 2),
            "smoke_ratio": round(smoke, 3),
            "dust_ratio": round(dust, 3),
            "open_burning_ratio": round(burning, 3),
            "fog_ratio": humid_fog,
            "vehicle_density_score": round(float(np.clip(self.rng.beta(4, 3), 0, 1)), 3),
            "construction_activity_score": round(float(np.clip(self.rng.beta(2, 5), 0, 1)), 3),
            "industrial_emission_score": round(float(np.clip(city.industrial_share + self.rng.normal(0, 0.1), 0, 1)), 3),
            "vision_aqi_estimate": round(float(np.clip(aqi * self.rng.normal(1.0, 0.18), 0, 500)), 1),
            "vision_confidence": round(float(np.clip(self.rng.beta(6, 2.5), 0.05, 1.0)), 3),
        }

    def _satellite_metrics(self, aqi: float, episode: float, city: City) -> Dict[str, float]:
        aod = max(0.05, 0.12 + aqi / 320.0 + self.rng.normal(0, 0.12))
        aer_ai = -0.6 + 2.2 * (aqi / 300.0) + 1.5 * episode + self.rng.normal(0, 0.35)
        no2 = max(1e-6, (3e-5 + 1.6e-4 * (aqi / 300.0)) * (0.8 + 0.6 * city.industrial_share) * self.rng.lognormal(0, 0.2))
        co = max(0.005, (0.028 + 0.03 * (aqi / 300.0) + 0.02 * episode) * self.rng.lognormal(0, 0.12))
        return {
            "aod_047": round(aod, 4),
            "aer_ai": round(aer_ai, 3),
            "no2_tropospheric_mol_m2": round(no2, 8),
            "co_column_mol_m2": round(co, 6),
        }

    def generate(self, rows: int, start: Optional[dt.datetime] = None, days: int = 365) -> Iterator[Dict[str, Any]]:
        """Yield ``rows`` observation dictionaries including the 12-hour target."""
        start = start or dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
        for _ in range(rows):
            city = self.cities[int(self.rng.integers(0, len(self.cities)))]
            offset_hours = float(self.rng.uniform(0, days * 24))
            timestamp = start + dt.timedelta(hours=offset_hours)
            # Biomass burning episodes cluster in October-November in the north.
            episode_prob = 0.25 if (timestamp.month in (10, 11) and city.latitude > 24) else 0.05
            episode = float(self.rng.beta(2, 4)) if self.rng.random() < episode_prob else 0.0

            weather_now = self._weather(city, timestamp, episode)
            aqi_now = self._current_aqi(city, timestamp, weather_now, episode)

            future = timestamp + dt.timedelta(hours=12)
            weather_future = self._weather(city, future, episode)
            # Episodes persist with decay; weather changes drive the 12-hour delta.
            future_episode = episode * float(self.rng.uniform(0.6, 1.1))
            aqi_future = self._current_aqi(city, future, weather_future, future_episode)
            aqi_12h = 0.55 * aqi_future + 0.45 * aqi_now * float(self.rng.normal(1.0, 0.05))

            lat = city.latitude + float(self.rng.normal(0, 0.08))
            lon = city.longitude + float(self.rng.normal(0, 0.08))
            report_count = int(max(1, self.rng.poisson(4) + (6 if aqi_now > 250 else 0)))

            record: Dict[str, Any] = {
                "timestamp": timestamp.isoformat(),
                "city": city.name,
                "latitude": round(lat, 5),
                "longitude": round(lon, 5),
                "report_count": report_count,
                "current_aqi": round(aqi_now, 1),
                TARGET_COLUMN: round(float(min(500.0, max(10.0, aqi_12h))), 1),
            }
            record.update(self._vision_metrics(aqi_now, weather_now, city, episode))
            record.update(self._satellite_metrics(aqi_now, episode, city))
            record.update(weather_now)
            yield record

    def generate_frame(self, rows: int, **kwargs: Any):  # noqa: ANN201 - pandas import kept lazy for callers
        import pandas as pd

        return pd.DataFrame(list(self.generate(rows, **kwargs)))
