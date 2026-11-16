"""Data Explorer: SQL-backed pagination, filtering, sorting, statistics and export.

A "source" is either the raw staging table of a dataset (`raw-<dataset_id>`) or the output
table of a pipeline run (`processed-<run_id>`). Every column key coming from the client is
checked against the source's own metadata before it reaches a query, and all values are
bound parameters.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterator, Literal

import pandas as pd
from pydantic import BaseModel
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.db import get_engine
from app.core.visitor import SYSTEM_SCOPE, Scope
from app.models import Dataset, Pipeline, PipelineRun, ProcessedDataset
from app.services import tables
from app.services import typing as T

FilterOp = Literal["eq", "neq", "contains", "gt", "gte", "lt", "lte", "is_null", "not_null"]
TEXT_OPS = {"eq", "neq", "contains", "is_null", "not_null"}
MAX_PAGE_SIZE = 200


class Filter(BaseModel):
    column: str
    op: FilterOp
    value: str | None = None


@dataclass
class SourceColumn:
    key: str
    name: str
    type: str


@dataclass
class Source:
    id: str
    kind: Literal["raw", "processed"]
    table: str
    label: str
    dataset_id: int
    dataset_name: str
    run_id: int | None
    row_count: int
    columns: list[SourceColumn]

    @property
    def typed(self) -> bool:
        return self.kind == "processed"

    def column(self, key: str) -> SourceColumn:
        for c in self.columns:
            if c.key == key:
                return c
        raise ValidationFailed(f"Unknown column '{key}' for this source")


_SOURCE_RE = re.compile(r"^(raw|processed)-(\d+)$")


def resolve_source(session: Session, source_id: str) -> Source:
    m = _SOURCE_RE.match(source_id or "")
    if not m:
        raise ValidationFailed("source must look like 'raw-<dataset_id>' or 'processed-<run_id>'")
    kind, ident = m.group(1), int(m.group(2))
    if kind == "raw":
        ds = session.get(Dataset, ident)
        if not ds or ds.status != "ready" or not ds.staging_table:
            raise NotFound(f"Raw data for dataset {ident} is not available")
        return Source(source_id, "raw", ds.staging_table, f"{ds.name} (raw)", ds.id, ds.name, None, ds.row_count,
                      [SourceColumn(c.key, c.name, c.inferred_type) for c in ds.columns])
    out = session.scalar(select(ProcessedDataset).where(ProcessedDataset.run_id == ident))
    if not out:
        raise NotFound(f"Run {ident} has no processed output")
    ds = session.get(Dataset, out.dataset_id)
    return Source(source_id, "processed", out.table_name, f"{ds.name} (run #{ident})", ds.id, ds.name, ident,
                  out.row_count, [SourceColumn(**c) for c in out.columns])


def list_sources(session: Session, scope: Scope = SYSTEM_SCOPE) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    datasets = session.scalars(
        select(Dataset).where(Dataset.status == "ready", scope.visible(Dataset.owner_id))
        .order_by(Dataset.is_sample.desc(), Dataset.created_at.desc())).all()
    outputs = session.execute(
        select(ProcessedDataset, PipelineRun.pipeline_id).join(PipelineRun, PipelineRun.id == ProcessedDataset.run_id)
        .join(Pipeline, Pipeline.id == PipelineRun.pipeline_id).where(scope.visible(Pipeline.owner_id))
        .order_by(ProcessedDataset.id.desc())
    ).all()
    by_dataset: dict[int, list[Any]] = {}
    for out, pipeline_id in outputs:
        by_dataset.setdefault(out.dataset_id, []).append((out, pipeline_id))
    for ds in datasets:
        result.append({"id": f"raw-{ds.id}", "kind": "raw", "dataset_id": ds.id, "dataset_name": ds.name,
                       "label": "Raw (as uploaded)", "row_count": ds.row_count, "column_count": ds.column_count,
                       "run_id": None, "created_at": ds.created_at, "is_sample": ds.is_sample})
        for out, pipeline_id in by_dataset.get(ds.id, []):
            result.append({"id": f"processed-{out.run_id}", "kind": "processed", "dataset_id": ds.id,
                           "dataset_name": ds.name, "label": f"Processed (run #{out.run_id})",
                           "row_count": out.row_count, "column_count": out.column_count, "run_id": out.run_id,
                           "pipeline_id": pipeline_id, "created_at": out.created_at, "is_sample": ds.is_sample})
    return result


def _coerce(value: str | None, col: SourceColumn, typed: bool) -> Any:
    if value is None:
        raise ValidationFailed(f"A value is required to filter '{col.name}'")
    if not typed or col.type not in T.TYPED_TYPES:
        return value
    if col.type in T.NUMERIC_TYPES:
        n = T.parse_numeric(pd.Series([value])).iloc[0]
        if pd.isna(n):
            raise ValidationFailed(f"'{value}' is not a number")
        return float(n)
    if col.type == "datetime":
        d = T.parse_datetime(pd.Series([value])).iloc[0]
        if pd.isna(d):
            raise ValidationFailed(f"'{value}' is not a date")
        return d.to_pydatetime()
    if col.type == "boolean":
        b = T.parse_boolean(pd.Series([value])).iloc[0]
        if pd.isna(b):
            raise ValidationFailed(f"'{value}' is not true/false")
        return bool(b)
    return value


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _build_where(table: Any, source: Source, search: str | None, filters: list[Filter]) -> list[Any]:
    clauses = []
    if search and search.strip():
        pattern = f"%{_escape_like(search.strip())}%"
        text_cols = [c for c in source.columns if not source.typed or c.type not in T.TYPED_TYPES]
        if text_cols:
            clauses.append(or_(*[table.c[c.key].ilike(pattern, escape="\\") for c in text_cols]))
    for f in filters:
        col = source.column(f.column)
        sql_col = table.c[col.key]
        is_text = not source.typed or col.type not in T.TYPED_TYPES
        if is_text and f.op not in TEXT_OPS:
            raise ValidationFailed(f"Operator '{f.op}' needs a typed column; '{col.name}' is text"
                                   + (" in raw data — use a processed source for numeric comparisons" if not source.typed else ""))
        if f.op == "is_null":
            clauses.append(sql_col.is_(None) if source.typed else (sql_col.is_(None) | (func.trim(sql_col) == "")))
            continue
        if f.op == "not_null":
            clauses.append(sql_col.is_not(None) if source.typed else (sql_col.is_not(None) & (func.trim(sql_col) != "")))
            continue
        if f.op == "contains":
            target = sql_col if is_text else cast(sql_col, String)
            clauses.append(target.ilike(f"%{_escape_like(f.value or '')}%", escape="\\"))
            continue
        value = _coerce(f.value, col, source.typed)
        if is_text and f.op in ("eq", "neq"):
            expr = func.lower(func.trim(sql_col)) == str(value).strip().lower()
            clauses.append(expr if f.op == "eq" else ~expr)
            continue
        ops = {"eq": sql_col.__eq__, "neq": sql_col.__ne__, "gt": sql_col.__gt__, "gte": sql_col.__ge__,
               "lt": sql_col.__lt__, "lte": sql_col.__le__}
        clauses.append(ops[f.op](value))
    return clauses


def query_rows(
    session: Session, source_id: str, page: int = 1, page_size: int = 50, search: str | None = None,
    filters: list[Filter] | None = None, sort: str | None = None, order: Literal["asc", "desc"] = "asc",
) -> dict[str, Any]:
    source = resolve_source(session, source_id)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    page = max(1, page)
    engine = get_engine()
    table = tables.reflect(engine, source.table)
    where = _build_where(table, source, search, filters or [])

    count_stmt = select(func.count()).select_from(table)
    stmt = select(*[table.c[c.key] for c in source.columns], table.c[tables.ROW_ID])
    for clause in where:
        count_stmt = count_stmt.where(clause)
        stmt = stmt.where(clause)
    sort_col = table.c[source.column(sort).key] if sort else table.c[tables.ROW_ID]
    # explicit NULLS LAST: PostgreSQL and SQLite disagree on where NULLs sort by default
    stmt = stmt.order_by((sort_col.desc() if order == "desc" else sort_col.asc()).nulls_last(), table.c[tables.ROW_ID])
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    with engine.connect() as conn:
        total = conn.scalar(count_stmt) or 0
        rows = [
            {k: tables.jsonable(v) for k, v in row._mapping.items()}
            for row in conn.execute(stmt)
        ]
    return {
        "source": source_meta(source),
        "rows": rows,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": max(1, -(-total // page_size)),
    }


def source_meta(source: Source) -> dict[str, Any]:
    return {"id": source.id, "kind": source.kind, "label": source.label, "dataset_id": source.dataset_id,
            "dataset_name": source.dataset_name, "run_id": source.run_id, "row_count": source.row_count,
            "columns": [c.__dict__ for c in source.columns]}


def typed_frame(source: Source, keys: list[str] | None = None) -> pd.DataFrame:
    """Load selected columns; for raw sources, parse values into their inferred types."""
    keys = keys or [c.key for c in source.columns]
    frame = tables.read_frame(get_engine(), source.table, keys)
    if source.typed:
        for c in source.columns:
            if c.key in frame and c.type in T.NUMERIC_TYPES:
                frame[c.key] = pd.to_numeric(frame[c.key], errors="coerce")
            elif c.key in frame and c.type == "datetime":
                frame[c.key] = pd.to_datetime(frame[c.key], errors="coerce")
        return frame
    for c in source.columns:
        if c.key not in frame:
            continue
        s = frame[c.key].where(~T.missing_mask(frame[c.key]))
        if c.type in T.NUMERIC_TYPES:
            frame[c.key] = T.parse_numeric(s)
        elif c.type == "datetime":
            frame[c.key] = T.parse_datetime(s)
        else:
            frame[c.key] = s.astype("string").str.strip()
    return frame


@lru_cache(maxsize=64)
def _cached_stats(source_id: str, table: str, columns: tuple[tuple[str, str, str], ...], typed: bool) -> list[dict[str, Any]]:
    # Row tables are immutable once written, so statistics can be cached per table.
    src = Source(source_id, "processed" if typed else "raw", table, "", 0, "", None, 0,
                 [SourceColumn(*c) for c in columns])
    frame = typed_frame(src)
    n = len(frame)
    stats = []
    for c in src.columns:
        s = frame[c.key]
        present = s.dropna()
        item: dict[str, Any] = {"key": c.key, "name": c.name, "type": c.type, "count": int(len(present)),
                                "missing": int(n - len(present)),
                                "missing_ratio": round((n - len(present)) / n, 4) if n else 0,
                                "distinct": int(present.nunique())}
        if c.type in T.NUMERIC_TYPES and len(present):
            v = present.astype("float64")
            item.update({"mean": float(v.mean()), "std": float(v.std()) if len(v) > 1 else 0.0,
                         "min": float(v.min()), "p25": float(v.quantile(0.25)), "median": float(v.median()),
                         "p75": float(v.quantile(0.75)), "max": float(v.max()), "sum": float(v.sum())})
        elif c.type == "datetime" and len(present):
            item.update({"min": present.min().isoformat(), "max": present.max().isoformat(),
                         "span_days": int((present.max() - present.min()).days)})
        else:
            top = present.astype(str).value_counts().head(8)
            item["top_values"] = [{"value": k, "count": int(v)} for k, v in top.items()]
        stats.append(item)
    return stats


def column_stats(session: Session, source_id: str) -> dict[str, Any]:
    source = resolve_source(session, source_id)
    cols = tuple((c.key, c.name, c.type) for c in source.columns)
    return {"source": source_meta(source),
            "columns": _cached_stats(source.id, source.table, cols, source.typed)}


_FORMULA_PREFIX = ("=", "+", "-", "@", "\t", "\r")


def _safe_cell(value: Any) -> Any:
    """Neutralise spreadsheet formula injection in exported CSV text cells."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIX):
        try:
            float(value)
            return value  # plain negative numbers are fine
        except ValueError:
            return "'" + value
    return value


def export_csv(session: Session, source_id: str) -> tuple[str, Iterator[str]]:
    source = resolve_source(session, source_id)
    engine = get_engine()
    table = tables.reflect(engine, source.table)

    def generate() -> Iterator[str]:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([c.name for c in source.columns])
        yield "﻿" + buf.getvalue()  # BOM so Excel on Windows reads UTF-8 correctly
        stmt = select(*[table.c[c.key] for c in source.columns]).order_by(table.c[tables.ROW_ID])
        with engine.connect() as conn:
            result = conn.execution_options(stream_results=True, yield_per=2000).execute(stmt)
            for chunk in result.partitions(2000):
                buf.seek(0)
                buf.truncate()
                for row in chunk:
                    writer.writerow([_safe_cell(tables.jsonable(v)) for v in row])
                yield buf.getvalue()

    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", source.dataset_name).strip("_") or "dataset"
    suffix = "raw" if source.kind == "raw" else f"run{source.run_id}"
    return f"{safe_name}_{suffix}.csv", generate()


def compare_run(session: Session, run_id: int) -> dict[str, Any]:
    run = session.get(PipelineRun, run_id)
    if not run or not run.output:
        raise NotFound(f"Run {run_id} has no processed output to compare")
    raw = column_stats(session, f"raw-{run.output.dataset_id}")
    processed = column_stats(session, f"processed-{run_id}")
    by_key = {c["key"]: c for c in processed["columns"]}
    columns = []
    for c in raw["columns"]:
        p = by_key.get(c["key"])
        columns.append({
            "key": c["key"], "name": c["name"], "raw_type": c["type"], "processed_type": p["type"] if p else None,
            "raw_missing": c["missing"], "processed_missing": p["missing"] if p else None,
            "raw_distinct": c["distinct"], "processed_distinct": p["distinct"] if p else None,
            "dropped": p is None,
        })
    return {"run_id": run_id, "raw_rows": raw["source"]["row_count"], "processed_rows": run.output.row_count,
            "columns": columns}

