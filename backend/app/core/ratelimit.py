"""In-memory sliding-window rate limiting for the public demo.

Limits are per client IP and per rule. State lives in process memory, so with several
workers each worker counts separately (documented limitation; a shared store such as Redis
would be needed for exact global limits).
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    name: str
    methods: frozenset[str]
    path: re.Pattern[str]
    limit: int
    window_s: int
    description: str


RULES: tuple[Rule, ...] = (
    Rule("uploads", frozenset({"POST"}), re.compile(r"^/api/datasets$"), 10, 3600, "10 uploads per hour"),
    Rule("runs", frozenset({"POST"}), re.compile(r"^/api/pipelines/\d+/runs$"), 30, 3600, "30 pipeline runs per hour"),
    Rule("analyst", frozenset({"POST"}), re.compile(r"^/api/analyst/ask$"), 30, 600, "30 questions per 10 minutes"),
    Rule("reports", frozenset({"POST"}), re.compile(r"^/api/reports$"), 30, 3600, "30 reports per hour"),
    Rule("exports", frozenset({"GET"}), re.compile(r"^/api/(explorer/export|reports/\d+/download|datasets/\d+/download)$"),
         60, 3600, "60 downloads per hour"),
    Rule("writes", frozenset({"POST", "PUT", "PATCH", "DELETE"}), re.compile(r"^/api/"), 120, 600,
         "120 changes per 10 minutes"),
    Rule("all", frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"}), re.compile(r"^/api/(?!health)"), 600, 60,
         "600 requests per minute"),
)


class RateLimiter:
    def __init__(self, rules: tuple[Rule, ...] = RULES) -> None:
        self.rules = rules
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, method: str, path: str, key: str) -> tuple[Rule, int] | None:
        """Record the request; return (rule, retry_after_seconds) if any matching rule is exceeded."""
        now = time.monotonic()
        matched = [r for r in self.rules if method in r.methods and r.path.match(path)]
        with self._lock:
            for rule in matched:
                q = self._hits.setdefault((rule.name, key), deque())
                while q and now - q[0] >= rule.window_s:
                    q.popleft()
                if len(q) >= rule.limit:
                    return rule, max(1, int(rule.window_s - (now - q[0])) + 1)
            for rule in matched:
                self._hits[(rule.name, key)].append(now)
            if len(self._hits) > 50_000:  # bound memory under abuse
                self._hits.clear()
        return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()
