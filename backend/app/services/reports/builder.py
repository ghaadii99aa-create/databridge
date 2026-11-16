"""Report generation (PDF and CSV) from stored results.

Reports are built only from persisted data — quality assessments, run logs, column
statistics — so every number in a report can be traced back to the database.
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import NotFound, ValidationFailed
from app.core.storage import ensure_dirs, remove_file, safe_child
from app.core.visitor import SYSTEM_SCOPE, Scope
from app.models import Dataset, PipelineRun, QualityAssessment, Report
from app.services import explorer
from app.services.etl import run_quality
from app.services.quality.engine import CHECKS, WEIGHTS
from app.services.quality.service import get_assessment, latest_assessment

CHARCOAL = colors.HexColor("#242824")
FOREST = colors.HexColor("#526B58")
SAGE = colors.HexColor("#DCE5DC")
WARM_GRAY = colors.HexColor("#E8E6DF")
OFF_WHITE = colors.HexColor("#F7F6F2")
TERRACOTTA = colors.HexColor("#B87559")
MUTED = colors.HexColor("#5E625B")

STYLES = {
    "eyebrow": ParagraphStyle("eyebrow", fontName="Helvetica-Bold", fontSize=7.5, textColor=FOREST, leading=10, spaceAfter=2),
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=18, textColor=CHARCOAL, leading=22, spaceAfter=4),
    "meta": ParagraphStyle("meta", fontName="Helvetica", fontSize=8.5, textColor=MUTED, leading=12),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11, textColor=CHARCOAL, leading=14, spaceBefore=12, spaceAfter=6),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9, textColor=CHARCOAL, leading=13, alignment=TA_LEFT),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8, textColor=CHARCOAL, leading=10),
    "cell_r": ParagraphStyle("cell_r", fontName="Helvetica", fontSize=8, textColor=CHARCOAL, leading=10, alignment=TA_RIGHT),
    "note": ParagraphStyle("note", fontName="Helvetica-Oblique", fontSize=7.5, textColor=MUTED, leading=10, spaceBefore=6),
}

KIND_TITLES = {"dataset_summary": "Dataset summary", "quality": "Data quality report", "pipeline_run": "Pipeline run report"}


def _esc(text: Any) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _num(v: Any, digits: int = 2) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.{digits}f}" if not v.is_integer() else f"{v:,.0f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def _table(rows: list[list[Any]], widths: list[float], numeric_cols: tuple[int, ...] = ()) -> Table:
    data = [[Paragraph(_esc(c), STYLES["cell_r" if j in numeric_cols else "cell"]) if isinstance(c, str) else c
             for j, c in enumerate(r)] for i, r in enumerate(rows)]
    for j in numeric_cols:  # header labels of numeric columns align with their values
        data[0][j] = Paragraph(f"<b>{_esc(rows[0][j])}</b>", ParagraphStyle("h_r", parent=STYLES["cell_r"], textColor=MUTED))
    t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    style = [
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, CHARCOAL),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, WARM_GRAY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ]
    for c in numeric_cols:
        style.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    t.setStyle(TableStyle(style))
    return t


def _kpis(items: list[tuple[str, str]]) -> Table:
    cells = [[Paragraph(f"<font size=7.5 color='#5E625B'>{_esc(label)}</font><br/>"
                        f"<font size=14 name='Helvetica-Bold'>{_esc(value)}</font>", ParagraphStyle("kpi", parent=STYLES["body"], leading=18))
              for label, value in items]]
    t = Table(cells, colWidths=[(A4[0] - 36 * mm) / len(items)] * len(items))
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, WARM_GRAY), ("INNERGRID", (0, 0), (-1, -1), 0.5, WARM_GRAY),
        ("BACKGROUND", (0, 0), (-1, -1), OFF_WHITE), ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9), ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _header(kind: str, title: str, subtitle: str, is_sample: bool) -> list[Any]:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    flow = [Paragraph(f"DataBridge {KIND_TITLES[kind].lower()}", STYLES["eyebrow"]),
            Paragraph(_esc(title), STYLES["title"]),
            Paragraph(f"{_esc(subtitle)}. Generated {now}.", STYLES["meta"])]
    if is_sample:
        flow.append(Paragraph("<font color='#8A5039'><b>Sample data.</b></font> This report was produced from the "
                              "synthetic demonstration dataset, not from real business records.", STYLES["meta"]))
    flow.append(Spacer(1, 8))
    return flow


def _footer(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    canvas.setStrokeColor(WARM_GRAY)
    canvas.line(18 * mm, 14 * mm, A4[0] - 18 * mm, 14 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 10 * mm, "DataBridge — figures computed from stored results")
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _quality_section(a: QualityAssessment, heading: str) -> list[Any]:
    counts = (a.details or {}).get("counts", {})
    flow: list[Any] = [Paragraph(heading, STYLES["h2"]),
                       _kpis([("Quality score", f"{a.score:.1f}"), ("Issues", str(a.total_issues)),
                              ("Rows affected", f"{a.affected_rows:,}"), ("Rows", f"{a.row_count:,}")]),
                       Spacer(1, 8)]
    dims = [["Dimension", "Weight", "Score", "Basis"],
            ["Completeness", f"{WEIGHTS['completeness']:.0%}", f"{a.completeness:.2f}",
             f"{counts.get('missing_cells', 0):,} missing of {counts.get('total_cells', 0):,} cells"],
            ["Validity", f"{WEIGHTS['validity']:.0%}", f"{a.validity:.2f}",
             f"{counts.get('invalid_cells', 0):,} invalid of {counts.get('typed_cells', 0):,} typed cells"],
            ["Uniqueness", f"{WEIGHTS['uniqueness']:.0%}", f"{a.uniqueness:.2f}",
             f"{counts.get('duplicate_rows', 0):,} duplicate of {a.row_count:,} rows"],
            ["Consistency", f"{WEIGHTS['consistency']:.0%}", f"{a.consistency:.2f}",
             f"{counts.get('inconsistent_cells', 0):,} inconsistent of {counts.get('textlike_cells', 0):,} text cells"]]
    flow.append(_table(dims, [32 * mm, 18 * mm, 18 * mm, 106 * mm], (1, 2)))
    if a.issues:
        rows = [["Severity", "Check", "Column", "Rows", "Finding and recommendation"]]
        for i in a.issues:
            rows.append([i.severity.capitalize(), CHECKS[i.check_code]["title"], i.column_name or "All columns",
                         _num(i.affected_rows), f"{i.message} {i.recommendation}"])
        flow += [Paragraph("Issues", STYLES["h2"]), _table(rows, [18 * mm, 30 * mm, 28 * mm, 14 * mm, 84 * mm], (3,))]
    flow.append(Paragraph(f"Score = 100 × (0.30·Completeness + 0.30·Validity + 0.20·Uniqueness + 0.20·Consistency). "
                          f"Methodology v{a.methodology_version}. Outliers are informational and not scored.", STYLES["note"]))
    return flow


def _dataset_summary(session: Session, dataset: Dataset) -> tuple[list[Any], list[list[Any]]]:
    stats = explorer.column_stats(session, f"raw-{dataset.id}")["columns"]
    a = latest_assessment(session, dataset.id, "raw")
    flow = _header("dataset_summary", dataset.name, f"{dataset.original_filename}", dataset.is_sample)
    flow.append(_kpis([("Rows", f"{dataset.row_count:,}"), ("Columns", str(dataset.column_count)),
                       ("File size", f"{dataset.file_size_bytes / 1024:,.0f} KB"),
                       ("Quality score", f"{a.score:.1f}" if a else "—")]))
    flow.append(Paragraph("Columns", STYLES["h2"]))
    rows = [["Column", "Type", "Missing", "Distinct", "Summary"]]
    csv_rows: list[list[Any]] = [["column", "type", "missing", "distinct", "mean", "median", "min", "max", "top_value"]]
    for c in stats:
        if "mean" in c:
            summary = f"min {_num(c['min'])} · median {_num(c['median'])} · max {_num(c['max'])}"
        elif "span_days" in c:
            summary = f"{c['min'][:10]} → {c['max'][:10]}"
        else:
            top = c.get("top_values") or []
            summary = ", ".join(f"{t['value']} ({t['count']:,})" for t in top[:3])
        rows.append([c["name"], c["type"], _num(c["missing"]), _num(c["distinct"]), summary])
        csv_rows.append([c["name"], c["type"], c["missing"], c["distinct"], c.get("mean"), c.get("median"),
                         c.get("min"), c.get("max"), (c.get("top_values") or [{}])[0].get("value")])
    flow.append(_table(rows, [38 * mm, 20 * mm, 16 * mm, 16 * mm, 84 * mm], (2, 3)))
    if a:
        flow += _quality_section(a, "Data quality (raw data)")
    return flow, csv_rows


def _quality_report(session: Session, dataset: Dataset, assessment_id: int | None) -> tuple[list[Any], list[list[Any]]]:
    a = get_assessment(session, assessment_id) if assessment_id else latest_assessment(session, dataset.id, "raw")
    if not a or a.dataset_id != dataset.id:
        raise ValidationFailed("No quality assessment found for this dataset.")
    stage = "processed output" if a.stage == "processed" else "raw data"
    flow = _header("quality", dataset.name, f"Assessment #{a.id} of {stage}", dataset.is_sample)
    flow += _quality_section(a, "Result")
    csv_rows: list[list[Any]] = [["severity", "check", "dimension", "column", "affected_rows", "affected_ratio", "message",
                                  "recommendation", "examples"]]
    for i in a.issues:
        csv_rows.append([i.severity, i.check_code, i.dimension, i.column_name or "", i.affected_rows, i.affected_ratio,
                         i.message, i.recommendation, " | ".join(map(str, i.examples or []))])
    return flow, csv_rows


def _run_report(session: Session, run: PipelineRun) -> tuple[list[Any], list[list[Any]]]:
    dataset = run.pipeline.dataset
    q = run_quality(session, run.id)
    flow = _header("pipeline_run", f"{run.pipeline.name} — run #{run.id}", f"Source: {dataset.name}", dataset.is_sample)
    flow.append(_kpis([("Status", run.status.capitalize()), ("Rows extracted", _num(run.rows_extracted)),
                       ("Rows loaded", _num(run.rows_loaded)), ("Rows rejected", _num(run.rows_rejected)),
                       ("Duration", f"{(run.duration_ms or 0) / 1000:.2f} s")]))
    if q["before"] and q["after"]:
        b, a = q["before"], q["after"]
        flow.append(Paragraph("Quality before and after", STYLES["h2"]))
        rows = [["Measure", "Source", "Processed", "Change"]]
        for label, attr in [("Quality score", "score"), ("Completeness", "completeness"), ("Validity", "validity"),
                            ("Uniqueness", "uniqueness"), ("Consistency", "consistency"),
                            ("Issues", "total_issues"), ("Rows affected", "affected_rows"), ("Rows", "row_count")]:
            bv, av = getattr(b, attr), getattr(a, attr)
            fmt = (lambda v: f"{v:,.2f}") if isinstance(bv, float) else _num
        rows.append([label, fmt(bv), fmt(av), f"{av - bv:+,.2f}" if isinstance(bv, float) else f"{av - bv:+,}"])
        flow.append(_table(rows, [50 * mm, 38 * mm, 38 * mm, 48 * mm], (1, 2, 3)))
    if run.error_message:
        flow += [Paragraph("Failure", STYLES["h2"]),
                 Paragraph(f"Stage <b>{_esc(run.error_stage)}</b>: {_esc(run.error_message)}", STYLES["body"])]
    timings = run.stage_timings_ms or {}
    flow.append(Paragraph("Stages", STYLES["h2"]))
    flow.append(_table([["Stage", "Duration (ms)"]] + [[k, _num(v)] for k, v in timings.items()], [60 * mm, 40 * mm], (1,)))
    rows = [["Time (UTC)", "Stage", "Level", "Message"]]
    csv_rows: list[list[Any]] = [["time", "stage", "level", "message"]]
    for lg in run.logs:
        ts = lg.created_at.strftime("%H:%M:%S.%f")[:-3]
        rows.append([ts, lg.stage, lg.level, lg.message])
        csv_rows.append([lg.created_at.isoformat(), lg.stage, lg.level, lg.message])
    flow += [Paragraph("Execution log", STYLES["h2"]),
             _table(rows, [24 * mm, 20 * mm, 16 * mm, 114 * mm])]
    return flow, csv_rows


def generate(session: Session, kind: str, fmt: str, dataset_id: int | None = None, run_id: int | None = None,
             assessment_id: int | None = None, owner_id: str | None = None) -> Report:
    if kind == "pipeline_run":
        run = session.get(PipelineRun, run_id) if run_id else None
        if not run:
            raise NotFound("A valid run_id is required for a pipeline run report")
        dataset = run.pipeline.dataset
        flow, csv_rows = _run_report(session, run)
        title = f"Run #{run.id} — {run.pipeline.name}"
    else:
        dataset = session.get(Dataset, dataset_id) if dataset_id else None
        if not dataset or dataset.status != "ready":
            raise NotFound("A ready dataset is required for this report")
        if kind == "dataset_summary":
            flow, csv_rows = _dataset_summary(session, dataset)
            title = f"Summary — {dataset.name}"
        else:
            flow, csv_rows = _quality_report(session, dataset, assessment_id)
            title = f"Quality — {dataset.name}"

    settings = get_settings()
    ensure_dirs(settings.report_dir)
    filename = f"{uuid.uuid4().hex}.{fmt}"
    path = safe_child(settings.report_dir, filename)
    if fmt == "pdf":
        doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                                topMargin=16 * mm, bottomMargin=20 * mm, title=title, author="DataBridge")
        doc.build(flow, onFirstPage=_footer, onLaterPages=_footer)
    else:
        buf = io.StringIO()
        csv.writer(buf).writerows([[explorer._safe_cell(v) for v in r] for r in csv_rows])
        path.write_text("﻿" + buf.getvalue(), encoding="utf-8")

    report = Report(kind=kind, format=fmt, title=title, dataset_id=dataset.id, run_id=run_id,
                    stored_filename=filename, size_bytes=path.stat().st_size, owner_id=owner_id)
    session.add(report)
    session.commit()
    return report


def list_reports(session: Session, scope: Scope = SYSTEM_SCOPE) -> list[Report]:
    return list(session.scalars(select(Report).where(scope.visible(Report.owner_id))
                                .order_by(Report.created_at.desc(), Report.id.desc())))


def report_path(session: Session, report_id: int) -> tuple[Report, Any]:
    report = session.get(Report, report_id)
    if not report:
        raise NotFound(f"Report {report_id} does not exist")
    path = safe_child(get_settings().report_dir, report.stored_filename)
    if not path.exists():
        raise NotFound("The report file is no longer available on disk")
    return report, path


def delete_report(session: Session, report_id: int) -> None:
    report = session.get(Report, report_id)
    if not report:
        raise NotFound(f"Report {report_id} does not exist")
    remove_file(get_settings().report_dir, report.stored_filename)
    session.delete(report)
    session.commit()
