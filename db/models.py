"""ORM models for GoalPost¹: enrolled patients and their weekly check-ins."""

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


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(120), nullable=False)
    weeks_on_therapy = Column(Integer, nullable=False, default=0)
    indication = Column(String(8), nullable=False)  # "AOM" or "T2D"
    insurance_type = Column(String(20), nullable=False)
    income_quintile = Column(Integer, nullable=False)
    baseline_bmi = Column(Float, nullable=False)
    enrolled_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    active = Column(Boolean, nullable=False, default=True)

    check_ins = relationship(
        "CheckIn",
        back_populates="patient",
        cascade="all, delete-orphan",
        order_by="CheckIn.created_at",
    )

    def __repr__(self) -> str:
        return f"<Patient id={self.id} name={self.name!r} week={self.weeks_on_therapy}>"


class CheckIn(Base):
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
