"""Inbound SMS webhook.

A patient reply arrives as Twilio-style form data and is handed straight to
services.scheduling.process_reply, which is the same function the simulator
calls. The route itself decides nothing: no risk logic, no intervention
branching, no cadence. That all lives in the scheduler and the rules engine so
there is exactly one copy of the policy.

Every path returns parseable JSON so the dashboard simulator never sees a raw
error.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Form
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import Patient
from services import scheduling

router = APIRouter(tags=["sms"])

VALID_REPLIES = ("1", "2", "3")


@router.post("/webhook/sms")
def receive_sms(
    From: str = Form(...),
    Body: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        body = (Body or "").strip()
        first_char = body[:1]

        patient = db.query(Patient).filter(Patient.phone_number == From).first()
        if patient is None:
            return JSONResponse(
                status_code=200,
                content={
                    "error": "Patient not enrolled",
                    "message": "Contact your care team to enroll.",
                },
            )

        if first_char not in VALID_REPLIES:
            return JSONResponse(
                status_code=200,
                content={
                    "error": "Invalid reply",
                    "message": "Please reply 1, 2, or 3.",
                },
            )

        result = scheduling.process_reply(
            db,
            patient,
            reply=int(first_char),
            raw_message=body,
            now=datetime.now(),
        )
        db.commit()

        return {
            "patient_name": patient.name,
            "risk_score": round(result.risk_score, 3),
            "risk_tier": result.risk_tier,
            "barrier_type": result.barrier_type,
            "intervention_fired": result.intervention_fired,
            "intervention_message": result.intervention_message,
            "consecutive_reply_3": result.consecutive_reply_3,
            "top_shap_feature": result.top_shap_feature,
            "tasks_created": result.tasks_created,
            "suppressed": [
                {"rule": rule, "reason": reason} for rule, reason in result.suppressed
            ],
            "next_checkin_due": (
                patient.next_checkin_due.isoformat()
                if patient.next_checkin_due
                else None
            ),
        }
    except Exception as exc:
        db.rollback()
        print(f"[sms_webhook] pipeline failed: {exc}")
        return JSONResponse(
            status_code=200,
            content={
                "error": "Pipeline error",
                "message": f"Could not process this reply: {exc}",
            },
        )
