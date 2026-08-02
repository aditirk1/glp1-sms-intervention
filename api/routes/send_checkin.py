"""Outbound weekly check-in triggers."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import Patient
from services import sms_sender

router = APIRouter(tags=["check-ins"])


# Declared before /send-checkin/{patient_id} so "all" is not parsed as an id.
@router.post("/send-checkin/all")
def send_checkin_to_all(db: Session = Depends(get_db)):
    """Send this week's check-in prompt to every active patient."""
    patients = db.query(Patient).filter(Patient.active.is_(True)).all()

    sent: list[str] = []
    for patient in patients:
        try:
            sms_sender.send_checkin(
                patient.phone_number, patient.name, (patient.weeks_on_therapy or 0) + 1
            )
            sent.append(patient.phone_number)
        except Exception as exc:
            print(f"[send_checkin] failed for {patient.phone_number}: {exc}")

    return {"sent_count": len(sent), "messages": sent}


@router.post("/send-checkin/{patient_id}")
def send_checkin_to_patient(patient_id: int, db: Session = Depends(get_db)):
    """Send this week's check-in prompt to one patient."""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    message = sms_sender.send_checkin(
        patient.phone_number, patient.name, (patient.weeks_on_therapy or 0) + 1
    )
    return {"message_sent": message, "to": patient.phone_number}
