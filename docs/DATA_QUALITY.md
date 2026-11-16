# Data quality methodology (v1.0)

The quality engine (`backend/app/services/quality/engine.py`) is a set of pure functions over a pandas DataFrame.
It has no database access, so it is unit-tested directly, and the same rules assess raw data and processed output.
That keeps before/after comparisons fair. The live rules are also served by `GET /api/quality/methodology`
and shown in the app.

## 1. Column types come first

Every rule depends on knowing what a column should contain. Raw values are read as text, and a type is inferred
from up to 20,000 non-empty values. **A typed classification needs at least 90% of values to parse**; the
remaining values become "invalid type" findings instead of silently changing the column's type.

| Type | Rule |
|---|---|
| Boolean | ≥ 90% of values are true/false/yes/no/y/n/t/f |
| Integer / Decimal | ≥ 90% parse as numbers (thousands separators, `$ € £ ¥`, `SAR/USD/EUR/GBP` and `(40)` negatives accepted). Names that look like identifiers (`…_id`, `code`, `sku`…) and zero-padded values (`00123`) are never numeric. |
| Date | ≥ half look date-shaped and ≥ 90% parse (ISO-8601 vectorised; other formats with mixed parsing) |
| Identifier | Identifier-like name and ≥ 90% distinct |
| Category | ≤ max(25, 5% of rows) distinct values |
| Text / Empty | Otherwise / no values at all |

**Missing** means empty, or one of the null tokens `NA, N/A, null, none, nan, #N/A, nil, -, --, ?`
(case-insensitive, surrounding spaces ignored).

## 2. Checks

| Check | Dimension | Rule | Severity |
|---|---|---|---|
| Missing values | Completeness | Value is missing | ≥ 30% high, ≥ 5% medium, else low; any missing identifier is high |
| Empty column | Completeness | Every value missing | high |
| Duplicate records | Uniqueness | Row equals an earlier row after trimming and lower-casing | ≥ 5% of rows high, else medium |
| Duplicate identifiers | Uniqueness | Identifier repeats in a row that is not a full duplicate | high |
| Invalid data type | Validity | Non-missing value doesn't parse as the column type | ≥ 5% high, ≥ 1% medium, else low |
| Unexpected negatives | Validity | Negative number in a column whose name implies a non-negative quantity (`qty, quantity, price, amount, revenue, cost, sales, units, count, age, total, weight, stock`, unless it also says `change, delta, diff, margin, profit, balance, adjust`) | medium |
| Inconsistent categories | Consistency | Same category written several ways. Values are compared after lower-casing, treating `&` and the word `and` as equal, and collapsing punctuation and spacing. The most frequent spelling is canonical. | ≥ 10% high, ≥ 2% medium, else low |
| Leading/trailing whitespace | Consistency | Value differs from its trimmed form | low |
| Mixed date formats | Consistency | Date values follow more than one pattern (digits → `9`, letters → `A`); the most frequent pattern is canonical | ≥ 10% high, ≥ 2% medium, else low |
| Potential outliers | Informational | Numeric value outside `[Q1 − 3·IQR, Q3 + 3·IQR]` (needs ≥ 20 values) | info, **not scored** |

Every finding stores its affected row count, ratio, up to five example values and a recommended action.

## 3. Score

```
score = 100 × (0.30 · Completeness + 0.30 · Validity + 0.20 · Uniqueness + 0.20 · Consistency)

Completeness = 1 − missing cells / total cells
Validity     = 1 − invalid cells / non-missing cells in typed columns (integer, decimal, boolean, date)
Uniqueness   = 1 − duplicate rows (full duplicates + reused identifiers) / rows
Consistency  = 1 − inconsistent cells / non-missing cells in category, text, identifier and date columns
```

The cell counts behind each dimension are stored with every assessment (`details.counts`) and printed in the
interface and the PDF reports, so a score can be checked by hand. A cell flagged by two checks in the same
dimension is counted once.

**Why these weights.** Completeness and validity carry the most weight because missing or wrong values change
results directly, for example totals, averages and joins. Duplicates and formatting inconsistency distort
results too, but they can usually be repaired mechanically, so they weigh less. The weights are a documented
choice, not a universal standard; they live in one constant (`WEIGHTS`) and the methodology is versioned.

**Why outliers are not scored.** An extreme value is a reason to look, not proof of an error. In the sample
dataset, the largest orders are genuine bulk purchases.

**Rows affected** is the number of distinct rows touched by at least one scored finding. It is reported next
to the score because cell-level ratios can look high even when many records have a problem. In the sample,
98.9 coexists with 19% of rows affected.

## 4. Worked example (from the unit tests)

Six rows: `id` (identifier), `cat` (category: Books, books, Books, Toys, Toys, empty) and `qty` (integer:
1, 2, x, −1, −1, 3). Rows 4 and 5 are identical.

| Dimension | Calculation | Value |
|---|---|---|
| Completeness | 1 − 1 missing / 18 cells | 94.44 |
| Validity | 1 − 3 invalid ("x", −1, −1) / 6 typed cells | 50.00 |
| Uniqueness | 1 − 1 duplicate row / 6 rows | 83.33 |
| Consistency | 1 − 1 variant ("books") / 11 text cells | 90.91 |
| **Score** | 0.3·94.44 + 0.3·50 + 0.2·83.33 + 0.2·90.91 | **78.2** |

`tests/test_units.py::TestQualityEngine::test_known_answer` asserts each of these numbers.

## 5. Cleaning rules (pipelines)

Rules run in a fixed, documented order, because the order changes results. For example, de-duplication runs
after normalisation so that rows differing only in case or spacing are caught.

1. Null tokens become real missing values (always).
2. Drop empty columns.
3. Trim whitespace.
4. Normalise category variants to the most frequent spelling.
5. Remove duplicate rows (keep the first).
6. Convert types. Unparseable values become empty and are **counted in the log, never guessed**.
7. Reject rows with negative values in non-negative columns.
8. Reject rows missing a required column.
9. Missing values: keep, drop incomplete rows, or fill text/category with `Unknown`. Numbers are only filled
   (median or zero) when you opt in, because a filled revenue figure would distort totals. Dates and
   identifiers are never filled.

## 6. Known limits

* Rules are generic. Domain rules, such as `revenue = quantity × unit price`, are not inferred; they are on the
  roadmap as user-defined checks.
* Category normalisation matches spelling variants, not synonyms ("KSA" vs "Saudi Arabia").
* Ambiguous dates such as `03/04/2025` are read month-first. A day-first option per column is on the roadmap.
