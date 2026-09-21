"""Training pipeline for the 12-hour AQI XGBoost regressor."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import platform
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd

from vayusetu_ml.features import FEATURE_COLUMNS, TARGET_COLUMN, build_feature_frame

logger = logging.getLogger(__name__)

MODEL_FORMAT_VERSION = 1


@dataclass
class TrainingMetrics:
    rows_total: int
    rows_train: int
    rows_validation: int
    mae: float
    rmse: float
    r2: float
    mae_baseline_persistence: Optional[float]
    within_one_category_pct: float
    trained_at: str
    training_seconds: float


@dataclass
class ModelBundle:
    """Everything the prediction service needs, serialised with joblib."""

    model: Any
    feature_columns: List[str]
    target_column: str
    model_version: str
    metrics: Dict[str, Any]
    hyperparameters: Dict[str, Any]
    format_version: int = MODEL_FORMAT_VERSION
    library_versions: Optional[Dict[str, str]] = None

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        missing = [c for c in self.feature_columns if c not in frame.columns]
        if missing:
            raise ValueError(f"Feature frame is missing columns: {missing}")
        predictions = self.model.predict(frame[self.feature_columns].astype(float))
        return np.clip(np.asarray(predictions, dtype=float), 0.0, 500.0)


DEFAULT_HYPERPARAMETERS: Dict[str, Any] = {
    "n_estimators": 600,
    "learning_rate": 0.03,
    "max_depth": 6,
    "min_child_weight": 3,
    "subsample": 0.85,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.1,
    "reg_lambda": 1.5,
    "gamma": 0.0,
    "objective": "reg:squarederror",
    "tree_method": "hist",
    "random_state": 42,
    "n_jobs": -1,
}


def _category_index(values: np.ndarray) -> np.ndarray:
    bins = np.array([50, 100, 200, 300, 400], dtype=float)
    return np.digitize(values, bins, right=True)


def prepare_training_frame(raw: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Return (features, target, timestamps) from a raw observation frame."""
    if TARGET_COLUMN not in raw.columns:
        raise ValueError(f"Training data must contain the target column '{TARGET_COLUMN}'")
    raw = raw.dropna(subset=[TARGET_COLUMN]).reset_index(drop=True)
    if raw.empty:
        raise ValueError("Training data is empty after dropping rows without target")
    if "timestamp" not in raw.columns:
        for candidate in ("observed_at", "received_at", "generated_at"):
            if candidate in raw.columns:
                raw = raw.rename(columns={candidate: "timestamp"})
                break
        else:
            raise ValueError("Training data must contain a timestamp column")
    records = raw.to_dict(orient="records")
    features = build_feature_frame(records)
    target = raw[TARGET_COLUMN].astype(float).clip(0, 500).reset_index(drop=True)
    timestamps = pd.to_datetime(raw["timestamp"], utc=True).reset_index(drop=True)
    return features, target, timestamps


def time_based_split(timestamps: pd.Series, validation_fraction: float = 0.2) -> Tuple[np.ndarray, np.ndarray]:
    """Chronological split: the most recent fraction of rows is held out."""
    order = np.argsort(timestamps.values)
    cutoff = int(len(order) * (1.0 - validation_fraction))
    cutoff = min(max(cutoff, 1), len(order) - 1)
    return order[:cutoff], order[cutoff:]


def train_model(
    raw: pd.DataFrame,
    hyperparameters: Optional[Dict[str, Any]] = None,
    validation_fraction: float = 0.2,
    model_version: Optional[str] = None,
) -> ModelBundle:
    """Train an XGBoost regressor and return a serialisable bundle."""
    import time

    import xgboost as xgb
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

    params = dict(DEFAULT_HYPERPARAMETERS)
    params.update(hyperparameters or {})

    features, target, timestamps = prepare_training_frame(raw)
    train_idx, val_idx = time_based_split(timestamps, validation_fraction)

    x_train, y_train = features.iloc[train_idx], target.iloc[train_idx]
    x_val, y_val = features.iloc[val_idx], target.iloc[val_idx]

    logger.info("Training XGBoost on %d rows, validating on %d rows", len(x_train), len(x_val))
    started = time.monotonic()
    model = xgb.XGBRegressor(**params, early_stopping_rounds=40, eval_metric="mae")
    model.fit(x_train, y_train, eval_set=[(x_val, y_val)], verbose=False)
    training_seconds = time.monotonic() - started

    predictions = np.clip(model.predict(x_val), 0, 500)
    mae = float(mean_absolute_error(y_val, predictions))
    rmse = float(np.sqrt(mean_squared_error(y_val, predictions)))
    r2 = float(r2_score(y_val, predictions)) if len(y_val) > 1 else 0.0
    within_one = float(np.mean(np.abs(_category_index(predictions) - _category_index(y_val.values)) <= 1) * 100.0)

    baseline_mae: Optional[float] = None
    if "current_aqi" in raw.columns:
        persistence = raw["current_aqi"].astype(float).reset_index(drop=True).iloc[val_idx]
        baseline_mae = float(mean_absolute_error(y_val, persistence.clip(0, 500)))

    metrics = TrainingMetrics(
        rows_total=int(len(features)),
        rows_train=int(len(x_train)),
        rows_validation=int(len(x_val)),
        mae=round(mae, 3),
        rmse=round(rmse, 3),
        r2=round(r2, 4),
        mae_baseline_persistence=None if baseline_mae is None else round(baseline_mae, 3),
        within_one_category_pct=round(within_one, 2),
        trained_at=dt.datetime.now(tz=dt.timezone.utc).isoformat(),
        training_seconds=round(training_seconds, 2),
    )
    logger.info("Validation MAE %.2f, RMSE %.2f, R2 %.3f", mae, rmse, r2)

    best_iteration = getattr(model, "best_iteration", None)
    params_used = dict(params)
    if best_iteration is not None:
        params_used["best_iteration"] = int(best_iteration)

    return ModelBundle(
        model=model,
        feature_columns=list(FEATURE_COLUMNS),
        target_column=TARGET_COLUMN,
        model_version=model_version or dt.datetime.now(tz=dt.timezone.utc).strftime("xgb-%Y%m%d%H%M%S"),
        metrics=asdict(metrics),
        hyperparameters=params_used,
        library_versions={
            "python": platform.python_version(),
            "xgboost": xgb.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
        },
    )


def feature_importance(bundle: ModelBundle, top_n: int = 15) -> List[Dict[str, Any]]:
    """Return the most influential features by gain."""
    booster = bundle.model.get_booster()
    scores = booster.get_score(importance_type="gain")
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    total = sum(scores.values()) or 1.0
    return [{"feature": name, "gain": round(value, 3), "share": round(value / total, 4)} for name, value in ranked]


def save_bundle(bundle: ModelBundle, path: str) -> str:
    """Persist the bundle with joblib alongside a metrics JSON sidecar."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    joblib.dump(asdict(bundle) | {"model": bundle.model}, path, compress=3)
    sidecar = os.path.join(directory, "model_metrics.json")
    with open(sidecar, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "model_version": bundle.model_version,
                "metrics": bundle.metrics,
                "hyperparameters": bundle.hyperparameters,
                "feature_columns": bundle.feature_columns,
                "feature_importance": feature_importance(bundle),
                "library_versions": bundle.library_versions,
            },
            handle,
            indent=2,
        )
    logger.info("Saved model bundle to %s", path)
    return path


def load_bundle(path: str) -> ModelBundle:
    """Load a bundle produced by :func:`save_bundle`."""
    payload = joblib.load(path)
    if isinstance(payload, ModelBundle):
        return payload
    if not isinstance(payload, dict) or "model" not in payload:
        raise ValueError(f"{path} is not a VayuSetu model bundle")
    return ModelBundle(
        model=payload["model"],
        feature_columns=list(payload.get("feature_columns") or FEATURE_COLUMNS),
        target_column=payload.get("target_column", TARGET_COLUMN),
        model_version=payload.get("model_version", "unknown"),
        metrics=payload.get("metrics") or {},
        hyperparameters=payload.get("hyperparameters") or {},
        format_version=int(payload.get("format_version", MODEL_FORMAT_VERSION)),
        library_versions=payload.get("library_versions"),
    )
