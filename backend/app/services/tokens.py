"""Einmal-Links fuer Einladung und Passwort-Reset.

* Der Link selbst steht nie in der Datenbank, nur seine Pruefsumme.
* Jeder Link gilt genau einmal und laeuft ab.
* Ein neuer Link derselben Art entwertet die aelteren derselben Adresse.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuthToken, Role, TokenPurpose, User, utcnow

LIFETIME = {
    TokenPurpose.invitation: timedelta(days=7),
    TokenPurpose.password_reset: timedelta(hours=1),
}

TOKEN_BYTES = 32


def normalize_email(address: str) -> str:
    return address.strip().lower()


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def invalidate(db: Session, purpose: TokenPurpose, email: str) -> None:
    now = utcnow()
    for token in db.scalars(
        select(AuthToken).where(
            AuthToken.purpose == purpose,
            AuthToken.email == normalize_email(email),
            AuthToken.used_at.is_(None),
        )
    ):
        token.used_at = now


def revoke_issued_by(db: Session, user_id: int) -> None:
    """Offene Links entwerten, die dieses Konto ausgegeben hat. Der Aufrufer committet.

    12.09.2026: Einladungen und Passwort-Links galten weiter, nachdem ihr Admin abgesetzt,
    deaktiviert oder geloescht war.
    """
    now = utcnow()
    for token in db.scalars(select(AuthToken).where(AuthToken.created_by == user_id, AuthToken.used_at.is_(None))):
        token.used_at = now


def create(
    db: Session,
    purpose: TokenPurpose,
    email: str,
    *,
    user: User | None = None,
    created_by: int | None = None,
    invite_role: Role | None = None,
) -> tuple[str, AuthToken]:
    """Neuen Link anlegen. Der Klartext kommt nur dieses eine Mal zurueck."""
    address = normalize_email(email)
    invalidate(db, purpose, address)
    raw = secrets.token_urlsafe(TOKEN_BYTES)
    token = AuthToken(
        purpose=purpose,
        token_hash=_hash(raw),
        user_id=user.id if user else None,
        email=address,
        expires_at=utcnow() + LIFETIME[purpose],
        created_by=created_by,
        invite_role=invite_role,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return raw, token


def find(db: Session, raw: str, purpose: TokenPurpose) -> AuthToken | None:
    token = db.scalar(select(AuthToken).where(AuthToken.token_hash == _hash(raw), AuthToken.purpose == purpose))
    return token if token is not None and token.open else None


def consume(db: Session, raw: str, purpose: TokenPurpose) -> AuthToken | None:
    """Einloesen. Der Aufrufer committet, damit Verbrauch und Aenderung zusammen gelten."""
    token = find(db, raw, purpose)
    if token is not None:
        token.used_at = utcnow()
    return token


def purge_expired(db: Session) -> int:
    limit = utcnow() - timedelta(days=30)
    old = list(db.scalars(select(AuthToken).where((AuthToken.expires_at < limit) | (AuthToken.used_at < limit))))
    for token in old:
        db.delete(token)
    if old:
        db.commit()
    return len(old)
