"""API tests for the prediction service."""

from __future__ import annotations

import datetime as dt

import pytest


def _observation(**features):  # noqa: ANN003
    return {
        "geohash": "ttnfu",
        "latitude": 28.61,
        "longitude": 77.21,
        "timestamp": dt.datetime(2026, 11, 2, 6, 0, tzinfo=dt.timezone.utc).isoformat(),
        "city": "New Delhi",
        "features": features,
    }


def test_health_reports_loaded_model(client) -> None:  # noqa: ANN001
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok" and body["model_loaded"] is True
    assert body["model_version"] == "test-xgb"


def test_model_info(client) -> None:  # noqa: ANN001
    body = client.get("/model/info").json()
    assert body["model_version"] == "test-xgb"
    assert "haze_index" in body["feature_columns"]
    assert body["horizon_hours"] == 12
    assert body["metrics"]["rows_validation"] > 0


def test_predict_returns_forecast(client) -> None:  # noqa: ANN001
    payload = {
        "observations": [
            _observation(haze_index=0.9, visibility_km=0.8, aod_047=1.3, wind_speed_ms=0.5, report_count=14, vision_aqi_estimate=360, vision_confidence=0.8, aer_ai=2.5),
            _observation(haze_index=0.1, visibility_km=12, aod_047=0.1, wind_speed_ms=6, report_count=2, vision_aqi_estimate=45),
        ],
        "include_features": True,
    }
    response = client.post("/predict", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model_version"] == "test-xgb"
    first, second = body["predictions"]
    assert first["predicted_aqi"] > second["predicted_aqi"]
    assert first["predicted_category"] in {"poor", "very_poor", "severe", "moderate"}
    assert first["confidence"] > second["confidence"]
    assert first["horizon_hours"] == 12
    assert first["features"]["haze_index"] == 0.9
    assert first["forecast_for"].startswith("2026-11-02T18:00")


def test_predict_validates_input(client) -> None:  # noqa: ANN001
    response = client.post("/predict", json={"observations": []})
    assert response.status_code == 422
    bad = _observation(haze_index=7)
    response = client.post("/predict", json={"observations": [bad]})
    assert response.status_code == 422


def test_predict_without_model_returns_503(model_path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    from fastapi.testclient import TestClient

    from app import main as service_main

    monkeypatch.setattr(service_main.model_store, "model_path", "/nonexistent/model.joblib")
    monkeypatch.setattr(service_main.model_store, "model_gcs_uri", "")
    monkeypatch.setattr(service_main.model_store, "_loaded", None)
    with TestClient(service_main.app) as client:
        assert client.get("/healthz").json()["status"] == "degraded"
        response = client.post("/predict", json={"observations": [_observation()]})
        assert response.status_code == 503
        # Reload after restoring the path recovers the service.
        monkeypatch.setattr(service_main.model_store, "model_path", model_path)
        assert client.post("/model/reload").json()["model_loaded"] is True
