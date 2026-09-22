"""Erst-Einrichtung: Das erste Konto wird Admin."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from .. import __version__
from ..deps import DbSession, has_any_user
from ..meldungen import fehler
from ..models import Role, User, utcnow
from ..schemas import SetupIn, TokenPair
from ..security import hash_password
from ..services import sitzung
from ..services.mail import valid_address
from ..services.settings_service import save_settings
from ..services.tokens import normalize_email

router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("/status", summary="Whether the first administrator still has to be created")
def setup_status(db: DbSession) -> dict[str, bool]:
    return {"needs_setup": not has_any_user(db)}


@router.post("/admin", status_code=201, response_model=TokenPair, summary="Create the first administrator")
def create_admin(payload: SetupIn, request: Request, response: Response, db: DbSession) -> TokenPair:
    if has_any_user(db):
        raise fehler("setup_done", "Setup is already complete.", 409)
    email = normalize_email(payload.email)
    if not valid_address(email):
        raise fehler("invalid_email", "This is not a valid email address.", 422)
    now = utcnow()
    user = User(
        seen_version=__version__,
        username=payload.username,
        email=email,
        password_hash=hash_password(payload.password),
        role=Role.admin,
        display_name=payload.username,
        language=payload.language,
        password_changed_at=now,
        last_login_at=now,
    )
    db.add(user)
    db.commit()
    save_settings(db, {"default_language": payload.language})
    return sitzung.start(response, request, user)
