"""Declarative intervention policy for GoaLPost¹.

Every decision about what to send and when to involve a human lives in RULES
below, so the policy can be read end to end without tracing control flow. The
engine evaluates rules against a context, then applies the guardrails centrally
rather than trusting each rule to police itself.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional
import os

from sqlalchemy.orm import Session

from db.models import (
    PROMPT_KINDS,
    TASK_ACKNOWLEDGED,
    TASK_OPEN,
    OutboundMessage,
    Patient,
    Task,
)
from services import plateau_messenger, sms_sender

# Guardrails
MAX_MESSAGES_PER_WEEK = 2
DUPLICATE_BODY_WINDOW_DAYS = 14
# Optional overrides for demos outside business hours, e.g. SEND_WINDOW_END_HOUR=24
SEND_WINDOW_START_HOUR = int(os.getenv("SEND_WINDOW_START_HOUR", "9"))
SEND_WINDOW_END_HOUR = int(os.getenv("SEND_WINDOW_END_HOUR", "20"))

# A care team should not get the same patient for the same reason twice in
# three weeks, even if they already closed the first one. Escalation rules that
# fire on a standing condition set a longer cooldown of their own: without it a
# patient who stays red or stays silent regenerates the same task every tick and
# the queue becomes a backlog nobody can work.
DEFAULT_TASK_COOLDOWN_DAYS = 21

PLATEAU_RISK_THRESHOLD = 0.45

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

COST_MESSAGE = (
    "Cost should not be the reason you stop. Many plans cover more than people "
    "expect, and there are manufacturer savings programs for this treatment. "
    "Your care team is checking your coverage and will follow up with options."
)

NUDGE_MESSAGE = (
    "We have not heard from you in a little while. Even a one-number reply "
    "helps your care team support you. Reply 1 if things are going well, "
    "2 for side effects, or 3 if you are not seeing results."
)


@dataclass
class RuleContext:
    """Everything a rule is allowed to look at."""

    patient: Patient
    now: datetime
    risk_score: float
    risk_tier: str
    barrier_type: str
    weeks_on_therapy: int
    reply: Optional[int] = None  # None when the tick fired, not a patient reply
    consecutive_reply_3: int = 0
    consecutive_no_reply: int = 0
    recent_side_effect_replies: int = 0
    sustained_red: bool = False


@dataclass
class Action:
    """A send or a task produced by a matching rule."""

    rule_id: str
    kind: str  # "sms" | "task"
    priority: int
    message_kind: str = "intervention"
    body: Optional[str] = None
    # Deferred so an LLM call only happens when the guardrails let it through.
    body_builder: Optional[Callable[[RuleContext], str]] = None
    task_kind: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class Rule:
    id: str
    name: str
    priority: int
    when: Callable[[RuleContext], bool]
    actions: Callable[[RuleContext], list]
    cooldown_days: int = 0


def _plateau_body(ctx: RuleContext) -> str:
    return plateau_messenger.generate_plateau_message(
        patient_dict={"indication": ctx.patient.indication},
        weeks_on_therapy=ctx.weeks_on_therapy,
        consecutive_reply_3=ctx.consecutive_reply_3,
    )


def checkin_body(ctx: RuleContext) -> str:
    """The weekly 1/2/3 prompt. Public because manual sends reuse it."""
    return sms_sender.build_checkin_message(ctx.patient.name, ctx.weeks_on_therapy + 1)


RULES: list[Rule] = [
    Rule(
        id="red_sustained",
        name="Sustained red risk",
        priority=100,
        when=lambda c: c.sustained_red and c.risk_tier == "red",
        actions=lambda c: [
            Action(
                rule_id="red_sustained",
                kind="task",
                priority=100,
                task_kind="nurse_call",
                reason=(
                    f"Risk has stayed red across consecutive scorings "
                    f"(currently {c.risk_score:.2f})."
                ),
            )
        ],
        cooldown_days=28,
    ),
    Rule(
        id="silence_escalate",
        name="Two missed check-ins",
        priority=90,
        when=lambda c: c.consecutive_no_reply >= 2,
        actions=lambda c: [
            Action(
                rule_id="silence_escalate",
                kind="task",
                priority=90,
                task_kind="outreach_call",
                reason=(
                    f"No reply to {c.consecutive_no_reply} consecutive check-ins. "
                    f"Silence is the strongest dropout signal."
                ),
            )
        ],
        cooldown_days=28,
    ),
    Rule(
        id="cost_barrier",
        name="Cost barrier detected",
        priority=80,
        when=lambda c: c.barrier_type == "cost" and c.risk_tier in ("amber", "red"),
        actions=lambda c: [
            Action(
                rule_id="cost_barrier",
                kind="sms",
                priority=80,
                body=COST_MESSAGE,
            ),
            Action(
                rule_id="cost_barrier",
                kind="task",
                priority=70,
                task_kind="benefits_check",
                reason=(
                    f"Cost attributed as the dominant barrier at risk "
                    f"{c.risk_score:.2f} ({c.patient.insurance_type})."
                ),
            ),
        ],
        cooldown_days=21,
    ),
    Rule(
        id="side_effect",
        name="Side effects reported",
        priority=70,
        when=lambda c: c.reply == 2,
        actions=lambda c: (
            [
                Action(
                    rule_id="side_effect",
                    kind="sms",
                    priority=70,
                    body=SIDE_EFFECT_MESSAGE,
                )
            ]
            + (
                [
                    Action(
                        rule_id="side_effect",
                        kind="task",
                        priority=80,
                        task_kind="gi_escalation",
                        reason=(
                            f"{c.recent_side_effect_replies} side-effect reports "
                            f"in the last 4 weeks."
                        ),
                    )
                ]
                if c.recent_side_effect_replies >= 2
                else []
            )
        ),
    ),
    Rule(
        id="plateau_streak",
        name="Plateau with elevated risk",
        priority=60,
        when=lambda c: c.reply == 3 and c.risk_score >= PLATEAU_RISK_THRESHOLD,
        actions=lambda c: [
            Action(
                rule_id="plateau_streak",
                kind="sms",
                priority=60,
                body_builder=_plateau_body,
            )
        ],
    ),
    Rule(
        id="silence_nudge",
        name="One missed check-in",
        priority=50,
        when=lambda c: c.consecutive_no_reply == 1,
        actions=lambda c: [
            Action(
                rule_id="silence_nudge",
                kind="sms",
                priority=50,
                message_kind="nudge",
                body=NUDGE_MESSAGE,
            )
        ],
        cooldown_days=5,
    ),
    Rule(
        id="doing_well",
        name="Patient doing well",
        priority=20,
        when=lambda c: c.reply == 1,
        actions=lambda c: [
            Action(
                rule_id="doing_well",
                kind="sms",
                priority=20,
                message_kind="acknowledgement",
                body=POSITIVE_MESSAGE,
            )
        ],
    ),
    Rule(
        id="scheduled_checkin",
        name="Routine cadence check-in",
        priority=10,
        when=lambda c: c.reply is None,
        actions=lambda c: [
            Action(
                rule_id="scheduled_checkin",
                kind="sms",
                priority=10,
                message_kind="checkin_prompt",
                body_builder=checkin_body,
            )
        ],
    ),
]

# The control arm still receives cadence prompts, so the comparison isolates the
# effect of the interventions rather than of being contacted at all.
CONTROL_ARM_RULES = {"scheduled_checkin"}


def within_send_window(now: datetime) -> bool:
    """Send window uses the hour on whatever clock the caller passed.

    Live routes should pass local wall-clock time (datetime.now()), not UTC.
    The simulator already uses virtual wall-clock hours (tick at 10:00).
    """
    return SEND_WINDOW_START_HOUR <= now.hour < SEND_WINDOW_END_HOUR


def evaluate(ctx: RuleContext) -> list:
    """Return the actions of every matching rule, highest priority first."""
    actions: list = []
    for rule in sorted(RULES, key=lambda r: -r.priority):
        try:
            if rule.when(ctx):
                actions.extend(rule.actions(ctx))
        except Exception as exc:
            print(f"[rules] rule {rule.id} failed to evaluate: {exc}")
    return sorted(actions, key=lambda a: -a.priority)


def _messages_last_7_days(db: Session, patient_id: int, now: datetime) -> int:
    return (
        db.query(OutboundMessage)
        .filter(
            OutboundMessage.patient_id == patient_id,
            OutboundMessage.sent_at > now - timedelta(days=7),
        )
        .count()
    )


def _rule_on_cooldown(
    db: Session, patient_id: int, rule_id: str, cooldown_days: int, now: datetime
) -> bool:
    if cooldown_days <= 0:
        return False
    recent = (
        db.query(OutboundMessage)
        .filter(
            OutboundMessage.patient_id == patient_id,
            OutboundMessage.rule_id == rule_id,
            OutboundMessage.sent_at > now - timedelta(days=cooldown_days),
        )
        .first()
    )
    return recent is not None


def _is_duplicate_body(db: Session, patient_id: int, body: str, now: datetime) -> bool:
    recent = (
        db.query(OutboundMessage)
        .filter(
            OutboundMessage.patient_id == patient_id,
            OutboundMessage.body == body,
            OutboundMessage.sent_at > now - timedelta(days=DUPLICATE_BODY_WINDOW_DAYS),
        )
        .first()
    )
    return recent is not None


def _open_task_exists(db: Session, patient_id: int, kind: str) -> bool:
    existing = (
        db.query(Task)
        .filter(
            Task.patient_id == patient_id,
            Task.kind == kind,
            Task.status.in_([TASK_OPEN, TASK_ACKNOWLEDGED]),
        )
        .first()
    )
    return existing is not None


def _task_on_cooldown(
    db: Session, patient_id: int, kind: str, cooldown_days: int, now: datetime
) -> bool:
    """True if this kind of task was already raised recently.

    Deduplicating against open tasks alone is not enough: the moment the care
    team closes one, the rule that raised it fires again on the next tick and
    the queue refills with the same work.
    """
    if cooldown_days <= 0:
        return False
    recent = (
        db.query(Task)
        .filter(
            Task.patient_id == patient_id,
            Task.kind == kind,
            Task.created_at > now - timedelta(days=cooldown_days),
        )
        .first()
    )
    return recent is not None


def _cooldown_for(rule_id: str) -> int:
    for rule in RULES:
        if rule.id == rule_id:
            return rule.cooldown_days
    return 0


@dataclass
class ApplyResult:
    sent_body: Optional[str] = None
    sent_rule_id: Optional[str] = None
    tasks_created: list = field(default_factory=list)
    suppressed: list = field(default_factory=list)


def apply_actions(
    db: Session,
    ctx: RuleContext,
    actions: list,
    arm: str = "intervention",
) -> ApplyResult:
    """Execute actions under the guardrails.

    At most one SMS goes out per evaluation. Tasks are deduplicated against
    anything already open so the queue does not fill with repeats.
    """
    result = ApplyResult()
    patient = ctx.patient
    now = ctx.now

    if arm == "control":
        actions = [a for a in actions if a.rule_id in CONTROL_ARM_RULES]

    # The session runs with autoflush off, and a simulated day batches a whole
    # tick plus every reply into one transaction. Without this the guardrail
    # queries below cannot see sends that are still pending, and the weekly cap
    # silently leaks.
    db.flush()

    weekly_count = _messages_last_7_days(db, patient.id, now)

    for action in actions:
        if action.kind == "sms":
            if result.sent_body is not None:
                result.suppressed.append((action.rule_id, "one message per evaluation"))
                continue
            if weekly_count >= MAX_MESSAGES_PER_WEEK:
                result.suppressed.append((action.rule_id, "weekly cap"))
                continue
            if not within_send_window(now):
                result.suppressed.append((action.rule_id, "outside send window"))
                continue
            if _rule_on_cooldown(
                db, patient.id, action.rule_id, _cooldown_for(action.rule_id), now
            ):
                result.suppressed.append((action.rule_id, "rule cooldown"))
                continue

            try:
                body = action.body or (
                    action.body_builder(ctx) if action.body_builder else None
                )
            except Exception as exc:
                print(f"[rules] could not build body for {action.rule_id}: {exc}")
                continue
            if not body:
                continue

            if _is_duplicate_body(db, patient.id, body, now):
                result.suppressed.append((action.rule_id, "duplicate body"))
                continue

            sms_sender.send_sms(patient.phone_number, body)
            db.add(
                OutboundMessage(
                    patient_id=patient.id,
                    kind=action.message_kind,
                    body=body,
                    rule_id=action.rule_id,
                    sent_at=now,
                    responded=False,
                )
            )
            patient.last_contacted_at = now
            if action.message_kind in PROMPT_KINDS:
                patient.last_prompt_at = now
            weekly_count += 1
            result.sent_body = body
            result.sent_rule_id = action.rule_id

        elif action.kind == "task":
            if _open_task_exists(db, patient.id, action.task_kind):
                result.suppressed.append((action.rule_id, "task already open"))
                continue
            if _task_on_cooldown(
                db,
                patient.id,
                action.task_kind,
                _cooldown_for(action.rule_id) or DEFAULT_TASK_COOLDOWN_DAYS,
                now,
            ):
                result.suppressed.append((action.rule_id, "task cooldown"))
                continue
            db.add(
                Task(
                    patient_id=patient.id,
                    kind=action.task_kind,
                    priority=action.priority,
                    reason=action.reason,
                    rule_id=action.rule_id,
                    status=TASK_OPEN,
                    created_at=now,
                )
            )
            result.tasks_created.append(action.task_kind)

    return result
