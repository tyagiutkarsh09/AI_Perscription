from dataclasses import FrozenInstanceError

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base
from app.seed import load_reference_data
from app.providers import (
    CuratedDrugKnowledge,
    DeepgramSTT,
    FakeLLM,
    FakeSTT,
    Ingredient,
    LLMProvider,
    OpenAILLM,
    STTProvider,
    Transcript,
    UncoveredResult,
    build_providers,
    strip_pii,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        load_reference_data(db)
        db.commit()
        yield db


def test_provider_protocols_and_result_records_are_immutable():
    assert isinstance(FakeSTT({b"audio": "headache"}), STTProvider)
    assert isinstance(FakeLLM({"headache": {"diagnosis": "headache"}}), LLMProvider)
    with pytest.raises(FrozenInstanceError):
        Ingredient(id="x", name="paracetamol", atc_class=None, covered=True).name = "x"


def test_curated_provider_resolves_brand_and_queries_safety_by_generic(session):
    provider = CuratedDrugKnowledge(session)

    ingredient = provider.resolve_brand("Dolo-650")
    assert ingredient.name == "paracetamol"
    assert ingredient.covered is True
    assert provider.dose_limits(ingredient, age=30, weight=70).max_single_dose == 1000


def test_curated_provider_reports_uncovered_without_false_pass(session):
    provider = CuratedDrugKnowledge(session)

    result = provider.resolve_brand("unknown brand")
    assert isinstance(result, UncoveredResult)
    assert result.covered is False
    assert result.message == "Not in safety database — verify manually."
    assert provider.dose_limits("not-a-generic", age=30, weight=70).covered is False
    assert provider.dose_limits(Ingredient("missing", "missing"), age=30, weight=70).covered is False


def test_curated_provider_finds_interaction_and_allergy_conflict_by_ingredient(session):
    provider = CuratedDrugKnowledge(session)
    warfarin = provider.ingredient("warfarin")
    ibuprofen = provider.ingredient("ibuprofen")
    amoxicillin = provider.ingredient("amoxicillin")

    interactions = provider.interactions([warfarin, ibuprofen])
    assert interactions[0].severity == "severe"
    conflicts = provider.allergy_conflicts([amoxicillin], ["penicillins"])
    assert conflicts[0].class_name == "penicillins"


def test_fake_providers_are_fixed_and_structured():
    stt = FakeSTT({b"audio": "clinical text"})
    assert stt.transcribe(b"audio").text == "clinical text"
    assert list(stt.stream(b"audio"))[0].text == "clinical text"

    draft = {"diagnosis": "viral fever", "medicines": []}
    llm = FakeLLM({"clinical text": draft})
    assert llm.extract_prescription("clinical text", "voice").diagnosis == "viral fever"


def test_strip_pii_removes_identity_fields():
    payload = {"patient_name": "Anita", "patient_id": "p-1", "contact": "9999", "clinical_text": "fever"}
    assert strip_pii(payload) == {"clinical_text": "fever"}


def test_strip_pii_redacts_labeled_identity_from_text():
    assert strip_pii("Patient name: Anita; patient ID: p-1; contact: 9999; fever") == "fever"


def test_openai_uses_strict_schema_and_sends_only_clinical_text():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"diagnosis":"fever","medicines":[]}'}}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    llm = OpenAILLM(api_key="test", client=client)
    draft = llm.extract_prescription(
        {"patient_name": "Anita", "patient_id": "p-1", "contact": "9999", "clinical_text": "fever"},
        "voice",
    )
    body = requests[0].read().decode()
    assert draft.diagnosis == "fever"
    assert "Anita" not in body and "p-1" not in body and "9999" not in body
    assert '"type":"json_schema"' in body
    assert '"strict":true' in body
    client.close()


def test_deepgram_transcribe_uses_http_adapter():
    def handler(request):
        assert request.headers["Authorization"] == "Token test"
        return httpx.Response(200, json={"results": {"channels": [{"alternatives": [{"transcript": "fever"}]}]}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    stt = DeepgramSTT(api_key="test", client=client)
    assert stt.transcribe(b"audio").text == "fever"
    client.close()


def test_deepgram_transcribe_forwards_audio_content_type():
    def handler(request):
        assert request.headers["Content-Type"] == "audio/webm"
        return httpx.Response(200, json={"results": {"channels": [{"alternatives": [{"transcript": "fever"}]}]}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    stt = DeepgramSTT(api_key="test", client=client)
    assert stt.transcribe(b"audio", "audio/webm").text == "fever"
    client.close()


def test_build_providers_uses_environment_selectors(monkeypatch, session):
    monkeypatch.setenv("STT_BACKEND", "fake")
    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.setenv("DRUGKNOWLEDGE_BACKEND", "curated")
    providers = build_providers(session, fake_stt={b"x": "ok"}, fake_llm={"ok": {"medicines": []}})
    assert isinstance(providers["stt"], FakeSTT)
    assert isinstance(providers["llm"], FakeLLM)
    assert isinstance(providers["drugknowledge"], CuratedDrugKnowledge)
