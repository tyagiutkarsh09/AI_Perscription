from sqlalchemy import CHAR, JSON

from app.models import Base


EXPECTED_TABLES = {
    "doctors",
    "patients",
    "patient_allergies",
    "encounters",
    "transcripts",
    "prescriptions",
    "prescription_items",
    "safety_events",
    "formulary",
    "brand_catalog",
    "interactions",
    "allergy_classes",
    "audit_log",
}


def test_models_match_architecture_section_6_invariants():
    assert set(Base.metadata.tables) == EXPECTED_TABLES
    assert all(
        isinstance(table.c.id.type, CHAR) and table.c.id.type.length == 36
        for table in Base.metadata.tables.values()
    )

    json_columns = {
        (table.name, column.name)
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, JSON)
    }
    assert json_columns == {
        ("doctors", "preferences"),
        ("transcripts", "segments"),
        ("prescription_items", "evidence_segment_ids"),
        ("formulary", "forms"),
        ("allergy_classes", "member_ingredient_ids"),
        ("audit_log", "before"),
        ("audit_log", "after"),
    }
