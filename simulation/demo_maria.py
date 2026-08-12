"""Reset Maria Alvarez to a fresh enroll for the live demo.

Wipes her simulated SMS history and sets enrolled_at / therapy_start_date
to today so the dashboard shows week 0 and the next scheduler tick picks
her up like a new patient.

    python -m simulation.demo_maria
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = "sqlite:///./GoaLPost¹.db"

MARIA_NAME = "Maria Alvarez"


def pin_maria_as_new_enroll(db, now: datetime | None = None):
    """Clear Maria's history and position her as enrolling today."""
    from db.models import (
        STATUS_ACTIVE,
        CheckIn,
        OutboundMessage,
        Patient,
        RiskSnapshot,
        Task,
    )
    from services import risk_scorer
    from services.scheduling import build_features, record_risk

    now = now or datetime.now()
    maria = db.query(Patient).filter(Patient.name == MARIA_NAME).one()

    for model in (CheckIn, OutboundMessage, Task, RiskSnapshot):
        db.query(model).filter(model.patient_id == maria.id).delete()

    enrolled = now - timedelta(hours=2)
    maria.enrolled_at = enrolled
    maria.therapy_start_date = enrolled
    maria.weeks_on_therapy = 0
    maria.active = True
    maria.status = STATUS_ACTIVE
    maria.discontinued_at = None
    maria.last_contacted_at = None
    maria.last_prompt_at = None
    maria.last_reply_at = None
    maria.next_checkin_due = None
    maria.consecutive_no_reply = 0

    scored = risk_scorer.score_patient(build_features(maria, 0, None, 0, 0))
    record_risk(db, maria, scored, trigger="scheduled", now=now)
    db.commit()
    db.refresh(maria)
    return maria


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    os.environ.setdefault("DATABASE_URL", os.getenv("DATABASE_URL", DEFAULT_DB))

    from db.database import SessionLocal

    db = SessionLocal()
    try:
        maria = pin_maria_as_new_enroll(db)
        print(f"Maria reset for demo:")
        print(f"  id              {maria.id}")
        print(f"  enrolled_at     {maria.enrolled_at.isoformat()}")
        print(f"  weeks_on_therapy {maria.weeks_on_therapy}")
        print(f"  risk            {maria.current_risk_score:.3f} ({maria.current_risk_tier})")
        print(f"  next_checkin_due {maria.next_checkin_due}")
        print()
        print("Run scheduler tick on Operations to send her first check-in.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
