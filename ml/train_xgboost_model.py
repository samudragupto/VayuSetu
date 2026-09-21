#!/usr/bin/env python3
"""Train the VayuSetu 12-hour AQI forecaster (zero-cost alternative to Vertex AI AutoML).

Runs locally, in CI or in Google Colab. Three data sources are supported:

    # Synthetic data (no cloud access required; used by CI and the Docker build)
    python ml/train_xgboost_model.py --source synthetic --rows 20000 --output ml/artifacts/model.joblib

    # A CSV export (for example from BigQuery or the mock data generator)
    python ml/train_xgboost_model.py --source csv --path ml/data/observations.csv

    # BigQuery (fused_observations view joined with a CPCB/ground-truth AQI table)
    python ml/train_xgboost_model.py --source bigquery --project my-project --dataset vayusetu \
        --label-table my-project.vayusetu.ground_truth_aqi

In Colab, authentication is handled automatically through google.colab.auth.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import pandas as pd  # noqa: E402

from vayusetu_ml.features import TARGET_COLUMN  # noqa: E402
from vayusetu_ml.synthetic import SyntheticObservationGenerator  # noqa: E402
from vayusetu_ml.training import feature_importance, save_bundle, train_model  # noqa: E402

logger = logging.getLogger("train_xgboost_model")

BIGQUERY_TRAINING_SQL = """
-- Join each fused observation with the ground-truth AQI observed 12 hours later
-- within the same geohash-5 cell. The label table is expected to contain
-- geohash5 STRING, observed_at TIMESTAMP and aqi FLOAT64 (for example CPCB
-- station readings mapped to cells).
WITH observations AS (
  SELECT
    o.report_id,
    o.received_at AS timestamp,
    o.latitude,
    o.longitude,
    SUBSTR(o.geohash, 1, 5) AS geohash5,
    o.city,
    o.haze_index,
    o.visibility_km,
    CAST(o.smoke_detected AS FLOAT64) AS smoke_ratio,
    CAST(o.dust_detected AS FLOAT64) AS dust_ratio,
    CAST(o.open_burning_detected AS FLOAT64) AS open_burning_ratio,
    CAST(o.fog_or_mist_detected AS FLOAT64) AS fog_ratio,
    o.vehicle_density_score,
    o.construction_activity_score,
    o.industrial_emission_score,
    o.estimated_aqi AS vision_aqi_estimate,
    o.vision_confidence,
    o.aer_ai,
    o.no2_tropospheric_mol_m2,
    o.co_column_mol_m2,
    o.aod_047,
    o.estimated_aqi AS current_aqi
  FROM `{project}.{dataset}.fused_observations` o
  WHERE o.received_at BETWEEN TIMESTAMP('{start}') AND TIMESTAMP('{end}')
),
labels AS (
  SELECT geohash5, observed_at, aqi
  FROM `{label_table}`
)
SELECT
  obs.*,
  1 AS report_count,
  lbl.aqi AS {target}
FROM observations obs
JOIN labels lbl
  ON lbl.geohash5 = obs.geohash5
 AND lbl.observed_at BETWEEN TIMESTAMP_ADD(obs.timestamp, INTERVAL 11 HOUR)
                          AND TIMESTAMP_ADD(obs.timestamp, INTERVAL 13 HOUR)
"""


def _maybe_authenticate_colab() -> None:
    """Authenticate transparently when running inside Google Colab."""
    if "google.colab" in sys.modules or os.environ.get("COLAB_RELEASE_TAG"):
        try:
            from google.colab import auth  # type: ignore

            auth.authenticate_user()
            logger.info("Authenticated Colab user for BigQuery access")
        except Exception as exc:  # noqa: BLE001 - authentication is best effort
            logger.warning("Colab authentication failed: %s", exc)


def load_synthetic(rows: int, seed: int) -> pd.DataFrame:
    logger.info("Generating %d synthetic observations (seed %d)", rows, seed)
    return SyntheticObservationGenerator(seed=seed).generate_frame(rows)


def load_csv(path: str) -> pd.DataFrame:
    logger.info("Loading CSV %s", path)
    frame = pd.read_csv(path)
    if TARGET_COLUMN not in frame.columns:
        raise SystemExit(f"CSV must contain a '{TARGET_COLUMN}' column with the 12-hour-ahead AQI label")
    return frame


def load_bigquery(project: str, dataset: str, label_table: str, start: str, end: str, weather_csv: Optional[str]) -> pd.DataFrame:
    _maybe_authenticate_colab()
    from google.cloud import bigquery

    client = bigquery.Client(project=project)
    sql = BIGQUERY_TRAINING_SQL.format(
        project=project, dataset=dataset, label_table=label_table, start=start, end=end, target=TARGET_COLUMN
    )
    logger.info("Querying BigQuery for training data between %s and %s", start, end)
    frame = client.query(sql).result().to_dataframe(create_bqstorage_client=False)
    if frame.empty:
        raise SystemExit("BigQuery returned no labelled rows; check the label table and date range")

    if weather_csv:
        # Optional hourly weather export with columns: geohash5, timestamp, temperature_c, humidity_pct,
        # wind_speed_ms, wind_direction_deg, precipitation_mm, pressure_hpa, boundary_layer_height_m
        weather = pd.read_csv(weather_csv)
        weather["timestamp"] = pd.to_datetime(weather["timestamp"], utc=True).dt.floor("h")
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame["_join_hour"] = frame["timestamp"].dt.floor("h")
        frame = frame.merge(weather, left_on=["geohash5", "_join_hour"], right_on=["geohash5", "timestamp"], how="left", suffixes=("", "_weather"))
        frame = frame.drop(columns=[c for c in frame.columns if c.endswith("_weather") or c == "_join_hour"])
    else:
        logger.warning("No weather export supplied; weather features will use climatological defaults")
    return frame


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the VayuSetu XGBoost 12-hour AQI model")
    parser.add_argument("--source", choices=["synthetic", "csv", "bigquery"], default="synthetic")
    parser.add_argument("--rows", type=int, default=20000, help="Rows to generate for the synthetic source")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--path", help="CSV path for --source csv")
    parser.add_argument("--project", default=os.environ.get("GCP_PROJECT_ID"), help="GCP project for --source bigquery")
    parser.add_argument("--dataset", default=os.environ.get("BIGQUERY_DATASET", "vayusetu"))
    parser.add_argument("--label-table", help="Fully qualified BigQuery table with ground-truth AQI labels")
    parser.add_argument("--start", default="2025-01-01", help="Training window start (BigQuery source)")
    parser.add_argument("--end", default="2030-01-01", help="Training window end (BigQuery source)")
    parser.add_argument("--weather-csv", help="Optional hourly weather export to join on geohash5 and hour")
    parser.add_argument("--output", default=os.path.join(_HERE, "artifacts", "model.joblib"))
    parser.add_argument("--validation-fraction", type=float, default=0.2)
    parser.add_argument("--n-estimators", type=int, default=None)
    parser.add_argument("--max-depth", type=int, default=None)
    parser.add_argument("--learning-rate", type=float, default=None)
    parser.add_argument("--model-version", default=None)
    parser.add_argument("--export-csv", help="Optionally write the training frame to this CSV path")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.source == "synthetic":
        frame = load_synthetic(args.rows, args.seed)
    elif args.source == "csv":
        if not args.path:
            raise SystemExit("--path is required for --source csv")
        frame = load_csv(args.path)
    else:
        if not (args.project and args.label_table):
            raise SystemExit("--project and --label-table are required for --source bigquery")
        frame = load_bigquery(args.project, args.dataset, args.label_table, args.start, args.end, args.weather_csv)

    if args.export_csv:
        os.makedirs(os.path.dirname(os.path.abspath(args.export_csv)), exist_ok=True)
        frame.to_csv(args.export_csv, index=False)
        logger.info("Exported training frame to %s", args.export_csv)

    overrides = {
        key: value
        for key, value in {
            "n_estimators": args.n_estimators,
            "max_depth": args.max_depth,
            "learning_rate": args.learning_rate,
        }.items()
        if value is not None
    }

    bundle = train_model(frame, hyperparameters=overrides, validation_fraction=args.validation_fraction, model_version=args.model_version)
    save_bundle(bundle, args.output)

    print(json.dumps({"model_version": bundle.model_version, "output": os.path.abspath(args.output), "metrics": bundle.metrics}, indent=2))
    print("Top features by gain:")
    for item in feature_importance(bundle, top_n=10):
        print(f"  {item['feature']:<28} share={item['share']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
