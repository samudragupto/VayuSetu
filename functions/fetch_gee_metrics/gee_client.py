"""Google Earth Engine client for Sentinel-5P and MODIS metrics.

Datasets
--------
* ``COPERNICUS/S5P/OFFL/L3_AER_AI`` - UV aerosol index (band ``absorbing_aerosol_index``)
* ``COPERNICUS/S5P/OFFL/L3_NO2``   - tropospheric NO2 column (``tropospheric_NO2_column_number_density``)
* ``COPERNICUS/S5P/OFFL/L3_CO``    - CO column (``CO_column_number_density``)
* ``COPERNICUS/S5P/OFFL/L3_SO2``   - SO2 column (``SO2_column_number_density``)
* ``MODIS/061/MCD19A2_GRANULES``   - MAIAC aerosol optical depth at 470 nm (``Optical_Depth_047``)

All reductions are batched into a single server-side ``ee.Dictionary`` so each
report costs exactly one ``getInfo`` round trip against the noncommercial
Earth Engine quota.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import math
import threading
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from vayusetu_common.retry import retry_with_backoff

logger = logging.getLogger(__name__)

EE_SCOPES = [
    "https://www.googleapis.com/auth/earthengine",
    "https://www.googleapis.com/auth/cloud-platform",
]
EE_HIGH_VOLUME_URL = "https://earthengine-highvolume.googleapis.com"

S5P_SCALE_M = 1113.2
MODIS_SCALE_M = 1000.0
MODIS_AOD_SCALE_FACTOR = 0.001


class EarthEngineError(RuntimeError):
    """Raised when Earth Engine cannot serve a request."""


@dataclass
class SatelliteMetrics:
    aer_ai: Optional[float]
    no2_tropospheric_mol_m2: Optional[float]
    co_column_mol_m2: Optional[float]
    so2_column_mol_m2: Optional[float]
    aod_047: Optional[float]
    s5p_image_count: int
    modis_image_count: int
    window_start: dt.datetime
    window_end: dt.datetime
    buffer_radius_m: int
    lookback_days: int
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


class EarthEngineClient:
    """Thread-safe, lazily initialised Earth Engine accessor."""

    _init_lock = threading.Lock()
    _initialised_for: Optional[str] = None

    def __init__(self, project: str, buffer_radius_m: int = 5000, lookback_days: int = 3, use_high_volume: bool = True) -> None:
        if not project:
            raise ValueError("An Earth Engine enabled Cloud project is required")
        self.project = project
        self.buffer_radius_m = buffer_radius_m
        self.lookback_days = lookback_days
        self.use_high_volume = use_high_volume

    # -- initialisation ---------------------------------------------------

    def initialise(self) -> None:
        """Initialise the Earth Engine library once per process using ADC."""
        with EarthEngineClient._init_lock:
            if EarthEngineClient._initialised_for == self.project:
                return
            try:
                import ee
                import google.auth
            except ImportError as exc:  # pragma: no cover - dependency present in deployment
                raise EarthEngineError("earthengine-api is not installed") from exc

            try:
                credentials, _ = google.auth.default(scopes=EE_SCOPES)
                init_kwargs: Dict[str, Any] = {"credentials": credentials, "project": self.project}
                if self.use_high_volume:
                    init_kwargs["opt_url"] = EE_HIGH_VOLUME_URL
                ee.Initialize(**init_kwargs)
            except Exception as exc:  # noqa: BLE001 - normalise all init failures
                raise EarthEngineError(f"Earth Engine initialisation failed: {exc}") from exc

            EarthEngineClient._initialised_for = self.project
            logger.info("Earth Engine initialised", extra={"gee_project": self.project})

    # -- queries ----------------------------------------------------------

    @retry_with_backoff(max_attempts=4, base_delay=2.0, max_delay=30.0, operation_name="earth_engine_query")
    def fetch_metrics(self, latitude: float, longitude: float, observed_at: dt.datetime) -> SatelliteMetrics:
        """Return area-averaged satellite metrics around a point for the lookback window."""
        self.initialise()
        import ee

        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=dt.timezone.utc)
        window_end = observed_at
        window_start = observed_at - dt.timedelta(days=self.lookback_days)

        point = ee.Geometry.Point([longitude, latitude])
        region = point.buffer(self.buffer_radius_m)
        start = ee.Date(window_start.isoformat())
        end = ee.Date(window_end.isoformat())

        def mean_over_region(collection_id: str, band: str, scale: float) -> tuple[Any, Any]:
            collection = ee.ImageCollection(collection_id).select(band).filterDate(start, end).filterBounds(region)
            count = collection.size()
            # ee.Algorithms.If keeps the reduction server-side even when the collection is empty.
            mean_value = ee.Algorithms.If(
                count.gt(0),
                collection.mean().reduceRegion(
                    reducer=ee.Reducer.mean(), geometry=region, scale=scale, maxPixels=1e9, bestEffort=True
                ).get(band),
                None,
            )
            return mean_value, count

        aer_ai, aer_count = mean_over_region("COPERNICUS/S5P/OFFL/L3_AER_AI", "absorbing_aerosol_index", S5P_SCALE_M)
        no2, no2_count = mean_over_region("COPERNICUS/S5P/OFFL/L3_NO2", "tropospheric_NO2_column_number_density", S5P_SCALE_M)
        co, _ = mean_over_region("COPERNICUS/S5P/OFFL/L3_CO", "CO_column_number_density", S5P_SCALE_M)
        so2, _ = mean_over_region("COPERNICUS/S5P/OFFL/L3_SO2", "SO2_column_number_density", S5P_SCALE_M)
        aod, aod_count = mean_over_region("MODIS/061/MCD19A2_GRANULES", "Optical_Depth_047", MODIS_SCALE_M)

        payload = ee.Dictionary(
            {
                "aer_ai": aer_ai,
                "no2": no2,
                "co": co,
                "so2": so2,
                "aod": aod,
                "s5p_count": ee.Number(aer_count).max(ee.Number(no2_count)),
                "modis_count": aod_count,
            }
        )

        try:
            result: Dict[str, Any] = payload.getInfo()
        except Exception as exc:  # noqa: BLE001 - wrap for consistent retry classification
            raise EarthEngineError(f"Earth Engine query failed: {exc}") from exc

        aod_value = _to_float(result.get("aod"))
        metrics = SatelliteMetrics(
            aer_ai=_round(_to_float(result.get("aer_ai")), 4),
            no2_tropospheric_mol_m2=_round(_to_float(result.get("no2")), 8),
            co_column_mol_m2=_round(_to_float(result.get("co")), 6),
            so2_column_mol_m2=_round(_to_float(result.get("so2")), 8),
            aod_047=_round(aod_value * MODIS_AOD_SCALE_FACTOR if aod_value is not None else None, 4),
            s5p_image_count=_to_int(result.get("s5p_count")),
            modis_image_count=_to_int(result.get("modis_count")),
            window_start=window_start,
            window_end=window_end,
            buffer_radius_m=self.buffer_radius_m,
            lookback_days=self.lookback_days,
            source="earth_engine",
        )
        logger.info(
            "Earth Engine metrics fetched",
            extra={"aer_ai": metrics.aer_ai, "no2": metrics.no2_tropospheric_mol_m2, "s5p_images": metrics.s5p_image_count},
        )
        return metrics


def _round(value: Optional[float], digits: int) -> Optional[float]:
    return None if value is None else round(value, digits)


def mock_metrics(
    latitude: float,
    longitude: float,
    observed_at: dt.datetime,
    buffer_radius_m: int = 5000,
    lookback_days: int = 3,
) -> SatelliteMetrics:
    """Deterministic, physically plausible metrics for local development.

    Values are seeded from the coordinates and the calendar day so repeated runs
    are stable while different locations still differ. Winter months over the
    Indo-Gangetic plain are biased upwards to mirror the real seasonal cycle.
    """
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=dt.timezone.utc)
    seed_source = f"{round(latitude, 2)}:{round(longitude, 2)}:{observed_at.date().isoformat()}"
    digest = hashlib.sha256(seed_source.encode("utf-8")).digest()
    unit = [b / 255.0 for b in digest[:6]]

    month = observed_at.month
    winter_boost = 1.0 if month in (11, 12, 1) else (0.6 if month in (2, 10) else 0.2)
    northern_plain = 1.0 if 24.0 <= latitude <= 31.0 and 74.0 <= longitude <= 88.0 else 0.4
    severity = min(1.0, 0.25 + 0.45 * winter_boost * northern_plain + 0.3 * unit[0])

    return SatelliteMetrics(
        aer_ai=round(-0.5 + 3.0 * severity + 0.4 * (unit[1] - 0.5), 4),
        no2_tropospheric_mol_m2=round((0.00004 + 0.00016 * severity) * (0.8 + 0.4 * unit[2]), 8),
        co_column_mol_m2=round((0.025 + 0.03 * severity) * (0.9 + 0.2 * unit[3]), 6),
        so2_column_mol_m2=round((0.0001 + 0.0004 * severity) * (0.8 + 0.4 * unit[4]), 8),
        aod_047=round(0.15 + 1.2 * severity + 0.2 * (unit[5] - 0.5), 4),
        s5p_image_count=2 + int(unit[0] * 3),
        modis_image_count=1 + int(unit[1] * 4),
        window_start=observed_at - dt.timedelta(days=lookback_days),
        window_end=observed_at,
        buffer_radius_m=buffer_radius_m,
        lookback_days=lookback_days,
        source="mock",
    )
