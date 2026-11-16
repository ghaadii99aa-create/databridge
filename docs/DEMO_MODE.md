# Public demo mode

DataBridge has no user accounts. To publish it as a portfolio demo that anyone can open, it has a demo mode,
switched on with one environment variable: `DEMO_MODE=true`. Without it, DataBridge behaves exactly as the
single-user local application described in the README.

## What a visitor gets

* **A populated dashboard on the first visit.** On start-up the server prepares shared demonstration data:
  the synthetic retail sample (2,448 rows), a cleaning pipeline, one successful run of it and a PDF run report.
  Overview, Data quality, Pipelines, Explorer, Analytics, AI analyst and Reports all have content immediately.
* **Clearly labelled demonstration data.** A notice at the top of every page states that the retail dataset is
  synthetic, shared and read-only, that uploads are private to the browser and deleted after 24 hours, and the
  upload limits. The sample keeps its *Sample data* tag and description.
* **Their own workspace.** Visitors can upload their own CSV or XLSX files, build and run pipelines (including
  on the shared sample), and generate reports. Shared items show *Make a copy* or *Create pipeline* instead of
  edit and delete controls.

## How shared data is protected

| Rule | Where it is enforced |
|---|---|
| Shared data (sample dataset, its pipeline, run and report) cannot be deleted, renamed, edited, re-run or re-assessed | Server: every write route checks ownership and returns `403 read_only`; the UI hides those controls |
| The sample is always available | Seeding is idempotent and runs on start-up and before every cleanup pass, so a missing sample is restored |
| Cleanup never removes shared data | Cleanup only selects rows with a visitor owner; shared rows have no owner |
| Accidental deletion of a visitor's own data | Deleting a dataset or pipeline still asks for confirmation; deletion of shared data is impossible |

## Visitor isolation

Each browser gets a random 128-bit visitor ID in a cookie (`databridge_visitor`: `HttpOnly`, `SameSite=Lax`,
`Secure` in production, 30 days). Everything a visitor creates is tagged with that ID. Every lookup by ID —
datasets, previews, downloads, quality assessments, pipelines, runs, processed outputs, explorer and analytics
queries, AI analyst questions and reports — checks it. Another visitor's items are reported as **not found**
(`404`), so IDs cannot be used to discover them. Lists and Overview figures include only shared data and the
visitor's own data. A forged or malformed cookie is replaced with a new ID.

**This is isolation by an anonymous cookie, not authentication.** It stops visitors from seeing each other's
data in the application. It does not identify people, and a visitor who clears cookies or switches browsers
loses access to their own uploads (they are then removed by the next cleanup after 24 hours). Uploaded
files should not contain personal or confidential data; the notice and this page say the demo is for sample
data.

## Limits (enforced on the server)

| Limit | Value | Error |
|---|---|---|
| File size | 10 MB (`DEMO_MAX_UPLOAD_MB`) — checked from `Content-Length` and while the body streams in, so an oversized file is rejected before it is stored | `413 file_too_large` |
| Rows per file | 50,000 (`DEMO_MAX_ROWS`) — nothing is kept for a rejected file | `413 limit_exceeded` |
| Columns per file | `MAX_COLUMNS` (default 200) | `413 limit_exceeded` |
| Other request bodies | 1 MB | `413 request_too_large` |
| Datasets kept per visitor | 5 | `413 limit_exceeded` |
| Pipelines kept per visitor | 10 | `413 limit_exceeded` |

In demo mode the configured `MAX_UPLOAD_MB` and `MAX_ROWS` are capped at these values even if set higher.
The upload panel shows the limits, and every error message states the limit and the actual value.

## Rate limits (per client IP)

| Action | Limit |
|---|---|
| Uploads | 10 per hour |
| Pipeline runs | 30 per hour |
| AI analyst questions | 30 per 10 minutes |
| Reports generated | 30 per hour |
| Downloads and exports | 60 per hour |
| Any change (POST, PUT, PATCH, DELETE) | 120 per 10 minutes |
| All API requests | 600 per minute |

Health checks are never limited. Over the limit, the API returns `429 rate_limited` with a `Retry-After`
header and a message saying when to try again. Counters are kept in memory in each server process (see
limitations).

## Daily cleanup

A background thread starts with the server in demo mode. About a minute after start-up and then every
`DEMO_CLEANUP_INTERVAL_MINUTES` (60), it:

1. deletes visitor datasets, pipelines and reports older than `DEMO_RETENTION_HOURS` (24), together with their
   runs, quality assessments, generated row tables and stored files;
2. deletes files in the upload and report folders that no database row refers to, if they are older than one
   hour (in-progress uploads are never touched);
3. drops generated row tables named exactly `stg_<number>` or `prc_<number>` that no dataset or output refers
   to and that do not belong to a running pipeline.

It never touches shared data (no owner), the `app_settings` and `alembic_version` tables, the metadata tables
themselves, migrations, configuration, or any file outside the upload and report folders. The time and
counts of the last pass are stored in `app_settings` and shown by `GET /api/datasets/limits`.

Run it by hand with:

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.cli cleanup   # remove expired visitor data now
.\.venv\Scripts\python.exe -m app.cli seed      # create the shared demo data if missing
```

## Running the demo locally

```powershell
powershell -ExecutionPolicy Bypass -File scripts\demo.ps1
```

This uses a separate database and folder (`backend/data/demo`), so your normal local data is not affected.
Open two different browsers (or a normal and a private window) to see that uploads are private.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `DEMO_MODE` | `false` | Turns demo mode on |
| `DEMO_MAX_UPLOAD_MB` | `10` | File size cap in demo mode |
| `DEMO_MAX_ROWS` | `50000` | Row cap in demo mode |
| `DEMO_RETENTION_HOURS` | `24` | Age at which visitor data is deleted |
| `DEMO_CLEANUP_INTERVAL_MINUTES` | `60` | Time between cleanup passes |
| `DEMO_MAX_DATASETS_PER_VISITOR` | `5` | Uploaded datasets kept per visitor |
| `DEMO_MAX_PIPELINES_PER_VISITOR` | `10` | Pipelines kept per visitor |
| `RATE_LIMIT_ENABLED` | same as `DEMO_MODE` | Rate limiting on or off |
| `COOKIE_SECURE` | `true` when `ENVIRONMENT=production` | Send the visitor cookie over HTTPS only |

## Known limitations

* Isolation is per browser cookie, not per person; there is no login.
* Rate-limit counters live in each server process. With `WEB_CONCURRENCY=2` each worker counts separately, so
  the effective limit can be up to twice the table above. Exact global limits would need a shared store such as
  Redis.
* Rate limits use the client IP. Behind a proxy the server must be started with `--proxy-headers` (the
  Dockerfiles do this) so the real visitor IP is used; visitors sharing one IP (an office, a mobile carrier)
  share limits.
* Cleanup runs inside the web server process. If the host stops the server when idle (as free hosting tiers
  do), cleanup runs on the next start-up instead of on the hour.
* A visitor's pipeline on the shared sample adds its run to the sample's quality history only for that visitor;
  other visitors do not see it.
