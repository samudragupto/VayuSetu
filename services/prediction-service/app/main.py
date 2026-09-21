"""VayuSetu prediction service.

A FastAPI application serving 12-hour AQI forecasts from a pre-trained XGBoost
regressor. Deployed as a private Cloud Run service; only the batch prediction
Cloud Function holds the invoker role.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, List

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.config import settings
from app.model_store import ModelStore
from app.schemas import HealthResponse, ModelInfoResponse, Prediction, PredictRequest, PredictResponse
from vayusetu_ml.features import (
    FEATURE_COLUMNS,
    build_feature_frame,
    category_for,
    confidence_score,
    describe_feature_columns,
)

# ---------------------------------------------------------------------------
# Logging (structured for Cloud Logging)
# ---------------------------------------------------------------------------


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "service": settings.service_name,
            "timestamp": dt.datetime.fromtimestamp(record.created, tz=dt.timezone.utc).isoformat(),
        }
        for key in ("batch_size", "latency_ms", "model_version", "path", "status_code"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level)
    logging.getLogger("uvicorn.access").disabled = True


_configure_logging()
logger = logging.getLogger("prediction-service")

model_store = ModelStore(
    model_path=settings.model_path,
    model_gcs_uri=settings.model_gcs_uri,
    prefer_gcs=settings.prefer_gcs_model,
    project_id=settings.project_id,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    model_store.load()
    yield


app = FastAPI(
    title="VayuSetu Prediction Service",
    description="12-hour hyper-local AQI forecasts from fused citizen, satellite and weather signals.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def access_log(request: Request, call_next):  # type: ignore[no-untyped-def]
    started = time.monotonic()
    response = await call_next(request)
    logger.info(
        "%s %s -> %d",
        request.method,
        request.url.path,
        response.status_code,
        extra={"path": request.url.path, "status_code": response.status_code, "latency_ms": int((time.monotonic() - started) * 1000)},
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal error", "type": type(exc).__name__})


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/healthz", response_model=HealthResponse, tags=["operations"])
def healthz() -> HealthResponse:
    loaded = model_store.loaded
    return HealthResponse(
        status="ok" if loaded else "degraded",
        model_loaded=loaded is not None,
        model_version=loaded.bundle.model_version if loaded else None,
        model_source=loaded.source if loaded else model_store.last_error,
    )


@app.post("/model/reload", response_model=HealthResponse, tags=["operations"])
def reload_model() -> HealthResponse:
    """Re-read the model artifact (used after a new model is published to Cloud Storage)."""
    model_store.load()
    return healthz()


@app.get("/model/info", response_model=ModelInfoResponse, tags=["model"])
def model_info() -> ModelInfoResponse:
    loaded = model_store.loaded
    if loaded is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"model not loaded: {model_store.last_error}")
    bundle = loaded.bundle
    return ModelInfoResponse(
        model_version=bundle.model_version,
        model_source=loaded.source,
        format_version=bundle.format_version,
        feature_columns=bundle.feature_columns,
        feature_descriptions=describe_feature_columns(),
        metrics=bundle.metrics,
        hyperparameters={k: v for k, v in bundle.hyperparameters.items() if k != "n_jobs"},
        library_versions=bundle.library_versions,
        horizon_hours=settings.horizon_hours,
    )


@app.post("/predict", response_model=PredictResponse, tags=["model"])
def predict(request: PredictRequest) -> PredictResponse:
    loaded = model_store.loaded
    if loaded is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"model not loaded: {model_store.last_error}")
    if len(request.observations) > settings.max_batch_size:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=f"batch exceeds {settings.max_batch_size} observations")

    started = time.monotonic()
    records: List[Dict[str, object]] = []
    for observation in request.observations:
        record: Dict[str, object] = observation.features.model_dump(exclude_none=True)
        record.update({"timestamp": observation.timestamp, "latitude": observation.latitude, "longitude": observation.longitude})
        records.append(record)

    frame = build_feature_frame(records)
    try:
        raw_predictions = loaded.bundle.predict(frame)
    except Exception as exc:  # noqa: BLE001 - surface as a client-visible error with context
        logger.exception("Model inference failed")
        raise HTTPException(status_code=500, detail=f"inference failed: {exc}") from exc

    generated_at = dt.datetime.now(tz=dt.timezone.utc)
    predictions: List[Prediction] = []
    for observation, value, (_, feature_row) in zip(request.observations, raw_predictions, frame.iterrows(), strict=True):
        features = observation.features
        has_satellite = any(getattr(features, name) is not None for name in ("aer_ai", "no2_tropospheric_mol_m2", "aod_047"))
        has_weather = any(getattr(features, name) is not None for name in ("wind_speed_ms", "temperature_c", "boundary_layer_height_m"))
        predicted = float(round(value, 1))
        predictions.append(
            Prediction(
                geohash=observation.geohash,
                latitude=observation.latitude,
                longitude=observation.longitude,
                city=observation.city,
                observed_at=observation.timestamp,
                forecast_for=observation.timestamp + dt.timedelta(hours=settings.horizon_hours),
                horizon_hours=settings.horizon_hours,
                predicted_aqi=predicted,
                predicted_category=category_for(predicted),
                current_aqi_estimate=features.vision_aqi_estimate,
                confidence=confidence_score(features.report_count or 1.0, features.vision_confidence or 0.6, has_satellite, has_weather),
                model_version=loaded.bundle.model_version,
                features={name: float(feature_row[name]) for name in FEATURE_COLUMNS} if request.include_features else None,
            )
        )

    logger.info(
        "Generated %d prediction(s)",
        len(predictions),
        extra={"batch_size": len(predictions), "latency_ms": int((time.monotonic() - started) * 1000), "model_version": loaded.bundle.model_version},
    )
    return PredictResponse(predictions=predictions, model_version=loaded.bundle.model_version, generated_at=generated_at)
