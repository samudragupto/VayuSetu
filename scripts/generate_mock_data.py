#!/usr/bin/env python3
"""Populate the Firestore emulator with a realistic escalating pollution event.

The generator writes the same document shapes produced by the API gateway,
the Gemini vision function, the Earth Engine function, the batch predictor
and the alerting function, so the dashboard and every downstream component
behave exactly as they would with live traffic.

Scenario
--------
A post-harvest winter smog episode builds over Delhi NCR across the chosen
time window: the average estimated AQI climbs from the "poor" band into the
"severe" band while crop residue burning and waste burning become the
dominant sources reported by citizens. Background cities (Mumbai, Bengaluru,
Kolkata, Kanpur and others) contribute stable, lower readings so that maps
and charts show contrast.

Usage
-----
    export FIRESTORE_EMULATOR_HOST=localhost:8080
    python scripts/generate_mock_data.py --reports 500 --hours 48 --clear

    # Preview without writing anything
    python scripts/generate_mock_data.py --dry-run --json-out /tmp/mock.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import logging
import math
import os
import random
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "functions", "common"))

from vayusetu_common.aqi import aqi_category  # noqa: E402
from vayusetu_common.geo import encode_geohash  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("generate_mock_data")

MODEL_NAME = "gemini-1.5-flash"
MODEL_VERSION = "xgboost-1.0.0-synthetic"

# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------


@dataclass
class CityProfile:
    name: str
    state: str
    latitude: float
    longitude: float
    weight: float
    baseline_aqi: float
    escalation: float  # additional AQI reached at the peak of the event
    sources: Sequence[Tuple[str, float]]  # (source, base probability)
    spread_km: float = 9.0


CITIES: List[CityProfile] = [
    CityProfile("New Delhi", "Delhi", 28.6139, 77.2090, 0.30, 165, 265, [("vehicular", 0.8), ("crop_residue_burning", 0.35), ("waste_burning", 0.3), ("construction_dust", 0.4), ("industrial", 0.2)], 6.0),
    CityProfile("Noida", "Uttar Pradesh", 28.5355, 77.3910, 0.10, 175, 250, [("vehicular", 0.7), ("construction_dust", 0.6), ("crop_residue_burning", 0.35), ("waste_burning", 0.25)], 4.0),
    CityProfile("Gurugram", "Haryana", 28.4595, 77.0266, 0.10, 160, 240, [("vehicular", 0.85), ("construction_dust", 0.55), ("crop_residue_burning", 0.3), ("industrial", 0.25)], 4.0),
    CityProfile("Ghaziabad", "Uttar Pradesh", 28.6692, 77.4538, 0.08, 185, 250, [("vehicular", 0.6), ("industrial", 0.5), ("waste_burning", 0.4), ("crop_residue_burning", 0.35)], 4.0),
    CityProfile("Faridabad", "Haryana", 28.4089, 77.3178, 0.05, 170, 230, [("industrial", 0.6), ("vehicular", 0.6), ("construction_dust", 0.4)], 4.0),
    CityProfile("Kanpur", "Uttar Pradesh", 26.4499, 80.3319, 0.07, 190, 60, [("industrial", 0.7), ("vehicular", 0.5), ("waste_burning", 0.35), ("biomass_cooking", 0.3)], 4.0),
    CityProfile("Lucknow", "Uttar Pradesh", 26.8467, 80.9462, 0.06, 170, 50, [("vehicular", 0.7), ("construction_dust", 0.4), ("crop_residue_burning", 0.25)], 4.0),
    CityProfile("Kolkata", "West Bengal", 22.5726, 88.3639, 0.07, 140, 30, [("vehicular", 0.75), ("industrial", 0.35), ("biomass_cooking", 0.3)], 5.0),
    CityProfile("Mumbai", "Maharashtra", 19.0760, 72.8777, 0.09, 95, 15, [("vehicular", 0.7), ("construction_dust", 0.55), ("industrial", 0.3)], 6.0),
    CityProfile("Bengaluru", "Karnataka", 12.9716, 77.5946, 0.08, 70, 5, [("vehicular", 0.75), ("construction_dust", 0.45)], 6.0),
]

CAPTIONS_EN = [
    "Very smoky this morning, cannot see the next building",
    "Eyes burning near the market",
    "Haze since yesterday evening",
    "Burning garbage near the road again",
    "Sky looks grey and heavy",
    "Traffic jam and dust everywhere",
    "Construction site next door, dust all day",
    "Sun is orange at 10 am",
    "Air feels heavy, children coughing",
    "",
    "",
    "",
]
CAPTIONS_HI = [
    "बहुत धुआं है, सामने की इमारत नहीं दिख रही",
    "आंखों में जलन हो रही है",
    "कल शाम से धुंध है",
    "सड़क के पास कूड़ा जल रहा है",
    "आसमान बिल्कुल धूसर है",
    "",
    "",
]

SKY_BY_BAND = {
    "good": "clear",
    "satisfactory": "clear",
    "moderate": "hazy",
    "poor": "hazy",
    "very_poor": "smoky",
    "severe": "smoky",
}

VISIBILITY_CATEGORY = [
    (10.0, "excellent"),
    (6.0, "good"),
    (3.0, "moderate"),
    (1.5, "poor"),
    (0.0, "very_poor"),
]

LANGUAGE_WEIGHTS = [("hi", 0.55), ("en", 0.35), ("pa", 0.04), ("bn", 0.03), ("mr", 0.03)]

AUTHORITIES: List[Dict[str, Any]] = [
    {"_id": "dpcc-control-room", "name": "DPCC Air Quality Control Room", "organisation": "Delhi Pollution Control Committee", "phone": "+911123456701", "whatsapp": "+911123456701", "language": "hi", "channels": ["voice", "whatsapp"], "coverageGeohashes": ["ttnf", "ttng", "ttnc"], "priority": 10, "active": True, "region": "Delhi"},
    {"_id": "gurugram-dc-office", "name": "Gurugram District Emergency Operations Centre", "organisation": "District Administration Gurugram", "phone": "+911244567802", "whatsapp": "+911244567802", "language": "hi", "channels": ["voice", "whatsapp"], "coverageGeohashes": ["ttnc", "ttnb"], "priority": 20, "active": True, "region": "Haryana"},
    {"_id": "noida-authority", "name": "Noida Authority Environment Cell", "organisation": "New Okhla Industrial Development Authority", "phone": "+911204567803", "whatsapp": "+911204567803", "language": "hi", "channels": ["voice", "whatsapp"], "coverageGeohashes": ["ttp4", "ttp5"], "priority": 20, "active": True, "region": "Uttar Pradesh"},
    {"_id": "uppcb-kanpur", "name": "UPPCB Regional Office Kanpur", "organisation": "Uttar Pradesh Pollution Control Board", "phone": "+915124567804", "whatsapp": "+915124567804", "language": "hi", "channels": ["voice", "whatsapp"], "coverageGeohashes": ["tu9", "tuc"], "priority": 20, "active": True, "region": "Uttar Pradesh"},
    {"_id": "wbpcb-kolkata", "name": "WBPCB Kolkata Control Room", "organisation": "West Bengal Pollution Control Board", "phone": "+913324567807", "whatsapp": "+913324567807", "language": "bn", "channels": ["whatsapp"], "coverageGeohashes": ["tun"], "priority": 20, "active": True, "region": "West Bengal"},
    {"_id": "mpcb-mumbai", "name": "MPCB Mumbai Regional Office", "organisation": "Maharashtra Pollution Control Board", "phone": "+912224567805", "whatsapp": "+912224567805", "language": "mr", "channels": ["whatsapp"], "coverageGeohashes": ["te7"], "priority": 20, "active": True, "region": "Maharashtra"},
    {"_id": "kspcb-bengaluru", "name": "KSPCB Bengaluru Regional Office", "organisation": "Karnataka State Pollution Control Board", "phone": "+918024567808", "whatsapp": "+918024567808", "language": "kn", "channels": ["whatsapp"], "coverageGeohashes": ["tdr"], "priority": 20, "active": True, "region": "Karnataka"},
    {"_id": "punjab-ppcb", "name": "PPCB Crop Residue Task Force", "organisation": "Punjab Pollution Control Board", "phone": "+911724567806", "whatsapp": "+911724567806", "language": "pa", "channels": ["voice", "whatsapp"], "coverageGeohashes": ["ttm", "ttt", "ttq"], "priority": 20, "active": True, "region": "Punjab"},
    {"_id": "cpcb-national", "name": "CPCB National Air Quality Monitoring Cell", "organisation": "Central Pollution Control Board", "phone": "+911143102030", "whatsapp": "+911143102030", "language": "en", "channels": ["whatsapp"], "coverageGeohashes": ["*"], "priority": 90, "active": True, "region": "India"},
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def weighted_choice(rng: random.Random, options: Sequence[Tuple[Any, float]]) -> Any:
    total = sum(weight for _, weight in options)
    pick = rng.uniform(0, total)
    upto = 0.0
    for value, weight in options:
        upto += weight
        if pick <= upto:
            return value
    return options[-1][0]


def offset_point(rng: random.Random, latitude: float, longitude: float, spread_km: float) -> Tuple[float, float]:
    """Random point around a centre with a roughly Gaussian spread."""
    d_lat = rng.gauss(0, spread_km / 111.0)
    d_lon = rng.gauss(0, spread_km / (111.0 * math.cos(math.radians(latitude))))
    return round(latitude + d_lat, 6), round(longitude + d_lon, 6)


def event_intensity(progress: float) -> float:
    """Escalation curve in [0, 1] as a function of window progress in [0, 1].

    Slow start, steep rise over the second half, plateau near the end.
    """
    return 1.0 / (1.0 + math.exp(-10.0 * (progress - 0.62)))


def diurnal_factor(when: dt.datetime) -> float:
    """Night-time inversion raises concentrations; afternoons ventilate."""
    hour = (when.hour + 5.5) % 24  # convert UTC to IST
    return 1.0 + 0.18 * math.cos((hour - 4.0) / 24.0 * 2 * math.pi)


def visibility_for(aqi: float, rng: random.Random) -> float:
    base = max(0.4, 14.0 * math.exp(-aqi / 140.0))
    return round(max(0.3, base * rng.uniform(0.8, 1.2)), 1)


def visibility_category(visibility_km: float) -> str:
    for threshold, label in VISIBILITY_CATEGORY:
        if visibility_km >= threshold:
            return label
    return "very_poor"


def haze_for(aqi: float, rng: random.Random) -> float:
    return round(min(0.98, max(0.03, aqi / 460.0 + rng.gauss(0, 0.05))), 3)


def phone_hash(phone: str, secret: str) -> str:
    return hmac.new(secret.encode(), phone.encode(), hashlib.sha256).hexdigest()[:32]


def report_id(rng: random.Random) -> str:
    return uuid.UUID(int=rng.getrandbits(128)).hex


def message_sid(rng: random.Random) -> str:
    return "SM" + uuid.UUID(int=rng.getrandbits(128)).hex


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------


@dataclass
class Citizen:
    phone: str
    phone_hash: str
    language: str
    city: CityProfile
    home: Tuple[float, float]
    profile_name: str
    reports: int = 0
    first_seen: Optional[dt.datetime] = None
    last_seen: Optional[dt.datetime] = None
    last_location: Optional[Tuple[float, float]] = None


@dataclass
class Dataset:
    reports: List[Dict[str, Any]] = field(default_factory=list)
    users: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    hotspots: List[Dict[str, Any]] = field(default_factory=list)
    alerts: List[Dict[str, Any]] = field(default_factory=list)
    authorities: List[Dict[str, Any]] = field(default_factory=list)
    batch_runs: List[Dict[str, Any]] = field(default_factory=list)
    alert_state: List[Dict[str, Any]] = field(default_factory=list)
    access: Dict[str, Any] = field(default_factory=dict)


FIRST_NAMES = ["Asha", "Rohan", "Priya", "Arjun", "Meera", "Kabir", "Ananya", "Vikram", "Neha", "Farhan", "Simran", "Aditya", "Pooja", "Imran", "Kavya", "Manish", "Divya", "Rahul", "Sneha", "Harpreet"]


def build_citizens(rng: random.Random, count: int, secret: str) -> List[Citizen]:
    citizens: List[Citizen] = []
    used_numbers: set[str] = set()
    for _ in range(count):
        city = weighted_choice(rng, [(c, c.weight) for c in CITIES])
        while True:
            phone = f"+91{rng.choice(['6', '7', '8', '9'])}{rng.randint(100000000, 999999999)}"
            if phone not in used_numbers:
                used_numbers.add(phone)
                break
        home = offset_point(rng, city.latitude, city.longitude, city.spread_km)
        citizens.append(
            Citizen(
                phone=phone,
                phone_hash=phone_hash(phone, secret),
                language=weighted_choice(rng, LANGUAGE_WEIGHTS),
                city=city,
                home=home,
                profile_name=rng.choice(FIRST_NAMES),
            )
        )
    return citizens


def estimate_aqi(city: CityProfile, when: dt.datetime, progress: float, rng: random.Random) -> float:
    value = (city.baseline_aqi + city.escalation * event_intensity(progress)) * diurnal_factor(when)
    value += rng.gauss(0, 18)
    return float(min(500, max(20, value)))


def pick_sources(city: CityProfile, progress: float, aqi: float, rng: random.Random) -> List[str]:
    intensity = event_intensity(progress)
    chosen: List[str] = []
    for source, probability in city.sources:
        boost = 0.0
        if source in {"crop_residue_burning", "waste_burning"} and city.escalation > 100:
            boost = 0.45 * intensity
        if rng.random() < min(0.95, probability + boost):
            chosen.append(source)
    if not chosen:
        chosen.append("vehicular" if aqi > 90 else "unknown")
    return chosen[:3]


def build_report(rng: random.Random, citizen: Citizen, when: dt.datetime, progress: float, bucket: str, outdoor_probability: float = 0.94) -> Dict[str, Any]:
    city = citizen.city
    lat, lon = offset_point(rng, citizen.home[0], citizen.home[1], 1.2)
    rid = report_id(rng)
    aqi = estimate_aqi(city, when, progress, rng)
    band = aqi_category(aqi)
    outdoor = rng.random() < outdoor_probability
    status_roll = rng.random()
    status = "analyzed" if status_roll < 0.9 else ("analyzing" if status_roll < 0.94 else ("received" if status_roll < 0.97 else "failed"))
    if (dt.datetime.now(tz=dt.timezone.utc) - when) > dt.timedelta(minutes=20) and status in {"analyzing", "received"}:
        status = "analyzed"

    sources = pick_sources(city, progress, aqi, rng)
    visibility = visibility_for(aqi, rng)
    haze = haze_for(aqi, rng)
    smoke = "crop_residue_burning" in sources or "waste_burning" in sources or aqi > 320
    dust = "construction_dust" in sources or "road_dust" in sources
    caption = rng.choice(CAPTIONS_HI if citizen.language == "hi" else CAPTIONS_EN)
    location_source = weighted_choice(rng, [("message", 0.55), ("user_profile", 0.4), ("text", 0.05)])

    analysis: Dict[str, Any] = {
        "is_outdoor_scene": outdoor,
        "haze_index": haze if outdoor else 0.0,
        "visibility_km": visibility if outdoor else None,
        "visibility_category": visibility_category(visibility) if outdoor else "unknown",
        "sky_condition": SKY_BY_BAND[band] if outdoor else "unknown",
        "smoke_detected": bool(smoke and outdoor),
        "dust_detected": bool(dust and outdoor),
        "fog_or_mist_detected": bool(outdoor and aqi > 250 and rng.random() < 0.25),
        "open_burning_detected": bool(outdoor and ("waste_burning" in sources or "crop_residue_burning" in sources) and rng.random() < 0.5),
        "vehicle_density_score": round(rng.uniform(0.5, 0.95) if "vehicular" in sources else rng.uniform(0.1, 0.5), 2),
        "construction_activity_score": round(rng.uniform(0.4, 0.9) if "construction_dust" in sources else rng.uniform(0.0, 0.3), 2),
        "industrial_emission_score": round(rng.uniform(0.4, 0.9) if "industrial" in sources else rng.uniform(0.0, 0.2), 2),
        "pollution_sources": sources if outdoor else ["unknown"],
        "estimated_aqi_category": band if outdoor else "unknown",
        "estimated_aqi": round(aqi) if outdoor else None,
        "confidence": round(rng.uniform(0.62, 0.9) if outdoor else rng.uniform(0.15, 0.35), 2),
        "reasoning": (
            f"{SKY_BY_BAND[band].capitalize()} sky with visibility around {visibility} km; "
            + ("visible smoke plume, " if smoke else "")
            + ("dust haze near ground level, " if dust else "")
            + f"consistent with the {band.replace('_', ' ')} AQI band."
            if outdoor
            else "Interior scene without a view of the sky; air quality cannot be assessed."
        ),
        "model_name": MODEL_NAME,
        "latency_ms": rng.randint(1800, 6200),
    }

    created_at = when
    analyzed_at = when + dt.timedelta(seconds=rng.randint(8, 40)) if status == "analyzed" else None
    doc: Dict[str, Any] = {
        "_id": rid,
        "phoneHash": citizen.phone_hash,
        "messageSid": message_sid(rng),
        "imageUri": f"gs://{bucket}/reports/{when:%Y/%m/%d}/{rid}.jpg",
        "contentType": "image/jpeg",
        "caption": caption or None,
        "location": {"latitude": lat, "longitude": lon},
        "geohash": encode_geohash(lat, lon, precision=7),
        "city": city.name,
        "state": city.state,
        "locationSource": location_source,
        "source": "whatsapp",
        "status": status,
        "receivedAt": created_at,
        "createdAt": created_at,
        "updatedAt": analyzed_at or created_at,
        "metadata": {"profileName": citizen.profile_name, "sizeBytes": rng.randint(180_000, 2_400_000), "synthetic": True},
    }
    if status == "analyzed":
        doc.update(
            {
                "analyzedAt": analyzed_at,
                "geminiAnalysis": analysis,
                "isOutdoorScene": outdoor,
                "hazeIndex": analysis["haze_index"] if outdoor else None,
                "estimatedAqi": analysis["estimated_aqi"] if outdoor else None,
                "estimatedAqiCategory": band if outdoor else "not_applicable",
                "visibilityKm": visibility if outdoor else None,
                "pollutionSources": sources if outdoor else [],
                "modelName": MODEL_NAME,
            }
        )
        if outdoor and rng.random() < 0.85:
            intensity = event_intensity(progress)
            doc["satelliteMetrics"] = {
                "aerAi": round(max(-1.0, rng.gauss(0.6 + 2.4 * intensity * (city.escalation / 265), 0.35)), 3),
                "no2TroposphericMolM2": round(max(1e-6, rng.gauss(6e-5 + 1.1e-4 * (aqi / 400), 2e-5)), 8),
                "coColumnMolM2": round(max(0.01, rng.gauss(0.032 + 0.02 * (aqi / 400), 0.004)), 5),
                "so2ColumnMolM2": round(max(0.0, rng.gauss(0.0002, 0.00008)), 7),
                "aod047": round(max(0.05, rng.gauss(0.35 + 1.1 * (aqi / 400), 0.12)), 3),
                "s5pImageCount": rng.randint(2, 6),
                "modisImageCount": rng.randint(1, 4),
                "windowStart": when - dt.timedelta(days=3),
                "windowEnd": when,
                "bufferRadiusM": 5000,
                "lookbackDays": 3,
                "source": "mock",
            }
            doc["satelliteStatus"] = "fetched"
            doc["satelliteFetchedAt"] = analyzed_at
    elif status == "failed":
        doc["error"] = "Gemini analysis failed: all model candidates exhausted (HTTP 429)"
    return doc


def build_hotspots(
    rng: random.Random,
    reports: List[Dict[str, Any]],
    window_start: dt.datetime,
    window_end: dt.datetime,
    threshold: float,
    run_interval_hours: int,
    min_reports: int = 2,
    quiet_hours: float = 0.0,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Simulate periodic batch prediction runs over the window.

    ``quiet_hours`` stops the simulated runs that many hours before the end of
    the window and marks every above-threshold hotspot as already alerted.
    This leaves the most recent reports unpredicted so that a live batch run
    during a demo produces fresh hotspots that are not suppressed by the alert
    cooldown.
    """
    hotspots: List[Dict[str, Any]] = []
    runs: List[Dict[str, Any]] = []
    total_hours = (window_end - window_start).total_seconds() / 3600
    last_run_time = window_end - dt.timedelta(hours=max(0.0, quiet_hours))
    run_time = window_start + dt.timedelta(hours=6)
    while run_time <= last_run_time:
        since = run_time - dt.timedelta(hours=6)
        recent = [r for r in reports if r["status"] == "analyzed" and r.get("estimatedAqi") is not None and since <= r["createdAt"] <= run_time]
        cells: Dict[str, List[Dict[str, Any]]] = {}
        for r in recent:
            cells.setdefault(r["geohash"][:5], []).append(r)
        progress_now = (run_time - window_start).total_seconds() / 3600 / total_hours
        progress_future = min(1.0, progress_now + 12 / total_hours)
        run_docs: List[Dict[str, Any]] = []
        for cell, items in cells.items():
            if len(items) < min_reports:
                continue
            city_name = max({r["city"] for r in items}, key=lambda c: sum(1 for r in items if r["city"] == c))
            city = next(c for c in CITIES if c.name == city_name)
            current = sum(r["estimatedAqi"] for r in items) / len(items)
            future = (city.baseline_aqi + city.escalation * event_intensity(progress_future)) * diurnal_factor(run_time + dt.timedelta(hours=12))
            predicted = float(min(500, max(20, 0.35 * current + 0.65 * future + rng.gauss(0, 12))))
            sources_counter: Dict[str, int] = {}
            for r in items:
                for s in r.get("pollutionSources", []):
                    sources_counter[s] = sources_counter.get(s, 0) + 1
            dominant = [s for s, _ in sorted(sources_counter.items(), key=lambda kv: -kv[1])[:3]]
            lat = sum(r["location"]["latitude"] for r in items) / len(items)
            lon = sum(r["location"]["longitude"] for r in items) / len(items)
            above = predicted >= threshold
            is_latest_run = quiet_hours <= 0 and run_time + dt.timedelta(hours=run_interval_hours) > last_run_time
            alert_status = ("pending" if is_latest_run else "sent") if above else "not_required"
            features = {
                "haze_index": round(sum(r["hazeIndex"] for r in items) / len(items), 4),
                "visibility_km": round(sum(r["visibilityKm"] for r in items) / len(items), 3),
                "vision_aqi_estimate": round(current, 2),
                "report_count": float(len(items)),
                "smoke_ratio": round(sum(1 for r in items if r["geminiAnalysis"]["smoke_detected"]) / len(items), 3),
                "wind_speed_ms": round(max(0.2, rng.gauss(1.4 if city.escalation > 100 else 2.8, 0.5)), 2),
                "boundary_layer_height_m": round(max(120, rng.gauss(320 if city.escalation > 100 else 780, 90)), 1),
                "relative_humidity_pct": round(rng.uniform(48, 82), 1),
                "temperature_c": round(rng.uniform(11, 24), 1),
            }
            sats = [r["satelliteMetrics"] for r in items if r.get("satelliteMetrics")]
            if sats:
                features["aer_ai"] = round(sum(s["aerAi"] for s in sats) / len(sats), 4)
                features["aod_047"] = round(sum(s["aod047"] for s in sats) / len(sats), 4)
                features["no2_tropospheric_mol_m2"] = round(sum(s["no2TroposphericMolM2"] for s in sats) / len(sats), 8)
            run_docs.append(
                {
                    "_id": f"{cell}_{run_time:%Y%m%dT%H%M}",
                    "geohash": cell,
                    "latitude": round(lat, 5),
                    "longitude": round(lon, 5),
                    "city": city_name,
                    "generatedAt": run_time,
                    "forecastFor": run_time + dt.timedelta(hours=12),
                    "horizonHours": 12,
                    "predictedAqi": round(predicted, 1),
                    "predictedCategory": aqi_category(predicted),
                    "currentAqiEstimate": round(current, 1),
                    "reportCount": len(items),
                    "confidence": round(min(0.95, 0.45 + 0.05 * len(items) + (0.1 if sats else 0.0)), 3),
                    "modelVersion": MODEL_VERSION,
                    "dominantSources": dominant,
                    "features": features,
                    "weatherSource": "synthetic",
                    "hasSatellite": bool(sats),
                    "reportIds": [r["_id"] for r in items][:50],
                    "alertStatus": alert_status,
                    "alertThreshold": threshold,
                }
            )
        hotspots.extend(run_docs)
        runs.append(
            {
                "_id": f"{run_time:%Y%m%dT%H%M%S}",
                "generated_at": run_time.isoformat(),
                "lookback_hours": 6,
                "observation_source": "firestore",
                "observations": len(recent),
                "cells": len(run_docs),
                "weather_source": "synthetic",
                "model_version": MODEL_VERSION,
                "alerts_pending": sum(1 for d in run_docs if d["alertStatus"] != "not_required"),
                "max_predicted_aqi": max((d["predictedAqi"] for d in run_docs), default=None),
                "hotspots_written": len(run_docs),
                "elapsed_ms": rng.randint(2400, 9800),
                "dry_run": False,
                "synthetic": True,
            }
        )
        run_time += dt.timedelta(hours=run_interval_hours)
    return hotspots, runs


ALERT_TEXT = {
    "en": "VayuSetu air quality alert for {area}. Citizen reports and satellite data indicate the air quality index may reach {aqi} ({band}) within twelve hours. Likely sources: {sources}. Please activate the graded response action plan.",
    "hi": "{area} के लिए VayuSetu वायु गुणवत्ता चेतावनी। नागरिक रिपोर्टों और उपग्रह डेटा के अनुसार अगले बारह घंटों में वायु गुणवत्ता सूचकांक {aqi} ({band}) तक पहुंच सकता है। संभावित स्रोत: {sources}। कृपया ग्रेडेड रिस्पांस एक्शन प्लान सक्रिय करें।",
    "pa": "{area} ਲਈ VayuSetu ਹਵਾ ਗੁਣਵੱਤਾ ਚੇਤਾਵਨੀ। ਨਾਗਰਿਕ ਰਿਪੋਰਟਾਂ ਅਤੇ ਉਪਗ੍ਰਹਿ ਡੇਟਾ ਦਰਸਾਉਂਦੇ ਹਨ ਕਿ ਅਗਲੇ ਬਾਰਾਂ ਘੰਟਿਆਂ ਵਿੱਚ ਹਵਾ ਗੁਣਵੱਤਾ ਸੂਚਕ {aqi} ({band}) ਤੱਕ ਪਹੁੰਚ ਸਕਦਾ ਹੈ। ਸੰਭਾਵਿਤ ਸਰੋਤ: {sources}।",
    "mr": "{area} साठी VayuSetu हवा गुणवत्ता इशारा। नागरिक अहवाल आणि उपग्रह डेटानुसार पुढील बारा तासांत हवा गुणवत्ता निर्देशांक {aqi} ({band}) पर्यंत पोहोचू शकतो। संभाव्य स्रोत: {sources}।",
}


def matching_authorities(geohash: str) -> List[Dict[str, Any]]:
    prefixes = {geohash[:n] for n in range(3, len(geohash) + 1)} | {"*"}
    matched = [a for a in AUTHORITIES if a["active"] and any(p in prefixes for p in a["coverageGeohashes"])]
    matched.sort(key=lambda a: (-max((len(p) for p in a["coverageGeohashes"] if p != "*"), default=0), a["priority"]))
    return matched[:5]


def build_alerts(rng: random.Random, hotspots: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return (alert_log rows, alert_state rows) for every hotspot marked as sent."""
    alerts: List[Dict[str, Any]] = []
    last_alert_by_cell: Dict[str, dt.datetime] = {}
    state_by_cell: Dict[str, Dict[str, Any]] = {}
    for hotspot in sorted(hotspots, key=lambda h: h["generatedAt"]):
        if hotspot["alertStatus"] != "sent":
            continue
        previous = last_alert_by_cell.get(hotspot["geohash"])
        if previous and hotspot["generatedAt"] - previous < dt.timedelta(hours=3):
            hotspot["alertStatus"] = "suppressed_cooldown"
            continue
        last_alert_by_cell[hotspot["geohash"]] = hotspot["generatedAt"]
        recipients = matching_authorities(hotspot["geohash"])
        if not recipients:
            hotspot["alertStatus"] = "no_recipients"
            continue
        sent_languages: set[str] = set()
        for authority in recipients:
            language = authority["language"] if authority["language"] in ALERT_TEXT else "en"
            text = ALERT_TEXT[language].format(
                area=hotspot["city"] or hotspot["geohash"],
                aqi=int(round(hotspot["predictedAqi"])),
                band=hotspot["predictedCategory"].replace("_", " "),
                sources=", ".join(s.replace("_", " ") for s in hotspot["dominantSources"]) or "unknown",
            )
            for channel in authority["channels"]:
                failed = rng.random() < 0.05
                alerts.append(
                    {
                        "_id": str(uuid.UUID(int=rng.getrandbits(128))),
                        "hotspotId": hotspot["_id"],
                        "geohash": hotspot["geohash"],
                        "predictedAqi": hotspot["predictedAqi"],
                        "authorityId": authority["_id"],
                        "authorityName": authority["name"],
                        "channel": channel,
                        "language": language,
                        "twilioSid": None if failed else ("CA" if channel == "voice" else "SM") + uuid.UUID(int=rng.getrandbits(128)).hex,
                        "status": "failed" if failed else "sent",
                        "messageText": text,
                        "error": "Twilio error 21211: invalid To phone number" if failed else None,
                        "sentAt": hotspot["generatedAt"] + dt.timedelta(seconds=rng.randint(20, 240)),
                    }
                )
                if not failed:
                    sent_languages.add(language)
        hotspot["alertedAt"] = hotspot["generatedAt"] + dt.timedelta(seconds=30)
        hotspot["alertLanguages"] = sorted(sent_languages)
        hotspot["alertRecipients"] = len(recipients)
        state_by_cell[hotspot["geohash"]] = {
            "_id": hotspot["geohash"],
            "lastAlertAt": hotspot["alertedAt"],
            "lastPredictedAqi": hotspot["predictedAqi"],
            "lastHotspotId": hotspot["_id"],
        }
    return alerts, list(state_by_cell.values())


def build_dataset(args: argparse.Namespace) -> Dataset:
    rng = random.Random(args.seed)
    now = dt.datetime.now(tz=dt.timezone.utc).replace(second=0, microsecond=0)
    window_end = now - dt.timedelta(minutes=5)
    window_start = window_end - dt.timedelta(hours=args.hours)
    total_seconds = (window_end - window_start).total_seconds()

    citizens = build_citizens(rng, args.citizens, args.phone_hash_secret)
    dataset = Dataset()

    # Report volume grows with the event: sample timestamps from a density
    # that mixes a uniform floor with the escalation curve.
    timestamps: List[dt.datetime] = []
    while len(timestamps) < args.reports:
        progress = rng.random()
        accept = 0.35 + 0.65 * event_intensity(progress)
        if rng.random() <= accept:
            timestamps.append(window_start + dt.timedelta(seconds=progress * total_seconds))
    timestamps.sort()

    for when in timestamps:
        progress = (when - window_start).total_seconds() / total_seconds
        # Citizens in the escalating region report more often as the event worsens.
        weights = [(c, (1.0 + 2.5 * event_intensity(progress)) if c.city.escalation > 100 else 1.0) for c in citizens]
        citizen = weighted_choice(rng, weights)
        report = build_report(rng, citizen, when, progress, args.bucket)
        dataset.reports.append(report)
        citizen.reports += 1
        citizen.first_seen = citizen.first_seen or when
        citizen.last_seen = when
        citizen.last_location = (report["location"]["latitude"], report["location"]["longitude"])

    for citizen in citizens:
        if citizen.reports == 0:
            continue
        dataset.users[citizen.phone_hash] = {
            "phoneNumber": f"whatsapp:{citizen.phone}",
            "profileName": citizen.profile_name,
            "language": citizen.language,
            "lastLocation": {"latitude": citizen.last_location[0], "longitude": citizen.last_location[1]} if citizen.last_location else None,
            "lastLocationAt": citizen.last_seen,
            "lastLocationLabel": f"{citizen.city.name}, {citizen.city.state}",
            "reportCount": citizen.reports,
            "lastReportAt": citizen.last_seen,
            "createdAt": citizen.first_seen,
            "updatedAt": citizen.last_seen,
        }

    dataset.hotspots, dataset.batch_runs = build_hotspots(
        rng,
        dataset.reports,
        window_start,
        window_end,
        args.alert_threshold,
        args.batch_interval_hours,
        args.min_reports_per_cell,
        args.quiet_hours,
    )
    dataset.alerts, dataset.alert_state = build_alerts(rng, dataset.hotspots)
    dataset.authorities = [dict(a, createdAt=window_start, updatedAt=window_start) for a in AUTHORITIES]
    dataset.access = {
        "adminDomains": [d.strip() for d in args.admin_domain.split(",") if d.strip()],
        "adminEmails": [e.strip() for e in args.admin_emails.split(",") if e.strip()],
        "updatedBy": "generate_mock_data.py",
        "updatedAt": now,
    }
    return dataset


# ---------------------------------------------------------------------------
# Firestore writer
# ---------------------------------------------------------------------------


def to_firestore(value: Any, firestore_module: Any) -> Any:
    """Convert plain dictionaries into Firestore GeoPoints where appropriate."""
    if isinstance(value, dict):
        keys = set(value.keys())
        if keys == {"latitude", "longitude"}:
            return firestore_module.GeoPoint(value["latitude"], value["longitude"])
        return {k: to_firestore(v, firestore_module) for k, v in value.items() if k != "_id"}
    if isinstance(value, list):
        return [to_firestore(v, firestore_module) for v in value]
    return value


def chunked(items: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def delete_collection(db: Any, name: str, batch_size: int = 300) -> int:
    deleted = 0
    while True:
        docs = list(db.collection(name).limit(batch_size).stream())
        if not docs:
            return deleted
        batch = db.batch()
        for doc in docs:
            batch.delete(doc.reference)
        batch.commit()
        deleted += len(docs)


def write_dataset(dataset: Dataset, project: str, clear: bool, hotspots_last: bool) -> None:
    from google.cloud import firestore

    db = firestore.Client(project=project)
    collections = {
        "citizen_reports": dataset.reports,
        "users": [dict(v, _id=k) for k, v in dataset.users.items()],
        "authorities": dataset.authorities,
        "alert_log": dataset.alerts,
        "alert_state": dataset.alert_state,
        "batch_runs": dataset.batch_runs,
        "predicted_hotspots": dataset.hotspots,
    }
    if clear:
        for name in list(collections) + ["webhook_events"]:
            removed = delete_collection(db, name)
            if removed:
                logger.info("Cleared %s (%d documents)", name, removed)

    db.collection("config").document("access").set(to_firestore(dataset.access, firestore))
    logger.info("Wrote config/access for domains %s", dataset.access["adminDomains"])

    order = [n for n in collections if n != "predicted_hotspots"] + (["predicted_hotspots"] if hotspots_last else [])
    if not hotspots_last:
        order.insert(0, "predicted_hotspots")
    for name in order:
        docs = collections[name]
        written = 0
        for group in chunked(docs, 400):
            batch = db.batch()
            for doc in group:
                batch.set(db.collection(name).document(doc["_id"]), to_firestore(doc, firestore))
            batch.commit()
            written += len(group)
        logger.info("Wrote %d documents to %s", written, name)


def summarise(dataset: Dataset) -> Dict[str, Any]:
    analyzed = [r for r in dataset.reports if r["status"] == "analyzed" and r.get("estimatedAqi") is not None]
    by_city: Dict[str, List[float]] = {}
    for r in analyzed:
        by_city.setdefault(r["city"], []).append(r["estimatedAqi"])
    first_quarter = analyzed[: max(1, len(analyzed) // 4)]
    last_quarter = analyzed[-max(1, len(analyzed) // 4) :]
    return {
        "reports": len(dataset.reports),
        "analyzed": len(analyzed),
        "citizens": len(dataset.users),
        "cities": {city: round(sum(v) / len(v)) for city, v in sorted(by_city.items())},
        "average_aqi_first_quarter": round(sum(r["estimatedAqi"] for r in first_quarter) / len(first_quarter)),
        "average_aqi_last_quarter": round(sum(r["estimatedAqi"] for r in last_quarter) / len(last_quarter)),
        "hotspots": len(dataset.hotspots),
        "hotspots_above_threshold": sum(1 for h in dataset.hotspots if h["alertStatus"] in {"sent", "pending", "suppressed_cooldown"}),
        "pending_alerts": sum(1 for h in dataset.hotspots if h["alertStatus"] == "pending"),
        "alerts_logged": len(dataset.alerts),
        "alert_languages": sorted({a["language"] for a in dataset.alerts}),
        "authorities": len(dataset.authorities),
        "batch_runs": len(dataset.batch_runs),
    }


def json_default(value: Any) -> Any:
    if isinstance(value, dt.datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serialisable")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=os.environ.get("GCP_PROJECT_ID", "vayusetu-local"), help="Firestore project id (default: vayusetu-local)")
    parser.add_argument("--emulator-host", default=os.environ.get("FIRESTORE_EMULATOR_HOST", "localhost:8080"), help="Firestore emulator host:port")
    parser.add_argument("--allow-production", action="store_true", help="Permit writes without FIRESTORE_EMULATOR_HOST (dangerous)")
    parser.add_argument("--reports", type=int, default=500, help="Number of citizen reports to generate")
    parser.add_argument("--citizens", type=int, default=80, help="Number of distinct citizens")
    parser.add_argument("--hours", type=int, default=48, help="Length of the simulated window in hours")
    parser.add_argument("--batch-interval-hours", type=int, default=3, help="Interval between simulated batch prediction runs")
    parser.add_argument("--quiet-hours", type=float, default=0.0, help="Stop simulated batch runs this many hours before now and mark their alerts as sent, so a live batch run produces fresh, non-suppressed alerts (recommended: 3 for demos)")
    parser.add_argument("--min-reports-per-cell", type=int, default=2, help="Minimum analysed reports in a cell before a hotspot is generated")
    parser.add_argument("--alert-threshold", type=float, default=float(os.environ.get("ALERT_AQI_THRESHOLD", 300)))
    parser.add_argument("--bucket", default=os.environ.get("CITIZEN_IMAGES_BUCKET", "vayusetu-local-citizen-images"))
    parser.add_argument("--admin-domain", default=os.environ.get("ADMIN_DOMAIN", "example.com"))
    parser.add_argument("--admin-emails", default=os.environ.get("ADMIN_EMAILS", ""))
    parser.add_argument("--phone-hash-secret", default=os.environ.get("PHONE_HASH_SECRET", "local-development-phone-hash-secret"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--clear", action="store_true", help="Delete existing documents in the target collections first")
    parser.add_argument("--hotspots-first", action="store_true", help="Write predicted_hotspots before other collections (default: last, so the local alert bridge sees complete data)")
    parser.add_argument("--dry-run", action="store_true", help="Generate and summarise without writing to Firestore")
    parser.add_argument("--json-out", help="Optional path to dump the generated dataset as JSON")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.reports < 1 or args.hours < 6:
        logger.error("--reports must be positive and --hours at least 6")
        return 2

    dataset = build_dataset(args)
    summary = summarise(dataset)
    logger.info("Generated dataset: %s", json.dumps(summary, ensure_ascii=False))

    if args.json_out:
        payload = {
            "summary": summary,
            "citizen_reports": dataset.reports,
            "users": dataset.users,
            "predicted_hotspots": dataset.hotspots,
            "alert_log": dataset.alerts,
            "alert_state": dataset.alert_state,
            "authorities": dataset.authorities,
            "batch_runs": dataset.batch_runs,
            "config_access": dataset.access,
        }
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, default=json_default, ensure_ascii=False, indent=2)
        logger.info("Wrote JSON snapshot to %s", args.json_out)

    if args.dry_run:
        return 0

    if args.emulator_host:
        os.environ["FIRESTORE_EMULATOR_HOST"] = args.emulator_host
    elif not args.allow_production:
        logger.error("Refusing to write to production Firestore without --allow-production")
        return 2

    write_dataset(dataset, args.project, clear=args.clear, hotspots_last=not args.hotspots_first)
    logger.info("Done. Sign in to the dashboard with an account on %s to explore the data.", ", ".join(dataset.access["adminDomains"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
