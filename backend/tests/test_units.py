"""Unit tests for pure functions: identifiers, type inference, quality engine, cleaning."""
from __future__ import annotations

import pandas as pd
import pytest

from app.core.identifiers import assert_safe_identifier, unique_column_keys
from app.services import typing as T
from app.services.cleaning import TransformConfig, transform
from app.services.quality.engine import WEIGHTS, ColumnSpec, assess


class TestIdentifiers:
    def test_column_keys_are_safe_and_unique(self):
        keys = unique_column_keys(["Order ID", "order id", "Unit Price (SAR)", "", "1st Value", "select", "Ünïcode"])
        assert keys == ["order_id", "order_id_1", "unit_price_sar", "column_4", "c_1st_value", "select_col", "unicode"]

    @pytest.mark.parametrize("bad", ["users; DROP TABLE x", "a-b", "1abc", "", 'x"y', "A" * 70])
    def test_unsafe_identifiers_rejected(self, bad):
        with pytest.raises(ValueError):
            assert_safe_identifier(bad)


class TestTypeInference:
    @pytest.mark.parametrize("values,name,expected", [
        (["1", "2", "3", "40"], "quantity", "integer"),
        (["$1,200.50", "99.90", "1,000"], "price", "decimal"),
        (["2025-01-02", "2025-02-03", "03/04/2025"], "order date", "datetime"),
        (["yes", "no", "Yes", "NO"], "active", "boolean"),
        (["A-1", "A-2", "A-3", "A-4"], "Order ID", "identifier"),
        (["North", "South", "North", "East", "South", "North"], "region", "category"),
        (["", "N/A", "null"], "notes", "empty"),
        (["00123", "00456", "00789", "01011"], "zip", "text"),
    ])
    def test_infer(self, values, name, expected):
        assert T.infer_type(pd.Series(values), name) == expected

    def test_missing_tokens(self):
        mask = T.missing_mask(pd.Series(["", " NA ", "n/a", "None", "-", "0", "value"]))
        assert mask.tolist() == [True, True, True, True, True, False, False]

    def test_numeric_parsing_handles_currency_and_parentheses(self):
        parsed = T.parse_numeric(pd.Series(["SAR 1,250.00", "(40)", "abc", "12"]))
        assert parsed.iloc[0] == 1250.0 and parsed.iloc[1] == -40.0 and pd.isna(parsed.iloc[2]) and parsed.iloc[3] == 12


def _frame():
    df = pd.DataFrame({
        "id": ["1", "2", "3", "4", "4", "6"],
        "cat": ["Books", "books", "Books", "Toys", "Toys", ""],
        "qty": ["1", "2", "x", "-1", "-1", "3"],
    })
    cols = [ColumnSpec("id", "Order ID", "identifier"), ColumnSpec("cat", "Category", "category"),
            ColumnSpec("qty", "Quantity", "integer")]
    return df, cols


class TestQualityEngine:
    def test_known_answer(self):
        df, cols = _frame()
        r = assess(df, cols)
        codes = {(i.check_code, i.column_key): i.affected_rows for i in r.issues}
        assert codes[("missing_values", "cat")] == 1
        assert codes[("duplicate_rows", None)] == 1          # row 5 duplicates row 4
        assert codes[("invalid_type", "qty")] == 1           # "x"
        assert codes[("unexpected_negative", "qty")] == 2    # -1, -1
        assert codes[("inconsistent_categories", "cat")] == 1  # "books" vs "Books"
        # dimensions follow the documented formulas exactly
        assert r.dimensions["completeness"] == round((1 - 1 / 18) * 100, 2)
        assert r.dimensions["uniqueness"] == round((1 - 1 / 6) * 100, 2)
        assert r.dimensions["validity"] == round((1 - 3 / 6) * 100, 2)
        assert r.dimensions["consistency"] == round((1 - 1 / 11) * 100, 2)
        expected = 100 * sum(WEIGHTS[k] * v / 100 for k, v in {
            "completeness": (1 - 1 / 18) * 100, "validity": 50.0,
            "uniqueness": (1 - 1 / 6) * 100, "consistency": (1 - 1 / 11) * 100}.items())
        assert r.score == round(expected, 1)

    def test_clean_data_scores_100(self):
        df = pd.DataFrame({"a": ["x", "y", "z"], "b": ["1", "2", "3"]})
        r = assess(df, [ColumnSpec("a", "A", "category"), ColumnSpec("b", "B", "integer")])
        assert r.score == 100.0 and r.total_issues == 0

    def test_outliers_reported_but_not_scored(self):
        values = [str(v) for v in [10] * 30 + [11] * 30 + [10_000]]
        df = pd.DataFrame({"id": [f"r{i}" for i in range(len(values))], "v": values})
        r = assess(df, [ColumnSpec("id", "Row ID", "identifier"), ColumnSpec("v", "Value", "integer")])
        assert any(i.check_code == "outliers" and i.severity == "info" for i in r.issues)
        assert r.score == 100.0 and r.total_issues == 0

    def test_empty_column(self):
        r = assess(pd.DataFrame({"a": ["1", "2"], "b": ["", ""]}),
                   [ColumnSpec("a", "A", "integer"), ColumnSpec("b", "B", "empty")])
        assert r.issues[0].check_code == "empty_column"


class TestCleaning:
    def test_transform_pipeline_order_and_counts(self):
        df, cols = _frame()
        res = transform(df, cols, TransformConfig(missing_values="fill", required_columns=["id"]))
        steps = {s.rule: s for s in res.steps}
        assert steps["normalize_categories"].cells_changed == 1
        assert steps["remove_duplicates"].rows_affected == 1
        assert steps["reject_negative_values"].rows_affected == 1   # one negative row left after de-duplication
        assert res.rows_rejected == 1
        assert len(res.frame) == 4
        assert str(res.frame["qty"].dtype) == "Int64"
        assert res.frame["cat"].tolist().count("Unknown") == 1
        assert res.frame["qty"].isna().sum() == 1  # "x" could not be parsed; numeric fill defaults to none

    def test_numeric_fill_median(self):
        df = pd.DataFrame({"n": ["1", "", "3"]})
        res = transform(df, [ColumnSpec("n", "Score", "integer")], TransformConfig(numeric_fill="median"))
        assert res.frame["n"].tolist() == [1, 2, 3]

    def test_drop_rows_strategy(self):
        df = pd.DataFrame({"a": ["x", "", "z"], "b": ["1", "2", ""]})
        res = transform(df, [ColumnSpec("a", "A", "category"), ColumnSpec("b", "B", "integer")],
                        TransformConfig(missing_values="drop_rows"))
        assert len(res.frame) == 1 and res.rows_rejected == 2


def test_settings_read_comma_separated_origins_from_env_file(tmp_path):
    from app.core.config import Settings

    env = tmp_path / ".env"
    env.write_text("CORS_ORIGINS=http://localhost:5173, http://127.0.0.1:5173\nMAX_UPLOAD_MB=10\n")
    s = Settings(_env_file=env)
    assert s.cors_origin_list == ["http://localhost:5173", "http://127.0.0.1:5173"]
    assert s.max_upload_mb == 5  # real environment variables take precedence over .env (set to 5 in conftest)
