"""Generate a synthetic GLP-1 patient cohort for model training.

A hand-specified base cohort defines the marginal distributions, SDV's
GaussianCopulaSynthesizer learns the joint structure and resamples it, and the
`discontinued_90d` label is then applied to the sampled rows so the published
dropout drivers stay intact end to end.

Run:  python data/generate_synthetic.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_CSV = PROJECT_ROOT / "data" / "synthetic_patients.csv"

# Training cohort size, independent of how many patients the simulation runs.
# The labels are a Bernoulli draw so the achievable AUC is capped; 5000 rows
# closes to within ~0.02 of that ceiling where 500 left ~0.09 on the table.
N_PATIENTS = 5000
RANDOM_SEED = 42

INSURANCE_TYPES = ["commercial", "medicaid", "medicare", "uninsured"]
INSURANCE_WEIGHTS = [0.45, 0.25, 0.15, 0.15]
INCOME_QUINTILES = [1, 2, 3, 4, 5]
INCOME_WEIGHTS = [0.25, 0.25, 0.20, 0.15, 0.15]

# Baseline 90-day discontinuation rates observed in real-world GLP-1 cohorts.
BASE_RATE_AOM = 0.37
BASE_RATE_T2D = 0.18

# Each risk factor is expressed as the probability bump it would add to a
# patient sitting at the AOM base rate. They are converted to log-odds below so
# that stacking several factors stays inside a valid probability range.
RISK_BUMPS = {
    "plateau_slope": 0.15,
    "gi_event": 0.10,
    "coverage_gap": 0.10,
    "low_income": 0.08,
    "prior_pa_denial": 0.10,
    "repeat_reply_3": 0.18,
    # Non-response is the strongest real-world dropout signal: a patient who
    # has stopped answering has usually already stopped refilling.
    "no_reply_streak": 0.20,
}


def _logit(p):
    return np.log(p / (1.0 - p))


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _bump_to_log_odds(bump: float, reference: float = BASE_RATE_AOM) -> float:
    """Convert an additive probability bump into an additive log-odds weight."""
    return float(_logit(reference + bump) - _logit(reference))


def build_base_cohort(n: int, rng: np.random.Generator) -> pd.DataFrame:
    """Hand-built cohort with the marginal distributions we want SDV to learn."""
    # Right-skewed tenure: most patients are 4-16 weeks in, a long tail reaches 52.
    weeks = rng.exponential(scale=10.0, size=n) + 1.0
    weeks_on_therapy = np.clip(np.round(weeks), 1, 52).astype(int)

    # Percent body weight change per week. Negative means losing weight,
    # near-zero or positive means the scale has stalled.
    weight_change_slope = np.clip(rng.normal(loc=-0.55, scale=0.55, size=n), -2.0, 0.5)

    gi_event_flag = rng.binomial(1, 0.35, size=n)
    insurance_type = rng.choice(INSURANCE_TYPES, size=n, p=INSURANCE_WEIGHTS)
    income_quintile = rng.choice(INCOME_QUINTILES, size=n, p=INCOME_WEIGHTS)
    indication_flag = rng.binomial(1, 0.70, size=n)  # 1 = AOM, 0 = T2D
    prior_pa_denial = rng.binomial(1, 0.28, size=n)
    baseline_bmi = np.clip(rng.normal(loc=38.0, scale=6.0, size=n), 27.0, None)

    # Weeks in a row the patient answered "not seeing results".
    consecutive_reply_3 = rng.choice(
        [0, 1, 2, 3, 4], size=n, p=[0.45, 0.25, 0.15, 0.10, 0.05]
    )

    # Check-ins in a row the patient ignored entirely. Most people answer, and
    # the tail that does not is where dropout concentrates.
    consecutive_no_reply = rng.choice(
        [0, 1, 2, 3, 4], size=n, p=[0.55, 0.22, 0.12, 0.07, 0.04]
    )

    return pd.DataFrame(
        {
            "weeks_on_therapy": weeks_on_therapy,
            "weight_change_slope": np.round(weight_change_slope, 4),
            "gi_event_flag": gi_event_flag,
            "insurance_type": insurance_type,
            "income_quintile": income_quintile,
            "indication_flag": indication_flag,
            "prior_pa_denial": prior_pa_denial,
            "baseline_bmi": np.round(baseline_bmi, 2),
            "consecutive_reply_3": consecutive_reply_3,
            "consecutive_no_reply": consecutive_no_reply,
        }
    )


def _detect_metadata(df: pd.DataFrame):
    """Build SDV metadata across the 1.x metadata API variants."""
    try:
        from sdv.metadata import Metadata

        return Metadata.detect_from_dataframe(data=df, table_name="patients")
    except Exception:
        from sdv.metadata import SingleTableMetadata

        metadata = SingleTableMetadata()
        metadata.detect_from_dataframe(df)
        return metadata


def synthesize(base: pd.DataFrame, n: int) -> pd.DataFrame:
    """Fit a GaussianCopulaSynthesizer on the base cohort and resample it."""
    from sdv.single_table import GaussianCopulaSynthesizer

    metadata = _detect_metadata(base)
    synthesizer = GaussianCopulaSynthesizer(metadata, enforce_min_max_values=True)
    synthesizer.fit(base)
    return synthesizer.sample(num_rows=n)


def enforce_domain(df: pd.DataFrame) -> pd.DataFrame:
    """Clamp sampled values back into their clinically valid ranges."""
    df = df.copy()
    df["weeks_on_therapy"] = np.clip(df["weeks_on_therapy"].round(), 1, 52).astype(int)
    df["weight_change_slope"] = np.clip(df["weight_change_slope"], -2.0, 0.5).round(4)
    df["gi_event_flag"] = np.clip(df["gi_event_flag"].round(), 0, 1).astype(int)
    df["income_quintile"] = np.clip(df["income_quintile"].round(), 1, 5).astype(int)
    df["indication_flag"] = np.clip(df["indication_flag"].round(), 0, 1).astype(int)
    df["prior_pa_denial"] = np.clip(df["prior_pa_denial"].round(), 0, 1).astype(int)
    df["baseline_bmi"] = np.clip(df["baseline_bmi"], 27.0, None).round(2)
    df["consecutive_reply_3"] = np.clip(
        df["consecutive_reply_3"].round(), 0, 4
    ).astype(int)
    df["consecutive_no_reply"] = np.clip(
        df["consecutive_no_reply"].round(), 0, 4
    ).astype(int)
    df["insurance_type"] = df["insurance_type"].where(
        df["insurance_type"].isin(INSURANCE_TYPES), "commercial"
    )
    return df


def add_labels(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Draw discontinued_90d from a logistic model of the known dropout drivers."""
    df = df.copy()

    base_rate = np.where(df["indication_flag"] == 1, BASE_RATE_AOM, BASE_RATE_T2D)
    log_odds = _logit(base_rate)

    log_odds += (df["weight_change_slope"] > -0.1) * _bump_to_log_odds(
        RISK_BUMPS["plateau_slope"]
    )
    log_odds += (df["gi_event_flag"] == 1) * _bump_to_log_odds(RISK_BUMPS["gi_event"])
    log_odds += df["insurance_type"].isin(["medicaid", "uninsured"]) * _bump_to_log_odds(
        RISK_BUMPS["coverage_gap"]
    )
    log_odds += (df["income_quintile"] <= 2) * _bump_to_log_odds(
        RISK_BUMPS["low_income"]
    )
    log_odds += (df["prior_pa_denial"] == 1) * _bump_to_log_odds(
        RISK_BUMPS["prior_pa_denial"]
    )
    log_odds += (df["consecutive_reply_3"] >= 2) * _bump_to_log_odds(
        RISK_BUMPS["repeat_reply_3"]
    )
    log_odds += (df["consecutive_no_reply"] >= 2) * _bump_to_log_odds(
        RISK_BUMPS["no_reply_streak"]
    )

    probability = np.clip(_sigmoid(log_odds), 0.05, 0.95)
    df["dropout_probability"] = probability.round(4)
    df["discontinued_90d"] = rng.binomial(1, probability)
    return df


def main() -> None:
    rng = np.random.default_rng(RANDOM_SEED)

    base = build_base_cohort(N_PATIENTS, rng)

    try:
        sampled = synthesize(base, N_PATIENTS)
        source = "SDV GaussianCopulaSynthesizer"
    except Exception as exc:  # SDV missing or incompatible: fall back to the base draw
        print(f"[generate_synthetic] SDV unavailable ({exc}); using base cohort.")
        sampled = base
        source = "direct numpy sampling (SDV fallback)"

    sampled = enforce_domain(sampled)
    labelled = add_labels(sampled, rng)

    # The rest of the stack speaks in clinical labels, not flags.
    labelled["indication"] = np.where(labelled["indication_flag"] == 1, "AOM", "T2D")
    labelled = labelled.drop(columns=["indication_flag"])

    columns = [
        "weeks_on_therapy",
        "weight_change_slope",
        "gi_event_flag",
        "insurance_type",
        "income_quintile",
        "indication",
        "prior_pa_denial",
        "baseline_bmi",
        "consecutive_reply_3",
        "consecutive_no_reply",
        "dropout_probability",
        "discontinued_90d",
    ]
    labelled = labelled[columns]

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    labelled.to_csv(OUTPUT_CSV, index=False)

    print(f"\nGenerated {len(labelled)} synthetic patients via {source}")
    print(f"Saved to {OUTPUT_CSV}")

    print("\nClass distribution (discontinued_90d)")
    counts = labelled["discontinued_90d"].value_counts().sort_index()
    for label, count in counts.items():
        pct = 100.0 * count / len(labelled)
        name = "retained" if label == 0 else "discontinued"
        print(f"  {label} ({name}): {count} ({pct:.1f}%)")

    print("\nCorrelation of numeric features with discontinued_90d")
    numeric = labelled.select_dtypes(include=[np.number])
    correlations = (
        numeric.corr()["discontinued_90d"].drop("discontinued_90d").sort_values()
    )
    print(correlations.to_string(float_format=lambda v: f"{v: .3f}"))

    print("\nFirst 5 rows")
    print(labelled.head().to_string(index=False))


if __name__ == "__main__":
    main()
