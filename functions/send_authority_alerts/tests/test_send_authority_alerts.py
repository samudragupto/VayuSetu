"""Unit tests for the alerting function (Google APIs and Twilio are mocked)."""

from __future__ import annotations

import datetime as dt
import sys
import types
from typing import Any, Dict, List

import main
import pytest
from messaging import build_play_twiml, build_say_twiml, compose_alert_text, compose_whatsapp_text
from translation import SpeechSynthesizer, Translator, normalise_language

HOTSPOT = {
    "_id": "ttnfu_20261102T0600",
    "geohash": "ttnfu",
    "latitude": 28.61,
    "longitude": 77.21,
    "city": "New Delhi",
    "predictedAqi": 342.0,
    "reportCount": 18,
    "dominantSources": ["vehicular", "crop_residue_burning"],
    "forecastFor": dt.datetime(2026, 11, 2, 18, 0, tzinfo=dt.timezone.utc),
}
AUTHORITY = {"_id": "dpcc-central", "name": "Shri Sharma", "language": "hi", "phone": "+911100000000", "channels": ["voice", "whatsapp"]}


def test_compose_alert_text_mentions_key_facts() -> None:
    text = compose_alert_text(HOTSPOT, AUTHORITY)
    assert "342" in text
    assert "Very Poor" in text
    assert "18 citizen reports" in text
    assert "vehicular and crop residue burning" in text
    assert "Shri Sharma" in text


def test_twiml_builders_escape_content() -> None:
    play = build_play_twiml("https://storage.example.com/a.mp3?x=1&y=2", repeat=2)
    assert play.count("<Play>") == 2
    assert "&amp;" in play
    say = build_say_twiml("Alert <now>", "hi-IN", repeat=1)
    assert 'language="hi-IN"' in say and "&lt;now&gt;" in say


def test_whatsapp_text_includes_reference() -> None:
    text = compose_whatsapp_text(HOTSPOT, AUTHORITY, "translated body", "https://dash.example.com")
    assert "translated body" in text and "Cell: ttnfu" in text and "Dashboard:" in text


def test_language_normalisation() -> None:
    assert normalise_language("hi-IN") == "hi"
    assert normalise_language("ta") == "ta"
    assert normalise_language("xx") == "en"
    assert normalise_language(None) == "en"


def test_translator_mock_and_identity() -> None:
    translator = Translator(mock=True)
    assert translator.translate("hello", "en").translated is False
    result = translator.translate("hello", "mr")
    assert result.translated and result.text.startswith("[mr]")


def test_translator_remote_unescapes_html() -> None:
    class _Client:
        def translate(self, text: str, target_language: str, source_language: str, format_: str) -> Dict[str, str]:  # noqa: ARG002
            return {"translatedText": "Namaste &amp; swagat"}

    translator = Translator(client=_Client())
    assert translator.translate("Hello & welcome", "hi").text == "Namaste & swagat"


def test_synthesizer_voice_selection() -> None:
    standard = SpeechSynthesizer(voice_tier="standard", mock=True)
    assert standard.voice_for("hi") == ("hi-IN", "hi-IN-Standard-A")
    wavenet = SpeechSynthesizer(voice_tier="wavenet", mock=True)
    assert wavenet.voice_for("ta")[1] == "ta-IN-Wavenet-A"
    assert standard.synthesize("text", "hi") is None


class _FakeTwilio:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.messages: List[Dict[str, Any]] = []

    def create_call(self, to: str, from_: str, twiml: str) -> Any:
        self.calls.append({"to": to, "from": from_, "twiml": twiml})
        return types.SimpleNamespace(sid="CA123")

    def send_whatsapp(self, to: str, from_: str, body: str) -> Any:
        self.messages.append({"to": to, "from": from_, "body": body})
        return types.SimpleNamespace(sid="SM123")


@pytest.fixture()
def alert_env(monkeypatch: pytest.MonkeyPatch) -> _FakeTwilio:
    monkeypatch.setenv("ALERTS_MOCK_GOOGLE_APIS", "true")
    monkeypatch.setenv("TWILIO_VOICE_FROM", "+15550000000")
    monkeypatch.setenv("TWILIO_WHATSAPP_FROM", "whatsapp:+15550000000")
    monkeypatch.delenv("ALERT_AUDIO_BUCKET", raising=False)
    monkeypatch.delenv("ALERTS_DRY_RUN", raising=False)
    monkeypatch.setattr(main, "_translator", None)
    monkeypatch.setattr(main, "_synthesizer", None)
    twilio = _FakeTwilio()
    monkeypatch.setattr(main, "get_twilio", lambda: twilio)
    return twilio


def test_dispatch_sends_voice_and_whatsapp(alert_env: _FakeTwilio) -> None:
    rows = main.dispatch_to_authority(HOTSPOT, AUTHORITY, dt.datetime.now(tz=dt.timezone.utc))
    assert [r["channel"] for r in rows] == ["voice", "whatsapp"]
    assert all(r["status"] == "sent" for r in rows)
    assert 'language="hi-IN"' in alert_env.calls[0]["twiml"]
    assert alert_env.messages[0]["body"].startswith("VayuSetu ALERT")
    assert rows[0]["language"] == "hi-IN"


def test_dispatch_isolates_channel_failures(alert_env: _FakeTwilio, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("twilio down")

    monkeypatch.setattr(alert_env, "create_call", _boom)
    rows = main.dispatch_to_authority(HOTSPOT, AUTHORITY, dt.datetime.now(tz=dt.timezone.utc))
    assert rows[0]["status"] == "failed" and "twilio down" in rows[0]["error"]
    assert rows[1]["status"] == "sent"


def test_dispatch_dry_run(alert_env: _FakeTwilio, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALERTS_DRY_RUN", "true")
    rows = main.dispatch_to_authority(HOTSPOT, AUTHORITY, dt.datetime.now(tz=dt.timezone.utc))
    assert all(r["status"] == "skipped" for r in rows)
    assert alert_env.calls == [] and alert_env.messages == []


class _FakeHotspotRef:
    def __init__(self, data: Dict[str, Any]) -> None:
        self.data = data
        self.writes: List[Dict[str, Any]] = []

    def get(self, transaction: Any = None) -> Any:  # noqa: ARG002
        return types.SimpleNamespace(exists=True, to_dict=lambda: dict(self.data), id=self.data.get("_id", "h1"))

    def set(self, payload: Dict[str, Any], merge: bool = False) -> None:  # noqa: ARG002
        self.writes.append(payload)
        self.data.update(payload)


def _install_fake_firestore(monkeypatch: pytest.MonkeyPatch, hotspot_ref: _FakeHotspotRef) -> Dict[str, Any]:
    state: Dict[str, Any] = {"alert_state_writes": [], "log_docs": []}

    class _Batch:
        def set(self, ref: Any, doc: Dict[str, Any]) -> None:  # noqa: ARG002
            state["log_docs"].append(doc)

        def commit(self) -> None:
            return None

    class _StateDoc:
        def get(self) -> Any:
            return types.SimpleNamespace(exists=False, to_dict=lambda: {})

        def set(self, payload: Dict[str, Any], merge: bool = False) -> None:  # noqa: ARG002
            state["alert_state_writes"].append(payload)

    class _DB:
        def collection(self, name: str) -> Any:
            if name == main.COLLECTION_HOTSPOTS:
                return types.SimpleNamespace(document=lambda _id: hotspot_ref)
            if name == main.COLLECTION_ALERT_STATE:
                return types.SimpleNamespace(document=lambda _id: _StateDoc())
            return types.SimpleNamespace(document=lambda _id: object())

        def batch(self) -> _Batch:
            return _Batch()

    monkeypatch.setattr(main, "get_firestore", lambda: _DB())
    fake_fs_module = types.SimpleNamespace(SERVER_TIMESTAMP="TS")
    google_cloud = sys.modules.get("google.cloud") or types.ModuleType("google.cloud")
    monkeypatch.setitem(sys.modules, "google.cloud", google_cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.firestore", fake_fs_module)
    monkeypatch.setattr(google_cloud, "firestore", fake_fs_module, raising=False)
    return state


def test_function_end_to_end(alert_env: _FakeTwilio, monkeypatch: pytest.MonkeyPatch) -> None:
    hotspot_ref = _FakeHotspotRef(dict(HOTSPOT))
    state = _install_fake_firestore(monkeypatch, hotspot_ref)
    monkeypatch.setattr(main, "claim_hotspot", lambda ref: dict(ref.data))
    monkeypatch.setattr(main, "find_authorities", lambda gh: [AUTHORITY])
    monkeypatch.setattr(main, "get_bigquery_sink", lambda: types.SimpleNamespace(write=lambda *a, **k: 0))

    main.send_authority_alerts({"document": "projects/p/databases/(default)/documents/predicted_hotspots/h1"})

    assert hotspot_ref.data["alertStatus"] == "sent"
    assert hotspot_ref.data["alertRecipients"] == ["dpcc-central"]
    assert len(state["log_docs"]) == 2
    assert state["alert_state_writes"][0]["lastPredictedAqi"] == 342.0


def test_function_below_threshold(alert_env: _FakeTwilio, monkeypatch: pytest.MonkeyPatch) -> None:
    hotspot_ref = _FakeHotspotRef(dict(HOTSPOT, predictedAqi=120))
    _install_fake_firestore(monkeypatch, hotspot_ref)
    main.send_authority_alerts({"document": "projects/p/databases/(default)/documents/predicted_hotspots/h1"})
    assert hotspot_ref.data["alertStatus"] == "below_threshold"
    assert alert_env.calls == []


def test_function_no_recipients(alert_env: _FakeTwilio, monkeypatch: pytest.MonkeyPatch) -> None:
    hotspot_ref = _FakeHotspotRef(dict(HOTSPOT))
    _install_fake_firestore(monkeypatch, hotspot_ref)
    monkeypatch.setattr(main, "claim_hotspot", lambda ref: dict(ref.data))
    monkeypatch.setattr(main, "find_authorities", lambda gh: [])
    main.send_authority_alerts({"document": "projects/p/databases/(default)/documents/predicted_hotspots/h1"})
    assert hotspot_ref.data["alertStatus"] == "no_recipients"
