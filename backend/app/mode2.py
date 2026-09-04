from dataclasses import replace
from datetime import datetime, timezone
from difflib import SequenceMatcher
import json
import os
from pathlib import Path
import re

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_session
from .models import (
    AuditLog,
    BrandCatalog,
    Doctor,
    Encounter,
    Formulary,
    Patient,
    Prescription,
    PrescriptionItem,
    SafetyEvent as SafetyEventRow,
    Transcript as TranscriptRow,
    new_id,
)
from .pdf import write_pdf
from .providers import (
    AllergyConflict,
    CuratedDrugKnowledge,
    Ingredient,
    InteractionResult,
    MedicineDraft,
    UncoveredResult,
    get_drug_knowledge_provider,
    get_llm_provider,
    get_stt_provider,
    strip_pii,
)
from .safety import (
    DoseLimits,
    InteractionRule,
    Medicine,
    PatientFacts,
    evaluate,
)


router = APIRouter(prefix="/api")


class PatientInput(BaseModel):
    name: str = Field(min_length=1)
    patient_id: str | None = None
    age: int | None = Field(default=None, ge=0, le=130)
    sex: str = Field(min_length=1)
    weight_kg: float | None = Field(default=None, gt=0)
    contact: str | None = None
    allergies: list[str] = []


class DoctorInput(BaseModel):
    name: str = Field(min_length=1)
    registration_no: str = Field(min_length=1)


class DraftInput(BaseModel):
    text: str = Field(min_length=1)
    patient: PatientInput
    doctor: DoctorInput


class AcknowledgeInput(BaseModel):
    event_ids: list[str] = Field(min_length=1)
    doctor_name: str = Field(min_length=1)
    registration_no: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class SignInput(BaseModel):
    doctor_name: str = Field(min_length=1)
    registration_no: str = Field(min_length=1)


class ManualMedicineInput(BaseModel):
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

    @model_validator(mode="after")
    def _require_brand_or_generic(self) -> "ManualMedicineInput":
        if not (self.brand or "").strip() and not (self.generic or "").strip():
            raise ValueError("Each medicine needs a catalog brand or a generic ingredient.")
        return self


class ManualDraftInput(BaseModel):
    diagnosis: str | None = None
    patient: PatientInput
    doctor: DoctorInput
    medicines: list[ManualMedicineInput] = Field(min_length=1)


class EditDraftInput(BaseModel):
    diagnosis: str | None = None
    medicines: list[ManualMedicineInput] = Field(min_length=1)


def minimize_clinical_text(text: str, patient: PatientInput) -> str:
    for identifier in (patient.name, patient.patient_id, patient.contact):
        if identifier:
            text = re.sub(re.escape(identifier), "[redacted]", text, flags=re.IGNORECASE)
    return text


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _normal_parts(value: str) -> list[str]:
    return re.findall(r"[a-z]+|\d+", value.casefold())


def _brand_pattern(brand_name: str) -> str:
    return r"\b" + r"[\s-]*".join(map(re.escape, _normal_parts(brand_name))) + r"\b"


def correct_drug_names(text: str, session: Session) -> str:
    for brand in session.scalars(select(BrandCatalog)).all():
        parts = _normal_parts(brand.brand_name)
        pattern = _brand_pattern(brand.brand_name)
        if re.search(pattern, text, flags=re.IGNORECASE):
            text = re.sub(pattern, brand.brand_name, text, flags=re.IGNORECASE)
            continue
        words = re.findall(r"\b[a-z]+\b", text, flags=re.IGNORECASE)
        if parts and any(
            SequenceMatcher(None, parts[0], word.casefold()).ratio() >= 0.8 for word in words
        ) and all(number in text for number in parts[1:] if number.isdigit()):
            closest = max(words, key=lambda word: SequenceMatcher(None, parts[0], word.casefold()).ratio())
            text = re.sub(rf"\b{re.escape(closest)}\b(?:[\s-]*{parts[-1]})?", brand.brand_name, text, count=1, flags=re.IGNORECASE)
    return text


NUMBER_WORDS = {"one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0}


def _tablet_count(text: str | None) -> float | None:
    match = re.search(
        r"\b(\d+(?:\.\d+)?|one|two|three|four)\s+(?:tablets?|capsules?)\b", text or "", re.IGNORECASE
    )
    if not match:
        return None
    token = match.group(1).casefold()
    return NUMBER_WORDS.get(token, float(token) if token[0].isdigit() else None)


def _dictated_dose(text: str, brand: BrandCatalog) -> str:
    dosing_text = re.sub(_brand_pattern(brand.brand_name), "", text, count=1, flags=re.IGNORECASE)
    explicit = re.search(r"\b(\d+(?:\.\d+)?)\s*mg\b", dosing_text, re.IGNORECASE)
    tablets = re.search(
        r"\b(\d+(?:\.\d+)?|one|two|three|four)\s+tablets?\b",
        dosing_text,
        re.IGNORECASE,
    )
    if tablets and explicit:
        return f"{tablets.group(1)} tablets of {explicit.group(1)} mg"
    if explicit:
        return f"{explicit.group(1)} mg"
    if tablets:
        return f"{tablets.group(1)} tablets"
    return "1 tablet"


def _fake_draft(text: str, brand: BrandCatalog | None) -> dict:
    duration = re.search(r"for\s+(\d+)\s+days?", text, re.IGNORECASE)
    frequency = next(
        (label for label in ("twice daily", "once daily", "thrice daily") if label in text.casefold()),
        "once daily",
    )
    return {
        "diagnosis": "headache" if "headache" in text.casefold() else None,
        "patient_facts": {},
        "medicines": []
        if brand is None
        else [
            {
                "ingredient": None,
                "brand": brand.brand_name,
                "strength": brand.strength,
                "form": brand.form,
                "route": "oral",
                "dose": _dictated_dose(text, brand),
                "frequency": frequency,
                "duration": f"{duration.group(1)} days" if duration else "",
                "instructions": None,
                "evidence_segment_ids": [],
            }
        ],
    }


def _matching_brand(text: str, session: Session) -> BrandCatalog | None:
    normalized = " ".join(_normal_parts(text))
    return next(
        (
            brand
            for brand in session.scalars(select(BrandCatalog)).all()
            if " ".join(_normal_parts(brand.brand_name)) in normalized
        ),
        None,
    )


def _number(value: str | None) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", value or "")
    return float(match.group()) if match else None


def _dose_mg(dose: str | None, strength: str | None) -> float | None:
    explicit = re.search(r"\b(\d+(?:\.\d+)?)\s*mg\b", dose or "", re.IGNORECASE)
    explicit_mg = float(explicit.group(1)) if explicit else None
    tablets = _tablet_count(dose)
    strength_mg = _number(strength)
    tablet_total = tablets * strength_mg if tablets is not None and strength_mg is not None else None
    # ponytail: conservative heuristic; replace with a dose grammar when free-form dosing expands.
    candidates = [value for value in (explicit_mg, tablet_total) if value is not None]
    return max(candidates) if candidates else strength_mg


def _doses_per_day(value: str | None) -> float | None:
    text = (value or "").casefold()
    for label, count in (("once", 1), ("twice", 2), ("thrice", 3)):
        if label in text:
            return float(count)
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:times|x)", text)
    return float(match.group(1)) if match else None


def _serialize_event(
    row: SafetyEventRow,
    acknowledgment: SafetyEventRow | None,
    medicine: str,
    session: Session,
) -> dict:
    doctor = (
        session.get(Doctor, acknowledgment.acknowledged_by)
        if acknowledgment and acknowledgment.acknowledged_by
        else None
    )
    return {
        "id": row.id,
        "type": row.type,
        "severity": row.severity,
        "message": row.message,
        "medicine": medicine,
        "must_acknowledge": True,
        "shown_at": row.shown_at.isoformat() + "Z",
        "acknowledged": acknowledgment is not None,
        "acknowledged_by": doctor.name if doctor else None,
        "acknowledged_at": (
            acknowledgment.acknowledged_at.isoformat() + "Z"
            if acknowledgment and acknowledgment.acknowledged_at
            else None
        ),
        "acknowledged_reason": acknowledgment.override_reason if acknowledgment else None,
    }


def _event_rows(session: Session, prescription: Prescription) -> list[SafetyEventRow]:
    return list(
        session.scalars(
            select(SafetyEventRow)
            .join(Encounter, SafetyEventRow.encounter_id == Encounter.id)
            .where(Encounter.id == prescription.encounter_id)
            .order_by(SafetyEventRow.shown_at, SafetyEventRow.id)
        )
    )


def _active_event_ids(session: Session, prescription: Prescription) -> set[str] | None:
    latest = session.scalar(
        select(AuditLog)
        .where(
            AuditLog.entity_id == prescription.id,
            AuditLog.action.in_(("prescription_drafted", "prescription_edited")),
        )
        .order_by(AuditLog.at.desc(), AuditLog.id.desc())
    )
    if latest is None or not isinstance(latest.after, dict) or "safety_event_ids" not in latest.after:
        return None
    return set(latest.after.get("safety_event_ids") or ())


def _events_json(session: Session, prescription: Prescription) -> list[dict]:
    all_rows = _event_rows(session, prescription)
    rows = all_rows
    active_ids = _active_event_ids(session, prescription)
    if active_ids is not None:
        rows = [row for row in rows if row.id in active_ids]
    acknowledgments = {
        (row.type, row.message, row.prescription_item_id): row
        for row in all_rows
        if row.acknowledged
    }
    items = {
        item.id: session.get(Formulary, item.ingredient_id).ingredient_name
        for item in session.scalars(
            select(PrescriptionItem).where(PrescriptionItem.prescription_id == prescription.id)
        )
    }
    result = []
    for row in rows:
        if row.acknowledged:
            continue
        acknowledgment = acknowledgments.get((row.type, row.message, row.prescription_item_id))
        if acknowledgment and acknowledgment.shown_at < row.shown_at:
            acknowledgment = None
        result.append(_serialize_event(row, acknowledgment, items.get(row.prescription_item_id, "multiple medicines"), session))
    return result


def _doctor_for(session: Session, prescription: Prescription, name: str, registration_no: str) -> Doctor:
    encounter = session.get(Encounter, prescription.encounter_id)
    doctor = session.get(Doctor, encounter.doctor_id)
    if doctor.name != name or doctor.registration_no != registration_no:
        raise HTTPException(403, "Signing doctor does not match this encounter")
    return doctor


def _pdf_path(prescription_id: str) -> Path:
    root = Path(os.getenv("PDF_DIR", Path(__file__).resolve().parents[1] / "generated"))
    return root / f"{prescription_id}.pdf"


def _resolve_medicine(
    md: MedicineDraft, knowledge: CuratedDrugKnowledge, session: Session
) -> tuple[Ingredient | None, BrandCatalog | None]:
    """Resolve a draft medicine to a covered generic. Brand wins over a client generic
    so safety always runs on the catalog-resolved ingredient (never the typed brand)."""
    if md.brand:
        resolved = knowledge.resolve_brand(md.brand)
        brand_row = session.scalar(
            select(BrandCatalog).where(BrandCatalog.brand_name.ilike(md.brand))
        )
    elif md.ingredient:
        resolved = knowledge.ingredient(md.ingredient)
        brand_row = None
    else:
        return None, None
    if isinstance(resolved, UncoveredResult):
        return None, brand_row
    return resolved, brand_row


def _medicine_drafts(values: list[ManualMedicineInput]) -> list[MedicineDraft]:
    return [
        MedicineDraft(
            id=value.id,
            ingredient=value.generic or None,
            brand=value.brand or None,
            strength=value.strength,
            form=value.form,
            route=value.route,
            dose=value.dose,
            frequency=value.frequency,
            duration=value.duration,
            instructions=value.instructions,
            evidence_segment_ids=(),
        )
        for value in values
    ]


def _render_medicines(
    session: Session,
    resolved: list[tuple[PrescriptionItem, Ingredient, float | None, float | None]],
    uncovered: list[dict],
) -> list[dict]:
    medicines_json = []
    for item, ingredient, dose_mg, doses_per_day in resolved:
        brand_row = session.get(BrandCatalog, item.brand_id) if item.brand_id else None
        medicines_json.append(
            {
                "id": item.id,
                "brand": brand_row.brand_name if brand_row else None,
                "ingredient": ingredient.name,
                "strength": item.strength,
                "form": item.form,
                "route": item.route,
                "dose": item.dose,
                "frequency": item.frequency,
                "duration": item.duration,
                "instructions": item.instructions,
                "single_dose_mg": dose_mg,
                "daily_dose_mg": dose_mg * doses_per_day if dose_mg is not None and doses_per_day is not None else None,
            }
        )
    for entry in uncovered:
        dose_mg, doses_per_day = entry["single_dose_mg"], entry["doses_per_day"]
        medicines_json.append(
            {
                "id": entry["id"],
                "name": entry["name"],
                "brand": entry["brand"],
                "ingredient": None,
                "strength": entry["strength"],
                "form": entry["form"],
                "route": entry["route"],
                "dose": entry["dose"],
                "frequency": entry["frequency"],
                "duration": entry["duration"],
                "instructions": entry["instructions"],
                "single_dose_mg": dose_mg,
                "daily_dose_mg": dose_mg * doses_per_day if dose_mg is not None and doses_per_day is not None else None,
            }
        )
    return medicines_json


def _resolve_and_check(
    session: Session,
    prescription: Prescription,
    patient: PatientInput,
    medicines: list[MedicineDraft],
    now: datetime,
) -> tuple[list[tuple[PrescriptionItem, Ingredient, float | None, float | None]], list[dict], list[SafetyEventRow]]:
    knowledge = get_drug_knowledge_provider(session)
    resolved = []
    uncovered = []
    for md in medicines:
        ingredient, brand_row = _resolve_medicine(md, knowledge, session)
        strength = md.strength or (brand_row.strength if brand_row else "")
        dose_mg = _dose_mg(md.dose, strength)
        doses_per_day = _doses_per_day(md.frequency)
        form = md.form or (brand_row.form if brand_row else "")
        if ingredient is None:
            uncovered.append({
                "id": md.id or new_id(), "name": (md.brand or md.ingredient or "").strip(),
                "brand": brand_row.brand_name if brand_row else None, "strength": strength,
                "form": form, "route": md.route or "oral", "dose": md.dose or "",
                "frequency": md.frequency or "", "duration": md.duration or "",
                "instructions": md.instructions, "single_dose_mg": dose_mg,
                "doses_per_day": doses_per_day,
            })
            continue
        item = session.get(PrescriptionItem, md.id) if md.id else None
        if item is None or item.prescription_id != prescription.id:
            item = PrescriptionItem(prescription_id=prescription.id, ingredient_id=ingredient.id,
                brand_id=brand_row.id if brand_row else None, strength=strength, form=form,
                route=md.route or "oral", dose=md.dose or "", frequency=md.frequency or "",
                duration=md.duration or "", instructions=md.instructions,
                evidence_segment_ids=list(md.evidence_segment_ids),
                evidence_status="linked" if md.evidence_segment_ids else "missing_context")
            session.add(item)
        else:
            item.ingredient_id = ingredient.id
            item.brand_id = brand_row.id if brand_row else None
            item.strength, item.form = strength, form
            item.route, item.dose = md.route or "oral", md.dose or ""
            item.frequency, item.duration = md.frequency or "", md.duration or ""
            item.instructions = md.instructions
        session.flush()
        resolved.append((item, ingredient, dose_mg, doses_per_day))

    ingredients = [ingredient for _, ingredient, _, _ in resolved]
    interactions = [r for r in knowledge.interactions(ingredients) if isinstance(r, InteractionResult)]
    conflicts = [r for r in knowledge.allergy_conflicts(ingredients, patient.allergies) if isinstance(r, AllergyConflict)]
    safety_medicines = []
    for _, ingredient, dose_mg, doses_per_day in resolved:
        limits = knowledge.dose_limits(ingredient, patient.age, patient.weight_kg)
        safety_medicines.append(Medicine(
            ingredient.name or "", dose_mg=dose_mg, doses_per_day=doses_per_day,
            limits=DoseLimits(
                float(limits.max_single_dose) if limits.max_single_dose is not None else None,
                float(limits.max_daily_dose) if limits.max_daily_dose is not None else None,
                float(limits.mg_per_kg) if limits.mg_per_kg is not None else None,
                limits.min_age, limits.max_age),
            allergy_classes=tuple(c.class_name for c in conflicts if c.ingredient == ingredient.name),
            interactions=tuple(InteractionRule(r.ingredient_b, r.severity, r.description)
                for r in interactions if r.ingredient_a == ingredient.name),
        ))
    safety_medicines.extend(Medicine(entry["name"], covered=False) for entry in uncovered)
    safety = evaluate(safety_medicines, PatientFacts(patient.age, patient.weight_kg, tuple(patient.allergies)))
    rows = []
    for event in safety:
        item_id = next((item.id for item, ingredient, _, _ in resolved if ingredient.name == event.medicine), None)
        if item_id is None and resolved and event.type != "uncovered":
            item_id = resolved[0][0].id
        row = SafetyEventRow(encounter_id=prescription.encounter_id, prescription_item_id=item_id,
            type=event.type, severity=event.severity, message=event.message, shown_at=now,
            acknowledged=False, acknowledged_by=None, acknowledged_at=None, override_reason=None)
        session.add(row)
        rows.append(row)
    session.flush()
    return resolved, uncovered, rows


def persist_draft(
    session: Session,
    *,
    patient: PatientInput,
    doctor: DoctorInput,
    diagnosis: str | None,
    mode: str,
    source: str,
    medicines: list[MedicineDraft],
) -> dict:
    """Shared draft persistence + safety orchestration for every mode.

    Resolves each medicine brand->generic, runs the deterministic safety engine on
    generics only, records append-only safety events + audit, and returns the review
    payload. Uncovered medicines surface a "verify manually" event (never hard-blocked,
    never a false pass)."""
    now = utcnow()

    doctor_row = Doctor(
        name=doctor.name, registration_no=doctor.registration_no, preferences={}
    )
    patient_row = Patient(
        name=patient.name,
        age=patient.age,
        dob=None,
        sex=patient.sex,
        weight_kg=patient.weight_kg,
        contact=patient.contact,
    )
    session.add_all((doctor_row, patient_row))
    session.flush()
    encounter = Encounter(
        patient_id=patient_row.id,
        doctor_id=doctor_row.id,
        mode=mode,
        status="draft",
        recording_consent=False,
        consent_at=None,
        started_at=now,
        ended_at=now,
        diagnosis=diagnosis,
    )
    session.add(encounter)
    session.flush()
    prescription = Prescription(
        encounter_id=encounter.id,
        status="draft",
        signed_by=None,
        signed_registration_no=None,
        signed_at=None,
        pdf_url=None,
        locked=False,
    )
    session.add(prescription)
    session.flush()

    resolved, uncovered, safety_rows = _resolve_and_check(
        session, prescription, patient, medicines, now
    )
    medicines_json = _render_medicines(session, resolved, uncovered)
    session.add(
        AuditLog(
            actor_id=doctor_row.id,
            action="prescription_drafted",
            entity_type="prescription",
            entity_id=prescription.id,
            before=None,
            after={
                "source": source,
                "diagnosis": diagnosis,
                "patient": patient.model_dump(),
                "medicines": medicines_json,
                "safety_event_ids": [row.id for row in safety_rows],
            },
            at=now,
        )
    )
    session.commit()

    return {
        "prescription_id": prescription.id,
        "encounter_id": encounter.id,
        "patient": patient.model_dump(),
        "diagnosis": diagnosis,
        "medicines": medicines_json,
        "safety_events": _events_json(session, prescription),
        "signed": False,
    }


def _create_voice_draft(payload: DraftInput, session: Session, text: str) -> dict:
    corrected = correct_drug_names(text, session)
    matched_brand = _matching_brand(corrected, session)
    fake_draft = _fake_draft(corrected, matched_brand)
    minimized_text = minimize_clinical_text(corrected, payload.patient)
    llm = get_llm_provider(fake_responses={minimized_text: fake_draft})
    clinical = strip_pii(
        {
            "patient_name": payload.patient.name,
            "patient_id": payload.patient.patient_id,
            "contact": payload.patient.contact,
            "clinical_text": minimized_text,
        }
    )["clinical_text"]
    draft = llm.extract_prescription(clinical, "voice")
    return persist_draft(
        session,
        patient=payload.patient,
        doctor=payload.doctor,
        diagnosis=draft.diagnosis,
        mode="voice",
        source="voice",
        medicines=list(draft.medicines),
    )


@router.post("/mode2/draft")
def create_draft(payload: DraftInput, session: Session = Depends(get_session)):
    return _create_voice_draft(payload, session, payload.text)


@router.post("/mode2/audio-draft")
async def create_audio_draft(
    audio: UploadFile = File(...),
    patient: str = Form(...),
    doctor: str = Form(...),
    session: Session = Depends(get_session),
):
    try:
        patient_input = PatientInput.model_validate(json.loads(patient))
        doctor_input = DoctorInput.model_validate(json.loads(doctor))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise HTTPException(422, "patient and doctor must be valid JSON") from exc
    transcript = get_stt_provider(session).transcribe(
        await audio.read(), audio.content_type or "application/octet-stream"
    )
    return _create_voice_draft(
        DraftInput(text=transcript.text, patient=patient_input, doctor=doctor_input),
        session,
        transcript.text,
    )


@router.post("/manual/draft")
def create_manual_draft(payload: ManualDraftInput, session: Session = Depends(get_session)):
    medicines = _medicine_drafts(payload.medicines)
    return persist_draft(
        session,
        patient=payload.patient,
        doctor=payload.doctor,
        diagnosis=payload.diagnosis,
        mode="manual",
        source="manual",
        medicines=medicines,
    )


@router.patch("/prescriptions/{prescription_id}/draft")
def edit_draft(
    prescription_id: str,
    payload: EditDraftInput,
    session: Session = Depends(get_session),
):
    prescription = session.get(Prescription, prescription_id)
    if prescription is None:
        raise HTTPException(404, "Prescription not found")
    if prescription.locked or prescription.status == "signed":
        raise HTTPException(409, "Signed prescriptions are locked")
    encounter = session.get(Encounter, prescription.encounter_id)
    patient_row = session.get(Patient, encounter.patient_id)
    doctor = session.get(Doctor, encounter.doctor_id)
    previous = session.scalar(
        select(AuditLog)
        .where(AuditLog.entity_id == prescription.id, AuditLog.action.in_(("prescription_drafted", "prescription_edited")))
        .order_by(AuditLog.at.desc(), AuditLog.id.desc())
    )
    previous_data = previous.after if previous and isinstance(previous.after, dict) else {}
    previous_patient = previous_data.get("patient", {})
    patient = PatientInput(
        name=patient_row.name, patient_id=previous_patient.get("patient_id"), age=patient_row.age,
        sex=patient_row.sex, weight_kg=float(patient_row.weight_kg) if patient_row.weight_kg is not None else None,
        contact=patient_row.contact, allergies=previous_patient.get("allergies", []),
    )
    now = utcnow()
    resolved, uncovered, safety_rows = _resolve_and_check(
        session, prescription, patient, _medicine_drafts(payload.medicines), now
    )
    medicines_json = _render_medicines(session, resolved, uncovered)
    old_medicines = previous_data.get("medicines", [])
    encounter.diagnosis = payload.diagnosis if payload.diagnosis is not None else encounter.diagnosis
    session.add(
        AuditLog(
            actor_id=doctor.id,
            action="prescription_edited",
            entity_type="prescription",
            entity_id=prescription.id,
            before={"diagnosis": previous_data.get("diagnosis"), "medicines": old_medicines},
            after={
                "source": "edit", "diagnosis": encounter.diagnosis, "patient": patient.model_dump(),
                "medicines": medicines_json, "safety_event_ids": [row.id for row in safety_rows],
            },
            at=now,
        )
    )
    session.commit()
    return {
        "prescription_id": prescription.id, "encounter_id": encounter.id,
        "patient": patient.model_dump(), "diagnosis": encounter.diagnosis,
        "medicines": medicines_json, "safety_events": _events_json(session, prescription), "signed": False,
    }


@router.get("/catalog")
def catalog(session: Session = Depends(get_session)):
    """Brands and generics come from the DB only — no hardcoded drug names."""
    brands = []
    for brand in session.scalars(select(BrandCatalog).order_by(BrandCatalog.brand_name)):
        ingredient = session.get(Formulary, brand.ingredient_id)
        brands.append(
            {
                "brand_name": brand.brand_name,
                "ingredient": ingredient.ingredient_name if ingredient else None,
                "strength": brand.strength,
                "form": brand.form,
            }
        )
    generics = [
        row.ingredient_name
        for row in session.scalars(select(Formulary).order_by(Formulary.ingredient_name))
    ]
    return {"brands": brands, "generics": generics}


@router.post("/prescriptions/{prescription_id}/acknowledge")
def acknowledge(
    prescription_id: str,
    payload: AcknowledgeInput,
    session: Session = Depends(get_session),
):
    prescription = session.get(Prescription, prescription_id)
    if prescription is None:
        raise HTTPException(404, "Prescription not found")
    if prescription.locked:
        raise HTTPException(409, "Signed prescriptions are locked")
    doctor = _doctor_for(session, prescription, payload.doctor_name, payload.registration_no)
    rows = {row.id: row for row in _event_rows(session, prescription) if not row.acknowledged}
    if set(payload.event_ids) - rows.keys():
        raise HTTPException(404, "Safety event not found")
    now = utcnow()
    for event_id in payload.event_ids:
        original = rows[event_id]
        session.add(
            SafetyEventRow(
                encounter_id=original.encounter_id,
                prescription_item_id=original.prescription_item_id,
                type=original.type,
                severity=original.severity,
                message=original.message,
                shown_at=now,
                acknowledged=True,
                acknowledged_by=doctor.id,
                acknowledged_at=now,
                override_reason=payload.reason,
            )
        )
    session.commit()
    return {"safety_events": _events_json(session, prescription)}


@router.post("/prescriptions/{prescription_id}/sign")
def sign(prescription_id: str, payload: SignInput, session: Session = Depends(get_session)):
    prescription = session.get(Prescription, prescription_id)
    if prescription is None:
        raise HTTPException(404, "Prescription not found")
    if prescription.locked or prescription.status == "signed":
        raise HTTPException(409, "Signed prescriptions are locked")
    doctor = _doctor_for(session, prescription, payload.doctor_name, payload.registration_no)
    pending = [event for event in _events_json(session, prescription) if not event["acknowledged"]]
    if pending:
        return JSONResponse(
            status_code=409,
            content={"detail": "acknowledgment_required", "safety_events": pending},
        )
    encounter = session.get(Encounter, prescription.encounter_id)
    patient = session.get(Patient, encounter.patient_id)
    snapshot = session.scalar(
        select(AuditLog)
        .where(AuditLog.entity_id == prescription.id, AuditLog.action.in_(("prescription_drafted", "prescription_edited")))
        .order_by(AuditLog.at.desc(), AuditLog.id.desc())
    )
    snapshot_medicines = (snapshot.after or {}).get("medicines", []) if snapshot else []
    items = list(session.scalars(select(PrescriptionItem).where(PrescriptionItem.prescription_id == prescription.id)))
    pdf_medicines = snapshot_medicines or [
        {
            "ingredient": session.get(Formulary, item.ingredient_id).ingredient_name,
            "strength": item.strength,
            "dose": item.dose,
            "frequency": item.frequency,
            "duration": item.duration,
        }
        for item in items
    ]
    now = utcnow()
    path = _pdf_path(prescription.id)
    lines = [
        "PRESCRIPTION",
        f"Patient: {patient.name}",
        f"Diagnosis: {encounter.diagnosis or ''}",
        *[
            f"{medicine.get('ingredient') or medicine.get('brand') or medicine.get('name') or 'Unknown medicine'} {medicine.get('strength') or ''} - {medicine.get('dose') or ''}, {medicine.get('frequency') or ''}, {medicine.get('duration') or ''}"
            for medicine in pdf_medicines
        ],
        f"Signed by: {doctor.name}",
        f"Registration: {doctor.registration_no}",
        f"Signed at UTC: {now.isoformat()}Z",
    ]
    write_pdf(path, lines)
    prescription.status = "signed"
    prescription.signed_by = doctor.id
    prescription.signed_registration_no = doctor.registration_no
    prescription.signed_at = now
    prescription.pdf_url = f"/api/prescriptions/{prescription.id}/pdf"
    prescription.locked = True
    encounter.status = "signed"
    session.add(
        AuditLog(
            actor_id=doctor.id,
            action="prescription_signed",
            entity_type="prescription",
            entity_id=prescription.id,
            before={"status": "draft", "locked": False},
            after={"status": "signed", "locked": True, "signed_at": now.isoformat()},
            at=now,
        )
    )
    session.commit()
    return {"signed": True, "signed_at": now.isoformat() + "Z", "pdf_url": prescription.pdf_url}


@router.get("/prescriptions/{prescription_id}/pdf")
def prescription_pdf(prescription_id: str, session: Session = Depends(get_session)):
    prescription = session.get(Prescription, prescription_id)
    if prescription is None or not prescription.locked:
        raise HTTPException(404, "Signed PDF not found")
    path = _pdf_path(prescription_id)
    if not path.is_file():
        raise HTTPException(404, "Signed PDF not found")
    return FileResponse(path, media_type="application/pdf", filename=f"prescription-{prescription_id}.pdf")


# ── Mode 3: ambient conversation ──────────────────────────────────────────────
# Consent-gated recording → diarized live transcript over WebSocket → one
# full-context extraction at "End encounter", with each medicine linked to the
# transcript segment(s) that justify it. Resolve/safety/ack/sign reuse Mode 2.


class ConsentInput(BaseModel):
    patient: PatientInput
    doctor: DoctorInput
    consent: bool = False


def _speaker_label(speaker) -> str:
    """Map a provider speaker tag to a rail label. Fake STT emits Doctor/Patient;
    Deepgram diarization emits 0/1."""
    if speaker is None:
        return "Speaker"
    text = str(speaker).strip().casefold()
    if text in ("doctor", "0", "speaker 0", "speaker0"):
        return "Doctor"
    if text in ("patient", "1", "speaker 1", "speaker1"):
        return "Patient"
    return str(speaker).strip().title()


def _link_evidence(name: str | None, segments: list[dict]) -> list[str]:
    """Deterministically link a medicine to the transcript segments that name it
    (normalized token match). Not the LLM's job to invent segment ids — a name that
    appears nowhere in the conversation stays unlinked → 'missing context'."""
    key = " ".join(_normal_parts(name or ""))
    if not key:
        return []
    return [seg["id"] for seg in segments if key in " ".join(_normal_parts(seg["text"]))]


def _ambient_draft(segments: list[dict], session: Session) -> dict:
    """Heuristic extraction over the whole conversation (doubles as the fake-LLM
    response so the keyless demo works; the real path is OpenAI structured outputs)."""
    full = " ".join(seg["text"] for seg in segments)
    seen: set[str] = set()
    medicines = []
    for seg in segments:
        brand = _matching_brand(seg["text"], session)
        if brand is None or brand.brand_name in seen:
            continue
        seen.add(brand.brand_name)
        medicines.append(_fake_draft(seg["text"], brand)["medicines"][0])
    return {
        "diagnosis": "headache" if "headache" in full.casefold() else None,
        "patient_facts": {},
        "medicines": medicines,
    }


def _extract_ambient(segments: list[dict], patient: PatientInput, session: Session):
    full = " ".join(seg["text"] for seg in segments)
    minimized = minimize_clinical_text(full, patient)
    llm = get_llm_provider(fake_responses={minimized: _ambient_draft(segments, session)})
    clinical = strip_pii(
        {
            "patient_name": patient.name,
            "patient_id": patient.patient_id,
            "contact": patient.contact,
            "clinical_text": minimized,
        }
    )["clinical_text"]
    return llm.extract_prescription(clinical, "ambient")


def _ambient_patient(session: Session, encounter: Encounter) -> PatientInput:
    """Rebuild the patient facts (allergies live in the consent snapshot, not the
    patients row) so end-of-encounter safety runs on the same inputs Mode 2 uses."""
    patient_row = session.get(Patient, encounter.patient_id)
    consent = session.scalar(
        select(AuditLog)
        .where(AuditLog.entity_id == encounter.id, AuditLog.action == "recording_consent_captured")
        .order_by(AuditLog.at.desc(), AuditLog.id.desc())
    )
    stored = consent.after.get("patient", {}) if consent and isinstance(consent.after, dict) else {}
    return PatientInput(
        name=patient_row.name,
        patient_id=stored.get("patient_id"),
        age=patient_row.age,
        sex=patient_row.sex,
        weight_kg=float(patient_row.weight_kg) if patient_row.weight_kg is not None else None,
        contact=patient_row.contact,
        allergies=stored.get("allergies", []),
    )


def _attach_evidence(medicines_json: list[dict], resolved: list, segments: list[dict]) -> None:
    by_item = {
        item.id: (list(item.evidence_segment_ids or []), item.evidence_status)
        for item, _, _, _ in resolved
    }
    for med in medicines_json:
        if med["id"] in by_item:
            ids, status = by_item[med["id"]]
        else:  # uncovered medicine has no item row — recompute from its name
            name = med.get("brand") or med.get("ingredient") or med.get("name") or ""
            ids = _link_evidence(name, segments)
            status = "linked" if ids else "missing_context"
        med["evidence_segment_ids"] = ids
        med["evidence_status"] = status


def _coverage(medicines_json: list[dict]) -> dict:
    total = len(medicines_json)
    linked = sum(1 for med in medicines_json if med["evidence_status"] == "linked")
    missing = total - linked
    label = f"{linked} of {total} linked"
    if missing:
        label += f" · {missing} missing context"
    return {"total": total, "linked": linked, "missing": missing, "label": label}


def persist_ambient_draft(
    session: Session,
    *,
    encounter: Encounter,
    patient: PatientInput,
    diagnosis: str | None,
    segments: list[dict],
    medicines: list[MedicineDraft],
) -> dict:
    now = utcnow()
    encounter.ended_at = now
    encounter.diagnosis = diagnosis if diagnosis is not None else encounter.diagnosis
    doctor_row = session.get(Doctor, encounter.doctor_id)
    prescription = Prescription(
        encounter_id=encounter.id, status="draft", signed_by=None,
        signed_registration_no=None, signed_at=None, pdf_url=None, locked=False,
    )
    session.add(prescription)
    session.flush()
    resolved, uncovered, safety_rows = _resolve_and_check(
        session, prescription, patient, medicines, now
    )
    medicines_json = _render_medicines(session, resolved, uncovered)
    _attach_evidence(medicines_json, resolved, segments)
    session.add(
        AuditLog(
            actor_id=doctor_row.id,
            action="prescription_drafted",
            entity_type="prescription",
            entity_id=prescription.id,
            before=None,
            after={
                "source": "ambient",
                "diagnosis": encounter.diagnosis,
                "patient": patient.model_dump(),
                "medicines": medicines_json,
                "safety_event_ids": [row.id for row in safety_rows],
            },
            at=now,
        )
    )
    session.commit()
    return {
        "prescription_id": prescription.id,
        "encounter_id": encounter.id,
        "patient": patient.model_dump(),
        "diagnosis": encounter.diagnosis,
        "medicines": medicines_json,
        "safety_events": _events_json(session, prescription),
        "transcript": segments,
        "coverage": _coverage(medicines_json),
        "signed": False,
    }


@router.post("/mode3/consent")
def start_ambient_encounter(payload: ConsentInput, session: Session = Depends(get_session)):
    """Per-encounter consent gate. No consent → no encounter, so no recording."""
    if not payload.consent:
        raise HTTPException(422, "Recording consent is required before an ambient encounter can start.")
    now = utcnow()
    doctor_row = Doctor(name=payload.doctor.name, registration_no=payload.doctor.registration_no, preferences={})
    patient_row = Patient(
        name=payload.patient.name, age=payload.patient.age, dob=None, sex=payload.patient.sex,
        weight_kg=payload.patient.weight_kg, contact=payload.patient.contact,
    )
    session.add_all((doctor_row, patient_row))
    session.flush()
    encounter = Encounter(
        patient_id=patient_row.id, doctor_id=doctor_row.id, mode="ambient", status="draft",
        recording_consent=True, consent_at=now, started_at=now, ended_at=None, diagnosis=None,
    )
    session.add(encounter)
    session.flush()
    session.add(TranscriptRow(encounter_id=encounter.id, segments=[]))
    session.add(
        AuditLog(
            actor_id=doctor_row.id, action="recording_consent_captured", entity_type="encounter",
            entity_id=encounter.id, before=None,
            after={"recording_consent": True, "consent_at": now.isoformat(), "patient": payload.patient.model_dump()},
            at=now,
        )
    )
    session.commit()
    return {"encounter_id": encounter.id, "consent_at": now.isoformat() + "Z", "recording_consent": True}


@router.websocket("/mode3/encounters/{encounter_id}/stream")
async def stream_ambient(
    websocket: WebSocket, encounter_id: str, session: Session = Depends(get_session)
):
    """Live diarized transcript. Each audio (or, for the keyless demo, text) frame is
    transcribed, drug-name-corrected, appended as a segment, and echoed back labeled."""
    await websocket.accept()
    encounter = session.get(Encounter, encounter_id)
    if encounter is None or not encounter.recording_consent:
        await websocket.send_json({"error": "consent_required"})
        await websocket.close(code=1008)
        return
    transcript = session.scalar(
        select(TranscriptRow).where(TranscriptRow.encounter_id == encounter_id)
    )
    if transcript is None:
        transcript = TranscriptRow(encounter_id=encounter_id, segments=[])
        session.add(transcript)
        session.flush()
    stt = get_stt_provider(session)
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            payload = message.get("bytes")
            if payload is None:
                payload = (message.get("text") or "").encode()
            for chunk in stt.stream(payload):
                corrected = correct_drug_names(chunk.text, session)
                if not corrected.strip():
                    continue
                segments = list(transcript.segments or [])
                char_start = sum(len(seg["text"]) + 1 for seg in segments)
                segment = {
                    "id": f"seg-{len(segments)}",
                    "speaker": _speaker_label(chunk.speaker),
                    "text": corrected,
                    "t_start": chunk.start,
                    "t_end": chunk.end,
                    "char_start": char_start,
                    "char_end": char_start + len(corrected),
                }
                segments.append(segment)
                transcript.segments = segments  # reassign so SQLAlchemy sees the JSON change
                session.commit()
                await websocket.send_json({"segment": segment})
    except WebSocketDisconnect:
        pass


@router.post("/mode3/encounters/{encounter_id}/end")
def end_ambient_encounter(encounter_id: str, session: Session = Depends(get_session)):
    encounter = session.get(Encounter, encounter_id)
    if encounter is None or encounter.mode != "ambient":
        raise HTTPException(404, "Ambient encounter not found")
    if encounter.status == "signed":
        raise HTTPException(409, "Signed prescriptions are locked")
    transcript = session.scalar(
        select(TranscriptRow).where(TranscriptRow.encounter_id == encounter_id)
    )
    segments = list(transcript.segments or []) if transcript else []
    patient = _ambient_patient(session, encounter)
    draft = _extract_ambient(segments, patient, session)
    medicines = [
        replace(md, evidence_segment_ids=tuple(_link_evidence(md.brand or md.ingredient, segments)))
        for md in draft.medicines
    ]
    return persist_ambient_draft(
        session, encounter=encounter, patient=patient,
        diagnosis=draft.diagnosis, segments=segments, medicines=medicines,
    )
