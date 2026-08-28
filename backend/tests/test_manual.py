from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app, get_session
from app.models import AuditLog, Base, Prescription, SafetyEvent
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

    monkeypatch.setenv("DRUGKNOWLEDGE_BACKEND", "curated")
    monkeypatch.setenv("PDF_DIR", str(tmp_path))
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client, factory, tmp_path
    app.dependency_overrides.clear()


DOCTOR = {"name": "Dr Rao", "registration_no": "KMC-1234"}
SIGN = {"doctor_name": "Dr Rao", "registration_no": "KMC-1234"}


def patient(**overrides):
    base = {
        "name": "Anita Sharma",
        "patient_id": "OPD-101",
        "age": 28,
        "sex": "female",
        "weight_kg": 58,
        "contact": "9999999999",
        "allergies": [],
    }
    base.update(overrides)
    return base


def manual_payload(medicines, *, diagnosis="fever", pat=None):
    return {
        "diagnosis": diagnosis,
        "patient": pat or patient(),
        "doctor": DOCTOR,
        "medicines": medicines,
    }


def med(**overrides):
    base = {
        "brand": None,
        "generic": None,
        "strength": None,
        "form": None,
        "route": "oral",
        "dose": None,
        "frequency": None,
        "duration": None,
        "instructions": None,
    }
    base.update(overrides)
    return base


def dose_events(draft):
    return [event for event in draft["safety_events"] if event["type"] == "dose"]


def test_manual_dolo_one_tablet_twice_daily_resolves_generic_and_is_safe(client):
    http, _, _ = client
    response = http.post(
        "/api/manual/draft",
        json=manual_payload(
            [med(brand="Dolo-650", strength="650 mg", form="tablet",
                 dose="1 tablet", frequency="twice daily", duration="3 days")]
        ),
    )
    assert response.status_code == 200
    draft = response.json()
    medicine = draft["medicines"][0]
    assert medicine["ingredient"] == "paracetamol"
    assert medicine["brand"] == "Dolo-650"
    assert medicine["single_dose_mg"] == 650.0
    assert medicine["daily_dose_mg"] == 1300.0
    assert dose_events(draft) == []


def test_manual_dolo_two_tablets_flags_single_dose_daily_separate(client):
    http, _, _ = client
    response = http.post(
        "/api/manual/draft",
        json=manual_payload(
            [med(brand="Dolo-650", strength="650 mg", form="tablet",
                 dose="2 tablets", frequency="twice daily", duration="3 days")]
        ),
    )
    assert response.status_code == 200
    draft = response.json()
    medicine = draft["medicines"][0]
    assert medicine["single_dose_mg"] == 1300.0
    assert medicine["daily_dose_mg"] == 2600.0
    events = dose_events(draft)
    assert len(events) == 1
    assert events[0]["severity"] == "severe"
    assert "per dose" in events[0]["message"]


def test_manual_explicit_mg_flags_single_and_daily(client):
    http, _, _ = client
    response = http.post(
        "/api/manual/draft",
        json=manual_payload(
            [med(brand="Dolo-650", strength="650 mg", form="tablet",
                 dose="21000 mg", frequency="twice daily", duration="3 days")]
        ),
    )
    assert response.status_code == 200
    draft = response.json()
    medicine = draft["medicines"][0]
    assert medicine["single_dose_mg"] == 21000.0
    assert medicine["daily_dose_mg"] == 42000.0
    events = dose_events(draft)
    assert len(events) == 2
    assert all(event["severity"] == "severe" for event in events)
    messages = " ".join(event["message"] for event in events)
    assert "per dose" in messages
    assert "per day" in messages


def test_manual_penicillin_allergy_amoxicillin_flags_class_allergy(client):
    http, _, _ = client
    response = http.post(
        "/api/manual/draft",
        json=manual_payload(
            [med(generic="amoxicillin", strength="500 mg", form="capsule",
                 dose="1 capsule", frequency="thrice daily", duration="5 days")],
            pat=patient(allergies=["penicillins"]),
        ),
    )
    assert response.status_code == 200
    draft = response.json()
    allergy = [event for event in draft["safety_events"] if event["type"] == "allergy"]
    assert len(allergy) == 1
    assert allergy[0]["severity"] == "severe"
    assert draft["medicines"][0]["ingredient"] == "amoxicillin"


def test_manual_warfarin_and_ibuprofen_flags_interaction(client):
    http, _, _ = client
    response = http.post(
        "/api/manual/draft",
        json=manual_payload(
            [
                med(generic="warfarin", strength="5 mg", form="tablet",
                    dose="1 tablet", frequency="once daily", duration="7 days"),
                med(generic="ibuprofen", strength="400 mg", form="tablet",
                    dose="1 tablet", frequency="twice daily", duration="3 days"),
            ]
        ),
    )
    assert response.status_code == 200
    draft = response.json()
    interaction = [event for event in draft["safety_events"] if event["type"] == "interaction"]
    assert len(interaction) == 1
    assert interaction[0]["severity"] == "severe"


def test_manual_uncovered_medicine_shows_verify_manually_never_passes(client):
    http, _, _ = client
    response = http.post(
        "/api/manual/draft",
        json=manual_payload(
            [med(generic="aspirin", strength="75 mg", form="tablet",
                 dose="1 tablet", frequency="once daily", duration="30 days")]
        ),
    )
    assert response.status_code == 200
    draft = response.json()
    uncovered = [event for event in draft["safety_events"] if event["type"] == "uncovered"]
    assert len(uncovered) == 1
    assert uncovered[0]["message"] == "Not in safety database — verify manually."
    # No false green pass: the medicine is not resolved to a formulary ingredient.
    assert draft["medicines"][0]["ingredient"] != "aspirin" or draft["medicines"][0]["ingredient"] is None


def test_manual_unacknowledged_warning_gates_then_signs(client):
    http, factory, _ = client
    draft = http.post(
        "/api/manual/draft",
        json=manual_payload(
            [med(brand="Dolo-650", strength="650 mg", form="tablet",
                 dose="2 tablets", frequency="twice daily", duration="3 days")]
        ),
    ).json()
    warning = draft["safety_events"][0]

    gated = http.post(
        f"/api/prescriptions/{draft['prescription_id']}/sign",
        json=SIGN,
    )
    assert gated.status_code == 409
    assert gated.json()["detail"] == "acknowledgment_required"

    acknowledged = http.post(
        f"/api/prescriptions/{draft['prescription_id']}/acknowledge",
        json={
            "event_ids": [warning["id"]],
            "doctor_name": DOCTOR["name"],
            "registration_no": DOCTOR["registration_no"],
            "reason": "Clinical judgment after review",
        },
    )
    assert acknowledged.status_code == 200

    signed = http.post(
        f"/api/prescriptions/{draft['prescription_id']}/sign",
        json=SIGN,
    )
    assert signed.status_code == 200

    with factory() as session:
        events = session.scalars(select(SafetyEvent)).all()
        assert [event.acknowledged for event in events] == [False, True]


def test_manual_signed_prescription_is_immutable(client):
    http, factory, pdf_dir = client
    draft = http.post(
        "/api/manual/draft",
        json=manual_payload(
            [med(brand="Dolo-650", strength="650 mg", form="tablet",
                 dose="1 tablet", frequency="twice daily", duration="3 days")]
        ),
    ).json()

    signed = http.post(f"/api/prescriptions/{draft['prescription_id']}/sign", json=SIGN)
    assert signed.status_code == 200
    assert list(Path(pdf_dir).glob("*.pdf"))

    # Re-signing a locked prescription is refused.
    assert http.post(
        f"/api/prescriptions/{draft['prescription_id']}/sign", json=SIGN
    ).status_code == 409

    with factory() as session:
        prescription = session.get(Prescription, draft["prescription_id"])
        assert (prescription.status, prescription.locked) == ("signed", True)
        assert session.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.action == "prescription_signed"
            )
        ) == 1


def test_catalog_lists_seeded_brands_and_generics_without_hardcoding(client):
    http, _, _ = client
    response = http.get("/api/catalog")
    assert response.status_code == 200
    catalog = response.json()
    brand_names = {brand["brand_name"] for brand in catalog["brands"]}
    assert "Dolo-650" in brand_names
    dolo = next(brand for brand in catalog["brands"] if brand["brand_name"] == "Dolo-650")
    assert dolo["ingredient"] == "paracetamol"
    assert "amoxicillin" in set(catalog["generics"])


def test_manual_rejects_medicine_without_brand_or_generic(client):
    http, _, _ = client
    response = http.post("/api/manual/draft", json=manual_payload([med(dose="1 tablet")]))
    assert response.status_code == 422
