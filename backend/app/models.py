from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import CHAR, JSON, Boolean, Date, DateTime, Enum, ForeignKey, Integer, Numeric, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(Text)
    registration_no: Mapped[str] = mapped_column(Text)
    preferences: Mapped[dict] = mapped_column(JSON)


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(Text)
    age: Mapped[int | None] = mapped_column(Integer)
    dob: Mapped[date | None] = mapped_column(Date)
    sex: Mapped[str] = mapped_column(Text)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    contact: Mapped[str | None] = mapped_column(Text)


class Formulary(Base):
    __tablename__ = "formulary"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    ingredient_name: Mapped[str] = mapped_column(Text)
    atc_class: Mapped[str | None] = mapped_column(Text)
    max_single_dose: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    max_daily_dose: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    mg_per_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    min_age: Mapped[int | None] = mapped_column(Integer)
    max_age: Mapped[int | None] = mapped_column(Integer)
    forms: Mapped[list] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)
    verified_by: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(Text)


class PatientAllergy(Base):
    __tablename__ = "patient_allergies"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    patient_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("patients.id"))
    ingredient_id: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("formulary.id"))
    allergy_class: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)


class Encounter(Base):
    __tablename__ = "encounters"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    patient_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("patients.id"))
    doctor_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("doctors.id"))
    mode: Mapped[str] = mapped_column(Enum("manual", "voice", "ambient", name="encounter_mode"))
    status: Mapped[str] = mapped_column(Enum("draft", "signed", name="encounter_status"))
    recording_consent: Mapped[bool] = mapped_column(Boolean)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    diagnosis: Mapped[str | None] = mapped_column(Text)


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    encounter_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("encounters.id"))
    segments: Mapped[list] = mapped_column(JSON)


class Prescription(Base):
    __tablename__ = "prescriptions"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    encounter_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("encounters.id"))
    status: Mapped[str] = mapped_column(Enum("draft", "signed", name="prescription_status"))
    signed_by: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("doctors.id"))
    signed_registration_no: Mapped[str | None] = mapped_column(Text)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime)
    pdf_url: Mapped[str | None] = mapped_column(Text)
    locked: Mapped[bool] = mapped_column(Boolean)


class BrandCatalog(Base):
    __tablename__ = "brand_catalog"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    brand_name: Mapped[str] = mapped_column(Text)
    ingredient_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("formulary.id"))
    strength: Mapped[str] = mapped_column(Text)
    form: Mapped[str] = mapped_column(Text)
    manufacturer: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)


class PrescriptionItem(Base):
    __tablename__ = "prescription_items"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    prescription_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("prescriptions.id"))
    ingredient_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("formulary.id"))
    brand_id: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("brand_catalog.id"))
    strength: Mapped[str] = mapped_column(Text)
    form: Mapped[str] = mapped_column(Text)
    route: Mapped[str] = mapped_column(Text)
    dose: Mapped[str] = mapped_column(Text)
    frequency: Mapped[str] = mapped_column(Text)
    duration: Mapped[str] = mapped_column(Text)
    instructions: Mapped[str | None] = mapped_column(Text)
    evidence_segment_ids: Mapped[list] = mapped_column(JSON)
    evidence_status: Mapped[str] = mapped_column(
        Enum("linked", "missing_context", name="evidence_status")
    )


class SafetyEvent(Base):
    __tablename__ = "safety_events"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    encounter_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("encounters.id"))
    prescription_item_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("prescription_items.id")
    )
    type: Mapped[str] = mapped_column(
        Enum("dose", "interaction", "allergy", "age", "uncovered", name="safety_event_type")
    )
    severity: Mapped[str] = mapped_column(
        Enum("info", "warning", "severe", name="safety_event_severity")
    )
    message: Mapped[str] = mapped_column(Text)
    shown_at: Mapped[datetime] = mapped_column(DateTime)
    acknowledged: Mapped[bool] = mapped_column(Boolean)
    acknowledged_by: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("doctors.id"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime)
    override_reason: Mapped[str | None] = mapped_column(Text)


class Interaction(Base):
    __tablename__ = "interactions"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    ingredient_a: Mapped[str] = mapped_column(CHAR(36), ForeignKey("formulary.id"))
    ingredient_b: Mapped[str] = mapped_column(CHAR(36), ForeignKey("formulary.id"))
    severity: Mapped[str] = mapped_column(
        Enum("info", "warning", "severe", name="interaction_severity")
    )
    description: Mapped[str] = mapped_column(Text)
    management: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)


class AllergyClass(Base):
    __tablename__ = "allergy_classes"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    class_name: Mapped[str] = mapped_column(Text)
    member_ingredient_ids: Mapped[list] = mapped_column(JSON)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=new_id)
    actor_id: Mapped[str] = mapped_column(CHAR(36))
    action: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[str] = mapped_column(CHAR(36))
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    at: Mapped[datetime] = mapped_column(DateTime)
