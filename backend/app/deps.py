"""Wiederverwendbare Pruefungen: angemeldet? Admin?"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .meldungen import fehler, meldung
from .middleware import set_actor
from .models import User
from .security import decode_token
from .services import sitzung

_bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: DbSession,
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=meldung("not_signed_in", "Not signed in."),
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    content = decode_token(credentials.credentials, "access")
    if content is None:
        raise unauthorized
    user = db.get(User, content.user_id)
    if user is None or not user.is_active or not sitzung.still_valid(content, user):
        raise unauthorized
    set_actor(user.username)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise fehler("admins_only", "This action is reserved for administrators.", 403)
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def has_any_user(db: Session) -> bool:
    return db.scalar(select(User.id).limit(1)) is not None
