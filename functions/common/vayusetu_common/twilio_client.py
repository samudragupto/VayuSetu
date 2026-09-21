"""Minimal, mockable Twilio REST client.

The Twilio REST API is a plain HTTPS interface with HTTP basic authentication.
Talking to it directly (rather than through the SDK) keeps the Cloud Functions
lightweight and lets docker-compose point the client at a local mock server via
``TWILIO_API_BASE_URL`` so that free-tier quotas are never consumed during
development.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

from vayusetu_common.retry import is_transient_error, retry_with_backoff

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.twilio.com"
_API_VERSION = "2010-04-01"


class TwilioError(RuntimeError):
    """Raised when Twilio rejects a request."""

    def __init__(self, message: str, status_code: Optional[int] = None, response: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = response


@dataclass
class TwilioMessageResult:
    sid: str
    status: str
    to: str
    raw: Dict[str, Any]


class TwilioRestClient:
    """Thin wrapper over the Messages and Calls resources with exponential backoff."""

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 20.0,
        session: Optional[requests.Session] = None,
    ) -> None:
        if not account_sid or not auth_token:
            raise ValueError("Twilio account SID and auth token are required")
        self.account_sid = account_sid
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._session = session or requests.Session()
        self._auth = (account_sid, auth_token)

    def _account_url(self, resource: str) -> str:
        return f"{self.base_url}/{_API_VERSION}/Accounts/{self.account_sid}/{resource}.json"

    @retry_with_backoff(
        max_attempts=5,
        base_delay=1.0,
        max_delay=30.0,
        retry_on=(TwilioError, requests.RequestException),
        should_retry=is_transient_error,
        operation_name="twilio_request",
    )
    def _post(self, resource: str, data: Dict[str, Any]) -> Dict[str, Any]:
        response = self._session.post(
            self._account_url(resource),
            data=data,
            auth=self._auth,
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            detail: Any
            try:
                detail = response.json()
            except ValueError:
                detail = response.text
            raise TwilioError(
                f"Twilio {resource} request failed with HTTP {response.status_code}: {detail}",
                status_code=response.status_code,
                response=response,
            )
        return response.json()

    def send_whatsapp(self, to: str, from_: str, body: str, status_callback: Optional[str] = None) -> TwilioMessageResult:
        """Send a WhatsApp message. ``to`` and ``from_`` must use the whatsapp: prefix."""
        payload: Dict[str, Any] = {
            "To": to if to.startswith("whatsapp:") else f"whatsapp:{to}",
            "From": from_ if from_.startswith("whatsapp:") else f"whatsapp:{from_}",
            "Body": body,
        }
        if status_callback:
            payload["StatusCallback"] = status_callback
        raw = self._post("Messages", payload)
        result = TwilioMessageResult(sid=raw.get("sid", ""), status=raw.get("status", "unknown"), to=payload["To"], raw=raw)
        logger.info("Twilio WhatsApp message queued", extra={"twilio_sid": result.sid, "status": result.status})
        return result

    def create_call(self, to: str, from_: str, twiml: str, status_callback: Optional[str] = None) -> TwilioMessageResult:
        """Place a voice call that plays the supplied TwiML document."""
        payload: Dict[str, Any] = {"To": to, "From": from_, "Twiml": twiml}
        if status_callback:
            payload["StatusCallback"] = status_callback
        raw = self._post("Calls", payload)
        result = TwilioMessageResult(sid=raw.get("sid", ""), status=raw.get("status", "unknown"), to=to, raw=raw)
        logger.info("Twilio voice call queued", extra={"twilio_sid": result.sid, "status": result.status})
        return result

    @retry_with_backoff(
        max_attempts=4,
        base_delay=1.0,
        max_delay=15.0,
        retry_on=(TwilioError, requests.RequestException),
        should_retry=is_transient_error,
        operation_name="twilio_media_download",
    )
    def download_media(self, media_url: str) -> bytes:
        """Download an inbound media attachment (Twilio redirects to signed storage)."""
        response = self._session.get(media_url, auth=self._auth, timeout=self.timeout_seconds, allow_redirects=True)
        if response.status_code >= 400:
            raise TwilioError(
                f"Twilio media download failed with HTTP {response.status_code}",
                status_code=response.status_code,
                response=response,
            )
        return response.content
