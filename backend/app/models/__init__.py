"""SQLAlchemy ORM models — the metadata schema.

Row data itself lives in generated tables (stg_<dataset_id>, prc_<run_id>); these models
describe datasets, quality results, pipelines, runs and reports.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Timestamps are stored in UTC and always returned timezone-aware.

    PostgreSQL keeps the offset; SQLite drops it and returns naive values, which the API would
    then serialise without a zone and browsers would read as local time (off by the UTC offset).
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc) if value is not None else None

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


TS = UTCDateTime()

DATASET_STATUSES = ("processing", "ready", "failed")
RUN_STATUSES = ("pending", "running", "succeeded", "failed")
SEVERITIES = ("critical", "high", "medium", "low", "info")


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        CheckConstraint(f"status IN {DATASET_STATUSES}", name="ck_datasets_status"),
        CheckConstraint("file_format IN ('csv', 'xlsx')", name="ck_datasets_format"),
        Index("ix_datasets_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(255), unique=True)
    file_format: Mapped[str] = mapped_column(String(10))
    file_size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    sheet_name: Mapped[str | None] = mapped_column(String(100))
    encoding: Mapped[str | None] = mapped_column(String(20))
    delimiter: Mapped[str | None] = mapped_column(String(5))
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    column_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="processing")
    error_message: Mapped[str | None] = mapped_column(Text)
    staging_table: Mapped[str | None] = mapped_column(String(63))
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    # Demo mode: NULL = shared system data (read-only); otherwise the anonymous visitor who created it.
    owner_id: Mapped[str | None] = mapped_column(String(32), index=True)
    ingest_duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)

    columns: Mapped[list[DatasetColumn]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", order_by="DatasetColumn.position"
    )
    assessments: Mapped[list[QualityAssessment]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )
    pipelines: Mapped[list[Pipeline]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )


class DatasetColumn(Base):
    __tablename__ = "dataset_columns"
    __table_args__ = (
        UniqueConstraint("dataset_id", "position", name="uq_dataset_columns_position"),
        UniqueConstraint("dataset_id", "key", name="uq_dataset_columns_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255))
    key: Mapped[str] = mapped_column(String(63))
    inferred_type: Mapped[str] = mapped_column(String(20))
    null_count: Mapped[int] = mapped_column(Integer, default=0)
    distinct_count: Mapped[int] = mapped_column(Integer, default=0)
    sample_values: Mapped[list[Any]] = mapped_column(JSON, default=list)

    dataset: Mapped[Dataset] = relationship(back_populates="columns")


class Pipeline(Base):
    __tablename__ = "pipelines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Demo mode: NULL = shared system data (read-only); otherwise the anonymous visitor who created it.
    owner_id: Mapped[str | None] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)

    dataset: Mapped[Dataset] = relationship(back_populates="pipelines")
    runs: Mapped[list[PipelineRun]] = relationship(
        back_populates="pipeline", cascade="all, delete-orphan", order_by="PipelineRun.id.desc()"
    )


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = (
        CheckConstraint(f"status IN {RUN_STATUSES}", name="ck_pipeline_runs_status"),
        Index("ix_pipeline_runs_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipelines.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    current_stage: Mapped[str | None] = mapped_column(String(30))
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rows_extracted: Mapped[int | None] = mapped_column(Integer)
    rows_loaded: Mapped[int | None] = mapped_column(Integer)
    rows_rejected: Mapped[int | None] = mapped_column(Integer)
    error_stage: Mapped[str | None] = mapped_column(String(30))
    error_message: Mapped[str | None] = mapped_column(Text)
    stage_timings_ms: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(TS)
    finished_at: Mapped[datetime | None] = mapped_column(TS)
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    pipeline: Mapped[Pipeline] = relationship(back_populates="runs")
    logs: Mapped[list[PipelineRunLog]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="PipelineRunLog.id"
    )
    output: Mapped[ProcessedDataset | None] = relationship(
        back_populates="run", cascade="all, delete-orphan", uselist=False
    )


class PipelineRunLog(Base):
    __tablename__ = "pipeline_run_logs"
    __table_args__ = (
        CheckConstraint("level IN ('debug', 'info', 'warning', 'error')", name="ck_run_logs_level"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(30))
    level: Mapped[str] = mapped_column(String(10), default="info")
    message: Mapped[str] = mapped_column(Text)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    run: Mapped[PipelineRun] = relationship(back_populates="logs")


class ProcessedDataset(Base):
    __tablename__ = "processed_datasets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"), unique=True
    )
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    table_name: Mapped[str] = mapped_column(String(63), unique=True)
    row_count: Mapped[int] = mapped_column(Integer)
    column_count: Mapped[int] = mapped_column(Integer)
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    run: Mapped[PipelineRun] = relationship(back_populates="output")


class QualityAssessment(Base):
    __tablename__ = "quality_assessments"
    __table_args__ = (
        CheckConstraint("stage IN ('raw', 'processed')", name="ck_quality_stage"),
        CheckConstraint("score >= 0 AND score <= 100", name="ck_quality_score_range"),
        Index("ix_quality_dataset_created", "dataset_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(10))
    score: Mapped[float] = mapped_column(Float)
    completeness: Mapped[float] = mapped_column(Float)
    uniqueness: Mapped[float] = mapped_column(Float)
    validity: Mapped[float] = mapped_column(Float)
    consistency: Mapped[float] = mapped_column(Float)
    row_count: Mapped[int] = mapped_column(Integer)
    column_count: Mapped[int] = mapped_column(Integer)
    total_issues: Mapped[int] = mapped_column(Integer)
    affected_rows: Mapped[int] = mapped_column(Integer)
    methodology_version: Mapped[str] = mapped_column(String(10))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    dataset: Mapped[Dataset] = relationship(back_populates="assessments")
    issues: Mapped[list[QualityIssue]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan", order_by="QualityIssue.id"
    )


class QualityIssue(Base):
    __tablename__ = "quality_issues"
    __table_args__ = (
        CheckConstraint(f"severity IN {SEVERITIES}", name="ck_quality_issue_severity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("quality_assessments.id", ondelete="CASCADE"), index=True
    )
    check_code: Mapped[str] = mapped_column(String(40))
    dimension: Mapped[str] = mapped_column(String(20))
    severity: Mapped[str] = mapped_column(String(10))
    column_key: Mapped[str | None] = mapped_column(String(63))
    column_name: Mapped[str | None] = mapped_column(String(255))
    affected_rows: Mapped[int] = mapped_column(Integer)
    affected_ratio: Mapped[float] = mapped_column(Float)
    message: Mapped[str] = mapped_column(Text)
    recommendation: Mapped[str] = mapped_column(Text)
    examples: Mapped[list[Any]] = mapped_column(JSON, default=list)

    assessment: Mapped[QualityAssessment] = relationship(back_populates="issues")


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('dataset_summary', 'quality', 'pipeline_run')", name="ck_reports_kind"
        ),
        CheckConstraint("format IN ('pdf', 'csv')", name="ck_reports_format"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))
    format: Mapped[str] = mapped_column(String(5))
    title: Mapped[str] = mapped_column(String(255))
    dataset_id: Mapped[int | None] = mapped_column(
        ForeignKey("datasets.id", ondelete="SET NULL"), index=True
    )
    run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="SET NULL"))
    stored_filename: Mapped[str] = mapped_column(String(255), unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    # Demo mode: NULL = shared system data (read-only); otherwise the anonymous visitor who created it.
    owner_id: Mapped[str | None] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)
