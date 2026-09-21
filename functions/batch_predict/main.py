"""Cloud Function: batch_predict.

HTTP function invoked hourly by Cloud Scheduler (OIDC authenticated). It pulls
the last ``LOOKBACK_HOURS`` of fused observations from BigQuery (falling back
to Firestore), aggregates them into geohash cells, enriches each cell with
meteorological features, requests 12-hour AQI forecasts from the Cloud Run
prediction service and writes the resulting hotspots to Firestore (which in
turn triggers the alerting function) and BigQuery.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from typing import Any, Dict, List, Optional, Tuple

import functions_framework
from data_sources import BigQueryObservationSource, FirestoreObservationSource, filter_valid
from flask import Request, jsonify
from pipeline import (
    aggregate_by_cell,
    build_hotspot_documents,
    build_prediction_request,
    enrich_with_weather,
    hotspot_to_bigquery_row,
)
from prediction_client import PredictionClient, PredictionServiceError
from weather import build_weather_provider

from vayusetu_common import configure_logging, env_bool, env_float, env_int, env_str
from vayusetu_common.bigquery_sink import BigQuerySink

logger = configure_logging("batch-predict")

COLLECTION_HOTSPOTS = "predicted_hotspots"
COLLECTION_RUNS = "batch_runs"

_firestore_client: Any = None
_bigquery_sink: Optional[BigQuerySink] = None
_prediction_client: Optional[PredictionClient] = None


def get_firestore() -> Any:
    global _firestore_client
    if _firestore_client is None:
        from google.cloud import firestore

        _firestore_client = firestore.Client(project=env_str("GCP_PROJECT_ID"))
    return _firestore_client


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


def get_prediction_client() -> PredictionClient:
    global _prediction_client
    if _prediction_client is None:
        _prediction_client = PredictionClient(
            base_url=env_str("PREDICTION_SERVICE_URL", required=True) or "",
            use_auth=env_bool("PREDICTION_SERVICE_AUTH", True),
            timeout_seconds=float(env_int("PREDICTION_TIMEOUT_SECONDS", 90)),
        )
    return _prediction_client


def load_observations(since: dt.datetime, until: dt.datetime) -> Tuple[List[Dict[str, Any]], str]:
    """Return (observations, source_name) honouring DATA_SOURCE and fallback settings."""
    source = (env_str("DATA_SOURCE", "bigquery") or "bigquery").lower()
    fallback = env_bool("FALLBACK_TO_FIRESTORE", True)

    if source == "bigquery" and env_bool("BIGQUERY_ENABLED", True):
        try:
            bq = BigQueryObservationSource(env_str("GCP_PROJECT_ID", required=True) or "", env_str("BIGQUERY_DATASET", "vayusetu") or "vayusetu")
            observations = filter_valid(bq.fetch(since, until))
            if observations or not fallback:
                return observations, "bigquery"
            logger.info("BigQuery returned no rows; falling back to Firestore")
        except Exception as exc:  # noqa: BLE001 - degrade gracefully to Firestore
            if not fallback:
                raise
            logger.warning("BigQuery source failed (%s); falling back to Firestore", exc)

    observations = filter_valid(FirestoreObservationSource(get_firestore()).fetch(since, until))
    return observations, "firestore"


def write_hotspots(documents: List[Dict[str, Any]]) -> int:
    """Write hotspot documents to Firestore in batches of 400 and to BigQuery."""
    if not documents:
        return 0
    db = get_firestore()
    written = 0
    for start in range(0, len(documents), 400):
        batch = db.batch()
        for doc in documents[start : start + 400]:
            payload = {k: v for k, v in doc.items() if k != "_id"}
            batch.set(db.collection(COLLECTION_HOTSPOTS).document(doc["_id"]), payload)
        batch.commit()
        written += len(documents[start : start + 400])
    try:
        get_bigquery_sink().write("predicted_hotspots", [hotspot_to_bigquery_row(doc) for doc in documents])
    except Exception as exc:  # noqa: BLE001
        logger.error("BigQuery predicted_hotspots write failed: %s", exc)
    return written


def record_run(summary: Dict[str, Any]) -> None:
    try:
        run_id = summary["generated_at"].replace(":", "").replace("-", "")[:15]
        get_firestore().collection(COLLECTION_RUNS).document(run_id).set(summary)
    except Exception as exc:  # noqa: BLE001 - bookkeeping only
        logger.warning("Could not record batch run: %s", exc)


def run_batch_prediction(lookback_hours: Optional[int] = None, dry_run: bool = False, reference_time: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Execute one batch prediction cycle and return a JSON-serialisable summary."""
    started = time.monotonic()
    now = reference_time or dt.datetime.now(tz=dt.timezone.utc)
    hours = lookback_hours or env_int("LOOKBACK_HOURS", 6)
    since = now - dt.timedelta(hours=hours)
    precision = env_int("HOTSPOT_GEOHASH_PRECISION", 5)
    threshold = env_float("ALERT_AQI_THRESHOLD", 300.0)
    min_reports = env_int("MIN_REPORTS_PER_CELL", 1)

    observations, source = load_observations(since, now)
    aggregates = [a for a in aggregate_by_cell(observations, precision, now) if a.report_count >= min_reports]
    max_cells = env_int("MAX_CELLS_PER_RUN", 400)
    aggregates = aggregates[:max_cells]

    summary: Dict[str, Any] = {
        "generated_at": now.isoformat(),
        "lookback_hours": hours,
        "observation_source": source,
        "observations": len(observations),
        "cells": len(aggregates),
        "dry_run": dry_run,
    }

    if not aggregates:
        summary.update({"hotspots_written": 0, "alerts_pending": 0, "elapsed_ms": int((time.monotonic() - started) * 1000)})
        logger.info("No observations in window; nothing to predict", extra=summary)
        record_run(summary)
        return summary

    provider = build_weather_provider(env_str("WEATHER_PROVIDER", "open-meteo") or "open-meteo")
    summary["weather_source"] = provider.name
    summary["cells_with_weather"] = enrich_with_weather(aggregates, provider)

    try:
        response = get_prediction_client().predict(build_prediction_request(aggregates))
    except (PredictionServiceError, Exception) as exc:  # noqa: BLE001
        logger.error("Prediction service call failed: %s", exc)
        summary.update({"error": str(exc)[:500], "elapsed_ms": int((time.monotonic() - started) * 1000)})
        record_run(summary)
        raise

    documents = build_hotspot_documents(aggregates, response.get("predictions", []), now, threshold, provider.name)
    summary["model_version"] = response.get("model_version")
    summary["alerts_pending"] = sum(1 for d in documents if d["alertStatus"] == "pending")
    summary["max_predicted_aqi"] = max((d["predictedAqi"] for d in documents), default=None)
    summary["hotspots_written"] = 0 if dry_run else write_hotspots(documents)
    summary["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    if dry_run:
        summary["preview"] = [
            {"geohash": d["geohash"], "predictedAqi": d["predictedAqi"], "category": d["predictedCategory"], "reports": d["reportCount"]}
            for d in documents[:20]
        ]

    logger.info("Batch prediction complete", extra={k: v for k, v in summary.items() if k != "preview"})
    record_run({k: v for k, v in summary.items() if k != "preview"})
    return summary


@functions_framework.http
def batch_predict(request: Request):  # type: ignore[no-untyped-def]
    """HTTP entry point for Cloud Scheduler and manual invocation."""
    if request.method not in ("POST", "GET"):
        return jsonify({"error": "method not allowed"}), 405

    body: Dict[str, Any] = {}
    if request.method == "POST":
        try:
            body = request.get_json(silent=True) or {}
        except Exception:  # noqa: BLE001
            body = {}

    lookback = body.get("lookback_hours") or request.args.get("lookback_hours")
    dry_run = str(body.get("dry_run") or request.args.get("dry_run") or "false").lower() in {"1", "true", "yes"}

    try:
        summary = run_batch_prediction(lookback_hours=int(lookback) if lookback else None, dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001 - return a structured error and a 500 for Scheduler retry
        logger.exception("Batch prediction failed")
        return jsonify({"status": "error", "error": str(exc)[:500]}), 500

    return jsonify({"status": "ok", **json.loads(json.dumps(summary, default=str))}), 200
