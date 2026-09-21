"""Cloud Function: fetch_gee_metrics.

Triggered by ``google.cloud.firestore.document.v1.created`` events on
``citizen_reports/{reportId}``. Fetches Sentinel-5P aerosol, NO2, CO, SO2 and
MODIS AOD metrics around the report location from Google Earth Engine and
persists them to Firestore and BigQuery. Runs concurrently with the Gemini
vision function; the two streams are joined in the BigQuery
``fused_observations`` view.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Optional

import functions_framework
from cloudevents.http import CloudEvent
from gee_client import EarthEngineClient, EarthEngineError, SatelliteMetrics, mock_metrics

from vayusetu_common import configure_logging, encode_geohash, env_bool, env_int, env_str
from vayusetu_common.bigquery_sink import BigQuerySink
from vayusetu_common.firestore_events import document_id_from_path, extract_document_path

logger = configure_logging("fetch-gee-metrics")

COLLECTION_REPORTS = "citizen_reports"

_firestore_client: Any = None
_gee_client: Optional[EarthEngineClient] = None
_bigquery_sink: Optional[BigQuerySink] = None


def get_firestore() -> Any:
    global _firestore_client
    if _firestore_client is None:
        from google.cloud import firestore

        _firestore_client = firestore.Client(project=env_str("GCP_PROJECT_ID"))
    return _firestore_client


def get_gee_client() -> EarthEngineClient:
    global _gee_client
    if _gee_client is None:
        _gee_client = EarthEngineClient(
            project=env_str("GEE_PROJECT") or env_str("GCP_PROJECT_ID", required=True) or "",
            buffer_radius_m=env_int("GEE_BUFFER_METERS", 5000),
            lookback_days=env_int("GEE_LOOKBACK_DAYS", 3),
            use_high_volume=env_bool("GEE_USE_HIGH_VOLUME_ENDPOINT", True),
        )
    return _gee_client


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


def extract_location(report: Dict[str, Any]) -> Optional[tuple[float, float]]:
    """Return (latitude, longitude) from a GeoPoint or mapping, if present and valid."""
    location = report.get("location")
    if location is None:
        return None
    lat = getattr(location, "latitude", None)
    lon = getattr(location, "longitude", None)
    if lat is None and isinstance(location, dict):
        lat = location.get("latitude", location.get("lat"))
        lon = location.get("longitude", location.get("lng"))
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat_f <= 90 and -180 <= lon_f <= 180):
        return None
    return lat_f, lon_f


def resolve_observed_at(report: Dict[str, Any]) -> dt.datetime:
    value = report.get("capturedAt") or report.get("createdAt")
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    if hasattr(value, "timestamp"):
        try:
            return dt.datetime.fromtimestamp(value.timestamp(), tz=dt.timezone.utc)
        except Exception:  # pragma: no cover - defensive
            pass
    return dt.datetime.now(tz=dt.timezone.utc)


def fetch_with_fallback(latitude: float, longitude: float, observed_at: dt.datetime) -> SatelliteMetrics:
    """Query Earth Engine, falling back to deterministic mock data when configured."""
    if env_bool("GEE_MOCK", False):
        return mock_metrics(latitude, longitude, observed_at, env_int("GEE_BUFFER_METERS", 5000), env_int("GEE_LOOKBACK_DAYS", 3))
    try:
        return get_gee_client().fetch_metrics(latitude, longitude, observed_at)
    except EarthEngineError as exc:
        if env_bool("GEE_ALLOW_MOCK_FALLBACK", False):
            logger.warning("Earth Engine unavailable (%s); using mock metrics", exc)
            return mock_metrics(latitude, longitude, observed_at, env_int("GEE_BUFFER_METERS", 5000), env_int("GEE_LOOKBACK_DAYS", 3))
        raise


def build_firestore_payload(metrics: SatelliteMetrics) -> Dict[str, Any]:
    return {
        "aerAi": metrics.aer_ai,
        "no2TroposphericMolM2": metrics.no2_tropospheric_mol_m2,
        "coColumnMolM2": metrics.co_column_mol_m2,
        "so2ColumnMolM2": metrics.so2_column_mol_m2,
        "aod047": metrics.aod_047,
        "s5pImageCount": metrics.s5p_image_count,
        "modisImageCount": metrics.modis_image_count,
        "windowStart": metrics.window_start,
        "windowEnd": metrics.window_end,
        "bufferRadiusM": metrics.buffer_radius_m,
        "lookbackDays": metrics.lookback_days,
        "source": metrics.source,
    }


def build_bigquery_row(report_id: str, report: Dict[str, Any], latitude: float, longitude: float, observed_at: dt.datetime, metrics: SatelliteMetrics, fetched_at: dt.datetime) -> Dict[str, Any]:
    return {
        "report_id": report_id,
        "observed_at": observed_at,
        "fetched_at": fetched_at,
        "latitude": latitude,
        "longitude": longitude,
        "geohash": report.get("geohash") or encode_geohash(latitude, longitude, precision=7),
        "buffer_radius_m": metrics.buffer_radius_m,
        "lookback_days": metrics.lookback_days,
        "aer_ai": metrics.aer_ai,
        "no2_tropospheric_mol_m2": metrics.no2_tropospheric_mol_m2,
        "co_column_mol_m2": metrics.co_column_mol_m2,
        "so2_column_mol_m2": metrics.so2_column_mol_m2,
        "aod_047": metrics.aod_047,
        "s5p_image_count": metrics.s5p_image_count,
        "modis_image_count": metrics.modis_image_count,
        "source": metrics.source,
    }


@functions_framework.cloud_event
def fetch_gee_metrics(cloud_event: CloudEvent) -> None:
    """Handle a Firestore document-created event for a citizen report."""
    from google.cloud import firestore

    try:
        document_path = extract_document_path(cloud_event)
    except ValueError as exc:
        logger.error("Cannot decode Firestore event: %s", exc)
        return

    report_id = document_id_from_path(document_path)
    if not document_path.startswith(f"{COLLECTION_REPORTS}/"):
        logger.info("Ignoring event for %s", document_path)
        return

    report_ref = get_firestore().collection(COLLECTION_REPORTS).document(report_id)
    snapshot = report_ref.get()
    if not snapshot.exists:
        logger.warning("Report %s no longer exists", report_id, extra={"report_id": report_id})
        return
    report = snapshot.to_dict() or {}

    if report.get("satelliteMetrics"):
        logger.info("Satellite metrics already present; skipping", extra={"report_id": report_id})
        return

    location = extract_location(report)
    if location is None:
        logger.info("Report has no usable location; skipping satellite lookup", extra={"report_id": report_id})
        report_ref.set({"satelliteStatus": "skipped_no_location", "updatedAt": firestore.SERVER_TIMESTAMP}, merge=True)
        return

    latitude, longitude = location
    observed_at = resolve_observed_at(report)
    logger.info(
        "Fetching satellite metrics",
        extra={"report_id": report_id, "latitude": latitude, "longitude": longitude, "observed_at": observed_at.isoformat()},
    )

    try:
        metrics = fetch_with_fallback(latitude, longitude, observed_at)
    except EarthEngineError as exc:
        logger.error("Earth Engine lookup failed: %s", exc, extra={"report_id": report_id})
        report_ref.set(
            {"satelliteStatus": "failed", "satelliteError": str(exc)[:500], "updatedAt": firestore.SERVER_TIMESTAMP},
            merge=True,
        )
        return

    fetched_at = dt.datetime.now(tz=dt.timezone.utc)
    report_ref.set(
        {
            "satelliteMetrics": build_firestore_payload(metrics),
            "satelliteStatus": "fetched",
            "satelliteFetchedAt": fetched_at,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )

    try:
        get_bigquery_sink().write(
            "satellite_metrics",
            [build_bigquery_row(report_id, report, latitude, longitude, observed_at, metrics, fetched_at)],
        )
    except Exception as exc:  # noqa: BLE001 - keep Firestore state authoritative
        logger.error("BigQuery write failed: %s", exc, extra={"report_id": report_id})
        report_ref.set({"satelliteBigqueryStatus": "failed"}, merge=True)

    logger.info(
        "Satellite metrics stored",
        extra={"report_id": report_id, "source": metrics.source, "aer_ai": metrics.aer_ai, "aod_047": metrics.aod_047},
    )
