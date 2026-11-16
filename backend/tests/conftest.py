"""Test configuration.

By default tests run against a temporary SQLite database. Set TEST_DATABASE_URL to run the
same suite against PostgreSQL, e.g.
    TEST_DATABASE_URL=postgresql+psycopg://databridge:YOUR_PASSWORD@localhost:5432/databridge_test pytest
The schema is created with the real Alembic migrations, so migrations are tested too.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="databridge-test-"))
_DB_URL = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ.update({
    "DATABASE_URL": _DB_URL,
    "DATA_DIR": str(_TMP / "data"),
    "ENVIRONMENT": "test",
    "AI_PROVIDER": "none",
    "LOG_LEVEL": "WARNING",
    "MAX_UPLOAD_MB": "5",
})

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402

from app import models  # noqa: E402,F401  (registers tables on Base.metadata so drop_all sees them)
from app.core.config import get_settings  # noqa: E402
from app.db import Base, get_engine, session_factory  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
SAMPLE_CSV = BACKEND.parent / "sample_data" / "retail_sales_sample.csv"


def _migrate() -> None:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    engine = get_engine()
    with engine.begin() as conn:
        for name in inspect(conn).get_table_names():
            if name.startswith(("stg_", "prc_")):
                conn.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def _database():
    get_settings.cache_clear()
    _migrate()
    yield
    get_engine().dispose()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(autouse=True)
def clean_db():
    """Each test starts from an empty schema (metadata rows and generated row tables removed)."""
    yield
    from app.services.explorer import _cached_stats

    _cached_stats.cache_clear()
    engine = get_engine()
    with engine.begin() as conn:
        for name in inspect(conn).get_table_names():
            if name.startswith(("stg_", "prc_")):
                conn.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture
def client():
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def session():
    s = session_factory()()
    yield s
    s.close()


@pytest.fixture
def sample_dataset(client):
    res = client.post("/api/datasets/sample")
    assert res.status_code == 201, res.text
    return res.json()


def upload(client, name: str, content: bytes, content_type: str = "text/csv"):
    return client.post("/api/datasets", files={"file": (name, content, content_type)})
