"""Hybrid voice-first prescribing.

Two ways onto one AI-staged draft:
  * short commands ("add penicillin allergy") mutate the staged draft immediately,
  * full dictation is captured and extracted once, at "End" / "Review prescription".

Nothing here touches the database. ``/api/voice/review`` hands the staged draft to
the shared ``persist_draft`` path, so brand -> generic resolution, the deterministic
safety engine, ``safety_events`` and ``audit_log`` behave exactly as in manual and
ambient modes. Missing fields never reject a dictation: they come back as
``missing_required`` so the review screen can mark them before signing.
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_session
from .models import AllergyClass, Formulary
from .mode2 import (
    NUMBER_WORDS,
    DoctorInput,
    PatientInput,
    _matching_brand,
    _medicine_drafts,
    _normal_parts,
    correct_drug_names,
    minimize_clinical_text,
    persist_draft,
)
from .providers import PrescriptionDraft, get_llm_provider, get_stt_provider, strip_pii


router = APIRouter(prefix="/api/voice")


class StagedMedicine(BaseModel):
    id: str | None = None
    brand: str | None = None
    generic: str | None = None
    strength: str | None = None
    form: str | None = None
    route: str | None = "oral"
    dose: str | None = None
    frequency: str | None = None
    duration: str | None = None
    instructions: str | None = None


class StagedPatient(BaseModel):
    """Identity fields live here and are never sent to the LLM (see /dictation)."""

    name: str | None = None
    patient_id: str | None = None
    age: int | None = None
    sex: str | None = None
    weight_kg: float | None = None
    contact: str | None = None
    allergies: list[str] = Field(default_factory=list)


class StagedDoctor(BaseModel):
    name: str | None = None
    registration_no: str | None = None


class StagedDraft(BaseModel):
    patient: StagedPatient = Field(default_factory=StagedPatient)
    diagnosis: str | None = None
    medicines: list[StagedMedicine] = Field(default_factory=list)


class CommandInput(BaseModel):
    utterance: str = Field(min_length=1)
    draft: StagedDraft = Field(default_factory=StagedDraft)


class DictationInput(BaseModel):
    text: str = Field(min_length=1)
    draft: StagedDraft = Field(default_factory=StagedDraft)


class ReviewInput(BaseModel):
    draft: StagedDraft = Field(default_factory=StagedDraft)
    doctor: StagedDoctor = Field(default_factory=StagedDoctor)


# ── command grammar ───────────────────────────────────────────────────────────
# Deterministic, no LLM: a short command must do exactly what the doctor said.

_REVIEW = re.compile(
    r"\b(?:review|show|read\s+back)\s+(?:the\s+)?(?:prescription|rx|draft)\b"
    r"|\bend\s+(?:the\s+)?(?:encounter|dictation)\b",
    re.IGNORECASE,
)
_REMOVE_LAST = re.compile(
    r"\bremove\s+(?:the\s+)?last\s+(?:medicine|medication|drug|tablet|item)\b", re.IGNORECASE
)
_CHANGE = re.compile(
    r"\bchange\s+(?:the\s+)?(duration|frequency|dose|strength|instructions|route|form)\s+to\s+(.+)$",
    re.IGNORECASE,
)
_ALLERGY = re.compile(
    r"\b([A-Za-z][A-Za-z-]*(?:\s+[A-Za-z][A-Za-z-]*)?)\s+allerg(?:y|ies)\b", re.IGNORECASE
)
_ALLERGIC_TO = re.compile(r"\ballergic\s+to\s+([A-Za-z][A-Za-z -]*)", re.IGNORECASE)
_DIAGNOSIS = re.compile(r"\bdiagnosis\b\s*(?:is|of|:)?\s*(.+)$", re.IGNORECASE)
_PRESCRIBE = re.compile(r"\b(?:prescribe|start|give|add|write)\b\s+(.+)$", re.IGNORECASE)
_PATIENT_NAME = re.compile(
    r"\bpatient(?:'s)?\s+name\s+(?:is\s+)?([A-Za-z][A-Za-z .'-]*)", re.IGNORECASE
)
_AGE = re.compile(r"\b(\d{1,3})\s*(?:years?\s*old|year[- ]old|y/?o\b|yrs?\b)", re.IGNORECASE)
_SEX = re.compile(r"\b(male|female|other)\b", re.IGNORECASE)
_WEIGHT = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:kg|kilos?|kilograms?)\b", re.IGNORECASE)

_STRENGTH = re.compile(r"\b(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml|iu)\b", re.IGNORECASE)
_DOSE = re.compile(
    r"\b(\d+(?:\.\d+)?|one|two|three|four|half)\s+(tablets?|capsules?|drops?|puffs?|ml|sachets?)\b",
    re.IGNORECASE,
)
_DURATION = re.compile(r"\bfor\s+(\d+)\s*(days?|weeks?|months?)\b", re.IGNORECASE)
_INSTRUCTIONS = re.compile(
    r"\b(after food|before food|after meals|before meals|with food|with water|at bedtime|empty stomach)\b",
    re.IGNORECASE,
)
# Where a spoken medicine name ends and its dosing begins.
_MED_STOP = re.compile(
    r",|\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|iu)\b"
    r"|\b(?:\d+|one|two|three|four|half)\s+(?:tablets?|capsules?|drops?|puffs?|sachets?)\b"
    r"|\b(?:once|twice|thrice|daily|bd|od|tds|bid|tid|qid|for)\b",
    re.IGNORECASE,
)
_FREQUENCIES = (
    ("thrice daily", re.compile(r"\b(?:thrice|three\s+times|tds|tid)\b", re.IGNORECASE)),
    ("twice daily", re.compile(r"\b(?:twice|two\s+times|bd|bid)\b", re.IGNORECASE)),
    ("4 times daily", re.compile(r"\b(?:four\s+times|qid)\b", re.IGNORECASE)),
    ("once daily", re.compile(r"\b(?:once|one\s+time|od|daily|every\s+day)\b", re.IGNORECASE)),
)
_COUNTS = NUMBER_WORDS | {"half": 0.5}
_ALLERGY_NOISE = {"add", "record", "note", "a", "an", "the", "known", "has", "have",
                  "new", "also", "patient", "and", "is", "no"}


def _resolve_allergy(spoken: str, session: Session) -> str:
    """Resolve a spoken allergy to a curated allergy class (or formulary ingredient)
    so the safety engine can match it. Unknown allergies are kept verbatim — they
    simply never produce a match, which is honest, not a pass."""
    key = " ".join(_normal_parts(spoken))
    if len(key) < 4:
        return spoken.strip()
    names = [row.class_name for row in session.scalars(select(AllergyClass))]
    names += [row.ingredient_name for row in session.scalars(select(Formulary))]
    for name in names:
        normal = " ".join(_normal_parts(name))
        if normal == key or normal.startswith(key) or key.startswith(normal):
            return name
    return spoken.strip()


def _allergy_name(text: str) -> str | None:
    match = _ALLERGIC_TO.search(text) or _ALLERGY.search(text)
    if not match:
        return None
    words = [word for word in match.group(1).split() if word.casefold() not in _ALLERGY_NOISE]
    return " ".join(words) or None


def _matching_generic(text: str, session: Session) -> str | None:
    normalized = " ".join(_normal_parts(text))
    return next(
        (
            row.ingredient_name
            for row in session.scalars(select(Formulary))
            if " ".join(_normal_parts(row.ingredient_name)) in normalized
        ),
        None,
    )


def _spoken_name(tail: str) -> str | None:
    stop = _MED_STOP.search(tail)
    return (tail[: stop.start()] if stop else tail).strip(" ,.;:") or None


def _dose_phrase(tail: str) -> str | None:
    match = _DOSE.search(tail)
    if not match:
        return None
    token = match.group(1).casefold()
    count = _COUNTS.get(token, float(token) if token[0].isdigit() else None)
    if count is None:
        return None
    unit = match.group(2).casefold().rstrip("s")
    return f"{count:g} {unit}" if count == 1 else f"{count:g} {unit}s"


def _frequency(tail: str) -> str | None:
    return next((label for label, pattern in _FREQUENCIES if pattern.search(tail)), None)


def _parse_medicine(text: str, tail: str, session: Session) -> StagedMedicine | None:
    """Brand names come from brand_catalog only — never a hardcoded list, and a spoken
    brand always wins over a spoken generic so safety resolves the catalog ingredient."""
    brand = _matching_brand(text, session)
    generic = None if brand else (_matching_generic(text, session) or _spoken_name(tail))
    if not (brand or generic):
        return None
    strength = _STRENGTH.search(tail)
    duration = _DURATION.search(tail)
    instructions = _INSTRUCTIONS.search(tail)
    return StagedMedicine(
        brand=brand.brand_name if brand else None,
        generic=generic,
        strength=(
            f"{strength.group(1)} {strength.group(2).casefold()}"
            if strength
            else (brand.strength if brand else None)
        ),
        form=brand.form if brand else None,
        route="oral",
        dose=_dose_phrase(tail),
        frequency=_frequency(tail),
        duration=f"{duration.group(1)} {duration.group(2).casefold()}" if duration else None,
        instructions=instructions.group(1).casefold() if instructions else None,
    )


def _apply_patient_facts(text: str, patient: StagedPatient) -> list[str]:
    """Fill-if-empty, so an incidental mention never silently overwrites a value the
    doctor has already corrected. An explicit "patient name ..." command does overwrite."""
    applied = []
    name = _PATIENT_NAME.search(text)
    if name:
        value = re.sub(r"\s+(male|female|other)$", "", name.group(1).strip(" .,"), flags=re.IGNORECASE)
        if value:
            patient.name = value
            applied.append(f"patient name: {value}")
    age = _AGE.search(text)
    if age and patient.age is None and 0 < int(age.group(1)) <= 130:
        patient.age = int(age.group(1))
        applied.append(f"age: {patient.age}")
    weight = _WEIGHT.search(text)
    if weight and patient.weight_kg is None and float(weight.group(1)) > 0:
        patient.weight_kg = float(weight.group(1))
        applied.append(f"weight: {patient.weight_kg} kg")
    sex = _SEX.search(text)
    if sex and not patient.sex:
        patient.sex = sex.group(1).casefold()
        applied.append(f"sex: {patient.sex}")
    return applied


def _add_allergy(patient: StagedPatient, allergy: str) -> bool:
    if allergy.casefold() in {existing.casefold() for existing in patient.allergies}:
        return False
    patient.allergies.append(allergy)
    return True


def apply_command(utterance: str, draft: StagedDraft, session: Session) -> tuple[list[str], str | None]:
    """Apply one short command to the staged draft in place.

    Returns (human-readable changes, action) where action is "review" when the doctor
    asked to see the prescription."""
    text = correct_drug_names(utterance.strip(), session)
    applied = _apply_patient_facts(text, draft.patient)

    if _REVIEW.search(text):
        return applied, "review"

    if _REMOVE_LAST.search(text):
        if draft.medicines:
            removed = draft.medicines.pop()
            applied.append(f"removed {removed.brand or removed.generic or 'last medicine'}")
        return applied, None

    change = _CHANGE.search(text)
    if change:
        field, value = change.group(1).casefold(), change.group(2).strip(" .")
        if draft.medicines:
            setattr(draft.medicines[-1], field, value)
            applied.append(f"{field}: {value}")
        return applied, None

    allergy = _allergy_name(text)
    if allergy:
        resolved = _resolve_allergy(allergy, session)
        if _add_allergy(draft.patient, resolved):
            applied.append(f"allergy: {resolved}")
        return applied, None

    diagnosis = _DIAGNOSIS.search(text)
    if diagnosis:
        draft.diagnosis = diagnosis.group(1).strip(" .")
        applied.append(f"diagnosis: {draft.diagnosis}")
        return applied, None

    prescribe = _PRESCRIBE.search(text)
    if prescribe:
        medicine = _parse_medicine(text, prescribe.group(1), session)
        if medicine:
            draft.medicines.append(medicine)
            applied.append(f"medicine: {medicine.brand or medicine.generic}")
        return applied, None

    return applied, None


def missing_required(draft: StagedDraft, doctor: StagedDoctor | None = None) -> list[str]:
    """Only the fields that must be present before a prescription can be signed."""
    missing = [f"patient.{field}" for field in ("name", "sex") if not getattr(draft.patient, field)]
    if not (draft.diagnosis or "").strip():
        missing.append("diagnosis")
    if not draft.medicines:
        missing.append("medicines")
    for position, medicine in enumerate(draft.medicines, start=1):
        if not (medicine.brand or medicine.generic):
            missing.append(f"medicine {position}.name")
        missing += [
            f"medicine {position}.{field}"
            for field in ("dose", "frequency", "duration")
            if not getattr(medicine, field)
        ]
    if doctor is not None:
        missing += [
            f"doctor.{field}"
            for field in ("name", "registration_no")
            if not getattr(doctor, field)
        ]
    return missing


# ── dictation ─────────────────────────────────────────────────────────────────


def _extraction_dict(text: str, session: Session) -> dict:
    """Heuristic stand-in for the LLM: run the command grammar over every sentence.

    Shape matches providers.PRESCRIPTION_SCHEMA, so the keyless demo and the real
    OpenAI structured-outputs response are interchangeable. Fields the doctor never
    spoke stay null instead of being invented."""
    staged = StagedDraft()
    for sentence in re.split(r"[.\n?!;]+", text):
        if sentence.strip():
            apply_command(sentence, staged, session)
    return {
        "diagnosis": staged.diagnosis,
        "patient_facts": {
            "age": staged.patient.age,
            "weight_kg": staged.patient.weight_kg,
            "allergies": staged.patient.allergies,
        },
        "medicines": [
            {
                "ingredient": medicine.generic,
                "brand": medicine.brand,
                "strength": medicine.strength,
                "form": medicine.form,
                "route": medicine.route,
                "dose": medicine.dose,
                "frequency": medicine.frequency,
                "duration": medicine.duration,
                "instructions": medicine.instructions,
                "evidence_segment_ids": [],
            }
            for medicine in staged.medicines
        ],
    }


def _merge_extraction(draft: StagedDraft, extracted: PrescriptionDraft, session: Session) -> list[str]:
    """Merge without clobbering: a value the doctor already set by command wins."""
    applied = []
    if extracted.diagnosis and not draft.diagnosis:
        draft.diagnosis = extracted.diagnosis
        applied.append(f"diagnosis: {draft.diagnosis}")
    facts = extracted.patient_facts or {}
    if draft.patient.age is None and facts.get("age") is not None:
        draft.patient.age = facts["age"]
        applied.append(f"age: {draft.patient.age}")
    if draft.patient.weight_kg is None and facts.get("weight_kg") is not None:
        draft.patient.weight_kg = facts["weight_kg"]
        applied.append(f"weight: {draft.patient.weight_kg} kg")
    for allergy in facts.get("allergies") or []:
        resolved = _resolve_allergy(allergy, session)
        if _add_allergy(draft.patient, resolved):
            applied.append(f"allergy: {resolved}")
    staged_names = {(m.brand or m.generic or "").casefold() for m in draft.medicines}
    for medicine in extracted.medicines:
        key = (medicine.brand or medicine.ingredient or "").casefold()
        if not key or key in staged_names:
            continue
        staged_names.add(key)
        draft.medicines.append(
            StagedMedicine(
                brand=medicine.brand,
                generic=medicine.ingredient,
                strength=medicine.strength,
                form=medicine.form,
                route=medicine.route or "oral",
                dose=medicine.dose,
                frequency=medicine.frequency,
                duration=medicine.duration,
                instructions=medicine.instructions,
            )
        )
        applied.append(f"medicine: {medicine.brand or medicine.ingredient}")
    return applied


def _extract_dictation(text: str, draft: StagedDraft, session: Session) -> tuple[str, list[str]]:
    corrected = correct_drug_names(text.strip(), session)
    applied = _apply_patient_facts(corrected, draft.patient)  # name resolved locally, never sent
    minimized = minimize_clinical_text(corrected, draft.patient)
    clinical = strip_pii(
        {
            "patient_name": draft.patient.name,
            "patient_id": draft.patient.patient_id,
            "contact": draft.patient.contact,
            "clinical_text": minimized,
        }
    )["clinical_text"]
    llm = get_llm_provider(fake_responses={clinical: _extraction_dict(minimized, session)})
    applied += _merge_extraction(draft, llm.extract_prescription(clinical, "voice"), session)
    return corrected, applied


def _staged_response(draft: StagedDraft, applied: list[str], action: str | None = None) -> dict:
    return {
        "draft": draft.model_dump(),
        "applied": applied,
        "action": action,
        "missing_required": missing_required(draft),
        "staged": True,
        "signed": False,
    }


# ── endpoints ─────────────────────────────────────────────────────────────────


@router.post("/command")
def voice_command(payload: CommandInput, session: Session = Depends(get_session)):
    applied, action = apply_command(payload.utterance, payload.draft, session)
    response = _staged_response(payload.draft, applied, action)
    response["note"] = None if applied or action else "Command not recognized."
    return response


@router.post("/audio-command")
async def voice_audio_command(
    audio: UploadFile = File(...),
    draft: str = Form("{}"),
    session: Session = Depends(get_session),
):
    try:
        staged = StagedDraft.model_validate(json.loads(draft))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise HTTPException(422, "draft must be valid JSON") from exc
    transcript = get_stt_provider(session).transcribe(
        await audio.read(), audio.content_type or "application/octet-stream"
    )
    applied, action = apply_command(transcript.text, staged, session)
    response = _staged_response(staged, applied, action)
    response["utterance"] = transcript.text
    response["note"] = None if applied or action else "Command not recognized."
    return response


@router.post("/dictation")
def voice_dictation(payload: DictationInput, session: Session = Depends(get_session)):
    """Full dictation: extract once, stage the result. Never persisted here, and never
    rejected for missing fields — unspoken fields stay null and are listed instead."""
    transcript, applied = _extract_dictation(payload.text, payload.draft, session)
    response = _staged_response(payload.draft, applied)
    response["transcript"] = transcript
    return response


@router.post("/audio-dictation")
async def voice_audio_dictation(
    audio: UploadFile = File(...),
    draft: str = Form("{}"),
    session: Session = Depends(get_session),
):
    try:
        staged = StagedDraft.model_validate(json.loads(draft))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise HTTPException(422, "draft must be valid JSON") from exc
    audio_bytes = await audio.read()
    spoken = get_stt_provider(session).transcribe(
        audio_bytes, audio.content_type or "application/octet-stream"
    )
    transcript, applied = _extract_dictation(spoken.text, staged, session)
    response = _staged_response(staged, applied)
    response["transcript"] = transcript
    return response


@router.post("/review")
def voice_review(payload: ReviewInput, session: Session = Depends(get_session)):
    """"Review prescription" / End: turn the staged draft into a real, safety-checked
    draft. Still doctor-approved-then-signed — this only stages it for review."""
    missing = missing_required(payload.draft, payload.doctor)
    if missing:
        response = _staged_response(payload.draft, [])
        response["missing_required"] = missing
        response["ready"] = False
        return response
    result = persist_draft(
        session,
        patient=PatientInput(**payload.draft.patient.model_dump()),
        doctor=DoctorInput(**payload.doctor.model_dump()),
        diagnosis=payload.draft.diagnosis,
        mode="voice",
        source="voice",
        medicines=_medicine_drafts(payload.draft.medicines),
    )
    return {"ready": True, "staged": False, "missing_required": [], **result}
