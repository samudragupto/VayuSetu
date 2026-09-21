"""Tests for the shared ML library and the training CLI."""

from __future__ import annotations

import datetime as dt
import json
import os

import numpy as np
import pandas as pd
import pytest

from vayusetu_ml.features import (
    FEATURE_COLUMNS,
    TARGET_COLUMN,
    build_feature_frame,
    category_for,
    coerce_observation,
    confidence_score,
)
from vayusetu_ml.synthetic import SyntheticObservationGenerator
from vayusetu_ml.training import load_bundle, save_bundle, train_model


def test_coerce_observation_imputes_and_clamps() -> None:
    vector = coerce_observation({"haze_index": 4.0, "visibility_km": -1, "report_count": 0, "timestamp": "2026-11-02T06:00:00Z"})
    assert vector.values["haze_index"] == 1.0
    assert vector.values["visibility_km"] == 0.0
    assert vector.values["report_count"] == 1.0
    assert vector.values["aer_ai"] == 0.8  # default imputed
    assert vector.timestamp.tzinfo is not None


def test_feature_frame_has_exact_columns() -> None:
    frame = build_feature_frame([{"timestamp": dt.datetime(2026, 1, 15, 3, 30, tzinfo=dt.timezone.utc), "wind_speed_ms": 1.0}])
    assert list(frame.columns) == FEATURE_COLUMNS
    assert frame.shape == (1, len(FEATURE_COLUMNS))
    assert frame.loc[0, "is_winter"] == 1.0
    # 03:30 UTC is 09:00 IST -> hour_sin positive, hour_cos negative-ish region
    assert frame.loc[0, "hour_sin"] > 0.5
    assert np.isfinite(frame.values).all()


def test_empty_frame() -> None:
    frame = build_feature_frame([])
    assert list(frame.columns) == FEATURE_COLUMNS and frame.empty


def test_confidence_and_category() -> None:
    assert confidence_score(1, 0.5, False, False) < confidence_score(30, 0.9, True, True)
    assert category_for(320) == "very_poor" and category_for(20) == "good"


def test_synthetic_generator_is_reproducible_and_seasonal() -> None:
    a = SyntheticObservationGenerator(seed=7).generate_frame(300)
    b = SyntheticObservationGenerator(seed=7).generate_frame(300)
    pd.testing.assert_frame_equal(a, b)
    a["month"] = pd.to_datetime(a["timestamp"]).dt.month
    winter = a[a["month"].isin([11, 12, 1])][TARGET_COLUMN].mean()
    monsoon = a[a["month"].isin([7, 8])][TARGET_COLUMN].mean()
    assert winter > monsoon
    assert a[TARGET_COLUMN].between(10, 500).all()


@pytest.fixture(scope="module")
def trained_bundle():
    frame = SyntheticObservationGenerator(seed=3).generate_frame(1500)
    return train_model(frame, hyperparameters={"n_estimators": 80, "max_depth": 4, "learning_rate": 0.1}, model_version="test-model")


def test_training_produces_reasonable_metrics(trained_bundle) -> None:
    metrics = trained_bundle.metrics
    assert metrics["rows_validation"] > 0
    assert metrics["mae"] < 60
    assert metrics["r2"] > 0.5
    assert trained_bundle.feature_columns == FEATURE_COLUMNS


def test_bundle_round_trip(tmp_path, trained_bundle) -> None:
    path = os.path.join(tmp_path, "model.joblib")
    save_bundle(trained_bundle, path)
    loaded = load_bundle(path)
    assert loaded.model_version == "test-model"
    frame = build_feature_frame([{"timestamp": "2026-11-02T06:00:00Z", "haze_index": 0.9, "wind_speed_ms": 0.5}])
    prediction = loaded.predict(frame)
    assert prediction.shape == (1,)
    assert 0 <= prediction[0] <= 500
    with open(os.path.join(tmp_path, "model_metrics.json"), encoding="utf-8") as handle:
        sidecar = json.load(handle)
    assert sidecar["model_version"] == "test-model"
    assert sidecar["feature_importance"]


def test_high_haze_predicts_worse_air(trained_bundle) -> None:
    clean = {"timestamp": "2026-12-02T02:00:00Z", "haze_index": 0.1, "visibility_km": 12, "aod_047": 0.15, "wind_speed_ms": 5, "vision_aqi_estimate": 60}
    dirty = {"timestamp": "2026-12-02T02:00:00Z", "haze_index": 0.95, "visibility_km": 0.6, "aod_047": 1.4, "wind_speed_ms": 0.4, "vision_aqi_estimate": 380, "smoke_ratio": 0.8}
    preds = trained_bundle.predict(build_feature_frame([clean, dirty]))
    assert preds[1] > preds[0]


def test_cli_synthetic(tmp_path) -> None:
    import train_xgboost_model

    output = os.path.join(tmp_path, "model.joblib")
    code = train_xgboost_model.main(["--source", "synthetic", "--rows", "800", "--n-estimators", "60", "--output", output, "--log-level", "WARNING"])
    assert code == 0
    assert os.path.exists(output)
