# API reference

The backend is a REST API under `/api`. Interactive documentation (OpenAPI / Swagger UI) is served by the
running backend at **http://127.0.0.1:8000/api/docs**, and the machine-readable schema at `/api/openapi.json`.
The table below is generated from that schema.

| Area | Method | Path | Summary |
|---|---|---|---|
| health | `GET` | `/api/health` | Liveness |
| health | `GET` | `/api/health/ready` | Readiness |
| overview | `GET` | `/api/overview` | Get Overview |
| datasets | `GET` | `/api/datasets` | List Datasets |
| datasets | `POST` | `/api/datasets` | Upload Dataset |
| datasets | `GET` | `/api/datasets/limits` | Upload Limits |
| datasets | `POST` | `/api/datasets/sample` | Load Sample |
| datasets | `DELETE` | `/api/datasets/{dataset_id}` | Delete Dataset |
| datasets | `GET` | `/api/datasets/{dataset_id}` | Get Dataset |
| datasets | `PATCH` | `/api/datasets/{dataset_id}` | Update Dataset |
| datasets | `GET` | `/api/datasets/{dataset_id}/download` | Download Original |
| datasets | `GET` | `/api/datasets/{dataset_id}/preview` | Preview |
| datasets | `GET` | `/api/datasets/{dataset_id}/quality` | Latest Quality |
| datasets | `POST` | `/api/datasets/{dataset_id}/quality` | Run Quality |
| datasets | `GET` | `/api/datasets/{dataset_id}/quality/history` | Quality History |
| quality | `GET` | `/api/quality/assessments/{assessment_id}` | Get Assessment |
| quality | `GET` | `/api/quality/methodology` | Quality Methodology |
| pipelines | `GET` | `/api/pipelines` | List Pipelines |
| pipelines | `POST` | `/api/pipelines` | Create Pipeline |
| pipelines | `GET` | `/api/pipelines/rules` | Transformation Rules |
| pipelines | `DELETE` | `/api/pipelines/{pipeline_id}` | Delete Pipeline |
| pipelines | `GET` | `/api/pipelines/{pipeline_id}` | Get Pipeline |
| pipelines | `PUT` | `/api/pipelines/{pipeline_id}` | Update Pipeline |
| pipelines | `POST` | `/api/pipelines/{pipeline_id}/runs` | Start Run |
| pipelines | `GET` | `/api/runs` | List Runs |
| pipelines | `GET` | `/api/runs/{run_id}` | Get Run |
| explorer | `GET` | `/api/explorer/export` | Export |
| explorer | `GET` | `/api/explorer/rows` | Rows |
| explorer | `GET` | `/api/explorer/sources` | Sources |
| explorer | `GET` | `/api/explorer/stats` | Stats |
| explorer | `GET` | `/api/runs/{run_id}/comparison` | Compare |
| analytics | `GET` | `/api/analytics/category` | Category |
| analytics | `GET` | `/api/analytics/comparison` | Comparison |
| analytics | `GET` | `/api/analytics/distribution` | Distribution |
| analytics | `GET` | `/api/analytics/suitability` | Suitability |
| analytics | `GET` | `/api/analytics/timeseries` | Timeseries |
| analyst | `POST` | `/api/analyst/ask` | Ask |
| analyst | `GET` | `/api/analyst/status` | Analyst Status |
| reports | `GET` | `/api/reports` | List Reports |
| reports | `POST` | `/api/reports` | Create Report |
| reports | `DELETE` | `/api/reports/{report_id}` | Delete Report |
| reports | `GET` | `/api/reports/{report_id}/download` | Download Report |

## Conventions

**Sources.** Explorer, analytics and analyst endpoints take a `source` parameter: `raw-<dataset_id>` for the
staged raw rows of a dataset, or `processed-<run_id>` for the typed output of a pipeline run.

**Errors.** Every error has the same shape, and the `x-request-id` response header carries the same ID:

```json
{
  "error": { "code": "validation_failed", "message": "Unknown column(s) in pipeline configuration",
             "details": { "columns": ["nope"] } },
  "request_id": "3f9c0d1a2b4e"
}
```

| Status | `code` | When |
|---|---|---|
| 403 | `read_only` | Demo mode: the item is shared demonstration data |
| 404 | `not_found` | Resource does not exist (in demo mode also: it belongs to another visitor) |
| 409 | `conflict` | A run of the pipeline is already in progress |
| 413 | `file_too_large` | Upload exceeds `MAX_UPLOAD_MB` (checked from `Content-Length` and while streaming) |
| 413 | `request_too_large` | Any other request body over 1 MB |
| 413 | `limit_exceeded` | Too many rows or columns (nothing is kept), or a demo per-visitor quota is reached |
| 429 | `rate_limited` | Demo mode rate limit; the `Retry-After` header gives the wait in seconds |
| 415 | `unsupported_file` | Wrong extension, or content does not match it |
| 422 | `validation_failed` | Invalid input, unknown column, unsuitable chart column |
| 500 | `internal_error` | Unexpected; details only in the server log |
| 502 | `ai_provider_error` | Returned inside the analyst answer, never as a failed request |

**Explorer filters** are a JSON list in the `filters` query parameter:
`[{"column": "region", "op": "eq", "value": "Central"}, {"column": "quantity", "op": "gte", "value": "3"}]`.
Operators: `eq`, `neq`, `contains`, `gt`, `gte`, `lt`, `lte`, `is_null`, `not_null`. Raw sources store text, so
only `eq`, `neq`, `contains`, `is_null` and `not_null` are accepted there.

**Demo mode.** With `DEMO_MODE=true` the API sets an anonymous `databridge_visitor` cookie and scopes every
list and lookup to shared data plus the caller's own data. Responses for datasets, pipelines, runs and reports
include `read_only: true` for shared items. `GET /api/datasets/limits` and the `demo` field of
`GET /api/overview` report the active limits. See [DEMO_MODE.md](DEMO_MODE.md).

**Pipeline runs** are asynchronous: `POST /api/pipelines/{id}/runs` returns `202` with the run, which then moves
`pending → running → succeeded | failed`. Poll `GET /api/runs/{id}` for status, stage timings and logs.

## Example: the demonstration workflow with curl

```bash
curl -X POST http://127.0.0.1:8000/api/datasets/sample                       # load SAMPLE data -> id 1
curl http://127.0.0.1:8000/api/datasets/1/quality                             # quality findings
curl -X POST http://127.0.0.1:8000/api/pipelines -H "content-type: application/json" \
     -d '{"dataset_id": 1, "name": "Clean retail", "config": {"required_columns": ["transaction_id"]}}'
curl -X POST http://127.0.0.1:8000/api/pipelines/1/runs                       # -> run id 1
curl http://127.0.0.1:8000/api/runs/1                                         # poll until succeeded
curl "http://127.0.0.1:8000/api/analytics/category?source=processed-1&column=region&measure=revenue_sar&agg=sum"
curl -X POST http://127.0.0.1:8000/api/reports -H "content-type: application/json" \
     -d '{"kind": "pipeline_run", "format": "pdf", "run_id": 1}'
```

On Windows PowerShell use `Invoke-RestMethod` instead, for example
`Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/datasets/sample`.
