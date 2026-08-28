from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app, get_session
from app.mode2 import PatientInput, minimize_clinical_text
from app.models import AuditLog, Base, Encounter, Prescription, SafetyEvent
from app.seed import load_reference_data


@pytest.fixture
def client(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as session:
        load_reference_data(session)

    def override_session():
        with factory() as session:
            yield session

    monkeypatch.setenv("STT_BACKEND", "fake")
    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.setenv("DRUGKNOWLEDGE_BACKEND", "curated")
    monkeypatch.setenv("PDF_DIR", str(tmp_path))
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client, factory, tmp_path
    app.dependency_overrides.clear()


def draft_payload(text):
    return {
        "text": text,
        "patient": {
            "name": "Anita Sharma",
            "patient_id": "OPD-101",
            "age": 28,
            "sex": "female",
            "weight_kg": 58,
            "contact": "9999999999",
        },
        "doctor": {"name": "Dr Rao", "registration_no": "KMC-1234"},
    }


def test_known_patient_identifiers_are_removed_from_clinical_text():
    patient = PatientInput(
        name="Anita Sharma",
        patient_id="OPD-101",
        age=28,
        sex="female",
        weight_kg=58,
        contact="9999999999",
    )

    minimized = minimize_clinical_text(
        "Anita Sharma OPD-101 9999999999 has a headache", patient
    )

    assert minimized == "[redacted] [redacted] [redacted] has a headache"


def test_example_dictation_fills_safe_generic_draft_and_signs_locked_pdf(client):
    http, factory, pdf_dir = client

    response = http.post(
        "/api/mode2/draft",
        json=draft_payload(
            "patient has a headache, give Dolo 650, twice daily for 3 days"
        ),
    )

    assert response.status_code == 200
    draft = response.json()
    assert draft["diagnosis"] == "headache"
    assert draft["patient"]["name"] == "Anita Sharma"
    assert draft["medicines"] == [
        {
            "id": draft["medicines"][0]["id"],
            "brand": "Dolo-650",
            "ingredient": "paracetamol",
            "strength": "650 mg",
            "form": "tablet",
            "route": "oral",
            "dose": "1 tablet",
            "frequency": "twice daily",
            "duration": "3 days",
            "instructions": None,
            "single_dose_mg": 650.0,
            "daily_dose_mg": 1300.0,
        }
    ]
    assert draft["safety_events"] == []

    signed = http.post(
        f"/api/prescriptions/{draft['prescription_id']}/sign",
        json={"doctor_name": "Dr Rao", "registration_no": "KMC-1234"},
    )

    assert signed.status_code == 200
    result = signed.json()
    assert result["signed"] is True
    pdf = http.get(result["pdf_url"])
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF-")
    assert list(Path(pdf_dir).glob("*.pdf"))

    with factory() as session:
        prescription = session.get(Prescription, draft["prescription_id"])
        encounter = session.get(Encounter, draft["encounter_id"])
        assert (prescription.status, prescription.locked, encounter.status) == (
            "signed",
            True,
            "signed",
        )
        assert session.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.action == "prescription_signed"
            )
        ) == 1

    assert http.post(
        f"/api/prescriptions/{draft['prescription_id']}/sign",
        json={"doctor_name": "Dr Rao", "registration_no": "KMC-1234"},
    ).status_code == 409


def test_unacknowledged_warning_opens_gate_then_append_only_ack_allows_signing(client):
    http, factory, _ = client
    draft = http.post(
        "/api/mode2/draft",
        json=draft_payload("give Dolo 650 as 1300 mg once daily"),
    ).json()
    warning = draft["safety_events"][0]
    assert (warning["type"], warning["severity"], warning["acknowledged"]) == (
        "dose",
        "severe",
        False,
    )

    gated = http.post(
        f"/api/prescriptions/{draft['prescription_id']}/sign",
        json={"doctor_name": "Dr Rao", "registration_no": "KMC-1234"},
    )
    assert gated.status_code == 409
    assert gated.json()["detail"] == "acknowledgment_required"

    acknowledged = http.post(
        f"/api/prescriptions/{draft['prescription_id']}/acknowledge",
        json={
            "event_ids": [warning["id"]],
            "doctor_name": "Dr Rao",
            "registration_no": "KMC-1234",
            "reason": "Clinical judgment after review",
        },
    )
    assert acknowledged.status_code == 200
    acknowledged_event = acknowledged.json()["safety_events"][0]
    assert acknowledged_event["acknowledged"] is True
    assert acknowledged_event["acknowledged_by"] == "Dr Rao"
    assert acknowledged_event["acknowledged_reason"] == "Clinical judgment after review"
    assert acknowledged_event["acknowledged_at"].endswith("Z")

    signed = http.post(
        f"/api/prescriptions/{draft['prescription_id']}/sign",
        json={"doctor_name": "Dr Rao", "registration_no": "KMC-1234"},
    )
    assert signed.status_code == 200

    with factory() as session:
        events = session.scalars(select(SafetyEvent)).all()
        assert len(events) == 2
        assert [event.acknowledged for event in events] == [False, True]


@pytest.mark.parametrize(
    ("text", "single_mg", "daily_mg"),
    [
        (
            "Patient has a headache. Prescribe Dolo 650, one tablet of 10300 mg twice daily for 3 days.",
            10300.0,
            20600.0,
        ),
        (
            "Patient has a headache. Prescribe Dolo 650, 21000 mg twice daily for 3 days.",
            21000.0,
            42000.0,
        ),
    ],
)
def test_explicit_mg_without_as_reaches_single_and_daily_safety_checks(
    client, text, single_mg, daily_mg
):
    http, _, _ = client

    response = http.post("/api/mode2/draft", json=draft_payload(text))

    assert response.status_code == 200
    draft = response.json()
    assert draft["medicines"][0]["single_dose_mg"] == single_mg
    assert draft["medicines"][0]["daily_dose_mg"] == daily_mg
    dose_events = [event for event in draft["safety_events"] if event["type"] == "dose"]
    assert len(dose_events) == 2
    assert all(event["severity"] == "severe" for event in dose_events)
    messages = " ".join(event["message"] for event in dose_events)
    assert "per dose" in messages
    assert "per day" in messages


def test_tablet_count_multiplies_catalog_strength_before_safety(client):
    http, _, _ = client

    response = http.post(
        "/api/mode2/draft",
        json=draft_payload(
            "Patient has a headache. Prescribe Dolo 650, take 2 tablets twice daily for 3 days."
        ),
    )

    assert response.status_code == 200
    draft = response.json()
    assert draft["medicines"][0]["single_dose_mg"] == 1300.0
    assert draft["medicines"][0]["daily_dose_mg"] == 2600.0
    dose_events = [event for event in draft["safety_events"] if event["type"] == "dose"]
    assert len(dose_events) == 1
    assert dose_events[0]["severity"] == "severe"
