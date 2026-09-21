"""Cloud Function: send_authority_alerts.

Triggered by ``google.cloud.firestore.document.v1.created`` events on
``predicted_hotspots/{hotspotId}``. When the predicted 12-hour AQI reaches the
configured threshold (default 300, the CPCB "Very Poor" boundary) the function:

1. claims the hotspot atomically so duplicate deliveries send nothing twice;
2. enforces a per-cell cooldown so authorities are not paged every hour;
3. resolves the responsible authorities from Firestore by geohash coverage;
4. translates the alert with Cloud Translation, synthesises speech with Cloud
   Text-to-Speech, stores the audio in Cloud Storage and places a Twilio voice
   call plus a WhatsApp message per authority;
5. records every attempt in Firestore and BigQuery for audit.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Dict, List, Optional

import functions_framework
from cloudevents.http import CloudEvent
from messaging import build_play_twiml, build_say_twiml, compose_alert_text, compose_whatsapp_text
from translation import LANGUAGE_VOICES, SpeechSynthesizer, Translator, normalise_language

from vayusetu_common import configure_logging, env_bool, env_float, env_int, env_str
from vayusetu_common.bigquery_sink import BigQuerySink
from vayusetu_common.firestore_events import document_id_from_path, extract_document_path
from vayusetu_common.retry import retry_with_backoff
from vayusetu_common.twilio_client import TwilioRestClient

logger = configure_logging("send-authority-alerts")

COLLECTION_HOTSPOTS = "predicted_hotspots"
COLLECTION_AUTHORITIES = "authorities"
COLLECTION_ALERT_LOG = "alert_log"
COLLECTION_ALERT_STATE = "alert_state"

_firestore_client: Any = None
_storage_client: Any = None
_translator: Optional[Translator] = None
_synthesizer: Optional[SpeechSynthesizer] = None
_twilio: Optional[TwilioRestClient] = None
_bigquery_sink: Optional[BigQuerySink] = None


# ---------------------------------------------------------------------------
# Lazy clients
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


def get_translator() -> Translator:
    global _translator
    if _translator is None:
        _translator = Translator(mock=env_bool("ALERTS_MOCK_GOOGLE_APIS", False))
    return _translator


def get_synthesizer() -> SpeechSynthesizer:
    global _synthesizer
    if _synthesizer is None:
        _synthesizer = SpeechSynthesizer(
            voice_tier=env_str("TTS_VOICE_TIER", "standard") or "standard",
            mock=env_bool("ALERTS_MOCK_GOOGLE_APIS", False),
            speaking_rate=env_float("TTS_SPEAKING_RATE", 0.92),
        )
    return _synthesizer


def get_twilio() -> TwilioRestClient:
    global _twilio
    if _twilio is None:
        _twilio = TwilioRestClient(
            account_sid=env_str("TWILIO_ACCOUNT_SID", required=True) or "",
            auth_token=env_str("TWILIO_AUTH_TOKEN", required=True) or "",
            base_url=env_str("TWILIO_API_BASE_URL", "https://api.twilio.com") or "https://api.twilio.com",
        )
    return _twilio


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


# ---------------------------------------------------------------------------
# Domain logic
# ---------------------------------------------------------------------------


def claim_hotspot(hotspot_ref: Any) -> Optional[Dict[str, Any]]:
    """Atomically mark the hotspot as being processed; returns None if already claimed."""
    from google.cloud import firestore

    db = get_firestore()
    transaction = db.transaction()

    @firestore.transactional
    def _claim(txn: Any) -> Optional[Dict[str, Any]]:
        snapshot = hotspot_ref.get(transaction=txn)
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        if data.get("alertStatus") in {"processing", "sent", "no_recipients", "suppressed_cooldown", "below_threshold"}:
            return None
        txn.set(hotspot_ref, {"alertStatus": "processing", "alertClaimedAt": firestore.SERVER_TIMESTAMP}, merge=True)
        data["_id"] = snapshot.id
        return data

    return _claim(transaction)


def within_cooldown(geohash: str, now: dt.datetime, cooldown_minutes: int) -> bool:
    if cooldown_minutes <= 0:
        return False
    snapshot = get_firestore().collection(COLLECTION_ALERT_STATE).document(geohash).get()
    if not snapshot.exists:
        return False
    last = (snapshot.to_dict() or {}).get("lastAlertAt")
    if not isinstance(last, dt.datetime):
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=dt.timezone.utc)
    return (now - last) < dt.timedelta(minutes=cooldown_minutes)


def find_authorities(geohash: str) -> List[Dict[str, Any]]:
    """Return active authorities whose coverage includes the hotspot cell.

    Coverage is expressed as geohash prefixes (precision 3-6) or the wildcard
    ``*`` for state or national control rooms.
    """
    from google.cloud.firestore_v1.base_query import FieldFilter

    prefixes = sorted({geohash[:n] for n in range(3, min(len(geohash), 6) + 1)} | {"*"}, key=len, reverse=True)
    query = (
        get_firestore()
        .collection(COLLECTION_AUTHORITIES)
        .where(filter=FieldFilter("active", "==", True))
        .where(filter=FieldFilter("coverageGeohashes", "array_contains_any", prefixes[:30]))
    )
    authorities: List[Dict[str, Any]] = []
    for snapshot in query.stream():
        data = snapshot.to_dict() or {}
        data["_id"] = snapshot.id
        authorities.append(data)
    # Most specific coverage first, then by priority.
    authorities.sort(key=lambda a: (-max((len(p) for p in a.get("coverageGeohashes", []) if p != "*"), default=0), int(a.get("priority", 100))))
    return authorities


@retry_with_backoff(max_attempts=3, base_delay=1.0, max_delay=8.0, operation_name="upload_alert_audio")
def upload_audio(bucket_name: str, object_name: str, audio_bytes: bytes, content_type: str) -> str:
    """Upload audio and return a signed URL valid for 24 hours."""
    bucket = get_storage().bucket(bucket_name)
    blob = bucket.blob(object_name)
    blob.upload_from_string(audio_bytes, content_type=content_type)

    import google.auth
    from google.auth.transport import requests as ga_requests

    credentials, _ = google.auth.default()
    credentials.refresh(ga_requests.Request())
    service_account_email = getattr(credentials, "service_account_email", None)
    signing_kwargs: Dict[str, Any] = {}
    if service_account_email and service_account_email != "default":
        signing_kwargs = {"service_account_email": service_account_email, "access_token": credentials.token}
    return blob.generate_signed_url(version="v4", expiration=dt.timedelta(hours=24), method="GET", **signing_kwargs)


def dispatch_to_authority(hotspot: Dict[str, Any], authority: Dict[str, Any], now: dt.datetime) -> List[Dict[str, Any]]:
    """Translate, synthesise and deliver the alert to one authority; returns log rows."""
    language = normalise_language(authority.get("language"))
    english_text = compose_alert_text(hotspot, authority)
    translated = get_translator().translate(english_text, language)
    locale = LANGUAGE_VOICES[language]["locale"]
    rows: List[Dict[str, Any]] = []
    base_row = {
        "hotspot_id": hotspot["_id"],
        "geohash": hotspot.get("geohash"),
        "predicted_aqi": float(hotspot.get("predictedAqi") or 0),
        "authority_id": authority["_id"],
        "authority_name": authority.get("name"),
        "language": locale,
        "message_text": translated.text,
        "sent_at": now,
    }

    channels = set(authority.get("channels") or ["voice", "whatsapp"])
    dry_run = env_bool("ALERTS_DRY_RUN", False)

    if "voice" in channels and authority.get("phone"):
        row = dict(base_row, alert_id=str(uuid.uuid4()), channel="voice")
        try:
            twiml: str
            speech = get_synthesizer().synthesize(translated.text, language)
            if speech is not None and env_str("ALERT_AUDIO_BUCKET"):
                object_name = f"alerts/{hotspot['_id']}/{authority['_id']}-{language}.mp3"
                audio_url = upload_audio(env_str("ALERT_AUDIO_BUCKET") or "", object_name, speech.audio_bytes, speech.content_type)
                twiml = build_play_twiml(audio_url)
            else:
                twiml = build_say_twiml(translated.text, locale)
            if dry_run:
                row.update(status="skipped", twilio_sid=None, error="dry run")
            else:
                result = get_twilio().create_call(
                    to=str(authority["phone"]),
                    from_=env_str("TWILIO_VOICE_FROM", required=True) or "",
                    twiml=twiml,
                )
                row.update(status="sent", twilio_sid=result.sid)
        except Exception as exc:  # noqa: BLE001 - one channel failing must not block the other
            logger.error("Voice alert failed for %s: %s", authority["_id"], exc, extra={"hotspot_id": hotspot["_id"]})
            row.update(status="failed", twilio_sid=None, error=str(exc)[:500])
        rows.append(row)

    whatsapp_number = authority.get("whatsapp") or authority.get("phone")
    if "whatsapp" in channels and whatsapp_number:
        row = dict(base_row, alert_id=str(uuid.uuid4()), channel="whatsapp")
        try:
            body = compose_whatsapp_text(hotspot, authority, translated.text, env_str("DASHBOARD_URL"))
            if dry_run:
                row.update(status="skipped", twilio_sid=None, error="dry run")
            else:
                result = get_twilio().send_whatsapp(
                    to=str(whatsapp_number),
                    from_=env_str("TWILIO_WHATSAPP_FROM", required=True) or "",
                    body=body,
                )
                row.update(status="sent", twilio_sid=result.sid)
        except Exception as exc:  # noqa: BLE001
            logger.error("WhatsApp alert failed for %s: %s", authority["_id"], exc, extra={"hotspot_id": hotspot["_id"]})
            row.update(status="failed", twilio_sid=None, error=str(exc)[:500])
        rows.append(row)

    return rows


def persist_alert_log(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    db = get_firestore()
    batch = db.batch()
    for row in rows:
        doc = {
            "hotspotId": row["hotspot_id"],
            "geohash": row.get("geohash"),
            "predictedAqi": row.get("predicted_aqi"),
            "authorityId": row.get("authority_id"),
            "authorityName": row.get("authority_name"),
            "channel": row.get("channel"),
            "language": row.get("language"),
            "twilioSid": row.get("twilio_sid"),
            "status": row.get("status"),
            "messageText": row.get("message_text"),
            "error": row.get("error"),
            "sentAt": row["sent_at"],
        }
        batch.set(db.collection(COLLECTION_ALERT_LOG).document(row["alert_id"]), doc)
    batch.commit()
    try:
        get_bigquery_sink().write("alert_log", rows)
    except Exception as exc:  # noqa: BLE001
        logger.error("BigQuery alert_log write failed: %s", exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


@functions_framework.cloud_event
def send_authority_alerts(cloud_event: CloudEvent) -> None:
    """Handle a Firestore document-created event for a predicted hotspot."""
    from google.cloud import firestore

    try:
        document_path = extract_document_path(cloud_event)
    except ValueError as exc:
        logger.error("Cannot decode Firestore event: %s", exc)
        return
    if not document_path.startswith(f"{COLLECTION_HOTSPOTS}/"):
        logger.info("Ignoring event for %s", document_path)
        return

    hotspot_id = document_id_from_path(document_path)
    db = get_firestore()
    hotspot_ref = db.collection(COLLECTION_HOTSPOTS).document(hotspot_id)
    threshold = env_float("ALERT_AQI_THRESHOLD", 300.0)

    snapshot = hotspot_ref.get()
    if not snapshot.exists:
        logger.warning("Hotspot %s no longer exists", hotspot_id)
        return
    preview = snapshot.to_dict() or {}
    predicted = float(preview.get("predictedAqi") or 0)
    if predicted < threshold:
        hotspot_ref.set({"alertStatus": "below_threshold"}, merge=True)
        logger.info("Predicted AQI %.0f below threshold %.0f", predicted, threshold, extra={"hotspot_id": hotspot_id})
        return

    hotspot = claim_hotspot(hotspot_ref)
    if hotspot is None:
        logger.info("Hotspot already claimed or processed", extra={"hotspot_id": hotspot_id})
        return

    now = dt.datetime.now(tz=dt.timezone.utc)
    geohash = str(hotspot.get("geohash") or "")
    cooldown = env_int("ALERT_COOLDOWN_MINUTES", 180)
    if geohash and within_cooldown(geohash, now, cooldown):
        hotspot_ref.set({"alertStatus": "suppressed_cooldown", "alertedAt": now}, merge=True)
        logger.info("Alert suppressed by cooldown", extra={"hotspot_id": hotspot_id, "geohash": geohash})
        return

    authorities = find_authorities(geohash) if geohash else []
    if not authorities:
        hotspot_ref.set({"alertStatus": "no_recipients", "alertedAt": now}, merge=True)
        logger.warning("No authorities cover cell %s", geohash, extra={"hotspot_id": hotspot_id})
        return

    max_recipients = env_int("ALERT_MAX_RECIPIENTS", 5)
    all_rows: List[Dict[str, Any]] = []
    for authority in authorities[:max_recipients]:
        all_rows.extend(dispatch_to_authority(hotspot, authority, now))

    persist_alert_log(all_rows)

    sent = [r for r in all_rows if r["status"] == "sent"]
    status = "sent" if sent else ("skipped" if all(r["status"] == "skipped" for r in all_rows) else "failed")
    hotspot_ref.set(
        {
            "alertStatus": status,
            "alertedAt": now,
            "alertRecipients": sorted({r["authority_id"] for r in sent}),
            "alertChannels": sorted({r["channel"] for r in sent}),
            "alertLanguages": sorted({r["language"] for r in sent}),
            "updatedAt": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )
    if sent and geohash:
        db.collection(COLLECTION_ALERT_STATE).document(geohash).set(
            {"lastAlertAt": now, "lastPredictedAqi": predicted, "lastHotspotId": hotspot_id}, merge=True
        )

    logger.info(
        "Authority alerting complete",
        extra={
            "hotspot_id": hotspot_id,
            "geohash": geohash,
            "predicted_aqi": predicted,
            "recipients": len(authorities[:max_recipients]),
            "sent": len(sent),
            "status": status,
        },
    )
