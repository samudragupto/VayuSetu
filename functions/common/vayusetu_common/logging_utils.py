"""Structured JSON logging compatible with Cloud Logging.

Cloud Functions (2nd gen) and Cloud Run forward stdout to Cloud Logging. When a
line is valid JSON containing ``severity`` and ``message`` keys it is ingested
as a structured log entry, which makes filtering by report ID, geohash or model
name trivial in Logs Explorer.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict

_SEVERITY_MAP = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARNING",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "CRITICAL",
}

_RESERVED_ATTRS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}


class CloudLoggingJsonFormatter(logging.Formatter):
    """Format log records as single-line JSON understood by Cloud Logging."""

    def __init__(self, service_name: str) -> None:
        super().__init__()
        self._service_name = service_name

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401 - standard override
        payload: Dict[str, Any] = {
            "severity": _SEVERITY_MAP.get(record.levelno, "DEFAULT"),
            "message": record.getMessage(),
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "logger": record.name,
            "service": self._service_name,
        }

        for key, value in record.__dict__.items():
            if key in _RESERVED_ATTRS or key.startswith("_"):
                continue
            payload[key] = _json_safe(value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def configure_logging(service_name: str, level: str | None = None) -> logging.Logger:
    """Configure the root logger once and return a service-scoped logger.

    The log level defaults to the LOG_LEVEL environment variable, then INFO.
    Calling this function repeatedly is safe; handlers are only installed once.
    """
    resolved_level = (level or os.environ.get("LOG_LEVEL") or "INFO").upper()
    root = logging.getLogger()
    root.setLevel(resolved_level)

    already_configured = any(getattr(h, "_vayusetu_handler", False) for h in root.handlers)
    if not already_configured:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(CloudLoggingJsonFormatter(service_name))
        handler._vayusetu_handler = True  # type: ignore[attr-defined]
        root.addHandler(handler)

    # Silence noisy third-party loggers unless debugging.
    if resolved_level != "DEBUG":
        for noisy in ("urllib3", "google.auth", "google.api_core", "googleapiclient", "PIL"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    return logging.getLogger(service_name)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger; configure_logging must have been called first."""
    return logging.getLogger(name)
