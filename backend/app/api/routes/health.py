from __future__ import annotations

import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.db import get_engine

router = APIRouter(tags=["health"])
_STARTED = time.time()


@router.get("/health")
def liveness() -> dict:
    """Liveness: the process is up. Cheap enough for frequent uptime monitors."""
    return {"status": "ok", "uptime_s": int(time.time() - _STARTED)}


@router.get("/health/ready")
def readiness() -> JSONResponse:
    """Readiness: the database answers a query."""
    started = time.perf_counter()
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db = {"status": "ok", "latency_ms": round((time.perf_counter() - started) * 1000, 1)}
        code = 200
    except Exception as exc:  # pragma: no cover - exercised manually
        db = {"status": "error", "error": type(exc).__name__}
        code = 503
    s = get_settings()
    return JSONResponse(status_code=code, content={
        "status": "ok" if code == 200 else "degraded",
        "database": {**db, "engine": "sqlite" if s.is_sqlite else "postgresql"},
        "environment": s.environment,
    })
