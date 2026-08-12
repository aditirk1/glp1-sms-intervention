"""Cohort-level metrics and the retention curve.

Retention is measured from enrollment rather than from therapy start. Patients
join GoaLPost¹ at different points in their treatment, so weeks-since-enrolled
is the only axis on which every patient is comparable and on which the two
simulation arms line up.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import (
    PROMPT_KINDS,
    STATUS_ACTIVE,
    STATUS_DISCONTINUED,
    CheckIn,
    OutboundMessage,
    Patient,
    Task,
    TASK_OPEN,
)

router = APIRouter(tags=["cohort"])

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = PROJECT_ROOT / "simulation" / "results"

MAX_CURVE_WEEKS = 78

TENURE_BUCKETS = (
    ("0–12 wks since enroll", 0, 12),
    ("13–26 wks", 13, 26),
    ("27–39 wks", 27, 39),
    ("40+ wks", 40, 9999),
)


def _weeks_since_enrollment(patient: Patient, now: datetime) -> int | None:
    if patient.enrolled_at is None:
        return None
    return max(0, (now - patient.enrolled_at).days // 7)


def _retention_by_tenure(patients: list, now: datetime) -> list:
    """Share still active within each enrollment-age bucket.

    Every patient sits in exactly one bucket, so these bars sum to the cohort
    and align with the headline retention KPI — unlike the Kaplan–Meier curve.
    """
    rows = []
    for label, low, high in TENURE_BUCKETS:
        group = [
            p
            for p in patients
            if (weeks := _weeks_since_enrollment(p, now)) is not None
            and low <= weeks <= high
        ]
        if not group:
            continue
        active = sum(1 for p in group if p.status == STATUS_ACTIVE)
        total = len(group)
        rows.append(
            {
                "bucket": label,
                "total": total,
                "active": active,
                "retention": round(active / total, 4),
            }
        )
    return rows


def _retention_curve(patients: list, now: datetime) -> list:
    """Fraction of the cohort still active at each week since enrollment.

    Patients only count toward a week they have actually lived through, so a
    patient enrolled three weeks ago does not drag down week 20.
    """
    if not patients:
        return []

    observed = []
    for patient in patients:
        if patient.enrolled_at is None:
            continue
        follow_up = max(0, (now - patient.enrolled_at).days // 7)
        event_week = None
        if patient.discontinued_at is not None:
            event_week = max(0, (patient.discontinued_at - patient.enrolled_at).days // 7)
        observed.append((follow_up, event_week))

    if not observed:
        return []

    horizon = min(max(f for f, _ in observed), MAX_CURVE_WEEKS)

    curve = []
    for week in range(horizon + 1):
        at_risk = 0
        retained = 0
        for follow_up, event_week in observed:
            # Only patients whose window reaches this week, or who left before it.
            if follow_up < week and event_week is None:
                continue
            at_risk += 1
            if event_week is None or event_week > week:
                retained += 1
        if at_risk == 0:
            continue
        curve.append(
            {
                "week": week,
                "at_risk": at_risk,
                "retained": retained,
                "retention": round(retained / at_risk, 4),
            }
        )
    return curve


@router.get("/cohort/metrics")
def cohort_metrics(db: Session = Depends(get_db)):
    """Everything the dashboard header and charts need, in one call."""
    now = datetime.now()
    patients = db.query(Patient).all()
    total = len(patients)

    tiers = {"red": 0, "amber": 0, "green": 0, "unscored": 0}
    statuses = {"active": 0, "paused": 0, "discontinued": 0}
    barriers: dict = {}
    silent_one = 0
    silent_two = 0
    risk_sum = 0.0
    risk_count = 0

    for patient in patients:
        tiers[patient.current_risk_tier or "unscored"] = (
            tiers.get(patient.current_risk_tier or "unscored", 0) + 1
        )
        statuses[patient.status] = statuses.get(patient.status, 0) + 1
        if patient.current_barrier_type:
            barriers[patient.current_barrier_type] = (
                barriers.get(patient.current_barrier_type, 0) + 1
            )
        streak = patient.consecutive_no_reply or 0
        if streak >= 1:
            silent_one += 1
        if streak >= 2:
            silent_two += 1
        if patient.current_risk_score is not None:
            risk_sum += patient.current_risk_score
            risk_count += 1

    week_ago = now - timedelta(days=7)
    messages_7d = (
        db.query(OutboundMessage).filter(OutboundMessage.sent_at > week_ago).count()
    )

    prompts_total = (
        db.query(OutboundMessage).filter(OutboundMessage.kind.in_(PROMPT_KINDS)).count()
    )
    prompts_answered = (
        db.query(OutboundMessage)
        .filter(
            OutboundMessage.kind.in_(PROMPT_KINDS),
            OutboundMessage.responded.is_(True),
        )
        .count()
    )

    open_tasks = db.query(Task).filter(Task.status == TASK_OPEN).count()
    tasks_by_kind = dict(
        db.query(Task.kind, func.count(Task.id))
        .filter(Task.status == TASK_OPEN)
        .group_by(Task.kind)
        .all()
    )

    due_now = (
        db.query(Patient)
        .filter(
            Patient.status == STATUS_ACTIVE,
            Patient.next_checkin_due.isnot(None),
            Patient.next_checkin_due <= now,
        )
        .count()
    )

    return {
        "generated_at": now.isoformat(),
        "total_patients": total,
        "statuses": statuses,
        "tiers": tiers,
        "barriers": barriers,
        "mean_risk_score": round(risk_sum / risk_count, 4) if risk_count else None,
        "retention": {
            "active": statuses.get(STATUS_ACTIVE, 0),
            "discontinued": statuses.get(STATUS_DISCONTINUED, 0),
            "rate": round(statuses.get(STATUS_ACTIVE, 0) / total, 4) if total else None,
            "by_tenure": _retention_by_tenure(patients, now),
            "curve": _retention_curve(patients, now),
        },
        "engagement": {
            "messages_last_7_days": messages_7d,
            "prompts_sent": prompts_total,
            "prompts_answered": prompts_answered,
            "response_rate": (
                round(prompts_answered / prompts_total, 4) if prompts_total else None
            ),
            "check_ins": db.query(CheckIn).count(),
            "silent_one_or_more": silent_one,
            "silent_two_or_more": silent_two,
        },
        "work_queue": {
            "open_tasks": open_tasks,
            "by_kind": tasks_by_kind,
        },
        "scheduler": {"due_now": due_now},
    }


@router.get("/simulation/results")
def simulation_results(
    arm: str | None = Query(None, pattern="^(control|intervention)$"),
):
    """Serve the JSON written by simulation/run_simulation.py.

    The dashboard stays HTTP-only rather than reaching into the filesystem, and
    the arm comparison lives here because a single database only ever holds one
    arm.
    """
    if not RESULTS_DIR.exists():
        return {"available": [], "results": {}}

    arms = [arm] if arm else ["control", "intervention"]
    results = {}
    for name in arms:
        path = RESULTS_DIR / f"{name}.json"
        if not path.exists():
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                results[name] = json.load(handle)
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Could not read {name} results: {exc}"
            )

    return {"available": sorted(results.keys()), "results": results}
