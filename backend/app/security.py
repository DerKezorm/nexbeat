"""Passwort-Hashing (bcrypt) und Sitzungs-Token (JWT).

Uebernommen aus Nexview, dort mit ausfuehrlicher Begruendung.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Any, Literal

import bcrypt
import jwt

from .config import get_settings

ALGORITHM = "HS256"
TokenType = Literal["access", "refresh"]

# bcrypt verarbeitet hoechstens 72 Bytes. bcrypt 5 wirft bei laengeren
# Eingaben einen Fehler, statt still abzuschneiden.
_BCRYPT_MAX_BYTES = 72


def _signing_key() -> bytes:
    # Das Praefix trennt diesen Schluessel von dem der Verschluesselung.
    secret = get_settings().resolved_secret_key().encode("utf-8")
    return hashlib.sha256(b"nexbeat-jwt:" + secret).digest()


def _password_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    rounds = get_settings().bcrypt_rounds
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt(rounds)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_password_bytes(password), password_hash.encode("utf-8"))
    except ValueError:
        return False


@cache
def dummy_hash() -> str:
    """Hash, gegen den bei unbekanntem Konto geprueft wird.

    So dauert eine Anmeldung mit unbekanntem Namen genauso lange wie eine mit
    falschem Passwort, und die Antwortzeit verraet nicht, welche Konten es gibt.
    """
    return hash_password("nexbeat-dummy-password")


def _create_token(subject: int, token_type: TokenType, expires_in: timedelta, session_id: str = "") -> str:
    # ⚠️ ``ms`` ist der Ausstellungszeitpunkt in Millisekunden. ``iat`` ist auf
    # Sekunden gerundet und reicht fuer den Vergleich mit dem letzten
    # Passwortwechsel nicht, siehe ``sitzung.still_valid``.
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": int(now.timestamp()),
        "ms": int(now.timestamp() * 1000),
        "exp": int((now + expires_in).timestamp()),
    }
    if session_id:
        payload["sid"] = session_id
    return jwt.encode(payload, _signing_key(), algorithm=ALGORITHM)


def create_access_token(user_id: int) -> str:
    return _create_token(user_id, "access", timedelta(minutes=get_settings().access_token_minutes))


def create_refresh_token(user_id: int, session_id: str) -> str:
    return _create_token(user_id, "refresh", timedelta(days=get_settings().refresh_token_days), session_id)


@dataclass(frozen=True)
class TokenContent:
    user_id: int
    issued_ms: int
    #: Kennung der Anmeldung. Jede Erneuerung traegt sie weiter, Abmelden entwertet sie ganz.
    session_id: str = ""


def decode_token(token: str, expected_type: TokenType) -> TokenContent | None:
    """Unterschrift, Art und Ablauf pruefen. Ob das Konto das Token noch gelten
    laesst, entscheidet ``sitzung.still_valid``."""
    try:
        payload = jwt.decode(token, _signing_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != expected_type:
        return None
    try:
        return TokenContent(
            user_id=int(payload.get("sub")), issued_ms=int(payload["ms"]), session_id=str(payload.get("sid") or "")
        )
    except (KeyError, TypeError, ValueError):
        return None


def create_device_token(user_id: int, device_id: str, days: int) -> str:
    """Kennzeichen eines Browsers fuer die Anmeldebremse. Art ``device``, oeffnet also keine Sitzung."""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": "device",
        "did": device_id,
        "exp": int((now + timedelta(days=days)).timestamp()),
    }
    return jwt.encode(payload, _signing_key(), algorithm=ALGORITHM)


def decode_device_token(token: str) -> tuple[int, str] | None:
    try:
        payload = jwt.decode(token, _signing_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    device_id = payload.get("did")
    if payload.get("type") != "device" or not isinstance(device_id, str):
        return None
    try:
        return int(payload.get("sub")), device_id
    except (TypeError, ValueError):
        return None


def access_token_expires_in() -> int:
    return get_settings().access_token_minutes * 60
