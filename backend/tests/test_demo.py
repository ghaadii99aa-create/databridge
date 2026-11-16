"""Public demo mode: shared read-only sample, per-visitor isolation, limits, rate limiting, cleanup."""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text

from app.core.config import get_settings
from app.core.ratelimit import limiter
from app.core.visitor import COOKIE_NAME
from app.db import get_engine
from app.models import AppSetting, Dataset, Pipeline, Report
from tests.conftest import upload
from tests.test_api import wait_for_run

SMALL_CSV = b"id,city,amount\n1,Riyadh,10\n2,Jeddah,20\n3,Dammam,30\n"


@pytest.fixture
def demo_env(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.delenv("MAX_UPLOAD_MB", raising=False)  # demo defaults: 10 MB, 50,000 rows
    get_settings.cache_clear()
    limiter.reset()
    yield get_settings()
    get_settings.cache_clear()
    limiter.reset()


@pytest.fixture
def demo_app(demo_env):
    from app.main import create_app
    return create_app()


@pytest.fixture
def visitor_a(demo_app):
    with TestClient(demo_app) as c:
        yield c


@pytest.fixture
def visitor_b(demo_app, visitor_a):  # visitor_a's start-up has already seeded the shared data
    with TestClient(demo_app) as c:
        yield c


def _sample(client) -> dict:
    samples = [d for d in client.get("/api/datasets").json() if d["is_sample"]]
    assert len(samples) == 1
    return samples[0]


# ---- settings & seeding --------------------------------------------------------------

def test_demo_settings_enforce_limits(demo_env):
    assert demo_env.max_upload_mb == 10
    assert demo_env.max_rows == 50_000
    assert demo_env.rate_limit_enabled is True


def test_first_visit_is_populated(visitor_a):
    res = visitor_a.get("/api/overview")
    assert res.status_code == 200
    body = res.json()
    assert body["demo"]["demo_mode"] is True
    assert body["demo"]["max_upload_mb"] == 10 and body["demo"]["max_rows"] == 50_000
    sample = _sample(visitor_a)
    assert sample["status"] == "ready" and sample["read_only"] is True
    assert "SAMPLE" in sample["name"] and "not real business data" in sample["description"]
    pipelines = visitor_a.get("/api/pipelines").json()
    assert len(pipelines) == 1 and pipelines[0]["read_only"] is True
    assert pipelines[0]["last_run"]["status"] == "succeeded"
    reports = visitor_a.get("/api/reports").json()
    assert len(reports) == 1 and reports[0]["read_only"] is True
    assert visitor_a.get(f"/api/reports/{reports[0]['id']}/download").status_code == 200
    # explorer, analytics and quality work on the shared data without uploading anything
    sources = visitor_a.get("/api/explorer/sources").json()
    assert {s["kind"] for s in sources} == {"raw", "processed"}
    src = f"raw-{sample['id']}"
    assert visitor_a.get("/api/explorer/rows", params={"source": src}).json()["total"] == sample["row_count"]
    assert visitor_a.get(f"/api/datasets/{sample['id']}/quality").json()["score"] is not None
    assert visitor_a.get("/api/analytics/suitability", params={"source": src}).status_code == 200


def test_cookie_flags(visitor_a):
    res = visitor_a.get("/api/overview")
    cookie = res.headers.get("set-cookie", "")
    assert COOKIE_NAME in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    # the same browser keeps its ID
    assert COOKIE_NAME not in visitor_a.get("/api/overview").headers.get("set-cookie", "")


def test_seeding_is_idempotent(demo_app, visitor_a, session):
    from app.services import demo
    assert demo.seed(session)["seeded"] is False
    with TestClient(demo_app):  # another start-up
        pass
    assert session.scalar(select(text("count(*)")).select_from(Dataset).where(Dataset.is_sample.is_(True))) == 1
    assert len(session.scalars(select(Pipeline).where(Pipeline.owner_id.is_(None))).all()) == 1


def test_load_sample_returns_shared_copy(visitor_a):
    sample = _sample(visitor_a)
    res = visitor_a.post("/api/datasets/sample")
    assert res.status_code == 200 and res.json()["id"] == sample["id"]
    assert len(visitor_a.get("/api/datasets").json()) == 1


# ---- protection of shared data -------------------------------------------------------

def test_sample_cannot_be_deleted_or_modified(visitor_a, session):
    sample = _sample(visitor_a)
    pipeline = visitor_a.get("/api/pipelines").json()[0]
    report = visitor_a.get("/api/reports").json()[0]
    checks = [
        visitor_a.delete(f"/api/datasets/{sample['id']}"),
        visitor_a.patch(f"/api/datasets/{sample['id']}", json={"name": "hacked", "description": None}),
        visitor_a.post(f"/api/datasets/{sample['id']}/quality"),
        visitor_a.delete(f"/api/pipelines/{pipeline['id']}"),
        visitor_a.put(f"/api/pipelines/{pipeline['id']}", json={"name": "x", "description": None, "config": pipeline["config"]}),
        visitor_a.post(f"/api/pipelines/{pipeline['id']}/runs"),
        visitor_a.delete(f"/api/reports/{report['id']}"),
    ]
    for res in checks:
        assert res.status_code == 403, res.text
        assert res.json()["error"]["code"] == "read_only"
    session.expire_all()
    ds = session.get(Dataset, sample["id"])
    assert ds.name == sample["name"] and ds.status == "ready"
    assert inspect(get_engine()).has_table(ds.staging_table)


def test_visitor_can_build_own_pipeline_on_sample(visitor_a, visitor_b):
    sample = _sample(visitor_a)
    rules = visitor_a.get("/api/pipelines/rules").json()["defaults"]
    res = visitor_a.post("/api/pipelines", json={"dataset_id": sample["id"], "name": "Mine", "description": None, "config": rules})
    assert res.status_code == 201 and res.json()["read_only"] is False
    run = visitor_a.post(f"/api/pipelines/{res.json()['id']}/runs").json()
    assert wait_for_run(visitor_a, run["id"])["status"] == "succeeded"
    # visitor B sees only the shared pipeline, not A's pipeline, run or output
    assert [p["name"] for p in visitor_b.get("/api/pipelines").json()] == ["Clean retail sales (SAMPLE)"]
    assert visitor_b.get(f"/api/runs/{run['id']}").status_code == 404
    assert visitor_b.get("/api/explorer/rows", params={"source": f"processed-{run['id']}"}).status_code == 404
    assert all(s["id"] != f"processed-{run['id']}" for s in visitor_b.get("/api/explorer/sources").json())
    # and the shared sample's quality history does not show A's run
    history_b = visitor_b.get(f"/api/datasets/{sample['id']}/quality/history").json()
    history_a = visitor_a.get(f"/api/datasets/{sample['id']}/quality/history").json()
    assert len(history_a) > len(history_b)


# ---- visitor isolation ---------------------------------------------------------------

def test_visitor_uploads_are_private(visitor_a, visitor_b):
    res = upload(visitor_a, "private.csv", SMALL_CSV)
    assert res.status_code == 201, res.text
    ds = res.json()
    assert ds["read_only"] is False
    did = ds["id"]

    assert did in [d["id"] for d in visitor_a.get("/api/datasets").json()]
    assert did not in [d["id"] for d in visitor_b.get("/api/datasets").json()]
    for path in (f"/api/datasets/{did}", f"/api/datasets/{did}/preview", f"/api/datasets/{did}/download",
                 f"/api/datasets/{did}/quality", f"/api/datasets/{did}/quality/history"):
        assert visitor_b.get(path).status_code == 404, path
    for path in ("/api/explorer/rows", "/api/explorer/stats", "/api/explorer/export", "/api/analytics/suitability"):
        assert visitor_b.get(path, params={"source": f"raw-{did}"}).status_code == 404, path
    assert visitor_b.post("/api/analyst/ask", json={"source": f"raw-{did}", "question": "What is in it?"}).status_code == 404
    assert visitor_b.post("/api/reports", json={"kind": "dataset_summary", "format": "csv", "dataset_id": did}).status_code == 404
    assert visitor_b.delete(f"/api/datasets/{did}").status_code == 404
    assert visitor_b.patch(f"/api/datasets/{did}", json={"name": "x", "description": None}).status_code == 404
    assessment_id = visitor_a.get(f"/api/datasets/{did}/quality").json()["id"]
    assert visitor_b.get(f"/api/quality/assessments/{assessment_id}").status_code == 404

    # A's report is private too
    rep = visitor_a.post("/api/reports", json={"kind": "dataset_summary", "format": "csv", "dataset_id": did}).json()
    assert visitor_b.get(f"/api/reports/{rep['id']}/download").status_code == 404
    assert rep["id"] not in [r["id"] for r in visitor_b.get("/api/reports").json()]

    # overview counts only shared data + own data
    assert visitor_a.get("/api/overview").json()["datasets"]["total"] == 2
    assert visitor_b.get("/api/overview").json()["datasets"]["total"] == 1

    # the owner can delete their own upload
    assert visitor_a.delete(f"/api/datasets/{did}").status_code == 204


def test_forged_cookie_gets_new_identity(demo_app, visitor_a):
    did = upload(visitor_a, "private.csv", SMALL_CSV).json()["id"]
    with TestClient(demo_app, cookies={COOKIE_NAME: "not-a-valid-id"}) as other:
        res = other.get(f"/api/datasets/{did}")
        assert res.status_code == 404
        assert COOKIE_NAME in res.headers.get("set-cookie", "")  # a fresh, valid ID replaces the forged one


# ---- limits ---------------------------------------------------------------------------

def _csv_rows(n: int) -> bytes:
    return b"id,value\n" + b"".join(b"%d,%d\n" % (i, i % 97) for i in range(n))


def test_row_limit_is_enforced_server_side(visitor_a, session):
    before = session.scalar(select(text("count(*)")).select_from(Dataset))
    res = upload(visitor_a, "big.csv", _csv_rows(50_001))
    assert res.status_code == 413
    err = res.json()["error"]
    assert err["code"] == "limit_exceeded" and "50,001 rows" in err["message"] and "50,000" in err["message"]
    session.expire_all()
    assert session.scalar(select(text("count(*)")).select_from(Dataset)) == before  # nothing kept
    assert not list(get_settings().upload_dir.glob("*big*"))

    ok = upload(visitor_a, "exact.csv", _csv_rows(50_000))
    assert ok.status_code == 201 and ok.json()["row_count"] == 50_000


def test_file_size_limit_is_enforced_server_side(visitor_a):
    payload = b"id,text\n" + b"1," + b"x" * (10 * 1024 * 1024 + 10) + b"\n"
    res = upload(visitor_a, "huge.csv", payload)
    assert res.status_code == 413
    err = res.json()["error"]
    assert err["code"] == "file_too_large" and "10 MB" in err["message"] and res.json()["request_id"]
    assert len(visitor_a.get("/api/datasets").json()) == 1  # only the shared sample


def test_file_size_limit_without_content_length(demo_app):
    """A streamed (chunked) body without Content-Length is cut off once it crosses the limit."""
    from app.core.bodylimit import BodySizeLimitMiddleware
    assert isinstance(demo_app, BodySizeLimitMiddleware)
    import asyncio

    head = (b'--zz\r\nContent-Disposition: form-data; name="file"; filename="a.csv"\r\n'
            b"Content-Type: text/csv\r\n\r\n")
    chunks = [b"x" * (1024 * 1024)] * 12 + [head]  # popped from the end: head first
    sent: list[dict] = []

    async def receive():
        if chunks:
            return {"type": "http.request", "body": chunks.pop(), "more_body": bool(chunks)}
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": "/api/datasets", "raw_path": b"/api/datasets",
             "headers": [(b"content-type", b"multipart/form-data; boundary=zz")], "query_string": b"",
             "client": ("1.2.3.4", 1), "server": ("testserver", 80), "scheme": "http", "http_version": "1.1",
             "root_path": "", "state": {}}
    asyncio.run(demo_app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 413


def test_per_visitor_dataset_quota(visitor_a, demo_env):
    for i in range(demo_env.demo_max_datasets_per_visitor):
        assert upload(visitor_a, f"f{i}.csv", SMALL_CSV).status_code == 201
    res = upload(visitor_a, "one-more.csv", SMALL_CSV)
    assert res.status_code == 413 and "up to 5 uploaded datasets" in res.json()["error"]["message"]


def test_rate_limit_returns_429(visitor_a):
    for _ in range(10):
        assert upload(visitor_a, "notes.txt", b"hello", "text/plain").status_code in (400, 415, 422)
    res = upload(visitor_a, "notes.txt", b"hello", "text/plain")
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "rate_limited" and int(res.headers["retry-after"]) > 0
    assert visitor_a.get("/api/health").status_code == 200  # health checks are never limited


def test_invalid_input_is_rejected(visitor_a):
    assert visitor_a.get("/api/explorer/rows", params={"source": "raw-1; DROP TABLE datasets"}).status_code == 422
    assert visitor_a.get("/api/explorer/rows", params={"source": "raw-1", "page_size": 5000}).status_code == 422
    res = visitor_a.post("/api/analyst/ask", json={"source": f"raw-{_sample(visitor_a)['id']}", "question": "x" * 5000})
    assert res.status_code == 422
    res = visitor_a.post("/api/pipelines", content=b"{" * (2 * 1024 * 1024), headers={"content-type": "application/json"})
    assert res.status_code == 413 and res.json()["error"]["code"] == "request_too_large"


# ---- cleanup --------------------------------------------------------------------------

def test_cleanup_removes_only_expired_visitor_data(visitor_a, session):
    from app.services import demo

    settings = get_settings()
    sample = _sample(visitor_a)
    system_pipeline = visitor_a.get("/api/pipelines").json()[0]
    system_report = visitor_a.get("/api/reports").json()[0]

    did = upload(visitor_a, "temp.csv", SMALL_CSV).json()["id"]
    rules = visitor_a.get("/api/pipelines/rules").json()["defaults"]
    pid = visitor_a.post("/api/pipelines", json={"dataset_id": sample["id"], "name": "Temp", "description": None,
                                                 "config": rules}).json()["id"]
    run = visitor_a.post(f"/api/pipelines/{pid}/runs").json()
    wait_for_run(visitor_a, run["id"])
    rep = visitor_a.post("/api/reports", json={"kind": "dataset_summary", "format": "pdf", "dataset_id": did}).json()

    engine = get_engine()
    with engine.begin() as conn:  # an orphaned generated table and an unrelated table
        conn.execute(text('CREATE TABLE "stg_999999" (_row_id INTEGER PRIMARY KEY)'))
        conn.execute(text('CREATE TABLE "keep_me_table" (id INTEGER PRIMARY KEY)'))
    orphan = settings.upload_dir / "orphan-file.csv"
    orphan.write_text("x")
    old = time.time() - 2 * 3600
    os.utime(orphan, (old, old))
    fresh_orphan = settings.upload_dir / "uploading-now.csv"
    fresh_orphan.write_text("x")

    # nothing expires before the retention period; only orphans are removed (fresh files get a grace period)
    counts = demo.cleanup(session)
    assert counts["datasets"] == 0 and counts["pipelines"] == 0 and counts["reports"] == 0
    assert counts["tables"] == 1 and counts["files"] >= 1
    assert not orphan.exists() and fresh_orphan.exists()
    assert session.get(Dataset, did) is not None

    counts = demo.cleanup(session, now=datetime.now(timezone.utc) + timedelta(hours=settings.demo_retention_hours + 1))
    assert (counts["datasets"], counts["pipelines"], counts["reports"], counts["tables"], counts["errors"]) == (1, 1, 1, 0, 0)
    session.expire_all()
    assert session.get(Dataset, did) is None and session.get(Pipeline, pid) is None and session.get(Report, rep["id"]) is None

    # shared data and system tables are untouched
    ds = session.get(Dataset, sample["id"])
    assert ds is not None and ds.status == "ready"
    assert session.get(Pipeline, system_pipeline["id"]) is not None
    assert session.get(Report, system_report["id"]) is not None
    assert (settings.upload_dir / ds.stored_filename).exists()
    names = set(inspect(engine).get_table_names())
    assert {ds.staging_table, "alembic_version", "app_settings", "datasets", "keep_me_table"} <= names
    assert any(n.startswith("prc_") for n in names)  # the shared run's output
    assert (settings.report_dir / session.get(Report, system_report["id"]).stored_filename).exists()
    assert session.get(AppSetting, demo.LAST_CLEANUP) is not None
    with engine.begin() as conn:
        conn.execute(text('DROP TABLE "keep_me_table"'))

    # the demo still works after cleanup
    assert visitor_a.get("/api/explorer/rows", params={"source": f"raw-{sample['id']}"}).status_code == 200


def test_seed_restores_missing_sample(visitor_a, session):
    """If the shared sample ever disappears (e.g. manual database edits), the next pass restores it."""
    from app.services import demo, ingestion

    sample = _sample(visitor_a)
    ingestion.delete_dataset(session, sample["id"])
    assert demo.seed(session)["seeded"] is True
    assert _sample(visitor_a)["status"] == "ready"


def test_non_demo_mode_is_unchanged(client):
    """Local single-user mode keeps full control and sets no visitor cookie."""
    res = client.post("/api/datasets/sample")
    assert res.status_code == 201 and res.json()["read_only"] is False
    assert COOKIE_NAME not in res.headers.get("set-cookie", "")
    assert client.delete(f"/api/datasets/{res.json()['id']}").status_code == 204


def test_cli_cleanup(demo_env):
    from app import cli
    assert cli.main(["cleanup"]) == 0
