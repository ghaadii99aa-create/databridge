"""Pydantic request/response schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.cleaning import TransformConfig


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ColumnOut(ORM):
    id: int
    position: int
    name: str
    key: str
    inferred_type: str
    null_count: int
    distinct_count: int
    sample_values: list[Any]


class QualityBrief(ORM):
    id: int
    stage: str
    score: float
    total_issues: int
    affected_rows: int
    created_at: datetime


class DatasetOut(ORM):
    id: int
    name: str
    description: str | None
    original_filename: str
    file_format: str
    file_size_bytes: int
    sha256: str
    sheet_name: str | None
    encoding: str | None
    delimiter: str | None
    row_count: int
    column_count: int
    status: str
    error_message: str | None
    is_sample: bool
    ingest_duration_ms: int | None
    created_at: datetime
    updated_at: datetime
    latest_quality: QualityBrief | None = None
    pipeline_count: int = 0
    read_only: bool = False


class DatasetDetail(DatasetOut):
    columns: list[ColumnOut]


class DatasetUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class IssueOut(ORM):
    id: int
    check_code: str
    dimension: str
    severity: str
    column_key: str | None
    column_name: str | None
    affected_rows: int
    affected_ratio: float
    message: str
    recommendation: str
    examples: list[Any]


class AssessmentOut(ORM):
    id: int
    dataset_id: int
    run_id: int | None
    stage: Literal["raw", "processed"]
    score: float
    completeness: float
    uniqueness: float
    validity: float
    consistency: float
    row_count: int
    column_count: int
    total_issues: int
    affected_rows: int
    methodology_version: str
    details: dict[str, Any]
    created_at: datetime
    issues: list[IssueOut]


class PipelineIn(BaseModel):
    dataset_id: int
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    config: TransformConfig = Field(default_factory=TransformConfig)


class PipelineUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    config: TransformConfig


class RunBrief(ORM):
    id: int
    pipeline_id: int
    status: str
    current_stage: str | None
    rows_extracted: int | None
    rows_loaded: int | None
    rows_rejected: int | None
    error_stage: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None


class PipelineOut(ORM):
    id: int
    dataset_id: int
    dataset_name: str
    name: str
    description: str | None
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    last_run: RunBrief | None = None
    run_count: int = 0
    read_only: bool = False


class LogOut(ORM):
    id: int
    stage: str
    level: str
    message: str
    context: dict[str, Any] | None
    created_at: datetime


class OutputOut(ORM):
    table_name: str
    row_count: int
    column_count: int
    columns: list[dict[str, Any]]


class RunDetail(RunBrief):
    pipeline_name: str
    dataset_id: int
    dataset_name: str
    config_snapshot: dict[str, Any]
    stage_timings_ms: dict[str, int]
    logs: list[LogOut]
    output: OutputOut | None
    quality_before: AssessmentOut | None
    quality_after: AssessmentOut | None
    read_only: bool = False


class ReportIn(BaseModel):
    kind: Literal["dataset_summary", "quality", "pipeline_run"]
    format: Literal["pdf", "csv"] = "pdf"
    dataset_id: int | None = None
    run_id: int | None = None
    assessment_id: int | None = None


class ReportOut(ORM):
    id: int
    kind: str
    format: str
    title: str
    dataset_id: int | None
    run_id: int | None
    size_bytes: int
    created_at: datetime
    read_only: bool = False


class AskIn(BaseModel):
    source: str = Field(pattern=r"^(raw|processed)-\d+$")
    question: str = Field(min_length=3, max_length=500)


class ExplorerQuery(BaseModel):
    source: str
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
    search: str | None = Field(default=None, max_length=200)
    sort: str | None = None
    order: Literal["asc", "desc"] = "asc"
    filters: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
