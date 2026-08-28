"""Initial architecture section 6 schema.

Revision ID: 0001
Revises: None
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def id_column() -> sa.Column:
    return sa.Column("id", sa.CHAR(36), primary_key=True)


def upgrade() -> None:
    op.create_table(
        "doctors",
        id_column(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("registration_no", sa.Text(), nullable=False),
        sa.Column("preferences", sa.JSON(), nullable=False),
    )
    op.create_table(
        "patients",
        id_column(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("dob", sa.Date(), nullable=True),
        sa.Column("sex", sa.Text(), nullable=False),
        sa.Column("weight_kg", sa.Numeric(8, 2), nullable=True),
        sa.Column("contact", sa.Text(), nullable=True),
    )
    op.create_table(
        "formulary",
        id_column(),
        sa.Column("ingredient_name", sa.Text(), nullable=False),
        sa.Column("atc_class", sa.Text(), nullable=True),
        sa.Column("max_single_dose", sa.Numeric(10, 2), nullable=True),
        sa.Column("max_daily_dose", sa.Numeric(10, 2), nullable=True),
        sa.Column("mg_per_kg", sa.Numeric(10, 2), nullable=True),
        sa.Column("min_age", sa.Integer(), nullable=True),
        sa.Column("max_age", sa.Integer(), nullable=True),
        sa.Column("forms", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("verified_by", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
    )
    op.create_table(
        "patient_allergies",
        id_column(),
        sa.Column("patient_id", sa.CHAR(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("ingredient_id", sa.CHAR(36), sa.ForeignKey("formulary.id"), nullable=True),
        sa.Column("allergy_class", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_table(
        "encounters",
        id_column(),
        sa.Column("patient_id", sa.CHAR(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("doctor_id", sa.CHAR(36), sa.ForeignKey("doctors.id"), nullable=False),
        sa.Column("mode", sa.Enum("manual", "voice", "ambient", name="encounter_mode"), nullable=False),
        sa.Column("status", sa.Enum("draft", "signed", name="encounter_status"), nullable=False),
        sa.Column("recording_consent", sa.Boolean(), nullable=False),
        sa.Column("consent_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("diagnosis", sa.Text(), nullable=True),
    )
    op.create_table(
        "transcripts",
        id_column(),
        sa.Column("encounter_id", sa.CHAR(36), sa.ForeignKey("encounters.id"), nullable=False),
        sa.Column("segments", sa.JSON(), nullable=False),
    )
    op.create_table(
        "prescriptions",
        id_column(),
        sa.Column("encounter_id", sa.CHAR(36), sa.ForeignKey("encounters.id"), nullable=False),
        sa.Column("status", sa.Enum("draft", "signed", name="prescription_status"), nullable=False),
        sa.Column("signed_by", sa.CHAR(36), sa.ForeignKey("doctors.id"), nullable=True),
        sa.Column("signed_registration_no", sa.Text(), nullable=True),
        sa.Column("signed_at", sa.DateTime(), nullable=True),
        sa.Column("pdf_url", sa.Text(), nullable=True),
        sa.Column("locked", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "brand_catalog",
        id_column(),
        sa.Column("brand_name", sa.Text(), nullable=False),
        sa.Column("ingredient_id", sa.CHAR(36), sa.ForeignKey("formulary.id"), nullable=False),
        sa.Column("strength", sa.Text(), nullable=False),
        sa.Column("form", sa.Text(), nullable=False),
        sa.Column("manufacturer", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
    )
    op.create_table(
        "prescription_items",
        id_column(),
        sa.Column("prescription_id", sa.CHAR(36), sa.ForeignKey("prescriptions.id"), nullable=False),
        sa.Column("ingredient_id", sa.CHAR(36), sa.ForeignKey("formulary.id"), nullable=False),
        sa.Column("brand_id", sa.CHAR(36), sa.ForeignKey("brand_catalog.id"), nullable=True),
        sa.Column("strength", sa.Text(), nullable=False),
        sa.Column("form", sa.Text(), nullable=False),
        sa.Column("route", sa.Text(), nullable=False),
        sa.Column("dose", sa.Text(), nullable=False),
        sa.Column("frequency", sa.Text(), nullable=False),
        sa.Column("duration", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("evidence_segment_ids", sa.JSON(), nullable=False),
        sa.Column(
            "evidence_status",
            sa.Enum("linked", "missing_context", name="evidence_status"),
            nullable=False,
        ),
    )
    op.create_table(
        "safety_events",
        id_column(),
        sa.Column("encounter_id", sa.CHAR(36), sa.ForeignKey("encounters.id"), nullable=False),
        sa.Column(
            "prescription_item_id",
            sa.CHAR(36),
            sa.ForeignKey("prescription_items.id"),
            nullable=True,
        ),
        sa.Column(
            "type",
            sa.Enum("dose", "interaction", "allergy", "age", "uncovered", name="safety_event_type"),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum("info", "warning", "severe", name="safety_event_severity"),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("shown_at", sa.DateTime(), nullable=False),
        sa.Column("acknowledged", sa.Boolean(), nullable=False),
        sa.Column("acknowledged_by", sa.CHAR(36), sa.ForeignKey("doctors.id"), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("override_reason", sa.Text(), nullable=True),
    )
    op.create_table(
        "interactions",
        id_column(),
        sa.Column("ingredient_a", sa.CHAR(36), sa.ForeignKey("formulary.id"), nullable=False),
        sa.Column("ingredient_b", sa.CHAR(36), sa.ForeignKey("formulary.id"), nullable=False),
        sa.Column(
            "severity",
            sa.Enum("info", "warning", "severe", name="interaction_severity"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("management", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
    )
    op.create_table(
        "allergy_classes",
        id_column(),
        sa.Column("class_name", sa.Text(), nullable=False),
        sa.Column("member_ingredient_ids", sa.JSON(), nullable=False),
    )
    op.create_table(
        "audit_log",
        id_column(),
        sa.Column("actor_id", sa.CHAR(36), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.CHAR(36), nullable=False),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("at", sa.DateTime(), nullable=False),
    )

    for table in ("safety_events", "audit_log"):
        op.execute(
            f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
            "FOR EACH ROW SIGNAL SQLSTATE '45000' "
            f"SET MESSAGE_TEXT = '{table} is append-only'"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
            "FOR EACH ROW SIGNAL SQLSTATE '45000' "
            f"SET MESSAGE_TEXT = '{table} is append-only'"
        )


def downgrade() -> None:
    for table in ("safety_events", "audit_log"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete")

    for table in (
        "audit_log",
        "allergy_classes",
        "interactions",
        "safety_events",
        "prescription_items",
        "brand_catalog",
        "prescriptions",
        "transcripts",
        "encounters",
        "patient_allergies",
        "formulary",
        "patients",
        "doctors",
    ):
        op.drop_table(table)
