"""Data quality engine.

Pure functions over a pandas DataFrame of raw string values plus the inferred column types.
No database access here, so the engine is reusable and directly unit-testable.

Scoring methodology (version 1.0, documented in docs/DATA_QUALITY.md):

    score = 100 × (0.30·Completeness + 0.30·Validity + 0.20·Uniqueness + 0.20·Consistency)

    Completeness = 1 − missing cells / total cells
    Validity     = 1 − invalid cells / non-missing cells in typed columns
    Uniqueness   = 1 − duplicate rows / total rows
    Consistency  = 1 − inconsistently formatted cells / non-missing cells in text-like columns

Outliers are reported with severity "info" and never reduce the score: an extreme value
is a reason to look, not proof of an error.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from app.services import typing as T

METHODOLOGY_VERSION = "1.0"
WEIGHTS = {"completeness": 0.30, "validity": 0.30, "uniqueness": 0.20, "consistency": 0.20}
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
OUTLIER_IQR_FACTOR = 3.0
TEXTLIKE = {"category", "text", "identifier"}

CHECKS: dict[str, dict[str, str]] = {
    "missing_values": {"dimension": "completeness", "title": "Missing values",
                       "rule": "Value is empty or a null token (NA, N/A, null, none, -, ?)."},
    "empty_column": {"dimension": "completeness", "title": "Empty column",
                     "rule": "Every value in the column is missing."},
    "duplicate_rows": {"dimension": "uniqueness", "title": "Duplicate records",
                       "rule": "Row is identical to an earlier row after trimming whitespace and ignoring case."},
    "duplicate_identifier": {"dimension": "uniqueness", "title": "Duplicate identifiers",
                             "rule": "Identifier value repeats in a row that is not a full duplicate."},
    "invalid_type": {"dimension": "validity", "title": "Invalid data type",
                     "rule": "Value cannot be parsed as the column's inferred type (≥90% of values define the type)."},
    "unexpected_negative": {"dimension": "validity", "title": "Unexpected negative values",
                            "rule": "Negative number in a column whose name implies a non-negative quantity (price, quantity, revenue…)."},
    "inconsistent_categories": {"dimension": "consistency", "title": "Inconsistent categories",
                                "rule": "Same category written in different ways (case, spacing, punctuation)."},
    "whitespace": {"dimension": "consistency", "title": "Leading/trailing whitespace",
                   "rule": "Value has spaces before or after the text."},
    "mixed_date_formats": {"dimension": "consistency", "title": "Mixed date formats",
                           "rule": "Dates in a column use more than one format pattern."},
    "outliers": {"dimension": "info", "title": "Potential outliers",
                 "rule": f"Numeric value outside [Q1 − {OUTLIER_IQR_FACTOR}·IQR, Q3 + {OUTLIER_IQR_FACTOR}·IQR]. Not scored."},
}


@dataclass
class ColumnSpec:
    key: str
    name: str
    type: str


@dataclass
class Issue:
    check_code: str
    severity: str
    column_key: str | None
    column_name: str | None
    affected_rows: int
    affected_ratio: float
    message: str
    recommendation: str
    examples: list[Any] = field(default_factory=list)
    row_mask: np.ndarray | None = field(default=None, repr=False)

    @property
    def dimension(self) -> str:
        return CHECKS[self.check_code]["dimension"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_code": self.check_code,
            "dimension": self.dimension,
            "severity": self.severity,
            "column_key": self.column_key,
            "column_name": self.column_name,
            "affected_rows": self.affected_rows,
            "affected_ratio": round(self.affected_ratio, 4),
            "message": self.message,
            "recommendation": self.recommendation,
            "examples": self.examples,
        }


@dataclass
class QualityResult:
    score: float
    dimensions: dict[str, float]
    row_count: int
    column_count: int
    affected_rows: int
    issues: list[Issue]
    counts: dict[str, int]
    column_summary: list[dict[str, Any]]

    @property
    def total_issues(self) -> int:
        return len([i for i in self.issues if i.severity != "info"])


def _ratio_severity(ratio: float, high: float = 0.2, medium: float = 0.05) -> str:
    if ratio >= high:
        return "high"
    if ratio >= medium:
        return "medium"
    return "low"


def _examples(values: pd.Series, limit: int = 5) -> list[str]:
    return [str(v) for v in values.dropna().astype(str).unique()[:limit]]


def assess(df: pd.DataFrame, columns: list[ColumnSpec]) -> QualityResult:
    """Run every check and compute the score. `df` columns are keyed by ColumnSpec.key."""
    n_rows = len(df)
    n_cols = len(columns)
    issues: list[Issue] = []
    if n_rows == 0 or n_cols == 0:
        return QualityResult(0.0, {k: 0.0 for k in WEIGHTS}, n_rows, n_cols, 0, [], {}, [])

    df = df.reset_index(drop=True)
    raw = df.astype("string")
    missing = pd.DataFrame({c.key: T.missing_mask(raw[c.key]) for c in columns})
    total_cells = n_rows * n_cols
    missing_cells = int(missing.to_numpy().sum())

    invalid_cells = 0
    typed_cells = 0
    inconsistent_cells = 0
    textlike_cells = 0
    column_summary: list[dict[str, Any]] = []

    for col in columns:
        s = raw[col.key]
        miss = missing[col.key].to_numpy(dtype=bool)
        present = ~miss
        n_missing = int(miss.sum())
        n_present = int(present.sum())
        col_invalid = np.zeros(n_rows, dtype=bool)
        col_inconsistent = np.zeros(n_rows, dtype=bool)

        # --- completeness ------------------------------------------------------------
        if n_missing == n_rows:
            issues.append(Issue(
                "empty_column", "high", col.key, col.name, n_rows, 1.0,
                f"Column '{col.name}' contains no values.",
                "Drop the column, or check the source export for a mapping error.",
                row_mask=None,
            ))
        elif n_missing:
            ratio = n_missing / n_rows
            sev = "high" if col.type == "identifier" else _ratio_severity(ratio, 0.3, 0.05)
            if col.type == "identifier":
                rec = "Reject rows without an identifier; they cannot be traced back to the source."
            elif col.type in T.NUMERIC_TYPES:
                rec = "Fill with the median, or drop rows if this value is required for analysis."
            elif col.type == "datetime":
                rec = "Drop rows if dates are required for time-based analysis; do not guess dates."
            else:
                rec = "Fill with an explicit 'Unknown' value so the gap stays visible in reports."
            issues.append(Issue(
                "missing_values", sev, col.key, col.name, n_missing, ratio,
                f"{n_missing:,} of {n_rows:,} values missing in '{col.name}' ({ratio:.1%}).",
                rec, row_mask=miss,
            ))

        # --- validity ----------------------------------------------------------------
        if col.type in T.TYPED_TYPES and n_present:
            typed_cells += n_present
            ok = T.conforms(s, col.type).fillna(False).to_numpy(dtype=bool)
            bad = present & ~ok
            col_invalid |= bad
            if bad.any():
                cnt = int(bad.sum())
                ratio = cnt / n_present
                issues.append(Issue(
                    "invalid_type", _ratio_severity(ratio, 0.05, 0.01), col.key, col.name, cnt, cnt / n_rows,
                    f"{cnt:,} values in '{col.name}' are not valid {col.type} values.",
                    f"Convert to {col.type}; unparseable values become empty and are reported, not guessed.",
                    _examples(s[bad]), row_mask=bad,
                ))
            if col.type in T.NUMERIC_TYPES:
                nums = T.parse_numeric(s)
                if T.expects_non_negative(col.name):
                    neg = (nums < 0).fillna(False).to_numpy(dtype=bool) & present
                    col_invalid |= neg
                    if neg.any():
                        cnt = int(neg.sum())
                        issues.append(Issue(
                            "unexpected_negative", "medium", col.key, col.name, cnt, cnt / n_rows,
                            f"{cnt:,} negative values in '{col.name}', which should not be negative.",
                            "Reject these rows or confirm whether they are returns/refunds recorded in the wrong column.",
                            _examples(s[neg]), row_mask=neg,
                        ))
                vals = nums.dropna()
                if len(vals) >= 20:
                    q1, q3 = vals.quantile(0.25), vals.quantile(0.75)
                    iqr = q3 - q1
                    if iqr > 0:
                        lo, hi = q1 - OUTLIER_IQR_FACTOR * iqr, q3 + OUTLIER_IQR_FACTOR * iqr
                        out = ((nums < lo) | (nums > hi)).fillna(False).to_numpy(dtype=bool)
                        if out.any():
                            cnt = int(out.sum())
                            issues.append(Issue(
                                "outliers", "info", col.key, col.name, cnt, cnt / n_rows,
                                f"{cnt:,} values in '{col.name}' fall outside {lo:,.2f} – {hi:,.2f}.",
                                "Review these records. Keep them if they are genuine (e.g. bulk orders).",
                                _examples(s[out]), row_mask=out,
                            ))
            invalid_cells += int(col_invalid.sum())

        # --- consistency -------------------------------------------------------------
        if (col.type in TEXTLIKE or col.type == "datetime") and n_present:
            textlike_cells += n_present
            stripped = T.strip(s)
            ws = (present & (s != stripped).fillna(False).to_numpy(dtype=bool))
            col_inconsistent |= ws
            if ws.any():
                cnt = int(ws.sum())
                issues.append(Issue(
                    "whitespace", "low", col.key, col.name, cnt, cnt / n_rows,
                    f"{cnt:,} values in '{col.name}' have leading or trailing spaces.",
                    "Trim whitespace.", [f"'{v}'" for v in _examples(s[ws], 3)], row_mask=ws,
                ))
            if col.type == "category":
                norm = T.normalize_token(s)
                frame = pd.DataFrame({"raw": stripped, "norm": norm}).reset_index(drop=True)[present]
                bad = np.zeros(n_rows, dtype=bool)
                examples: list[str] = []
                for _, grp in frame.groupby("norm"):
                    counts = grp["raw"].value_counts()
                    if len(counts) > 1:
                        dominant = counts.index[0]
                        bad[grp.index[grp["raw"] != dominant].to_numpy()] = True
                        examples.append(" / ".join(map(str, counts.index[:4])))
                col_inconsistent |= bad
                if bad.any():
                    cnt = int(bad.sum())
                    issues.append(Issue(
                        "inconsistent_categories", _ratio_severity(cnt / n_present, 0.1, 0.02),
                        col.key, col.name, cnt, cnt / n_rows,
                        f"{len(examples)} categories in '{col.name}' are written in more than one way ({cnt:,} rows).",
                        "Normalise each group to its most frequent spelling.", examples[:5], row_mask=bad,
                    ))
            if col.type == "datetime":
                shapes = T.date_shape(s)[present]
                counts = shapes.value_counts()
                if len(counts) > 1:
                    dominant = counts.index[0]
                    bad = present & (T.date_shape(s) != dominant).fillna(False).to_numpy(dtype=bool)
                    col_inconsistent |= bad
                    cnt = int(bad.sum())
                    issues.append(Issue(
                        "mixed_date_formats", _ratio_severity(cnt / n_present, 0.1, 0.02),
                        col.key, col.name, cnt, cnt / n_rows,
                        f"'{col.name}' uses {len(counts)} date formats; {cnt:,} values differ from the most common one.",
                        "Parse all dates and store them in one ISO-8601 format.",
                        _examples(s[bad], 4), row_mask=bad,
                    ))
            inconsistent_cells += int(col_inconsistent.sum())

        column_summary.append({
            "key": col.key, "name": col.name, "type": col.type,
            "missing": n_missing, "invalid": int(col_invalid.sum()),
            "inconsistent": int(col_inconsistent.sum()),
        })

    # --- uniqueness --------------------------------------------------------------------
    keys = [c.key for c in columns]
    normalized = raw[keys].apply(lambda s: T.strip(s).str.lower()).fillna("")
    dup_mask = normalized.duplicated(keep="first").to_numpy(dtype=bool)
    dup_rows = int(dup_mask.sum())
    if dup_rows:
        ratio = dup_rows / n_rows
        issues.append(Issue(
            "duplicate_rows", "high" if ratio >= 0.05 else "medium", None, None, dup_rows, ratio,
            f"{dup_rows:,} rows are duplicates of an earlier row.",
            "Remove duplicates, keeping the first occurrence.", row_mask=dup_mask,
        ))
    id_dup_total = np.zeros(n_rows, dtype=bool)
    for col in columns:
        if col.type != "identifier":
            continue
        s = normalized[col.key]
        present = ~missing[col.key].to_numpy(dtype=bool)
        id_dup = present & s.duplicated(keep="first").to_numpy(dtype=bool) & ~dup_mask
        if id_dup.any():
            id_dup_total |= id_dup
            cnt = int(id_dup.sum())
            issues.append(Issue(
                "duplicate_identifier", "high", col.key, col.name, cnt, cnt / n_rows,
                f"{cnt:,} rows reuse an existing '{col.name}' with different content.",
                "Investigate the source system; two different records should not share an identifier.",
                _examples(raw[col.key][id_dup]), row_mask=id_dup,
            ))
    duplicate_rows = int((dup_mask | id_dup_total).sum())

    # --- scores ------------------------------------------------------------------------
    dims = {
        "completeness": 1 - missing_cells / total_cells,
        "validity": 1 - invalid_cells / typed_cells if typed_cells else 1.0,
        "uniqueness": 1 - duplicate_rows / n_rows,
        "consistency": 1 - inconsistent_cells / textlike_cells if textlike_cells else 1.0,
    }
    score = round(100 * sum(WEIGHTS[k] * v for k, v in dims.items()), 1)

    affected = np.zeros(n_rows, dtype=bool)
    for issue in issues:
        if issue.severity != "info" and issue.row_mask is not None:
            affected |= issue.row_mask
    issues.sort(key=lambda i: (SEVERITY_ORDER[i.severity], -i.affected_rows))

    return QualityResult(
        score=score,
        dimensions={k: round(v * 100, 2) for k, v in dims.items()},
        row_count=n_rows,
        column_count=n_cols,
        affected_rows=int(affected.sum()),
        issues=issues,
        counts={
            "total_cells": total_cells, "missing_cells": missing_cells,
            "typed_cells": typed_cells, "invalid_cells": invalid_cells,
            "duplicate_rows": duplicate_rows, "textlike_cells": textlike_cells,
            "inconsistent_cells": inconsistent_cells,
        },
        column_summary=column_summary,
    )


def methodology() -> dict[str, Any]:
    return {
        "version": METHODOLOGY_VERSION,
        "weights": WEIGHTS,
        "formula": "score = 100 × Σ(weight × dimension)",
        "dimensions": {
            "completeness": "1 − missing cells / total cells",
            "validity": "1 − invalid cells / non-missing cells in typed columns (integer, decimal, boolean, datetime)",
            "uniqueness": "1 − duplicate rows (full duplicates + reused identifiers) / total rows",
            "consistency": "1 − inconsistent cells / non-missing cells in text-like and date columns",
        },
        "checks": CHECKS,
        "type_threshold": T.TYPE_THRESHOLD,
        "severity_levels": list(SEVERITY_ORDER),
    }
