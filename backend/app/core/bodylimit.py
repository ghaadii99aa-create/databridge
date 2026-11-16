"""ASGI middleware that rejects oversized request bodies before they are buffered.

Multipart uploads are otherwise spooled to disk in full before the endpoint runs, so the
size limit must also be enforced at the transport level: first from Content-Length, then by
counting bytes as they arrive (for chunked requests).
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Callable

UPLOAD_PATH = "/api/datasets"
JSON_LIMIT = 1024 * 1024  # 1 MB for every other API request


class _TooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app: Any, upload_limit: Callable[[], int]) -> None:
        self.app = app
        self.upload_limit = upload_limit

    def _limit_for(self, scope: dict) -> int:
        if scope.get("method") == "POST" and scope.get("path") == UPLOAD_PATH:
            return self.upload_limit() + 256 * 1024  # multipart envelope overhead
        return JSON_LIMIT

    async def _reject(self, send: Callable, limit: int, scope: dict | None = None) -> None:
        # Same error shape as every other API error (see app/main.py).
        rid = uuid.uuid4().hex[:12]
        if limit == JSON_LIMIT and (scope or {}).get("path") != UPLOAD_PATH:
            error = {"code": "request_too_large", "message": "The request body is larger than the 1 MB limit.",
                     "details": {"limit_bytes": limit}}
        else:
            mb = self.upload_limit() // (1024 * 1024)
            error = {"code": "file_too_large", "message": f"The file is larger than the {mb} MB limit.",
                     "details": {"limit_mb": mb}}
        body = json.dumps({"error": error, "request_id": rid}, separators=(",", ":")).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                                (b"x-request-id", rid.encode())]})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http" or scope.get("method") in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        limit = self._limit_for(scope)
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await self._reject(send, limit, scope)
            return

        received = 0
        exceeded = False
        replaced = False

        async def counting_receive() -> dict:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    raise _TooLarge()
            return message

        async def guarded_send(message: dict) -> None:
            # The framework converts errors raised while reading the body into its own 400/500,
            # so when the limit was crossed we replace whatever response it produces.
            nonlocal replaced
            if exceeded:
                if message["type"] == "http.response.start" and not replaced:
                    replaced = True
                    await self._reject(send, limit, scope)
                return
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except _TooLarge:
            if not replaced:
                await self._reject(send, limit, scope)
