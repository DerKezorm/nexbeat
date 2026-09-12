"""Die Sitzung im Browser und der eine Ort, an dem sie entsteht.

Wie in Nexview: Das Erneuerungs-Token verlaesst das Backend nur als
HttpOnly-Cookie unter ``/api/auth``. Der Zugangs-Token steht im
Antwortkoerper, lebt nur im Arbeitsspeicher der Seite und faehrt als
``Authorization``-Kopf mit. Damit braucht nur ein Endpunkt einen CSRF-Schutz,
und den gibt ``SameSite=Lax``.

⚠️ Jeder Weg zu einer Sitzung geht durch ``start``: Erst-Einrichtung, Anmeldung,
Erneuerung, Passwortwechsel.

Alle Erneuerungs-Tokens einer Anmeldung tragen dieselbe Kennung (``sid``). Abmelden
traegt sie in ``revoked_sessions`` ein, damit gilt keins mehr davon. 12.09.2026: Vorher
loeschte Abmelden nur das Cookie, und eine vorher gezogene Kopie bekam weiter neue
Zugaenge, auch nach etlichen Erneuerungen.

Ein zweites Cookie, ``nexbeat_device``, merkt sich Browser, die sich schon einmal
erfolgreich angemeldet haben. Es oeffnet nichts, es gibt nur der Anmeldebremse
einen eigenen Zaehler.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Request, Response
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import RevokedSession, User, utcnow
from ..schemas import TokenPair
from ..security import (
    TokenContent,
    access_token_expires_in,
    create_access_token,
    create_device_token,
    create_refresh_token,
    decode_device_token,
    decode_token,
)

logger = logging.getLogger("nexbeat.sitzung")

COOKIE_NAME = "nexbeat_refresh"
COOKIE_PATH = "/api/auth"
DEVICE_COOKIE = "nexbeat_device"
DEVICE_DAYS = 365


def cookie_secure(request: Request) -> bool:
    setting = (get_settings().cookie_secure or "auto").strip().lower()
    if setting == "on":
        return True
    if setting == "off":
        return False
    if setting != "auto":
        logger.warning("NEXBEAT_COOKIE_SECURE is %r, which is not understood. Using auto.", setting)
    # Zurueckhaltend: Ein Secure-Cookie ueber http wirft der Browser weg, und
    # dann kommt niemand mehr hinein.
    return request.url.scheme == "https"


def start(response: Response, request: Request, user: User, session_id: str | None = None) -> TokenPair:
    """Neue Anmeldung, oder mit ``session_id`` dieselbe Anmeldung mit frischen Tokens."""
    response.set_cookie(
        COOKIE_NAME,
        create_refresh_token(user.id, session_id or secrets.token_urlsafe(16)),
        max_age=get_settings().refresh_token_days * 24 * 60 * 60,
        path=COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(request),
    )
    return TokenPair(access_token=create_access_token(user.id), expires_in=access_token_expires_in())


def end(response: Response, request: Request) -> None:
    # Pfad und Secure muessen wie beim Setzen sein, sonst bleibt das echte liegen.
    response.delete_cookie(
        COOKIE_NAME,
        path=COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(request),
    )


def read(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME)


def _token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def session_of(raw: str, content: TokenContent) -> str:
    """Kennung der Anmeldung. Ein Token ohne Kennung zaehlt als eigene Anmeldung."""
    return content.session_id or _token_hash(raw)[:32]


def revoke(db: Session, raw: str) -> None:
    """Die ganze Anmeldung entwerten, auch aeltere Tokens daraus, nicht nur das Cookie loeschen."""
    content = decode_token(raw, "refresh")
    if content is None:
        return
    session_id = session_of(raw, content)
    if db.get(RevokedSession, session_id) is None:
        # Kein Token dieser Anmeldung lebt laenger als eins, das jetzt ausgestellt wuerde.
        expires = utcnow() + timedelta(days=get_settings().refresh_token_days)
        db.add(RevokedSession(session_id=session_id, expires_at=expires))
        db.commit()


def revoked(db: Session, raw: str, content: TokenContent) -> bool:
    return db.get(RevokedSession, session_of(raw, content)) is not None


def purge_revoked(db: Session) -> int:
    """Eintraege abgelaufener Tokens entfernen. Die lassen sich ohnehin nicht mehr erneuern."""
    result = db.execute(delete(RevokedSession).where(RevokedSession.expires_at < utcnow()))
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


def remember_device(response: Response, request: Request, user: User) -> None:
    """Nach erfolgreicher Anmeldung: diesen Browser fuer die Anmeldebremse als bekannt markieren."""
    device_id = known_device(request, user) or secrets.token_urlsafe(16)
    response.set_cookie(
        DEVICE_COOKIE,
        create_device_token(user.id, device_id, DEVICE_DAYS),
        max_age=DEVICE_DAYS * 24 * 60 * 60,
        path=COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(request),
    )


def known_device(request: Request, user: User) -> str | None:
    """Kennung des Browsers, wenn er sich schon einmal als dieses Konto angemeldet hat."""
    raw = request.cookies.get(DEVICE_COOKIE)
    content = decode_device_token(raw) if raw else None
    if content is None or content[0] != user.id:
        return None
    return content[1]


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def still_valid(content: TokenContent, user: User) -> bool:
    """Gilt das Token nach dem letzten Passwortwechsel und dem letzten Beenden aller Sitzungen noch?

    ⚠️ In Millisekunden verglichen. Mit gerundeten Sekunden ueberlebt ein
    Token aus derselben Sekunde den Wechsel, oder ein frisches Konto sperrt
    sich selbst aus. Nexview hat beides erlebt.

    12.09.2026: Ohne gespeicherten Passwortwechsel galt ``sessions_valid_from`` nicht. Ein
    deaktiviertes und wieder aktiviertes Konto behielt so seine alten Sitzungen.
    """
    limits = [_utc(value) for value in (user.password_changed_at, user.sessions_valid_from) if value is not None]
    if not limits:
        return True
    return content.issued_ms >= int(max(limits).timestamp() * 1000)
