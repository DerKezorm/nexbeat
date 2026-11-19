"""Ein Geraet per Code verbinden, gebaut wie nexbooks' Kopplung per Code (S1b).

Ablauf: Das Geraet (etwa die iPhone-App nextune) fragt ohne Anmeldung einen Code an und bekommt dazu ein
Geheimnis. Es zeigt den Code, der Mensch tippt ihn im Browser unter Profil > API-Token ein. Danach holt das
Geraet mit seinem Geheimnis einen Token ab, der genau die Rechte des bestaetigenden Kontos hat.

⚠️ Der Code allein gibt nichts heraus: Abholen geht nur mit dem Geheimnis, und das sieht nur das Geraet.
Wer Codes durchprobiert, braucht eine Browsersitzung, und Fehlgriffe bremst ``anmeldebremse`` je Konto.
Der Token entsteht erst beim Abholen und wird genau einmal herausgegeben.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import ApiKey, PairingRequest, User, utcnow
from . import anmeldebremse, api_keys

#: Ohne 0, O, 1, I und L: nichts, was man beim Abtippen verwechselt.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
LIFETIME = timedelta(minutes=10)
POLL_SECONDS = 3
#: Offene Anfragen insgesamt. Anfragen kommen ohne Anmeldung, also darf niemand die Tabelle fluten.
MOST_OPEN = 50
#: Abgelaufene und abgeholte Anfragen bleiben so lange, damit ein spaetes Nachfragen noch "abgelaufen" hoert.
KEEP = timedelta(days=1)


class PairingProblem(Exception):
    def __init__(self, code: str, message: str, status_code: int, **values: object) -> None:
        super().__init__(code)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.values = values


@dataclass
class Made:
    request: PairingRequest
    secret: str


@dataclass
class State:
    state: str
    token: str | None = None
    account: str | None = None


def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize(text: str) -> str:
    """Was ein Mensch eintippt: Gross, Klein, Bindestrich und Leerzeichen sind gleich."""
    return "".join(ch for ch in text.upper() if ch.isalnum())


def formatted(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


def _brake_key(user_id: int) -> str:
    return f"pairing:{user_id}"


def _purge(db: Session) -> None:
    db.execute(delete(PairingRequest).where(PairingRequest.expires_at < utcnow() - KEEP))


def create(db: Session, device_name: str | None) -> Made:
    _purge(db)
    now = utcnow()
    open_count = db.scalar(
        select(func.count()).select_from(PairingRequest).where(
            PairingRequest.expires_at > now, PairingRequest.used_at.is_(None)
        )
    )
    if (open_count or 0) >= MOST_OPEN:
        raise PairingProblem(
            "pairing_busy", "Too many devices are waiting for a code. Try again in a few minutes.", 429, retry_after=60
        )
    name = (device_name or "").strip()[:80] or "App"
    while True:
        code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
        taken = db.scalar(select(PairingRequest.id).where(PairingRequest.code == code, PairingRequest.expires_at > now))
        if taken is None:
            break
    secret = secrets.token_urlsafe(32)
    request = PairingRequest(id=secrets.token_urlsafe(16)[:22], secret_hash=_digest(secret), code=code,
                             device_name=name, created_at=now, expires_at=now + LIFETIME)
    db.add(request)
    db.commit()
    db.refresh(request)
    return Made(request=request, secret=secret)


def _own(db: Session, request_id: str, secret: str) -> PairingRequest:
    """Die Anfrage zu Kennung und Geheimnis. Falsches Geheimnis und unbekannte Kennung klingen gleich."""
    request = db.get(PairingRequest, request_id)
    if request is None or not hmac.compare_digest(request.secret_hash, _digest(secret or "")):
        raise PairingProblem("pairing_unknown", "No such pairing request.", 404)
    return request


def state(db: Session, request_id: str, secret: str) -> State:
    """Was das Geraet beim Nachfragen hoert. Nach der Bestaetigung genau einmal den Token."""
    request = _own(db, request_id, secret)
    if request.used_at is not None:
        raise PairingProblem("pairing_used", "This code was used already.", 410)
    if request.user_id is None:
        if request.expires_at <= utcnow():
            raise PairingProblem("pairing_expired", "This code ran out. Ask for a new one.", 410)
        return State(state="waiting")
    user = db.get(User, request.user_id)
    if user is None or not user.is_active:
        raise PairingProblem("pairing_unknown", "No such pairing request.", 404)
    _key, token = api_keys.create(db, user, name=request.device_name, read_only=False)
    request.used_at = utcnow()
    db.commit()
    return State(state="confirmed", token=token, account=user.display_name or user.username)


def release(db: Session, request_id: str, secret: str) -> None:
    """Das Geraet laesst seinen Code los (neuer Code, Bildschirm zu). Nach dem Abholen bleibt alles stehen."""
    request = _own(db, request_id, secret)
    if request.used_at is None:
        db.delete(request)
        db.commit()


def confirm(db: Session, user: User, code: str) -> PairingRequest:
    """Im Browser: Der Mensch bestaetigt den Code, den sein Geraet zeigt."""
    clean = normalize(code)
    if len(clean) != CODE_LENGTH or any(ch not in ALPHABET for ch in clean):
        raise PairingProblem("pairing_code", "That is not a code. It has eight letters and digits.", 422)
    key = _brake_key(user.id)
    wait = anmeldebremse.wait_seconds(key)
    if wait > 0:
        raise PairingProblem("pairing_wait", "Too many wrong codes. Wait a moment.", 429, retry_after=wait)
    request = db.scalar(
        select(PairingRequest).where(PairingRequest.code == clean, PairingRequest.expires_at > utcnow())
    )
    if request is None or request.user_id is not None or request.used_at is not None:
        anmeldebremse.failed(key)
        raise PairingProblem(
            "pairing_unknown", "No device is waiting with this code. Check it, or let the device show a new one.", 404
        )
    keys = db.scalar(select(func.count()).select_from(ApiKey).where(ApiKey.user_id == user.id)) or 0
    if keys >= api_keys.MOST:
        raise PairingProblem(
            "api_key_too_many", f"An account can have at most {api_keys.MOST} API tokens. Revoke one first.", 409
        )
    anmeldebremse.succeeded(key)
    request.user_id = user.id
    request.confirmed_at = utcnow()
    db.commit()
    return request
