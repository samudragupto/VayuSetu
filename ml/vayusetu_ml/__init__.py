"""VayuSetu machine learning library.

Shared between the training script (``ml/train_xgboost_model.py``), the Cloud
Run prediction service and the batch prediction Cloud Function, so that feature
engineering is defined exactly once.
"""

from vayusetu_ml.features import (
    FEATURE_COLUMNS,
    TARGET_COLUMN,
    FeatureVector,
    build_feature_frame,
    coerce_observation,
    default_feature_values,
)

__all__ = [
    "FEATURE_COLUMNS",
    "TARGET_COLUMN",
    "FeatureVector",
    "build_feature_frame",
    "coerce_observation",
    "default_feature_values",
]

__version__ = "1.0.0"
