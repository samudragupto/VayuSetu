"""Model loading with Cloud Storage fallback.

Resolution order at start-up:

1. ``MODEL_GCS_URI`` (if set and ``PREFER_GCS_MODEL`` is true) - the model
   published by the training pipeline; downloaded once per container instance.
2. ``MODEL_PATH`` - the model baked into the container image at build time.

If neither is available the service starts in a degraded state and returns
HTTP 503 from ``/predict`` while ``/healthz`` keeps reporting the condition, so
Cloud Run can still route traffic and operators can see the problem.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Optional

from vayusetu_ml.training import ModelBundle, load_bundle

logger = logging.getLogger(__name__)


@dataclass
class LoadedModel:
    bundle: ModelBundle
    source: str
    loaded_at: float


class ModelStore:
    """Thread-safe holder for the active model bundle."""

    def __init__(self, model_path: str, model_gcs_uri: str = "", prefer_gcs: bool = True, project_id: str = "") -> None:
        self.model_path = model_path
        self.model_gcs_uri = model_gcs_uri
        self.prefer_gcs = prefer_gcs
        self.project_id = project_id
        self._lock = threading.Lock()
        self._loaded: Optional[LoadedModel] = None
        self.last_error: Optional[str] = None

    @property
    def loaded(self) -> Optional[LoadedModel]:
        return self._loaded

    @property
    def bundle(self) -> ModelBundle:
        if self._loaded is None:
            raise RuntimeError("Model is not loaded")
        return self._loaded.bundle

    def load(self) -> Optional[LoadedModel]:
        """Load the model, trying Cloud Storage first when configured."""
        with self._lock:
            errors = []
            if self.model_gcs_uri and self.prefer_gcs:
                try:
                    self._loaded = self._load_from_gcs()
                    self.last_error = None
                    return self._loaded
                except Exception as exc:  # noqa: BLE001 - fall back to the local artifact
                    errors.append(f"gcs: {exc}")
                    logger.warning("Could not load model from %s: %s", self.model_gcs_uri, exc)
            if self.model_path and os.path.exists(self.model_path):
                try:
                    bundle = load_bundle(self.model_path)
                    self._loaded = LoadedModel(bundle=bundle, source=f"file:{self.model_path}", loaded_at=time.time())
                    self.last_error = None
                    logger.info("Loaded model %s from %s", bundle.model_version, self.model_path)
                    return self._loaded
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"file: {exc}")
                    logger.error("Could not load model from %s: %s", self.model_path, exc)
            else:
                errors.append(f"file: {self.model_path} does not exist")
            self.last_error = "; ".join(errors)
            logger.error("No model could be loaded (%s)", self.last_error)
            return None

    def _load_from_gcs(self) -> LoadedModel:
        from google.cloud import storage

        if not self.model_gcs_uri.startswith("gs://"):
            raise ValueError("MODEL_GCS_URI must start with gs://")
        bucket_name, _, blob_name = self.model_gcs_uri[5:].partition("/")
        client = storage.Client(project=self.project_id or None)
        blob = client.bucket(bucket_name).blob(blob_name)
        if not blob.exists():
            raise FileNotFoundError(f"{self.model_gcs_uri} does not exist")
        with tempfile.NamedTemporaryFile(suffix=".joblib", delete=False) as handle:
            temp_path = handle.name
        blob.download_to_filename(temp_path)
        bundle = load_bundle(temp_path)
        logger.info("Loaded model %s from %s", bundle.model_version, self.model_gcs_uri)
        return LoadedModel(bundle=bundle, source=self.model_gcs_uri, loaded_at=time.time())
