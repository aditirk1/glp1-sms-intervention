"""Simulated patient behaviour.

Each patient carries a latent state the system cannot observe directly (doing
well, plateaued, fighting GI side effects, or blocked on cost) and a reply
probability that decays with tenure and rises with engagement. The scheduler
only ever sees what a real deployment would see: a reply, or silence.

Every effect size below is an assumption, not a finding. The simulation cannot
prove that a cost-navigation text resolves a coverage barrier 30% of the time;
it proves that the scheduler finds the right patients on the right day, that
the guardrails hold at cohort scale, and that a given set of effect sizes
produces a given retention curve. Treat EFFECTS as the dial to argue about.
"""

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from db.models import (
    STATUS_ACTIVE,
    TASK_OPEN,
    TASK_RESOLVED,
    OutboundMessage,
    Patient,
    Task,
)

STATE_WELL = "well"
STATE_PLATEAU = "plateau"
STATE_GI = "gi"
STATE_COST = "cost"

# How long a patient will still answer a prompt before it goes stale.
REPLY_WINDOW_DAYS = 4

# Patients who will never answer a text again, whatever we send. Real panels
# have them, and a harness without them flatters the intervention.
PERMANENT_SILENCE_RATE = 0.06

# Weekly probability of leaving therapy, before state and tenure adjustments.
BASE_QUIT_HAZARD = {"AOM": 0.009, "T2D": 0.004}

# Added weekly hazard while the barrier is live and unaddressed.
STATE_HAZARD = {
    STATE_WELL: 0.000,
    STATE_PLATEAU: 0.020,
    STATE_GI: 0.026,
    STATE_COST: 0.030,
}

# Real GLP-1 discontinuation is front-loaded into the titration months.
EARLY_TENURE_MULTIPLIER = 1.8
EARLY_TENURE_WEEKS = 12

# Weekly reply probability by state, before engagement and tenure decay.
STATE_REPLY_FACTOR = {
    STATE_WELL: 1.00,
    STATE_PLATEAU: 0.78,
    STATE_GI: 0.86,
    STATE_COST: 0.72,
}

# Distribution over the 1/2/3 reply codes for each latent state. Cost patients
# have no code of their own: they read as plateau or as fine, which is exactly
# why the barrier has to come from the model rather than from the reply.
REPLY_MIX = {
    STATE_WELL: {1: 0.86, 2: 0.05, 3: 0.09},
    STATE_PLATEAU: {1: 0.14, 2: 0.09, 3: 0.77},
    STATE_GI: {1: 0.14, 2: 0.76, 3: 0.10},
    STATE_COST: {1: 0.34, 2: 0.19, 3: 0.47},
}

# Weekly probability of drifting into a barrier state from "well".
GI_ONSET_WEEKLY = 0.055          # concentrated in titration
GI_ONSET_UNTIL_WEEK = 10
GI_SPONTANEOUS_RESOLVE = 0.10    # bodies adapt on their own
PLATEAU_ONSET_WEEKLY = 0.030     # rises once the fast loss phase ends
PLATEAU_ONSET_FROM_WEEK = 12
COST_ONSET_WEEKLY = 0.010        # a denial or a formulary change lands


@dataclass
class Effect:
    """What a message or a worked task does to the patient underneath."""

    resolves: float = 0.0        # chance the barrier clears outright
    relief: float = 1.0          # multiplier on quit hazard while it lasts
    relief_weeks: int = 4
    engagement: float = 0.0      # additive bump to reply propensity
    applies_to: tuple = ()       # latent states this can help


# Keyed by rule_id for messages and by task kind for worked tasks.
EFFECTS = {
    "plateau_streak": Effect(
        resolves=0.30, relief=0.62, relief_weeks=4,
        engagement=0.04, applies_to=(STATE_PLATEAU,),
    ),
    "side_effect": Effect(
        resolves=0.34, relief=0.60, relief_weeks=4,
        engagement=0.04, applies_to=(STATE_GI,),
    ),
    "cost_barrier": Effect(
        resolves=0.22, relief=0.65, relief_weeks=6,
        engagement=0.03, applies_to=(STATE_COST,),
    ),
    "silence_nudge": Effect(
        relief=0.92, relief_weeks=2, engagement=0.10,
        applies_to=(STATE_WELL, STATE_PLATEAU, STATE_GI, STATE_COST),
    ),
    "doing_well": Effect(relief=0.97, relief_weeks=2, engagement=0.02,
                         applies_to=(STATE_WELL,)),
    # A human on the phone is worth more than a text, and costs more.
    "outreach_call": Effect(
        resolves=0.20, relief=0.55, relief_weeks=6, engagement=0.22,
        applies_to=(STATE_WELL, STATE_PLATEAU, STATE_GI, STATE_COST),
    ),
    "nurse_call": Effect(
        resolves=0.38, relief=0.50, relief_weeks=8, engagement=0.16,
        applies_to=(STATE_PLATEAU, STATE_GI, STATE_COST),
    ),
    "benefits_check": Effect(
        resolves=0.52, relief=0.45, relief_weeks=10, engagement=0.08,
        applies_to=(STATE_COST,),
    ),
    "gi_escalation": Effect(
        resolves=0.55, relief=0.45, relief_weeks=8, engagement=0.08,
        applies_to=(STATE_GI,),
    ),
}

# Tasks a care team can actually work in a day. Without a cap the queue is free
# labour and the intervention arm wins on volume rather than on targeting.
CARE_TEAM_DAILY_CAPACITY = 25
TASK_TURNAROUND_DAYS = 2


@dataclass
class Profile:
    """The latent truth about one simulated patient."""

    state: str
    engagement: float
    permanently_silent: bool
    quit_at: Optional[datetime] = None
    relief: float = 1.0
    relief_until: Optional[datetime] = None
    engagement_bonus: float = 0.0
    engagement_bonus_until: Optional[datetime] = None
    interventions_received: int = 0
    barriers_resolved: int = 0


@dataclass
class DayResult:
    replies: int = 0
    quits: int = 0
    tasks_worked: int = 0
    barriers_resolved: int = 0
    reply_codes: dict = field(default_factory=dict)


class Cohort:
    """Latent behaviour for every patient in the simulation."""

    def __init__(self, patients: list, rng: random.Random):
        self.rng = rng
        self.profiles: dict = {}
        for patient in patients:
            self.profiles[patient.id] = self._initial_profile(patient)
        self._last_message_id = 0
        self._task_due: dict = {}

    # ------------------------------------------------------------ setup

    def _initial_profile(self, patient: Patient) -> Profile:
        rng = self.rng
        weeks = patient.weeks_on_therapy or 0

        cost_pressure = (
            patient.insurance_type in ("medicaid", "uninsured")
            or patient.income_quintile <= 2
        )

        roll = rng.random()
        if cost_pressure and roll < 0.22:
            state = STATE_COST
        elif weeks <= GI_ONSET_UNTIL_WEEK and roll < 0.30:
            state = STATE_GI
        elif weeks >= PLATEAU_ONSET_FROM_WEEK and roll < 0.38:
            state = STATE_PLATEAU
        else:
            state = STATE_WELL

        # Engagement is a trait, not a coin flip: some people always answer.
        engagement = min(0.95, max(0.10, rng.betavariate(5.0, 2.2)))

        return Profile(
            state=state,
            engagement=engagement,
            permanently_silent=rng.random() < PERMANENT_SILENCE_RATE,
        )

    # ------------------------------------------------------- probabilities

    def reply_probability(self, patient: Patient, profile: Profile, now: datetime) -> float:
        """Weekly chance this patient answers an outstanding prompt."""
        if profile.permanently_silent or profile.quit_at is not None:
            return 0.0

        weeks = patient.weeks_on_therapy or 0
        # Novelty wears off. Half-life of roughly a year of tenure.
        tenure_decay = math.exp(-weeks / 55.0)
        risk = patient.current_risk_score or 0.35

        bonus = (
            profile.engagement_bonus
            if profile.engagement_bonus_until
            and now < profile.engagement_bonus_until
            else 0.0
        )

        probability = (
            (profile.engagement + bonus)
            * (0.45 + 0.55 * tenure_decay)
            * STATE_REPLY_FACTOR[profile.state]
            * (1.0 - 0.30 * risk)
        )
        return min(0.97, max(0.0, probability))

    def quit_hazard(self, patient: Patient, profile: Profile, now: datetime) -> float:
        """Weekly chance this patient stops therapy."""
        weeks = patient.weeks_on_therapy or 0
        hazard = BASE_QUIT_HAZARD.get(patient.indication, 0.007)
        hazard += STATE_HAZARD[profile.state]

        if weeks <= EARLY_TENURE_WEEKS:
            hazard *= EARLY_TENURE_MULTIPLIER

        if profile.relief_until and now < profile.relief_until:
            hazard *= profile.relief

        # Disengagement is not just a symptom of leaving, it accelerates it.
        hazard *= 1.0 + 0.12 * min(patient.consecutive_no_reply or 0, 4)
        return min(0.5, hazard)

    # ------------------------------------------------------------ effects

    def _apply_effect(self, profile: Profile, effect: Effect, now: datetime) -> bool:
        """Returns True if the underlying barrier cleared."""
        profile.interventions_received += 1

        if effect.engagement:
            profile.engagement_bonus = effect.engagement
            profile.engagement_bonus_until = now + timedelta(weeks=3)

        resolved = False
        if (
            profile.state in effect.applies_to
            and profile.state != STATE_WELL
            and self.rng.random() < effect.resolves
        ):
            profile.state = STATE_WELL
            profile.barriers_resolved += 1
            resolved = True

        if effect.relief < 1.0 and profile.state in effect.applies_to:
            profile.relief = min(profile.relief, effect.relief)
            profile.relief_until = now + timedelta(weeks=effect.relief_weeks)

        return resolved

    def _absorb_messages(self, db, now: datetime, result: DayResult) -> None:
        """Let patients react to whatever the engine sent since the last step."""
        messages = (
            db.query(OutboundMessage)
            .filter(OutboundMessage.id > self._last_message_id)
            .order_by(OutboundMessage.id)
            .all()
        )
        for message in messages:
            self._last_message_id = max(self._last_message_id, message.id)
            profile = self.profiles.get(message.patient_id)
            effect = EFFECTS.get(message.rule_id or "")
            if profile is None or effect is None:
                continue
            if self._apply_effect(profile, effect, now):
                result.barriers_resolved += 1

    def _work_tasks(self, db, now: datetime, result: DayResult) -> None:
        """A bounded care team works the queue in priority order."""
        # Age is filtered in the query, not after it: filtering a limited slice
        # lets fresh high-priority tasks eat the day's capacity and the backlog
        # grows even though the team is nowhere near busy.
        open_tasks = (
            db.query(Task)
            .filter(
                Task.status == TASK_OPEN,
                Task.created_at <= now - timedelta(days=TASK_TURNAROUND_DAYS),
            )
            .order_by(Task.priority.desc(), Task.created_at)
            .limit(CARE_TEAM_DAILY_CAPACITY)
            .all()
        )
        for task in open_tasks:
            task.status = TASK_RESOLVED
            task.resolved_at = now
            task.resolved_by = "care team (simulated)"
            result.tasks_worked += 1

            profile = self.profiles.get(task.patient_id)
            effect = EFFECTS.get(task.kind)
            if profile is None or effect is None:
                continue
            if self._apply_effect(profile, effect, now):
                result.barriers_resolved += 1

    # ------------------------------------------------------- state drift

    def _drift(self, patient: Patient, profile: Profile) -> None:
        """Weekly chance of moving between latent states."""
        rng = self.rng
        weeks = patient.weeks_on_therapy or 0

        if profile.state == STATE_GI and rng.random() < GI_SPONTANEOUS_RESOLVE:
            profile.state = STATE_WELL
            return

        if profile.state != STATE_WELL:
            return

        if weeks <= GI_ONSET_UNTIL_WEEK and rng.random() < GI_ONSET_WEEKLY:
            profile.state = STATE_GI
        elif weeks >= PLATEAU_ONSET_FROM_WEEK and rng.random() < PLATEAU_ONSET_WEEKLY:
            profile.state = STATE_PLATEAU
        elif rng.random() < COST_ONSET_WEEKLY:
            profile.state = STATE_COST

    # ------------------------------------------------------------- step

    def step(self, db, now: datetime, patients: list, on_reply) -> DayResult:
        """Advance every patient one day.

        on_reply(patient, reply_code, now) is called for each reply so the
        caller can push it through the same pipeline an inbound SMS would take.
        """
        result = DayResult()
        rng = self.rng

        self._absorb_messages(db, now, result)
        self._work_tasks(db, now, result)

        # Hazards and drift are specified weekly; convert once per day.
        daily = 1.0 / 7.0

        for patient in patients:
            profile = self.profiles.get(patient.id)
            if profile is None or profile.quit_at is not None:
                continue

            if rng.random() < daily:
                self._drift(patient, profile)

            if rng.random() < self.quit_hazard(patient, profile, now) * daily:
                profile.quit_at = now
                result.quits += 1
                continue

            if patient.status != STATUS_ACTIVE:
                continue

            outstanding = patient.last_prompt_at is not None and (
                patient.last_reply_at is None
                or patient.last_reply_at < patient.last_prompt_at
            )
            if not outstanding:
                continue
            if (now - patient.last_prompt_at).days > REPLY_WINDOW_DAYS:
                continue

            weekly = self.reply_probability(patient, profile, now)
            if weekly <= 0.0:
                continue
            # Spread the weekly probability across the days it can land on.
            per_day = 1.0 - (1.0 - weekly) ** (1.0 / max(REPLY_WINDOW_DAYS, 1))
            if rng.random() >= per_day:
                continue

            code = self._sample_reply(profile)
            result.replies += 1
            result.reply_codes[code] = result.reply_codes.get(code, 0) + 1
            on_reply(patient, code, now)

        return result

    def _sample_reply(self, profile: Profile) -> int:
        mix = REPLY_MIX[profile.state]
        roll = self.rng.random()
        cumulative = 0.0
        for code, weight in mix.items():
            cumulative += weight
            if roll < cumulative:
                return code
        return 1

    # ---------------------------------------------------------- reporting

    def ground_truth(self) -> dict:
        """What actually happened underneath, which the engine never sees."""
        states: dict = {}
        for profile in self.profiles.values():
            states[profile.state] = states.get(profile.state, 0) + 1
        quit_count = sum(1 for p in self.profiles.values() if p.quit_at is not None)
        return {
            "on_therapy": len(self.profiles) - quit_count,
            "quit": quit_count,
            "states": states,
            "barriers_resolved": sum(
                p.barriers_resolved for p in self.profiles.values()
            ),
            "interventions_received": sum(
                p.interventions_received for p in self.profiles.values()
            ),
        }

    def quit_weeks(self, origin: datetime) -> list:
        """Week index of each ground-truth quit, for the true retention curve."""
        return [
            max(0, (p.quit_at - origin).days // 7)
            for p in self.profiles.values()
            if p.quit_at is not None
        ]
