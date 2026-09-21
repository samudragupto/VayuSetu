"""Unit tests for the shared vayusetu_common package."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest

from vayusetu_common import aqi, geo, retry
from vayusetu_common.bigquery_sink import BigQuerySink
from vayusetu_common.firestore_events import document_id_from_path, extract_document_path
from vayusetu_common.logging_utils import CloudLoggingJsonFormatter


class _FakeHttpError(Exception):
    def __init__(self, status_code: int, retry_after: str | None = None) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code
        headers = {"Retry-After": retry_after} if retry_after else {}
        self.response = SimpleNamespace(status_code=status_code, headers=headers)


def test_geohash_round_trip() -> None:
    encoded = geo.encode_geohash(28.6139, 77.2090, precision=7)
    assert encoded == "ttnfucj"
    lat, lon = geo.decode_geohash_center(encoded)
    assert abs(lat - 28.6139) < 0.001
    assert abs(lon - 77.2090) < 0.001


def test_geohash_prefix_property() -> None:
    fine = geo.encode_geohash(19.0760, 72.8777, precision=8)
    coarse = geo.encode_geohash(19.0760, 72.8777, precision=5)
    assert fine.startswith(coarse)


def test_haversine_delhi_mumbai() -> None:
    distance = geo.haversine_km(28.6139, 77.2090, 19.0760, 72.8777)
    assert 1140 < distance < 1160


@pytest.mark.parametrize(
    "value,expected",
    [(10, "good"), (75, "satisfactory"), (150, "moderate"), (250, "poor"), (350, "very_poor"), (450, "severe"), (999, "severe")],
)
def test_aqi_categories(value: float, expected: str) -> None:
    assert aqi.aqi_category(value) == expected


def test_pm25_conversion_is_monotonic() -> None:
    values = [aqi.pm25_to_aqi(c) for c in (0, 30, 60, 90, 120, 250, 400)]
    assert values == sorted(values)
    assert aqi.pm25_to_aqi(60) == 100.0
    assert abs(aqi.aqi_to_pm25(aqi.pm25_to_aqi(150)) - 150) < 1.0


def test_rate_limit_detection() -> None:
    assert retry.is_rate_limit_error(_FakeHttpError(429))
    assert retry.is_rate_limit_error(RuntimeError("429 Resource has been exhausted"))
    assert not retry.is_rate_limit_error(_FakeHttpError(400))


def test_transient_detection() -> None:
    assert retry.is_transient_error(_FakeHttpError(503))
    assert retry.is_transient_error(TimeoutError("timed out"))
    assert not retry.is_transient_error(_FakeHttpError(404))
    assert not retry.is_transient_error(ValueError("bad json"))


def test_retry_after_header_is_honoured() -> None:
    assert retry.retry_after_seconds(_FakeHttpError(429, retry_after="7")) == 7.0
    assert retry.retry_after_seconds(RuntimeError("Please retry in 12.5s")) == 12.5
    assert retry.retry_after_seconds(RuntimeError("no hint")) is None


def test_backoff_is_bounded() -> None:
    for attempt in range(1, 10):
        delay = retry.compute_backoff_seconds(attempt, base_delay=1.0, max_delay=8.0)
        assert 0.0 <= delay <= 8.0
    assert retry.compute_backoff_seconds(3, base_delay=1.0, max_delay=60.0, jitter=False) == 4.0


def test_retry_decorator_retries_then_succeeds() -> None:
    calls = {"count": 0}
    sleeps: list[float] = []

    @retry.retry_with_backoff(max_attempts=4, base_delay=0.01, max_delay=0.02, sleep=sleeps.append)
    def flaky() -> str:
        calls["count"] += 1
        if calls["count"] < 3:
            raise _FakeHttpError(429)
        return "ok"

    assert flaky() == "ok"
    assert calls["count"] == 3
    assert len(sleeps) == 2


def test_retry_decorator_does_not_retry_permanent_errors() -> None:
    calls = {"count": 0}

    @retry.retry_with_backoff(max_attempts=4, base_delay=0.01, sleep=lambda _: None)
    def permanent() -> None:
        calls["count"] += 1
        raise _FakeHttpError(404)

    with pytest.raises(_FakeHttpError):
        permanent()
    assert calls["count"] == 1


def test_retry_decorator_gives_up() -> None:
    @retry.retry_with_backoff(max_attempts=3, base_delay=0.01, sleep=lambda _: None)
    def always_busy() -> None:
        raise _FakeHttpError(503)

    with pytest.raises(_FakeHttpError):
        always_busy()


def test_extract_document_path_from_attribute() -> None:
    event = {"document": "projects/p/databases/(default)/documents/citizen_reports/abc123"}
    assert extract_document_path(event) == "citizen_reports/abc123"
    assert document_id_from_path("citizen_reports/abc123") == "abc123"


def test_extract_document_path_from_json_payload() -> None:
    event = SimpleNamespace(data={"value": {"name": "projects/p/databases/(default)/documents/predicted_hotspots/h1"}})
    assert extract_document_path(event) == "predicted_hotspots/h1"


def test_extract_document_path_failure() -> None:
    with pytest.raises(ValueError):
        extract_document_path(SimpleNamespace(data={}))


def test_bigquery_sink_disabled_skips_client() -> None:
    sink = BigQuerySink("p", "d", enabled=False)
    assert sink.write("citizen_reports", [{"report_id": "x"}]) == 0


def test_bigquery_sink_streaming_mode_uses_client() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.rows = None

        def insert_rows_json(self, table, rows):  # noqa: ANN001
            self.rows = (table, rows)
            return []

    client = FakeClient()
    sink = BigQuerySink("p", "d", mode="streaming", client=client)
    written = sink.write("alert_log", [{"alert_id": "a", "sent_at": __import__("datetime").datetime(2026, 1, 1)}])
    assert written == 1
    assert client.rows[0] == "p.d.alert_log"
    assert client.rows[1][0]["sent_at"].startswith("2026-01-01")


def test_json_formatter_emits_severity_and_extras() -> None:
    formatter = CloudLoggingJsonFormatter("test-service")
    record = logging.LogRecord("vayusetu", logging.WARNING, __file__, 1, "hello %s", ("world",), None)
    record.report_id = "r1"
    payload = json.loads(formatter.format(record))
    assert payload["severity"] == "WARNING"
    assert payload["message"] == "hello world"
    assert payload["report_id"] == "r1"
    assert payload["service"] == "test-service"
