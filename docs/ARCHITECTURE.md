# DataBridge — Architecture

This document is the Phase 1 plan, kept up to date as the system was built. It explains
what each part does and why it was designed that way.

## 1. System overview

```
                 ┌──────────────────────────── Browser ────────────────────────────┐
                 │ React + TypeScript SPA (Vite build, code-split per page)        │
                 │ TanStack Query cache · typed API client · Recharts              │
                 └───────────────────────────────┬─────────────────────────────────┘
                                                 │  HTTPS, same origin  /api/*
                 ┌───────────────────────────────▼─────────────────────────────────┐
                 │ nginx (production) — serves static assets, proxies /api         │
                 └───────────────────────────────┬─────────────────────────────────┘
                 ┌───────────────────────────────▼─────────────────────────────────┐
                 │ FastAPI (uvicorn)                                                │
                 │  routes ─► services ─► SQLAlchemy ─► PostgreSQL / SQLite         │
                 │                                                                  │
                 │  ingestion   quality engine   cleaning   ETL runner   explorer   │
                 │  analytics   AI analyst (provider adapters + statistical fallback)│
                 │  reports (PDF via ReportLab, CSV streaming)                      │
                 └──────────────┬───────────────────────────────────┬───────────────┘
                                │                                   │
                     ┌──────────▼──────────┐             ┌──────────▼──────────┐
                     │ File storage        │             │ Relational database │
                     │ uploads/ (originals)│             │ metadata tables     │
                     │ reports/ (PDF/CSV)  │             │ stg_* raw tables    │
                     └─────────────────────┘             │ prc_* processed     │
                                                         └─────────────────────┘
```

**Request flow.** Routes are thin: they validate input with Pydantic, call a service, and
map the result to a response schema. Services hold all business logic and are plain
Python functions that take a SQLAlchemy `Session`, which makes them easy to unit test
without HTTP.

## 2. Data lifecycle

```
Upload ─► Validate file ─► Parse (pandas) ─► Profile columns ─► Stage raw rows (stg_<id>)
                                                   │
                                                   ▼
                                         Raw quality assessment
                                                   │
                              Pipeline run (background task, status polled)
   Extract ─► Validate ─► Transform (selected rules) ─► Load (prc_<run>) ─► Re-assess quality
                                                   │
                                                   ▼
                          Explorer · Analytics · AI analyst · Reports
```

* **Originals are never modified.** The uploaded file is stored once, under a generated
  name, with its SHA-256 recorded.
* **Raw staging table (`stg_<dataset_id>`).** All columns are stored as text, exactly as
  parsed. This is what "raw" means in the Explorer's raw-vs-processed comparison, and it
  lets the Explorer paginate raw data with SQL instead of re-reading the file.
* **Processed table (`prc_<run_id>`).** Typed columns (numeric, datetime, text, boolean),
  created by the load stage inside a transaction. Each successful run produces a new
  table, so earlier outputs remain available and comparable.

## 3. Backend modules

| Module | Responsibility |
|---|---|
| `core/config.py` | Typed settings from environment variables (pydantic-settings) |
| `core/logging.py` | Structured JSON logging with request IDs |
| `core/storage.py` | Safe file storage: generated names, size limits, path containment |
| `core/identifiers.py` | Column-name sanitising and SQL identifier validation |
| `services/ingestion.py` | File validation (extension + content sniffing), parsing, staging |
| `services/profiling.py` | Column type inference and per-column statistics |
| `services/quality/engine.py` | Rule-based quality checks and the documented score |
| `services/cleaning.py` | Transformation rules used by pipelines |
| `services/etl.py` | Pipeline runner: stages, logs, transactions, failure handling |
| `services/explorer.py` | Paginated, filtered, sorted SQL queries over stg/prc tables |
| `services/analytics.py` | Chart data built from real columns, with suitability checks |
| `services/ai/` | Provider interface, Anthropic/OpenAI adapters, statistical fallback |
| `services/reports/` | PDF and CSV report generation |

## 4. Frontend structure

```
frontend/src
├── api/            typed client + endpoint functions + shared types
├── components/
│   ├── ui/         Button, Badge, Card, Table, Dialog, EmptyState, Skeleton, Tabs…
│   ├── layout/     AppShell, Sidebar, PageHeader
│   └── charts/     chart wrappers bound to the design tokens
├── features/       one folder per module (overview, datasets, quality, pipelines,
│                   explorer, analytics, analyst, reports) — pages + local components
├── lib/            formatting, hooks, validation helpers
└── styles/         Tailwind entry + design tokens
```

Pages are lazy-loaded with `React.lazy`, so the first visit only downloads the shell and
the Overview page. Charts (the largest dependency) load only on pages that use them.

## 5. Key engineering decisions

| Decision | Alternatives considered | Reason |
|---|---|---|
| Dynamic per-dataset tables for staged/processed rows | One generic JSON rows table | Real typed columns allow SQL filtering, sorting and aggregation with indexes; demonstrates relational loading. Table names are generated by the app, never by users. |
| Raw staging as text | Store parsed types | "Raw" must show what was actually in the file, including invalid values the quality engine flags. |
| ETL via FastAPI `BackgroundTasks` + status polling | Celery/Redis queue | No extra infrastructure for a single-node app; the runner is a plain function, so moving to a queue later is a small change. Documented as a known limit. |
| PostgreSQL primary, SQLite fallback | Postgres only | Zero-setup local runs on Windows; Docker Compose and production use Postgres. All SQL goes through SQLAlchemy so both work, and the test suite runs against both. |
| Quality score from four weighted dimensions | Single heuristic number | Transparent, explainable in an interview, and reproducible (see `DATA_QUALITY.md`). |
| AI calls via `httpx` adapters, not vendor SDKs | Official SDKs | Smaller dependency footprint, one interface for several providers, easy to mock in tests. |
| Only a dataset *profile* is sent to the AI provider | Sending raw rows | Limits data exposure and token cost; the profile is shown to the user so they see exactly what was shared. |
| Same-origin `/api` behind nginx in production | Separate API domain | No CORS in production, one deployable unit, simpler always-on hosting. |

## 6. Error handling

* Domain errors (`NotFound`, `ValidationFailed`, `Conflict`, `UnsupportedFile`) are raised
  by services and converted to a consistent JSON body by one exception handler:
  `{"error": {"code": "...", "message": "...", "details": {...}}, "request_id": "..."}`.
* Unexpected exceptions return a generic 500 with the request ID; the stack trace goes to
  the log only.
* A failed pipeline stage marks the run `failed`, records the stage and message in the
  run logs, and rolls back the load transaction so no half-written table remains.
* The frontend shows the server's message and the request ID, so a user can quote it.

## 7. AI integration

```
POST /api/analyst/ask ─► build dataset profile (stats, quality issues, 10 sample rows)
                       ├─► statistical answer (always computed, labelled "Statistical")
                       └─► if provider configured: provider.complete(prompt) ─► "AI" answer
```

`GET /api/analyst/status` reports whether a provider is configured. The key is read from
`AI_API_KEY` on the server and never returned. If the provider call fails, the user sees
the error and still gets the statistical answer.

## 8. Security measures (implemented)

* Extension allow-list plus content checks (Excel files must be valid ZIP/OLE containers;
  CSV must decode as text and parse).
* Configurable size limit (`MAX_UPLOAD_MB`), enforced while streaming the upload to disk.
* Stored files use generated names inside a fixed directory; paths are resolved and
  checked for containment.
* All database access goes through SQLAlchemy with bound parameters. Dynamic table and
  column identifiers are generated by the app and validated against a strict pattern and
  the dataset's own metadata before use.
* CSV exports neutralise spreadsheet formula injection (`=`, `+`, `-`, `@` prefixes).
* Secrets only from environment variables; `.env` is git-ignored; no defaults for keys.
* Security headers in nginx; CORS restricted to configured origins.

Not implemented (and not claimed): authentication, multi-tenancy, rate limiting,
encryption at rest. These are listed in the roadmap.

## 9. Performance work (measured)

Both changes were driven by profiling a 200,000-row (17 MB) file on PostgreSQL 16 on a 2-vCPU sandbox.
The figures are from `scripts/benchmark.py`; full tables are in `TESTING.md`.

| Change | Problem found | Effect |
|---|---|---|
| Per-unique-value evaluation (`typing.per_unique`) | cProfile showed nearly all quality-engine time in row-by-row string operations (`str.strip`, regex replace, number and date parsing) over values that repeat heavily | Each column is factorised, the work runs once per distinct value and is mapped back. Results are identical (same counts and score) and the engine is about 3× faster. |
| `COPY … FROM STDIN` for PostgreSQL loads | Batched `INSERT`s took 9.8 s to load 198k rows | The load stage dropped to about 4.2 s, inside the same transaction. SQLite keeps batched inserts. |

Overall on that file: ingestion went from 15.8 s to 6.3 s, and a full pipeline run from 32.6 s to 17.4 s.

## 10. Known limitations

* **Single-node background jobs.** Runs execute in FastAPI background tasks in the worker that accepted the
  request. At startup each worker marks runs left `pending`/`running` as failed. With several workers, a worker
  restarting mid-run could mark another worker's live run as failed. A job queue (e.g. Redis + RQ/Celery) with
  heartbeats is the fix and is on the roadmap.
* **Synchronous ingestion.** Parsing happens during the upload request (about 6 s for 200k rows). Moving it to
  the job queue would allow larger files.
* **Whole-column processing in memory.** pandas processes a dataset in memory. Peak RSS was 261 MB for 50k rows
  and 556 MB for 200k rows (one worker), which sets the instance size (see `DEPLOYMENT.md`).
* **No authentication.** DataBridge is a single-workspace application. Users, roles and per-workspace
  isolation are on the roadmap. Do not expose a deployment with confidential data before that exists.
* **Column statistics cache** is per process (an LRU of 64 tables). It is safe because row tables never change
  after creation.
