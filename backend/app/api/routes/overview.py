from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import SessionDep
from app.core.visitor import ScopeDep
from app.services.demo import demo_info
from app.services.overview import overview

router = APIRouter(tags=["overview"])


@router.get("/overview")
def get_overview(session: SessionDep, scope: ScopeDep) -> dict:
    return {**overview(session, scope), "demo": demo_info(session)}
