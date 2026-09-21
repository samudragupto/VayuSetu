"""Cloud Function: process_citizen_image.

Triggered by ``google.cloud.storage.object.v1.finalized`` events on the citizen
images bucket. Downloads the image, extracts structured pollution indicators
with Gemini, persists the result to Firestore and BigQuery and optionally sends
the citizen a WhatsApp summary in their preferred language.
"""

from __future__ import annotations

import datetime as dt
import time
from typing import Any, Dict, Optional

import functions_framework
from cloudevents.http import CloudEvent
from gemini_client import (
    DEFAULT_MODEL_CANDIDATES,
    GeminiAnalysis,
    GeminiAnalysisError,
    GeminiVisionAnalyzer,
    prepare_image,
)

from vayusetu_common import (
    aqi_category_label,
    configure_logging,
    encode_geohash,
    env_bool,
    env_int,
    env_list,
    env_str,
    retry_with_backoff,
)
from vayusetu_common.bigquery_sink import BigQuerySink
from vayusetu_common.twilio_client import TwilioRestClient

logger = configure_logging("process-citizen-image")

SUPPORTED_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic", "image/heif"}
REPORT_PREFIX = env_str("REPORT_OBJECT_PREFIX", "reports/") or "reports/"
COLLECTION_REPORTS = "citizen_reports"
COLLECTION_USERS = "users"

_firestore_client: Any = None
_storage_client: Any = None
_analyzer: Optional[GeminiVisionAnalyzer] = None
_bigquery_sink: Optional[BigQuerySink] = None
_twilio_client: Optional[TwilioRestClient] = None


# ---------------------------------------------------------------------------
# Lazy clients (created once per instance)
# ---------------------------------------------------------------------------


def get_firestore() -> Any:
    global _firestore_client
    if _firestore_client is None:
        from google.cloud import firestore

        _firestore_client = firestore.Client(project=env_str("GCP_PROJECT_ID"))
    return _firestore_client


def get_storage() -> Any:
    global _storage_client
    if _storage_client is None:
        from google.cloud import storage

        _storage_client = storage.Client(project=env_str("GCP_PROJECT_ID"))
    return _storage_client


def get_analyzer() -> GeminiVisionAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = GeminiVisionAnalyzer(
            api_key=env_str("GOOGLE_AI_STUDIO_API_KEY", required=True) or "",
            model_candidates=env_list("GEMINI_MODEL_CANDIDATES", DEFAULT_MODEL_CANDIDATES),
            api_endpoint=env_str("GEMINI_API_ENDPOINT"),
            max_attempts_per_model=env_int("GEMINI_MAX_ATTEMPTS_PER_MODEL", 4),
            base_delay_seconds=float(env_int("GEMINI_BASE_DELAY_SECONDS", 2)),
            max_delay_seconds=float(env_int("GEMINI_MAX_DELAY_SECONDS", 45)),
            request_timeout_seconds=float(env_int("GEMINI_REQUEST_TIMEOUT_SECONDS", 60)),
        )
    return _analyzer


def get_bigquery_sink() -> BigQuerySink:
    global _bigquery_sink
    if _bigquery_sink is None:
        _bigquery_sink = BigQuerySink(
            project_id=env_str("GCP_PROJECT_ID", required=True) or "",
            dataset_id=env_str("BIGQUERY_DATASET", "vayusetu") or "vayusetu",
            mode=env_str("BIGQUERY_WRITE_MODE", "load") or "load",
            enabled=env_bool("BIGQUERY_ENABLED", True),
        )
    return _bigquery_sink


def get_twilio() -> Optional[TwilioRestClient]:
    global _twilio_client
    if _twilio_client is None:
        sid = env_str("TWILIO_ACCOUNT_SID")
        token = env_str("TWILIO_AUTH_TOKEN")
        if not sid or not token:
            return None
        _twilio_client = TwilioRestClient(
            account_sid=sid,
            auth_token=token,
            base_url=env_str("TWILIO_API_BASE_URL", "https://api.twilio.com") or "https://api.twilio.com",
        )
    return _twilio_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def should_process(object_name: Optional[str], content_type: Optional[str]) -> bool:
    """Only citizen report images are analysed; everything else is ignored."""
    if not object_name or not object_name.startswith(REPORT_PREFIX):
        return False
    if content_type and content_type.lower() in SUPPORTED_CONTENT_TYPES:
        return True
    lowered = object_name.lower()
    return lowered.endswith((".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"))


def report_id_from_event(data: Dict[str, Any]) -> str:
    metadata = data.get("metadata") or {}
    report_id = metadata.get("reportId") or metadata.get("report_id")
    if report_id:
        return str(report_id)
    name = str(data.get("name", ""))
    stem = name.rsplit("/", 1)[-1]
    return stem.rsplit(".", 1)[0]


@retry_with_backoff(max_attempts=4, base_delay=1.0, max_delay=10.0, operation_name="download_image")
def download_image(bucket: str, name: str) -> bytes:
    blob = get_storage().bucket(bucket).blob(name)
    return blob.download_as_bytes(timeout=60)


@retry_with_backoff(
    max_attempts=4,
    base_delay=1.5,
    max_delay=8.0,
    should_retry=lambda exc: isinstance(exc, LookupError),
    operation_name="load_report",
)
def load_report(report_id: str) -> Dict[str, Any]:
    """Read the report document, retrying briefly in case the gateway write is still propagating."""
    snapshot = get_firestore().collection(COLLECTION_REPORTS).document(report_id).get()
    if not snapshot.exists:
        raise LookupError(f"Report {report_id} not found in Firestore yet")
    data = snapshot.to_dict() or {}
    data["_id"] = snapshot.id
    return data


def _to_datetime(value: Any) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    if hasattr(value, "timestamp"):
        try:
            return dt.datetime.fromtimestamp(value.timestamp(), tz=dt.timezone.utc)
        except Exception:  # pragma: no cover - defensive
            pass
    return dt.datetime.now(tz=dt.timezone.utc)


def _location(report: Dict[str, Any]) -> tuple[Optional[float], Optional[float]]:
    location = report.get("location")
    if location is None:
        return None, None
    lat = getattr(location, "latitude", None)
    lon = getattr(location, "longitude", None)
    if lat is None and isinstance(location, dict):
        lat = location.get("latitude", location.get("lat"))
        lon = location.get("longitude", location.get("lng"))
    try:
        return (float(lat), float(lon)) if lat is not None and lon is not None else (None, None)
    except (TypeError, ValueError):
        return None, None


def build_bigquery_row(report: Dict[str, Any], analysis: GeminiAnalysis, image_uri: str, analyzed_at: dt.datetime) -> Dict[str, Any]:
    lat, lon = _location(report)
    geohash = report.get("geohash")
    if not geohash and lat is not None and lon is not None:
        geohash = encode_geohash(lat, lon, precision=7)
    import json

    return {
        "report_id": report["_id"],
        "phone_hash": report.get("phoneHash"),
        "message_sid": report.get("messageSid"),
        "received_at": _to_datetime(report.get("createdAt")),
        "analyzed_at": analyzed_at,
        "latitude": lat,
        "longitude": lon,
        "geohash": geohash,
        "location_source": report.get("locationSource"),
        "city": report.get("city"),
        "image_uri": image_uri,
        "caption": report.get("caption"),
        "is_outdoor_scene": analysis.is_outdoor_scene,
        "haze_index": analysis.haze_index,
        "visibility_km": analysis.visibility_km,
        "visibility_category": analysis.visibility_category,
        "sky_condition": analysis.sky_condition,
        "smoke_detected": analysis.smoke_detected,
        "dust_detected": analysis.dust_detected,
        "fog_or_mist_detected": analysis.fog_or_mist_detected,
        "open_burning_detected": analysis.open_burning_detected,
        "vehicle_density_score": analysis.vehicle_density_score,
        "construction_activity_score": analysis.construction_activity_score,
        "industrial_emission_score": analysis.industrial_emission_score,
        "pollution_sources": analysis.pollution_sources,
        "estimated_aqi_category": analysis.estimated_aqi_category,
        "estimated_aqi": analysis.estimated_aqi,
        "confidence": analysis.confidence,
        "model_name": analysis.model_name,
        "processing_latency_ms": analysis.latency_ms,
        "raw_analysis": json.dumps(analysis.raw, default=str),
    }


FEEDBACK_TEMPLATES = {
    "en": (
        "VayuSetu analysis for report {short_id}\n"
        "Haze index: {haze:.2f} ({haze_label})\n"
        "Estimated AQI: {aqi:.0f} ({aqi_label})\n"
        "Visibility: about {visibility:.1f} km\n"
        "Likely sources: {sources}\n"
        "Thank you for helping map air quality in {city}."
    ),
    "hi": (
        "VayuSetu रिपोर्ट {short_id} का विश्लेषण\n"
        "धुंध सूचकांक: {haze:.2f} ({haze_label})\n"
        "अनुमानित AQI: {aqi:.0f} ({aqi_label})\n"
        "दृश्यता: लगभग {visibility:.1f} किमी\n"
        "संभावित स्रोत: {sources}\n"
        "{city} में वायु गुणवत्ता मानचित्रण में सहयोग के लिए धन्यवाद।"
    ),
}

_HAZE_LABELS = {
    "en": [(0.25, "low"), (0.5, "moderate"), (0.75, "high"), (1.01, "very high")],
    "hi": [(0.25, "कम"), (0.5, "मध्यम"), (0.75, "अधिक"), (1.01, "बहुत अधिक")],
}

_SOURCE_LABELS_HI = {
    "vehicular": "वाहन",
    "industrial": "उद्योग",
    "construction_dust": "निर्माण धूल",
    "road_dust": "सड़क की धूल",
    "biomass_burning": "बायोमास जलाना",
    "waste_burning": "कचरा जलाना",
    "crop_residue_burning": "पराली जलाना",
    "fireworks": "आतिशबाजी",
    "natural_dust_storm": "धूल भरी आंधी",
    "unknown": "अज्ञात",
}


def compose_feedback(analysis: GeminiAnalysis, report: Dict[str, Any], language: str) -> str:
    lang = language if language in FEEDBACK_TEMPLATES else "en"
    haze_label = next(label for upper, label in _HAZE_LABELS[lang] if analysis.haze_index < upper)
    if lang == "hi":
        sources = ", ".join(_SOURCE_LABELS_HI.get(s, s) for s in analysis.pollution_sources)
    else:
        sources = ", ".join(s.replace("_", " ") for s in analysis.pollution_sources)
    if not analysis.is_outdoor_scene:
        if lang == "hi":
            return "यह फोटो बाहर के आसमान या सड़क की नहीं लगती। कृपया खुले आसमान या सड़क की फोटो भेजें।"
        return "This photo does not appear to show the outdoor sky or street. Please send a photo of the open sky or road."
    return FEEDBACK_TEMPLATES[lang].format(
        short_id=report["_id"][:8].upper(),
        haze=analysis.haze_index,
        haze_label=haze_label,
        aqi=analysis.estimated_aqi,
        aqi_label=aqi_category_label(analysis.estimated_aqi),
        visibility=analysis.visibility_km,
        sources=sources,
        city=report.get("city") or ("आपके क्षेत्र" if lang == "hi" else "your area"),
    )


def send_user_feedback(report: Dict[str, Any], analysis: GeminiAnalysis) -> None:
    if not env_bool("SEND_USER_FEEDBACK", False):
        return
    client = get_twilio()
    sender = env_str("TWILIO_WHATSAPP_FROM")
    phone_hash = report.get("phoneHash")
    if client is None or not sender or not phone_hash:
        return
    user_snapshot = get_firestore().collection(COLLECTION_USERS).document(str(phone_hash)).get()
    if not user_snapshot.exists:
        return
    user = user_snapshot.to_dict() or {}
    phone = user.get("phoneNumber")
    if not phone:
        return
    try:
        message = compose_feedback(analysis, report, str(user.get("language") or "en"))
        client.send_whatsapp(to=str(phone), from_=sender, body=message)
        logger.info("Sent analysis feedback to citizen", extra={"report_id": report["_id"]})
    except Exception as exc:  # noqa: BLE001 - feedback is best effort
        logger.warning("Failed to send citizen feedback: %s", exc, extra={"report_id": report["_id"]})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


@functions_framework.cloud_event
def process_citizen_image(cloud_event: CloudEvent) -> None:
    """Handle a Cloud Storage finalize event for a citizen image."""
    data: Dict[str, Any] = cloud_event.data or {}
    bucket = data.get("bucket")
    name = data.get("name")
    content_type = data.get("contentType")

    if not bucket or not should_process(name, content_type):
        logger.info("Ignoring object %s (%s)", name, content_type)
        return

    report_id = report_id_from_event(data)
    image_uri = f"gs://{bucket}/{name}"
    started = time.monotonic()
    logger.info("Processing citizen image", extra={"report_id": report_id, "image_uri": image_uri})

    firestore_client = get_firestore()
    from google.cloud import firestore

    report_ref = firestore_client.collection(COLLECTION_REPORTS).document(report_id)

    try:
        report = load_report(report_id)
    except LookupError:
        logger.error("No Firestore report found for %s; creating a minimal record", report_id, extra={"report_id": report_id})
        report_ref.set(
            {
                "status": "received",
                "imageUri": image_uri,
                "createdAt": firestore.SERVER_TIMESTAMP,
                "updatedAt": firestore.SERVER_TIMESTAMP,
                "locationSource": "unknown",
            },
            merge=True,
        )
        report = {"_id": report_id, "imageUri": image_uri, "createdAt": dt.datetime.now(tz=dt.timezone.utc)}

    if report.get("status") == "analyzed" and report.get("geminiAnalysis"):
        logger.info("Report already analysed; skipping duplicate event", extra={"report_id": report_id})
        return

    report_ref.set({"status": "analyzing", "updatedAt": firestore.SERVER_TIMESTAMP}, merge=True)

    try:
        raw_bytes = download_image(bucket, str(name))
        image_bytes, mime_type = prepare_image(raw_bytes, max_edge_px=env_int("MAX_IMAGE_EDGE_PX", 1024))
        context = {
            "city": report.get("city"),
            "caption": report.get("caption"),
            "local_time": _to_datetime(report.get("createdAt")).astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d %H:%M IST"),
        }
        analysis = get_analyzer().analyze(image_bytes, mime_type, context)
    except GeminiAnalysisError as exc:
        logger.error("Gemini analysis failed: %s", exc, extra={"report_id": report_id})
        report_ref.set(
            {"status": "failed", "error": str(exc)[:500], "updatedAt": firestore.SERVER_TIMESTAMP},
            merge=True,
        )
        return
    except Exception as exc:  # noqa: BLE001 - surface unexpected errors but keep the record consistent
        logger.exception("Unexpected failure while processing image", extra={"report_id": report_id})
        report_ref.set(
            {"status": "failed", "error": f"unexpected: {exc}"[:500], "updatedAt": firestore.SERVER_TIMESTAMP},
            merge=True,
        )
        raise

    analyzed_at = dt.datetime.now(tz=dt.timezone.utc)
    analysis_doc = analysis.to_dict()
    analysis_doc.pop("raw", None)

    # Indoor or otherwise unusable scenes keep their analysis for auditing but
    # expose no AQI signal, so dashboards and the batch predictor ignore them.
    outdoor = bool(analysis.is_outdoor_scene)
    report_ref.set(
        {
            "status": "analyzed",
            "analyzedAt": analyzed_at,
            "updatedAt": firestore.SERVER_TIMESTAMP,
            "imageUri": image_uri,
            "geminiAnalysis": analysis_doc,
            "isOutdoorScene": outdoor,
            "hazeIndex": analysis.haze_index if outdoor else None,
            "estimatedAqi": analysis.estimated_aqi if outdoor else None,
            "estimatedAqiCategory": analysis.estimated_aqi_category if outdoor else "not_applicable",
            "visibilityKm": analysis.visibility_km if outdoor else None,
            "pollutionSources": analysis.pollution_sources if outdoor else [],
            "modelName": analysis.model_name,
            "error": firestore.DELETE_FIELD,
        },
        merge=True,
    )

    try:
        get_bigquery_sink().write("citizen_reports", [build_bigquery_row(report, analysis, image_uri, analyzed_at)])
    except Exception as exc:  # noqa: BLE001 - warehouse write must not undo the Firestore update
        logger.error("BigQuery write failed: %s", exc, extra={"report_id": report_id})
        report_ref.set({"bigqueryStatus": "failed"}, merge=True)

    send_user_feedback(report, analysis)

    logger.info(
        "Citizen image processed",
        extra={
            "report_id": report_id,
            "model_name": analysis.model_name,
            "estimated_aqi": analysis.estimated_aqi,
            "haze_index": analysis.haze_index,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        },
    )
