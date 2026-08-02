"""Inbound SMS webhook: the full check-in to intervention pipeline.

A patient reply arrives as form data, gets scored for dropout risk, attributed
to a barrier type via SHAP, and routed to the matching intervention. Every
path returns parseable JSON so the dashboard simulator never sees a raw error.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Form
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import CheckIn, Patient
from services import plateau_messenger, risk_scorer, sms_sender

router = APIRouter(tags=["sms"])

PLATEAU_RISK_THRESHOLD = 0.45
CONSECUTIVE_LOOKBACK = 4

SIDE_EFFECT_MESSAGE = (
    "Thanks for letting us know. Side effects like nausea often improve in "
    "weeks 4-8 as your body adjusts. Try eating a small meal before your "
    "injection, stay well hydrated, and avoid fatty foods. Your care team has "
    "been notified and can help if symptoms persist."
)

POSITIVE_MESSAGE = (
    "Great to hear. Keep going. Your care team can see your progress and is "
    "here if anything changes."
)


def _count_consecutive_reply_3(db: Session, patient_id: int, current_reply: int) -> int:
    """Weeks in a row ending now that the patient said 'not seeing results'."""
    recent = (
        db.query(CheckIn)
        .filter(CheckIn.patient_id == patient_id)
        .order_by(CheckIn.created_at.desc(), CheckIn.id.desc())
        .limit(CONSECUTIVE_LOOKBACK)
        .all()
    )

    streak = 0
    for check_in in recent:
        if check_in.reply == 3:
            streak += 1
        else:
            break

    if current_reply == 3:
        streak += 1
    return streak


def _weight_change_slope_proxy(reply: int) -> float:
    """Stand-in for a real weight trend.

    The demo has no scale integration, so the reply itself proxies the slope:
    reply 1 means still losing, reply 3 means the scale has stalled, reply 2 is
    treated as roughly flat. Replace this with measured weights in production.
    """
    if reply == 1:
        return -0.05
    if reply == 3:
        return 0.1
    return -0.02


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

        if first_char not in ("1", "2", "3"):
            return JSONResponse(
                status_code=200,
                content={
                    "error": "Invalid reply",
                    "message": "Please reply 1, 2, or 3.",
                },
            )
        reply_int = int(first_char)

        consecutive_reply_3 = _count_consecutive_reply_3(db, patient.id, reply_int)

        patient.weeks_on_therapy = (patient.weeks_on_therapy or 0) + 1

        check_in = CheckIn(
            patient_id=patient.id,
            week_number=patient.weeks_on_therapy,
            reply=reply_int,
            raw_message=body,
            created_at=datetime.utcnow(),
        )
        db.add(check_in)

        feature_dict = {
            "weeks_on_therapy": patient.weeks_on_therapy,
            "weight_change_slope": _weight_change_slope_proxy(reply_int),
            "gi_event_flag": 1 if reply_int == 2 else 0,
            "income_quintile": patient.income_quintile,
            "prior_pa_denial": 0,
            "baseline_bmi": patient.baseline_bmi,
            "consecutive_reply_3": consecutive_reply_3,
            "insurance_type": patient.insurance_type,
            "indication": patient.indication,
        }

        scored = risk_scorer.score_patient(feature_dict)
        risk_score = float(scored["risk_score"])
        risk_tier = scored["risk_tier"]
        barrier_type = scored["barrier_type"]

        check_in.risk_score = risk_score
        check_in.barrier_type = barrier_type

        if reply_int == 3 and risk_score >= PLATEAU_RISK_THRESHOLD:
            message = plateau_messenger.generate_plateau_message(
                patient_dict=feature_dict,
                weeks_on_therapy=patient.weeks_on_therapy,
                consecutive_reply_3=consecutive_reply_3,
            )
            sms_sender.send_sms(patient.phone_number, message)
            intervention_fired = "plateau_branch"
        elif reply_int == 2:
            message = SIDE_EFFECT_MESSAGE
            sms_sender.send_sms(patient.phone_number, message)
            intervention_fired = "side_effect_branch"
        elif reply_int == 1:
            message = POSITIVE_MESSAGE
            sms_sender.send_sms(patient.phone_number, message)
            intervention_fired = "checkin_only"
        else:
            message = ""
            intervention_fired = "none"

        check_in.intervention_fired = intervention_fired
        check_in.intervention_message = message

        db.commit()

        return {
            "patient_name": patient.name,
            "risk_score": round(risk_score, 3),
            "risk_tier": risk_tier,
            "barrier_type": barrier_type,
            "intervention_fired": intervention_fired,
            "intervention_message": message,
            "consecutive_reply_3": consecutive_reply_3,
            "top_shap_feature": scored.get("top_shap_feature"),
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
