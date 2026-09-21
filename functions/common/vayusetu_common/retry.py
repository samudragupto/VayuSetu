"""Exponential backoff with full jitter for free-tier API quotas.

Every outbound call to Google AI Studio, Earth Engine, Cloud Translation,
Text-to-Speech, Twilio and BigQuery goes through :func:`retry_with_backoff`.
The implementation follows the "full jitter" strategy recommended by AWS and
Google SRE guidance, honours ``Retry-After`` headers when present and treats
HTTP 429 (rate limited) and 5xx responses as transient.
"""

from __future__ import annotations

import functools
import logging
import random
import time
from typing import Any, Callable, Iterable, Optional, Tuple, Type, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_RATE_LIMIT_STATUS = {429}
_TRANSIENT_STATUS = {408, 429, 500, 502, 503, 504}

_RATE_LIMIT_MARKERS = (
    "429",
    "resource_exhausted",
    "resource has been exhausted",
    "rate limit",
    "quota",
    "too many requests",
)


class RetryExhaustedError(RuntimeError):
    """Raised when every retry attempt has failed."""

    def __init__(self, operation: str, attempts: int, last_error: BaseException) -> None:
        super().__init__(f"{operation} failed after {attempts} attempt(s): {last_error}")
        self.operation = operation
        self.attempts = attempts
        self.last_error = last_error


def _status_code_from_exception(exc: BaseException) -> Optional[int]:
    """Best-effort extraction of an HTTP status code from heterogeneous exceptions."""
    for attr in ("status_code", "code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
        if callable(value):
            try:
                result = value()
                if isinstance(result, int):
                    return result
            except Exception:  # pragma: no cover - defensive
                continue
    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", None) or getattr(response, "status", None)
        if isinstance(status, int):
            return status
    # google.api_core exceptions expose grpc status codes; ResourceExhausted maps to 429.
    grpc_status = getattr(exc, "grpc_status_code", None)
    if grpc_status is not None:
        name = getattr(grpc_status, "name", "")
        mapping = {
            "RESOURCE_EXHAUSTED": 429,
            "UNAVAILABLE": 503,
            "DEADLINE_EXCEEDED": 504,
            "INTERNAL": 500,
            "ABORTED": 409,
        }
        return mapping.get(name)
    return None


def is_rate_limit_error(exc: BaseException) -> bool:
    """Return True when ``exc`` represents an HTTP 429 / quota exhaustion."""
    status = _status_code_from_exception(exc)
    if status in _RATE_LIMIT_STATUS:
        return True
    name = type(exc).__name__.lower()
    if "resourceexhausted" in name or "toomanyrequests" in name or "ratelimit" in name:
        return True
    message = str(exc).lower()
    return any(marker in message for marker in _RATE_LIMIT_MARKERS)


def is_transient_error(exc: BaseException) -> bool:
    """Return True for errors that are worth retrying (rate limits, 5xx, network)."""
    if is_rate_limit_error(exc):
        return True
    status = _status_code_from_exception(exc)
    if status in _TRANSIENT_STATUS:
        return True
    if status is not None and 400 <= status < 500:
        return False
    name = type(exc).__name__.lower()
    transient_names = (
        "serviceunavailable",
        "internalservererror",
        "deadlineexceeded",
        "gatewaytimeout",
        "badgateway",
        "connectionerror",
        "timeout",
        "aborted",
        "unavailable",
        "remotedisconnected",
        "protocolerror",
    )
    if any(marker in name for marker in transient_names):
        return True
    message = str(exc).lower()
    return any(marker in message for marker in ("503", "502", "504", "temporarily unavailable", "timed out"))


def retry_after_seconds(exc: BaseException) -> Optional[float]:
    """Extract a server-provided retry hint (seconds) when one exists."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers:
        raw = headers.get("Retry-After") or headers.get("retry-after")
        if raw:
            try:
                return max(0.0, float(raw))
            except ValueError:
                return None
    # google.api_core.exceptions.ResourceExhausted may carry retry_delay in details.
    retry_delay = getattr(exc, "retry_delay", None)
    if retry_delay is not None:
        seconds = getattr(retry_delay, "seconds", None)
        if isinstance(seconds, (int, float)):
            return float(seconds)
    message = str(exc)
    marker = "retry in "
    lowered = message.lower()
    if marker in lowered:
        tail = lowered.split(marker, 1)[1]
        digits = ""
        for char in tail:
            if char.isdigit() or char == ".":
                digits += char
            else:
                break
        if digits:
            try:
                return float(digits)
            except ValueError:
                return None
    return None


def compute_backoff_seconds(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    multiplier: float = 2.0,
    jitter: bool = True,
) -> float:
    """Return the delay before ``attempt`` (1-based) using exponential backoff with full jitter."""
    if attempt < 1:
        attempt = 1
    capped = min(max_delay, base_delay * (multiplier ** (attempt - 1)))
    if not jitter:
        return capped
    return random.uniform(0.0, capped)


def retry_with_backoff(
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    multiplier: float = 2.0,
    retry_on: Tuple[Type[BaseException], ...] = (Exception,),
    should_retry: Optional[Callable[[BaseException], bool]] = None,
    on_retry: Optional[Callable[[int, BaseException, float], None]] = None,
    operation_name: Optional[str] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator applying exponential backoff with jitter.

    Args:
        max_attempts: total number of attempts including the first call.
        base_delay: delay in seconds for the first retry before jitter.
        max_delay: upper bound on the delay between attempts.
        multiplier: exponential growth factor.
        retry_on: exception types eligible for retry.
        should_retry: optional predicate refining eligibility (defaults to
            :func:`is_transient_error`).
        on_retry: optional callback invoked with (attempt, error, delay).
        operation_name: label used in log messages and errors.
        sleep: injectable sleep function (tests pass a no-op).
    """
    predicate = should_retry or is_transient_error

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        name = operation_name or func.__name__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_error: Optional[BaseException] = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retry_on as exc:  # type: ignore[misc]
                    last_error = exc
                    if attempt >= max_attempts or not predicate(exc):
                        raise
                    hinted = retry_after_seconds(exc)
                    delay = compute_backoff_seconds(attempt, base_delay, max_delay, multiplier)
                    if hinted is not None:
                        delay = min(max_delay, max(delay, hinted))
                    logger.warning(
                        "Retrying %s after error (attempt %d/%d, sleeping %.2fs): %s",
                        name,
                        attempt,
                        max_attempts,
                        delay,
                        exc,
                        extra={"operation": name, "attempt": attempt, "delay_seconds": round(delay, 2)},
                    )
                    if on_retry is not None:
                        on_retry(attempt, exc, delay)
                    sleep(delay)
            # Unreachable in practice, kept for type-checkers.
            raise RetryExhaustedError(name, max_attempts, last_error or RuntimeError("unknown error"))

        return wrapper

    return decorator


def call_with_backoff(
    func: Callable[..., T],
    *args: Any,
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    should_retry: Optional[Callable[[BaseException], bool]] = None,
    operation_name: Optional[str] = None,
    retry_on: Iterable[Type[BaseException]] = (Exception,),
    sleep: Callable[[float], None] = time.sleep,
    **kwargs: Any,
) -> T:
    """Functional form of :func:`retry_with_backoff` for one-off calls."""
    wrapped = retry_with_backoff(
        max_attempts=max_attempts,
        base_delay=base_delay,
        max_delay=max_delay,
        retry_on=tuple(retry_on),
        should_retry=should_retry,
        operation_name=operation_name or getattr(func, "__name__", "operation"),
        sleep=sleep,
    )(func)
    return wrapped(*args, **kwargs)
