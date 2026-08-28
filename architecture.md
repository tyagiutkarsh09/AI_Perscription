# Architecture — AI Prescription Tool (POC)

**Last updated:** 2026-08-28
**Condensed version for quick reading:** `architecture-essentials.md`
**Product context:** `PRD.md`

---

## 1. Stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | React (SPA) | Matches the reference UI; rich interactive review screen |
| Backend | Python + FastAPI | Clean home for audio handling, Whisper fallback, drug-name matching; async-friendly for streaming |
| Database | MySQL 8 | Relational clinical data; strong constraints; JSON columns where needed |
| Hosting | India region (for residency path) | DPDP Act; keep patient data in-country where possible |

External services are all **API calls behind interfaces** (see §4): Deepgram (STT), OpenAI (LLM), a drug-knowledge provider (TBD).

---

## 2. High-level components

```
                        ┌─────────────────────────────────────────────┐
                        │                 React SPA                    │
                        │  Encounter screen · live transcript rail ·   │
                        │  Rx form · safety-status panel · sign+PDF     │
                        └───────────────┬──────────────────────────────┘
                                        │  REST + WebSocket (live transcript)
                        ┌───────────────▼──────────────────────────────┐
                        │              FastAPI backend                  │
                        │                                               │
                        │  ┌──────────┐  ┌──────────────┐  ┌─────────┐  │
                        │  │ Encounter│  │  Extraction  │  │ Safety  │  │
                        │  │ service  │  │  service     │  │ engine  │  │
                        │  └────┬─────┘  └──────┬───────┘  └────┬────┘  │
                        │       │               │               │       │
                        │  ┌────▼─────┐   ┌─────▼──────┐  ┌──────▼────┐  │
                        │  │ STT      │   │ LLM        │  │ DrugKnow- │  │
                        │  │ provider │   │ provider   │  │ ledge     │  │
                        │  │ iface    │   │ iface      │  │ provider  │  │
                        │  └────┬─────┘   └─────┬──────┘  └──────┬────┘  │
                        └───────┼───────────────┼───────────────┼───────┘
                                │               │               │
                          Deepgram/Whisper   OpenAI          free-now /
                          + name-correction  (Structured     licensed-later
                                              Outputs)        (§4.3, §7)
                                        │
                             ┌──────────▼──────────┐
                             │       MySQL 8       │
                             │  patients, encounters,
                             │  prescriptions, safety_events,
                             │  formulary, brand catalog, audit
                             └─────────────────────┘
```

---

## 3. Data flow per mode

### 3.1 The locked brand→generic→safety flow (all modes)

```
  Indian brand (UI display)      brand catalog        generic ingredient       international
  "Crocin 650"            ──▶   (Indian source)  ──▶  "Paracetamol" + RxCUI ──▶ drug-knowledge base
   doctor sees the brand         resolve                normalized id            runs dose/interaction/allergy
```

**Why two hops:** RxNorm (the free normalization service) contains **US** drugs — Indian brands like Crocin are **not** in it. So we resolve the Indian brand to its generic with an **Indian catalog first**, then use the generic to look up safety data internationally. Never run safety checks on the brand.

### 3.2 Mode 2 — Voice dictation

```
  mic ─▶ STT provider ─▶ text ─▶ drug-name post-correction ─▶ LLM extract (1 utterance)
                                                                      │
                                                      structured Rx fields ─▶ form
                                                                      │
                                                            safety engine ─▶ warnings
```

**Detailed walk-through** — example utterance: *"Patient has a headache, give Dolo 650, twice daily for 3 days."*

```
  Doctor taps VOICE mode, speaks
         │
         ▼
  ┌─────────────────────────────┐
  │ Deepgram STT (streaming)     │   heard: "...dollo 650 twice daily three days"
  └─────────────┬───────────────┘
                ▼
  ┌─────────────────────────────┐
  │ Drug-name post-correction    │   fuzzy-match vs brand_catalog (RapidFuzz)
  │                              │   "dollo" ─fix─ "Dolo 650"
  └─────────────┬───────────────┘
                ▼
  ┌─────────────────────────────┐
  │ Strip PII before LLM         │   remove name/id/contact; send clinical text only
  └─────────────┬───────────────┘
                ▼
  ┌─────────────────────────────┐
  │ OpenAI (Structured Outputs)  │   → { brand:"Dolo 650", dose:"1 tablet",
  │ extract Rx fields (JSON)     │       freq:"twice daily", duration:"3 days" }
  └─────────────┬───────────────┘
                ▼
  ┌─────────────────────────────┐
  │ Resolve brand → generic      │   Dolo 650 ─(brand_catalog)─ Paracetamol 650 mg + RxCUI
  └─────────────┬───────────────┘
                ▼
          in curated formulary?
                │
        ┌───────┴────────┐
        │yes             │no
        ▼                ▼
  ┌──────────────────┐  ┌──────────────────────────────┐
  │ Safety engine    │  │ "Not in safety DB —          │
  │ on Paracetamol:  │  │  verify manually" (never a    │
  │  dose 650 single │  │  false green tick)            │
  │   ≤1000 ✓        │  └───────────────┬──────────────┘
  │  1300/day ≤4000 ✓│                  │
  │  interaction: none (single drug) ✓  │
  │  allergy: check patient list        │
  │  age 28 ✓        │                   │
  └────────┬─────────┘                   │
           ▼                             │
       warnings?                         │
           │                             │
     ┌─────┴─────┐                       │
     │yes        │no                     │
     ▼           │                       │
   show +        │                       │
   REQUIRE ack ──┤                       │
   (→ safety_events)                     │
     │           ▼                       ▼
     └───▶ ┌──────────────────────────────────┐
           │ Form fills (AI-staged draft)      │
           │ apply doctor brand memory         │
           └─────────────┬────────────────────┘
                         ▼
                Doctor reviews / edits
                         │
                         ▼
           ┌──────────────────────────────┐
           │ Approve & Sign               │   name + registration no. + timestamp
           │ → lock Rx + generate PDF     │   immutable
           └─────────────┬────────────────┘
                         ▼
              audit_log + safety_events written
```

> Note: safety runs on **Paracetamol**, not the brand. "1300" appears twice with opposite meaning — 650mg × twice = **1300 mg/day (safe, ≤4000)**, versus the danger case of **1300 mg in a single dose (unsafe, >1000)**. The engine keeps single-dose and daily-total as separate limits.

### 3.3 Mode 3 — Ambient conversation

```
  DURING VISIT (streaming)                          ON "END ENCOUNTER" (batch, full context)
  ┌───────────────────────────────┐                ┌──────────────────────────────────────┐
  │ audio ─▶ STT (streaming+diariz)│                │ full transcript ─▶ LLM extract        │
  │ ─▶ partial transcript          │  ──────────▶   │   · diagnosis                         │
  │ ─▶ WebSocket ─▶ live rail      │                │   · medicines[]                       │
  │   (Doctor/Patient labels)      │                │   · evidence: transcript segment refs │
  └───────────────────────────────┘                │ ─▶ drug-name correction ─▶ resolve    │
                                                    │ ─▶ safety engine ─▶ warnings          │
                                                    │ ─▶ AI-staged draft + evidence links   │
                                                    └──────────────────────────────────────┘
```

**Consent gate:** recording cannot start until per-encounter consent is captured (§6, PRD §7).

---

## 4. Provider interfaces (all swappable — "decide backend later")

Each external dependency sits behind a Python interface so the backend can start free/simple and upgrade without rewrites.

### 4.1 STT provider
```python
class STTProvider(Protocol):
    def stream(self, audio) -> Iterator[TranscriptChunk]: ...   # live, diarized
    def transcribe(self, audio_file) -> Transcript: ...          # batch, best accuracy
```
- **Primary:** Deepgram nova-3 — streaming + speaker diarization + medical model; team has experience. Hosted for pilot (consent + DPA); self-hosted / India-region documented for scale.
- **Fallback:** self-hosted Whisper (large-v3) + WhisperX/pyannote for diarization — free, full residency, more assembly.
- **Always:** a **drug-name post-correction** pass that fuzzy-matches STT output against the brand catalog (no ASR gets "Ambroxol" right every time).

### 4.2 LLM provider (extraction)
```python
class LLMProvider(Protocol):
    def extract_prescription(self, clinical_text, mode) -> PrescriptionDraft: ...
```
- **Primary:** OpenAI, using **Structured Outputs** (JSON-schema-guaranteed) so the model must return valid prescription fields.
- Interface allows swapping to Claude or a self-hosted model later.
- **PII minimization:** strip patient name / ID / contact before the call; send clinical content only; re-attach identifiers locally. OpenAI API does not train on API data by default; request **Zero Data Retention** for the pilot.

### 4.3 DrugKnowledge provider (safety data)
```python
class DrugKnowledgeProvider(Protocol):
    def resolve_brand(self, brand) -> Ingredient: ...            # Indian brand → generic + code
    def dose_limits(self, ingredient, age, weight) -> DoseRule: ...
    def interactions(self, ingredients) -> list[Interaction]: ...
    def allergy_conflicts(self, ingredients, allergies) -> list[Conflict]: ...
```
- **Free-now backend:** curated formulary tables (§5) + openFDA labels + RxNorm normalization + open academic interaction set (DDInter).
- **Licensed-later backend:** DrugBank / First Databank / Medi-Span (§7 candidates).
- Outside the curated set → returns "not covered", surfaced as *"verify manually"*, never a false pass.

---

## 5. Safety engine

Pure function over the drafted medicine list + patient facts (age, weight, allergies). Deterministic, testable, no LLM in the safety path.

```
  inputs                          engine                         output
  ┌────────────────┐   ┌──────────────────────────────┐   ┌──────────────────────┐
  │ medicines[]    │   │ for each med:                 │   │ warnings[]           │
  │ patient age    │──▶│  · in formulary? else "uncov" │──▶│  {type, severity,    │
  │ patient weight │   │  · dose vs max single/daily   │   │   message, med, must_│
  │ allergies[]    │   │  · age/weight appropriateness │   │   acknowledge}       │
  └────────────────┘   │ for each pair: interaction    │   │ coverage: n/n linked │
                       │ for each med × allergy: class │   └──────────────────────┘
                       └──────────────────────────────┘
```

**Dose rule model (per ingredient):** `max_single_dose`, `max_daily_dose`, `mg_per_kg` (optional, for weight-based), `min_age`, `max_age`, `notes`. The 1300 mg paracetamol case: single-dose limit ~1000 mg, daily ~4000 mg → 1300 mg single dose fires a warning.

**Allergy cross-sensitivity:** grouped by drug class (ATC classification). Penicillin allergy blocks the whole beta-lactam class, not just the one drug.

**Fail behavior:** every warning is override-able but **requires explicit acknowledgment**; the acknowledgment is written to `safety_events`. Nothing is ever hard-blocked.

---

## 6. Database schema (MySQL 8, FHIR-aligned naming)

Real relational tables, named after FHIR R4 concepts so a future ABDM/FHIR migration is a mapping, not a rewrite. Not full FHIR resources.

**MySQL 8 type mapping** (the conceptual types below → MySQL): `jsonb → JSON`; `text[] / int[] → JSON array` (or a junction table if you need to query members); `timestamptz → DATETIME` storing UTC; `uuid → CHAR(36)` (or `BINARY(16)`). SQLAlchemy + Alembic handle the dialect; driver is `mysql+pymysql`.

```
  doctors ──< encounters >── patients
                  │
                  ├──< transcripts (segments) ──< (evidence links) ──┐
                  │                                                   │
                  └──< prescriptions ──< prescription_items >─────────┘
                                              │        │
                                              │        └── brand (from brand_catalog)
                                              │        └── ingredient (from formulary)
                                              │
                                          safety_events (immutable)

  reference/data tables:  formulary · brand_catalog · interactions · allergy_classes
  audit:                  audit_log (immutable, append-only)
```

### 6.1 Core tables

**doctors**
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| name | text | |
| registration_no | text | medical council registration; printed on signed Rx |
| preferences | JSON | per-doctor brand memory: `{ingredient_id: brand_id}` |

**patients**  (FHIR: Patient)
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| name | text | PII — stripped before external AI calls |
| age / dob | int / date | drives age checks |
| sex | text | |
| weight_kg | numeric | drives weight-based dosing |
| contact | text | PII |

**patient_allergies**  (FHIR: AllergyIntolerance)
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| patient_id | uuid FK | |
| ingredient_id | uuid FK nullable | specific drug, or... |
| allergy_class | text nullable | ...a whole class (e.g. "penicillins") |
| note | text | |

**encounters**  (FHIR: Encounter)
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| patient_id | uuid FK | |
| doctor_id | uuid FK | |
| mode | enum | manual / voice / ambient |
| status | enum | draft / signed |
| recording_consent | bool | Mode 3 gate |
| consent_at | timestamptz | when consent captured |
| started_at / ended_at | timestamptz | |
| diagnosis | text | doctor's assessment |

**transcripts**
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| encounter_id | uuid FK | |
| segments | JSON | ordered `[{speaker, text, t_start, t_end, char_start, char_end}]` |

**prescriptions**  (FHIR: MedicationRequest set)
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| encounter_id | uuid FK | |
| status | enum | draft / signed |
| signed_by | uuid FK doctor | |
| signed_registration_no | text | snapshot at signing |
| signed_at | timestamptz | |
| pdf_url | text | generated on sign |
| locked | bool | immutable once signed |

**prescription_items**  (one medicine)
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| prescription_id | uuid FK | |
| ingredient_id | uuid FK → formulary | the generic; safety runs on this |
| brand_id | uuid FK → brand_catalog nullable | display brand, from catalog |
| strength | text | e.g. "650 mg" |
| form | text | tablet / syrup |
| route | text | oral |
| dose | text | "1 tablet" |
| frequency | text | "every 6–8 h" |
| duration | text | "3 days" |
| instructions | text | |
| evidence_segment_ids | JSON | transcript segment refs (Mode 3) |
| evidence_status | enum | linked / missing_context |

**safety_events**  (immutable — the safety story)
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| encounter_id | uuid FK | |
| prescription_item_id | uuid FK nullable | |
| type | enum | dose / interaction / allergy / age / uncovered |
| severity | enum | info / warning / severe |
| message | text | what was shown to the doctor |
| shown_at | timestamptz | |
| acknowledged | bool | |
| acknowledged_by | uuid FK doctor | |
| acknowledged_at | timestamptz | |
| override_reason | text | |

### 6.2 Reference / data tables

**formulary** (curated, hand-verified — the safety source of truth for v1)
`id, ingredient_name, atc_class, max_single_dose, max_daily_dose, mg_per_kg, min_age, max_age, forms (JSON array), notes, verified_by, verified_at, source`

**brand_catalog** (Indian brands — sourced, never hardcoded)
`id, brand_name, ingredient_id FK, strength, form, manufacturer, source`

**interactions** (pairwise)
`id, ingredient_a FK, ingredient_b FK, severity, description, management, source`

**allergy_classes**
`id, class_name (ATC), member_ingredient_ids (JSON array, or a junction table)`

**audit_log** (append-only, immutable)
`id, actor_id, action, entity_type, entity_id, before JSON, after JSON, at DATETIME(UTC)`

---

## 7. External data sources — candidates (the API/library research)

**The reality:** India has no unified drug index and no free interaction API. The free NLM RxNav Drug Interaction API was **discontinued Jan 2024**; DrugBank's free checker **retires 25 Mar 2026**. So structured, graded interaction data means a **licensed** source or a **curated** one.

### 7.1 Interactions / dose / allergy (the safety engine backends)

| Source | Type | Coverage | Status / cost | Verdict |
|---|---|---|---|---|
| **Curated formulary (ours)** | Hand-built | ~100–200 pilot drugs | Free, our labor | **v1 primary** — trustworthy, bounded |
| **openFDA drug labels** | Free API | US labels, interactions as prose | Free | Supplement — unstructured text, needs parsing |
| **RxNorm / RxNav (RxCUI, RxClass, ATC)** | Free API | Normalization + drug classes | Free, alive | **Use** for generic normalization + allergy classes |
| **DDInter** | Free academic DB (CC-BY) | ~drug–drug interactions | Free download | Seed the interactions table; verify before clinical use |
| **DrugBank** | Licensed API | Broad, graded, well-modeled | Paid; free checker ends Mar 2026 | Strong licensed-later candidate |
| **First Databank (FDB)** | Licensed | Enterprise clinical | Paid | Licensed-later candidate |
| **Medi-Span (Wolters Kluwer)** | Licensed | Enterprise clinical | Paid | Licensed-later candidate |
| **Micromedex (Merative)** | Licensed | Enterprise clinical | Paid | Licensed-later candidate |

### 7.2 Indian brand catalog (brand→generic display layer)

| Source | Notes |
|---|---|
| **DataRequisite Indian Medicine DB** | Claims ~6 lakh medicines, 33 fields; commercial — **verify licensing + coverage** |
| **CDSCO published data / National Formulary of India** | Official but not a clean API; needs ingestion |
| **1mg / Netmeds** | No official public API; scraping not acceptable for a clinical pilot |

> All of §7 licensing, pricing, and coverage figures are **candidates to verify**, not confirmed picks. See `key_essentials.md` for what to sign up for.

### 7.3 Speech + LLM
- **Deepgram** — STT (streaming, diarization, medical). Python SDK.
- **OpenAI** — extraction via Structured Outputs. Python SDK.
- **Whisper (large-v3) + WhisperX/pyannote** — free self-hosted STT fallback.
- **RapidFuzz** (Python) — fuzzy matching for drug-name post-correction.

---

## 8. Deployment & residency

```
  Pilot (now)                              Scale (documented path)
  ┌──────────────────────────┐            ┌──────────────────────────┐
  │ India-region cloud host  │            │ + Deepgram self-hosted    │
  │ MySQL in-region          │   ──────▶  │ + self-hosted LLM option  │
  │ Deepgram/OpenAI hosted   │            │ + full in-country only    │
  │  under DPA + consent +   │            │   (no external AI calls)  │
  │  PII minimization        │            │                          │
  └──────────────────────────┘            └──────────────────────────┘
```

For the consented pilot, external hosted AI (Deepgram/OpenAI) under a DPA with PII minimization is acceptable. The interfaces (§4) make the fully-in-country version a backend swap, not a rewrite.

---

## 9. What this design deliberately does NOT do (v1)

- No telemedicine / remote consults.
- No cryptographic digital signature (simple e-sign only).
- No universal drug coverage (curated formulary + "verify manually" outside it).
- No full FHIR resources (FHIR-aligned tables only).
- No fully-live form-filling (live transcript + end-of-visit extraction instead).
- No hard blocks (warn + acknowledge only).
