"""Transformation rules applied by the ETL transform stage.

Each rule is a small function that returns a new DataFrame plus a record of what it changed,
so every run has an auditable list of effects in its logs. The order is fixed and documented
because results depend on it (e.g. de-duplication runs after normalisation so near-duplicates
that differ only in spacing or case are caught).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from app.services import typing as T
from app.services.quality.engine import ColumnSpec


class TransformConfig(BaseModel):
    """Pipeline transformation settings. Stored as JSON on the pipeline."""

    drop_empty_columns: bool = True
    trim_whitespace: bool = True
    normalize_categories: bool = True
    remove_duplicates: bool = True
    coerce_types: bool = True
    reject_negative_values: bool = True
    missing_values: Literal["keep", "drop_rows", "fill"] = "fill"
    numeric_fill: Literal["none", "median", "zero"] = "none"
    required_columns: list[str] = Field(default_factory=list, max_length=200)
    type_overrides: dict[str, Literal["integer", "decimal", "boolean", "datetime", "category", "text", "identifier"]] = Field(default_factory=dict)


RULES: list[dict[str, str]] = [
    {"key": "drop_empty_columns", "label": "Drop empty columns",
     "description": "Remove columns where every value is missing."},
    {"key": "trim_whitespace", "label": "Trim whitespace",
     "description": "Remove leading and trailing spaces from text values; null tokens become empty."},
    {"key": "normalize_categories", "label": "Normalise categories",
     "description": "Rewrite category variants (case, spacing, punctuation) to the most frequent spelling."},
    {"key": "remove_duplicates", "label": "Remove duplicate records",
     "description": "Keep the first of each group of identical rows (compared after normalisation)."},
    {"key": "coerce_types", "label": "Convert data types",
     "description": "Parse numbers, dates and booleans. Values that cannot be parsed become empty and are counted."},
    {"key": "reject_negative_values", "label": "Reject negative quantities",
     "description": "Move rows with negative values in quantity/price/amount-type columns to the rejected count."},
    {"key": "required_columns", "label": "Required columns",
     "description": "Reject rows missing a value in any selected column."},
    {"key": "missing_values", "label": "Missing value strategy",
     "description": "keep: leave empty · drop_rows: remove rows with any missing value · fill: write 'Unknown' into category and text columns. Dates and identifiers are never filled."},
    {"key": "numeric_fill", "label": "Numeric fill",
     "description": "none (default): leave missing numbers empty so totals are not distorted · median · zero. Applies when the missing value strategy is 'fill'."},
]


@dataclass
class StepResult:
    rule: str
    message: str
    rows_affected: int = 0
    cells_changed: int = 0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class TransformResult:
    frame: pd.DataFrame  # typed when coerce_types is on
    columns: list[ColumnSpec]
    rows_in: int
    rows_rejected: int
    steps: list[StepResult]


def _changed(before: pd.Series, after: pd.Series) -> int:
    b = before.astype("string").fillna("\x00")
    a = after.astype("string").fillna("\x00")
    return int((b != a).sum())


def transform(df: pd.DataFrame, columns: list[ColumnSpec], cfg: TransformConfig) -> TransformResult:
    df = df.reset_index(drop=True).astype("string")
    cols = [ColumnSpec(c.key, c.name, cfg.type_overrides.get(c.key, c.type)) for c in columns]
    rows_in = len(df)
    steps: list[StepResult] = []
    rejected = 0

    # null tokens -> real missing values, always (this is what "missing" means everywhere)
    for c in cols:
        df.loc[T.missing_mask(df[c.key]).to_numpy(), c.key] = pd.NA

    if cfg.drop_empty_columns:
        empty = [c for c in cols if df[c.key].isna().all()]
        if empty:
            df = df.drop(columns=[c.key for c in empty])
            cols = [c for c in cols if c not in empty]
        steps.append(StepResult("drop_empty_columns", f"Dropped {len(empty)} empty column(s)",
                                details={"columns": [c.name for c in empty]}))

    if cfg.trim_whitespace:
        changed = 0
        for c in cols:
            before = df[c.key]
            after = before.str.strip()
            changed += _changed(before, after)
            df[c.key] = after
        steps.append(StepResult("trim_whitespace", f"Trimmed {changed:,} value(s)", cells_changed=changed))

    if cfg.normalize_categories:
        changed = 0
        mapping_report: dict[str, dict[str, str]] = {}
        for c in cols:
            if c.type != "category":
                continue
            s = df[c.key]
            norm = T.normalize_token(s)
            frame = pd.DataFrame({"raw": s.str.strip(), "norm": norm}).dropna()
            if frame.empty:
                continue
            canonical = frame.groupby("norm")["raw"].agg(lambda x: x.value_counts().index[0])
            new = norm.map(canonical).where(s.notna(), pd.NA).astype("string")
            col_changed = _changed(s, new)
            if col_changed:
                variants = frame[frame["raw"] != frame["norm"].map(canonical)]
                mapping_report[c.name] = {
                    str(v): str(canonical[n]) for v, n in variants.drop_duplicates("raw").head(20).itertuples(index=False)
                }
            changed += col_changed
            df[c.key] = new
        steps.append(StepResult("normalize_categories", f"Normalised {changed:,} category value(s)",
                                cells_changed=changed, details={"mappings": mapping_report}))

    if cfg.remove_duplicates and len(df):
        keys = [c.key for c in cols]
        normalized = df[keys].apply(lambda s: s.str.strip().str.lower()).fillna("\x00")
        dup = normalized.duplicated(keep="first").to_numpy(dtype=bool)
        df = df[~dup].reset_index(drop=True)
        steps.append(StepResult("remove_duplicates", f"Removed {int(dup.sum()):,} duplicate row(s)",
                                rows_affected=int(dup.sum())))

    typed = df.copy()
    if cfg.coerce_types:
        typed = pd.DataFrame(index=df.index)
        failures: dict[str, int] = {}
        for c in cols:
            s = df[c.key]
            if c.type == "integer":
                n = T.parse_numeric(s)
                n = n.where(np.floor(n) == n)
                typed[c.key] = n.round().astype("Int64")
            elif c.type == "decimal":
                typed[c.key] = T.parse_numeric(s)
            elif c.type == "datetime":
                typed[c.key] = T.parse_datetime(s)
            elif c.type == "boolean":
                typed[c.key] = T.parse_boolean(s)
            else:
                typed[c.key] = s
            lost = int((s.notna() & typed[c.key].isna()).sum())
            if lost:
                failures[c.name] = lost
        total = sum(failures.values())
        steps.append(StepResult("coerce_types", f"Converted column types; {total:,} unparseable value(s) set to empty",
                                cells_changed=total, details={"unparseable": failures}))

    reject_mask = np.zeros(len(typed), dtype=bool)
    if cfg.reject_negative_values:
        negatives: dict[str, int] = {}
        for c in cols:
            if c.type in T.NUMERIC_TYPES and T.expects_non_negative(c.name):
                nums = T.parse_numeric(typed[c.key]) if not cfg.coerce_types else typed[c.key].astype("float64")
                neg = (nums < 0).fillna(False).to_numpy(dtype=bool)
                if neg.any():
                    negatives[c.name] = int(neg.sum())
                reject_mask |= neg
        steps.append(StepResult("reject_negative_values",
                                f"Rejected {int(reject_mask.sum()):,} row(s) with negative quantities",
                                rows_affected=int(reject_mask.sum()), details={"columns": negatives}))

    required = [c for c in cols if c.key in set(cfg.required_columns)]
    if required:
        req_mask = typed[[c.key for c in required]].isna().any(axis=1).to_numpy(dtype=bool) & ~reject_mask
        reject_mask |= req_mask
        steps.append(StepResult("required_columns",
                                f"Rejected {int(req_mask.sum()):,} row(s) missing a required value",
                                rows_affected=int(req_mask.sum()),
                                details={"columns": [c.name for c in required]}))

    rejected += int(reject_mask.sum())
    typed = typed[~reject_mask].reset_index(drop=True)

    if cfg.missing_values == "drop_rows":
        drop = typed.isna().any(axis=1).to_numpy(dtype=bool)
        typed = typed[~drop].reset_index(drop=True)
        rejected += int(drop.sum())
        steps.append(StepResult("missing_values", f"Dropped {int(drop.sum()):,} row(s) with missing values",
                                rows_affected=int(drop.sum())))
    elif cfg.missing_values == "fill":
        filled: dict[str, Any] = {}
        for c in cols:
            s = typed[c.key]
            n = int(s.isna().sum())
            if not n:
                continue
            if c.type in T.NUMERIC_TYPES and cfg.numeric_fill != "none" and s.notna().any():
                base = s.astype("float64").median() if cfg.numeric_fill == "median" else 0.0
                value = int(round(base)) if c.type == "integer" else round(float(base), 4)
                typed[c.key] = s.fillna(value)
                filled[c.name] = {"count": n, "value": value}
            elif c.type in ("category", "text"):
                typed[c.key] = s.fillna("Unknown")
                filled[c.name] = {"count": n, "value": "Unknown"}
        total = sum(v["count"] for v in filled.values())
        steps.append(StepResult("missing_values", f"Filled {total:,} missing value(s)",
                                cells_changed=total, details={"filled": filled}))
    else:
        steps.append(StepResult("missing_values", "Missing values kept as empty"))

    return TransformResult(typed, cols, rows_in, rejected, steps)


def to_raw_strings(frame: pd.DataFrame) -> pd.DataFrame:
    """Render a typed frame as strings so the quality engine can assess it with the same rules."""
    out = pd.DataFrame(index=frame.index)
    for key in frame.columns:
        s = frame[key]
        if pd.api.types.is_datetime64_any_dtype(s):
            out[key] = s.dt.strftime("%Y-%m-%d %H:%M:%S").str.replace(" 00:00:00", "", regex=False)
        else:
            out[key] = s.astype("string")
    return out.astype("string").fillna("")
