# CODEX_PROMPTS.md — how to drive Codex to build this

Build in slices. Paste ONE step, let Codex finish, check the "Done when" box yourself, then paste the next. Don't ask for the whole app at once — it's a clinical tool and each slice must be verified.

## One-time setup (do this first)

```
cp claude.md AGENTS.md
```

Codex auto-reads `AGENTS.md`, so the non-negotiable rules load on every run without re-pasting.

## The rules Codex must never break (already in AGENTS.md — restated so you can spot violations)

1. Never hardcode brand names — always from `brand_catalog`.
2. Safety checks run on the generic ingredient, never the brand.
3. Never hard-block a prescription — warn + require acknowledgment, log it.
4. Never show a false safety pass — outside the formulary = "verify manually".
5. Strip patient PII before any external AI call.
6. Mode 3 recording needs per-encounter consent first.
7. Signed prescriptions are immutable; every action is audited.
8. Don't assert drug-vendor pricing/coverage as fact — it's unverified.

---

## STEP 1 — Scaffold

```
Read AGENTS.md, architecture-essentials.md, and PRD.md before writing anything.

Build STEP 1 ONLY: project scaffold. Nothing clinical yet.
- Backend: Python + FastAPI. Frontend: React (Vite). DB: MySQL 8 (driver mysql+pymysql).
- Config from .env via pydantic-settings (see .env.example). No hardcoded secrets.
- One GET /health endpoint returning {"status":"ok"}.
- A React page that calls /health and shows the result.
- docker-compose.yml running MySQL 8 locally.
- A README with run instructions.

Stop after `docker-compose up` + the dev servers run and I can load the page and see
"ok". Do not build prescription logic. Wait for my go on STEP 2.
```
**Done when:** page shows "ok", MySQL is up, README explains how to run.

---

## STEP 2 — Schema + seed data

```
Build STEP 2 ONLY: database schema + seed data. Follow architecture.md §6 exactly.

- SQLAlchemy models + Alembic migrations for ALL tables:
  doctors, patients, patient_allergies, encounters, transcripts, prescriptions,
  prescription_items, safety_events, formulary, brand_catalog, interactions,
  allergy_classes, audit_log.
- FHIR-aligned naming as documented. safety_events and audit_log are append-only.
- MySQL 8 types (per architecture.md §6): jsonb→JSON, arrays→JSON, uuid→CHAR(36), timestamptz→DATETIME storing UTC.
- Seed ~20 common Indian outpatient drugs into `formulary` with real, well-established
  dose limits (max single, max daily, weight/age fields). Cite the source in a comment
  for each (BNF / label / National Formulary of India). Do NOT invent limits — if unsure
  of a value, leave it null and add a TODO for clinician verification.
- Seed `brand_catalog` with a handful of real brand→generic rows (e.g. Crocin, Dolo,
  Calpol → Paracetamol; Brufen → Ibuprofen; Mox → Amoxicillin).
- Seed `interactions` with a few well-known pairs (e.g. warfarin+NSAID) with severity.
- Seed `allergy_classes` with at least "penicillins" and its members.

Stop after migrations apply cleanly and seeds load. Print row counts. Wait for STEP 3.
```
**Done when:** `alembic upgrade head` works, seed script loads, row counts print. Every seeded dose limit has a source comment or a TODO.

---

## STEP 3 — Provider interfaces

```
Build STEP 3 ONLY: the three swappable provider interfaces (architecture.md §4).

- Define Python Protocols: STTProvider, LLMProvider, DrugKnowledgeProvider.
- Implement CuratedDrugKnowledge (reads formulary/brand_catalog/interactions/
  allergy_classes from the DB). resolve_brand, dose_limits, interactions,
  allergy_conflicts. Outside the formulary → return "uncovered", never a pass.
- Implement a FAKE deterministic STTProvider and LLMProvider for offline tests
  (fixed input → fixed structured output).
- Implement real adapters: DeepgramSTT and OpenAILLM (OpenAI Structured Outputs /
  JSON schema), selected by env var. Strip PII before the OpenAI call.
- Selection via env: STT_BACKEND, LLM_BACKEND, DRUGKNOWLEDGE_BACKEND.

Stop after the fake providers work and unit tests for CuratedDrugKnowledge pass
(including an uncovered-drug case). Wait for STEP 4.
```
**Done when:** business logic never imports Deepgram/OpenAI directly — only the interface. Uncovered-drug returns "verify manually".

---

## STEP 4 — Safety engine (+ danger tests)

```
Build STEP 4 ONLY: the deterministic safety engine (architecture.md §5). No LLM here.

- Pure function: evaluate(medicines, patient) -> list[SafetyEvent].
- Checks: dose (max single AND max daily, weight mg/kg + age aware), interaction
  (pairwise from the table, severity-graded), allergy (by ATC class, not just exact
  drug), age, and uncovered (not in formulary).
- Output SafetyEvent {type, severity, message, medicine, must_acknowledge}. Plain-language
  messages per design.md §8.

Write tests that MUST fail if the logic breaks:
- 1300 mg paracetamol single dose  -> severe (limit ~1000 single / ~4000 daily).
- 650 mg paracetamol twice daily    -> passes (1300 mg/day is under 4000).
- Patient allergic to penicillins, prescribed amoxicillin -> severe (class match).
- Warfarin + ibuprofen              -> interaction warning/severe.
- A drug not in the formulary       -> uncovered ("verify manually").

Stop after all tests pass. Show the test output. Wait for STEP 5.
```
**Done when:** all five cases pass, test output shown. Single-dose vs daily-total are separate limits.

---

## STEP 5 — Mode 2 end-to-end (the default mode, build first)

```
Build STEP 5 ONLY: Mode 2 (voice dictation) end-to-end. Follow architecture.md §3.2
and design.md exactly for the UI.

Backend flow:
  dictation text (or audio -> STT) -> drug-name post-correction (fuzzy-match vs
  brand_catalog, e.g. RapidFuzz) -> strip PII -> LLM extract (structured Rx fields) ->
  resolve brand->generic -> safety engine -> return draft + warnings.

Frontend (per design.md):
  - Dictation screen (record / paste text for now).
  - Review screen: patient header, diagnosis, Rx item card(s), Safety Rail, sign bar.
  - AI-filled fields get the --accent-weak wash. Doses/IDs in Plex Mono tabular.
  - Safety Rail rows with correct states; acknowledgment is a GATE not a block:
    Approve & Sign is always enabled; unacknowledged warnings open an acknowledgment
    sheet; acknowledging writes to safety_events; then signing proceeds.
  - Approve & Sign captures doctor name + registration no. + timestamp, locks the Rx,
    generates a PDF, writes audit_log.

Use IBM Plex Sans + Plex Mono. Color = signal only (design.md §2).

Stop after I can dictate "patient has a headache, give Dolo 650, twice daily for 3 days",
see the form fill, see the safety rail, acknowledge if needed, and sign to a locked PDF.
Wait for STEP 6.
```
**Done when:** the example dictation runs the whole flow to a signed PDF + audit entry, and the UI matches `design.md` tokens.

---

## STEP 6 — Mode 1 manual

```
Build STEP 6 ONLY: Mode 1 (manual). Reuse the STEP 5 review screen with an empty form the
doctor fills by hand. Same safety engine, same acknowledgment gate, same sign flow.
Stop when a fully hand-typed prescription can be checked and signed. Wait for STEP 7.
```
**Done when:** manual entry reuses the same review/safety/sign path — no duplicated logic.

---

## STEP 7 — Mode 3 ambient (the selling point, hardest, last)

```
Build STEP 7 ONLY: Mode 3 (ambient conversation). Follow architecture.md §3.3.

- Per-encounter consent gate: recording cannot start without captured, timestamped consent.
- Streaming STT with speaker diarization (Deepgram) over WebSocket -> live transcript rail
  with Doctor/Patient labels (design.md left rail).
- On "End encounter": ONE full-context LLM extraction -> diagnosis + medicines[] +
  evidence links (transcript segment refs per medicine).
- Evidence coverage meter ("N of N linked"); unlinked medicines -> "Missing context" warning.
- Then the same resolve -> safety -> acknowledge -> sign path as Mode 2.

Stop when a recorded (consented) mock conversation produces an evidence-linked draft that
can be reviewed and signed. Show diarization + evidence links working.
```
**Done when:** consent gates recording, transcript streams diarized, every medicine links to a transcript segment, unlinked ones warn.

---

> Steps 1–7 give a **working app on your machine**. Steps 8–11 make it **pilot-grade**.
> The human items in `PILOT_READINESS.md` (formulary sign-off, DPA, security) still gate go-live — Codex cannot do those.

---

## STEP 8 — Auth + roles

```
Build STEP 8 ONLY: authentication + authorization. No clinical PII endpoint may be
reachable without it.

- Doctor login: email + password, hashed with argon2/bcrypt. Session via secure,
  httpOnly cookie (or JWT). Logout.
- Roles: doctor and admin (admin manages formulary + users). Enforce RBAC on every endpoint.
- A doctor sees only their own encounters/patients unless admin.
- signed_by, acknowledged_by, and audit_log.actor come from the authenticated session,
  NEVER from client input.
- Seed one admin + one doctor for dev.

Stop after login works and an unauthenticated request to any clinical endpoint is refused
(401). Show that. Wait for STEP 9.
```
**Done when:** nothing clinical is reachable without auth; actor identity comes from the session, not the request body.

---

## STEP 9 — Deploy (India region)

```
Build STEP 9 ONLY: deploy to an India-region environment. No new features.

- Containerize backend + frontend. Managed MySQL 8 in an India region (document which host/region).
- HTTPS/TLS everywhere. Secrets from the host's secret manager, never committed.
- Alembic migrations run on deploy. Automated daily DB backups + a tested restore.
- Health checks + basic uptime monitoring. A staging environment kept separate from any real data.
- Document the full deploy + rollback steps in the README.

Stop after the app is reachable over HTTPS on the host with migrations applied and a backup
taken. Wait for STEP 10.
```
**Done when:** reachable over HTTPS, MySQL in-region, backups run + restore tested, no secrets in the repo.

---

## STEP 10 — Hardening (safe failure)

```
Build STEP 10 ONLY: robustness and safe failure. No new features.

- Handle every external failure gracefully:
  * STT error/timeout -> clear message, fall back to manual entry.
  * LLM invalid/empty output -> validate against the schema; on failure show
    "Couldn't read that — please enter manually", NEVER a wrong guess.
  * Network drop mid-recording (Mode 3) -> auto-save partial transcript + consent, allow resume.
- Input validation at every trust boundary. Provider calls get timeouts + limited retries.
- Structured logging that NEVER logs patient PII or full transcripts. Rate limiting on APIs.
- Graceful empty/error states using the design.md §8 copy voice.

Stop after a fault-injection test shows each failure degrades safely: no crash, no wrong
prescription, no PII in logs. Show the results. Wait for STEP 11.
```
**Done when:** injected faults degrade safely and logs contain zero PII.

---

## STEP 11 — Accuracy-validation harness (the trust gate)

```
Build STEP 11 ONLY: an accuracy-measurement harness. This decides whether the voice modes
can be trusted on real patients — it is the gate before real-patient use.

- A script that runs a LABELED test set through the REAL pipeline and scores it:
  * Mode 2: dictation clips/text with ground-truth Rx fields -> field-level accuracy
    (drug, strength, dose, frequency, duration) + drug-name correction hit rate.
  * Mode 3: consented recordings with ground-truth diarization + Rx -> diarization error
    (who-spoke), extraction accuracy, and evidence-link correctness.
- Print a per-field + overall report so a human can compare against the PRD §10 targets.
- Include a small starter sample set; make adding real consented clinic samples trivial.

Stop after the harness runs and prints a scored report. Wait for review — do not declare the
modes "good enough"; that's a human call against the numbers.
```
**Done when:** harness prints a scored report and real clinic samples can be dropped in. The numbers, not Codex, decide readiness.

---

## How to run it

1. Paste a step's fenced prompt into Codex.
2. Let it finish; check the "Done when" line yourself.
3. For UI steps (5, 7) also hand Codex the reference screenshot.
4. If it drifts, point it back at the doc: "re-read design.md §7 and fix the Safety Rail."
5. Then paste the next step.

Keep each step small. If Codex tries to jump ahead, tell it to stop and finish the current step only.
