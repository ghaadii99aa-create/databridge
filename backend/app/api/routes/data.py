"""Explorer, analytics, AI analyst and reports."""
from __future__ import annotations

import json
from typing import Literal

from fastapi import Response, APIRouter, Query, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import TypeAdapter, ValidationError

from app.api.deps import SessionDep
from app.core.errors import ValidationFailed
from app.core.visitor import ScopeDep
from app.schemas import AskIn, ReportIn, ReportOut
from app.services import access, analytics, explorer
from app.services.ai import analyst
from app.services.ai.providers import provider_status
from app.services.reports import builder

router = APIRouter()
SOURCE = Query(..., pattern=r"^(raw|processed)-\d+$", description="raw-<dataset_id> or processed-<run_id>")
_filters = TypeAdapter(list[explorer.Filter])


def _parse_filters(raw: str | None) -> list[explorer.Filter]:
    if not raw:
        return []
    try:
        return _filters.validate_python(json.loads(raw))[:20]
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValidationFailed("filters must be a JSON list of {column, op, value}") from exc


# ---- explorer ------------------------------------------------------------------------

@router.get("/explorer/sources", tags=["explorer"])
def sources(session: SessionDep, scope: ScopeDep) -> list[dict]:
    return explorer.list_sources(session, scope)


@router.get("/explorer/rows", tags=["explorer"])
def rows(session: SessionDep, scope: ScopeDep, source: str = SOURCE, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
         search: str | None = Query(None, max_length=200), sort: str | None = Query(None, max_length=63),
         order: Literal["asc", "desc"] = "asc", filters: str | None = Query(None, max_length=4000)) -> dict:
    access.source(session, scope, source)
    return explorer.query_rows(session, source, page, page_size, search, _parse_filters(filters), sort, order)


@router.get("/explorer/stats", tags=["explorer"])
def stats(session: SessionDep, scope: ScopeDep, source: str = SOURCE) -> dict:
    access.source(session, scope, source)
    return explorer.column_stats(session, source)


@router.get("/explorer/export", tags=["explorer"])
def export(session: SessionDep, scope: ScopeDep, source: str = SOURCE) -> StreamingResponse:
    access.source(session, scope, source)
    filename, body = explorer.export_csv(session, source)
    return StreamingResponse(body, media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/runs/{run_id}/comparison", tags=["explorer"])
def compare(run_id: int, session: SessionDep, scope: ScopeDep) -> dict:
    access.run(session, scope, run_id)
    return explorer.compare_run(session, run_id)


# ---- analytics -----------------------------------------------------------------------

Agg = Literal["count", "sum", "mean", "median"]


@router.get("/analytics/suitability", tags=["analytics"])
def suitability(session: SessionDep, scope: ScopeDep, source: str = SOURCE) -> dict:
    access.source(session, scope, source)
    return analytics.suitability(session, source)


@router.get("/analytics/distribution", tags=["analytics"])
def distribution(session: SessionDep, scope: ScopeDep, source: str = SOURCE, column: str = Query(...), bins: int = Query(20, ge=5, le=60)) -> dict:
    access.source(session, scope, source)
    return analytics.distribution(session, source, column, bins)


@router.get("/analytics/category", tags=["analytics"])
def category(session: SessionDep, scope: ScopeDep, source: str = SOURCE, column: str = Query(...), measure: str | None = None,
             agg: Agg = "count", limit: int = Query(12, ge=3, le=50)) -> dict:
    access.source(session, scope, source)
    return analytics.category_breakdown(session, source, column, measure, agg, limit)


@router.get("/analytics/timeseries", tags=["analytics"])
def timeseries(session: SessionDep, scope: ScopeDep, source: str = SOURCE, column: str = Query(...), measure: str | None = None,
               agg: Agg = "count", freq: Literal["auto", "D", "W", "M", "Q"] = "auto") -> dict:
    access.source(session, scope, source)
    return analytics.timeseries(session, source, column, measure, agg, freq)


@router.get("/analytics/comparison", tags=["analytics"])
def comparison(session: SessionDep, scope: ScopeDep, source: str = SOURCE, column: str = Query(...), split: str = Query(...),
               measure: str | None = None, agg: Agg = "count", limit: int = Query(8, ge=2, le=15)) -> dict:
    access.source(session, scope, source)
    return analytics.comparison(session, source, column, split, measure, agg, limit)


# ---- AI analyst ----------------------------------------------------------------------

@router.get("/analyst/status", tags=["analyst"])
def analyst_status() -> dict:
    return provider_status()


@router.post("/analyst/ask", tags=["analyst"])
def ask(body: AskIn, session: SessionDep, scope: ScopeDep) -> dict:
    access.source(session, scope, body.source)
    return analyst.ask(session, body.source, body.question.strip())


# ---- reports -------------------------------------------------------------------------

@router.get("/reports", response_model=list[ReportOut], tags=["reports"])
def list_reports(session: SessionDep, scope: ScopeDep):
    return [_report_out(r, scope) for r in builder.list_reports(session, scope)]


def _report_out(r, scope) -> ReportOut:
    out = ReportOut.model_validate(r)
    out.read_only = scope.read_only(r.owner_id)
    return out


@router.post("/reports", response_model=ReportOut, status_code=status.HTTP_201_CREATED, tags=["reports"])
def create_report(body: ReportIn, session: SessionDep, scope: ScopeDep):
    if body.dataset_id is not None:
        access.dataset(session, scope, body.dataset_id)
    if body.run_id is not None:
        access.run(session, scope, body.run_id)
    if body.assessment_id is not None:
        access.assessment(session, scope, body.assessment_id)
    return _report_out(builder.generate(session, body.kind, body.format, body.dataset_id, body.run_id,
                                        body.assessment_id, owner_id=scope.owner_for_new), scope)


@router.get("/reports/{report_id}/download", tags=["reports"])
def download_report(report_id: int, session: SessionDep, scope: ScopeDep) -> FileResponse:
    access.report(session, scope, report_id)
    report, path = builder.report_path(session, report_id)
    safe_title = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in report.title).strip()[:80]
    media = "application/pdf" if report.format == "pdf" else "text/csv"
    return FileResponse(path, media_type=media, filename=f"{safe_title}.{report.format}")


@router.delete("/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, response_model=None, tags=["reports"])
def delete_report(report_id: int, session: SessionDep, scope: ScopeDep) -> None:
    access.report(session, scope, report_id, modify=True)
    builder.delete_report(session, report_id)
