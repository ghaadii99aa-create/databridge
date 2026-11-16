"""API integration tests, including the full demonstration workflow."""
from __future__ import annotations

import io
import json
import time

import httpx
from openpyxl import Workbook
from sqlalchemy import inspect

from app.db import get_engine
from tests.conftest import upload

CSV = b"Order ID,Order Date,Region,Amount\nA1,2025-01-05,North,10.5\nA2,2025-01-06,south,20\nA3,,North,abc\n"


def xlsx_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["Product", "Units", "Price"])
    ws.append(["Pen", 3, 1.5])
    ws.append(["Book", 1, 12.0])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def wait_for_run(client, run_id: int, timeout: float = 30) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in ("succeeded", "failed"):
            return run
        time.sleep(0.1)
    raise AssertionError("run did not finish")


class TestHealth:
    def test_health_and_readiness(self, client):
        assert client.get("/api/health").json()["status"] == "ok"
        ready = client.get("/api/health/ready")
        assert ready.status_code == 200 and ready.json()["database"]["status"] == "ok"

    def test_errors_have_consistent_shape_and_request_id(self, client):
        res = client.get("/api/datasets/9999")
        body = res.json()
        assert res.status_code == 404 and body["error"]["code"] == "not_found"
        assert body["request_id"] == res.headers["x-request-id"]


class TestIngestion:
    def test_csv_upload_profiles_columns(self, client):
        res = upload(client, "orders.csv", CSV)
        assert res.status_code == 201, res.text
        ds = res.json()
        assert ds["status"] == "ready" and ds["row_count"] == 3 and ds["column_count"] == 4
        types = {c["name"]: c["inferred_type"] for c in ds["columns"]}
        assert types["Order ID"] == "identifier"
        assert ds["latest_quality"]["total_issues"] > 0
        preview = client.get(f"/api/datasets/{ds['id']}/preview").json()
        assert len(preview["rows"]) == 3 and preview["rows"][2]["amount"] == "abc"  # raw kept as-is

    def test_xlsx_upload(self, client):
        res = upload(client, "products.xlsx", xlsx_bytes(),
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        ds = res.json()
        assert res.status_code == 201 and ds["status"] == "ready" and ds["file_format"] == "xlsx"
        assert ds["sheet_name"] == "Sheet" and ds["row_count"] == 2

    def test_semicolon_and_cp1252_csv(self, client):
        content = "Name;Price\nCafé;3,5\nThé;2\n".encode("cp1252")
        ds = upload(client, "eu.csv", content).json()
        assert ds["status"] == "ready" and ds["delimiter"] == ";" and ds["encoding"] == "cp1252"

    def test_rejects_unsupported_extension(self, client):
        res = upload(client, "malware.exe", b"MZ...")
        assert res.status_code == 415 and res.json()["error"]["code"] == "unsupported_file"

    def test_rejects_fake_xlsx(self, client):
        res = upload(client, "fake.xlsx", b"just,some,text\n1,2,3")
        assert res.status_code == 415

    def test_rejects_binary_csv(self, client):
        assert upload(client, "bin.csv", b"a,b\x00\x01\x02").status_code == 415

    def test_rejects_oversized_file(self, client):
        big = b"a,b\n" + b"1,2\n" * (6 * 1024 * 1024 // 4)
        res = upload(client, "big.csv", big)
        assert res.status_code == 413

    def test_empty_file(self, client):
        assert upload(client, "empty.csv", b"").status_code == 422

    def test_header_only_is_recorded_as_failed(self, client):
        res = upload(client, "header.csv", b"a,b,c\n")
        ds = res.json()
        assert res.status_code == 201 and ds["status"] == "failed" and "no data rows" in ds["error_message"]

    def test_path_traversal_filename_is_not_used(self, client):
        ds = upload(client, "../../etc/passwd.csv", CSV).json()
        assert ds["original_filename"] == "passwd.csv"

    def test_delete_removes_staging_table(self, client):
        ds = upload(client, "orders.csv", CSV).json()
        assert inspect(get_engine()).has_table(f"stg_{ds['id']}")
        assert client.delete(f"/api/datasets/{ds['id']}").status_code == 204
        assert not inspect(get_engine()).has_table(f"stg_{ds['id']}")
        assert client.get(f"/api/datasets/{ds['id']}").status_code == 404


class TestDemonstrationWorkflow:
    """The documented end-to-end scenario: upload → inspect → quality → clean/ETL → explore → charts → report."""

    def test_end_to_end(self, client, sample_dataset):
        ds = sample_dataset
        assert ds["is_sample"] and ds["status"] == "ready" and ds["row_count"] == 2448

        quality = client.get(f"/api/datasets/{ds['id']}/quality").json()
        checks = {i["check_code"] for i in quality["issues"]}
        assert {"duplicate_rows", "missing_values", "inconsistent_categories", "mixed_date_formats",
                "unexpected_negative", "invalid_type", "whitespace"} <= checks

        pipeline = client.post("/api/pipelines", json={
            "dataset_id": ds["id"], "name": "Clean retail sales",
            "config": {"required_columns": ["transaction_id", "transaction_date"], "missing_values": "fill"},
        })
        assert pipeline.status_code == 201, pipeline.text
        run = client.post(f"/api/pipelines/{pipeline.json()['id']}/runs")
        assert run.status_code == 202
        run = wait_for_run(client, run.json()["id"])
        assert run["status"] == "succeeded", run
        assert run["rows_extracted"] == 2448
        assert run["rows_loaded"] + run["rows_rejected"] + 48 == 2448  # 48 duplicates removed
        assert set(run["stage_timings_ms"]) == {"extract", "validate", "transform", "load", "profile"}
        assert run["quality_after"]["score"] > run["quality_before"]["score"]
        assert inspect(get_engine()).has_table(run["output"]["table_name"])

        source = f"processed-{run['id']}"
        page = client.get("/api/explorer/rows", params={
            "source": source, "page_size": 25, "sort": "revenue_sar", "order": "desc",
            "filters": json.dumps([{"column": "region", "op": "eq", "value": "central"},
                                   {"column": "quantity", "op": "gte", "value": "2"}])}).json()
        assert page["total"] > 0 and len(page["rows"]) <= 25
        assert all(r["region"] == "Central" and r["quantity"] >= 2 for r in page["rows"])
        revenues = [r["revenue_sar"] for r in page["rows"] if r["revenue_sar"] is not None]
        assert revenues == sorted(revenues, reverse=True)

        stats = client.get("/api/explorer/stats", params={"source": source}).json()
        cats = next(c for c in stats["columns"] if c["key"] == "product_category")
        assert cats["distinct"] == 6  # variants normalised to the six real categories

        comparison = client.get(f"/api/runs/{run['id']}/comparison").json()
        assert comparison["raw_rows"] == 2448 and comparison["processed_rows"] == run["rows_loaded"]

        dist = client.get("/api/analytics/distribution", params={"source": source, "column": "unit_price_sar"}).json()
        assert sum(b["count"] for b in dist["bins"]) == dist["count"]
        cat = client.get("/api/analytics/category", params={"source": source, "column": "region",
                                                            "measure": "revenue_sar", "agg": "sum"}).json()
        assert abs(sum(i["value"] for i in cat["items"]) - cat["total"]) < 0.01
        ts = client.get("/api/analytics/timeseries", params={"source": source, "column": "transaction_date"}).json()
        assert ts["freq"] == "M" and sum(p["value"] for p in ts["points"]) == run["rows_loaded"]
        comp = client.get("/api/analytics/comparison", params={"source": source, "column": "region",
                                                               "split": "customer_segment"}).json()
        assert comp["rows"] and comp["series"]

        export = client.get("/api/explorer/export", params={"source": source})
        assert export.status_code == 200
        lines = export.content.decode("utf-8-sig").strip().splitlines()
        assert len(lines) == run["rows_loaded"] + 1

        for kind, extra in (("dataset_summary", {"dataset_id": ds["id"]}), ("quality", {"dataset_id": ds["id"]}),
                            ("pipeline_run", {"run_id": run["id"]})):
            for fmt in ("pdf", "csv"):
                rep = client.post("/api/reports", json={"kind": kind, "format": fmt, **extra})
                assert rep.status_code == 201, rep.text
                dl = client.get(f"/api/reports/{rep.json()['id']}/download")
                assert dl.status_code == 200
                if fmt == "pdf":
                    assert dl.content.startswith(b"%PDF")
        assert len(client.get("/api/reports").json()) == 6

        ov = client.get("/api/overview").json()
        assert ov["datasets"]["total"] == 1 and ov["runs"]["succeeded"] == 1
        assert ov["records"]["loaded"] == run["rows_loaded"]
        assert ov["quality"]["score"] == run["quality_after"]["score"]

    def test_failed_run_is_recorded_and_cleaned_up(self, client, sample_dataset):
        pid = client.post("/api/pipelines", json={"dataset_id": sample_dataset["id"], "name": "Will fail"}).json()["id"]
        with get_engine().begin() as conn:  # simulate a lost staging table
            conn.exec_driver_sql(f'DROP TABLE "stg_{sample_dataset["id"]}"')
        run = wait_for_run(client, client.post(f"/api/pipelines/{pid}/runs").json()["id"])
        assert run["status"] == "failed" and run["error_stage"] == "extract"
        assert any(log["level"] == "error" for log in run["logs"])
        assert not inspect(get_engine()).has_table(f"prc_{run['id']}")
        assert client.get("/api/overview").json()["runs"]["failed"] == 1

    def test_pipeline_rejects_unknown_columns(self, client, sample_dataset):
        res = client.post("/api/pipelines", json={"dataset_id": sample_dataset["id"], "name": "x",
                                                  "config": {"required_columns": ["nope"]}})
        assert res.status_code == 422 and res.json()["error"]["details"]["columns"] == ["nope"]


class TestExplorerSafety:
    def test_unknown_columns_and_injection_are_rejected(self, client, sample_dataset):
        src = f"raw-{sample_dataset['id']}"
        bad_sort = client.get("/api/explorer/rows", params={"source": src, "sort": "region; DROP TABLE datasets"})
        assert bad_sort.status_code == 422
        bad_filter = client.get("/api/explorer/rows", params={
            "source": src, "filters": json.dumps([{"column": "x\" OR 1=1 --", "op": "eq", "value": "1"}])})
        assert bad_filter.status_code == 422
        assert client.get("/api/datasets").status_code == 200

    def test_raw_text_columns_reject_numeric_operators(self, client, sample_dataset):
        res = client.get("/api/explorer/rows", params={
            "source": f"raw-{sample_dataset['id']}",
            "filters": json.dumps([{"column": "quantity", "op": "gt", "value": "3"}])})
        assert res.status_code == 422 and "processed source" in res.json()["error"]["message"]

    def test_search_treats_wildcards_literally(self, client, sample_dataset):
        res = client.get("/api/explorer/rows", params={"source": f"raw-{sample_dataset['id']}", "search": "%"}).json()
        assert res["total"] == 0

    def test_csv_export_neutralises_formulas(self, client):
        ds = upload(client, "f.csv", b"name,v\n=HYPERLINK(\"http://x\"),1\n-5,2\n").json()
        text = client.get("/api/explorer/export", params={"source": f"raw-{ds['id']}"}).content.decode("utf-8-sig")
        assert "'=HYPERLINK" in text and "\n-5," in text

    def test_charts_explain_unsuitable_columns(self, client, sample_dataset):
        res = client.get("/api/analytics/distribution", params={"source": f"raw-{sample_dataset['id']}", "column": "region"})
        assert res.status_code == 422 and "not numeric" in res.json()["error"]["message"]


class TestAnalyst:
    def test_without_provider_returns_statistical_answer_only(self, client, sample_dataset):
        status = client.get("/api/analyst/status").json()
        assert status["configured"] is False
        res = client.post("/api/analyst/ask", json={"source": f"raw-{sample_dataset['id']}",
                                                    "question": "Which columns have the most missing values?"}).json()
        assert res["ai"] is None and res["shared_profile"] is None
        titles = [f["title"] for f in res["statistical"]["findings"]]
        assert "Columns with missing values" in titles
        assert "Customer Segment" in res["statistical"]["findings"][0]["detail"]

    def test_with_mocked_provider(self, client, sample_dataset, monkeypatch):
        from app.core import config
        from app.services.ai import analyst

        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            seen["key"] = request.headers.get("x-api-key")
            return httpx.Response(200, json={"model": "test-model", "content": [{"type": "text", "text": "Mocked insight."}],
                                             "usage": {"input_tokens": 10, "output_tokens": 3}})

        monkeypatch.setenv("AI_PROVIDER", "anthropic")
        monkeypatch.setenv("AI_API_KEY", "test-key")
        monkeypatch.setenv("AI_MODEL", "test-model")
        config.get_settings.cache_clear()
        try:
            from app.db import session_factory
            with session_factory()() as s:
                out = analyst.ask(s, f"raw-{sample_dataset['id']}", "Summarize this dataset",
                                  transport=httpx.MockTransport(handler))
            assert out["ai"]["text"] == "Mocked insight." and out["ai"]["error"] is None
            assert out["statistical"]["findings"]  # fallback is always present
            assert seen["key"] == "test-key"
            prompt = seen["body"]["messages"][0]["content"]
            assert '"sample_rows"' in prompt and prompt.count("TXN-") <= 5  # only the profile is shared
            assert out["shared_profile"]["rows"] == 2448

            def failing(request):
                return httpx.Response(401, json={"error": "bad key"})
            with session_factory()() as s:
                out = analyst.ask(s, f"raw-{sample_dataset['id']}", "patterns?", transport=httpx.MockTransport(failing))
            assert out["ai"]["text"] is None and "rejected the API key" in out["ai"]["error"]
            assert out["statistical"]["findings"]
        finally:
            monkeypatch.undo()
            config.get_settings.cache_clear()


class TestOverview:
    def test_empty_state(self, client):
        ov = client.get("/api/overview").json()
        assert ov["datasets"]["total"] == 0 and ov["quality"]["score"] is None and ov["activity"] == []


class TestSorting:
    def test_empty_values_sort_last_in_both_directions(self, client):
        content = b"id,amount,region\nr1,5,North\nr2,,North\nr3,9,South\nr4,1,South\n"
        ds = upload(client, "s.csv", content).json()
        pid = client.post("/api/pipelines", json={"dataset_id": ds["id"], "name": "p",
                                                  "config": {"missing_values": "keep"}}).json()["id"]
        run = wait_for_run(client, client.post(f"/api/pipelines/{pid}/runs").json()["id"])
        for order, expected in (("desc", [9, 5, 1, None]), ("asc", [1, 5, 9, None])):
            rows = client.get("/api/explorer/rows", params={"source": f"processed-{run['id']}", "sort": "amount",
                                                            "order": order}).json()["rows"]
            assert [r["amount"] for r in rows] == expected


def test_security_headers_present(client):
    res = client.get("/api/health")
    assert res.headers["x-content-type-options"] == "nosniff" and res.headers["x-frame-options"] == "DENY"


def test_timestamps_are_serialised_with_utc_offset(client):
    ds = upload(client, "t.csv", b"a,b\n1,2\n").json()
    assert ds["created_at"].endswith(("Z", "+00:00"))
    run_free = client.get("/api/overview").json()["latest_datasets"][0]["created_at"]
    assert run_free.endswith(("Z", "+00:00"))
