"""Patient roster endpoints backing the care team dashboard."""

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import CheckIn, Patient
from services.risk_scorer import risk_tier_for_score

router = APIRouter(tags=["patients"])

VALID_INDICATIONS = {"AOM", "T2D"}
VALID_INSURANCE_TYPES = {"commercial", "medicaid", "medicare", "uninsured"}

# E.164: leading +, country code, up to 15 digits total.
E164_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")


class PatientCreate(BaseModel):
    name: str = Field(..., min_length=1)
    phone_number: str
    indication: str
    insurance_type: str
    income_quintile: int = Field(..., ge=1, le=5)
    baseline_bmi: float = Field(..., gt=0)


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
def list_patients(db: Session = Depends(get_db)):
    """Roster with each patient's most recent check-in flattened onto the row."""
    rows = []
    for patient in db.query(Patient).order_by(Patient.id).all():
        latest = _latest_check_in(db, patient.id)
        row = _patient_base(patient)
        row.update(
            {
                "last_reply": latest.reply if latest else None,
                "last_risk_score": latest.risk_score if latest else None,
                "last_risk_tier": (
                    risk_tier_for_score(latest.risk_score)
                    if latest and latest.risk_score is not None
                    else None
                ),
                "last_barrier_type": latest.barrier_type if latest else None,
                "last_intervention": latest.intervention_fired if latest else None,
                "last_checkin_at": _iso(latest.created_at) if latest else None,
            }
        )
        rows.append(row)
    return rows


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

    patient = Patient(
        name=payload.name.strip(),
        phone_number=phone_number,
        indication=payload.indication,
        insurance_type=payload.insurance_type,
        income_quintile=payload.income_quintile,
        baseline_bmi=payload.baseline_bmi,
        weeks_on_therapy=0,
        enrolled_at=datetime.utcnow(),
        active=True,
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
    """Full patient record including every check-in in chronological order."""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    check_ins = (
        db.query(CheckIn)
        .filter(CheckIn.patient_id == patient_id)
        .order_by(CheckIn.created_at, CheckIn.id)
        .all()
    )

    result = _patient_base(patient)
    result["check_ins"] = [_serialize_check_in(c) for c in check_ins]
    return result
