"""HTTP client for the private Cloud Run prediction service.

Service-to-service calls are authenticated with a Google-signed OIDC identity
token whose audience is the Cloud Run URL. Authentication is skipped for plain
http:// endpoints (docker-compose) or when ``PREDICTION_SERVICE_AUTH=false``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import requests

from vayusetu_common.retry import is_transient_error, retry_with_backoff

logger = logging.getLogger(__name__)


class PredictionServiceError(RuntimeError):
    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class PredictionClient:
    def __init__(self, base_url: str, use_auth: bool = True, timeout_seconds: float = 90.0, session: Optional[requests.Session] = None) -> None:
        if not base_url:
            raise ValueError("PREDICTION_SERVICE_URL is required")
        self.base_url = base_url.rstrip("/")
        self.use_auth = use_auth and self.base_url.startswith("https://")
        self.timeout_seconds = timeout_seconds
        self._session = session or requests.Session()

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.use_auth:
            import google.auth.transport.requests
            import google.oauth2.id_token

            token = google.oauth2.id_token.fetch_id_token(google.auth.transport.requests.Request(), self.base_url)
            headers["Authorization"] = f"Bearer {token}"
        return headers

    @retry_with_backoff(
        max_attempts=4,
        base_delay=2.0,
        max_delay=20.0,
        retry_on=(PredictionServiceError, requests.RequestException),
        should_retry=is_transient_error,
        operation_name="prediction_service_predict",
    )
    def predict(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = self._session.post(f"{self.base_url}/predict", json=payload, headers=self._headers(), timeout=self.timeout_seconds)
        if response.status_code >= 400:
            raise PredictionServiceError(
                f"Prediction service returned HTTP {response.status_code}: {response.text[:300]}",
                status_code=response.status_code,
            )
        body = response.json()
        if "predictions" not in body:
            raise PredictionServiceError("Prediction service response is missing 'predictions'")
        return body

    def health(self) -> Dict[str, Any]:
        response = self._session.get(f"{self.base_url}/healthz", headers=self._headers(), timeout=15)
        response.raise_for_status()
        return response.json()
