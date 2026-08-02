"""The clock for GoalPost¹.

Two entry points drive every contact decision in the system:

    run_due_checkins(now, db)  - the scheduler tick
    process_reply(db, ...)     - an inbound patient reply

Both assemble the same feature vector, score it, snapshot the risk, hand a
context to the rules engine and then reschedule the patient by tier. The API
calls them with a real clock and the simulator calls them with a fake one, so
the demo exercises the production path rather than a parallel copy of it.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from db.models import (
    PROMPT_KINDS,
    STATUS_ACTIVE,
    STATUS_DISCONTINUED,
    CheckIn,
    OutboundMessage,
    Patient,
    RiskSnapshot,
)
from services import risk_scorer, rules

# Days between check-ins by risk tier. Higher risk earns a tighter loop.
CADENCE_DAYS = {"red": 3, "amber": 7, "green": 14}
DEFAULT_CADENCE_DAYS = 7

# Early titration is when GI dropout clusters, so nobody waits a fortnight
# during their first month regardless of how green they look.
EARLY_TITRATION_WEEKS = 4
EARLY_TITRATION_MAX_DAYS = 7

# Sustained silence is how a patient actually leaves. Measured from their last
# reply rather than from a count of missed prompts, so the tier cadence does
# not change how quickly someone is considered lost to follow-up.
DAYS_SILENT_UNTIL_DISCONTINUED = 42

# Check-ins land mid-morning. Keeping every scheduled contact on one hour also
# makes the simulator deterministic.
SEND_HOUR = 10

REPLY_STREAK_LOOKBACK = 4
SIDE_EFFECT_LOOKBACK_DAYS = 28

# The model was trained on tenure clipped to 1-52 weeks; feeding it week 80
# would be extrapolation.
MIN_FEATURE_WEEK = 1
MAX_FEATURE_WEEK = 52


@dataclass
class ReplyResult:
    """What process_reply decided, in the shape the webhook returns."""

    patient: Patient
    reply: int
    risk_score: float
    risk_tier: str
    barrier_type: str
    top_shap_feature: Optional[str]
    consecutive_reply_3: int
    intervention_fired: str
    intervention_message: str
    tasks_created: list = field(default_factory=list)
    suppressed: list = field(default_factory=list)


@dataclass
class TickResult:
    """Aggregate outcome of one scheduler tick."""

    ran_at: datetime
    considered: int = 0
    messaged: int = 0
    tasks_created: int = 0
    missed_checkins: int = 0
    discontinued: int = 0
    suppressed: int = 0
    by_rule: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "ran_at": self.ran_at.isoformat(),
            "considered": self.considered,
            "messaged": self.messaged,
            "tasks_created": self.tasks_created,
            "missed_checkins": self.missed_checkins,
            "discontinued": self.discontinued,
            "suppressed": self.suppressed,
            "by_rule": self.by_rule,
        }


# ---------------------------------------------------------------- cadence


def cadence_days(risk_tier: Optional[str], weeks_on_therapy: int) -> int:
    """Days until the next check-in for this tier and tenure."""
    base = CADENCE_DAYS.get(risk_tier or "", DEFAULT_CADENCE_DAYS)
    if weeks_on_therapy < EARLY_TITRATION_WEEKS:
        # A cap, not a fixed interval: red patients keep their 3-day loop.
        return min(base, EARLY_TITRATION_MAX_DAYS)
    return base


def at_send_hour(moment: datetime) -> datetime:
    return moment.replace(hour=SEND_HOUR, minute=0, second=0, microsecond=0)


def schedule_next(patient: Patient, now: datetime, risk_tier: Optional[str]) -> datetime:
    """Set and return the patient's next due time."""
    days = cadence_days(risk_tier, patient.weeks_on_therapy or 0)
    patient.next_checkin_due = at_send_hour(now + timedelta(days=days))
    return patient.next_checkin_due


# ---------------------------------------------------------------- tenure


def weeks_on_therapy_for(patient: Patient, now: datetime) -> int:
    """Calendar tenure in whole weeks.

    Derived rather than incremented: the old counter only moved when a reply
    arrived, which froze silent patients at week 0 exactly when their tenure
    mattered most.
    """
    start = patient.therapy_start_date or patient.enrolled_at
    if start is None:
        return patient.weeks_on_therapy or 0
    return max(0, (now - start).days // 7)


def refresh_tenure(patient: Patient, now: datetime) -> int:
    patient.weeks_on_therapy = weeks_on_therapy_for(patient, now)
    return patient.weeks_on_therapy


# ---------------------------------------------------------------- history


def latest_check_in(db: Session, patient_id: int) -> Optional[CheckIn]:
    return (
        db.query(CheckIn)
        .filter(CheckIn.patient_id == patient_id)
        .order_by(CheckIn.created_at.desc(), CheckIn.id.desc())
        .first()
    )


def count_consecutive_reply_3(
    db: Session, patient_id: int, current_reply: Optional[int] = None
) -> int:
    """Check-ins in a row, ending now, where the patient said 'no results'."""
    recent = (
        db.query(CheckIn)
        .filter(CheckIn.patient_id == patient_id)
        .order_by(CheckIn.created_at.desc(), CheckIn.id.desc())
        .limit(REPLY_STREAK_LOOKBACK)
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


def count_recent_side_effect_replies(
    db: Session, patient_id: int, now: datetime, current_reply: Optional[int] = None
) -> int:
    prior = (
        db.query(CheckIn)
        .filter(
            CheckIn.patient_id == patient_id,
            CheckIn.reply == 2,
            CheckIn.created_at > now - timedelta(days=SIDE_EFFECT_LOOKBACK_DAYS),
        )
        .count()
    )
    return prior + (1 if current_reply == 2 else 0)


def _mark_prompt_answered(db: Session, patient_id: int, now: datetime) -> None:
    """Flag the outstanding prompt as responded so response rate is measurable."""
    outstanding = (
        db.query(OutboundMessage)
        .filter(
            OutboundMessage.patient_id == patient_id,
            OutboundMessage.kind.in_(PROMPT_KINDS),
            OutboundMessage.responded.is_(False),
            OutboundMessage.sent_at <= now,
        )
        .order_by(OutboundMessage.sent_at.desc(), OutboundMessage.id.desc())
        .first()
    )
    if outstanding is not None:
        outstanding.responded = True


# ---------------------------------------------------------------- features


def weight_change_slope_proxy(reply: Optional[int]) -> float:
    """Stand-in for a real weight trend.

    The demo has no scale integration, so the reply proxies the slope: 1 means
    still losing, 3 means the scale has stalled, 2 is roughly flat. A patient
    who has never replied is treated as flat. Replace with measured weights in
    production.
    """
    if reply == 1:
        return -0.05
    if reply == 3:
        return 0.1
    if reply == 2:
        return -0.02
    return -0.02


def build_features(
    patient: Patient,
    weeks_on_therapy: int,
    reply: Optional[int],
    consecutive_reply_3: int,
    consecutive_no_reply: int,
    gi_recent: bool = False,
) -> dict:
    """The 9 raw fields the scorer one-hot encodes into the model's columns."""
    return {
        "weeks_on_therapy": min(
            max(weeks_on_therapy, MIN_FEATURE_WEEK), MAX_FEATURE_WEEK
        ),
        "weight_change_slope": weight_change_slope_proxy(reply),
        "gi_event_flag": 1 if (reply == 2 or gi_recent) else 0,
        "income_quintile": patient.income_quintile,
        "prior_pa_denial": 0,
        "baseline_bmi": patient.baseline_bmi,
        "consecutive_reply_3": consecutive_reply_3,
        "consecutive_no_reply": consecutive_no_reply,
        "insurance_type": patient.insurance_type,
        "indication": patient.indication,
    }


def record_risk(
    db: Session,
    patient: Patient,
    scored: dict,
    trigger: str,
    now: datetime,
) -> str:
    """Persist a snapshot and denormalize the result onto the patient row.

    Returns the tier the patient held *before* this scoring, which is what the
    sustained-red rule compares against.
    """
    previous_tier = patient.current_risk_tier

    db.add(
        RiskSnapshot(
            patient_id=patient.id,
            risk_score=float(scored["risk_score"]),
            risk_tier=scored["risk_tier"],
            barrier_type=scored["barrier_type"],
            trigger=trigger,
            week_number=patient.weeks_on_therapy,
            computed_at=now,
        )
    )

    patient.current_risk_score = float(scored["risk_score"])
    patient.current_risk_tier = scored["risk_tier"]
    patient.current_barrier_type = scored["barrier_type"]
    return previous_tier


def _record_outcome(result_bucket: TickResult, applied) -> None:
    if applied.sent_rule_id:
        result_bucket.messaged += 1
        key = applied.sent_rule_id
        result_bucket.by_rule[key] = result_bucket.by_rule.get(key, 0) + 1
    result_bucket.tasks_created += len(applied.tasks_created)
    result_bucket.suppressed += len(applied.suppressed)


# ---------------------------------------------------------------- reply path


def process_reply(
    db: Session,
    patient: Patient,
    reply: int,
    raw_message: str,
    now: Optional[datetime] = None,
    arm: str = "intervention",
) -> ReplyResult:
    """Score an inbound reply, run the policy, and reschedule the patient.

    Does not commit; the caller owns the transaction so the simulator can batch
    a whole day into one flush.
    """
    now = now or datetime.utcnow()

    weeks = refresh_tenure(patient, now)
    consecutive_reply_3 = count_consecutive_reply_3(db, patient.id, reply)
    side_effect_replies = count_recent_side_effect_replies(db, patient.id, now, reply)

    # A reply breaks the silence streak and, if they had lapsed, brings them back.
    patient.last_reply_at = now
    patient.consecutive_no_reply = 0
    if patient.status == STATUS_DISCONTINUED:
        patient.status = STATUS_ACTIVE
        patient.discontinued_at = None
        patient.active = True
    _mark_prompt_answered(db, patient.id, now)

    check_in = CheckIn(
        patient_id=patient.id,
        week_number=weeks,
        reply=reply,
        raw_message=raw_message,
        created_at=now,
    )
    db.add(check_in)

    features = build_features(
        patient,
        weeks_on_therapy=weeks,
        reply=reply,
        consecutive_reply_3=consecutive_reply_3,
        consecutive_no_reply=0,
    )
    scored = risk_scorer.score_patient(features)
    previous_tier = record_risk(db, patient, scored, trigger="reply", now=now)

    ctx = rules.RuleContext(
        patient=patient,
        now=now,
        risk_score=float(scored["risk_score"]),
        risk_tier=scored["risk_tier"],
        barrier_type=scored["barrier_type"],
        weeks_on_therapy=weeks,
        reply=reply,
        consecutive_reply_3=consecutive_reply_3,
        consecutive_no_reply=0,
        recent_side_effect_replies=side_effect_replies,
        sustained_red=(previous_tier == "red" and scored["risk_tier"] == "red"),
    )
    applied = rules.apply_actions(db, ctx, rules.evaluate(ctx), arm=arm)

    if applied.sent_rule_id:
        intervention_fired = applied.sent_rule_id
    elif applied.tasks_created:
        intervention_fired = f"task:{applied.tasks_created[0]}"
    else:
        intervention_fired = "none"

    check_in.risk_score = float(scored["risk_score"])
    check_in.barrier_type = scored["barrier_type"]
    check_in.intervention_fired = intervention_fired
    check_in.intervention_message = applied.sent_body or ""

    schedule_next(patient, now, scored["risk_tier"])

    return ReplyResult(
        patient=patient,
        reply=reply,
        risk_score=float(scored["risk_score"]),
        risk_tier=scored["risk_tier"],
        barrier_type=scored["barrier_type"],
        top_shap_feature=scored.get("top_shap_feature"),
        consecutive_reply_3=consecutive_reply_3,
        intervention_fired=intervention_fired,
        intervention_message=applied.sent_body or "",
        tasks_created=applied.tasks_created,
        suppressed=applied.suppressed,
    )


# ---------------------------------------------------------------- tick


def due_patients(db: Session, now: datetime, limit: Optional[int] = None) -> list:
    """Active patients whose next check-in has come around.

    A null due date means never scheduled, which is how a freshly enrolled
    patient enters the loop.
    """
    query = (
        db.query(Patient)
        .filter(
            Patient.status == STATUS_ACTIVE,
            or_(Patient.next_checkin_due.is_(None), Patient.next_checkin_due <= now),
        )
        .order_by(Patient.next_checkin_due.is_(None).desc(), Patient.next_checkin_due)
    )
    if limit:
        query = query.limit(limit)
    return query.all()


def _silent_since(patient: Patient) -> Optional[datetime]:
    """When this patient last gave us any signal.

    Falls back to enrollment rather than therapy start: a patient seeded at
    week 30 has been on therapy for months but has only been reachable by
    GoalPost¹ since they enrolled.
    """
    return patient.last_reply_at or patient.enrolled_at


def _should_discontinue(patient: Patient, now: datetime) -> bool:
    if patient.last_prompt_at is None:
        return False
    since = _silent_since(patient)
    if since is None:
        return False
    return (now - since).days >= DAYS_SILENT_UNTIL_DISCONTINUED


def run_due_checkins(
    now: Optional[datetime] = None,
    db: Session = None,
    arm: str = "intervention",
    limit: Optional[int] = None,
) -> TickResult:
    """One pass of the scheduler.

    Refreshes tenure, converts unanswered prompts into a silence signal,
    re-scores, applies the policy and reschedules. Does not commit.
    """
    now = now or datetime.utcnow()
    result = TickResult(ran_at=now)

    patients = due_patients(db, now, limit=limit)
    if not patients:
        return result

    pending = []
    for patient in patients:
        weeks = refresh_tenure(patient, now)

        # An unanswered prompt is the signal. Counted here rather than on a
        # timer so one missed prompt is exactly one increment.
        missed = patient.last_prompt_at is not None and (
            patient.last_reply_at is None
            or patient.last_reply_at < patient.last_prompt_at
        )
        if missed:
            patient.consecutive_no_reply = (patient.consecutive_no_reply or 0) + 1
            result.missed_checkins += 1

        if _should_discontinue(patient, now):
            patient.status = STATUS_DISCONTINUED
            patient.discontinued_at = now
            patient.active = False
            patient.next_checkin_due = None
            result.discontinued += 1
            continue

        latest = latest_check_in(db, patient.id)
        pending.append(
            {
                "patient": patient,
                "weeks": weeks,
                "last_reply": latest.reply if latest else None,
                "consecutive_reply_3": count_consecutive_reply_3(db, patient.id),
                "side_effect_replies": count_recent_side_effect_replies(
                    db, patient.id, now
                ),
            }
        )

    if not pending:
        return result

    # One SHAP call for the whole batch. At cohort scale the per-row path was
    # the dominant cost of a tick.
    feature_rows = [
        build_features(
            item["patient"],
            weeks_on_therapy=item["weeks"],
            reply=None,
            consecutive_reply_3=item["consecutive_reply_3"],
            consecutive_no_reply=item["patient"].consecutive_no_reply or 0,
            gi_recent=item["side_effect_replies"] > 0,
        )
        for item in pending
    ]
    scores = risk_scorer.score_batch(feature_rows)

    for item, scored in zip(pending, scores):
        patient = item["patient"]
        result.considered += 1

        previous_tier = record_risk(db, patient, scored, trigger="scheduled", now=now)

        ctx = rules.RuleContext(
            patient=patient,
            now=now,
            risk_score=float(scored["risk_score"]),
            risk_tier=scored["risk_tier"],
            barrier_type=scored["barrier_type"],
            weeks_on_therapy=item["weeks"],
            reply=None,
            consecutive_reply_3=item["consecutive_reply_3"],
            consecutive_no_reply=patient.consecutive_no_reply or 0,
            recent_side_effect_replies=item["side_effect_replies"],
            sustained_red=(previous_tier == "red" and scored["risk_tier"] == "red"),
        )
        applied = rules.apply_actions(db, ctx, rules.evaluate(ctx), arm=arm)
        _record_outcome(result, applied)

        schedule_next(patient, now, scored["risk_tier"])

    return result


def tick(db: Session, now: Optional[datetime] = None, arm: str = "intervention") -> dict:
    """Run a tick and commit it. The API and APScheduler entry point."""
    now = now or datetime.utcnow()
    try:
        result = run_due_checkins(now=now, db=db, arm=arm)
        db.commit()
        return result.as_dict()
    except Exception as exc:
        db.rollback()
        print(f"[scheduling] tick failed: {exc}")
        return TickResult(ran_at=now).as_dict() | {"error": str(exc)}
