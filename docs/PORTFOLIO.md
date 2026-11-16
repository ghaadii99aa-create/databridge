# DataBridge: project presentation

A summary for recruiters and interviewers, and a script for talking about the project. Every number here comes
from `TESTING.md` and was measured on this build.

## Purpose

Operations and finance teams often work from exported spreadsheets that arrive with missing values, duplicate
rows, the same category spelled several ways, and dates in mixed formats. Reports built on them are quietly
wrong. DataBridge turns such a file into a clean, typed database table. It shows exactly what was wrong, what
was changed, and how much the data improved, and then makes the result explorable and reportable.

## Architecture in one paragraph

A React + TypeScript single-page app talks to a FastAPI backend over a same-origin REST API. Services hold the
logic: ingestion, a pandas quality engine, cleaning rules, an ETL runner, an SQL-backed explorer, analytics,
an AI analyst with a statistical fallback, and PDF/CSV reports. They write to PostgreSQL through SQLAlchemy;
Alembic owns the schema. Raw rows are staged as text in `stg_<dataset>`; each pipeline run loads typed rows
into its own `prc_<run>` table. The app is deployable as one container (FastAPI serves the built UI) or as a
compose stack with nginx. See `ARCHITECTURE.md`.

## Main features

* CSV/XLSX upload with content checks, size limits, encoding and delimiter detection, and a column profile
* Ten documented quality checks; a weighted, reproducible score with the cell counts behind it
* Pipelines with ordered cleaning rules, a five-stage runner, per-stage timings, logs, and before/after quality
* Explorer with server-side pagination, filters, sorting, search, column statistics and CSV export
* Charts that refuse to draw when the data can't support them, with a table view for every chart
* AI analyst that always computes a statistical answer and adds a clearly labelled AI answer only when a key is
  configured
* PDF and CSV reports built only from stored results

## Key technical challenges and how they were solved

| Challenge | Solution |
|---|---|
| A quality score that can be defended in a meeting | Four dimensions with documented formulas and weights. The counts behind each dimension are stored, and a unit test asserts a hand-calculated example. Outliers are reported but not scored. |
| Showing "raw" honestly | Raw rows are staged as text, exactly as parsed, so invalid values stay visible and the raw/processed comparison is real. |
| User-supplied column names in dynamic SQL | Generated, validated identifiers. Client column keys are checked against stored metadata, and all values are bound parameters. Injection attempts are covered by tests. |
| Atomic ingestion and loading | Metadata and staged rows are written in one transaction on one connection. Run output loads inside a transaction, and a failure removes any partial table. |
| Slow quality checks on large files | Profiled with cProfile. Nearly all time was row-by-row string work on repeated values, so each column is factorised and processed once per distinct value: about 3× faster, with identical results. |
| Slow bulk loads | PostgreSQL `COPY … FROM STDIN` replaced batched inserts: load stage 9.8 s → 4.2 s for 198k rows. |
| Same code on PostgreSQL and SQLite | SQLAlchemy Core throughout, with the same test suite run against both. That caught a real difference: NULL ordering in descending sorts. |
| Not over-claiming AI | Keys stay server-side. Only a profile (statistics, findings, 5 sample rows, no identifier lists) is sent, and the user can see it. The statistical answer always exists, and provider errors are shown as such. |
| Instant first load for recruiters | Code-split pages, charts loaded on demand, self-hosted fonts, immutable asset caching, and an always-on hosting recommendation sized from measured memory. |

## Measured results (build environment: 2 vCPU, PostgreSQL 16)

| Measure | Result |
|---|---|
| Automated tests | 52 backend tests passing on SQLite and on PostgreSQL; 10 frontend tests; strict TypeScript with 0 errors |
| End-to-end browser run | The full demonstration scenario in headless Chrome with 0 console errors |
| Sample dataset (2,448 rows) | Quality 98.9 → 99.9; rows with issues 465 → 57; 48 duplicates removed; 22 rows with negative quantities rejected; 93 category spellings normalised; whole run under 1 s |
| 200,000-row file | Ingestion 15.8 s → 6.3 s and full pipeline 32.6 s → 17.4 s after the two optimisations |
| Reads at 200k rows | Filtered and sorted Explorer page 159 ms; cached column statistics 7 ms |
| Memory | 149 MB idle; 261 MB peak at 50k rows; 556 MB peak at 200k rows (one worker) |
| First contentful paint | 244 ms on localhost (excludes network latency) |

The sample data is synthetic. These figures describe how the software behaves; they are not business-impact
claims.

## Engineering decisions to be ready to discuss

1. **Dynamic typed tables instead of JSON rows.** This trades a fixed schema for real SQL filtering, indexes
   and BI-tool compatibility. It is safe because identifiers are generated and validated.
2. **Background tasks instead of Celery.** Fewer moving parts for a single node. The runner is a plain function,
   so moving to a queue is straightforward, and the multi-worker restart limitation is documented.
3. **Leave missing numbers empty by default.** Median-filling revenue would distort totals; it is opt-in.
4. **httpx adapters instead of vendor SDKs.** One interface for two providers, easy to mock, smaller install.
5. **Render Starter vs Standard.** The choice is driven by measured memory (556 MB peak at 200k rows), not by
   price alone.

## A two-minute demo script

1. Overview (empty) → **Load sample dataset**. Point out the "Sample data" label.
2. Dataset page: inferred types, raw preview with the messy values still visible.
3. Data quality: the weighted bar ("width is the weight, fill is the score"), then a finding with its examples.
4. Create a pipeline, tick Transaction ID as required → **Save and run**. Watch the stage track fill in.
5. Run page: before/after table, the remaining findings, the execution log.
6. Explorer: filter Region = Central, sort revenue descending. Mention that only 50 rows reach the browser.
7. Analytics: revenue by category and by month. Switch to the raw source to show the warning.
8. Reports: download the pipeline run PDF.

## Roadmap

* Job queue (Redis + RQ/Celery) for runs and large ingestions, with progress and cancellation
* Authentication, workspaces and roles; audit log
* User-defined rules (e.g. `revenue = quantity × unit_price`, allowed values, regex), saved per dataset
* Scheduled pipelines and incremental loads; database and API sources besides files
* Object storage for originals and reports; chunked processing for files beyond memory
* Day-first date parsing per column; synonym maps for categories
* Automated accessibility audit (axe) and Playwright tests in CI; GitHub Actions pipeline
