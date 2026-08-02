"""The care team work queue.

Tasks are the system's only request for human time, so they are ranked by
priority first and by the patient's current risk second: two nurse calls are
not equally urgent if one patient is at 0.81 and the other at 0.52.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import (
    TASK_ACKNOWLEDGED,
    TASK_OPEN,
    TASK_RESOLVED,
    Patient,
    Task,
)

router = APIRouter(tags=["tasks"])

VALID_STATUSES = {TASK_OPEN, TASK_ACKNOWLEDGED, TASK_RESOLVED}


class TaskAction(BaseModel):
    by: str | None = None


def _serialize(task: Task, patient: Patient) -> dict:
    return {
        "id": task.id,
        "kind": task.kind,
        "priority": task.priority,
        "reason": task.reason,
        "rule_id": task.rule_id,
        "status": task.status,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "resolved_at": task.resolved_at.isoformat() if task.resolved_at else None,
        "resolved_by": task.resolved_by,
        "patient_id": patient.id,
        "patient_name": patient.name,
        "phone_number": patient.phone_number,
        "weeks_on_therapy": patient.weeks_on_therapy,
        "risk_score": patient.current_risk_score,
        "risk_tier": patient.current_risk_tier,
        "barrier_type": patient.current_barrier_type,
        "consecutive_no_reply": patient.consecutive_no_reply,
        "last_reply_at": (
            patient.last_reply_at.isoformat() if patient.last_reply_at else None
        ),
    }


@router.get("/tasks")
def list_tasks(
    status: str = Query("open"),
    kind: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Ranked work queue. status=all returns every task."""
    query = db.query(Task, Patient).join(Patient, Task.patient_id == Patient.id)

    if status != "all":
        if status not in VALID_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"status must be 'all' or one of {sorted(VALID_STATUSES)}",
            )
        query = query.filter(Task.status == status)

    if kind:
        query = query.filter(Task.kind == kind)

    total = query.count()

    rows = (
        query.order_by(
            Task.priority.desc(),
            Patient.current_risk_score.desc().nullslast(),
            Task.created_at,
        )
        .limit(limit)
        .offset(offset)
        .all()
    )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [_serialize(task, patient) for task, patient in rows],
    }


def _transition(db: Session, task_id: int, status: str, by: str | None) -> dict:
    task = db.query(Task).filter(Task.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    task.status = status
    if status == TASK_RESOLVED:
        task.resolved_at = datetime.utcnow()
        task.resolved_by = by or "care team"

    patient = db.query(Patient).filter(Patient.id == task.patient_id).first()
    db.commit()
    return _serialize(task, patient)


@router.post("/tasks/{task_id}/ack")
def acknowledge_task(task_id: int, payload: TaskAction | None = None, db: Session = Depends(get_db)):
    """Claim a task so two people do not call the same patient."""
    return _transition(db, task_id, TASK_ACKNOWLEDGED, payload.by if payload else None)


@router.post("/tasks/{task_id}/resolve")
def resolve_task(task_id: int, payload: TaskAction | None = None, db: Session = Depends(get_db)):
    return _transition(db, task_id, TASK_RESOLVED, payload.by if payload else None)
