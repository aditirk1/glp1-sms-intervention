"""Patient roster endpoints backing the care team dashboard."""

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import (
    STATUS_ACTIVE,
    CheckIn,
    OutboundMessage,
    Patient,
    RiskSnapshot,
    Task,
)
from services.risk_scorer import risk_tier_for_score

router = APIRouter(tags=["patients"])

VALID_INDICATIONS = {"AOM", "T2D"}
VALID_INSURANCE_TYPES = {"commercial", "medicaid", "medicare", "uninsured"}
VALID_TIERS = {"red", "amber", "green"}
VALID_STATUSES = {"active", "paused", "discontinued"}

SORT_COLUMNS = {
    "risk": Patient.current_risk_score,
    "name": Patient.name,
    "weeks": Patient.weeks_on_therapy,
    "due": Patient.next_checkin_due,
    "silence": Patient.consecutive_no_reply,
}

# E.164: leading +, country code, up to 15 digits total.
E164_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")


class PatientCreate(BaseModel):
    name: str = Field(..., min_length=1)
    phone_number: str
    indication: str
    insurance_type: str
    income_quintile: int = Field(..., ge=1, le=5)
    baseline_bmi: float = Field(..., gt=0)
    # Optional so a patient already mid-treatment can be enrolled at their
    # real tenure rather than restarting at week 0.
    therapy_start_date: datetime | None = None


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _latest_check_in(db: Session, patient_id: int) -> CheckIn | None:
    return (
        db.query(CheckIn)
        .filter(CheckIn.patient_id == patient_id)
        .order_by(CheckIn.created_at.desc(), CheckIn.id.desc())
        .first()
    )


def _patient_base(patient: Patient) -> dict:
    return {
        "id": patient.id,
        "name": patient.name,
        "phone_number": patient.phone_number,
        "indication": patient.indication,
        "insurance_type": patient.insurance_type,
        "income_quintile": patient.income_quintile,
        "baseline_bmi": patient.baseline_bmi,
        "weeks_on_therapy": patient.weeks_on_therapy,
        "enrolled_at": _iso(patient.enrolled_at),
        "active": patient.active,
        "status": patient.status,
        "therapy_start_date": _iso(patient.therapy_start_date),
        "last_contacted_at": _iso(patient.last_contacted_at),
        "last_prompt_at": _iso(patient.last_prompt_at),
        "last_reply_at": _iso(patient.last_reply_at),
        "next_checkin_due": _iso(patient.next_checkin_due),
        "consecutive_no_reply": patient.consecutive_no_reply,
        "discontinued_at": _iso(patient.discontinued_at),
        # Denormalized on every scoring, so the roster sorts without a join.
        "risk_score": patient.current_risk_score,
        "risk_tier": patient.current_risk_tier,
        "barrier_type": patient.current_barrier_type,
    }


def _serialize_check_in(check_in: CheckIn) -> dict:
    return {
        "id": check_in.id,
        "week_number": check_in.week_number,
        "reply": check_in.reply,
        "raw_message": check_in.raw_message,
        "risk_score": check_in.risk_score,
        "risk_tier": (
            risk_tier_for_score(check_in.risk_score)
            if check_in.risk_score is not None
            else None
        ),
        "barrier_type": check_in.barrier_type,
        "intervention_fired": check_in.intervention_fired,
        "intervention_message": check_in.intervention_message,
        "created_at": _iso(check_in.created_at),
    }


@router.get("/patients")
def list_patients(
    tier: str | None = Query(None, description="red | amber | green"),
    status: str | None = Query(None, description="active | paused | discontinued"),
    barrier: str | None = Query(None),
    silent: bool = Query(False, description="Only patients with a missed check-in"),
    due: bool = Query(False, description="Only patients due for a check-in now"),
    search: str | None = Query(None),
    sort: str = Query("risk", description=" | ".join(SORT_COLUMNS)),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Filtered, paginated roster.

    Returns an envelope rather than a bare list: a thousand-patient cohort
    needs a total count to page through, and the previous shape could not
    carry one.
    """
    if tier and tier not in VALID_TIERS:
        raise HTTPException(
            status_code=400, detail=f"tier must be one of {sorted(VALID_TIERS)}"
        )
    if status and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400, detail=f"status must be one of {sorted(VALID_STATUSES)}"
        )
    if sort not in SORT_COLUMNS:
        raise HTTPException(
            status_code=400, detail=f"sort must be one of {sorted(SORT_COLUMNS)}"
        )

    query = db.query(Patient)

    if tier:
        query = query.filter(Patient.current_risk_tier == tier)
    if status:
        query = query.filter(Patient.status == status)
    if barrier:
        query = query.filter(Patient.current_barrier_type == barrier)
    if silent:
        query = query.filter(Patient.consecutive_no_reply >= 1)
    if due:
        query = query.filter(
            Patient.status == STATUS_ACTIVE,
            Patient.next_checkin_due.isnot(None),
            Patient.next_checkin_due <= datetime.utcnow(),
        )
    if search:
        query = query.filter(Patient.name.ilike(f"%{search.strip()}%"))

    total = query.count()

    column = SORT_COLUMNS[sort]
    direction = column.desc().nullslast() if order == "desc" else column.asc()
    patients = query.order_by(direction, Patient.id).limit(limit).offset(offset).all()

    rows = []
    for patient in patients:
        latest = _latest_check_in(db, patient.id)
        row = _patient_base(patient)
        row.update(
            {
                "last_reply": latest.reply if latest else None,
                "last_risk_score": patient.current_risk_score,
                "last_risk_tier": patient.current_risk_tier,
                "last_barrier_type": patient.current_barrier_type,
                "last_intervention": latest.intervention_fired if latest else None,
                "last_checkin_at": _iso(latest.created_at) if latest else None,
            }
        )
        rows.append(row)

    return {"total": total, "limit": limit, "offset": offset, "items": rows}


@router.post("/patients")
def create_patient(payload: PatientCreate, db: Session = Depends(get_db)):
    """Enroll a patient. Phone numbers must be E.164 (+1XXXXXXXXXX)."""
    if payload.indication not in VALID_INDICATIONS:
        raise HTTPException(
            status_code=400,
            detail=f"indication must be one of {sorted(VALID_INDICATIONS)}",
        )

    if payload.insurance_type not in VALID_INSURANCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"insurance_type must be one of {sorted(VALID_INSURANCE_TYPES)}",
        )

    phone_number = payload.phone_number.strip()
    if not E164_PATTERN.match(phone_number):
        raise HTTPException(
            status_code=400,
            detail="phone_number must be in E.164 format, for example +15551234567",
        )

    existing = db.query(Patient).filter(Patient.phone_number == phone_number).first()
    if existing:
        raise HTTPException(status_code=400, detail="Phone number already enrolled")

    now = datetime.utcnow()
    patient = Patient(
        name=payload.name.strip(),
        phone_number=phone_number,
        indication=payload.indication,
        insurance_type=payload.insurance_type,
        income_quintile=payload.income_quintile,
        baseline_bmi=payload.baseline_bmi,
        weeks_on_therapy=0,
        enrolled_at=now,
        active=True,
        status=STATUS_ACTIVE,
        # Tenure is derived from this from here on, so a patient who never
        # replies still ages instead of sitting at week 0 forever.
        therapy_start_date=payload.therapy_start_date or now,
        # A null due date makes the next tick pick them up immediately.
        next_checkin_due=None,
    )

    try:
        db.add(patient)
        db.commit()
        db.refresh(patient)
    except Exception as exc:
        db.rollback()
        print(f"[patients] enrollment failed: {exc}")
        raise HTTPException(status_code=400, detail="Could not enroll patient")

    return _patient_base(patient)


@router.get("/patients/{patient_id}")
def get_patient(patient_id: int, db: Session = Depends(get_db)):
    """Full patient record: replies, outbound messages, tasks and risk history."""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    check_ins = (
        db.query(CheckIn)
        .filter(CheckIn.patient_id == patient_id)
        .order_by(CheckIn.created_at, CheckIn.id)
        .all()
    )
    messages = (
        db.query(OutboundMessage)
        .filter(OutboundMessage.patient_id == patient_id)
        .order_by(OutboundMessage.sent_at, OutboundMessage.id)
        .all()
    )
    tasks = (
        db.query(Task)
        .filter(Task.patient_id == patient_id)
        .order_by(Task.created_at.desc())
        .all()
    )
    snapshots = (
        db.query(RiskSnapshot)
        .filter(RiskSnapshot.patient_id == patient_id)
        .order_by(RiskSnapshot.computed_at)
        .all()
    )

    result = _patient_base(patient)
    result["check_ins"] = [_serialize_check_in(c) for c in check_ins]
    result["outbound_messages"] = [
        {
            "id": m.id,
            "kind": m.kind,
            "body": m.body,
            "rule_id": m.rule_id,
            "sent_at": _iso(m.sent_at),
            "responded": m.responded,
        }
        for m in messages
    ]
    result["tasks"] = [
        {
            "id": t.id,
            "kind": t.kind,
            "priority": t.priority,
            "reason": t.reason,
            "status": t.status,
            "created_at": _iso(t.created_at),
            "resolved_at": _iso(t.resolved_at),
        }
        for t in tasks
    ]
    # Risk moves on silence too, so the trend is not just the reply history.
    result["risk_history"] = [
        {
            "risk_score": s.risk_score,
            "risk_tier": s.risk_tier,
            "barrier_type": s.barrier_type,
            "trigger": s.trigger,
            "week_number": s.week_number,
            "computed_at": _iso(s.computed_at),
        }
        for s in snapshots
    ]
    return result
