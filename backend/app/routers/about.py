"""Die Seite "Ueber nexbeat": Fassung, Herkunft, Lizenz, und fuer Admins der Stand der Update-Pruefung."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from .. import __version__
from ..deps import AdminUser, CurrentUser, DbSession
from ..services import updates
from ..services.settings_service import load_settings

router = APIRouter(prefix="/api/about", tags=["about"])


class UpdateOut(BaseModel):
    enabled: bool
    latest: str | None
    available: bool
    checked_at: datetime | None


class AboutOut(BaseModel):
    version: str
    repo_url: str
    releases_url: str
    license: str = "AGPL-3.0-or-later"
    #: Nur fuer Admins, sonst ``null``: Nutzer sehen keinen Update-Hinweis.
    update: UpdateOut | None


async def _about(db: Any, is_admin: bool, *, force: bool) -> AboutOut:
    update = None
    if is_admin:
        enabled = load_settings(db).flag("update_check")
        state = await updates.status(enabled=enabled, force=force)
        update = UpdateOut(enabled=enabled, latest=state.latest, available=state.available, checked_at=state.checked_at)
    return AboutOut(version=__version__, repo_url=updates.REPO_URL, releases_url=updates.RELEASES_URL, update=update)


@router.get("", response_model=AboutOut, summary="Version, origin and, for administrators, the update state")
async def about(user: CurrentUser, db: DbSession) -> AboutOut:
    return await _about(db, user.is_admin, force=False)


@router.post("/check", response_model=AboutOut, summary="Ask GitHub for a newer version now")
async def check_now(_admin: AdminUser, db: DbSession) -> AboutOut:
    return await _about(db, True, force=True)
