"""Unit tests for the Gemini vision function (no network access required)."""

from __future__ import annotations

import io
import json
import sys
import types
from typing import Any, Dict, List

import gemini_client
import main
import pytest
from gemini_client import (
    GeminiAnalysisError,
    GeminiVisionAnalyzer,
    ModelUnavailableError,
    normalize_analysis,
    parse_model_json,
    prepare_image,
    visibility_category_from_km,
)

VALID_RAW: Dict[str, Any] = {
    "is_outdoor_scene": True,
    "haze_index": 0.72,
    "visibility_km": 1.8,
    "visibility_category": "poor",
    "sky_condition": "brown_smog",
    "smoke_detected": True,
    "dust_detected": False,
    "fog_or_mist_detected": False,
    "open_burning_detected": False,
    "vehicle_density_score": 0.8,
    "construction_activity_score": 0.3,
    "industrial_emission_score": 0.1,
    "pollution_sources": ["vehicular", "construction_dust"],
    "estimated_aqi_category": "poor",
    "estimated_aqi": 286,
    "confidence": 0.74,
    "reasoning": "Brown gradient near horizon with blurred buildings indicates heavy particulate load.",
}


class _FakeStatusError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.prompt_feedback = types.SimpleNamespace(block_reason=None)
        self.candidates = [types.SimpleNamespace(finish_reason=types.SimpleNamespace(name="STOP"))]


class _FakeModel:
    def __init__(self, name: str, script: List[Any]) -> None:
        self.name = name
        self.script = list(script)
        self.calls = 0

    def generate_content(self, parts: Any, request_options: Any = None) -> _FakeResponse:  # noqa: ARG002
        self.calls += 1
        if not self.script:
            raise AssertionError(f"unexpected call to {self.name}")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return _FakeResponse(item)


@pytest.fixture()
def fake_genai(monkeypatch: pytest.MonkeyPatch):
    """Install a fake google.generativeai module with scripted model behaviour."""
    registry: Dict[str, _FakeModel] = {}
    module = types.ModuleType("google.generativeai")

    def configure(**kwargs: Any) -> None:  # noqa: ARG001
        module.configured = kwargs

    class GenerationConfig:  # noqa: D401 - mimic SDK
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    def GenerativeModel(model_name: str, **kwargs: Any) -> _FakeModel:  # noqa: N802, ARG001
        return registry[model_name]

    module.configure = configure  # type: ignore[attr-defined]
    module.GenerationConfig = GenerationConfig  # type: ignore[attr-defined]
    module.GenerativeModel = GenerativeModel  # type: ignore[attr-defined]

    google_pkg = sys.modules.get("google") or types.ModuleType("google")
    monkeypatch.setitem(sys.modules, "google", google_pkg)
    monkeypatch.setattr(google_pkg, "generativeai", module, raising=False)
    monkeypatch.setitem(sys.modules, "google.generativeai", module)
    return registry


def _analyzer(candidates: List[str]) -> GeminiVisionAnalyzer:
    return GeminiVisionAnalyzer(
        api_key="test",
        model_candidates=candidates,
        max_attempts_per_model=3,
        base_delay_seconds=0.001,
        max_delay_seconds=0.002,
        sleep=lambda _: None,
    )


def test_normalize_valid_payload() -> None:
    result = normalize_analysis(VALID_RAW)
    assert result["haze_index"] == 0.72
    assert result["estimated_aqi_category"] == "poor"
    assert result["pollution_sources"] == ["vehicular", "construction_dust"]


def test_normalize_clamps_and_repairs_inconsistencies() -> None:
    raw = dict(VALID_RAW)
    raw.update(
        {
            "haze_index": 3.2,
            "visibility_km": -4,
            "visibility_category": "not-a-category",
            "estimated_aqi": 350,
            "estimated_aqi_category": "good",
            "pollution_sources": ["Vehicular", "banana"],
        }
    )
    result = normalize_analysis(raw)
    assert result["haze_index"] == 1.0
    assert result["visibility_km"] == 0.0
    assert result["estimated_aqi_category"] == "very_poor"
    assert result["pollution_sources"] == ["vehicular"]
    assert result["visibility_category"] == visibility_category_from_km(0.0)


def test_normalize_indoor_scene_zeroes_estimate() -> None:
    raw = dict(VALID_RAW)
    raw["is_outdoor_scene"] = False
    result = normalize_analysis(raw)
    assert result["estimated_aqi"] == 0.0
    assert result["confidence"] <= 0.1


def test_parse_model_json_handles_code_fences() -> None:
    fenced = "```json\n" + json.dumps(VALID_RAW) + "\n```"
    assert parse_model_json(fenced)["estimated_aqi"] == 286
    with pytest.raises(GeminiAnalysisError):
        parse_model_json("not json at all")


def test_prepare_image_downscales_large_images() -> None:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (3000, 2000), color=(120, 110, 90)).save(buffer, format="PNG")
    data, mime = prepare_image(buffer.getvalue(), max_edge_px=512)
    assert mime == "image/jpeg"
    with Image.open(io.BytesIO(data)) as image:
        assert max(image.size) <= 512


def test_prepare_image_falls_back_on_garbage() -> None:
    data, mime = prepare_image(b"definitely-not-an-image")
    assert data == b"definitely-not-an-image"
    assert mime == "image/jpeg"


def test_analyzer_falls_through_on_404(fake_genai: Dict[str, _FakeModel]) -> None:
    fake_genai["gemini-1.5-flash"] = _FakeModel("gemini-1.5-flash", [_FakeStatusError(404, "404 model not found")])
    fake_genai["gemini-flash-latest"] = _FakeModel("gemini-flash-latest", [json.dumps(VALID_RAW)])
    analyzer = _analyzer(["gemini-1.5-flash", "gemini-flash-latest"])

    analysis = analyzer.analyze(b"bytes", "image/jpeg", {"city": "Delhi"})

    assert analysis.model_name == "gemini-flash-latest"
    assert analysis.estimated_aqi == 286
    assert analyzer.available_models == ["gemini-flash-latest"]
    # Second call must skip the retired model entirely.
    fake_genai["gemini-flash-latest"].script.append(json.dumps(VALID_RAW))
    analyzer.analyze(b"bytes", "image/jpeg")
    assert fake_genai["gemini-1.5-flash"].calls == 1


def test_analyzer_backs_off_on_429_then_succeeds(fake_genai: Dict[str, _FakeModel]) -> None:
    fake_genai["m"] = _FakeModel("m", [_FakeStatusError(429, "429 Resource has been exhausted"), json.dumps(VALID_RAW)])
    sleeps: List[float] = []
    analyzer = GeminiVisionAnalyzer(api_key="k", model_candidates=["m"], max_attempts_per_model=3, base_delay_seconds=0.01, max_delay_seconds=0.02, sleep=sleeps.append)

    analysis = analyzer.analyze(b"bytes", "image/jpeg")

    assert analysis.attempts == 2
    assert len(sleeps) == 1


def test_analyzer_moves_to_next_model_after_sustained_429(fake_genai: Dict[str, _FakeModel]) -> None:
    busy = [_FakeStatusError(429, "429 quota exceeded") for _ in range(3)]
    fake_genai["busy"] = _FakeModel("busy", busy)
    fake_genai["fresh"] = _FakeModel("fresh", [json.dumps(VALID_RAW)])
    analyzer = _analyzer(["busy", "fresh"])

    analysis = analyzer.analyze(b"bytes", "image/jpeg")

    assert analysis.model_name == "fresh"
    assert fake_genai["busy"].calls == 3
    # A rate-limited model is not permanently disabled.
    assert analyzer.available_models == ["busy", "fresh"]


def test_analyzer_permanent_error_is_not_retried(fake_genai: Dict[str, _FakeModel]) -> None:
    fake_genai["m"] = _FakeModel("m", [_FakeStatusError(403, "403 API key not valid")])
    analyzer = _analyzer(["m"])
    with pytest.raises(GeminiAnalysisError):
        analyzer.analyze(b"bytes", "image/jpeg")
    assert fake_genai["m"].calls == 1


def test_analyzer_retries_malformed_json_once(fake_genai: Dict[str, _FakeModel]) -> None:
    fake_genai["m"] = _FakeModel("m", ["<<garbage>>", json.dumps(VALID_RAW)])
    analyzer = _analyzer(["m"])
    analysis = analyzer.analyze(b"bytes", "image/jpeg")
    assert analysis.haze_index == 0.72
    assert fake_genai["m"].calls == 2


def test_analyzer_raises_when_all_models_fail(fake_genai: Dict[str, _FakeModel]) -> None:
    fake_genai["a"] = _FakeModel("a", [_FakeStatusError(404, "404 not found")])
    fake_genai["b"] = _FakeModel("b", [_FakeStatusError(404, "404 not found")])
    analyzer = _analyzer(["a", "b"])
    with pytest.raises(GeminiAnalysisError) as excinfo:
        analyzer.analyze(b"bytes", "image/jpeg")
    assert "All Gemini model candidates failed" in str(excinfo.value)


def test_classify_model_unavailable_from_invalid_argument() -> None:
    err = _FakeStatusError(400, "400 model gemini-x is not found or not supported")
    assert GeminiVisionAnalyzer._classify(err) == "unavailable"
    err2 = _FakeStatusError(400, "400 invalid image payload")
    assert GeminiVisionAnalyzer._classify(err2) == "permanent"
    with pytest.raises(ModelUnavailableError):
        raise ModelUnavailableError("x")


def test_main_should_process_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    assert main.should_process("reports/2026/01/01/abc.jpg", "image/jpeg")
    assert main.should_process("reports/x/abc.webp", None)
    assert not main.should_process("alerts/audio.mp3", "audio/mpeg")
    assert not main.should_process("reports/x/notes.txt", "text/plain")
    assert main.report_id_from_event({"name": "reports/a/b/report123.jpg"}) == "report123"
    assert main.report_id_from_event({"name": "reports/a.jpg", "metadata": {"reportId": "meta-id"}}) == "meta-id"


def test_main_compose_feedback_languages() -> None:
    analysis = gemini_client.GeminiAnalysis(**normalize_analysis(VALID_RAW), model_name="m")
    report = {"_id": "abcdefgh1234", "city": "Delhi"}
    english = main.compose_feedback(analysis, report, "en")
    hindi = main.compose_feedback(analysis, report, "hi")
    assert "Estimated AQI: 286" in english
    assert "ABCDEFGH" in english
    assert "AQI" in hindi and "वाहन" in hindi
