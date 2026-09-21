"""Shared utilities for the VayuSetu Cloud Functions.

The package is vendored into each function directory by scripts/stage_functions.sh
before deployment so that every function remains a self-contained deployable
unit while the source of truth stays in one place.
"""

from vayusetu_common.aqi import aqi_category, aqi_category_label, clamp_aqi
from vayusetu_common.config import env_bool, env_float, env_int, env_list, env_str
from vayusetu_common.geo import decode_geohash_center, encode_geohash, haversine_km
from vayusetu_common.logging_utils import configure_logging, get_logger
from vayusetu_common.retry import (
    RetryExhaustedError,
    compute_backoff_seconds,
    is_rate_limit_error,
    is_transient_error,
    retry_after_seconds,
    retry_with_backoff,
)

__all__ = [
    "aqi_category",
    "aqi_category_label",
    "clamp_aqi",
    "env_bool",
    "env_float",
    "env_int",
    "env_list",
    "env_str",
    "decode_geohash_center",
    "encode_geohash",
    "haversine_km",
    "configure_logging",
    "get_logger",
    "RetryExhaustedError",
    "compute_backoff_seconds",
    "is_rate_limit_error",
    "is_transient_error",
    "retry_after_seconds",
    "retry_with_backoff",
]

__version__ = "1.0.0"
