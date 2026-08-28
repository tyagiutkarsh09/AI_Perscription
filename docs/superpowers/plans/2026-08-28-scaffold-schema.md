# Scaffold and Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver STEP 1 and STEP 2 only: a runnable FastAPI/Vite/MySQL scaffold, the exact architecture §6 schema, and sourced seed data.

**Architecture:** A small FastAPI app owns settings, the SQLAlchemy engine, models, and `/health`. Vite proxies `/health` to FastAPI. Alembic creates the MySQL 8 schema and database triggers enforce append-only safety/audit tables; one idempotent script loads reference data.

**Tech Stack:** Python, FastAPI, pydantic-settings, SQLAlchemy 2, Alembic, PyMySQL, React, Vite, MySQL 8, Docker Compose.

**Spec:** `AGENTS.md`, `architecture-essentials.md`, `PRD.md`, and `architecture.md` §6.

## Global Constraints

- Build STEP 1 and STEP 2 only; no prescription or safety-engine business logic.
- Use `mysql+pymysql`; MySQL JSON, `CHAR(36)` UUIDs, and UTC `DATETIME` columns.
- Load application configuration from `.env`; commit only `.env.example` placeholders.
- Brand rows exist only in `brand_catalog`; seeded dose values need an authoritative source or a clinician-verification note.
- `safety_events` and `audit_log` are append-only at the database layer.

---

### Task 1: Health scaffold

**Files:**
- Create: `backend/requirements.txt`, `backend/app/__init__.py`, `backend/app/config.py`, `backend/app/database.py`, `backend/app/main.py`, `backend/tests/test_health.py`
- Create: `frontend/package.json`, `frontend/index.html`, `frontend/vite.config.js`, `frontend/src/main.jsx`, `frontend/src/App.jsx`, `frontend/src/index.css`
- Modify: `.env.example`, `.gitignore`

**Interfaces:**
- Produces: `GET /health -> {"status": "ok"}` and a React page rendering the returned status.

- [ ] Write `backend/tests/test_health.py` using FastAPI `TestClient`; assert status 200 and the literal JSON payload.
- [ ] Run `pytest backend/tests/test_health.py -q`; verify failure because `app.main` does not exist.
- [ ] Add the minimum settings, engine, FastAPI route, Vite proxy, React fetch/render page, and dependency manifests.
- [ ] Run the health test and `npm run build`; verify both pass.

### Task 2: Schema and seeds

**Files:**
- Create: `backend/app/models.py`, `backend/alembic.ini`, `backend/migrations/env.py`, `backend/migrations/script.py.mako`, `backend/migrations/versions/0001_initial_schema.py`, `backend/app/seed.py`, `backend/tests/test_seed_data.py`

**Interfaces:**
- Produces: SQLAlchemy metadata for all 13 §6 tables; `python -m app.seed` idempotently loads 20 formulary rows plus brands, interactions, and allergy classes and prints counts.

- [ ] Write a seed-data invariant test asserting 20 unique ingredients, a source or verification note per drug, catalog brands resolving only to seeded generics, valid interaction pairs, and penicillin membership.
- [ ] Run the seed test; verify failure because `app.seed` does not exist.
- [ ] Add the exact §6 SQLAlchemy models, seed constants, and idempotent loader.
- [ ] Add one Alembic migration matching model metadata and MySQL append-only triggers for `safety_events` and `audit_log`.
- [ ] Run all backend tests; verify they pass.

### Task 3: Local runtime and proof

**Files:**
- Create: `docker-compose.yml`, `README.md`

**Interfaces:**
- Produces: MySQL 8 on port 3306 and documented commands for DB, migrations, seeds, API, and UI.

- [ ] Add Docker Compose using only `.env` variables and a MySQL healthcheck.
- [ ] Add concise Windows PowerShell and portable run instructions to README.
- [ ] Run Docker Compose, `alembic upgrade head`, and `python -m app.seed`; capture successful migration and printed row counts.
- [ ] Start FastAPI and Vite, request both `/health` and the page, and verify the page bundle contains the status UI.
- [ ] Re-run tests and frontend build, inspect the final diff/file list, and stop before STEP 3.
