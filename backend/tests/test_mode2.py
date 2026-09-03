from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app, get_session
import app.mode2 as mode2_module
from app.mode2 import PatientInput, minimize_clinical_text
from app.models import AuditLog, Base, Encounter, Prescription, PrescriptionItem, SafetyEvent
from app.providers import Transcript
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


def test_audio_dictation_uses_stt_then_normal_extraction_path(client):
    http, _, _ = client
    payload = draft_payload("ignored client text")
    response = http.post(
        "/api/mode2/audio-draft",
        data={"patient": __import__("json").dumps(payload["patient"]), "doctor": __import__("json").dumps(payload["doctor"])},
        files={"audio": ("dictation.wav", b"patient has a headache, give Dolo 650, twice daily for 3 days", "audio/wav")},
    )

    assert response.status_code == 200
    draft = response.json()
    assert draft["diagnosis"] == "headache"
    assert draft["medicines"][0]["brand"] == "Dolo-650"
    assert draft["medicines"][0]["ingredient"] == "paracetamol"


def test_audio_dictation_forwards_browser_mime_type_to_stt(client, monkeypatch):
    http, _, _ = client
    received = {}

    class CapturingSTT:
        def transcribe(self, audio, content_type=None):
            received.update(audio=audio, content_type=content_type)
            return Transcript("patient has a headache, give Dolo 650, twice daily for 3 days")

    monkeypatch.setattr(mode2_module, "get_stt_provider", lambda session: CapturingSTT())
    payload = draft_payload("ignored client text")
    response = http.post(
        "/api/mode2/audio-draft",
        data={"patient": __import__("json").dumps(payload["patient"]), "doctor": __import__("json").dumps(payload["doctor"])},
        files={"audio": ("dictation.webm", b"webm audio", "audio/webm")},
    )

    assert response.status_code == 200
    assert received == {"audio": b"webm audio", "content_type": "audio/webm"}


def test_editing_staged_draft_persists_rechecks_and_audits(client):
    http, factory, _ = client
    draft = http.post(
        "/api/mode2/draft", json=draft_payload("give Dolo 650 as 1300 mg once daily")
    ).json()
    assert any(event["type"] == "dose" for event in draft["safety_events"])

    edited = http.patch(
        f"/api/prescriptions/{draft['prescription_id']}/draft",
        json={
            "diagnosis": "headache",
            "medicines": [{
                "id": draft["medicines"][0]["id"],
                "brand": "Dolo-650",
                "generic": "paracetamol",
                "strength": "650 mg",
                "form": "tablet",
                "route": "oral",
                "dose": "1 tablet",
                "frequency": "twice daily",
                "duration": "3 days",
                "instructions": "Take after food",
            }],
        },
    )

    assert edited.status_code == 200
    result = edited.json()
    assert result["safety_events"] == []
    assert result["medicines"][0]["dose"] == "1 tablet"
    with factory() as session:
        item = session.get(PrescriptionItem, draft["medicines"][0]["id"])
        assert item.dose == "1 tablet"
        assert session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "prescription_edited")
        ) == 1


def test_edit_reintroducing_same_warning_requires_new_acknowledgment(client):
    http, _, _ = client
    draft = http.post(
        "/api/mode2/draft", json=draft_payload("give Dolo 650 as 1300 mg once daily")
    ).json()
    warning = draft["safety_events"][0]
    http.post(
        f"/api/prescriptions/{draft['prescription_id']}/acknowledge",
        json={"event_ids": [warning["id"]], "doctor_name": "Dr Rao", "registration_no": "KMC-1234", "reason": "Reviewed"},
    )
    edited = http.patch(
        f"/api/prescriptions/{draft['prescription_id']}/draft",
        json={"diagnosis": "headache", "medicines": [{
            "id": draft["medicines"][0]["id"], "brand": "Dolo-650", "generic": "paracetamol",
            "strength": "650 mg", "form": "tablet", "route": "oral", "dose": "1300 mg",
            "frequency": "once daily", "duration": "3 days",
        }]},
    )
    assert edited.status_code == 200
    assert len([event for event in edited.json()["safety_events"] if not event["acknowledged"]]) == 1


def test_uncovered_medicine_is_retained_in_signed_pdf(client):
    http, _, _ = client
    payload = draft_payload("prescribe an unknown medicine")
    response = http.post(
        "/api/manual/draft",
        json={
            "diagnosis": "unknown condition",
            "patient": payload["patient"],
            "doctor": payload["doctor"],
            "medicines": [{"generic": "Mysterymol", "dose": "1 tablet", "frequency": "once daily", "duration": "3 days"}],
        },
    )
    assert response.status_code == 200
    draft = response.json()
    assert draft["medicines"][0]["ingredient"] is None
    signed = http.post(
        f"/api/prescriptions/{draft['prescription_id']}/sign",
        json={"doctor_name": "Dr Rao", "registration_no": "KMC-1234"},
    )
    assert signed.status_code == 409
    warning = draft["safety_events"][0]
    http.post(
        f"/api/prescriptions/{draft['prescription_id']}/acknowledge",
        json={"event_ids": [warning["id"]], "doctor_name": "Dr Rao", "registration_no": "KMC-1234", "reason": "Verified manually"},
    )
    signed = http.post(
        f"/api/prescriptions/{draft['prescription_id']}/sign",
        json={"doctor_name": "Dr Rao", "registration_no": "KMC-1234"},
    )
    assert signed.status_code == 200
    pdf = http.get(signed.json()["pdf_url"])
    assert b"Mysterymol" in pdf.content
