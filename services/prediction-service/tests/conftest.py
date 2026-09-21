"""Test fixtures: train a tiny model and point the service at it."""

from __future__ import annotations

import os
import sys

_SERVICE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(os.path.dirname(_SERVICE_DIR))
for path in (_SERVICE_DIR, os.path.join(_REPO_ROOT, "ml")):
    if path not in sys.path:
        sys.path.insert(0, path)

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def model_path(tmp_path_factory: pytest.TempPathFactory) -> str:
    from vayusetu_ml.synthetic import SyntheticObservationGenerator
    from vayusetu_ml.training import save_bundle, train_model

    frame = SyntheticObservationGenerator(seed=11).generate_frame(900)
    bundle = train_model(frame, hyperparameters={"n_estimators": 60, "max_depth": 4, "learning_rate": 0.1}, model_version="test-xgb")
    path = str(tmp_path_factory.mktemp("model") / "model.joblib")
    save_bundle(bundle, path)
    return path


@pytest.fixture()
def client(model_path: str, monkeypatch: pytest.MonkeyPatch):
    from fastapi.testclient import TestClient

    from app import main as service_main

    monkeypatch.setattr(service_main.model_store, "model_path", model_path)
    monkeypatch.setattr(service_main.model_store, "model_gcs_uri", "")
    with TestClient(service_main.app) as test_client:
        yield test_client
