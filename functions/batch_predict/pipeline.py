"""Batch prediction pipeline: aggregate, enrich, predict, persist."""

from __future__ import annotations

import datetime as dt
import json
import logging
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from weather import WeatherProvider

from vayusetu_common.aqi import aqi_category
from vayusetu_common.geo import decode_geohash_center, encode_geohash

logger = logging.getLogger(__name__)


@dataclass
class CellAggregate:
    geohash: str
    latitude: float
    longitude: float
    city: Optional[str]
    timestamp: dt.datetime
    report_count: int
    features: Dict[str, float]
    dominant_sources: List[str]
    has_satellite: bool
    report_ids: List[str] = field(default_factory=list)


def _mean(values: Iterable[Optional[float]]) -> Optional[float]:
    cleaned = [float(v) for v in values if v is not None]
    return statistics.fmean(cleaned) if cleaned else None


def _ratio(values: Iterable[Optional[bool]]) -> float:
    items = [bool(v) for v in values if v is not None]
    return sum(items) / len(items) if items else 0.0


def aggregate_by_cell(observations: List[Dict[str, Any]], precision: int, reference_time: dt.datetime) -> List[CellAggregate]:
    """Aggregate observations into geohash cells of ``precision`` characters."""
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for obs in observations:
        geohash = obs.get("geohash")
        if not geohash or len(geohash) < precision:
            geohash = encode_geohash(float(obs["latitude"]), float(obs["longitude"]), precision=max(precision, 7))
        buckets[geohash[:precision]].append(obs)

    aggregates: List[CellAggregate] = []
    for cell, items in buckets.items():
        lat = _mean(o.get("latitude") for o in items)
        lon = _mean(o.get("longitude") for o in items)
        if lat is None or lon is None:
            lat, lon = decode_geohash_center(cell)
        sources = Counter(src for o in items for src in (o.get("pollution_sources") or []) if src and src != "unknown")
        cities = Counter(o.get("city") for o in items if o.get("city"))
        features: Dict[str, float] = {}
        mapping = {
            "haze_index": "haze_index",
            "visibility_km": "visibility_km",
            "vehicle_density_score": "vehicle_density_score",
            "construction_activity_score": "construction_activity_score",
            "industrial_emission_score": "industrial_emission_score",
            "vision_aqi_estimate": "estimated_aqi",
            "vision_confidence": "vision_confidence",
            "aer_ai": "aer_ai",
            "no2_tropospheric_mol_m2": "no2_tropospheric_mol_m2",
            "co_column_mol_m2": "co_column_mol_m2",
            "aod_047": "aod_047",
        }
        for feature_name, source_key in mapping.items():
            value = _mean(o.get(source_key) for o in items)
            if value is not None:
                features[feature_name] = round(value, 6)
        features["smoke_ratio"] = round(_ratio(o.get("smoke_detected") for o in items), 3)
        features["dust_ratio"] = round(_ratio(o.get("dust_detected") for o in items), 3)
        features["open_burning_ratio"] = round(_ratio(o.get("open_burning_detected") for o in items), 3)
        features["fog_ratio"] = round(_ratio(o.get("fog_or_mist_detected") for o in items), 3)
        features["report_count"] = float(len(items))

        aggregates.append(
            CellAggregate(
                geohash=cell,
                latitude=round(lat, 5),
                longitude=round(lon, 5),
                city=cities.most_common(1)[0][0] if cities else None,
                timestamp=reference_time,
                report_count=len(items),
                features=features,
                dominant_sources=[name for name, _ in sources.most_common(3)],
                has_satellite=any(o.get("aer_ai") is not None or o.get("aod_047") is not None for o in items),
                report_ids=[str(o.get("report_id")) for o in items if o.get("report_id")],
            )
        )
    aggregates.sort(key=lambda a: a.report_count, reverse=True)
    return aggregates


def enrich_with_weather(aggregates: List[CellAggregate], provider: WeatherProvider) -> int:
    """Attach meteorological features in place; returns the number of cells enriched."""
    enriched = 0
    for aggregate in aggregates:
        weather = provider.current(aggregate.latitude, aggregate.longitude, aggregate.timestamp)
        if weather:
            aggregate.features.update({k: float(v) for k, v in weather.items()})
            enriched += 1
    return enriched


def build_prediction_request(aggregates: List[CellAggregate]) -> Dict[str, Any]:
    return {
        "observations": [
            {
                "geohash": a.geohash,
                "latitude": a.latitude,
                "longitude": a.longitude,
                "timestamp": a.timestamp.isoformat(),
                "city": a.city,
                "features": a.features,
            }
            for a in aggregates
        ],
        "include_features": False,
    }


def build_hotspot_documents(
    aggregates: List[CellAggregate],
    predictions: List[Dict[str, Any]],
    generated_at: dt.datetime,
    alert_threshold: float,
    weather_source: str,
) -> List[Dict[str, Any]]:
    """Merge predictions with aggregates into Firestore-ready hotspot documents."""
    by_cell = {p["geohash"]: p for p in predictions}
    documents: List[Dict[str, Any]] = []
    stamp = generated_at.strftime("%Y%m%dT%H%M")
    for aggregate in aggregates:
        prediction = by_cell.get(aggregate.geohash)
        if prediction is None:
            logger.warning("No prediction returned for cell %s", aggregate.geohash)
            continue
        predicted = float(prediction["predicted_aqi"])
        forecast_for = prediction.get("forecast_for")
        forecast_dt = dt.datetime.fromisoformat(str(forecast_for).replace("Z", "+00:00")) if forecast_for else generated_at + dt.timedelta(hours=12)
        documents.append(
            {
                "_id": f"{aggregate.geohash}_{stamp}",
                "geohash": aggregate.geohash,
                "latitude": aggregate.latitude,
                "longitude": aggregate.longitude,
                "city": aggregate.city,
                "generatedAt": generated_at,
                "forecastFor": forecast_dt,
                "horizonHours": int(prediction.get("horizon_hours", 12)),
                "predictedAqi": round(predicted, 1),
                "predictedCategory": prediction.get("predicted_category") or aqi_category(predicted),
                "currentAqiEstimate": aggregate.features.get("vision_aqi_estimate"),
                "reportCount": aggregate.report_count,
                "confidence": float(prediction.get("confidence", 0.5)),
                "modelVersion": prediction.get("model_version", "unknown"),
                "dominantSources": aggregate.dominant_sources,
                "features": {k: round(float(v), 6) for k, v in aggregate.features.items()},
                "weatherSource": weather_source,
                "hasSatellite": aggregate.has_satellite,
                "reportIds": aggregate.report_ids[:50],
                "alertStatus": "pending" if predicted >= alert_threshold else "not_required",
                "alertThreshold": alert_threshold,
            }
        )
    return documents


def hotspot_to_bigquery_row(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "hotspot_id": doc["_id"],
        "geohash": doc["geohash"],
        "latitude": doc["latitude"],
        "longitude": doc["longitude"],
        "city": doc.get("city"),
        "generated_at": doc["generatedAt"],
        "forecast_for": doc["forecastFor"],
        "horizon_hours": doc["horizonHours"],
        "predicted_aqi": doc["predictedAqi"],
        "predicted_category": doc["predictedCategory"],
        "current_aqi_estimate": doc.get("currentAqiEstimate"),
        "report_count": doc["reportCount"],
        "confidence": doc["confidence"],
        "model_version": doc["modelVersion"],
        "alert_triggered": doc["alertStatus"] == "pending",
        "features": json.dumps(doc["features"], default=str),
    }
