from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Query, Response, status
from sqlalchemy import func, select

from app.api.deps import SessionDep
from app.core.config import get_settings
from app.core.errors import LimitExceeded
from app.core.visitor import Scope, ScopeDep
from app.models import Pipeline, PipelineRun
from app.schemas import AssessmentOut, PipelineIn, PipelineOut, PipelineUpdate, RunBrief, RunDetail
from app.services import access, etl
from app.services.cleaning import RULES, TransformConfig
from app.services.quality.service import get_assessment

router = APIRouter(tags=["pipelines"])


def _pipeline_out(p: Pipeline, scope: Scope) -> PipelineOut:
    runs = p.runs
    return PipelineOut(
        id=p.id, dataset_id=p.dataset_id, dataset_name=p.dataset.name, name=p.name, description=p.description,
        config=p.config, created_at=p.created_at, updated_at=p.updated_at,
        last_run=RunBrief.model_validate(runs[0]) if runs else None, run_count=len(runs),
        read_only=scope.read_only(p.owner_id),
    )


@router.get("/pipelines/rules")
def transformation_rules() -> dict:
    return {"rules": RULES, "defaults": TransformConfig().model_dump(),
            "stages": [{"key": s, "label": s.capitalize()} for s in etl.STAGES]}


@router.get("/pipelines", response_model=list[PipelineOut])
def list_pipelines(session: SessionDep, scope: ScopeDep, dataset_id: int | None = None):
    return [_pipeline_out(p, scope) for p in etl.list_pipelines(session, dataset_id, scope)]


@router.post("/pipelines", response_model=PipelineOut, status_code=status.HTTP_201_CREATED)
def create_pipeline(body: PipelineIn, session: SessionDep, scope: ScopeDep):
    access.dataset(session, scope, body.dataset_id)  # visitors may build pipelines on shared sample data
    if scope.demo:
        owned = session.scalar(select(func.count(Pipeline.id)).where(Pipeline.owner_id == scope.visitor_id)) or 0
        limit = get_settings().demo_max_pipelines_per_visitor
        if owned >= limit:
            raise LimitExceeded(f"The public demo keeps up to {limit} pipelines per visitor. "
                                "Delete one of yours to create another.", {"limit": limit})
    p = etl.create_pipeline(session, body.dataset_id, body.name.strip(), body.description, body.config,
                            owner_id=scope.owner_for_new)
    return _pipeline_out(p, scope)


@router.get("/pipelines/{pipeline_id}", response_model=PipelineOut)
def get_pipeline(pipeline_id: int, session: SessionDep, scope: ScopeDep):
    return _pipeline_out(access.pipeline(session, scope, pipeline_id), scope)


@router.put("/pipelines/{pipeline_id}", response_model=PipelineOut)
def update_pipeline(pipeline_id: int, body: PipelineUpdate, session: SessionDep, scope: ScopeDep):
    access.pipeline(session, scope, pipeline_id, modify=True)
    return _pipeline_out(etl.update_pipeline(session, pipeline_id, body.name.strip(), body.description, body.config), scope)


@router.delete("/pipelines/{pipeline_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, response_model=None)
def delete_pipeline(pipeline_id: int, session: SessionDep, scope: ScopeDep) -> None:
    access.pipeline(session, scope, pipeline_id, modify=True)
    etl.delete_pipeline(session, pipeline_id)


@router.post("/pipelines/{pipeline_id}/runs", response_model=RunBrief, status_code=status.HTTP_202_ACCEPTED)
def start_run(pipeline_id: int, session: SessionDep, scope: ScopeDep, background: BackgroundTasks):
    """Queue a run and execute it in the background. Poll GET /runs/{id} for progress."""
    access.pipeline(session, scope, pipeline_id, modify=True)
    run = etl.queue_run(session, pipeline_id)
    background.add_task(etl.execute_run, run.id)
    return run


@router.get("/runs", response_model=list[RunBrief])
def list_runs(session: SessionDep, scope: ScopeDep, pipeline_id: int | None = None, limit: int = Query(50, ge=1, le=200)):
    return etl.list_runs(session, pipeline_id, limit, scope)


def _assessment(session: SessionDep, a) -> AssessmentOut | None:
    return AssessmentOut.model_validate(get_assessment(session, a.id)) if a else None


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: int, session: SessionDep, scope: ScopeDep):
    access.run(session, scope, run_id)
    run: PipelineRun = etl.get_run(session, run_id)
    q = etl.run_quality(session, run_id)
    base = RunBrief.model_validate(run).model_dump()
    return RunDetail(
        **base, pipeline_name=run.pipeline.name, dataset_id=run.pipeline.dataset_id,
        dataset_name=run.pipeline.dataset.name, config_snapshot=run.config_snapshot,
        stage_timings_ms=run.stage_timings_ms or {}, logs=run.logs, output=run.output,
        quality_before=_assessment(session, q["before"]), quality_after=_assessment(session, q["after"]),
        read_only=scope.read_only(run.pipeline.owner_id),
    )
