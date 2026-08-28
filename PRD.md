# PRD — AI Prescription Tool (POC)

**Status:** POC / clinical pilot planning
**Last updated:** 2026-08-28
**Market:** India (outpatient clinics)
**Companion docs:** `architecture.md` (full technical design), `architecture-essentials.md` (condensed), `claude.md` (build guidance), `key_essentials.md` (keys/accounts)

---

## 1. Vision

A prescription assistant for Indian doctors that turns what is **said** during a consultation into a **safe, structured, signed prescription** — while keeping the doctor fully in control.

The doctor never loses authority. The tool drafts, checks, and warns; the doctor reviews, edits, and signs. It is **clinical decision support, not a decision maker**.

Three ways to create a prescription, in increasing ambition:

1. **Manual** — type it (baseline, always available).
2. **Voice dictation (DEFAULT)** — doctor narrates intent ("patient has a headache, needs Dolo 650"); the form fills itself.
3. **Ambient conversation (THE SELLING POINT)** — the tool listens to the whole doctor–patient visit, separates who said what, and produces a draft prescription where **every medicine is linked back to the exact thing that was said**.

---

## 2. Who it's for

- **Primary user:** an outpatient doctor (GP / physician) in an Indian clinic, seeing patients in person.
- **Secondary:** clinic staff who register patients.
- **Not in scope for v1:** patients as direct users, pharmacists, remote/telemedicine consults.

---

## 3. Core principles (non-negotiable)

| Principle | What it means in the product |
|---|---|
| Doctor in control | The tool never hard-blocks a prescription. It warns and requires acknowledgment. |
| No false safety | If a drug is outside our verified data, we say "not checked — verify manually", never a green tick. |
| Never hardcode brands | Brand names always come from a live catalog, never baked into code. |
| Minimize PII exposure | Patient identifiers are stripped before any external AI call. |
| Everything is auditable | Every AI suggestion, every warning, every acknowledgment, every signature is logged immutably. |
| Traceable decisions | In Mode 3, every prescribed medicine traces back to a transcript line. |

---

## 4. The three input modes

```
  Mode 1: MANUAL            Mode 2: VOICE DICTATION (default)     Mode 3: AMBIENT (selling point)
  ┌──────────────┐          ┌──────────────────────────┐         ┌────────────────────────────────┐
  │ doctor types │          │ doctor narrates intent   │         │ tool records the whole visit   │
  │ every field  │          │ "headache, Dolo 650"     │         │ diarized (Doctor vs Patient)   │
  │              │          │ → 1 short utterance      │         │ → transcript streams live      │
  │              │          │ → LLM extracts 1 med     │         │ → at end: LLM extracts         │
  │              │          │ → form fills             │         │   diagnosis + meds + EVIDENCE  │
  └──────────────┘          └──────────────────────────┘         └────────────────────────────────┘
        │                            │                                        │
        └────────────────────────────┴────────────────────────────────────────┘
                                      ▼
                     Same review screen: AI-staged draft
                     Safety checks run → warnings shown
                     Doctor edits → Approve & Sign → locked Rx + PDF
```

### Mode 2 — Voice dictation (DEFAULT)
- Doctor speaks a directive. Short. One or a few medicines.
- Speech → text → LLM extracts structured fields (generic, brand, strength, form, route, dose, frequency, duration, instructions).
- Form fills; doctor reviews and edits.

### Mode 3 — Ambient conversation (SELLING POINT)
- Doctor taps **Start**; recording begins **only after per-encounter consent is captured**.
- Audio streams; transcript appears live with **Doctor / Patient** labels (speaker diarization).
- On **End encounter**, the full transcript goes through one extraction pass producing:
  - a diagnosis suggestion,
  - a medicine list,
  - **evidence links**: each medicine points to the transcript segment(s) that justify it.
- Unjustified medicines raise a **"Missing context"** warning. A coverage meter shows **"N of N medicines linked"**.

### Processing model (applies to Modes 2 & 3)
- **Live transcript** during the visit (cheap, and it looks impressive).
- **Extraction runs once, at the end, with full context** (accurate and safe).
- No fully-live field-filling in v1 — it is fragile and less accurate mid-sentence.

---

## 5. Safety engine (the clinical core)

Runs on the **generic ingredient**, not the brand. Indian brand → resolve to ingredient → check.

### 5.1 Checks performed
| Check | What it catches | Example |
|---|---|---|
| **Dose** | Single dose or daily total above safe limit | 1300 mg paracetamol single dose (max ~1000 mg / ~4000 mg per day) |
| **Interaction** | Dangerous drug–drug pairs, severity-graded | Warfarin + NSAID |
| **Allergy** | Prescribing something the patient is allergic to, incl. the whole drug class | Penicillin allergy → any beta-lactam |
| **Age** | Age-inappropriate drug or dose | Adult dose for a child |

### 5.2 Coverage — bounded curated formulary
- We hand-verify the **~100–200 outpatient drugs the pilot doctors actually prescribe** against authoritative sources (BNF, Indian National Formulary, drug labels).
- Each carries: max single dose, max daily dose (weight-aware mg/kg where relevant), age limits, interaction rules, allergy class.
- **Outside the formulary:** the tool shows *"Not in safety database — please verify manually."* It never fakes a green check.

### 5.3 Fail behavior — warn, never block
- Every issue is a **warning the doctor must explicitly acknowledge** before signing.
- The tool **never prevents** a licensed doctor from prescribing.
- **Every warning and every acknowledgment is logged** (which warning, doctor, timestamp, override reason). This audit trail *is* the safety story — see §7.

---

## 6. Personalization

- **Per-doctor brand memory:** the AI suggests a generic (Paracetamol); the system remembers this doctor's preferred brand (Dr X → Dolo 650) and auto-fills it next time. Editable via a dropdown **sourced from the brand catalog** — never hardcoded.
- **Templates:** reusable prescription sets for common presentations (matches the "Templates" nav in the reference UI).

---

## 7. Compliance & data handling

| Requirement | How we meet it |
|---|---|
| **DPDP Act 2023** (data protection) | Patient consent; PII minimized before AI calls; India-region hosting path; access controls. |
| **Telemedicine Practice Guidelines 2020** | Prescription carries doctor name + medical registration number + timestamp; immutable once signed. |
| **Recording consent (Mode 3)** | Captured **per encounter, before recording starts**; timestamped on the record. No consent → no recording. |
| **Audit trail** | Immutable log of AI suggestions, edits, warnings, acknowledgments, signatures. |
| **Future ABDM integration** | Database is FHIR-aligned (R4 concepts) so national-stack integration is a migration, not a rewrite. |

**PII posture:** before any external AI (STT / LLM) call, strip patient name, ID, and contact details. Send only clinical content; re-attach identifiers locally from our own database. Operate under a data-processing agreement with each vendor.

---

## 8. Signing

- **Approve & Sign** captures the signing doctor's **name + medical registration number + timestamp**, locks the prescription immutable, and generates a **PDF**.
- v1 uses a simple e-sign (not a cryptographic DSC / Aadhaar eSign — that is a later upgrade).

---

## 9. Scope

### In scope (v1)
- In-person outpatient encounters.
- All three input modes.
- Safety engine over the curated formulary.
- Per-doctor brand memory + templates.
- Evidence-linking in Mode 3.
- Per-encounter consent, e-sign, PDF, audit trail.

### Out of scope (v1)
- Telemedicine / remote consults.
- Full FHIR resource storage (only FHIR-*aligned* tables).
- Cryptographic digital signatures (DSC / Aadhaar eSign).
- Universal drug coverage (only the curated formulary).
- Pharmacy dispensing, billing, lab orders.
- Patient-facing app.

---

## 10. Success criteria (pilot)

- A doctor can complete a real in-person encounter end-to-end in each mode.
- Mode 2 fills the form correctly for a single-drug dictation ≥ 90% of the time (pilot target, to be measured).
- Mode 3 produces a draft where every medicine is evidence-linked, and diarization correctly separates doctor from patient in typical clinic audio.
- The safety engine correctly flags the seeded danger cases (e.g. 1300 mg paracetamol, a known-allergy hit, a severe interaction).
- Zero prescriptions signed without the audit trail capturing the full decision path.

---

## 11. Open questions / top risks

Ranked — the first is the one to lose sleep over.

1. **Drug-data sourcing is unfinished (BIG ONE).** No licensed provider is chosen and India has no free interaction API (NLM RxNav killed Jan 2024; DrugBank's free checker retires Mar 2026). The pilot's safety quality depends entirely on the curated formulary until a vendor is picked. **Action:** evaluate DrugBank / First Databank / Medi-Span pricing (see `key_essentials.md`) and lock the curated formulary content early. **Untested:** we have not yet validated any candidate against Indian brands.
2. **Speaker diarization accuracy in real clinic audio (Mode 3).** The selling point depends on cleanly separating doctor from patient with background noise, accents, and cross-talk. **Untested** on real Indian clinic recordings. **Action:** record a few consented real encounters and measure diarization error before over-promising.
3. **Drug-name recognition for Indian brands.** ASR mis-hears "Ambroxol", "Mucosolvan". We add a fuzzy-match post-correction against the catalog, but this is **untested** at scale. **Action:** build a test set of dictated Indian brand names and measure correction accuracy.
4. **Brand→generic resolution for Indian brands.** RxNorm does **not** contain Indian brands; we need an Indian catalog (e.g. DataRequisite) whose coverage/licensing is **not yet confirmed**. **Action:** trial a catalog source and check coverage of the pilot formulary.
5. **DPDP residency for external AI calls.** Sending clinical text to OpenAI/Deepgram (US) relies on consent + DPA + data-minimization for the pilot. Acceptable at pilot scale; a self-hosted path is documented for scale. **Not a blocker for a consented pilot, but do not skip the DPA.**

---

## 12. Reference UI

The design reference ("Evidence Rail" mockup) establishes the target layout: left transcript-evidence rail, center patient + diagnosis + prescription form, right safety-status panel (interaction / allergy / dose / age checks, warnings, evidence coverage, clinical reminders), and an **AI-staged draft → Approve & Sign** flow with *"Review required. You are in control."*
