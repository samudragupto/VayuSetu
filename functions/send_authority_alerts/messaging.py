"""Alert message composition and TwiML generation."""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

from vayusetu_common.aqi import aqi_category_label

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _format_time(value: Optional[dt.datetime]) -> str:
    if value is None:
        return "the next twelve hours"
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(IST).strftime("%I:%M %p on %d %B")


def _describe_sources(sources: List[str]) -> str:
    readable = [s.replace("_", " ") for s in sources if s and s != "unknown"]
    if not readable:
        return "mixed local sources"
    if len(readable) == 1:
        return readable[0]
    return ", ".join(readable[:-1]) + " and " + readable[-1]


def compose_alert_text(hotspot: Dict[str, Any], authority: Dict[str, Any]) -> str:
    """Compose the English source text that is translated for each authority."""
    predicted = float(hotspot.get("predictedAqi") or 0)
    category = aqi_category_label(predicted)
    area = hotspot.get("areaName") or hotspot.get("city") or f"grid cell {hotspot.get('geohash', 'unknown')}"
    forecast_for = hotspot.get("forecastFor")
    report_count = int(hotspot.get("reportCount") or 0)
    sources = hotspot.get("dominantSources") or hotspot.get("pollutionSources") or []
    officer = authority.get("name") or "Officer"
    lat = hotspot.get("latitude")
    lon = hotspot.get("longitude")
    coordinates = f" near latitude {lat:.3f}, longitude {lon:.3f}" if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) else ""

    return (
        f"Urgent air quality alert from VayuSetu for {officer}. "
        f"The air quality index in {area}{coordinates} is forecast to reach {predicted:.0f}, "
        f"which is in the {category} category, by {_format_time(forecast_for)}. "
        f"This forecast is based on {report_count} citizen reports and satellite measurements, "
        f"with {_describe_sources(list(sources))} as the likely contributors. "
        "Please consider activating the Graded Response Action Plan measures for this area, "
        "including dust suppression, traffic diversion and advisories for schools and outdoor workers."
    )


def compose_whatsapp_text(hotspot: Dict[str, Any], authority: Dict[str, Any], translated_body: str, dashboard_url: Optional[str]) -> str:
    """Plain-text WhatsApp companion message containing the translated alert."""
    lines = ["VayuSetu ALERT", translated_body]
    geohash = hotspot.get("geohash")
    if geohash:
        lines.append(f"Cell: {geohash}")
    if dashboard_url:
        lines.append(f"Dashboard: {dashboard_url}")
    lines.append(f"Ref: {hotspot.get('_id', '')[:12]}")
    return "\n".join(lines)


def build_play_twiml(audio_url: str, repeat: int = 2) -> str:
    """TwiML that plays the synthesised alert audio ``repeat`` times."""
    plays = "".join(f"<Play>{escape(audio_url)}</Play><Pause length=\"1\"/>" for _ in range(max(1, repeat)))
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{plays}</Response>'


def build_say_twiml(text: str, locale: str, repeat: int = 2) -> str:
    """Fallback TwiML that relies on Twilio's built-in text-to-speech."""
    body = escape(text)
    says = "".join(f'<Say language="{escape(locale)}">{body}</Say><Pause length="1"/>' for _ in range(max(1, repeat)))
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{says}</Response>'
