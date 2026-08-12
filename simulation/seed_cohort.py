"""Seed a patient cohort for the simulation.

Draws demographics from the same synthetic CSV the model trained on, then
staggers enrolled_at and therapy_start_date so the cohort spans weeks 1-52 of
treatment rather than everyone enrolling on the same day.

Run:  python -m simulation.seed_cohort --patients 1000 --reset
"""

import argparse
import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from db.database import Base, SessionLocal, create_tables, engine
from db.models import STATUS_ACTIVE, Patient
from services import risk_scorer
from services.scheduling import build_features, record_risk

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_CSV = PROJECT_ROOT / "data" / "synthetic_patients.csv"

DEFAULT_PATIENTS = 1000
RANDOM_SEED = 7

# Tenure is right-skewed the way a real enrolled panel is: a steady intake of
# new starts plus a thinning tail of long-term patients.
MAX_TENURE_WEEKS = 52
TENURE_MEAN_WEEKS = 14.0

FIRST_NAMES = [
    "Aaliyah", "Aaron", "Abigail", "Adam", "Aisha", "Alex", "Amara", "Amir",
    "Andrea", "Angela", "Anthony", "Aria", "Benjamin", "Bianca", "Brandon",
    "Brianna", "Caleb", "Camila", "Carlos", "Carmen", "Chloe", "Christopher",
    "Claire", "Daniel", "Danielle", "David", "Derek", "Diana", "Diego",
    "Dorothy", "Elena", "Elias", "Emily", "Emma", "Eric", "Esther", "Ethan",
    "Eva", "Fatima", "Felix", "Francesca", "Gabriel", "Gabriela", "Grace",
    "Hannah", "Harper", "Hassan", "Helena", "Henry", "Hunter", "Isabel",
    "Isaiah", "Ivy", "Jack", "Jacob", "Jade", "James", "Jasmine", "Jason",
    "Jayden", "Jennifer", "Jessica", "Joanna", "Jordan", "Joseph", "Joshua",
    "Julia", "Julian", "Kai", "Karen", "Katherine", "Kayla", "Kevin", "Kofi",
    "Laila", "Laura", "Leah", "Leo", "Lila", "Linda", "Lucas", "Luis",
    "Lydia", "Malik", "Marcus", "Maria", "Mason", "Matthew", "Maya", "Megan",
    "Michael", "Michelle", "Miguel", "Monica", "Nadia", "Naomi", "Natalia",
    "Nathan", "Nicole", "Nina", "Noah", "Noelle", "Omar", "Oscar", "Owen",
    "Patricia", "Patrick", "Peter", "Phoebe", "Priya", "Rachel", "Rafael",
    "Rebecca", "Riley", "Robert", "Rosa", "Ryan", "Sabrina", "Samantha",
    "Samuel", "Sara", "Sean", "Sebastian", "Sofia", "Solomon", "Stephanie",
    "Steven", "Tanya", "Taylor", "Thomas", "Tiffany", "Tyler", "Valentina",
    "Victor", "Victoria", "Vincent", "Violet", "William", "Xavier", "Yara",
    "Yasmin", "Zachary", "Zara", "Zoe",
]

LAST_NAMES = [
    "Adams", "Ahmed", "Ali", "Allen", "Alvarez", "Anderson", "Bailey",
    "Baker", "Barnes", "Bell", "Bennett", "Brooks", "Brown", "Campbell",
    "Carter", "Castillo", "Chavez", "Chen", "Clark", "Cole", "Collins",
    "Cook", "Cooper", "Cox", "Cruz", "Davis", "Dawson", "Diaz", "Dixon",
    "Duarte", "Edwards", "Ellis", "Evans", "Fisher", "Flores", "Foster",
    "Garcia", "Gonzalez", "Gray", "Green", "Gutierrez", "Hall", "Harris",
    "Hayes", "Hernandez", "Hill", "Howard", "Hughes", "Ibrahim", "Jackson",
    "James", "Jenkins", "Jensen", "Johnson", "Jones", "Jordan", "Kelly",
    "Khan", "Kim", "King", "Lee", "Lewis", "Li", "Lopez", "Martin",
    "Martinez", "Mensah", "Miller", "Mitchell", "Moore", "Morales", "Morgan",
    "Morris", "Murphy", "Myers", "Nelson", "Nguyen", "Novak", "Okonkwo",
    "Osei", "Owens", "Parker", "Patel", "Perez", "Perry", "Peterson",
    "Phillips", "Powell", "Price", "Quinn", "Ramirez", "Reed", "Reyes",
    "Richardson", "Rivera", "Roberts", "Robinson", "Rodriguez", "Rogers",
    "Ross", "Russell", "Sanchez", "Sanders", "Scott", "Shaw", "Silva",
    "Smith", "Stewart", "Sullivan", "Taylor", "Thomas", "Thompson", "Torres",
    "Tran", "Turner", "Ueda", "Vargas", "Walker", "Ward", "Watson", "White",
    "Williams", "Wilson", "Wood", "Wright", "Xu", "Young", "Zhang",
]


def _name(rng: random.Random, index: int, used: set[str]) -> str:
    """Pick a unique display name from the expanded pools."""
    for _ in range(40):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        # Mix plain and middle-initial forms so the roster does not look cloned.
        if index % 5 == 0:
            candidate = f"{first} {last[0]}. {last}"
        elif index % 7 == 0:
            candidate = f"{first} {chr(65 + (index % 26))}. {last}"
        else:
            candidate = f"{first} {last}"
        if candidate not in used:
            used.add(candidate)
            return candidate
    # Extremely unlikely fallback if the random draws collide repeatedly.
    fallback = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)} ({index})"
    used.add(fallback)
    return fallback


def _tenure_weeks(rng: random.Random) -> int:
    weeks = int(rng.expovariate(1.0 / TENURE_MEAN_WEEKS)) + 1
    return min(weeks, MAX_TENURE_WEEKS)


def _score_cohort(db, patients: list[Patient], now: datetime) -> None:
    """Baseline risk from demographics + tenure so the dashboard is not blank."""
    if not patients:
        return
    features = [
        build_features(patient, patient.weeks_on_therapy or 0, None, 0, 0)
        for patient in patients
    ]
    for patient, scored in zip(patients, risk_scorer.score_batch(features)):
        record_risk(db, patient, scored, trigger="scheduled", now=now)


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
        used_names: set[str] = set()
        batch: list[Patient] = []

        for offset, (_, row) in enumerate(rows.iterrows()):
            indication = str(row["indication"])
            if offset == 0:
                # Demo anchor — reset to a fresh enroll after bootstrap_live.
                name = "Maria Alvarez"
                used_names.add(name)
                tenure = 14
                start = now - timedelta(days=tenure * 7 + 2)
            else:
                name = _name(rng, offset, used_names)
                tenure = _tenure_weeks(rng)
                # Spread starts across the week so ticks are not synchronised.
                start = now - timedelta(days=tenure * 7 + rng.randint(0, 6))

            # Retention is measured from enrollment; stagger enroll dates like
            # therapy starts so the live curve has width on day one.
            enrolled_at = start - timedelta(days=rng.randint(0, 2))

            patient = Patient(
                phone_number=f"+1555{existing + offset:07d}",
                name=name,
                indication=indication,
                insurance_type=str(row["insurance_type"]),
                income_quintile=int(row["income_quintile"]),
                baseline_bmi=float(row["baseline_bmi"]),
                enrolled_at=enrolled_at,
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
            batch.append(patient)
            created += 1

        db.flush()
        _score_cohort(db, batch, now)

        db.commit()
        return created
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a GoaLPost¹ cohort.")
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
