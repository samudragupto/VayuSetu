"""Prompt and strict response schema for Gemini image analysis.

The schema uses the OpenAPI subset supported by the Gemini API's
``response_schema`` generation parameter. Combined with
``response_mime_type="application/json"`` the model is constrained to emit a
single JSON object that validates against the schema, which removes the need
for brittle free-text parsing.
"""

from __future__ import annotations

from typing import Any, Dict, List

VISIBILITY_CATEGORIES: List[str] = ["excellent", "good", "moderate", "poor", "very_poor", "severe"]

SKY_CONDITIONS: List[str] = [
    "clear_blue",
    "hazy_blue",
    "grey_overcast",
    "brown_smog",
    "yellow_haze",
    "night",
    "not_visible",
]

POLLUTION_SOURCES: List[str] = [
    "vehicular",
    "industrial",
    "construction_dust",
    "road_dust",
    "biomass_burning",
    "waste_burning",
    "crop_residue_burning",
    "fireworks",
    "natural_dust_storm",
    "unknown",
]

AQI_CATEGORIES: List[str] = ["good", "satisfactory", "moderate", "poor", "very_poor", "severe"]

SYSTEM_PROMPT = """You are VayuSetu, an atmospheric science assistant that estimates local air quality
from citizen photographs taken in Indian cities.

Analyse the supplied photograph of the sky or street and return ONLY a JSON object that conforms to the
provided schema. Follow these rules:

1. haze_index is a continuous value from 0.0 (perfectly clear air, sharp distant edges, deep blue sky)
   to 1.0 (opaque smog where objects a few hundred metres away are invisible).
2. visibility_km is your best estimate of meteorological visibility in kilometres. Use landmarks,
   buildings, trees and horizon sharpness as cues. If the sky is not visible, estimate from the street.
3. Distinguish moisture (fog_or_mist_detected) from particulate haze using colour: fog is white or grey
   and uniform, while smog is brown, yellow or has a gradient that thickens near the horizon.
4. smoke_detected is true only when a plume, column or visible source of smoke is present.
5. open_burning_detected is true when fire, embers, burning waste or crop stubble is visible.
6. Score visible activity between 0.0 and 1.0: vehicle_density_score (traffic volume),
   construction_activity_score (cranes, excavation, uncovered debris, dust clouds) and
   industrial_emission_score (chimneys, stacks, industrial plumes).
7. pollution_sources lists the most likely contributors visible or strongly implied in the image.
8. estimated_aqi uses the Indian CPCB scale (0 to 500) and estimated_aqi_category must be consistent
   with it: good 0-50, satisfactory 51-100, moderate 101-200, poor 201-300, very_poor 301-400,
   severe 401-500.
9. confidence expresses how reliable the estimate is given image quality, lighting and framing.
10. is_outdoor_scene must be false for indoor photos, selfies, screenshots or documents; in that case
    set confidence to 0.1 and estimated_aqi to 0.
11. reasoning must be a single concise sentence (maximum 40 words) suitable for showing to a municipal
    officer.

Never include markdown, commentary or any text outside the JSON object."""


RESPONSE_SCHEMA: Dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "is_outdoor_scene": {"type": "BOOLEAN", "description": "True when the image shows an outdoor sky or street scene."},
        "haze_index": {"type": "NUMBER", "description": "0.0 clear to 1.0 opaque smog."},
        "visibility_km": {"type": "NUMBER", "description": "Estimated visibility in kilometres."},
        "visibility_category": {"type": "STRING", "format": "enum", "enum": VISIBILITY_CATEGORIES},
        "sky_condition": {"type": "STRING", "format": "enum", "enum": SKY_CONDITIONS},
        "smoke_detected": {"type": "BOOLEAN"},
        "dust_detected": {"type": "BOOLEAN"},
        "fog_or_mist_detected": {"type": "BOOLEAN"},
        "open_burning_detected": {"type": "BOOLEAN"},
        "vehicle_density_score": {"type": "NUMBER", "description": "0.0 to 1.0."},
        "construction_activity_score": {"type": "NUMBER", "description": "0.0 to 1.0."},
        "industrial_emission_score": {"type": "NUMBER", "description": "0.0 to 1.0."},
        "pollution_sources": {
            "type": "ARRAY",
            "items": {"type": "STRING", "format": "enum", "enum": POLLUTION_SOURCES},
        },
        "estimated_aqi_category": {"type": "STRING", "format": "enum", "enum": AQI_CATEGORIES},
        "estimated_aqi": {"type": "INTEGER", "description": "CPCB AQI estimate 0-500."},
        "confidence": {"type": "NUMBER", "description": "0.0 to 1.0."},
        "reasoning": {"type": "STRING"},
    },
    "required": [
        "is_outdoor_scene",
        "haze_index",
        "visibility_km",
        "visibility_category",
        "sky_condition",
        "smoke_detected",
        "dust_detected",
        "fog_or_mist_detected",
        "open_burning_detected",
        "vehicle_density_score",
        "construction_activity_score",
        "industrial_emission_score",
        "pollution_sources",
        "estimated_aqi_category",
        "estimated_aqi",
        "confidence",
        "reasoning",
    ],
}


def build_user_prompt(context: Dict[str, Any]) -> str:
    """Compose the per-request instruction that accompanies the image."""
    lines = ["Analyse this citizen photograph and return the JSON object."]
    city = context.get("city")
    if city:
        lines.append(f"Reported city: {city}.")
    caption = context.get("caption")
    if caption:
        lines.append(f"Citizen caption (may be in any Indian language, treat as a weak hint only): {caption[:280]}")
    local_time = context.get("local_time")
    if local_time:
        lines.append(f"Local capture time: {local_time}.")
    return "\n".join(lines)
