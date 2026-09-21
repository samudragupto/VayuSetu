"""Unit tests for the batch prediction function."""

from __future__ import annotations

import datetime as dt
import json
import types
from typing import Any, Dict, List

import main
import pytest
import responses
from data_sources import filter_valid
from pipeline import (
    aggregate_by_cell,
    build_hotspot_documents,
    build_prediction_request,
    enrich_with_weather,
    hotspot_to_bigquery_row,
)
from prediction_client import PredictionClient, PredictionServiceError
from weather import OpenMeteoWeatherProvider, SyntheticWeatherProvider

NOW = dt.datetime(2026, 11, 2, 6, 0, tzinfo=dt.timezone.utc)


def _obs(report_id: str, lat: float, lon: float, haze: float, aqi: float, smoke: bool = False, sources: List[str] | None = None) -> Dict[str, Any]:
    return {
        "report_id": report_id,
        "timestamp": NOW - dt.timedelta(minutes=30),
        "latitude": lat,
        "longitude": lon,
        "geohash": None,
        "city": "New Delhi",
        "haze_index": haze,
        "visibility_km": 2.0,
        "smoke_detected": smoke,
        "dust_detected": False,
        "open_burning_detected": False,
        "fog_or_mist_detected": False,
        "vehicle_density_score": 0.7,
        "construction_activity_score": 0.2,
        "industrial_emission_score": 0.1,
        "estimated_aqi": aqi,
        "vision_confidence": 0.8,
        "pollution_sources": sources or ["vehicular"],
        "aer_ai": 2.1,
        "no2_tropospheric_mol_m2": 0.00012,
        "co_column_mol_m2": 0.04,
        "aod_047": 0.9,
    }


def test_filter_valid_drops_incomplete() -> None:
    good = _obs("a", 28.6, 77.2, 0.5, 200)
    no_loc = dict(good, latitude=None)
    no_signal = dict(good, haze_index=None, estimated_aqi=None)
    assert filter_valid([good, no_loc, no_signal]) == [good]


def test_aggregate_by_cell_groups_and_averages() -> None:
    observations = [
        _obs("a", 28.6139, 77.2090, 0.8, 300, smoke=True, sources=["vehicular", "crop_residue_burning"]),
        _obs("b", 28.6150, 77.2100, 0.6, 260, sources=["vehicular"]),
        _obs("c", 19.0760, 72.8777, 0.2, 90),
    ]
    aggregates = aggregate_by_cell(observations, precision=5, reference_time=NOW)
    assert len(aggregates) == 2
    delhi = aggregates[0]
    assert delhi.report_count == 2
    assert delhi.features["haze_index"] == pytest.approx(0.7)
    assert delhi.features["smoke_ratio"] == 0.5
    assert delhi.dominant_sources[0] == "vehicular"
    assert delhi.has_satellite is True
    assert delhi.geohash == "ttnfu"


def test_weather_enrichment_and_request_shape() -> None:
    aggregates = aggregate_by_cell([_obs("a", 28.6139, 77.2090, 0.5, 200)], precision=5, reference_time=NOW)
    assert enrich_with_weather(aggregates, SyntheticWeatherProvider()) == 1
    request = build_prediction_request(aggregates)
    features = request["observations"][0]["features"]
    assert "wind_speed_ms" in features and "boundary_layer_height_m" in features
    assert request["observations"][0]["geohash"] == "ttnfu"


def test_build_hotspot_documents_flags_alerts() -> None:
    aggregates = aggregate_by_cell([_obs("a", 28.6139, 77.2090, 0.9, 350)], precision=5, reference_time=NOW)
    predictions = [{"geohash": "ttnfu", "predicted_aqi": 341.2, "predicted_category": "very_poor", "confidence": 0.7, "model_version": "xgb-1", "forecast_for": (NOW + dt.timedelta(hours=12)).isoformat(), "horizon_hours": 12}]
    docs = build_hotspot_documents(aggregates, predictions, NOW, alert_threshold=300, weather_source="synthetic")
    assert docs[0]["_id"] == "ttnfu_20261102T0600"
    assert docs[0]["alertStatus"] == "pending"
    row = hotspot_to_bigquery_row(docs[0])
    assert row["alert_triggered"] is True and json.loads(row["features"])["haze_index"] == 0.9


@responses.activate
def test_open_meteo_provider_parses_and_caches() -> None:
    responses.add(
        responses.GET,
        OpenMeteoWeatherProvider.BASE_URL,
        json={
            "current": {"temperature_2m": 18.5, "relative_humidity_2m": 70, "precipitation": 0, "surface_pressure": 1015, "wind_speed_10m": 1.2, "wind_direction_10m": 300},
            "hourly": {"time": ["2026-11-02T06:00"], "boundary_layer_height": [240.0]},
        },
        status=200,
    )
    provider = OpenMeteoWeatherProvider()
    weather = provider.current(28.61, 77.21, NOW)
    assert weather["boundary_layer_height_m"] == 240.0 and weather["wind_speed_ms"] == 1.2
    provider.current(28.62, 77.22, NOW)  # same 0.25 degree cell -> cached
    assert len(responses.calls) == 1


@responses.activate
def test_open_meteo_falls_back_on_error() -> None:
    responses.add(responses.GET, OpenMeteoWeatherProvider.BASE_URL, status=500)
    provider = OpenMeteoWeatherProvider()
    weather = provider.current(28.61, 77.21, NOW)
    assert set(weather) >= {"temperature_c", "wind_speed_ms"}


@responses.activate
def test_prediction_client_success_and_retry() -> None:
    responses.add(responses.POST, "http://predict.local/predict", status=503)
    responses.add(responses.POST, "http://predict.local/predict", json={"predictions": [], "model_version": "v"}, status=200)
    client = PredictionClient("http://predict.local", use_auth=False)
    body = client.predict({"observations": []})
    assert body["model_version"] == "v" and len(responses.calls) == 2


@responses.activate
def test_prediction_client_permanent_error() -> None:
    responses.add(responses.POST, "http://predict.local/predict", status=422, json={"detail": "bad"})
    client = PredictionClient("http://predict.local", use_auth=False)
    with pytest.raises(PredictionServiceError):
        client.predict({"observations": []})
    assert len(responses.calls) == 1


def test_run_batch_prediction_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEATHER_PROVIDER", "synthetic")
    monkeypatch.setenv("ALERT_AQI_THRESHOLD", "300")
    written: Dict[str, Any] = {}

    monkeypatch.setattr(main, "load_observations", lambda since, until: ([_obs("a", 28.6139, 77.2090, 0.9, 350), _obs("b", 28.6150, 77.2100, 0.85, 330)], "test"))

    class _Client:
        def predict(self, payload: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "model_version": "xgb-test",
                "predictions": [
                    {"geohash": o["geohash"], "predicted_aqi": 355.0, "predicted_category": "very_poor", "confidence": 0.8, "horizon_hours": 12, "forecast_for": (NOW + dt.timedelta(hours=12)).isoformat()}
                    for o in payload["observations"]
                ],
            }

    monkeypatch.setattr(main, "get_prediction_client", lambda: _Client())
    monkeypatch.setattr(main, "write_hotspots", lambda docs: written.setdefault("docs", docs) and len(docs))
    monkeypatch.setattr(main, "record_run", lambda summary: written.setdefault("run", summary))

    summary = main.run_batch_prediction(lookback_hours=6, reference_time=NOW)

    assert summary["cells"] == 1 and summary["hotspots_written"] == 1
    assert summary["alerts_pending"] == 1 and summary["max_predicted_aqi"] == 355.0
    assert written["docs"][0]["reportCount"] == 2
    assert written["run"]["observation_source"] == "test"


def test_run_batch_prediction_dry_run_without_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "load_observations", lambda since, until: ([], "bigquery"))
    monkeypatch.setattr(main, "record_run", lambda summary: None)
    summary = main.run_batch_prediction(lookback_hours=3, dry_run=True, reference_time=NOW)
    assert summary["hotspots_written"] == 0 and summary["cells"] == 0


def test_http_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    from flask import Flask

    monkeypatch.setattr(main, "run_batch_prediction", lambda lookback_hours=None, dry_run=False: {"generated_at": NOW.isoformat(), "cells": 0, "lookback": lookback_hours, "dry_run": dry_run})
    app = Flask(__name__)
    with app.test_request_context("/?lookback_hours=2&dry_run=true", method="POST", json={}):
        from flask import request

        body, status = main.batch_predict(request)
        assert status == 200
        payload = body.get_json()
        assert payload["status"] == "ok" and payload["lookback"] == 2 and payload["dry_run"] is True

    def _boom(**kwargs: Any) -> None:
        raise RuntimeError("prediction down")

    monkeypatch.setattr(main, "run_batch_prediction", _boom)
    with app.test_request_context("/", method="POST", json={}):
        from flask import request

        body, status = main.batch_predict(request)
        assert status == 500 and "prediction down" in body.get_json()["error"]


def test_firestore_observation_source_maps_documents() -> None:
    from data_sources import FirestoreObservationSource

    doc = types.SimpleNamespace(
        id="r9",
        to_dict=lambda: {
            "status": "analyzed",
            "createdAt": NOW,
            "location": types.SimpleNamespace(latitude=28.6, longitude=77.2),
            "geohash": "ttnfucj",
            "city": "New Delhi",
            "geminiAnalysis": {"haze_index": 0.7, "estimated_aqi": 280, "confidence": 0.7, "pollution_sources": ["vehicular"], "smoke_detected": True},
            "satelliteMetrics": {"aerAi": 1.9, "aod047": 0.8},
        },
    )

    class _Query:
        def where(self, **kwargs: Any) -> "_Query":  # noqa: ARG002
            return self

        def limit(self, n: int) -> "_Query":  # noqa: ARG002
            return self

        def stream(self):  # noqa: ANN201
            yield doc

    client = types.SimpleNamespace(collection=lambda name: _Query())  # noqa: ARG005
    observations = FirestoreObservationSource(client).fetch(NOW - dt.timedelta(hours=1), NOW)
    assert observations[0]["report_id"] == "r9"
    assert observations[0]["aer_ai"] == 1.9 and observations[0]["smoke_detected"] is True
