"""Fast-forward the live dashboard database to a mid-simulation state.

Seeds patients, then runs the real scheduler day-by-day for N weeks with
simulated replies. Virtual time ends near wall-clock now so Overview retention
and tenure line up with today.

    python -m simulation.bootstrap_live --weeks 13

Uses DATABASE_URL from .env (default: sqlite:///./GoaLPost¹.db). Does not
overwrite simulation/results/*.json — Outcomes keeps the 26-week experiment.
"""

from __future__ import annotations

import argparse
import os
from argparse import Namespace
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_PATIENTS = 1000
DEFAULT_WEEKS = 13
DEFAULT_SEED = 11
DEFAULT_DB = "sqlite:///./GoaLPost¹.db"


def _sim_origin(weeks: int) -> datetime:
    """First simulation day, chosen so the last day lands near now."""
    from simulation.run_simulation import REPLY_HOUR, TICK_HOUR

    end = datetime.now().replace(hour=REPLY_HOUR, minute=0, second=0, microsecond=0)
    origin = end - timedelta(days=weeks * 7 - 1)
    return origin.replace(hour=TICK_HOUR, minute=0, second=0, microsecond=0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bootstrap the live dashboard DB to a mid-simulation state."
    )
    parser.add_argument(
        "--weeks",
        type=int,
        default=DEFAULT_WEEKS,
        help="Virtual weeks to fast-forward (default: 13).",
    )
    parser.add_argument("--patients", type=int, default=DEFAULT_PATIENTS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--db",
        default=None,
        help="SQLite URL. Defaults to DATABASE_URL from .env.",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")

    args = parse_args()
    db_url = args.db or os.getenv("DATABASE_URL", DEFAULT_DB)
    os.environ["DATABASE_URL"] = db_url

    origin = _sim_origin(args.weeks)

    from simulation.run_simulation import run

    sim_args = Namespace(
        arm="intervention",
        patients=args.patients,
        weeks=args.weeks,
        seed=args.seed,
        db=db_url,
        quiet=True,
    )

    print(f"Bootstrapping live panel → {db_url}")
    print(f"  virtual origin  {origin.isoformat()}")
    print(f"  fast-forward    {args.weeks} weeks · {args.patients} patients")
    print(f"  arm             intervention (Outcomes JSON untouched)")
    print()

    summary = run(sim_args, origin=origin, write_json=False)

    from db.database import SessionLocal
    from simulation.demo_maria import pin_maria_as_new_enroll

    db = SessionLocal()
    try:
        maria = pin_maria_as_new_enroll(db)
        print(f"Maria Alvarez → fresh enroll (week {maria.weeks_on_therapy})")
    finally:
        db.close()

    totals = summary["totals"]
    guards = summary["guardrails"]
    print()
    print("=== live panel ready ===")
    print(f"  program retention     {totals['final_retention']:.1%}")
    print(f"  discontinued          {totals['discontinued']}")
    print(f"  messages / patient    {totals['messages_per_patient']}")
    print(f"  response rate         {totals['response_rate']:.1%}")
    print(f"  open tasks            {totals['tasks_still_open']}")
    print(f"  check-ins             {totals['check_ins']}")
    print(f"  runtime               {summary['runtime_seconds']}s")
    print()
    print("Refresh the dashboard. Continue with Operations → scheduler tick.")


if __name__ == "__main__":
    main()
