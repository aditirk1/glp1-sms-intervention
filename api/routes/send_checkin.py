"""Manual check-in override.

Routine check-ins are the scheduler's job: POST /scheduler/tick picks whoever
is due by tier. This endpoint stays as the escape hatch for a care team member
who wants to reach one patient now, and it goes through the same guardrails, so
a manual prompt still counts against the weekly cap and still lands inside the
send window.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import KIND_CHECKIN_PROMPT, Patient
from services import rules, scheduling

router = APIRouter(tags=["check-ins"])

MANUAL_RULE_ID = "manual_checkin"


@router.post("/send-checkin/{patient_id}")
def send_checkin_to_patient(patient_id: int, db: Session = Depends(get_db)):
    """Send this week's prompt to one patient, guardrails included."""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    now = datetime.now()
    weeks = scheduling.refresh_tenure(patient, now)

    ctx = rules.RuleContext(
        patient=patient,
        now=now,
        risk_score=patient.current_risk_score or 0.0,
        risk_tier=patient.current_risk_tier or "amber",
        barrier_type=patient.current_barrier_type or "plateau",
        weeks_on_therapy=weeks,
        consecutive_no_reply=patient.consecutive_no_reply or 0,
    )
    action = rules.Action(
        rule_id=MANUAL_RULE_ID,
        kind="sms",
        priority=1,
        message_kind=KIND_CHECKIN_PROMPT,
        body=rules.checkin_body(ctx),
    )

    try:
        result = rules.apply_actions(db, ctx, [action])
        scheduling.schedule_next(patient, now, patient.current_risk_tier)
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"[send_checkin] manual send failed: {exc}")
        raise HTTPException(status_code=500, detail="Could not send check-in")

    if result.sent_body is None:
        reason = result.suppressed[0][1] if result.suppressed else "suppressed"
        return {
            "sent": False,
            "reason": reason,
            "to": patient.phone_number,
            "next_checkin_due": (
                patient.next_checkin_due.isoformat()
                if patient.next_checkin_due
                else None
            ),
        }

    return {
        "sent": True,
        "message_sent": result.sent_body,
        "to": patient.phone_number,
        "next_checkin_due": (
            patient.next_checkin_due.isoformat() if patient.next_checkin_due else None
        ),
    }
