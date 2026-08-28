# PILOT_READINESS.md — go-live gate for the clinical pilot

The code (CODEX_PROMPTS.md STEP 1–11) makes the app **work and pilot-grade**. This checklist covers what code can't: the human, legal, and clinical sign-offs that gate putting real doctors and real patients on it.

**Rule: no real patient touches the system until every 🔴 BLOCKER below is checked and signed.** 🟡 items should be done but can run in parallel with a tightly-scoped early pilot if a named owner accepts the risk in writing.

Legend: 🔴 blocker · 🟡 required soon · Owner = who signs it off.

---

## 1. Clinical safety

- [ ] 🔴 **Every seeded formulary dose limit reviewed and signed by a clinician** (doctor/pharmacist). No prescription is signed on unverified dose data. — *Owner: clinical lead*
  - Verify: each `formulary` row has a real source (BNF / label / National Formulary of India) and a reviewer initial + date; zero TODO/null limits remain for in-scope drugs.
- [ ] 🔴 **Danger cases validated on the running system** (not just unit tests): 1300 mg paracetamol single dose fires; penicillin-allergy + amoxicillin fires; a known severe interaction fires; an out-of-formulary drug shows "verify manually". — *Owner: clinical lead + eng*
- [ ] 🔴 **"Warn, never block" behavior confirmed by a real doctor** in a walkthrough — acknowledgment gate works, override reason is captured. — *Owner: clinical lead*
- [ ] 🟡 Interaction + allergy-class coverage judged adequate for the pilot's drug set, or gaps documented and accepted. — *Owner: clinical lead*

## 2. Drug-data sourcing (the top project risk)

- [ ] 🔴 **Indian brand catalog chosen and it covers the pilot formulary's brands.** — *Owner: eng + product*
  - Verify: trial catalog resolves every in-scope brand to the correct generic.
- [ ] 🟡 **Safety-data path decided:** either a licensed vendor (DrugBank/FDB/Medi-Span) is contracted, OR the pilot runs on the curated formulary with the coverage limit written down and accepted. — *Owner: product*
- [ ] 🟡 No unverified vendor pricing/coverage claim is treated as fact anywhere. — *Owner: product*

## 3. Legal & compliance (DPDP Act 2023, Telemedicine Guidelines 2020)

- [ ] 🔴 **Data Processing Agreement signed with OpenAI and with Deepgram.** — *Owner: legal*
- [ ] 🔴 **Zero Data Retention requested/confirmed on the OpenAI API** for the pilot. — *Owner: eng + legal*
- [ ] 🔴 **Recording-consent wording (Mode 3) legally reviewed** and shown to the patient before recording, per encounter, timestamped. — *Owner: legal + clinical*
- [ ] 🔴 **PII minimization verified in the running system:** patient name/ID/contact are stripped before any external AI call (inspect real outbound payloads). — *Owner: eng*
- [ ] 🔴 **Data residency confirmed:** patient data (MySQL) hosted in an India region; cross-border AI calls covered by consent + DPA. — *Owner: eng + legal*
- [ ] 🟡 Data-retention + deletion policy written (how long transcripts/audio are kept, how a patient's data is deleted on request). — *Owner: legal*
- [ ] 🟡 Signed-prescription format meets Telemedicine Guidelines (doctor name + registration no. + timestamp, immutable, patient-identifiable). — *Owner: clinical + legal*

## 4. Security

- [ ] 🔴 **Security review passed** on the clinical/PII surface (authn/authz, injection, access control, secret handling). — *Owner: security*
- [ ] 🔴 **Auth verified:** no clinical endpoint reachable unauthenticated; a doctor cannot see another doctor's patients. — *Owner: eng + security*
- [ ] 🔴 **Secrets not in the repo** (`.env` git-ignored; production secrets in a secret manager). — *Owner: eng*
- [ ] 🟡 Backups run and a restore has actually been tested. — *Owner: eng*
- [ ] 🟡 Audit log confirmed append-only and complete (suggestion, edit, warning, acknowledgment, signature). — *Owner: eng*

## 5. Accuracy (the trust gate — PRD §10)

- [ ] 🔴 **Accuracy harness (STEP 11) run on REAL consented clinic audio**, not just synthetic. — *Owner: eng + clinical*
- [ ] 🔴 **Numbers clear the PRD §10 targets**, or a named owner accepts the measured level in writing. — *Owner: product + clinical*
  - Mode 2 field extraction, drug-name correction hit rate, Mode 3 diarization error, evidence-link correctness.
- [ ] 🟡 Failure modes rehearsed with a doctor: STT mishears a drug, LLM returns junk, network drops mid-recording — the app degrades safely and the doctor knows what to do. — *Owner: clinical + eng*

## 6. Operations

- [ ] 🔴 **Deployed to the India-region host over HTTPS**, staging separate from real data. — *Owner: eng*
- [ ] 🟡 Monitoring + uptime alerts live. — *Owner: eng*
- [ ] 🟡 Incident + rollback plan written; who to call when something breaks mid-clinic. — *Owner: eng + product*
- [ ] 🟡 A named support contact for the pilot doctors. — *Owner: product*

## 7. Pilot design

- [ ] 🟡 Scope agreed: how many doctors, which clinic, how many patients, how long. — *Owner: product*
- [ ] 🟡 Doctors briefed: the tool drafts and warns; they review, edit, and sign; they are in control. — *Owner: clinical*
- [ ] 🟡 A way for doctors to report problems and for you to act on them fast. — *Owner: product*

---

## Go / No-Go sign-off

Pilot may start only when **all 🔴 are checked** and each owner has signed.

```
Clinical lead   ____________________  date ________   (Sections 1, 5)
Engineering     ____________________  date ________   (Sections 3, 4, 6)
Legal           ____________________  date ________   (Section 3)
Security        ____________________  date ________   (Section 4)
Product         ____________________  date ________   (Sections 2, 5, 7)

Decision:  ☐ GO    ☐ NO-GO        Signed off by ____________________  date ________
```

---

*Companion docs: `PRD.md` (targets + risks), `architecture.md` (how it's built), `CODEX_PROMPTS.md` (build steps), `key_essentials.md` (keys + DPA/ZDR notes).*
