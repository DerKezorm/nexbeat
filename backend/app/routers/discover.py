"""Die Startseite: Empfehlungen und Trends."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..deps import CurrentUser, DbSession
from ..services import recommendations
from ..services.settings_service import load_settings

router = APIRouter(tags=["discover"])


@router.get("/api/discover", summary="Recommendation rows for the start page")
async def discover(user: CurrentUser, db: DbSession) -> dict[str, Any]:
    return await recommendations.home(db, load_settings(db), user)
