# claude.md — build guidance for AI Prescription Tool (POC)

Instructions for any AI/agent working in this repo. Read `architecture-essentials.md` for context; `PRD.md` for the what/why; `architecture.md` for schema + API detail.

## What we're building
Clinical prescription assistant for Indian outpatient doctors. Doctor-in-control **decision support**. Three input modes: manual, voice dictation (default), ambient conversation (selling point). Pilot with real doctors — treat it as safety-critical, not a toy demo.

## Stack
- Frontend: **React** (SPA).
- Backend: **Python + FastAPI**.
- DB: **MySQL 8** (driver `mysql+pymysql`; JSON columns for `segments`/`preferences`/`evidence_segment_ids`/audit; arrays as JSON).
- Hosting: **India region**.
- External (all behind interfaces): Deepgram (STT), OpenAI (LLM extraction), a drug-knowledge provider (TBD).

## Non-negotiable rules (violating these breaks the product)
1. **Never hardcode brand names.** Brands come from `brand_catalog`. Always.
2. **Run safety checks on the generic ingredient, never the brand.** Resolve brand→generic first.
3. **Never hard-block a prescription.** Warn + require acknowledgment. Log every warning and acknowledgment to `safety_events`.
4. **Never show a false safety pass.** Drug outside the curated formulary → "not in safety DB, verify manually", not a green tick.
5. **Minimize PII before external AI calls.** Strip patient name/ID/contact; send clinical text only; re-attach identifiers locally.
6. **Mode 3 recording requires per-encounter consent first.** No consent → no recording.
7. **Signed prescriptions are immutable.** Once signed (name + registration no. + timestamp), locked. Generate PDF.
8. **Everything is auditable.** `audit_log` is append-only.

## Architecture conventions
- Three provider interfaces — `STTProvider`, `LLMProvider`, `DrugKnowledgeProvider` — keep external services swappable. Don't call vendors directly from business logic; go through the interface.
- The **safety engine is deterministic** (pure function, no LLM in the safety path). LLM is only for extraction.
- LLM extraction uses **OpenAI Structured Outputs** (JSON schema) so fields are guaranteed-valid.
- STT output always passes a **drug-name post-correction** step (fuzzy match vs `brand_catalog`, e.g. RapidFuzz).
- Live transcript over WebSocket; extraction is a **single batch call at "End encounter"**, not per-token.

## Data model quick map
`doctors → encounters ← patients`, `encounters → transcripts / prescriptions`, `prescriptions → prescription_items`, each item → `formulary` (ingredient) + `brand_catalog` (brand) + `evidence_segment_ids`. Immutable: `safety_events`, `audit_log`. See `architecture.md` §6 for columns.

## When you write code
- Match existing patterns; keep it minimal (this is a POC — don't over-engineer).
- Non-trivial logic (dose math, interaction check, brand resolution, evidence linking) needs a runnable check/test.
- Seed a small **danger-case test set**: 1300 mg paracetamol (dose), penicillin allergy → amoxicillin (allergy class), a known severe interaction. The safety engine must flag all three.
- Don't add a dependency for what a few lines do; don't add an abstraction with one implementation (the three provider interfaces are the intended ones — no more).

## Verify before claiming done
- Run the danger-case tests; show output.
- Any pricing/coverage claim about a drug-data vendor is **unverified** until checked — see `key_essentials.md`. Don't assert it as fact.

## Current status
Planning docs written (this session). No code yet. Design tree fully resolved — see `GRILL_NOTES.md`.
