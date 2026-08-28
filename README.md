# AI Prescription Tool POC

Steps 1–5 POC: FastAPI + React, MySQL schema and curated reference data, swappable STT/LLM/drug-knowledge providers, deterministic safety checks, and the Mode 2 dictation-to-signed-PDF flow.

## Setup (Windows PowerShell)

```powershell
Copy-Item .env.example .env
# Edit .env: set MYSQL_ROOT_PASSWORD, MYSQL_PASSWORD, and make DATABASE_URL use the same password.
.\.python\python.exe -m pip install -r backend\requirements.txt
Set-Location frontend
npm install
Set-Location ..
```

Use Python 3.12+ instead of `.python\python.exe` if the portable interpreter is absent.

## Database

```powershell
docker compose up -d db
Set-Location backend
..\.python\python.exe -m alembic upgrade head
..\.python\python.exe -m app.seed
Set-Location ..
```

The seed command is idempotent and prints counts for `formulary`, `brand_catalog`, `interactions`, and `allergy_classes`. Numeric limits are intentionally sparse; rows marked “Clinician verification required” are not pilot-ready safety data.

Generate MySQL SQL without a running database:

```powershell
Set-Location backend
..\.python\python.exe -m alembic upgrade head --sql
Set-Location ..
```

## Run

API terminal:

```powershell
Set-Location backend
..\.python\python.exe -m uvicorn app.main:app --reload
```

UI terminal:

```powershell
Set-Location frontend
npm run dev
```

Open `http://localhost:5173`; Vite proxies `/health` and `/api` to `http://localhost:8000`.

For offline use, keep `STT_BACKEND=fake`, `LLM_BACKEND=fake`, and `DRUGKNOWLEDGE_BACKEND=curated`. Paste the Step 5 acceptance dictation, review the resolved generic and Safety Rail, then use `Approve & Sign`. Signed PDFs are written under `backend/generated` unless `PDF_DIR` is set.

For vendor adapters, select `STT_BACKEND=deepgram` and/or `LLM_BACKEND=openai` and provide the matching API key. Business logic still calls only the provider protocols.

## Verify

```powershell
Set-Location backend
..\.python\python.exe -m pytest tests -q
Set-Location ..
Set-Location frontend
npm run build
```
