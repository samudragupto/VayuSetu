"""Request and response models for the prediction API."""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ObservationFeatures(BaseModel):
    """Fused cell-level features. Every field is optional; missing values are imputed."""

    model_config = ConfigDict(extra="ignore")

    # Gemini vision (cell averages)
    haze_index: Optional[float] = Field(None, ge=0, le=1)
    visibility_km: Optional[float] = Field(None, ge=0, le=100)
    smoke_ratio: Optional[float] = Field(None, ge=0, le=1)
    dust_ratio: Optional[float] = Field(None, ge=0, le=1)
    open_burning_ratio: Optional[float] = Field(None, ge=0, le=1)
    fog_ratio: Optional[float] = Field(None, ge=0, le=1)
    vehicle_density_score: Optional[float] = Field(None, ge=0, le=1)
    construction_activity_score: Optional[float] = Field(None, ge=0, le=1)
    industrial_emission_score: Optional[float] = Field(None, ge=0, le=1)
    vision_aqi_estimate: Optional[float] = Field(None, ge=0, le=500)
    vision_confidence: Optional[float] = Field(None, ge=0, le=1)
    report_count: Optional[float] = Field(None, ge=0)
    # Satellite
    aer_ai: Optional[float] = None
    no2_tropospheric_mol_m2: Optional[float] = Field(None, ge=0)
    co_column_mol_m2: Optional[float] = Field(None, ge=0)
    aod_047: Optional[float] = Field(None, ge=0)
    # Weather
    temperature_c: Optional[float] = Field(None, ge=-30, le=60)
    humidity_pct: Optional[float] = Field(None, ge=0, le=100)
    wind_speed_ms: Optional[float] = Field(None, ge=0, le=80)
    wind_direction_deg: Optional[float] = Field(None, ge=0, le=360)
    precipitation_mm: Optional[float] = Field(None, ge=0)
    pressure_hpa: Optional[float] = Field(None, ge=800, le=1100)
    boundary_layer_height_m: Optional[float] = Field(None, ge=0)


class Observation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    geohash: str = Field(..., min_length=1, max_length=12, description="Aggregation cell identifier")
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    timestamp: dt.datetime = Field(..., description="Observation time (UTC)")
    city: Optional[str] = None
    features: ObservationFeatures = Field(default_factory=ObservationFeatures)

    @field_validator("timestamp")
    @classmethod
    def _ensure_tz(cls, value: dt.datetime) -> dt.datetime:
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


class PredictRequest(BaseModel):
    observations: List[Observation] = Field(..., min_length=1)
    include_features: bool = Field(False, description="Echo the engineered feature vector in each prediction")


class Prediction(BaseModel):
    geohash: str
    latitude: float
    longitude: float
    city: Optional[str] = None
    observed_at: dt.datetime
    forecast_for: dt.datetime
    horizon_hours: int
    predicted_aqi: float
    predicted_category: str
    current_aqi_estimate: Optional[float] = None
    confidence: float
    model_version: str
    features: Optional[Dict[str, float]] = None


class PredictResponse(BaseModel):
    predictions: List[Prediction]
    model_version: str
    generated_at: dt.datetime


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    model_version: Optional[str] = None
    model_source: Optional[str] = None


class ModelInfoResponse(BaseModel):
    model_version: str
    model_source: str
    format_version: int
    feature_columns: List[str]
    feature_descriptions: List[Dict[str, Any]]
    metrics: Dict[str, Any]
    hyperparameters: Dict[str, Any]
    library_versions: Optional[Dict[str, str]] = None
    horizon_hours: int
