"""Gemini vision client with strict JSON schema prompting and quota-aware retries.

Design notes
------------
* The Google AI Studio free tier enforces per-model requests-per-minute and
  requests-per-day quotas. Every call therefore runs through exponential backoff
  with full jitter, honouring server supplied retry hints.
* Google retires model identifiers over time (the originally specified
  ``gemini-1.5-flash`` now returns HTTP 404). The analyzer accepts an ordered
  list of candidate models; a 404 permanently disables a candidate for the
  lifetime of the instance, and sustained 429 responses move the request to the
  next candidate, which has an independent quota bucket.
* All SDK specific code is isolated in this module so a future migration to the
  ``google-genai`` SDK is a single-file change.
"""

from __future__ import annotations

import io
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from prompts import (
    AQI_CATEGORIES,
    POLLUTION_SOURCES,
    RESPONSE_SCHEMA,
    SKY_CONDITIONS,
    SYSTEM_PROMPT,
    VISIBILITY_CATEGORIES,
    build_user_prompt,
)

from vayusetu_common.aqi import aqi_category, clamp_aqi
from vayusetu_common.retry import compute_backoff_seconds, is_rate_limit_error, is_transient_error, retry_after_seconds

logger = logging.getLogger(__name__)

DEFAULT_MODEL_CANDIDATES: List[str] = [
    "gemini-1.5-flash",
    "gemini-flash-latest",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
]


class GeminiAnalysisError(RuntimeError):
    """Permanent failure: the image cannot be analysed."""


class ModelUnavailableError(GeminiAnalysisError):
    """The requested model identifier is not served by the API (HTTP 404/400)."""


class RateLimitedError(GeminiAnalysisError):
    """Quota for the model remained exhausted after all retry attempts."""


class TransientUpstreamError(GeminiAnalysisError):
    """The API kept returning 5xx responses after all retry attempts."""


@dataclass
class GeminiAnalysis:
    """Normalised, schema-validated output of the vision model."""

    is_outdoor_scene: bool
    haze_index: float
    visibility_km: float
    visibility_category: str
    sky_condition: str
    smoke_detected: bool
    dust_detected: bool
    fog_or_mist_detected: bool
    open_burning_detected: bool
    vehicle_density_score: float
    construction_activity_score: float
    industrial_emission_score: float
    pollution_sources: List[str]
    estimated_aqi_category: str
    estimated_aqi: float
    confidence: float
    reasoning: str
    model_name: str = ""
    latency_ms: int = 0
    attempts: int = 1
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


def _as_float(value: Any, default: float, lower: float, upper: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return max(lower, min(upper, number))


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    return default


def visibility_category_from_km(visibility_km: float) -> str:
    if visibility_km >= 10:
        return "excellent"
    if visibility_km >= 6:
        return "good"
    if visibility_km >= 3:
        return "moderate"
    if visibility_km >= 1.5:
        return "poor"
    if visibility_km >= 0.5:
        return "very_poor"
    return "severe"


def normalize_analysis(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Clamp, coerce and cross-validate a raw model response."""
    if not isinstance(raw, dict):
        raise GeminiAnalysisError("Model response is not a JSON object")

    is_outdoor = _as_bool(raw.get("is_outdoor_scene"), default=True)
    haze_index = _as_float(raw.get("haze_index"), 0.5, 0.0, 1.0)
    visibility_km = _as_float(raw.get("visibility_km"), 5.0, 0.0, 50.0)

    visibility_category = str(raw.get("visibility_category", "")).strip().lower()
    if visibility_category not in VISIBILITY_CATEGORIES:
        visibility_category = visibility_category_from_km(visibility_km)

    sky_condition = str(raw.get("sky_condition", "")).strip().lower()
    if sky_condition not in SKY_CONDITIONS:
        sky_condition = "not_visible" if not is_outdoor else "hazy_blue"

    sources_raw = raw.get("pollution_sources") or []
    if isinstance(sources_raw, str):
        sources_raw = [sources_raw]
    sources: List[str] = []
    for item in sources_raw:
        key = str(item).strip().lower().replace(" ", "_").replace("-", "_")
        if key in POLLUTION_SOURCES and key not in sources:
            sources.append(key)
    if not sources:
        sources = ["unknown"]

    estimated_aqi = clamp_aqi(_as_float(raw.get("estimated_aqi"), 100.0, 0.0, 500.0))
    category_raw = str(raw.get("estimated_aqi_category", "")).strip().lower()
    derived_category = aqi_category(estimated_aqi)
    estimated_category = derived_category if category_raw not in AQI_CATEGORIES else category_raw
    if estimated_category != derived_category:
        # The numeric estimate is authoritative; keep the category consistent.
        estimated_category = derived_category

    confidence = _as_float(raw.get("confidence"), 0.5, 0.0, 1.0)
    if not is_outdoor:
        confidence = min(confidence, 0.1)
        estimated_aqi = 0.0
        estimated_category = aqi_category(estimated_aqi)

    reasoning = str(raw.get("reasoning", "")).strip()
    if len(reasoning) > 300:
        reasoning = reasoning[:297].rstrip() + "..."

    return {
        "is_outdoor_scene": is_outdoor,
        "haze_index": round(haze_index, 3),
        "visibility_km": round(visibility_km, 2),
        "visibility_category": visibility_category,
        "sky_condition": sky_condition,
        "smoke_detected": _as_bool(raw.get("smoke_detected")),
        "dust_detected": _as_bool(raw.get("dust_detected")),
        "fog_or_mist_detected": _as_bool(raw.get("fog_or_mist_detected")),
        "open_burning_detected": _as_bool(raw.get("open_burning_detected")),
        "vehicle_density_score": round(_as_float(raw.get("vehicle_density_score"), 0.0, 0.0, 1.0), 3),
        "construction_activity_score": round(_as_float(raw.get("construction_activity_score"), 0.0, 0.0, 1.0), 3),
        "industrial_emission_score": round(_as_float(raw.get("industrial_emission_score"), 0.0, 0.0, 1.0), 3),
        "pollution_sources": sources,
        "estimated_aqi_category": estimated_category,
        "estimated_aqi": round(estimated_aqi, 1),
        "confidence": round(confidence, 3),
        "reasoning": reasoning,
    }


def parse_model_json(text: str) -> Dict[str, Any]:
    """Parse JSON from a model response, tolerating markdown code fences."""
    if text is None:
        raise GeminiAnalysisError("Model returned an empty response")
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        if candidate.lower().startswith("json"):
            candidate = candidate[4:]
    candidate = candidate.strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(candidate[start : end + 1])
            except json.JSONDecodeError as exc:
                raise GeminiAnalysisError(f"Model response is not valid JSON: {exc}") from exc
        raise GeminiAnalysisError("Model response does not contain a JSON object") from None


# ---------------------------------------------------------------------------
# Image preparation
# ---------------------------------------------------------------------------


def prepare_image(image_bytes: bytes, max_edge_px: int = 1024, jpeg_quality: int = 85) -> tuple[bytes, str]:
    """Downscale and re-encode an image to limit token usage on the free tier.

    Returns the encoded bytes and their MIME type. Falls back to the original
    bytes if Pillow cannot decode the payload, leaving the model to decide.
    """
    try:
        from PIL import Image, ImageOps
    except ImportError:  # pragma: no cover - Pillow is a declared dependency
        return image_bytes, "image/jpeg"

    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image = ImageOps.exif_transpose(image)
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            image.thumbnail((max_edge_px, max_edge_px))
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=jpeg_quality, optimize=True)
            return output.getvalue(), "image/jpeg"
    except Exception as exc:  # noqa: BLE001 - any decode failure falls back to raw bytes
        logger.warning("Image pre-processing failed, sending original bytes: %s", exc)
        return image_bytes, "image/jpeg"


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class GeminiVisionAnalyzer:
    """Analyse citizen images with Gemini via the Google AI Studio API."""

    def __init__(
        self,
        api_key: str,
        model_candidates: Optional[Sequence[str]] = None,
        api_endpoint: Optional[str] = None,
        max_attempts_per_model: int = 4,
        base_delay_seconds: float = 2.0,
        max_delay_seconds: float = 45.0,
        request_timeout_seconds: float = 60.0,
        temperature: float = 0.2,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise ValueError("A Google AI Studio API key is required")
        self.model_candidates: List[str] = [m for m in (model_candidates or DEFAULT_MODEL_CANDIDATES) if m]
        if not self.model_candidates:
            raise ValueError("At least one Gemini model candidate is required")
        self.max_attempts_per_model = max(1, max_attempts_per_model)
        self.base_delay_seconds = base_delay_seconds
        self.max_delay_seconds = max_delay_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self.temperature = temperature
        self._sleep = sleep
        self._unavailable_models: set[str] = set()
        self._models: Dict[str, Any] = {}

        import google.generativeai as genai

        configure_kwargs: Dict[str, Any] = {"api_key": api_key}
        if api_endpoint:
            configure_kwargs["transport"] = "rest"
            configure_kwargs["client_options"] = {"api_endpoint": api_endpoint}
        genai.configure(**configure_kwargs)
        self._genai = genai

    # -- model management -------------------------------------------------

    def _get_model(self, model_name: str) -> Any:
        if model_name not in self._models:
            generation_config = self._genai.GenerationConfig(
                temperature=self.temperature,
                max_output_tokens=1024,
                response_mime_type="application/json",
                response_schema=RESPONSE_SCHEMA,
            )
            self._models[model_name] = self._genai.GenerativeModel(
                model_name=model_name,
                system_instruction=SYSTEM_PROMPT,
                generation_config=generation_config,
            )
        return self._models[model_name]

    @property
    def available_models(self) -> List[str]:
        return [m for m in self.model_candidates if m not in self._unavailable_models]

    # -- public API -------------------------------------------------------

    def analyze(self, image_bytes: bytes, mime_type: str, context: Optional[Dict[str, Any]] = None) -> GeminiAnalysis:
        """Run the analysis, walking the candidate chain until one model succeeds."""
        context = context or {}
        prompt = build_user_prompt(context)
        failures: List[str] = []
        started = time.monotonic()

        for model_name in self.model_candidates:
            if model_name in self._unavailable_models:
                continue
            try:
                raw, attempts = self._generate_with_retries(model_name, prompt, image_bytes, mime_type)
            except ModelUnavailableError as exc:
                self._unavailable_models.add(model_name)
                failures.append(f"{model_name}: unavailable ({exc})")
                logger.warning(
                    "Gemini model %s is unavailable; falling through to next candidate",
                    model_name,
                    extra={"model_name": model_name},
                )
                continue
            except RateLimitedError as exc:
                failures.append(f"{model_name}: rate limited ({exc})")
                logger.warning(
                    "Gemini model %s quota exhausted after retries; trying next candidate",
                    model_name,
                    extra={"model_name": model_name},
                )
                continue
            except TransientUpstreamError as exc:
                failures.append(f"{model_name}: upstream error ({exc})")
                logger.warning("Gemini model %s unavailable upstream; trying next candidate", model_name)
                continue

            normalised = normalize_analysis(raw)
            latency_ms = int((time.monotonic() - started) * 1000)
            analysis = GeminiAnalysis(**normalised, model_name=model_name, latency_ms=latency_ms, attempts=attempts, raw=raw)
            logger.info(
                "Gemini analysis complete",
                extra={
                    "model_name": model_name,
                    "attempts": attempts,
                    "latency_ms": latency_ms,
                    "haze_index": analysis.haze_index,
                    "estimated_aqi": analysis.estimated_aqi,
                },
            )
            return analysis

        raise GeminiAnalysisError("All Gemini model candidates failed: " + "; ".join(failures))

    # -- internals --------------------------------------------------------

    def _generate_with_retries(
        self, model_name: str, prompt: str, image_bytes: bytes, mime_type: str
    ) -> tuple[Dict[str, Any], int]:
        model = self._get_model(model_name)
        parts = [prompt, {"mime_type": mime_type, "data": image_bytes}]
        last_error: Optional[BaseException] = None
        parse_retry_used = False

        attempt = 1
        while attempt <= self.max_attempts_per_model:
            try:
                response = model.generate_content(parts, request_options={"timeout": self.request_timeout_seconds})
                text = self._extract_text(response)
                return parse_model_json(text), attempt
            except GeminiAnalysisError as exc:
                # Malformed JSON or a safety block: retry once, then give up.
                if isinstance(exc, ModelUnavailableError):
                    raise
                if not parse_retry_used and "JSON" in str(exc):
                    parse_retry_used = True
                    logger.warning("Model %s returned malformed JSON; retrying once", model_name)
                    attempt += 1
                    continue
                raise
            except Exception as exc:  # noqa: BLE001 - classify SDK / transport errors below
                last_error = exc
                classification = self._classify(exc)
                if classification == "unavailable":
                    raise ModelUnavailableError(str(exc)) from exc
                if classification == "permanent":
                    raise GeminiAnalysisError(f"Gemini request rejected: {exc}") from exc
                if attempt >= self.max_attempts_per_model:
                    break
                delay = compute_backoff_seconds(attempt, self.base_delay_seconds, self.max_delay_seconds)
                hinted = retry_after_seconds(exc)
                if hinted is not None:
                    delay = min(self.max_delay_seconds, max(delay, hinted))
                logger.warning(
                    "Gemini call failed (%s), attempt %d/%d, sleeping %.1fs: %s",
                    classification,
                    attempt,
                    self.max_attempts_per_model,
                    delay,
                    exc,
                    extra={"model_name": model_name, "attempt": attempt, "delay_seconds": round(delay, 1)},
                )
                self._sleep(delay)
                attempt += 1

        assert last_error is not None
        if is_rate_limit_error(last_error):
            raise RateLimitedError(str(last_error)) from last_error
        raise TransientUpstreamError(str(last_error)) from last_error

    @staticmethod
    def _classify(exc: BaseException) -> str:
        """Map an exception to unavailable, rate_limited, transient or permanent."""
        name = type(exc).__name__.lower()
        message = str(exc).lower()
        status = getattr(exc, "code", None)
        if callable(status):
            try:
                status = status()
            except Exception:  # pragma: no cover - defensive
                status = None
        if "notfound" in name or status == 404 or " 404" in f" {message}":
            return "unavailable"
        if "invalidargument" in name or status == 400:
            if "model" in message and ("not found" in message or "not supported" in message or "unsupported" in message):
                return "unavailable"
            return "permanent"
        if "permissiondenied" in name or "unauthenticated" in name or status in (401, 403):
            return "permanent"
        if is_rate_limit_error(exc):
            return "rate_limited"
        if is_transient_error(exc):
            return "transient"
        return "permanent"

    @staticmethod
    def _extract_text(response: Any) -> str:
        prompt_feedback = getattr(response, "prompt_feedback", None)
        block_reason = getattr(prompt_feedback, "block_reason", None)
        if block_reason:
            raise GeminiAnalysisError(f"Prompt blocked by safety filters: {block_reason}")
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            raise GeminiAnalysisError("Model returned no candidates")
        finish_reason = getattr(candidates[0], "finish_reason", None)
        finish_name = getattr(finish_reason, "name", str(finish_reason or "")).upper()
        if finish_name in {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}:
            raise GeminiAnalysisError(f"Response blocked: {finish_name}")
        try:
            text = response.text
        except (ValueError, AttributeError):
            parts = getattr(getattr(candidates[0], "content", None), "parts", None) or []
            text = "".join(getattr(part, "text", "") for part in parts)
        if not text or not text.strip():
            raise GeminiAnalysisError("Model returned empty text (not valid JSON)")
        return text
