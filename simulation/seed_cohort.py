"""Seed a patient cohort for the simulation.

Draws demographics from the same synthetic CSV the model trained on, then
staggers therapy_start_date so the cohort spans weeks 1-52 of treatment rather
than everyone standing at week 0. Tenure spread matters: the early-titration
cadence override and the GI barrier only bite in the first weeks, and plateaus
cluster much later.

Run:  python -m simulation.seed_cohort --patients 1000 --reset
"""

import argparse
import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from db.database import Base, SessionLocal, create_tables, engine
from db.models import STATUS_ACTIVE, Patient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_CSV = PROJECT_ROOT / "data" / "synthetic_patients.csv"

DEFAULT_PATIENTS = 1000
RANDOM_SEED = 7

# Tenure is right-skewed the way a real enrolled panel is: a steady intake of
# new starts plus a thinning tail of long-term patients.
MAX_TENURE_WEEKS = 52
TENURE_MEAN_WEEKS = 14.0

FIRST_NAMES = [
    "Maria", "James", "Aisha", "Robert", "Linda", "David", "Sofia", "Michael",
    "Grace", "Daniel", "Nina", "Carlos", "Ruth", "Thomas", "Priya", "Kevin",
    "Elena", "Marcus", "Hannah", "Omar", "Claire", "Andre", "Rosa", "Peter",
    "Yara", "Nathan", "Leah", "Victor", "Amara", "Simon", "Dana", "Felix",
]

LAST_NAMES = [
    "Alvarez", "Bennett", "Chen", "Dawson", "Ellis", "Foster", "Garcia",
    "Hughes", "Ibrahim", "Jensen", "Khan", "Lopez", "Mensah", "Novak",
    "Osei", "Patel", "Quinn", "Ramirez", "Silva", "Tran", "Ueda", "Vargas",
    "Walker", "Xu", "Young", "Zhang", "Brooks", "Cole", "Duarte", "Fisher",
]


def _name(rng: random.Random, index: int) -> str:
    first = rng.choice(FIRST_NAMES)
    last = rng.choice(LAST_NAMES)
    # The index keeps names unique enough to tell rows apart in the roster.
    return f"{first} {last}" if index % 3 else f"{first} {last[0]}. {last}"


def _tenure_weeks(rng: random.Random) -> int:
    weeks = int(rng.expovariate(1.0 / TENURE_MEAN_WEEKS)) + 1
    return min(weeks, MAX_TENURE_WEEKS)


def seed(
    n_patients: int = DEFAULT_PATIENTS,
    reset: bool = False,
    start_at: datetime = None,
    seed_value: int = RANDOM_SEED,
) -> int:
    """Create n_patients. Returns how many were inserted."""
    if not DATA_CSV.exists():
        raise SystemExit(
            f"{DATA_CSV} not found. Run: python data/generate_synthetic.py"
        )

    if reset:
        Base.metadata.drop_all(bind=engine)
    create_tables()

    now = start_at or datetime.utcnow()
    rng = random.Random(seed_value)

    frame = pd.read_csv(DATA_CSV)
    # Sample with replacement so the cohort size is independent of the CSV size.
    rows = frame.sample(n=n_patients, replace=True, random_state=seed_value)

    db = SessionLocal()
    try:
        existing = db.query(Patient).count()
        created = 0

        for offset, (_, row) in enumerate(rows.iterrows()):
            tenure = _tenure_weeks(rng)
            # Spread starts across the week so ticks are not synchronised.
            start = now - timedelta(days=tenure * 7 + rng.randint(0, 6))

            patient = Patient(
                phone_number=f"+1555{existing + offset:07d}",
                name=_name(rng, offset),
                indication=str(row["indication"]),
                insurance_type=str(row["insurance_type"]),
                income_quintile=int(row["income_quintile"]),
                baseline_bmi=float(row["baseline_bmi"]),
                enrolled_at=now,
                active=True,
                status=STATUS_ACTIVE,
                therapy_start_date=start,
                weeks_on_therapy=tenure,
                consecutive_no_reply=0,
                # Null due date means "never scheduled", so the first tick
                # picks everyone up and the cadence takes over from there.
                next_checkin_due=None,
            )
            db.add(patient)
            created += 1

        db.commit()
        return created
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a GoalPost¹ cohort.")
    parser.add_argument("--patients", type=int, default=DEFAULT_PATIENTS)
    parser.add_argument(
        "--reset", action="store_true", help="Drop every table before seeding."
    )
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    args = parser.parse_args()

    created = seed(n_patients=args.patients, reset=args.reset, seed_value=args.seed)
    print(f"Seeded {created} patients (reset={args.reset}).")


if __name__ == "__main__":
    main()
