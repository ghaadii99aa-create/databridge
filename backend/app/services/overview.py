"""Overview metrics — every figure is a query over stored application data."""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.visitor import SYSTEM_SCOPE, Scope
from app.models import Dataset, Pipeline, PipelineRun, QualityAssessment, Report


def overview(session: Session, scope: Scope = SYSTEM_SCOPE) -> dict[str, Any]:
    ds_visible = scope.visible(Dataset.owner_id)
    pl_visible = scope.visible(Pipeline.owner_id)
    visible_runs = select(PipelineRun.id).join(Pipeline).where(pl_visible)
    a_visible = or_(QualityAssessment.run_id.is_(None), QualityAssessment.run_id.in_(visible_runs))

    ds_counts = dict(session.execute(
        select(Dataset.status, func.count()).where(ds_visible).group_by(Dataset.status)).all())
    run_counts = dict(session.execute(
        select(PipelineRun.status, func.count()).join(Pipeline).where(pl_visible).group_by(PipelineRun.status)).all())
    records_ingested = session.scalar(
        select(func.coalesce(func.sum(Dataset.row_count), 0)).where(Dataset.status == "ready", ds_visible)) or 0
    records_processed = session.scalar(
        select(func.coalesce(func.sum(PipelineRun.rows_extracted), 0)).join(Pipeline)
        .where(PipelineRun.status == "succeeded", pl_visible)) or 0
    records_loaded = session.scalar(
        select(func.coalesce(func.sum(PipelineRun.rows_loaded), 0)).join(Pipeline)
        .where(PipelineRun.status == "succeeded", pl_visible)) or 0

    # current quality: latest assessment per ready dataset, preferring processed output
    latest_ids = select(func.max(QualityAssessment.id)).join(Dataset).where(Dataset.status == "ready", ds_visible, a_visible) \
        .group_by(QualityAssessment.dataset_id, QualityAssessment.stage)
    latest = session.scalars(select(QualityAssessment).where(QualityAssessment.id.in_(latest_ids))).all()
    best: dict[int, QualityAssessment] = {}
    for a in latest:
        cur = best.get(a.dataset_id)
        if cur is None or (a.stage == "processed" and cur.stage == "raw"):
            best[a.dataset_id] = a
    total_rows = sum(a.row_count for a in best.values())
    avg_score = round(sum(a.score * a.row_count for a in best.values()) / total_rows, 1) if total_rows else None

    trend = session.execute(
        select(QualityAssessment.id, QualityAssessment.created_at, QualityAssessment.score, QualityAssessment.stage,
               Dataset.name).join(Dataset).where(ds_visible, a_visible)
        .order_by(QualityAssessment.created_at.desc()).limit(30)
    ).all()
    runs = session.execute(
        select(PipelineRun.id, PipelineRun.status, PipelineRun.created_at, PipelineRun.duration_ms,
               PipelineRun.rows_loaded, PipelineRun.rows_rejected, Pipeline.name, Pipeline.id)
        .join(Pipeline).where(pl_visible).order_by(PipelineRun.id.desc()).limit(12)
    ).all()
    datasets = session.scalars(select(Dataset).where(ds_visible)
                               .order_by(Dataset.created_at.desc(), Dataset.id.desc()).limit(6)).all()

    activity: list[dict[str, Any]] = []
    for d in datasets:
        activity.append({"type": "dataset", "status": d.status, "at": d.created_at,
                         "text": f"Dataset '{d.name}' {'ingested' if d.status == 'ready' else d.status}",
                         "ref": d.id})
    for r in runs[:6]:
        activity.append({"type": "run", "status": r.status, "at": r.created_at,
                         "text": f"Run #{r.id} of '{r.name}' {r.status}", "ref": r.id})
    for rep in session.scalars(select(Report).where(scope.visible(Report.owner_id)).order_by(Report.id.desc()).limit(4)):
        activity.append({"type": "report", "status": "ready", "at": rep.created_at,
                         "text": f"Report generated: {rep.title}", "ref": rep.id})
    activity.sort(key=lambda x: x["at"], reverse=True)

    return {
        "datasets": {"total": sum(ds_counts.values()), "ready": ds_counts.get("ready", 0),
                     "failed": ds_counts.get("failed", 0)},
        "records": {"ingested": int(records_ingested), "processed": int(records_processed),
                    "loaded": int(records_loaded)},
        "runs": {"total": sum(run_counts.values()), "succeeded": run_counts.get("succeeded", 0),
                 "failed": run_counts.get("failed", 0),
                 "active": run_counts.get("running", 0) + run_counts.get("pending", 0)},
        "pipelines": session.scalar(select(func.count(Pipeline.id)).where(pl_visible)) or 0,
        "reports": session.scalar(select(func.count(Report.id)).where(scope.visible(Report.owner_id))) or 0,
        "quality": {"score": avg_score, "datasets_assessed": len(best),
                    "basis": "Row-weighted mean of each dataset's latest score (processed output when available)."},
        "quality_trend": [{"id": t.id, "at": t.created_at, "score": t.score, "stage": t.stage, "dataset": t.name}
                          for t in reversed(trend)],
        "recent_runs": [{"id": r.id, "status": r.status, "created_at": r.created_at, "duration_ms": r.duration_ms,
                         "rows_loaded": r.rows_loaded, "rows_rejected": r.rows_rejected, "pipeline_name": r.name,
                         "pipeline_id": r[7]} for r in runs],
        "latest_datasets": [{"id": d.id, "name": d.name, "status": d.status, "row_count": d.row_count,
                             "read_only": scope.read_only(d.owner_id),
                             "column_count": d.column_count, "created_at": d.created_at, "is_sample": d.is_sample,
                             "file_format": d.file_format} for d in datasets],
        "activity": activity[:10],
    }
