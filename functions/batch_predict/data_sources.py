"""Observation sources for batch prediction.

The primary source is the BigQuery ``fused_observations`` view, which joins
Gemini and Earth Engine outputs. A Firestore source provides an equivalent
result set for the local emulator and as a resilience fallback.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Dict, Iterable, List, Optional

from vayusetu_common.retry import retry_with_backoff

logger = logging.getLogger(__name__)

# Normalised observation keys produced by every source.
OBSERVATION_KEYS = (
    "report_id",
    "timestamp",
    "latitude",
    "longitude",
    "geohash",
    "city",
    "haze_index",
    "visibility_km",
    "smoke_detected",
    "dust_detected",
    "open_burning_detected",
    "fog_or_mist_detected",
    "vehicle_density_score",
    "construction_activity_score",
    "industrial_emission_score",
    "estimated_aqi",
    "vision_confidence",
    "pollution_sources",
    "aer_ai",
    "no2_tropospheric_mol_m2",
    "co_column_mol_m2",
    "aod_047",
)


def _as_datetime(value: Any) -> Optional[dt.datetime]:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    if hasattr(value, "timestamp") and not isinstance(value, (int, float)):
        try:
            return dt.datetime.fromtimestamp(value.timestamp(), tz=dt.timezone.utc)
        except Exception:  # pragma: no cover - defensive
            return None
    if isinstance(value, str) and value:
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            return None
    return None


class BigQueryObservationSource:
    """Read recent fused observations from BigQuery."""

    def __init__(self, project_id: str, dataset_id: str, client: Optional[Any] = None) -> None:
        self.project_id = project_id
        self.dataset_id = dataset_id
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            from google.cloud import bigquery

            self._client = bigquery.Client(project=self.project_id)
        return self._client

    @retry_with_backoff(max_attempts=3, base_delay=2.0, max_delay=20.0, operation_name="bigquery_fetch_observations")
    def fetch(self, since: dt.datetime, until: dt.datetime) -> List[Dict[str, Any]]:
        from google.cloud import bigquery

        sql = f"""
            SELECT
              report_id,
              received_at AS timestamp,
              latitude,
              longitude,
              geohash,
              city,
              haze_index,
              visibility_km,
              smoke_detected,
              dust_detected,
              open_burning_detected,
              fog_or_mist_detected,
              vehicle_density_score,
              construction_activity_score,
              industrial_emission_score,
              estimated_aqi,
              vision_confidence,
              pollution_sources,
              aer_ai,
              no2_tropospheric_mol_m2,
              co_column_mol_m2,
              aod_047
            FROM `{self.project_id}.{self.dataset_id}.fused_observations`
            WHERE received_at BETWEEN @since AND @until
              AND latitude IS NOT NULL
              AND longitude IS NOT NULL
              AND COALESCE(is_outdoor_scene, TRUE)
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("since", "TIMESTAMP", since),
                bigquery.ScalarQueryParameter("until", "TIMESTAMP", until),
            ]
        )
        rows = self.client.query(sql, job_config=job_config).result(timeout=120)
        observations: List[Dict[str, Any]] = []
        for row in rows:
            record = {key: row.get(key) for key in OBSERVATION_KEYS}
            record["timestamp"] = _as_datetime(record["timestamp"])
            record["pollution_sources"] = list(record.get("pollution_sources") or [])
            observations.append(record)
        logger.info("BigQuery returned %d observation(s)", len(observations))
        return observations


class FirestoreObservationSource:
    """Read analysed reports directly from Firestore (emulator friendly)."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def fetch(self, since: dt.datetime, until: dt.datetime) -> List[Dict[str, Any]]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = (
            self.client.collection("citizen_reports")
            .where(filter=FieldFilter("status", "==", "analyzed"))
            .where(filter=FieldFilter("analyzedAt", ">=", since))
            .where(filter=FieldFilter("analyzedAt", "<=", until))
            .limit(5000)
        )
        observations: List[Dict[str, Any]] = []
        for snapshot in query.stream():
            data = snapshot.to_dict() or {}
            analysis = data.get("geminiAnalysis") or {}
            satellite = data.get("satelliteMetrics") or {}
            location = data.get("location")
            lat = getattr(location, "latitude", None)
            lon = getattr(location, "longitude", None)
            if lat is None and isinstance(location, dict):
                lat = location.get("latitude", location.get("lat"))
                lon = location.get("longitude", location.get("lng"))
            if lat is None or lon is None:
                continue
            if analysis.get("is_outdoor_scene") is False:
                continue
            observations.append(
                {
                    "report_id": snapshot.id,
                    "timestamp": _as_datetime(data.get("createdAt")) or _as_datetime(data.get("analyzedAt")),
                    "latitude": float(lat),
                    "longitude": float(lon),
                    "geohash": data.get("geohash"),
                    "city": data.get("city"),
                    "haze_index": analysis.get("haze_index", data.get("hazeIndex")),
                    "visibility_km": analysis.get("visibility_km", data.get("visibilityKm")),
                    "smoke_detected": analysis.get("smoke_detected"),
                    "dust_detected": analysis.get("dust_detected"),
                    "open_burning_detected": analysis.get("open_burning_detected"),
                    "fog_or_mist_detected": analysis.get("fog_or_mist_detected"),
                    "vehicle_density_score": analysis.get("vehicle_density_score"),
                    "construction_activity_score": analysis.get("construction_activity_score"),
                    "industrial_emission_score": analysis.get("industrial_emission_score"),
                    "estimated_aqi": analysis.get("estimated_aqi", data.get("estimatedAqi")),
                    "vision_confidence": analysis.get("confidence"),
                    "pollution_sources": list(analysis.get("pollution_sources") or data.get("pollutionSources") or []),
                    "aer_ai": satellite.get("aerAi"),
                    "no2_tropospheric_mol_m2": satellite.get("no2TroposphericMolM2"),
                    "co_column_mol_m2": satellite.get("coColumnMolM2"),
                    "aod_047": satellite.get("aod047"),
                }
            )
        logger.info("Firestore returned %d observation(s)", len(observations))
        return observations


def filter_valid(observations: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop observations that lack the minimum signal needed for aggregation."""
    valid: List[Dict[str, Any]] = []
    for obs in observations:
        if obs.get("latitude") is None or obs.get("longitude") is None or obs.get("timestamp") is None:
            continue
        if obs.get("haze_index") is None and obs.get("estimated_aqi") is None:
            continue
        valid.append(obs)
    return valid
