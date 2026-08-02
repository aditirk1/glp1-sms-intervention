"""ORM models for GoalPost¹.

Patient and CheckIn hold the clinical record. OutboundMessage, Task and
RiskSnapshot exist so the scheduler can work at cohort scale: they let the
engine answer "when is this patient due", "have we already messaged them this
week", "who needs a human today" and "how did risk move over time" without
scanning conversation history.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from db.database import Base

STATUS_ACTIVE = "active"
STATUS_PAUSED = "paused"
STATUS_DISCONTINUED = "discontinued"

TASK_OPEN = "open"
TASK_ACKNOWLEDGED = "acknowledged"
TASK_RESOLVED = "resolved"

KIND_CHECKIN_PROMPT = "checkin_prompt"
KIND_NUDGE = "nudge"
KIND_INTERVENTION = "intervention"
KIND_ACKNOWLEDGEMENT = "acknowledgement"

# Only these ask the patient a question, so only these can go unanswered.
PROMPT_KINDS = (KIND_CHECKIN_PROMPT, KIND_NUDGE)


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(120), nullable=False)
    indication = Column(String(8), nullable=False)  # "AOM" or "T2D"
    insurance_type = Column(String(20), nullable=False)
    income_quintile = Column(Integer, nullable=False)
    baseline_bmi = Column(Float, nullable=False)
    enrolled_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    active = Column(Boolean, nullable=False, default=True)

    # Derived from therapy_start_date on every tick. It used to increment only
    # when a reply arrived, which froze silent patients at week 0 forever.
    weeks_on_therapy = Column(Integer, nullable=False, default=0)
    therapy_start_date = Column(DateTime, nullable=True)

    # Scheduling state. next_checkin_due is the column the tick query filters on.
    last_contacted_at = Column(DateTime, nullable=True)
    # Only prompts ask a question, so only prompts can go unanswered. An
    # intervention message moves last_contacted_at but not this.
    last_prompt_at = Column(DateTime, nullable=True)
    last_reply_at = Column(DateTime, nullable=True)
    next_checkin_due = Column(DateTime, nullable=True, index=True)
    consecutive_no_reply = Column(Integer, nullable=False, default=0)
    status = Column(String(16), nullable=False, default=STATUS_ACTIVE, index=True)
    # Event time for the retention curve. Set when sustained silence crosses the
    # lost-to-follow-up threshold.
    discontinued_at = Column(DateTime, nullable=True)

    # Denormalized latest risk so the roster and queue can sort and filter
    # without joining the full check-in history for every patient.
    current_risk_score = Column(Float, nullable=True, index=True)
    current_risk_tier = Column(String(8), nullable=True, index=True)
    current_barrier_type = Column(String(20), nullable=True)

    check_ins = relationship(
        "CheckIn",
        back_populates="patient",
        cascade="all, delete-orphan",
        order_by="CheckIn.created_at",
    )
    outbound_messages = relationship(
        "OutboundMessage", back_populates="patient", cascade="all, delete-orphan"
    )
    tasks = relationship("Task", back_populates="patient", cascade="all, delete-orphan")
    risk_snapshots = relationship(
        "RiskSnapshot", back_populates="patient", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Patient id={self.id} name={self.name!r} week={self.weeks_on_therapy}>"


class CheckIn(Base):
    """One inbound patient reply and whatever the engine decided in response."""

    __tablename__ = "check_ins"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    week_number = Column(Integer, nullable=False)
    reply = Column(Integer, nullable=False)  # 1, 2 or 3
    raw_message = Column(Text, nullable=True)
    risk_score = Column(Float, nullable=True)
    barrier_type = Column(String(20), nullable=True)  # plateau | side_effect | cost
    intervention_fired = Column(String(40), nullable=True)
    intervention_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    patient = relationship("Patient", back_populates="check_ins")

    def __repr__(self) -> str:
        return f"<CheckIn id={self.id} patient={self.patient_id} reply={self.reply}>"


class OutboundMessage(Base):
    """Every message the system sends.

    Kept separate from CheckIn so the guardrails can ask "how many messages has
    this patient had this week" and response rate is measurable.
    """

    __tablename__ = "outbound_messages"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    kind = Column(String(32), nullable=False)  # checkin_prompt | intervention | nudge
    body = Column(Text, nullable=False)
    rule_id = Column(String(40), nullable=True)
    sent_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    responded = Column(Boolean, nullable=False, default=False)

    patient = relationship("Patient", back_populates="outbound_messages")

    def __repr__(self) -> str:
        return f"<OutboundMessage id={self.id} patient={self.patient_id} kind={self.kind}>"


class Task(Base):
    """A care team work item. Higher priority sorts first in the queue."""

    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    kind = Column(String(40), nullable=False)
    priority = Column(Integer, nullable=False, default=1)
    reason = Column(Text, nullable=True)
    rule_id = Column(String(40), nullable=True)
    status = Column(String(16), nullable=False, default=TASK_OPEN, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(String(80), nullable=True)

    patient = relationship("Patient", back_populates="tasks")

    def __repr__(self) -> str:
        return f"<Task id={self.id} patient={self.patient_id} kind={self.kind}>"


class RiskSnapshot(Base):
    """Risk at a point in time.

    Non-response changes risk without producing a CheckIn, so retention curves
    and trend lines read from here rather than from the reply history.
    """

    __tablename__ = "risk_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    risk_score = Column(Float, nullable=False)
    risk_tier = Column(String(8), nullable=False)
    barrier_type = Column(String(20), nullable=True)
    trigger = Column(String(24), nullable=False)  # reply | scheduled | silence
    week_number = Column(Integer, nullable=True)
    computed_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    patient = relationship("Patient", back_populates="risk_snapshots")

    def __repr__(self) -> str:
        return f"<RiskSnapshot patient={self.patient_id} score={self.risk_score:.3f}>"
