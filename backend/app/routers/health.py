"""Lebenszeichen und das, was die Oberflaeche vor der Anmeldung wissen muss."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from .. import __version__
from ..deps import DbSession, has_any_user
from ..services.settings_service import load_settings

router = APIRouter(tags=["health"])


@router.get("/api/health", summary="Liveness check")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/api/config", summary="Public facts the interface needs before sign-in")
def public_config(db: DbSession) -> dict[str, Any]:
    settings = load_settings(db)
    return {
        "version": __version__,
        "needs_setup": not has_any_user(db),
        "mail_configured": settings.mail_configured,
        "default_language": settings.default_language,
        "previews_enabled": settings.flag("source_deezer"),
        "requests_enabled": settings.lidarr_ready,
    }
