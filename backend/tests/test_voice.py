"""Hybrid voice workflow: short commands stage fields immediately, full dictation
stages one draft at Review, and the deterministic safety engine still decides."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app, get_session
from app.models import AuditLog, Base, SafetyEvent
from app.seed import load_reference_data


DOCTOR = {"name": "Dr Rao", "registration_no": "KMC-1234"}


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
        yield test_client, factory
    app.dependency_overrides.clear()


def command(http, utterance, draft=None):
    response = http.post(
        "/api/voice/command", json={"utterance": utterance, "draft": draft or {}}
    )
    assert response.status_code == 200, response.text
    return response.json()


def say(http, utterances):
    """Run a sequence of short commands, threading the staged draft through."""
    body = {}
    for utterance in utterances:
        body = command(http, utterance, body)["draft"]
    return body


def review(http, draft, doctor=DOCTOR):
    response = http.post("/api/voice/review", json={"draft": draft, "doctor": doctor})
    assert response.status_code == 200, response.text
    return response.json()


def test_partial_dictation_returns_valid_json_with_nullable_gaps(client):
    """1. Missing information never rejects the dictation; spoken fields still land."""
    http, _ = client

    response = http.post(
        "/api/voice/dictation",
        json={"text": "Patient name Ramesh Kumar, male, 42 years old. Diagnosis: acute pharyngitis."},
    )

    assert response.status_code == 200
    body = response.json()
    patient = body["draft"]["patient"]
    assert (patient["name"], patient["sex"], patient["age"]) == ("Ramesh Kumar", "male", 42)
    assert body["draft"]["diagnosis"] == "acute pharyngitis"
    assert body["draft"]["medicines"] == []
    assert patient["weight_kg"] is None and patient["contact"] is None
    assert "medicines" in body["missing_required"]
    assert body["staged"] is True and body["signed"] is False


def test_short_command_corrects_the_existing_staged_draft(client):
    """2. A correction command updates what is already staged, in place."""
    http, _ = client
    draft = say(
        http,
        [
            "Patient name Ramesh Kumar, male, 42 years old.",
            "Diagnosis: acute pharyngitis.",
            "Prescribe Mox 500, 500 mg, one capsule twice daily for 5 days after food.",
        ],
    )
    assert draft["medicines"][0]["duration"] == "5 days"
    assert draft["medicines"][0]["instructions"] == "after food"

    corrected = command(http, "Change duration to 7 days.", draft)
    assert corrected["applied"] == ["duration: 7 days"]
    assert corrected["draft"]["medicines"][0]["duration"] == "7 days"
    assert corrected["draft"]["medicines"][0]["dose"] == "1 capsule"

    emptied = command(http, "Remove last medicine.", corrected["draft"])
    assert emptied["draft"]["medicines"] == []
    assert emptied["applied"] == ["removed Mox 500"]


def test_full_dictation_is_reviewable_only_after_review_command(client):
    """3. Dictation stages; nothing is persisted until End / "Review prescription"."""
    http, factory = client

    dictated = http.post(
        "/api/voice/dictation",
        json={
            "text": (
                "Patient name Ramesh Kumar, male, 42 years old. Diagnosis: acute pharyngitis. "
                "Prescribe Mox 500, one capsule twice daily for 5 days after food."
            )
        },
    ).json()

    assert dictated["draft"]["medicines"][0]["brand"] == "Mox 500"
    assert dictated["missing_required"] == []
    assert "prescription_id" not in dictated
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 0

    asked = command(http, "Review prescription.", dictated["draft"])
    assert asked["action"] == "review"

    reviewed = review(http, asked["draft"])
    assert reviewed["ready"] is True
    assert reviewed["prescription_id"]
    assert reviewed["signed"] is False  # doctor still has to approve and sign
    assert reviewed["medicines"][0]["ingredient"] == "amoxicillin"  # safety runs on the generic
    with factory() as session:
        assert session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "prescription_drafted")
        ) == 1


def test_review_marks_required_gaps_instead_of_rejecting(client):
    http, factory = client
    draft = say(http, ["Prescribe Mox 500 twice daily."])

    result = review(http, draft)

    assert result["ready"] is False
    assert set(result["missing_required"]) == {
        "patient.name", "patient.sex", "diagnosis", "medicine 1.dose", "medicine 1.duration",
    }
    assert result["draft"]["medicines"][0]["brand"] == "Mox 500"  # nothing thrown away
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 0


def test_dose_above_range_warns_and_requires_acknowledgment_before_signing(client):
    """4. 1300 mg of paracetamol (2 x 650 mg tablets) is above the single-dose ceiling."""
    http, factory = client
    draft = say(
        http,
        [
            "Patient name Ramesh Kumar, male, 42 years old.",
            "Diagnosis: fever.",
            "Prescribe Dolo 650, two tablets twice daily for 3 days.",
        ],
    )

    reviewed = review(http, draft)

    assert reviewed["medicines"][0]["single_dose_mg"] == 1300.0
    warning = next(event for event in reviewed["safety_events"] if event["type"] == "dose")
    assert warning["severity"] == "severe"
    assert "1300 mg" in warning["message"]

    gated = http.post(
        f"/api/prescriptions/{reviewed['prescription_id']}/sign", json={
            "doctor_name": DOCTOR["name"], "registration_no": DOCTOR["registration_no"]
        }
    )
    assert gated.status_code == 409  # warned, not hard-blocked
    assert gated.json()["detail"] == "acknowledgment_required"

    http.post(
        f"/api/prescriptions/{reviewed['prescription_id']}/acknowledge",
        json={"event_ids": [warning["id"]], **{"doctor_name": DOCTOR["name"],
              "registration_no": DOCTOR["registration_no"]}, "reason": "Reviewed, splitting the dose"},
    )
    signed = http.post(
        f"/api/prescriptions/{reviewed['prescription_id']}/sign", json={
            "doctor_name": DOCTOR["name"], "registration_no": DOCTOR["registration_no"]
        }
    )
    assert signed.status_code == 200
    with factory() as session:
        logged = session.scalars(select(SafetyEvent)).all()
        assert [event.acknowledged for event in logged] == [False, True]  # both rows kept


def test_spoken_penicillin_allergy_warns_on_the_resolved_generic(client):
    """5. "Add penicillin allergy" + a brand of amoxicillin must flag the allergy class."""
    http, _ = client
    draft = say(
        http,
        [
            "Patient name Ramesh Kumar, male, 42 years old.",
            "Add penicillin allergy.",
            "Diagnosis: acute pharyngitis.",
            "Prescribe Mox 500, one capsule twice daily for 5 days.",
        ],
    )
    assert draft["patient"]["allergies"] == ["penicillins"]  # resolved via allergy_classes

    reviewed = review(http, draft)

    allergy = next(event for event in reviewed["safety_events"] if event["type"] == "allergy")
    assert allergy["severity"] == "severe"
    assert "amoxicillin" in allergy["message"]


def test_known_severe_interaction_warns(client):
    """6. warfarin + ibuprofen (spoken as a brand) is a severe interaction."""
    http, _ = client
    draft = say(
        http,
        [
            "Patient name Ramesh Kumar, male, 42 years old.",
            "Diagnosis: atrial fibrillation with back pain.",
            "Prescribe warfarin, 5 mg, one tablet once daily for 5 days.",
            "Prescribe Brufen 400, one tablet twice daily for 5 days.",
        ],
    )

    reviewed = review(http, draft)

    interaction = next(
        event for event in reviewed["safety_events"] if event["type"] == "interaction"
    )
    assert interaction["severity"] == "severe"
    assert "bleeding" in interaction["message"]
    assert {medicine["ingredient"] for medicine in reviewed["medicines"]} == {
        "warfarin", "ibuprofen",
    }


def test_medicine_outside_the_formulary_shows_manual_verification_not_a_pass(client):
    """7. Unknown drug: verify-manually warning, no ingredient, never a green tick."""
    http, _ = client
    draft = say(
        http,
        [
            "Patient name Ramesh Kumar, male, 42 years old.",
            "Diagnosis: acute pharyngitis.",
            "Prescribe Mysterymol, 250 mg, one tablet twice daily for 5 days.",
        ],
    )
    assert draft["medicines"][0]["generic"] == "Mysterymol"
    assert draft["medicines"][0]["brand"] is None  # never invented from a hardcoded list

    reviewed = review(http, draft)

    assert reviewed["medicines"][0]["ingredient"] is None
    uncovered = next(event for event in reviewed["safety_events"] if event["type"] == "uncovered")
    assert uncovered["message"] == "Not in safety database — verify manually."
    assert uncovered["acknowledged"] is False


def test_identifiers_never_reach_the_extraction_prompt(client, monkeypatch):
    import app.voice as voice

    seen = {}

    class CapturingLLM:
        def extract_prescription(self, clinical_text, mode):
            seen["text"] = clinical_text
            from app.providers import PrescriptionDraft

            return PrescriptionDraft()

    monkeypatch.setattr(voice, "get_llm_provider", lambda **kwargs: CapturingLLM())
    http, _ = client

    body = http.post(
        "/api/voice/dictation",
        json={
            "draft": {"patient": {"name": "Ramesh Kumar", "patient_id": "OPD-7", "contact": "9999999999"}},
            "text": "Ramesh Kumar OPD-7 9999999999 has acute pharyngitis.",
        },
    ).json()

    assert "Ramesh Kumar" not in seen["text"]
    assert "OPD-7" not in seen["text"] and "9999999999" not in seen["text"]
    assert body["draft"]["patient"]["name"] == "Ramesh Kumar"  # re-attached locally
