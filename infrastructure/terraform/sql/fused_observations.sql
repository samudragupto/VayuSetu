-- Deduplicated join of Gemini vision metrics and Earth Engine satellite metrics.
-- Each report may be written more than once when an upstream function retries,
-- so the most recent row per report_id wins.
WITH latest_reports AS (
  SELECT
    *
  FROM `${project}.${dataset}.citizen_reports`
  WHERE haze_index IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY report_id ORDER BY analyzed_at DESC) = 1
),
latest_satellite AS (
  SELECT
    *
  FROM `${project}.${dataset}.satellite_metrics`
  QUALIFY ROW_NUMBER() OVER (PARTITION BY report_id ORDER BY fetched_at DESC) = 1
)
SELECT
  r.report_id,
  r.received_at,
  r.analyzed_at,
  r.latitude,
  r.longitude,
  r.geohash,
  r.city,
  r.is_outdoor_scene,
  r.haze_index,
  r.visibility_km,
  r.visibility_category,
  r.sky_condition,
  r.smoke_detected,
  r.dust_detected,
  r.fog_or_mist_detected,
  r.open_burning_detected,
  r.vehicle_density_score,
  r.construction_activity_score,
  r.industrial_emission_score,
  r.pollution_sources,
  r.estimated_aqi,
  r.estimated_aqi_category,
  r.confidence AS vision_confidence,
  r.model_name,
  s.aer_ai,
  s.no2_tropospheric_mol_m2,
  s.co_column_mol_m2,
  s.so2_column_mol_m2,
  s.aod_047,
  s.s5p_image_count,
  s.modis_image_count,
  s.source AS satellite_source,
  s.fetched_at AS satellite_fetched_at
FROM latest_reports AS r
LEFT JOIN latest_satellite AS s
  USING (report_id)
