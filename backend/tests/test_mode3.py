import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app, get_session
import app.mode2 as mode2_module
from app.models import Base, Encounter, Transcript as TranscriptRow
from app.seed import load_reference_data


@pytest.fixture
def client(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
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


def consent_payload(consent=True):
    return {
        "patient": {
            "name": "Anita Sharma",
            "patient_id": "OPD-101",
            "age": 28,
            "sex": "female",
            "weight_kg": 58,
            "contact": "9999999999",
        },
        "doctor": {"name": "Dr Rao", "registration_no": "KMC-1234"},
        "consent": consent,
    }


def stream_conversation(http, encounter_id, lines):
    segments = []
    with http.websocket_connect(f"/api/mode3/encounters/{encounter_id}/stream") as ws:
        for line in lines:
            ws.send_text(line)
            segments.append(ws.receive_json()["segment"])
    return segments


def test_consent_is_required_before_an_ambient_encounter_starts(client):
    http, factory, _ = client

    denied = http.post("/api/mode3/consent", json=consent_payload(consent=False))
    assert denied.status_code == 422
    with factory() as session:
        assert session.scalar(select(Encounter)) is None  # nothing recorded without consent

    granted = http.post("/api/mode3/consent", json=consent_payload())
    assert granted.status_code == 200
    body = granted.json()
    assert body["recording_consent"] is True
    assert body["consent_at"].endswith("Z")
    with factory() as session:
        encounter = session.get(Encounter, body["encounter_id"])
        assert (encounter.mode, encounter.recording_consent) == ("ambient", True)
        assert encounter.consent_at is not None


def test_stream_refuses_without_a_consented_encounter(client):
    http, _, _ = client
    with http.websocket_connect("/api/mode3/encounters/does-not-exist/stream") as ws:
        assert ws.receive_json() == {"error": "consent_required"}


def test_consented_mock_conversation_streams_diarized_then_signs_linked_draft(client):
    http, factory, _ = client
    encounter_id = http.post("/api/mode3/consent", json=consent_payload()).json()["encounter_id"]

    segments = stream_conversation(
        http,
        encounter_id,
        [
            "Patient: I've had a headache since this morning.",
            "Doctor: Let's start you on Dolo 650, twice daily for 3 days.",
        ],
    )
    assert [seg["speaker"] for seg in segments] == ["Patient", "Doctor"]
    assert "Dolo-650" in segments[1]["text"]  # drug-name post-correction ran on STT output

    draft = http.post(f"/api/mode3/encounters/{encounter_id}/end").json()
    assert draft["diagnosis"] == "headache"
    assert draft["coverage"]["label"] == "1 of 1 linked"
    medicine = draft["medicines"][0]
    assert (medicine["brand"], medicine["ingredient"]) == ("Dolo-650", "paracetamol")
    assert medicine["evidence_status"] == "linked"
    assert medicine["evidence_segment_ids"] == [segments[1]["id"]]
    assert draft["safety_events"] == []

    signed = http.post(
        f"/api/prescriptions/{draft['prescription_id']}/sign",
        json={"doctor_name": "Dr Rao", "registration_no": "KMC-1234"},
    )
    assert signed.status_code == 200
    with factory() as session:
        transcript = session.scalar(
            select(TranscriptRow).where(TranscriptRow.encounter_id == encounter_id)
        )
        assert len(transcript.segments) == 2
        assert session.get(Encounter, encounter_id).status == "signed"


def test_unlinked_medicine_is_flagged_missing_context(client, monkeypatch):
    http, _, _ = client
    encounter_id = http.post("/api/mode3/consent", json=consent_payload()).json()["encounter_id"]
    stream_conversation(http, encounter_id, ["Doctor: Start Dolo 650 twice daily for 3 days."])

    real_ambient_draft = mode2_module._ambient_draft

    def draft_with_uninferred_medicine(segments, session):
        draft = real_ambient_draft(segments, session)  # Dolo, spoken -> will link
        draft["medicines"].append(  # a med the model inferred but never appears in the transcript
            {
                "ingredient": None, "brand": "Mox 500", "strength": "500 mg", "form": "capsule",
                "route": "oral", "dose": "1 capsule", "frequency": "twice daily",
                "duration": "5 days", "instructions": None, "evidence_segment_ids": [],
            }
        )
        return draft

    monkeypatch.setattr(mode2_module, "_ambient_draft", draft_with_uninferred_medicine)

    draft = http.post(f"/api/mode3/encounters/{encounter_id}/end").json()
    assert draft["coverage"] == {
        "total": 2, "linked": 1, "missing": 1, "label": "1 of 2 linked · 1 missing context",
    }
    by_brand = {med["brand"]: med for med in draft["medicines"]}
    assert by_brand["Dolo-650"]["evidence_status"] == "linked"
    assert by_brand["Mox 500"]["evidence_status"] == "missing_context"
    assert by_brand["Mox 500"]["evidence_segment_ids"] == []
