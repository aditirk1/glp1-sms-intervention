"""Dropout risk scoring with per-patient SHAP attribution.

score_patient() returns both a probability and the reason behind it: the
highest-magnitude SHAP feature is mapped to a barrier type, which is what the
webhook uses to pick an intervention.

The model, feature column list and SHAP explainer are cached at module level.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = PROJECT_ROOT / "model" / "model.joblib"
FEATURE_COLUMNS_PATH = PROJECT_ROOT / "model" / "feature_columns.json"

CATEGORICAL_FEATURES = ["insurance_type", "indication"]

AMBER_THRESHOLD = 0.35
RED_THRESHOLD = 0.60

_model = None
_feature_columns = None
_explainer = None

# Fired when the model artefact is missing, so the webhook still returns a
# usable envelope instead of a 500.
_NEUTRAL_RESULT = {
    "risk_score": 0.5,
    "risk_tier": "amber",
    "barrier_type": "plateau",
    "top_shap_feature": "unavailable",
    "barrier_feature": "unavailable",
    "shap_values": {},
}


def load_model():
    """Load and cache model.joblib, the feature column list and the explainer."""
    global _model, _feature_columns, _explainer

    if _model is None:
        import joblib
        import shap

        if not MODEL_PATH.exists() or not FEATURE_COLUMNS_PATH.exists():
            raise FileNotFoundError(
                f"{MODEL_PATH} not found. Run: python model/train_model.py"
            )

        _model = joblib.load(MODEL_PATH)
        with open(FEATURE_COLUMNS_PATH, encoding="utf-8") as handle:
            _feature_columns = json.load(handle)
        _explainer = shap.TreeExplainer(_model)

    return _model, _feature_columns, _explainer


def risk_tier_for_score(risk_score: float) -> str:
    """green below 0.35, amber through 0.60, red above."""
    if risk_score < AMBER_THRESHOLD:
        return "green"
    if risk_score <= RED_THRESHOLD:
        return "amber"
    return "red"


def _barrier_for_feature(feature: str) -> str:
    """Map a SHAP feature to the barrier the care team can act on."""
    if feature in ("weight_change_slope", "consecutive_reply_3"):
        return "plateau"
    if "gi_event_flag" in feature:
        return "side_effect"
    if (
        "income_quintile" in feature
        or "prior_pa_denial" in feature
        or "insurance_type" in feature
    ):
        return "cost"
    return "plateau"


def _is_actionable(feature: str) -> bool:
    """True for features that correspond to a barrier an intervention can address.

    indication, weeks_on_therapy and baseline_bmi are fixed patient attributes.
    They can dominate the SHAP ranking without pointing at anything the care
    team can do, so they are excluded when choosing the barrier.
    """
    return _barrier_for_feature(feature) != "plateau" or feature in (
        "weight_change_slope",
        "consecutive_reply_3",
    )


def _encode(patient_dict: dict, feature_columns: list) -> pd.DataFrame:
    """One-hot encode a single patient and align it to the training columns."""
    row = pd.DataFrame([patient_dict])
    for column in CATEGORICAL_FEATURES:
        if column not in row.columns:
            row[column] = None
    encoded = pd.get_dummies(row, columns=CATEGORICAL_FEATURES, drop_first=False)
    # Unseen categories drop out, absent categories fill with 0, order is restored.
    return encoded.reindex(columns=feature_columns, fill_value=0).astype(float)


def score_patient(patient_dict: dict) -> dict:
    """Score one patient and explain the score.

    Returns risk_score, risk_tier, barrier_type, top_shap_feature and the full
    per-feature SHAP dict.
    """
    try:
        model, feature_columns, explainer = load_model()
        encoded = _encode(patient_dict, feature_columns)

        risk_score = float(model.predict_proba(encoded)[0][1])

        shap_values = explainer.shap_values(encoded)
        values = np.asarray(shap_values)
        if values.ndim == 3:
            # Some SHAP/XGBoost combinations return one matrix per class.
            values = values[..., -1]
        contributions = np.asarray(values).reshape(-1)[: len(feature_columns)]

        shap_map = {
            feature: float(value)
            for feature, value in zip(feature_columns, contributions)
        }
        top_feature = max(shap_map, key=lambda key: abs(shap_map[key]))

        actionable = [f for f in shap_map if _is_actionable(f)]
        barrier_feature = (
            max(actionable, key=lambda key: abs(shap_map[key]))
            if actionable
            else top_feature
        )

        return {
            "risk_score": risk_score,
            "risk_tier": risk_tier_for_score(risk_score),
            "barrier_type": _barrier_for_feature(barrier_feature),
            "top_shap_feature": top_feature,
            "barrier_feature": barrier_feature,
            "shap_values": shap_map,
        }
    except Exception as exc:
        print(f"[risk_scorer] scoring failed ({exc}); returning neutral risk.")
        return dict(_NEUTRAL_RESULT)
