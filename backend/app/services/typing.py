"""Type inference and value parsing shared by profiling, quality checks, cleaning and analytics.

Raw data is handled as strings. These helpers decide what a column *should* be and parse
values into that type, returning NaN/NaT where a value does not conform.
"""
from __future__ import annotations

import re
import warnings

import numpy as np
import pandas as pd

NULL_TOKENS = {"", "na", "n/a", "null", "none", "nan", "#n/a", "nil", "-", "--", "?"}
TRUE_TOKENS = {"true", "yes", "y", "t"}
FALSE_TOKENS = {"false", "no", "n", "f"}

TYPE_THRESHOLD = 0.90  # share of non-null values that must parse for a type to be inferred
INFERENCE_SAMPLE = 20_000

COLUMN_TYPES = ("integer", "decimal", "boolean", "datetime", "category", "identifier", "text", "empty")
NUMERIC_TYPES = {"integer", "decimal"}
TYPED_TYPES = {"integer", "decimal", "boolean", "datetime"}

_CURRENCY = re.compile(r"^\s*[\$€£¥]|\s*(USD|SAR|EUR|GBP)\s*$", re.IGNORECASE)
_NUMERIC_CLEAN = re.compile(r"[\s,\$€£¥]|(USD|SAR|EUR|GBP)", re.IGNORECASE)
_ID_NAME = re.compile(r"(^id$|_id$|^id_|identifier|code$|number$|^sku$|_no$|uuid)", re.IGNORECASE)
_DATEISH = re.compile(r"\d{1,4}[-/.\s]\w{1,9}[-/.\s]\d{1,4}|\d{4}-\d{2}-\d{2}")


def per_unique(fn):
    """Run a vectorised string function once per distinct value and map results back.

    Real columns repeat values heavily (categories, dates, prices), so factorising first turns
    O(rows) Python-level string work into O(distinct values). Results are identical.
    """
    def wrapper(series: pd.Series, *args, **kwargs) -> pd.Series:
        if len(series) < 2_000 or not (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
            return fn(series, *args, **kwargs)
        codes, uniques = pd.factorize(series, use_na_sentinel=True)
        mapped = fn(pd.Series(uniques, dtype=series.dtype), *args, **kwargs)
        missing = codes < 0
        out = mapped.take(np.where(missing, 0, codes) if len(mapped) else codes)
        out.index = series.index
        if missing.any():
            out = out.copy()
            out[missing] = fn(pd.Series([pd.NA], dtype=series.dtype), *args, **kwargs).iloc[0]
        return out
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


@per_unique
def strip(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip()


@per_unique
def missing_mask(series: pd.Series) -> pd.Series:
    """True where a raw value counts as missing (empty or a common null token)."""
    s = series.astype("string")
    return (s.isna() | s.str.strip().str.lower().isin(NULL_TOKENS)).fillna(True).astype(bool)


@per_unique
def parse_numeric(series: pd.Series) -> pd.Series:
    """Parse numbers, tolerating thousands separators and currency symbols."""
    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        return series.astype("float64")
    s = series.astype("string").str.strip()
    negative_paren = s.str.match(r"^\(.*\)$", na=False)
    cleaned = s.str.replace(_NUMERIC_CLEAN, "", regex=True).str.strip("()")
    out = pd.to_numeric(cleaned, errors="coerce").astype("float64")
    out[negative_paren.fillna(False).to_numpy()] *= -1
    return out


@per_unique
def parse_datetime(series: pd.Series) -> pd.Series:
    """Parse dates. ISO-8601 is parsed vectorised; remaining values fall back to mixed parsing."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    s = series.astype("string").str.strip()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = pd.to_datetime(s, format="ISO8601", errors="coerce")
        rest = out.isna() & s.notna() & (s != "")
        if rest.any():
            out.loc[rest] = pd.to_datetime(s[rest], format="mixed", errors="coerce", dayfirst=False)
    if getattr(out.dt, "tz", None) is not None:
        out = out.dt.tz_convert("UTC").dt.tz_localize(None)
    return out.astype("datetime64[ns]")


@per_unique
def parse_boolean(series: pd.Series) -> pd.Series:
    s = series.astype("string").str.strip().str.lower()
    out = pd.Series(pd.NA, index=series.index, dtype="boolean")
    out[s.isin(TRUE_TOKENS).fillna(False)] = True
    out[s.isin(FALSE_TOKENS).fillna(False)] = False
    return out


def conforms(series: pd.Series, col_type: str) -> pd.Series:
    """Boolean mask: True where a non-missing value parses as `col_type`."""
    if col_type == "integer":
        n = parse_numeric(series)
        return n.notna() & (np.floor(n) == n)
    if col_type == "decimal":
        return parse_numeric(series).notna()
    if col_type == "datetime":
        return parse_datetime(series).notna()
    if col_type == "boolean":
        return parse_boolean(series).notna()
    return pd.Series(True, index=series.index)


def infer_type(series: pd.Series, name: str = "") -> str:
    present = series[~missing_mask(series)]
    if present.empty:
        return "empty"
    sample = present.head(INFERENCE_SAMPLE).astype("string").str.strip()
    n = len(sample)
    lowered = sample.str.lower()

    if lowered.isin(TRUE_TOKENS | FALSE_TOKENS).mean() >= TYPE_THRESHOLD:
        return "boolean"

    numeric = parse_numeric(sample)
    num_ratio = numeric.notna().mean()
    looks_like_id = bool(_ID_NAME.search(re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")))
    if num_ratio >= TYPE_THRESHOLD and not looks_like_id:
        values = numeric.dropna()
        # zero-padded codes ("00123") are identifiers, not numbers
        padded = sample.str.match(r"^0\d+$", na=False).mean() > 0.2
        if not padded:
            return "integer" if bool((np.floor(values) == values).all()) else "decimal"

    if sample.str.contains(_DATEISH, na=False).mean() >= 0.5:
        if parse_datetime(sample).notna().mean() >= TYPE_THRESHOLD:
            return "datetime"

    distinct = sample.nunique()
    if looks_like_id and distinct >= 0.9 * n:
        return "identifier"
    if distinct <= max(25, int(0.05 * n)) and distinct < n:
        return "category"
    if distinct >= 0.98 * n and sample.str.len().median() <= 40 and not sample.str.contains(" ").mean() > 0.5:
        return "identifier" if looks_like_id else "text"
    return "text"


NON_NEGATIVE_HINTS = re.compile(
    r"(qty|quantity|price|amount|revenue|cost|sales|units|count|age|total|weight|stock)",
    re.IGNORECASE,
)


def expects_non_negative(name: str) -> bool:
    """Columns whose names imply a value can never be negative (documented heuristic)."""
    return bool(NON_NEGATIVE_HINTS.search(name)) and not re.search(
        r"(change|delta|diff|margin|profit|balance|adjust)", name, re.IGNORECASE
    )


@per_unique
def date_shape(series: pd.Series) -> pd.Series:
    """Format signature of each date string, e.g. '2024-03-05' -> '9999-99-99'."""
    return series.astype("string").str.strip().str.replace(r"\d", "9", regex=True).str.replace(
        r"[A-Za-z]+", "A", regex=True
    )


@per_unique
def normalize_token(series: pd.Series) -> pd.Series:
    """Canonical form used to detect category variants: case/whitespace/punctuation-insensitive."""
    return (
        series.astype("string")
        .str.strip()
        .str.lower()
        .str.replace(r"&|\band\b", " ", regex=True)  # "Home & Kitchen" == "Home and Kitchen"
        .str.replace(r"[^\w\s]|_", " ", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )
