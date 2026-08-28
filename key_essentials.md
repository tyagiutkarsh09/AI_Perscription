# key_essentials.md — keys, accounts & setup for the POC

Everything you need to sign up for or provision to run the POC. Nothing here is committed to the repo — use a `.env` file (git-ignored) and load via the backend config.

## Required for a working POC

| # | Key / account | For | Where | Cost | Status |
|---|---|---|---|---|---|
| 1 | **OpenAI API key** | LLM extraction (Structured Outputs) | platform.openai.com | Pay per token | Needed |
| 2 | **Deepgram API key** | STT — streaming, diarization, medical model | deepgram.com | Pay per minute; free credits to start | Needed |
| 3 | **MySQL 8** | All app data | India-region managed MySQL (or local for dev) | Free (local) / hosting | Needed |
| 4 | **Indian brand catalog** | brand→generic resolution (`brand_catalog`) | e.g. DataRequisite, or CDSCO/NFI ingestion | TBD — verify | **To source** |

## Needed only when we upgrade the safety engine (licensed-later)

| Key / account | For | Notes |
|---|---|---|
| **DrugBank API** | Interactions/dose/allergy | Paid; free checker retires 25 Mar 2026. Get a quote. |
| **First Databank (FDB)** | Same | Enterprise; request pricing |
| **Medi-Span (Wolters Kluwer)** | Same | Enterprise; request pricing |
| **Micromedex (Merative)** | Same | Enterprise; request pricing |

Until one is chosen, the safety engine runs on the **curated formulary** (no key needed) plus free sources below.

## Free sources (no key or free key)

| Source | For | Access |
|---|---|---|
| **RxNorm / RxNav** | Generic normalization (RxCUI), drug classes (RxClass/ATC) | Free REST API, no key |
| **openFDA** | US drug labels (interactions as prose), reference | Free; optional key raises rate limit |
| **DDInter** | Seed interactions table (academic, CC-BY) | Free download |
| **WHO ATC** | Allergy cross-sensitivity classes | Free reference |

## Env var names (suggested)

```
OPENAI_API_KEY=
DEEPGRAM_API_KEY=
DATABASE_URL=mysql+pymysql://user:pass@host:3306/rxtool
BRAND_CATALOG_SOURCE=            # provider name or file path
DRUGKNOWLEDGE_BACKEND=curated    # curated | drugbank | fdb | medispan
OPENFDA_API_KEY=                 # optional, rate-limit bump
```

## Compliance to arrange (not a key, but blocks a real pilot)
- **Data Processing Agreement (DPA)** with OpenAI and Deepgram.
- Request **Zero Data Retention (ZDR)** on the OpenAI API for the pilot.
- Patient **consent** flow (recording + data processing) — built into the app, per encounter.
- India-region hosting confirmed for MySQL (DPDP residency).

## To verify before relying on any of this
- **Vendor pricing/coverage** for #4 and the licensed-later table — all currently **unconfirmed candidates**, not picks.
- Deepgram **self-hosted** option availability/cost if full in-country processing is required at scale.
- Indian-brand coverage of whichever brand catalog you trial (does it contain the pilot formulary's brands?).
