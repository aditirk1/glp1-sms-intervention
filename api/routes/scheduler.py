"""Scheduler control surface.

POST /scheduler/tick is the single entry point for advancing the clock. The
in-process APScheduler job calls it, and so can an external cron, which is the
reliable path on hosts that sleep idle instances.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import Patient, STATUS_ACTIVE
from services import scheduling

router = APIRouter(tags=["scheduler"])


@router.post("/scheduler/tick")
def scheduler_tick(
    arm: str = Query("intervention", pattern="^(intervention|control)$"),
    db: Session = Depends(get_db),
):
    """Run one scheduling pass over every patient who is due."""
    return scheduling.tick(db, now=datetime.now(), arm=arm)


@router.get("/scheduler/status")
def scheduler_status(db: Session = Depends(get_db)):
    """What the next tick would pick up, without sending anything."""
    now = datetime.now()
    due = scheduling.due_patients(db, now)

    next_due = (
        db.query(Patient.next_checkin_due)
        .filter(
            Patient.status == STATUS_ACTIVE,
            Patient.next_checkin_due.isnot(None),
            Patient.next_checkin_due > now,
        )
        .order_by(Patient.next_checkin_due)
        .first()
    )

    return {
        "now": now.isoformat(),
        "due_now": len(due),
        "next_due_at": next_due[0].isoformat() if next_due else None,
        "cadence_days": scheduling.CADENCE_DAYS,
        "send_window": {
            "start_hour": scheduling.rules.SEND_WINDOW_START_HOUR,
            "end_hour": scheduling.rules.SEND_WINDOW_END_HOUR,
        },
        "max_messages_per_week": scheduling.rules.MAX_MESSAGES_PER_WEEK,
    }
