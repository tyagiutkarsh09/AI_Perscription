# Provider, Safety, and Mode 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver Steps 3–5: swappable providers, deterministic safety checks, and the signed Mode 2 dictation flow.

**Architecture:** Keep vendor calls in provider adapters, convert DB rows to small immutable safety records, and run a pure safety function over those records. A single FastAPI workflow endpoint creates the draft and warnings; acknowledgment and signing endpoints append logs, lock the prescription, and emit a small PDF. The React SPA consumes only those endpoints.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, stdlib `difflib`/`re`/PDF bytes, React 19, Vite.

**Spec:** `architecture.md` §§3.2, 4, 5; `design.md` §§2–11; user-provided Steps 3–5.

## Global Constraints

- Brands come only from `brand_catalog`; safety runs only on resolved generic ingredients.
- Uncovered medicine copy is exactly “Not in safety database — verify manually.” and never represents a pass.
- Safety is deterministic and contains no LLM calls.
- External LLM text has patient name, ID, and contact removed first.
- Signing never hard-blocks; warnings require logged acknowledgment before the same action proceeds.
- Signed prescriptions are locked, PDF-backed, and audited; `safety_events` and `audit_log` remain append-only.
- No new dependency where Python/browser native functionality is enough.

---

### Task 1: Provider contracts and curated provider

**Files:**
- Create: `backend/app/providers.py`
- Test: `backend/tests/test_providers.py`
- Modify: `backend/app/config.py`

**Interfaces:**
- Produces: `STTProvider`, `LLMProvider`, `DrugKnowledgeProvider`, `FakeSTT`, `FakeLLM`, `DeepgramSTT`, `OpenAILLM`, `CuratedDrugKnowledge`, `get_stt_provider`, `get_llm_provider`, `get_drug_knowledge_provider`, and immutable provider result records.

- [ ] Write provider tests covering deterministic fake results, exact brand resolution from seeded DB rows, dose limits, pairwise interaction, class allergy conflict, uncovered lookup, PII stripping, and env selection.
- [ ] Run `..\.python\python.exe -m pytest tests/test_providers.py -q` from `backend`; confirm missing-module/API failures.
- [ ] Implement the protocols and minimal DB-backed/provider adapters. Use `httpx` for Deepgram/OpenAI REST calls and OpenAI `response_format.type=json_schema` with `strict=true`.
- [ ] Re-run the provider test and existing suite.

### Task 2: Pure deterministic safety engine

**Files:**
- Create: `backend/app/safety.py`
- Test: `backend/tests/test_safety.py`

**Interfaces:**
- Consumes: immutable ingredient, dose-rule, interaction, and allergy-conflict records from Task 1.
- Produces: `Medicine`, `PatientFacts`, `SafetyEvent`, and `evaluate(medicines, patient, knowledge) -> list[SafetyEvent]`.

- [ ] Write the five required danger/coverage tests with hand-derived literal expectations: 1300 mg single paracetamol severe; 650 mg twice daily no dose event; penicillin/amoxicillin severe; warfarin/ibuprofen severe; unknown drug uncovered with verify-manually copy. Add one weight and one age boundary test so those requested branches can regress independently.
- [ ] Run `..\.python\python.exe -m pytest tests/test_safety.py -q`; confirm the import/API fails.
- [ ] Implement minimal single/daily/weight/age, pairwise interaction, class allergy, and uncovered branches. Emit events only for non-pass states.
- [ ] Re-run the danger tests and full backend suite.

### Task 3: Mode 2 extraction workflow and persistence

**Files:**
- Create: `backend/app/mode2.py`
- Create: `backend/app/pdf.py`
- Test: `backend/tests/test_mode2.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: provider selectors and `evaluate`.
- Produces: `POST /api/mode2/draft`, `POST /api/prescriptions/{id}/acknowledge`, `POST /api/prescriptions/{id}/sign`, and `GET /api/prescriptions/{id}/pdf`.

- [ ] Write an integration test that seeds SQLite, submits “patient has a headache, give Dolo 650, twice daily for 3 days”, and asserts diagnosis, catalog-backed brand/generic, 650 mg single and 1300 mg daily, and no false warning.
- [ ] Add warning acknowledgment and signing tests: signing with outstanding warnings returns the warning gate; acknowledgment appends `safety_events`; signing then snapshots doctor identity/time, locks rows, emits `%PDF` bytes, and appends `audit_log`; a second mutation/sign attempt is rejected.
- [ ] Run the test and confirm endpoint failures.
- [ ] Implement a stdlib fuzzy correction, orchestration service, dependency-injected SQLAlchemy session, minimal valid PDF writer, and endpoints.
- [ ] Re-run the Mode 2 and full backend suites.

### Task 4: Mode 2 clinical console

**Files:**
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/index.css`
- Modify: `frontend/vite.config.js`

**Interfaces:**
- Consumes: Task 3 JSON endpoints.

- [ ] Build the paste/record-ready dictation view and review console with patient header, diagnosis, editable Rx card, Safety Rail, sticky sign bar, acknowledgment sheet, signed lock state, and PDF link.
- [ ] Use only the exact `design.md` tokens, IBM Plex Sans/Mono roles, text+icon safety states, keyboard focus, reduced motion, and responsive safety visibility.
- [ ] Run `npm run build`; fix only compile/accessibility issues found.

### Task 5: End-to-end verification

**Files:**
- Modify: `README.md`
- Modify: `.env.example`

- [ ] Document `STT_BACKEND=fake|deepgram`, `LLM_BACKEND=fake|openai`, and `DRUGKNOWLEDGE_BACKEND=curated`, plus local run and example dictation.
- [ ] Run `..\.python\python.exe -m pytest tests -q` from `backend` and capture all five named safety cases in output.
- [ ] Run `npm run build` from `frontend`.
- [ ] Re-read the user’s Done-when clauses and inspect the final diff/file list for direct vendor imports outside adapters, hardcoded brands outside seed/test data, false pass copy, or writable signed data.
