"""Anonymous visitor scope for the public demo.

There are no user accounts. In demo mode each browser gets a random, unguessable visitor ID
in an HttpOnly cookie. Data a visitor creates is tagged with that ID and is only visible to the
same browser; shared system data (owner_id NULL) is visible to everyone and read-only.

Outside demo mode the scope is permissive: everything is visible and editable, which is the
behaviour a single local user expects.
"""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy import or_, true

from app.core.config import get_settings
from app.core.errors import NotFound, ReadOnly

COOKIE_NAME = "databridge_visitor"
COOKIE_MAX_AGE = 30 * 24 * 3600
_VALID = re.compile(r"^[0-9a-f]{32}$")

READ_ONLY_MESSAGE = (
    "This is shared demonstration data and is read-only in the public demo. "
    "Create your own pipeline from it, or upload your own file, to make changes."
)


def new_visitor_id() -> str:
    return secrets.token_hex(16)


def valid_visitor_id(value: str | None) -> bool:
    return bool(value and _VALID.match(value))


@dataclass(frozen=True)
class Scope:
    demo: bool
    visitor_id: str | None

    @property
    def owner_for_new(self) -> str | None:
        return self.visitor_id if self.demo else None

    def can_see(self, owner_id: str | None) -> bool:
        return not self.demo or owner_id is None or owner_id == self.visitor_id

    def can_modify(self, owner_id: str | None) -> bool:
        return not self.demo or (owner_id is not None and owner_id == self.visitor_id)

    def read_only(self, owner_id: str | None) -> bool:
        return not self.can_modify(owner_id)

    def visible(self, column: Any) -> Any:
        """SQL condition: rows of `column`'s table that this scope may see."""
        if not self.demo:
            return true()
        return or_(column.is_(None), column == self.visitor_id)

    def ensure_visible(self, owner_id: str | None, what: str) -> None:
        if not self.can_see(owner_id):
            raise NotFound(f"{what} does not exist")  # 404, not 403: don't reveal other visitors' data

    def ensure_modifiable(self, owner_id: str | None, what: str) -> None:
        self.ensure_visible(owner_id, what)
        if not self.can_modify(owner_id):
            raise ReadOnly(READ_ONLY_MESSAGE)


SYSTEM_SCOPE = Scope(demo=False, visitor_id=None)


def get_scope(request: Request) -> Scope:
    if not get_settings().demo_mode:
        return SYSTEM_SCOPE
    return Scope(demo=True, visitor_id=getattr(request.state, "visitor_id", None))


ScopeDep = Annotated[Scope, Depends(get_scope)]
