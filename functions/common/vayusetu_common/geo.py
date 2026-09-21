"""Dependency-free geospatial helpers (geohash and haversine)."""

from __future__ import annotations

import math
from typing import Tuple

_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"
_DECODE_MAP = {char: index for index, char in enumerate(_BASE32)}

EARTH_RADIUS_KM = 6371.0088


def encode_geohash(latitude: float, longitude: float, precision: int = 7) -> str:
    """Encode a coordinate pair into a geohash string of ``precision`` characters."""
    if not (-90.0 <= latitude <= 90.0):
        raise ValueError(f"latitude out of range: {latitude}")
    if not (-180.0 <= longitude <= 180.0):
        raise ValueError(f"longitude out of range: {longitude}")
    if precision < 1 or precision > 12:
        raise ValueError("precision must be between 1 and 12")

    lat_interval = [-90.0, 90.0]
    lon_interval = [-180.0, 180.0]
    geohash = []
    bits = [16, 8, 4, 2, 1]
    bit = 0
    char_index = 0
    even_bit = True

    while len(geohash) < precision:
        if even_bit:
            mid = (lon_interval[0] + lon_interval[1]) / 2
            if longitude > mid:
                char_index |= bits[bit]
                lon_interval[0] = mid
            else:
                lon_interval[1] = mid
        else:
            mid = (lat_interval[0] + lat_interval[1]) / 2
            if latitude > mid:
                char_index |= bits[bit]
                lat_interval[0] = mid
            else:
                lat_interval[1] = mid
        even_bit = not even_bit
        if bit < 4:
            bit += 1
        else:
            geohash.append(_BASE32[char_index])
            bit = 0
            char_index = 0

    return "".join(geohash)


def decode_geohash_center(geohash: str) -> Tuple[float, float]:
    """Decode a geohash into the (latitude, longitude) of its bounding box centre."""
    if not geohash:
        raise ValueError("geohash must not be empty")

    lat_interval = [-90.0, 90.0]
    lon_interval = [-180.0, 180.0]
    even_bit = True

    for char in geohash.lower():
        try:
            value = _DECODE_MAP[char]
        except KeyError as exc:
            raise ValueError(f"invalid geohash character: {char!r}") from exc
        for mask in (16, 8, 4, 2, 1):
            if even_bit:
                mid = (lon_interval[0] + lon_interval[1]) / 2
                if value & mask:
                    lon_interval[0] = mid
                else:
                    lon_interval[1] = mid
            else:
                mid = (lat_interval[0] + lat_interval[1]) / 2
                if value & mask:
                    lat_interval[0] = mid
                else:
                    lat_interval[1] = mid
            even_bit = not even_bit

    latitude = (lat_interval[0] + lat_interval[1]) / 2
    longitude = (lon_interval[0] + lon_interval[1]) / 2
    return round(latitude, 7), round(longitude, 7)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two coordinates in kilometres."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))
