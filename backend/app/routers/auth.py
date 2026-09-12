"""Anmelden, erneuern, abmelden und das eigene Konto."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..deps import CurrentUser, DbSession
from ..meldungen import fehler, meldung
from ..models import User, utcnow
from ..schemas import LoginIn, MeOut, MeUpdate, PasswordChangeIn, TokenPair, UserOut
from ..security import decode_token, dummy_hash, hash_password, verify_password
from ..services import anmeldebremse, quota, sitzung
from ..services.settings_service import load_settings
from ..services.tokens import normalize_email

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _find_user(db: Session, login: str) -> User | None:
    name = login.strip()
    return db.scalar(
        select(User).where(or_(func.lower(User.username) == name.lower(), User.email == normalize_email(name)))
    )


def me_out(db: Session, user: User) -> MeOut:
    state = quota.state(db, user, load_settings(db))
    return MeOut.model_validate(
        {**UserOut.model_validate(user).model_dump(), "is_admin": user.is_admin, "quota": quota.as_dict(state)}
    )


def _brake_key(request: Request, user: User | None, login: str) -> str:
    """Wessen Zaehler: der eines bekannten Browsers, der des Kontos oder, ohne Konto, der des Namens."""
    if user is None:
        return anmeldebremse.login_key(login)
    device = sitzung.known_device(request, user)
    return anmeldebremse.device_key(user.id, device) if device else anmeldebremse.account_key(user.id)


def _slow_down(wait: int, message: str) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail=meldung("too_many_attempts", message, retry_after=wait),
        headers={"Retry-After": str(wait)},
    )


@router.post("/login", response_model=TokenPair, summary="Sign in with username or email")
def login(payload: LoginIn, request: Request, response: Response, db: DbSession) -> TokenPair:
    user = _find_user(db, payload.login)
    key = _brake_key(request, user, payload.login)
    wait = anmeldebremse.wait_seconds(key)
    if wait:
        raise _slow_down(wait, "Too many failed sign-ins. Try again later.")
    # Auch ohne Konto wird geprueft, damit die Antwortzeit nichts verraet.
    password_ok = verify_password(payload.password, user.password_hash if user else dummy_hash())
    if user is None or not password_ok or not user.is_active:
        anmeldebremse.failed(key)
        raise fehler("invalid_credentials", "Username or password is wrong.", 401)
    anmeldebremse.succeeded(key)
    user.last_login_at = utcnow()
    db.commit()
    sitzung.remember_device(response, request, user)
    return sitzung.start(response, request, user)


@router.post("/refresh", response_model=TokenPair, summary="Issue a new access token from the session cookie")
def refresh(request: Request, response: Response, db: DbSession) -> Any:
    raw = sitzung.read(request)
    content = decode_token(raw, "refresh") if raw else None
    user = db.get(User, content.user_id) if content else None
    if (
        raw is None
        or content is None
        or user is None
        or not user.is_active
        or not sitzung.still_valid(content, user)
        or sitzung.revoked(db, raw, content)
    ):
        failure = JSONResponse(status_code=401, content={"detail": meldung("not_signed_in", "Not signed in.")})
        sitzung.end(failure, request)
        return failure
    return sitzung.start(response, request, user, session_id=sitzung.session_of(raw, content))


@router.post("/logout", status_code=204, summary="End the session in this browser")
def logout(request: Request, response: Response, db: DbSession) -> None:
    raw = sitzung.read(request)
    if raw:
        sitzung.revoke(db, raw)
    sitzung.end(response, request)


@router.get("/me", response_model=MeOut, summary="The signed-in account with its quota")
def me(user: CurrentUser, db: DbSession) -> MeOut:
    return me_out(db, user)


@router.patch("/me", response_model=MeOut, summary="Change display name or language")
def update_me(payload: MeUpdate, user: CurrentUser, db: DbSession) -> MeOut:
    if payload.display_name is not None:
        user.display_name = payload.display_name.strip()
    if payload.language is not None:
        user.language = payload.language
    db.commit()
    return me_out(db, user)


@router.post("/me/password", response_model=TokenPair, summary="Change the password and end other sessions")
def change_password(
    payload: PasswordChangeIn, request: Request, response: Response, user: CurrentUser, db: DbSession
) -> TokenPair:
    # 12.09.2026: Ohne Bremse liess sich hier mit einer fremden Sitzung das Passwort raten.
    key = anmeldebremse.password_change_key(user.id)
    wait = anmeldebremse.wait_seconds(key)
    if wait:
        raise _slow_down(wait, "Too many wrong passwords. Try again later.")
    if not verify_password(payload.current_password, user.password_hash):
        anmeldebremse.failed(key)
        raise fehler("wrong_password", "The current password is wrong.", 400)
    anmeldebremse.succeeded(key)
    user.password_hash = hash_password(payload.new_password)
    user.password_changed_at = utcnow()
    db.commit()
    # Alle anderen Sitzungen sind damit ungueltig, diese hier bekommt eine neue.
    return sitzung.start(response, request, user)
