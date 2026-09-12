"""Oeffentliche Wege ohne Anmeldung: Einladung annehmen, Passwort vergessen.

Einladung und Reset geben bewusst keine Sitzung aus, beide schicken danach auf
die normale Anmeldung. So entsteht eine Sitzung nur dort, wo auch die Bremse
gegen Passwort-Raten sitzt.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from fastapi import APIRouter, BackgroundTasks, Request
from sqlalchemy import func, select

from ..deps import DbSession
from ..meldungen import fehler
from ..models import Role, TokenPurpose, User, utcnow
from ..schemas import AcceptInvitationIn, ForgotPasswordIn, InvitationInfo, ResetPasswordIn
from ..security import hash_password
from ..services import accounts, anmeldebremse, tokens
from ..services.settings_service import load_settings
from ..services.tokens import normalize_email

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])

FORGOT_WINDOW_SECONDS = 3600
FORGOT_MAX_PER_WINDOW = 5
_forgot_lock = threading.Lock()
_forgot_log: dict[str, deque[float]] = {}


def _forgot_allowed(email: str) -> bool:
    now = time.monotonic()
    with _forgot_lock:
        log = _forgot_log.setdefault(email, deque())
        while log and now - log[0] > FORGOT_WINDOW_SECONDS:
            log.popleft()
        if len(log) >= FORGOT_MAX_PER_WINDOW:
            return False
        log.append(now)
        return True


def reset_limits() -> None:
    with _forgot_lock:
        _forgot_log.clear()


@router.post("/forgot-password", status_code=202, summary="Send a password link if the address belongs to an account")
def forgot_password(
    payload: ForgotPasswordIn, request: Request, background: BackgroundTasks, db: DbSession
) -> dict[str, str]:
    # ⚠️ Die Antwort ist immer dieselbe. Sonst liesse sich abfragen, welche
    # Adressen ein Konto haben. Der Versand laeuft nach der Antwort, damit auch
    # die Dauer nichts verraet.
    email = normalize_email(payload.email)
    settings = load_settings(db)
    if settings.mail_configured and _forgot_allowed(email):
        user = db.scalar(select(User).where(User.email == email))
        if user is not None and user.is_active:
            raw, _token = tokens.create(db, TokenPurpose.password_reset, email, user=user)
            background.add_task(
                accounts.send_password_reset,
                settings,
                raw=raw,
                email=email,
                language=user.language or settings.default_language,
                base_url=accounts.link_base(settings, request),
            )
    return {"status": "accepted"}


@router.get("/invitation/{raw}", response_model=InvitationInfo, summary="Look at an invitation without using it")
def invitation_info(raw: str, db: DbSession) -> InvitationInfo:
    token = tokens.find(db, raw, TokenPurpose.invitation)
    if token is None:
        raise fehler("invitation_invalid", "This invitation is invalid or has expired.", 404)
    return InvitationInfo(email=token.email, role=token.invite_role or Role.user)


@router.post("/invitation/{raw}", status_code=201, summary="Accept an invitation and create the account")
def accept_invitation(raw: str, payload: AcceptInvitationIn, db: DbSession) -> dict[str, str]:
    token = tokens.find(db, raw, TokenPurpose.invitation)
    if token is None:
        raise fehler("invitation_invalid", "This invitation is invalid or has expired.", 404)
    if db.scalar(select(User.id).where(func.lower(User.username) == payload.username.lower())):
        raise fehler("username_taken", "This username is already taken.", 409)
    if db.scalar(select(User.id).where(User.email == token.email)):
        raise fehler("email_taken", "An account with this email address already exists.", 409)
    user = User(
        username=payload.username,
        email=token.email,
        password_hash=hash_password(payload.password),
        role=token.invite_role or Role.user,
        display_name=payload.display_name.strip() or payload.username,
        language=payload.language,
        password_changed_at=utcnow(),
    )
    db.add(user)
    tokens.consume(db, raw, TokenPurpose.invitation)
    db.commit()
    return {"username": user.username}


@router.get("/password/{raw}", summary="Check a password link without using it")
def reset_info(raw: str, db: DbSession) -> dict[str, bool]:
    if tokens.find(db, raw, TokenPurpose.password_reset) is None:
        raise fehler("reset_invalid", "This link is invalid or has expired.", 404)
    return {"valid": True}


@router.post("/password/{raw}", status_code=204, summary="Set a new password with a password link")
def reset_password(raw: str, payload: ResetPasswordIn, db: DbSession) -> None:
    token = tokens.consume(db, raw, TokenPurpose.password_reset)
    user = db.get(User, token.user_id) if token is not None and token.user_id else None
    if token is None or user is None:
        db.rollback()
        raise fehler("reset_invalid", "This link is invalid or has expired.", 404)
    user.password_hash = hash_password(payload.password)
    # Wer sein Passwort zuruecksetzt, rechnet mit einem Angreifer. Alle
    # bestehenden Sitzungen enden damit.
    user.password_changed_at = utcnow()
    db.commit()
    anmeldebremse.forget_user(user.id)
