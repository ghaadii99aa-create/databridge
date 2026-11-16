"""FastAPI application factory."""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import data, datasets, health, overview, pipelines
from app.core.config import get_settings
from app.core.errors import DomainError
from app.core.logging import configure_logging, request_id_var
from app.core.bodylimit import BodySizeLimitMiddleware
from app.core.ratelimit import limiter
from app.core.storage import ensure_dirs
from app.core.visitor import COOKIE_MAX_AGE, COOKIE_NAME, new_visitor_id, valid_visitor_id

log = logging.getLogger("databridge")

SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
}
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self'; "
       "script-src 'self'; connect-src 'self'; frame-ancestors 'none'")


def _error(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={
        "error": {"code": code, "message": message, "details": details or {}},
        "request_id": request_id_var.get(),
    })


def create_app() -> BodySizeLimitMiddleware:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    ensure_dirs(settings.data_dir, settings.upload_dir, settings.report_dir)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        from app.services.etl import recover_interrupted_runs
        try:
            n = recover_interrupted_runs()
            if n:
                log.warning("marked %s interrupted run(s) as failed", n)
        except Exception:  # database may not be migrated yet
            log.exception("could not check for interrupted runs (has `alembic upgrade head` been run?)")
        scheduler = None
        if settings.demo_mode:
            from app.db import session_factory
            from app.services import demo
            try:
                with session_factory()() as session:
                    log.info("demo seed: %s", demo.seed(session))
            except Exception:
                log.exception("demo seeding failed")
            scheduler = demo.CleanupScheduler()
            scheduler.start()
        yield
        if scheduler:
            scheduler.stop()

    app = FastAPI(
        lifespan=lifespan,
        title="DataBridge API",
        version="1.0.0",
        description="Data ingestion, quality assessment, ETL and analytics.",
        docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json",
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id", "")[:64] or uuid.uuid4().hex[:12]
        token = request_id_var.set(rid)
        started = time.perf_counter()
        path = request.url.path
        new_cookie = None
        try:
            if settings.rate_limit_enabled and path.startswith("/api"):
                client = request.client.host if request.client else "unknown"
                hit = limiter.check(request.method, path, client)
                if hit:
                    rule, retry_after = hit
                    response = _error(429, "rate_limited",
                                      f"Too many requests ({rule.description}). Try again in {retry_after} seconds.",
                                      {"rule": rule.name, "retry_after_seconds": retry_after})
                    response.headers["retry-after"] = str(retry_after)
                    response.headers["x-request-id"] = rid
                    return response
            if settings.demo_mode:
                visitor = request.cookies.get(COOKIE_NAME)
                if not valid_visitor_id(visitor):
                    visitor = new_cookie = new_visitor_id()
                request.state.visitor_id = visitor
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        if new_cookie:
            response.set_cookie(COOKIE_NAME, new_cookie, max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax",
                                secure=bool(settings.cookie_secure), path="/")
        elapsed = (time.perf_counter() - started) * 1000
        response.headers["x-request-id"] = rid
        # Security headers (also set by nginx in the compose stack; here they cover single-service deploys)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers.setdefault("content-security-policy", CSP)
        response.headers["server-timing"] = f"app;dur={elapsed:.1f}"
        if request.url.path.startswith("/api") and not request.url.path.startswith("/api/health"):
            log.info("%s %s %s %.1fms", request.method, request.url.path, response.status_code, elapsed)
        return response

    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["content-type", "x-request-id"],
        expose_headers=["x-request-id", "content-disposition"],
    )

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError):
        return _error(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        fields = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]} for e in exc.errors()]
        return _error(422, "validation_failed", "The request is invalid.", {"fields": fields})

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception):
        log.exception("unhandled error")
        return _error(500, "internal_error", "An unexpected error occurred. Quote the request ID when reporting it.")

    for router in (health.router, overview.router, datasets.router, datasets.quality_router, pipelines.router, data.router):
        app.include_router(router, prefix="/api")

    dist = settings.frontend_dist
    if dist and Path(dist).joinpath("index.html").exists():
        _mount_frontend(app, Path(dist))
    # Outermost layer, so oversized bodies are cut off before any parsing happens.
    return BodySizeLimitMiddleware(app, lambda: get_settings().max_upload_bytes)


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built SPA: hashed assets are cached for a year, index.html is never cached."""
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    index = dist / "index.html"

    @app.middleware("http")
    async def cache_headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/assets/"):
            response.headers["cache-control"] = "public, max-age=31536000, immutable"
        return response

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index, headers={"cache-control": "no-cache"})


app = create_app()
