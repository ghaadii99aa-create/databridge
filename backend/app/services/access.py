"""Visibility and permission checks for routes (see app/core/visitor.py).

Every lookup by ID goes through these helpers, so a visitor can never reach another
visitor's datasets, pipelines, runs, outputs or reports by guessing IDs: those are reported
as not found. Shared system data is visible but read-only.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.core.visitor import Scope
from app.models import Dataset, Pipeline, PipelineRun, QualityAssessment, Report


def dataset(session: Session, scope: Scope, dataset_id: int, modify: bool = False) -> Dataset:
    ds = session.get(Dataset, dataset_id)
    if not ds:
        raise NotFound(f"Dataset {dataset_id} does not exist")
    (scope.ensure_modifiable if modify else scope.ensure_visible)(ds.owner_id, f"Dataset {dataset_id}")
    return ds


def pipeline(session: Session, scope: Scope, pipeline_id: int, modify: bool = False) -> Pipeline:
    p = session.get(Pipeline, pipeline_id)
    if not p:
        raise NotFound(f"Pipeline {pipeline_id} does not exist")
    (scope.ensure_modifiable if modify else scope.ensure_visible)(p.owner_id, f"Pipeline {pipeline_id}")
    return p


def run(session: Session, scope: Scope, run_id: int) -> PipelineRun:
    r = session.get(PipelineRun, run_id)
    if not r:
        raise NotFound(f"Run {run_id} does not exist")
    scope.ensure_visible(r.pipeline.owner_id, f"Run {run_id}")
    return r


def report(session: Session, scope: Scope, report_id: int, modify: bool = False) -> Report:
    rep = session.get(Report, report_id)
    if not rep:
        raise NotFound(f"Report {report_id} does not exist")
    (scope.ensure_modifiable if modify else scope.ensure_visible)(rep.owner_id, f"Report {report_id}")
    return rep


def assessment(session: Session, scope: Scope, assessment_id: int) -> QualityAssessment:
    a = session.get(QualityAssessment, assessment_id)
    if not a:
        raise NotFound(f"Assessment {assessment_id} does not exist")
    dataset(session, scope, a.dataset_id)
    if a.run_id is not None:
        run(session, scope, a.run_id)
    return a


_SOURCE = re.compile(r"^(raw|processed)-(\d+)$")


def source(session: Session, scope: Scope, source_id: str) -> None:
    m = _SOURCE.match(source_id or "")
    if not m:
        raise ValidationFailed("source must look like 'raw-<dataset_id>' or 'processed-<run_id>'")
    if m.group(1) == "raw":
        dataset(session, scope, int(m.group(2)))
    else:
        run(session, scope, int(m.group(2)))
