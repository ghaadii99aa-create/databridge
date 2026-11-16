"""ETL pipelines: definition management and the run executor.

A run goes through five stages, each logged with its duration:

    extract  → read raw rows from the dataset's staging table (the landing layer)
    validate → check configuration against the schema, assess raw quality
    transform→ apply the pipeline's rules (services/cleaning.py)
    load     → create prc_<run_id> with typed columns and bulk insert, in one transaction
    profile  → assess the processed data with the same rules, record output metadata

Any exception marks the run failed, records the stage and message, and removes a partially
created output table. Runs execute in a FastAPI background task; the executor is a plain
function that opens its own session, so it can move to a job queue without changes.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.identifiers import processed_table_name
from app.core.visitor import SYSTEM_SCOPE, Scope
from app.db import get_engine, session_factory
from app.models import (
    Dataset, Pipeline, PipelineRun, PipelineRunLog, ProcessedDataset, QualityAssessment, utcnow,
)
from app.services import tables
from app.services.cleaning import TransformConfig, to_raw_strings, transform
from app.services.quality.engine import assess
from app.services.quality.service import column_specs, save_result

log = logging.getLogger(__name__)
STAGES = ("extract", "validate", "transform", "load", "profile")


class StageFailed(Exception):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.message = message


# ---------------------------------------------------------------- pipeline definitions

def validate_config(dataset: Dataset, cfg: TransformConfig) -> None:
    keys = {c.key for c in dataset.columns}
    unknown = [k for k in [*cfg.required_columns, *cfg.type_overrides] if k not in keys]
    if unknown:
        raise ValidationFailed("Unknown column(s) in pipeline configuration", {"columns": unknown})


def create_pipeline(session: Session, dataset_id: int, name: str, description: str | None, cfg: TransformConfig,
                    owner_id: str | None = None) -> Pipeline:
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise NotFound(f"Dataset {dataset_id} does not exist")
    if dataset.status != "ready":
        raise ValidationFailed("Pipelines can only be created for datasets that were ingested successfully.")
    validate_config(dataset, cfg)
    pipeline = Pipeline(dataset_id=dataset_id, name=name, description=description, config=cfg.model_dump(),
                        owner_id=owner_id)
    session.add(pipeline)
    session.commit()
    return pipeline


def update_pipeline(session: Session, pipeline_id: int, name: str, description: str | None, cfg: TransformConfig) -> Pipeline:
    pipeline = get_pipeline(session, pipeline_id)
    validate_config(pipeline.dataset, cfg)
    pipeline.name, pipeline.description, pipeline.config = name, description, cfg.model_dump()
    session.commit()
    return pipeline


def get_pipeline(session: Session, pipeline_id: int) -> Pipeline:
    pipeline = session.get(Pipeline, pipeline_id)
    if not pipeline:
        raise NotFound(f"Pipeline {pipeline_id} does not exist")
    return pipeline


def list_pipelines(session: Session, dataset_id: int | None = None, scope: Scope = SYSTEM_SCOPE) -> list[Pipeline]:
    stmt = (select(Pipeline).options(selectinload(Pipeline.dataset)).where(scope.visible(Pipeline.owner_id))
            .order_by(Pipeline.created_at.desc()))
    if dataset_id:
        stmt = stmt.where(Pipeline.dataset_id == dataset_id)
    return list(session.scalars(stmt))


def delete_pipeline(session: Session, pipeline_id: int) -> None:
    pipeline = get_pipeline(session, pipeline_id)
    if any(r.status in ("pending", "running") for r in pipeline.runs):
        raise Conflict("The pipeline has a run in progress.")
    for run in pipeline.runs:
        if run.output:
            tables.drop_table(get_engine(), run.output.table_name)
    session.delete(pipeline)
    session.commit()


# ---------------------------------------------------------------- runs

def queue_run(session: Session, pipeline_id: int) -> PipelineRun:
    pipeline = get_pipeline(session, pipeline_id)
    active = session.scalar(
        select(PipelineRun.id).where(PipelineRun.pipeline_id == pipeline_id,
                                     PipelineRun.status.in_(("pending", "running")))
    )
    if active:
        raise Conflict(f"Run {active} of this pipeline is still in progress.")
    run = PipelineRun(pipeline_id=pipeline.id, status="pending", config_snapshot=dict(pipeline.config))
    session.add(run)
    session.commit()
    return run


def get_run(session: Session, run_id: int) -> PipelineRun:
    run = session.get(PipelineRun, run_id, options=[selectinload(PipelineRun.logs), selectinload(PipelineRun.output)])
    if not run:
        raise NotFound(f"Run {run_id} does not exist")
    return run


def list_runs(session: Session, pipeline_id: int | None = None, limit: int = 50,
              scope: Scope = SYSTEM_SCOPE) -> list[PipelineRun]:
    stmt = (select(PipelineRun).join(Pipeline).where(scope.visible(Pipeline.owner_id))
            .options(selectinload(PipelineRun.pipeline), selectinload(PipelineRun.output))
            .order_by(PipelineRun.id.desc()).limit(limit))
    if pipeline_id:
        stmt = stmt.where(PipelineRun.pipeline_id == pipeline_id)
    return list(session.scalars(stmt))


def run_quality(session: Session, run_id: int) -> dict[str, QualityAssessment | None]:
    rows = session.scalars(select(QualityAssessment).where(QualityAssessment.run_id == run_id)).all()
    return {"before": next((a for a in rows if a.stage == "raw"), None),
            "after": next((a for a in rows if a.stage == "processed"), None)}


def recover_interrupted_runs() -> int:
    """Mark runs left pending/running by a previous process as failed (called at startup)."""
    with session_factory()() as session:
        result = session.execute(
            update(PipelineRun)
            .where(PipelineRun.status.in_(("pending", "running")))
            .values(status="failed", error_message="Interrupted: the server restarted during this run.",
                    finished_at=utcnow())
        )
        session.commit()
        return result.rowcount or 0


class _RunContext:
    def __init__(self, session: Session, run: PipelineRun) -> None:
        self.session = session
        self.run = run

    def log(self, stage: str, message: str, level: str = "info", **context: Any) -> None:
        self.session.add(PipelineRunLog(run_id=self.run.id, stage=stage, level=level, message=message,
                                        context=context or None))
        self.session.commit()

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        self.run.current_stage = name
        self.session.commit()
        self.log(name, f"Stage '{name}' started")
        start = time.perf_counter()
        try:
            yield
        except StageFailed:
            raise
        except ValidationFailed as exc:
            raise StageFailed(name, exc.message) from exc
        except Exception as exc:
            log.exception("pipeline stage failed", extra={"run_id": self.run.id, "stage": name})
            raise StageFailed(name, f"{type(exc).__name__}: {exc}") from exc
        elapsed = int((time.perf_counter() - start) * 1000)
        self.run.stage_timings_ms = {**(self.run.stage_timings_ms or {}), name: elapsed}
        self.session.commit()
        self.log(name, f"Stage '{name}' completed in {elapsed} ms", duration_ms=elapsed)


def execute_run(run_id: int) -> None:
    """Execute a queued run. Opens its own session; safe to call from a background task."""
    engine = get_engine()
    with session_factory()() as session:
        run = session.get(PipelineRun, run_id)
        if run is None or run.status != "pending":
            return
        pipeline = run.pipeline
        dataset = pipeline.dataset
        run.status, run.started_at = "running", utcnow()
        session.commit()
        ctx = _RunContext(session, run)
        output_table = processed_table_name(run.id)
        started = time.perf_counter()

        try:
            cfg = TransformConfig.model_validate(run.config_snapshot)

            with ctx.stage("extract"):
                if dataset.status != "ready" or not dataset.staging_table:
                    raise ValidationFailed("Source dataset is not ready.")
                if not tables.table_exists(engine, dataset.staging_table):
                    raise ValidationFailed(f"Staging table {dataset.staging_table} is missing.")
                frame = tables.read_frame(engine, dataset.staging_table)
                run.rows_extracted = len(frame)
                ctx.log("extract", f"Extracted {len(frame):,} rows × {frame.shape[1]} columns from {dataset.staging_table}")

            with ctx.stage("validate"):
                validate_config(dataset, cfg)
                if frame.empty:
                    raise ValidationFailed("The source contains no rows.")
                specs = column_specs(dataset)
                missing_cols = [s.key for s in specs if s.key not in frame.columns]
                if missing_cols:
                    raise ValidationFailed(f"Source is missing expected columns: {missing_cols}")
                before = save_result(session, dataset, assess(frame, specs), "raw", run)
                session.commit()
                ctx.log("validate", f"Source quality score {before.score} with {before.total_issues} issue(s) "
                        f"affecting {before.affected_rows:,} rows", score=before.score)
                for issue in before.issues[:8]:
                    if issue.severity in ("critical", "high"):
                        ctx.log("validate", issue.message, level="warning", check=issue.check_code)

            with ctx.stage("transform"):
                result = transform(frame, specs, cfg)
                for step in result.steps:
                    ctx.log("transform", step.message, rule=step.rule, rows=step.rows_affected,
                            cells=step.cells_changed, **({"details": step.details} if step.details else {}))
                run.rows_rejected = result.rows_rejected
                if result.frame.empty:
                    raise ValidationFailed("All rows were rejected by the transformation rules; nothing to load.")

            with ctx.stage("load"):
                tables.drop_table(engine, output_table)
                table = tables.define_table(output_table, [(c.key, c.type) for c in result.columns], typed=True)
                try:
                    with engine.begin() as conn:
                        loaded = tables.create_and_load(conn, table, result.frame)  # also creates indexes
                except Exception:
                    tables.drop_table(engine, output_table)
                    raise
                run.rows_loaded = loaded
                ctx.log("load", f"Loaded {loaded:,} rows into {output_table} (transaction committed)")

            with ctx.stage("profile"):
                after = save_result(session, dataset, assess(to_raw_strings(result.frame), result.columns), "processed", run)
                session.add(ProcessedDataset(
                    run_id=run.id, dataset_id=dataset.id, table_name=output_table, row_count=loaded,
                    column_count=len(result.columns),
                    columns=[{"key": c.key, "name": c.name, "type": c.type} for c in result.columns],
                ))
                session.commit()
                ctx.log("profile", f"Processed quality score {after.score} ({after.score - before.score:+.1f} vs source)",
                        score=after.score)

            run.status = "succeeded"
        except StageFailed as exc:
            session.rollback()
            run.status, run.error_stage, run.error_message = "failed", exc.stage, exc.message
            ctx.log(exc.stage, f"Run failed: {exc.message}", level="error")
            tables.drop_table(engine, output_table)
        finally:
            run.current_stage = None
            run.finished_at = utcnow()
            run.duration_ms = int((time.perf_counter() - started) * 1000)
            session.commit()
            log.info("pipeline run finished", extra={"run_id": run.id, "status": run.status,
                                                      "duration_ms": run.duration_ms})
