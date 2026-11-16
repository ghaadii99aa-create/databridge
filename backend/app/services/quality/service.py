"""Persistence layer around the quality engine."""
from __future__ import annotations

import pandas as pd
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import NotFound, ValidationFailed
from app.db import get_engine
from app.core.visitor import SYSTEM_SCOPE, Scope
from app.models import Dataset, Pipeline, PipelineRun, QualityAssessment, QualityIssue
from app.services import tables
from app.services.quality.engine import METHODOLOGY_VERSION, ColumnSpec, QualityResult, assess


def column_specs(dataset: Dataset) -> list[ColumnSpec]:
    return [ColumnSpec(c.key, c.name, c.inferred_type) for c in dataset.columns]


def save_result(
    session: Session, dataset: Dataset, result: QualityResult, stage: str, run: PipelineRun | None = None
) -> QualityAssessment:
    assessment = QualityAssessment(
        dataset_id=dataset.id, run_id=run.id if run else None, stage=stage,
        score=result.score, row_count=result.row_count, column_count=result.column_count,
        total_issues=result.total_issues, affected_rows=result.affected_rows,
        methodology_version=METHODOLOGY_VERSION,
        details={"counts": result.counts, "columns": result.column_summary},
        **result.dimensions,
    )
    assessment.issues = [
        QualityIssue(**{k: v for k, v in issue.to_dict().items()}) for issue in result.issues
    ]
    session.add(assessment)
    session.flush()
    return assessment


def assess_dataset(session: Session, dataset: Dataset, frame: pd.DataFrame | None = None) -> QualityAssessment:
    """Assess the raw (staged) data of a dataset."""
    if frame is None:
        if dataset.status != "ready" or not dataset.staging_table:
            raise ValidationFailed("Only successfully ingested datasets can be assessed.")
        frame = tables.read_frame(get_engine(), dataset.staging_table)
    result = assess(frame, column_specs(dataset))
    return save_result(session, dataset, result, "raw")


def latest_assessment(session: Session, dataset_id: int, stage: str = "raw",
                      run_id: int | None = None) -> QualityAssessment | None:
    """Latest raw assessment of the dataset itself (not made by a pipeline run), or the
    processed assessment of a specific run."""
    run_filter = QualityAssessment.run_id.is_(None) if run_id is None else QualityAssessment.run_id == run_id
    stmt = (
        select(QualityAssessment)
        .where(QualityAssessment.dataset_id == dataset_id, QualityAssessment.stage == stage, run_filter)
        .options(selectinload(QualityAssessment.issues))
        .order_by(QualityAssessment.created_at.desc(), QualityAssessment.id.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def get_assessment(session: Session, assessment_id: int) -> QualityAssessment:
    a = session.get(QualityAssessment, assessment_id, options=[selectinload(QualityAssessment.issues)])
    if not a:
        raise NotFound(f"Assessment {assessment_id} does not exist")
    return a


def history(session: Session, dataset_id: int, scope: Scope = SYSTEM_SCOPE) -> list[QualityAssessment]:
    visible_runs = select(PipelineRun.id).join(Pipeline).where(scope.visible(Pipeline.owner_id))
    stmt = (
        select(QualityAssessment)
        .where(QualityAssessment.dataset_id == dataset_id,
               or_(QualityAssessment.run_id.is_(None), QualityAssessment.run_id.in_(visible_runs)))
        .order_by(QualityAssessment.created_at, QualityAssessment.id)
    )
    return list(session.scalars(stmt))
