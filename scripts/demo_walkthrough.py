"""Reset a small demo cohort and walk the backend pipeline once.

Use this before a live walkthrough so the story is clean:
  tick → 1/2/3 prompt → reply 3 → plateau SMS → reply 1 → ack (no nurse call)

Run with the API stopped or against a throwaway DB:

  ENABLE_SCHEDULER=false python -m scripts.demo_walkthrough
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

# Keep the walkthrough off the background scheduler and on a fresh DB.
os.environ.setdefault("ENABLE_SCHEDULER", "false")
os.environ["DATABASE_URL"] = os.environ.get(
    "DEMO_DATABASE_URL", "sqlite:///./demo_walkthrough.db"
)

from db.database import Base, SessionLocal, create_tables, engine
from db.models import STATUS_ACTIVE, Patient
from services import plateau_messenger, scheduling, sms_sender


def main() -> None:
    sms_sender.set_quiet(False)
    plateau_messenger.set_offline(True)

    Base.metadata.drop_all(bind=engine)
    create_tables()
    db = SessionLocal()
    now = datetime.now().replace(hour=11, minute=0, second=0, microsecond=0)

    try:
        patient = Patient(
            phone_number="+15559990001",
            name="Demo Patient",
            indication="AOM",
            insurance_type="commercial",
            income_quintile=3,
            baseline_bmi=36.0,
            enrolled_at=now,
            active=True,
            status=STATUS_ACTIVE,
            therapy_start_date=now - timedelta(days=21),
            weeks_on_therapy=3,
            next_checkin_due=None,
        )
        db.add(patient)
        db.commit()
        db.refresh(patient)

        print("\n1) Scheduler tick (should send the 1/2/3 check-in prompt)")
        tick = scheduling.run_due_checkins(now=now, db=db, arm="intervention")
        db.commit()
        print("   ", tick.as_dict())

        db.refresh(patient)
        print("   next due:", patient.next_checkin_due)
        print("   risk:", patient.current_risk_score, patient.current_risk_tier)

        print("\n2) Reply 3 — not seeing results (expect plateau SMS)")
        r3 = scheduling.process_reply(
            db, patient, reply=3, raw_message="3", now=now + timedelta(hours=1)
        )
        db.commit()
        print(
            f"   risk={r3.risk_score:.3f} tier={r3.risk_tier} barrier={r3.barrier_type}"
        )
        print(f"   fired={r3.intervention_fired}")
        print(f"   msg={r3.intervention_message[:80]}...")
        print(f"   tasks={r3.tasks_created} suppressed={r3.suppressed}")

        print("\n3) Reply 1 — going well (expect ack SMS, no nurse_call)")
        r1 = scheduling.process_reply(
            db, patient, reply=1, raw_message="1", now=now + timedelta(hours=2)
        )
        db.commit()
        print(
            f"   risk={r1.risk_score:.3f} tier={r1.risk_tier} barrier={r1.barrier_type}"
        )
        print(f"   fired={r1.intervention_fired}")
        print(f"   msg={r1.intervention_message[:80]}...")
        print(f"   tasks={r1.tasks_created} suppressed={r1.suppressed}")

        ok = (
            "scheduled_checkin" in (tick.by_rule or {})
            and "plateau" in (r3.intervention_fired or "")
            and "doing_well" in (r1.intervention_fired or "")
            and "nurse_call" not in (r1.tasks_created or [])
        )
        print("\nWalkthrough", "PASSED" if ok else "FAILED")
        if not ok:
            raise SystemExit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
