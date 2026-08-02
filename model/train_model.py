"""Train the GoalPost¹ dropout-risk classifier.

Fits an XGBoost model on the synthetic cohort, reports held-out performance,
ranks the drivers with SHAP, and writes the artefacts the API loads at runtime.

Run:  python model/train_model.py
"""

import json
from pathlib import Path

import joblib
import pandas as pd
import shap
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_CSV = PROJECT_ROOT / "data" / "synthetic_patients.csv"
MODEL_PATH = PROJECT_ROOT / "model" / "model.joblib"
FEATURE_COLUMNS_PATH = PROJECT_ROOT / "model" / "feature_columns.json"

NUMERIC_FEATURES = [
    "weeks_on_therapy",
    "weight_change_slope",
    "gi_event_flag",
    "income_quintile",
    "prior_pa_denial",
    "baseline_bmi",
    "consecutive_reply_3",
    "consecutive_no_reply",
]
CATEGORICAL_FEATURES = ["insurance_type", "indication"]
TARGET = "discontinued_90d"

RANDOM_STATE = 42


def build_feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Numeric columns plus explicit one-hot columns for every category."""
    features = df[NUMERIC_FEATURES + CATEGORICAL_FEATURES].copy()
    return pd.get_dummies(features, columns=CATEGORICAL_FEATURES, drop_first=False)


def build_classifier(scale_pos_weight: float) -> XGBClassifier:
    params = dict(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        scale_pos_weight=scale_pos_weight,
        eval_metric="auc",
        random_state=RANDOM_STATE,
    )
    try:
        # Removed in XGBoost 2.x; kept for parity with older installs.
        return XGBClassifier(use_label_encoder=False, **params)
    except TypeError:
        return XGBClassifier(**params)


def main() -> None:
    if not DATA_CSV.exists():
        raise SystemExit(
            f"{DATA_CSV} not found. Run: python data/generate_synthetic.py"
        )

    df = pd.read_csv(DATA_CSV)
    X = build_feature_matrix(df)
    y = df[TARGET].astype(int)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=RANDOM_STATE
    )

    negatives = int((y_train == 0).sum())
    positives = int((y_train == 1).sum())
    scale_pos_weight = negatives / max(positives, 1)

    print(f"Training rows: {len(X_train)}   Test rows: {len(X_test)}")
    print(f"scale_pos_weight: {scale_pos_weight:.3f}")

    model = build_classifier(scale_pos_weight)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]

    print("\nClassification report (test set)")
    print(
        classification_report(
            y_test, y_pred, target_names=["retained", "discontinued"], digits=3
        )
    )
    print(f"ROC-AUC (test set): {roc_auc_score(y_test, y_proba):.3f}")

    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_test)
    mean_abs_shap = (
        pd.DataFrame(shap_values, columns=X_test.columns)
        .abs()
        .mean()
        .sort_values(ascending=False)
    )

    print("\nTop 5 features by mean absolute SHAP value")
    for rank, (feature, value) in enumerate(mean_abs_shap.head(5).items(), start=1):
        print(f"  {rank}. {feature}: {value:.4f}")

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    with open(FEATURE_COLUMNS_PATH, "w", encoding="utf-8") as handle:
        json.dump(list(X.columns), handle, indent=2)

    print(f"\nSaved model to {MODEL_PATH}")
    print(f"Saved {len(X.columns)} feature columns to {FEATURE_COLUMNS_PATH}")


if __name__ == "__main__":
    main()
