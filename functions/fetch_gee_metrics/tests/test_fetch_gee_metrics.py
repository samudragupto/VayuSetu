"""Unit tests for the Earth Engine function (Earth Engine itself is mocked)."""

from __future__ import annotations

import datetime as dt
import sys
import types
from typing import Any, Dict

import gee_client
import main
import pytest
from gee_client import EarthEngineClient, EarthEngineError, mock_metrics


class _FakeDocRef:
    def __init__(self, data: Dict[str, Any] | None) -> None:
        self._data = data
        self.writes: list[Dict[str, Any]] = []

    def get(self) -> Any:
        exists = self._data is not None
        return types.SimpleNamespace(exists=exists, to_dict=lambda: dict(self._data or {}), id="r1")

    def set(self, payload: Dict[str, Any], merge: bool = False) -> None:  # noqa: ARG002
        self.writes.append(payload)


class _FakeFirestore:
    def __init__(self, doc: _FakeDocRef) -> None:
        self.doc = doc

    def collection(self, name: str) -> Any:  # noqa: ARG002
        return types.SimpleNamespace(document=lambda _id: self.doc)


class _FakeSink:
    def __init__(self) -> None:
        self.rows: list[tuple[str, list[Dict[str, Any]]]] = []

    def write(self, table: str, rows: list[Dict[str, Any]]) -> int:
        self.rows.append((table, rows))
        return len(rows)


@pytest.fixture(autouse=True)
def _reset_globals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "_firestore_client", None)
    monkeypatch.setattr(main, "_gee_client", None)
    monkeypatch.setattr(main, "_bigquery_sink", None)
    fake_fs_module = types.SimpleNamespace(SERVER_TIMESTAMP="SERVER_TIMESTAMP", Client=lambda project=None: None)
    google_cloud = sys.modules.get("google.cloud") or types.ModuleType("google.cloud")
    monkeypatch.setitem(sys.modules, "google.cloud", google_cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.firestore", fake_fs_module)
    monkeypatch.setattr(google_cloud, "firestore", fake_fs_module, raising=False)


def _event(path: str = "citizen_reports/r1") -> Dict[str, Any]:
    return {"document": f"projects/p/databases/(default)/documents/{path}"}


def test_mock_metrics_are_deterministic_and_seasonal() -> None:
    winter = mock_metrics(28.6, 77.2, dt.datetime(2026, 12, 15, tzinfo=dt.timezone.utc))
    winter_again = mock_metrics(28.6, 77.2, dt.datetime(2026, 12, 15, tzinfo=dt.timezone.utc))
    monsoon = mock_metrics(28.6, 77.2, dt.datetime(2026, 7, 15, tzinfo=dt.timezone.utc))
    assert winter.to_dict() == winter_again.to_dict()
    assert winter.aod_047 > monsoon.aod_047
    assert winter.source == "mock"


def test_extract_location_handles_geopoint_and_dict() -> None:
    geopoint = types.SimpleNamespace(latitude=19.07, longitude=72.87)
    assert main.extract_location({"location": geopoint}) == (19.07, 72.87)
    assert main.extract_location({"location": {"lat": 12.9, "lng": 77.5}}) == (12.9, 77.5)
    assert main.extract_location({"location": {"lat": 120, "lng": 77.5}}) is None
    assert main.extract_location({}) is None


def test_function_stores_mock_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEE_MOCK", "true")
    doc = _FakeDocRef({"location": {"lat": 28.61, "lng": 77.2}, "createdAt": dt.datetime(2026, 11, 2, tzinfo=dt.timezone.utc), "geohash": "ttnfucj"})
    sink = _FakeSink()
    monkeypatch.setattr(main, "get_firestore", lambda: _FakeFirestore(doc))
    monkeypatch.setattr(main, "get_bigquery_sink", lambda: sink)

    main.fetch_gee_metrics(_event())

    assert doc.writes[-1]["satelliteStatus"] == "fetched"
    assert doc.writes[-1]["satelliteMetrics"]["source"] == "mock"
    assert sink.rows[0][0] == "satellite_metrics"
    assert sink.rows[0][1][0]["report_id"] == "r1"
    assert sink.rows[0][1][0]["geohash"] == "ttnfucj"


def test_function_skips_without_location(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = _FakeDocRef({"createdAt": dt.datetime.now(tz=dt.timezone.utc)})
    monkeypatch.setattr(main, "get_firestore", lambda: _FakeFirestore(doc))
    main.fetch_gee_metrics(_event())
    assert doc.writes[-1]["satelliteStatus"] == "skipped_no_location"


def test_function_skips_when_already_fetched(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = _FakeDocRef({"satelliteMetrics": {"aerAi": 1.0}, "location": {"lat": 1, "lng": 1}})
    monkeypatch.setattr(main, "get_firestore", lambda: _FakeFirestore(doc))
    main.fetch_gee_metrics(_event())
    assert doc.writes == []


def test_function_records_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEE_MOCK", raising=False)
    monkeypatch.setenv("GEE_ALLOW_MOCK_FALLBACK", "false")
    doc = _FakeDocRef({"location": {"lat": 28.61, "lng": 77.2}})
    monkeypatch.setattr(main, "get_firestore", lambda: _FakeFirestore(doc))

    class _Broken:
        def fetch_metrics(self, *args: Any, **kwargs: Any) -> None:
            raise EarthEngineError("quota exceeded")

    monkeypatch.setattr(main, "get_gee_client", lambda: _Broken())
    main.fetch_gee_metrics(_event())
    assert doc.writes[-1]["satelliteStatus"] == "failed"


def test_function_falls_back_to_mock_when_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEE_MOCK", raising=False)
    monkeypatch.setenv("GEE_ALLOW_MOCK_FALLBACK", "true")
    doc = _FakeDocRef({"location": {"lat": 28.61, "lng": 77.2}})
    sink = _FakeSink()
    monkeypatch.setattr(main, "get_firestore", lambda: _FakeFirestore(doc))
    monkeypatch.setattr(main, "get_bigquery_sink", lambda: sink)

    class _Broken:
        def fetch_metrics(self, *args: Any, **kwargs: Any) -> None:
            raise EarthEngineError("init failed")

    monkeypatch.setattr(main, "get_gee_client", lambda: _Broken())
    main.fetch_gee_metrics(_event())
    assert doc.writes[-1]["satelliteStatus"] == "fetched"
    assert doc.writes[-1]["satelliteMetrics"]["source"] == "mock"


def test_earth_engine_client_requires_project() -> None:
    with pytest.raises(ValueError):
        EarthEngineClient(project="")


def test_earth_engine_client_wraps_init_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ee = types.ModuleType("ee")

    def _boom(**kwargs: Any) -> None:  # noqa: ARG001
        raise RuntimeError("not registered")

    fake_ee.Initialize = _boom  # type: ignore[attr-defined]
    fake_auth = types.ModuleType("google.auth")
    fake_auth.default = lambda scopes=None: (object(), "p")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ee", fake_ee)
    monkeypatch.setitem(sys.modules, "google.auth", fake_auth)
    monkeypatch.setattr(EarthEngineClient, "_initialised_for", None)

    client = EarthEngineClient(project="p")
    with pytest.raises(EarthEngineError):
        client.initialise()
    assert gee_client.EarthEngineClient._initialised_for is None
