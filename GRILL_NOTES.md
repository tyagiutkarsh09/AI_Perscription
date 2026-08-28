# GRILL_NOTES — AI Prescription Tool POC

Working record of design decisions from the grill-me interview.
Goal of the session: produce the POC planning docs (architecture.md,
architecture-essentials.md, claude.md, key_essentials.md, PRD.md).

---

## Checkpoint 1 — 2026-08-28

### Decisions resolved

1. **Market = India.** Screenshot brands (Crocin, Mucosolvan) are Indian; dosing in mg.
   Drives which drug-data sources are usable.

2. **POC depth = clinical pilot with real doctors.** Not a throwaway demo. Means real
   PII, real safety stakes, real regulatory surface (DPDP Act 2023, Telemedicine
   Guidelines 2020). Safety data cannot be mocked.

3. **Safety-data sourcing = interface now, decide backend later.** India has NO unified
   drug index and NO interaction API (NLM RxNav killed Jan 2024; DrugBank free checker
   retires Mar 25 2026). Forced architecture: Indian brand (display) → resolve to generic
   ingredient → run interaction/dose/allergy checks on the INGREDIENT via an international
   drug-knowledge base. Build a swappable `DrugKnowledgeProvider`; start free, license later.
   PRD must carry a vendor/price table (DrugBank / First Databank / Medi-Span / openFDA+RxNorm+DDInter).

4. **Budget = exists, amount unscoped.** PRD lists vendors + price tiers so a number can be picked.

5. **Processing model = hybrid: live transcript + on-end extraction.** Transcript streams
   live during the visit (cheap, impressive); safety-critical field extraction runs once at
   "end encounter" with full context (accurate, robust). Skip fully-live form-filling for v1.

6. **STT engine = Deepgram nova-3** (streaming + diarization + medical; user knows it).
   Hosted for pilot under consent + DPA; self-hosted/India-region documented for scale/DPDP.
   Whisper = free fallback behind an STT interface. Drug-name post-correction (fuzzy-match
   against brand catalog) runs regardless of engine.

### Input modes (clarified by user)

- **Mode 1 — Manual.** Doctor types the prescription directly. Baseline.
- **Mode 2 — Voice dictation (DEFAULT).** Doctor narrates an intent: "patient has headache,
  needs Dolo 650" → one short utterance → LLM extracts → form fills. Doctor-led, fast.
- **Mode 3 — Ambient conversation (SELLING POINT).** Doctor starts streaming; whole
  doctor-patient conversation captured with diarization; at end, LLM extracts diagnosis +
  meds + links each to transcript evidence lines → AI-staged draft for review.

### Locked architecture shape

Indian brand (UI) → resolve to generic/RxCUI → safety engine runs on ingredient.
Two data feeds: (a) India brand catalog (cheap/commercial), (b) safety engine (licensed-later).

### Open branches (with recommended default)

- **Tech stack** — rec: React/Next.js + Node or Python backend + Postgres, India-region host.
- **Schema modeling standard** — rec: pragmatic custom tables, FHIR-aligned naming, not full FHIR.
- **Recording consent flow (Mode 3)** — legal gate; must capture consent per encounter. Requirement, not optional.
- **Evidence-linking** — each extracted med links to transcript line(s); needs offsets stored.
- **Brand personalization** — doctor templates / favorite brands per generic; "Templates" nav in screenshot.
- **Dose-safety rules** — how max-dose detection works (1300mg paracetamol); per-ingredient limits, weight/age aware.
- **LLM choice for extraction** — rec: Claude; confirm + PII posture.
- **Compliance** — DPDP Act, Telemedicine Guidelines, e-prescription rules, audit trail.

### Next questions

- Tech stack + schema modeling standard (coupled: stack constrains DB).
- Then: consent/compliance requirements, evidence-linking, dose-rule design, personalization.

---

## Checkpoint 2 — 2026-08-28

### Decisions resolved (continued)

7. **Stack = React + Python (FastAPI) + Postgres.** Python backend also hosts Whisper
   fallback + drug-name fuzzy matching. Deepgram/OpenAI/drug-APIs are all API calls.

8. **Schema = custom Postgres tables, FHIR-aligned naming** (Patient, Encounter,
   MedicationRequest, AllergyIntolerance concepts). Eases future ABDM/FHIR R4 migration; no FHIR overhead now.

9. **Safety coverage = bounded curated formulary.** Hand-verify ~100–200 outpatient drugs
   the pilot doctors prescribe, against BNF / Indian National Formulary / labels. Outside the
   set → "not in safety DB, manual check required" (fail-safe, no false assurance).

10. **Fail behavior = warn + mandatory acknowledgment, NEVER block.** Tool is clinical
    decision *support*, not decision maker. Doctor always in control. CONSEQUENCE: the audit
    trail IS the safety story — every warning shown + every acknowledgment (who/when/which
    warning/override reason) recorded immutably. First-class `safety_events` table.

11. **Extraction LLM = OpenAI**, behind an LLM-provider interface (Claude/self-host swappable).
    Use Structured Outputs (JSON-schema-guaranteed) to fill prescription fields reliably.
    OpenAI API: not trained on by default; ZDR (zero data retention) available on request — supports DPDP posture.

12. **PII posture = minimize.** Strip patient name/ID/contact before the LLM call; send clinical
    text only; re-attach identifiers locally from own DB. Plus DPA + patient consent.

### Open branches (with recommended default)

- **Brand personalization** — rec: per-doctor brand memory (Paracetamol→Dolo for Dr X) + reusable templates.
- **Evidence-linking (Mode 3)** — rec: every med links to transcript segment; warn if unlinked ("2 of 2 linked").
- **Recording consent (Mode 3)** — requirement: capture per-encounter consent before recording. Minor: granularity.
- **Compliance/audit** — DPDP Act 2023, Telemedicine Guidelines 2020, e-prescription rules, immutable audit.
- **Dose-rule data model** — per-ingredient max single + max daily dose, weight (mg/kg) + age aware.

### Next questions

- Brand personalization scope + evidence-linking requirement (product features cluster).
- Then wrap: confirm consent/compliance requirements, then write the 5 docs.

---

## Final Checkpoint — 2026-08-28 — FULL RESOLVED DESIGN TREE

13. **Recording consent = per-encounter, before recording starts.** Captured + timestamped on
    the encounter; Mode 3 cannot record without it.
14. **Rx signing = simple e-sign.** Signing doctor's name + medical registration number +
    timestamp; locks the Rx immutable; generates PDF. (Not DSC/Aadhaar eSign for v1.)
15. **Encounter scope = in-person only for v1.** No telemedicine/remote-consult rules. Mode 3
    records in-room audio.

### THE COMPLETE PICTURE

**Product:** AI prescription tool for Indian outpatient clinics. Clinical pilot with real doctors.
Doctor-in-control clinical decision *support*. Three input modes:
- Mode 1 Manual (type it)
- Mode 2 Voice dictation — DEFAULT — doctor narrates intent ("headache, Dolo 650") → form fills
- Mode 3 Ambient conversation — SELLING POINT — records whole visit, diarized, extracts draft + evidence links

**Data flow (locked):** Indian brand (UI display) → resolve to generic ingredient via Indian brand
catalog → run ALL safety checks (interaction / dose / allergy) on the ingredient via an international
drug-knowledge base. RxNorm does NOT hold Indian brands — brand→generic needs an Indian catalog first.

**Stack:** React front + Python FastAPI backend + Postgres. India-region hosting for residency.

**Three swappable provider interfaces (all "decide backend later"):**
- STT: Deepgram nova-3 (streaming + diarization + medical) primary; Whisper self-host fallback.
  + drug-name post-correction (fuzzy-match vs brand catalog) regardless of engine.
- LLM extraction: OpenAI (Structured Outputs / JSON schema) primary; interface allows Claude/self-host.
  PII minimized (strip identifiers, send clinical text only) + DPA + consent.
- DrugKnowledge: free-now (openFDA + RxNorm + DDInter + curated) / licensed-later (DrugBank/FDB/Medi-Span).

**Processing:** live streaming transcript during visit (cheap + impressive) + single full-context
extraction at "end encounter" (accurate + safe). No fully-live form-filling in v1.

**Safety engine:** bounded curated formulary (~100–200 outpatient drugs, hand-verified against
BNF / Indian National Formulary / labels). Per-ingredient max single + max daily dose, weight (mg/kg)
+ age aware. Interactions pairwise severity-graded. Allergy via drug-class (ATC) cross-sensitivity.
Outside formulary → "not in safety DB, manual check". FAIL BEHAVIOR: warn + mandatory acknowledgment,
NEVER block. Audit trail is the safety story — immutable safety_events log.

**Personalization:** per-doctor brand memory (remembers Dr X: Paracetamol→Dolo 650, auto-fills) +
reusable Rx templates. Brands always sourced from catalog, never hardcoded.

**Evidence-linking:** every extracted med stores justifying transcript segment(s); "View in transcript";
unlinked meds → "Missing context" warning; "N of N linked" coverage meter.

**Compliance:** DPDP Act 2023 (consent + PII minimization + residency path), Telemedicine Guidelines
2020 (identifiable signed Rx), per-encounter recording consent, immutable audit trail. Schema
FHIR-aligned for future ABDM (FHIR R4) integration.

### Interview status: COMPLETE. Proceeding to write the 5 POC docs.
