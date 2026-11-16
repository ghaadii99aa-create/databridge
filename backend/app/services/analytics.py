"""Chart data built from real columns.

Each function loads only the columns it needs, aggregates server-side and returns compact
series. When a dataset cannot support a chart, a ValidationFailed explains why — the API
never fills a chart with placeholder values.
"""
from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.services import typing as T
from app.services.explorer import Source, resolve_source, source_meta, typed_frame

Agg = Literal["count", "sum", "mean", "median"]
MAX_CATEGORIES = 50
OTHER = "Other"


def suitability(session: Session, source_id: str) -> dict[str, Any]:
    source = resolve_source(session, source_id)
    numeric = [c for c in source.columns if c.type in T.NUMERIC_TYPES]
    dates = [c for c in source.columns if c.type == "datetime"]
    cats = [c for c in source.columns if c.type in ("category", "boolean")]

    distinct: dict[str, int] = {}
    if cats:
        frame = typed_frame(source, [c.key for c in cats])
        distinct = {c.key: int(frame[c.key].nunique()) for c in cats}

    def item(ok: bool, reason_no: str, reason_yes: str) -> dict[str, Any]:
        return {"available": ok, "reason": reason_yes if ok else reason_no}

    return {
        "source": source_meta(source),
        "numeric_columns": [c.__dict__ for c in numeric],
        "datetime_columns": [c.__dict__ for c in dates],
        "category_columns": [{**c.__dict__, "distinct": distinct.get(c.key, 0)} for c in cats],
        "charts": {
            "distribution": item(bool(numeric), "No numeric columns were detected, so there is nothing to bin.",
                                 f"{len(numeric)} numeric column(s) available."),
            "category": item(bool(cats), "No low-cardinality category columns were detected.",
                             f"{len(cats)} category column(s) available."),
            "timeseries": item(bool(dates), "No date column was detected, so a time trend cannot be drawn.",
                               f"{len(dates)} date column(s) available."),
            "comparison": item(len(cats) >= 2 or (cats and numeric),
                               "Comparison needs two category columns, or a category and a numeric measure.",
                               "Category columns can be cross-compared."),
        },
    }


def _measure(source: Source, frame: pd.DataFrame, measure: str | None, agg: Agg) -> tuple[str | None, Agg]:
    if agg != "count" and not measure:
        raise ValidationFailed(f"Aggregation '{agg}' needs a numeric measure column.")
    if measure:
        col = source.column(measure)
        if col.type not in T.NUMERIC_TYPES:
            raise ValidationFailed(f"'{col.name}' is not numeric, so it cannot be summed or averaged.")
        if agg == "count":
            agg = "sum"
    return measure, agg


def _aggregate(grouped: Any, measure: str | None, agg: Agg) -> pd.Series:
    if not measure or agg == "count":
        return grouped.size()
    return getattr(grouped[measure], agg)()


def distribution(session: Session, source_id: str, column: str, bins: int = 20) -> dict[str, Any]:
    source = resolve_source(session, source_id)
    col = source.column(column)
    if col.type not in T.NUMERIC_TYPES:
        raise ValidationFailed(f"'{col.name}' is {col.type}, not numeric; a distribution needs numbers.")
    values = typed_frame(source, [col.key])[col.key].dropna().astype("float64")
    if values.empty:
        raise ValidationFailed(f"'{col.name}' has no numeric values.")
    bins = max(5, min(bins, 60))
    lo, hi = float(values.min()), float(values.max())
    p1, p99 = (float(v) for v in values.quantile([0.01, 0.99]))
    if lo == hi:
        edges = np.array([lo - 0.5, hi + 0.5])
    elif col.type == "integer" and p99 - p1 <= 60:
        # whole-number bins for small integer ranges (e.g. quantities): one bar per value
        edges = np.arange(np.floor(p1) - 0.5, np.ceil(p99) + 1.5, 1.0)
    else:
        # clip the range to the 1st–99th percentile so a few extreme values don't flatten the chart
        edges = np.histogram_bin_edges(values.clip(p1, p99), bins=bins)
    counts, edges = np.histogram(values.clip(edges[0], edges[-1]), bins=edges)
    clipped = int(((values < edges[0]) | (values > edges[-1])).sum())
    return {
        "column": col.__dict__, "count": int(len(values)),
        "bins": [{"start": float(edges[i]), "end": float(edges[i + 1]), "count": int(counts[i])} for i in range(len(counts))],
        "stats": {"mean": float(values.mean()), "median": float(values.median()), "min": lo, "max": hi,
                  "std": float(values.std()) if len(values) > 1 else 0.0},
        "note": (f"{clipped} value(s) beyond the 1st–99th percentile are counted in the edge bins." if clipped else None),
    }


def category_breakdown(session: Session, source_id: str, column: str, measure: str | None = None,
                       agg: Agg = "count", limit: int = 12) -> dict[str, Any]:
    source = resolve_source(session, source_id)
    col = source.column(column)
    if col.type not in ("category", "boolean", "text", "identifier"):
        raise ValidationFailed(f"'{col.name}' is {col.type}; pick a category column for a breakdown.")
    keys = [col.key] + ([measure] if measure else [])
    frame = typed_frame(source, keys)
    measure, agg = _measure(source, frame, measure, agg)
    frame[col.key] = frame[col.key].astype("string").fillna("(missing)")
    distinct = frame[col.key].nunique()
    if distinct > MAX_CATEGORIES * 20:
        raise ValidationFailed(f"'{col.name}' has {distinct:,} distinct values — too many for a category chart.")
    series = _aggregate(frame.groupby(col.key), measure, agg).sort_values(ascending=False)
    limit = max(3, min(limit, MAX_CATEGORIES))
    top = series.head(limit)
    other = series.iloc[limit:]
    items = [{"label": str(k), "value": float(v)} for k, v in top.items()]
    if len(other) and agg in ("count", "sum"):
        items.append({"label": f"{OTHER} ({len(other)})", "value": float(other.sum())})
    total = float(series.sum()) if agg in ("count", "sum") else None
    return {"column": col.__dict__, "measure": measure, "agg": agg, "items": items, "total": total,
            "distinct": int(distinct)}


def timeseries(session: Session, source_id: str, date_column: str, measure: str | None = None,
               agg: Agg = "count", freq: Literal["auto", "D", "W", "M", "Q"] = "auto") -> dict[str, Any]:
    source = resolve_source(session, source_id)
    col = source.column(date_column)
    if col.type != "datetime":
        raise ValidationFailed(f"'{col.name}' is not a date column; time trends need dates.")
    keys = [col.key] + ([measure] if measure else [])
    frame = typed_frame(source, keys).dropna(subset=[col.key])
    measure, agg = _measure(source, frame, measure, agg)
    if frame.empty:
        raise ValidationFailed(f"'{col.name}' has no parseable dates.")
    span = (frame[col.key].max() - frame[col.key].min()).days
    if freq == "auto":
        freq = "D" if span <= 62 else "W" if span <= 270 else "M" if span <= 3 * 365 else "Q"
    rule = {"D": "D", "W": "W-MON", "M": "MS", "Q": "QS"}[freq]
    grouped = frame.set_index(col.key).resample(rule, label="left", closed="left")
    series = _aggregate(grouped, measure, agg)
    if agg in ("count", "sum"):
        series = series.fillna(0)
    points = [{"period": idx.strftime("%Y-%m-%d"), "value": None if pd.isna(v) else float(v)} for idx, v in series.items()]
    return {"column": col.__dict__, "measure": measure, "agg": agg, "freq": freq, "points": points,
            "start": frame[col.key].min().isoformat(), "end": frame[col.key].max().isoformat()}


def comparison(session: Session, source_id: str, column: str, split: str, measure: str | None = None,
               agg: Agg = "count", limit: int = 8) -> dict[str, Any]:
    source = resolve_source(session, source_id)
    a, b = source.column(column), source.column(split)
    if a.key == b.key:
        raise ValidationFailed("Choose two different columns to compare.")
    for c in (a, b):
        if c.type not in ("category", "boolean"):
            raise ValidationFailed(f"'{c.name}' is {c.type}; comparison needs category columns.")
    keys = [a.key, b.key] + ([measure] if measure else [])
    frame = typed_frame(source, keys)
    measure, agg = _measure(source, frame, measure, agg)
    frame[a.key] = frame[a.key].astype("string").fillna("(missing)")
    frame[b.key] = frame[b.key].astype("string").fillna("(missing)")
    limit = max(2, min(limit, 15))
    top_a = frame[a.key].value_counts().head(limit).index
    top_b = frame[b.key].value_counts().head(6).index
    frame = frame[frame[a.key].isin(top_a) & frame[b.key].isin(top_b)]
    table = _aggregate(frame.groupby([a.key, b.key]), measure, agg).unstack(fill_value=0)
    table = table.reindex(index=top_a, columns=top_b).fillna(0)
    return {
        "column": a.__dict__, "split": b.__dict__, "measure": measure, "agg": agg,
        "series": [str(s) for s in table.columns],
        "rows": [{"label": str(idx), **{str(k): float(v) for k, v in row.items()}} for idx, row in table.iterrows()],
    }
