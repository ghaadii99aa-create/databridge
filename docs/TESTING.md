# Testing and measured results

All results on this page come from actual runs on 15–16 November 2026 in the build environment: Linux, 2 vCPU,
7 GB RAM, Python 3.13, Node 22, PostgreSQL 16. Your Windows laptop will produce different timings. Re-run the
commands below to get your own numbers.

## Automated tests

| Suite | Command | Result |
|---|---|---|
| Backend unit + API integration, SQLite | `cd backend; python -m pytest` | **71 passed** (52 core + 19 demo mode) |
| Same suite on PostgreSQL 16 | `TEST_DATABASE_URL=… python -m pytest` | **71 passed** |
| Migrations match models | `alembic check` | No new upgrade operations detected |
| Frontend type check | `npm run typecheck` | 0 errors (strict mode) |
| Frontend component tests | `npm test` (Vitest + Testing Library) | **10 passed** |
| Demo-mode browser test, two visitors | `python scripts/e2e_demo.py --base …` | **27 of 27 checks passed** |
| Upgrade of a populated database | data created with the previous release, then `alembic upgrade head` with this one | Data kept, still editable in local mode |
| Clean-install check | `scripts/setup.ps1` then `scripts/test.ps1 -Postgres …` on a fresh copy without dependencies, run under PowerShell 7 | All checks passed |

The PowerShell scripts were executed with PowerShell 7 on Linux (paths are cross-platform). They have not been
run on Windows itself, so treat the first run on your laptop as the real Windows test.

### What the backend tests cover

* **Unit:** identifier safety (SQL-injection-shaped names rejected), type inference (8 cases including
  currency, zero-padded codes and mixed date formats), null tokens, numeric parsing, the quality engine against
  a hand-calculated known answer (every dimension and the final score), outliers excluded from scoring, the
  cleaning rule order and counts, missing-value strategies, and settings parsing from a `.env` file.
* **API integration:** health and readiness; consistent error shape with request IDs; CSV, XLSX, semicolon and
  cp1252 uploads; rejection of `.exe`, fake `.xlsx`, binary `.csv`, empty and oversized files; header-only files
  recorded as failed; path-traversal filenames neutralised; delete removes the staging table.
* **The full demonstration workflow** in one test: sample upload → quality findings → pipeline → run (five
  stages, row accounting, quality improved, output table exists) → filtered and sorted Explorer query →
  statistics (six categories after normalisation) → raw/processed comparison → four chart types (totals
  cross-checked) → CSV export (row count checked) → six reports in PDF and CSV → Overview metrics match the run.
* **Failure paths:** a run whose staging table disappears fails at `extract`, logs an error and leaves no
  partial table; unknown columns in a pipeline config return 422.
* **Safety:** sort and filter injection attempts return 422; `%` in search is treated literally; CSV export
  neutralises spreadsheet formulas but keeps negative numbers; charts explain unsuitable columns instead of
  drawing.
* **AI analyst:** without a provider, only the statistical answer is returned; with a mocked provider the key
  is sent only in the server-side request header, the prompt contains at most 5 sample rows and no identifier
  lists, and a 401 from the provider still returns the statistical answer.
* **Security headers** on every response (CSP on HTML) in single-service mode.
* **Demo mode (`tests/test_demo.py`):** first visit is populated (sample, pipeline, successful run, report;
  Explorer, quality and analytics work); seeding is idempotent and restores a missing sample; shared items return
  `403 read_only` for delete, rename, edit, re-run and re-assess, and the sample's table survives; a second
  visitor gets `404` for the first visitor's dataset, preview, download, quality, explorer, analytics, AI analyst,
  reports, runs and processed output, and lists and Overview exclude them; a forged cookie gets a new identity;
  50,001 rows rejected with nothing kept while exactly 50,000 succeed; an 11 MB file rejected both with and
  without `Content-Length`; per-visitor quota; `429` with `Retry-After` after 10 uploads, health never limited;
  oversized JSON bodies rejected; cleanup removes only expired visitor data plus orphaned files and `stg_`/`prc_`
  tables, keeps fresh files, the sample, its files and tables, `alembic_version`, `app_settings` and an unrelated
  table; local mode is unchanged (no cookie, sample deletable).
* **Regression:** empty values sort last in both directions on both databases (a real bug found in browser
  testing: PostgreSQL sorts NULLs first in descending order).

## End-to-end browser test

`scripts/e2e_walkthrough.py` (Playwright, headless Chrome) runs against the production build served by FastAPI
on PostgreSQL with an empty database, and exits non-zero on any missing step or browser console error. It completed the full demonstration scenario through the UI with **0 console errors**: load
sample → dataset detail → quality → pipeline editor (required columns ticked) → save and run → run page →
explore output with a filter and sort → column statistics → analytics → AI analyst → reports → overview →
mobile viewport and menu. Screenshots are in `docs/screenshots/`.

## Demo-mode browser test

`scripts/e2e_demo.py` (Playwright, headless Chrome) runs against the production build in demo mode with an
empty database. Visitor A: the notice is shown, Overview is populated, the sample has no rename or delete,
the shared pipeline offers *Make a copy* instead of edit, delete and run, quality has no re-assess, Explorer
shows rows, Analytics draws charts, the shared report downloads but cannot be deleted, an upload succeeds and
is editable, and a 50,001-row file shows the limit message. Visitor B (a separate browser context) sees the
sample but not A's upload, and opening A's URL shows "does not exist". Every page is also checked at a
390 px phone width for horizontal overflow. Result: **27 of 27 checks passed, 0 console errors**. The original
`scripts/e2e_walkthrough.py` was also re-run in local mode and completed all 14 steps with 0 console errors.

## Bugs found and fixed during testing

| Found by | Bug | Fix |
|---|---|---|
| API tests (SQLite) | "database is locked": an ORM autoflush held a write transaction while the staging table was created on a second connection | Metadata and staged rows are now written on one connection in one transaction (also makes ingestion atomic) |
| Demo workflow test | "Home and Kitchen" not matched with "Home & Kitchen" (7 categories instead of 6) | Normaliser treats `&` and `and` as equivalent |
| Mocked AI test | Identifier values leaked into the AI prompt through "top values" | Identifier and free-text columns no longer share value lists |
| Browser review | Descending sort put empty revenue values first on PostgreSQL | Explicit `NULLS LAST`; regression test on both databases |
| Browser review | Comparison chart defaulted to a nested column and was mostly empty | Default split is the most detailed category with at most six values |
| Clean install | Comma-separated `CORS_ORIGINS` in `.env` crashed startup | Stored as a string and split explicitly |
| Clean install | `setup.ps1` reported success after a failed migration | Every native command's exit code is checked |
| PostgreSQL test rerun | Test teardown didn't drop tables (models not yet imported) | Models imported in `conftest.py` |
| Contrast check | Faint text 2.7:1 on the sidebar; failure badge 4.3:1 | Tokens darkened; all checked pairs ≥ 4.5:1 |
| First run on the Windows laptop (SQLite) | Times shown in UTC instead of local time (3 h off in Riyadh): SQLite drops the time zone | Timestamps always returned with a UTC offset; regression test added |
| Demo browser test | The size-limit error (413) had no `request_id`, unlike every other error | Same error shape everywhere; JSON bodies over 1 MB get `request_too_large` instead of a file message |
| Demo browser test (phone width) | Overview, dataset detail and Data quality were 20–44 px wider than a 390 px screen: grids grew to their content, and the quality bar's four segments were 100% wide plus the gaps | Single-column grids are constrained, the bar uses proportional flex widths (same 30/30/20/20 look) |
| Demo browser test (phone width) | Pipelines page 757 px wide: a hidden "Actions" label inside a scrolling table was positioned against the page | Panels are now positioning containers |
| Upgrade review | `scripts/dev.ps1` did not apply database migrations, so an existing laptop database would miss the new columns | `dev.ps1` runs `alembic upgrade head` before starting |

## Performance

`python scripts/benchmark.py --rows N` uploads a SAMPLE file built from the retail dataset, runs a pipeline and
times typical reads (median of 7). Server: one uvicorn worker on PostgreSQL 16.

### 200,000 rows (17.3 MB CSV)

| Operation | Before optimisation | After |
|---|---|---|
| Upload + validate + profile + stage + raw assessment | 15.81 s | **6.31 s** |
| Pipeline run, all five stages | 32.58 s | **17.41 s** |
| Validate stage (includes quality assessment) | 6.88 s | 3.35 s |
| Load stage (198,076 rows) | 9.78 s | 4.16 s |
| Profile stage (quality assessment of output) | 7.71 s | 4.25 s |

"Before" is the first measured version (row-by-row string work, batched `INSERT`). "After" adds per-unique-value
evaluation and PostgreSQL `COPY` (see `ARCHITECTURE.md §9`). The quality scores were identical before and after
(99.3 → 99.9).

Reads after optimisation, at 200k rows: Explorer page 49 ms, Explorer with two filters and a sort 159 ms, text
search 405 ms, category chart 608 ms, monthly time series 851 ms, column statistics 1,636 ms first time and
7 ms cached, overview 17 ms, health check 2.5 ms.

### 50,000 rows (4.3 MB CSV)

| Operation | Time |
|---|---|
| Upload + validate + profile + stage + raw assessment | 2.14 s |
| Pipeline run, all five stages | 4.53 s |
| Explorer page / filtered + sorted page | 46 ms / 77 ms |
| Category chart / monthly time series | 129 ms / 171 ms |

### Memory (resident set size, one worker)

| State | Peak RSS |
|---|---|
| Idle after start | 149 MB |
| After loading the 2,448-row sample | 162 MB |
| During the 50,000-row benchmark | 261 MB |
| During the 200,000-row benchmark | 556 MB |

### Frontend

* Production bundle: shell + React ≈ 75 KB gzipped JS, plus each page as its own 1–4 KB chunk. Recharts
  (111 KB gzipped) loads only on pages with charts; on the Overview it loads once a trend exists.
* First contentful paint on localhost: 244 ms median of 5 cold loads (no network latency included).
* The empty-state Overview was visible 0.48–0.54 s after navigation in the Playwright runs.

## Not tested here

* **Docker images were not built.** The sandbox blocks Docker Hub, so base images could not be pulled.
  `docker compose config` validated the file, and the runtime paths the images use (PostgreSQL 16, migrations on
  start, FastAPI serving the built SPA with two workers) were tested directly. Build them with
  `docker compose up --build` on your machine.
* nginx configuration syntax (nginx was not available); it is used only by the compose stack.
* A real AI provider call (no key used); the adapter is tested with a mocked HTTP transport.
* Native Windows execution (see the note above). `scripts/demo.ps1` and the updated `scripts/dev.ps1` were
  syntax-checked with PowerShell 7 but not launched, because they open new Windows PowerShell windows.
* Demo-mode cleanup timing in a long-running server: the hourly thread was not left running for 24 hours;
  cleanup itself is tested by calling it with a simulated time 25 hours ahead.
* Automated accessibility audit (axe) and cross-browser testing beyond Chromium.
