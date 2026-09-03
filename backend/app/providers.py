"""Swappable STT, extraction, and drug-knowledge providers."""

from __future__ import annotations

import difflib
import json
import os
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterator, Mapping, Protocol, runtime_checkable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AllergyClass, BrandCatalog, Formulary, Interaction


UNCOVERED_MESSAGE = "Not in safety database — verify manually."


@dataclass(frozen=True)
class TranscriptChunk:
    text: str
    speaker: str | None = None
    start: float | None = None
    end: float | None = None


@dataclass(frozen=True)
class Transcript:
    text: str
    chunks: tuple[TranscriptChunk, ...] = ()


@dataclass(frozen=True)
class Ingredient:
    id: str | None
    name: str | None
    atc_class: str | None = None
    covered: bool = True
    message: str | None = None


@dataclass(frozen=True)
class UncoveredResult:
    query: str
    covered: bool = False
    message: str = UNCOVERED_MESSAGE


@dataclass(frozen=True)
class DoseRule:
    ingredient: str
    max_single_dose: Decimal | None = None
    max_daily_dose: Decimal | None = None
    mg_per_kg: Decimal | None = None
    min_age: int | None = None
    max_age: int | None = None
    covered: bool = True
    message: str | None = None


@dataclass(frozen=True)
class InteractionResult:
    ingredient_a: str
    ingredient_b: str
    severity: str
    description: str
    management: str
    covered: bool = True


@dataclass(frozen=True)
class AllergyConflict:
    ingredient: str
    class_name: str
    message: str
    covered: bool = True


@dataclass(frozen=True)
class MedicineDraft:
    ingredient: str | None = None
    brand: str | None = None
    strength: str | None = None
    form: str | None = None
    route: str | None = None
    dose: str | None = None
    frequency: str | None = None
    duration: str | None = None
    instructions: str | None = None
    evidence_segment_ids: tuple[str, ...] = ()
    id: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MedicineDraft":
        return cls(
            id=value.get("id"),
            ingredient=value.get("ingredient"),
            brand=value.get("brand"),
            strength=value.get("strength"),
            form=value.get("form"),
            route=value.get("route"),
            dose=value.get("dose"),
            frequency=value.get("frequency"),
            duration=value.get("duration"),
            instructions=value.get("instructions"),
            evidence_segment_ids=tuple(value.get("evidence_segment_ids") or ()),
        )


@dataclass(frozen=True)
class PrescriptionDraft:
    diagnosis: str | None = None
    patient_facts: Mapping[str, Any] = field(default_factory=dict)
    medicines: tuple[MedicineDraft, ...] = ()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PrescriptionDraft":
        medicines = tuple(
            medicine if isinstance(medicine, MedicineDraft) else MedicineDraft.from_dict(medicine)
            for medicine in value.get("medicines", ())
        )
        return cls(
            diagnosis=value.get("diagnosis"),
            patient_facts=value.get("patient_facts") or {},
            medicines=medicines,
        )


@runtime_checkable
class STTProvider(Protocol):
    def stream(self, audio: bytes) -> Iterator[TranscriptChunk]: ...

    def transcribe(self, audio_file: bytes, content_type: str = "audio/wav") -> Transcript: ...


@runtime_checkable
class LLMProvider(Protocol):
    def extract_prescription(self, clinical_text: Any, mode: str) -> PrescriptionDraft: ...


@runtime_checkable
class DrugKnowledgeProvider(Protocol):
    def resolve_brand(self, brand: str) -> Ingredient | UncoveredResult: ...

    def dose_limits(self, ingredient: Ingredient | str, age: int | None, weight: float | None) -> DoseRule: ...

    def interactions(self, ingredients: list[Ingredient | str]) -> list[InteractionResult | UncoveredResult]: ...

    def allergy_conflicts(
        self, ingredients: list[Ingredient | str], allergies: list[Any]
    ) -> list[AllergyConflict | UncoveredResult]: ...


def _uncovered(query: str) -> UncoveredResult:
    return UncoveredResult(query=query)


class CuratedDrugKnowledge:
    """Safety lookups over the local, bounded formulary."""

    def __init__(self, session: Session):
        self.session = session

    def ingredient(self, name: str) -> Ingredient | UncoveredResult:
        row = self.session.scalar(
            select(Formulary).where(Formulary.ingredient_name.ilike(name))
        )
        if row is None:
            return _uncovered(name)
        return Ingredient(row.id, row.ingredient_name, row.atc_class)

    def resolve_brand(self, brand: str) -> Ingredient | UncoveredResult:
        row = self.session.scalar(
            select(BrandCatalog).where(BrandCatalog.brand_name.ilike(brand))
        )
        if row is None:
            return _uncovered(brand)
        formulary = self.session.get(Formulary, row.ingredient_id)
        if formulary is None:
            return _uncovered(brand)
        return Ingredient(formulary.id, formulary.ingredient_name, formulary.atc_class)

    def _coerce(self, value: Ingredient | str) -> Ingredient | UncoveredResult:
        if isinstance(value, Ingredient) or isinstance(value, UncoveredResult):
            return value
        return self.ingredient(value)

    def dose_limits(
        self, ingredient: Ingredient | str, age: int | None, weight: float | None
    ) -> DoseRule:
        resolved = self._coerce(ingredient)
        if isinstance(resolved, UncoveredResult):
            return DoseRule(resolved.query, covered=False, message=resolved.message)
        row = self.session.get(Formulary, resolved.id)
        if row is None:
            return DoseRule(resolved.name or "", covered=False, message=UNCOVERED_MESSAGE)
        return DoseRule(
            ingredient=row.ingredient_name,
            max_single_dose=row.max_single_dose,
            max_daily_dose=row.max_daily_dose,
            mg_per_kg=row.mg_per_kg,
            min_age=row.min_age,
            max_age=row.max_age,
        )

    def interactions(
        self, ingredients: list[Ingredient | str]
    ) -> list[InteractionResult | UncoveredResult]:
        resolved = [self._coerce(item) for item in ingredients]
        results: list[InteractionResult | UncoveredResult] = [
            item for item in resolved if isinstance(item, UncoveredResult)
        ]
        known = [item for item in resolved if isinstance(item, Ingredient)]
        ids = {item.id for item in known}
        if len(ids) < 2:
            return results
        rows = self.session.scalars(select(Interaction)).all()
        for row in rows:
            if row.ingredient_a in ids and row.ingredient_b in ids:
                names = {
                    formulary.id: formulary.ingredient_name
                    for formulary in self.session.scalars(
                        select(Formulary).where(Formulary.id.in_([row.ingredient_a, row.ingredient_b]))
                    )
                }
                results.append(
                    InteractionResult(
                        names[row.ingredient_a],
                        names[row.ingredient_b],
                        row.severity,
                        row.description,
                        row.management,
                    )
                )
        return results

    def allergy_conflicts(
        self, ingredients: list[Ingredient | str], allergies: list[Any]
    ) -> list[AllergyConflict | UncoveredResult]:
        resolved = [self._coerce(item) for item in ingredients]
        results: list[AllergyConflict | UncoveredResult] = [
            item for item in resolved if isinstance(item, UncoveredResult)
        ]
        known = [item for item in resolved if isinstance(item, Ingredient)]
        classes = self.session.scalars(select(AllergyClass)).all()
        for allergy in allergies:
            allergy_class = getattr(allergy, "allergy_class", None) or str(allergy)
            ingredient_id = getattr(allergy, "ingredient_id", None)
            matching = [
                row
                for row in classes
                if row.class_name.casefold() == allergy_class.casefold()
            ]
            for row in matching:
                for item in known:
                    if item.id in row.member_ingredient_ids or item.id == ingredient_id:
                        results.append(
                            AllergyConflict(
                                item.name or "",
                                row.class_name,
                                f"{item.name} conflicts with allergy class {row.class_name}.",
                            )
                        )
        return results


class FakeSTT:
    def __init__(self, responses: Mapping[Any, str | Transcript] | None = None):
        self.responses = dict(responses or {})

    def transcribe(self, audio_file: bytes, content_type: str = "audio/wav") -> Transcript:
        response = self.responses.get(audio_file, audio_file.decode(errors="replace"))
        return response if isinstance(response, Transcript) else Transcript(response, (TranscriptChunk(response),))

    def stream(self, audio: bytes) -> Iterator[TranscriptChunk]:
        yield from self.transcribe(audio).chunks


class FakeLLM:
    def __init__(self, responses: Mapping[str, Mapping[str, Any] | PrescriptionDraft] | None = None):
        self.responses = dict(responses or {})

    def extract_prescription(self, clinical_text: Any, mode: str) -> PrescriptionDraft:
        key = clinical_text if isinstance(clinical_text, str) else json.dumps(clinical_text, sort_keys=True)
        response = self.responses.get(key, {"diagnosis": None, "patient_facts": {}, "medicines": []})
        return response if isinstance(response, PrescriptionDraft) else PrescriptionDraft.from_dict(response)


def _catalog_names(catalog: Any) -> list[str]:
    if catalog is None:
        return []
    if isinstance(catalog, Session):
        return list(catalog.scalars(select(BrandCatalog.brand_name)).all())
    return [str(item) for item in catalog]


def _post_correct(text: str, catalog: Any) -> str:
    for brand in _catalog_names(catalog):
        if brand.casefold() in text.casefold():
            continue
        parts = text.split()
        close = difflib.get_close_matches(brand, parts, n=1, cutoff=0.86)
        if close:
            text = text.replace(close[0], brand)
    return text


class DeepgramSTT:
    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        catalog: Any = None,
        base_url: str = "https://api.deepgram.com/v1/listen",
    ):
        self.api_key = api_key or os.getenv("DEEPGRAM_API_KEY")
        self.client = client
        self.catalog = catalog
        self.base_url = base_url

    def transcribe(self, audio_file: bytes, content_type: str = "audio/wav") -> Transcript:
        if not self.api_key:
            raise ValueError("DEEPGRAM_API_KEY is required")
        own_client = self.client is None
        client = self.client or httpx.Client()
        try:
            response = client.post(
                self.base_url,
                content=audio_file,
                headers={"Authorization": f"Token {self.api_key}", "Content-Type": content_type},
                params={"model": "nova-3", "smart_format": "true", "diarize": "true"},
            )
            response.raise_for_status()
            text = response.json()["results"]["channels"][0]["alternatives"][0]["transcript"]
            text = _post_correct(text, self.catalog)
            return Transcript(text, (TranscriptChunk(text),))
        finally:
            if own_client:
                client.close()

    def stream(self, audio: bytes) -> Iterator[TranscriptChunk]:
        yield from self.transcribe(audio).chunks


def strip_pii(value: Any) -> Any:
    """Remove patient identity fields before external model calls."""
    if isinstance(value, Mapping):
        clean = {}
        for key, item in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in {"name", "patient_name", "patient_id", "id", "contact", "phone", "email"}:
                continue
            clean[key] = strip_pii(item)
        return clean
    if isinstance(value, list):
        return [strip_pii(item) for item in value]
    if isinstance(value, str):
        redacted = re.sub(
            r"(?i)\b(?:patient\s+)?(?:name|id|contact|phone|email)\s*[:=]\s*[^;,\n]+[;,]?\s*",
            "",
            value,
        )
        return redacted.strip(" ;,\n")
    return value


PRESCRIPTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "diagnosis": {"type": ["string", "null"]},
        "patient_facts": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "age": {"type": ["integer", "null"]},
                "weight_kg": {"type": ["number", "null"]},
                "allergies": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["age", "weight_kg", "allergies"],
        },
        "medicines": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    key: {"type": ["string", "null"]}
                    for key in (
                        "ingredient", "brand", "strength", "form", "route", "dose",
                        "frequency", "duration", "instructions",
                    )
                }
                | {"evidence_segment_ids": {"type": "array", "items": {"type": "string"}}},
                "required": [
                    "ingredient", "brand", "strength", "form", "route", "dose", "frequency",
                    "duration", "instructions", "evidence_segment_ids",
                ],
            },
        },
    },
    "required": ["diagnosis", "patient_facts", "medicines"],
}


class OpenAILLM:
    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1/chat/completions",
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.client = client
        self.model = model
        self.base_url = base_url

    def extract_prescription(self, clinical_text: Any, mode: str) -> PrescriptionDraft:
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required")
        clean = strip_pii(clinical_text)
        prompt = clean if isinstance(clean, str) else json.dumps(clean, sort_keys=True)
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Extract a prescription draft from clinical text."},
                {"role": "user", "content": f"Mode: {mode}\nClinical text:\n{prompt}"},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "prescription_draft", "strict": True, "schema": PRESCRIPTION_SCHEMA},
            },
        }
        own_client = self.client is None
        client = self.client or httpx.Client()
        try:
            response = client.post(
                self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=body,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return PrescriptionDraft.from_dict(json.loads(content))
        finally:
            if own_client:
                client.close()


def build_providers(
    session: Session,
    *,
    fake_stt: Mapping[Any, str | Transcript] | None = None,
    fake_llm: Mapping[str, Mapping[str, Any] | PrescriptionDraft] | None = None,
) -> dict[str, Any]:
    return {
        "stt": get_stt_provider(session, fake_responses=fake_stt),
        "llm": get_llm_provider(fake_responses=fake_llm),
        "drugknowledge": get_drug_knowledge_provider(session),
    }


def get_stt_provider(
    settings: Any = None,
    session: Session | None = None,
    *,
    fake_responses: Mapping[Any, str | Transcript] | None = None,
) -> STTProvider:
    if isinstance(settings, Session) and session is None:
        session, settings = settings, None
    backend = str(getattr(settings, "stt_backend", os.getenv("STT_BACKEND", "deepgram"))).casefold()
    if backend == "fake":
        return FakeSTT(fake_responses or {})
    if backend == "deepgram":
        return DeepgramSTT(catalog=session)
    raise ValueError(f"Unsupported STT_BACKEND: {backend}")


def get_llm_provider(
    settings: Any = None,
    *,
    fake_responses: Mapping[str, Mapping[str, Any] | PrescriptionDraft] | None = None,
) -> LLMProvider:
    backend = str(getattr(settings, "llm_backend", os.getenv("LLM_BACKEND", "openai"))).casefold()
    if backend == "fake":
        return FakeLLM(fake_responses or {})
    if backend == "openai":
        return OpenAILLM()
    raise ValueError(f"Unsupported LLM_BACKEND: {backend}")


def get_drug_knowledge_provider(
    session: Session | Any,
    settings: Any = None,
) -> DrugKnowledgeProvider:
    if not isinstance(session, Session):
        session, settings = settings, session
    if session is None:
        raise ValueError("a SQLAlchemy Session is required for curated drug knowledge")
    backend = str(
        getattr(settings, "drugknowledge_backend", os.getenv("DRUGKNOWLEDGE_BACKEND", "curated"))
    ).casefold()
    if backend == "curated":
        return CuratedDrugKnowledge(session)
    raise ValueError(f"Unsupported DRUGKNOWLEDGE_BACKEND: {backend}")
