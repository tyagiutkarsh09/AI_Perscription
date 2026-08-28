# Architecture Essentials — AI Prescription Tool (POC)

Condensed from `architecture.md`. Read this for fast context; read the full doc only for schema/API detail.

## What it is
AI prescription assistant for Indian outpatient doctors. Clinical pilot. Doctor-in-control **decision support** — drafts, checks, warns; doctor edits and signs. Three input modes:
- **Manual** — type it.
- **Voice dictation (DEFAULT)** — doctor narrates ("headache, Dolo 650") → form fills.
- **Ambient (SELLING POINT)** — records whole visit, diarized, extracts draft with each medicine linked to the transcript line that justifies it.

## Stack
React (frontend) · Python FastAPI (backend) · MySQL 8 · India-region hosting.

## The one flow that governs everything
```
Indian brand (UI)  →  brand catalog  →  generic ingredient (RxCUI)  →  safety checks run HERE
"Crocin 650"          resolve            "Paracetamol"                  dose/interaction/allergy
```
RxNorm has **no Indian brands** — resolve brand→generic with an Indian catalog first, then check safety on the generic internationally. **Never check safety on the brand. Never hardcode brands.**

## Processing model
Live streaming transcript during the visit (cheap, impressive) + **one full-context extraction at "End encounter"** (accurate, safe). No fully-live form-filling in v1.

## Three swappable provider interfaces (all "decide backend later")
| Interface | Primary | Fallback / later | Note |
|---|---|---|---|
| STT | Deepgram nova-3 (stream + diarization + medical) | Whisper self-host | + drug-name fuzzy post-correction vs catalog, always |
| LLM extraction | OpenAI (Structured Outputs) | Claude / self-host | PII stripped before call; ZDR requested |
| DrugKnowledge | curated formulary + openFDA + RxNorm + DDInter | DrugBank / FDB / Medi-Span | licensed vendor TBD |

## Safety engine (deterministic, no LLM)
- Runs on the **generic ingredient**.
- Checks: dose (max single + max daily, weight/age aware), interaction (pairwise, graded), allergy (by ATC drug class), age.
- Coverage: **bounded curated formulary** (~100–200 hand-verified pilot drugs). Outside it → *"not in safety DB, verify manually"* (never a false green tick).
- **Fail behavior: warn + mandatory acknowledgment, NEVER block.** The immutable `safety_events` log IS the safety story.
- Danger example: 1300 mg paracetamol single dose fires (limit ~1000 mg single / ~4000 mg daily).

## Personalization
Per-doctor brand memory (remembers Dr X: Paracetamol→Dolo, auto-fills) + reusable Rx templates. Brands from catalog only.

## Evidence-linking (Mode 3)
Every medicine stores justifying transcript segment(s); "View in transcript"; unlinked → "Missing context" warning; "N of N linked" meter.

## Schema (FHIR-aligned, not full FHIR)
Core: `doctors, patients, patient_allergies, encounters, transcripts, prescriptions, prescription_items, safety_events`.
Reference: `formulary, brand_catalog, interactions, allergy_classes`.
Audit: `audit_log` (append-only, immutable).

## Compliance
DPDP Act 2023 (consent + PII minimization + residency path), Telemedicine Guidelines 2020 (identifiable signed Rx: name + registration no. + timestamp, immutable, PDF), per-encounter recording consent (Mode 3 gate), immutable audit trail. FHIR-aligned for future ABDM.

## Scope v1: IN
In-person only · all 3 modes · curated-formulary safety · brand memory + templates · evidence-linking · consent · e-sign · PDF · audit.

## Scope v1: OUT
Telemedicine · full FHIR · DSC/Aadhaar eSign · universal drug coverage · hard blocks · fully-live form-filling · patient app · pharmacy/billing/labs.

## Top risk
Drug-data sourcing unfinished + no free India interaction API (RxNav dead since Jan 2024). Safety quality rides on the curated formulary until a licensed vendor is picked. Diarization + Indian-brand ASR accuracy are **untested** on real clinic audio.
