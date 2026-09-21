"""Runtime configuration for the prediction service."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    project_id: str = os.environ.get("GCP_PROJECT_ID", "")
    model_path: str = os.environ.get("MODEL_PATH", "/app/model/model.joblib")
    model_gcs_uri: str = os.environ.get("MODEL_GCS_URI", "")
    prefer_gcs_model: bool = _bool("PREFER_GCS_MODEL", True)
    horizon_hours: int = int(os.environ.get("FORECAST_HORIZON_HOURS", "12"))
    max_batch_size: int = int(os.environ.get("MAX_BATCH_SIZE", "500"))
    log_level: str = os.environ.get("LOG_LEVEL", "INFO").upper()
    service_name: str = "vayusetu-prediction-service"


settings = Settings()
