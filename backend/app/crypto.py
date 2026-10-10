"""Verschluesselung der Geheimnisse, die in der Datenbank liegen.

Lidarr-Schluessel und SMTP-Passwort stehen damit nicht im Klartext in der
SQLite-Datei. Der Schluessel stammt aus ``NEXBEAT_SECRET_KEY`` oder der
automatisch erzeugten ``data/secret.key``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import os

from cryptography.exceptions import InvalidTag
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import get_settings

logger = logging.getLogger("nexbeat.crypto")

_PREFIX = "enc:"
_SEALED = "gcm:"
_remembered: Fernet | None = None
_remembered_aead: AESGCM | None = None


def _fernet() -> Fernet:
    global _remembered
    if _remembered is None:
        secret = get_settings().resolved_secret_key().encode("utf-8")
        digest = hashlib.sha256(b"nexbeat-settings:" + secret).digest()
        _remembered = Fernet(base64.urlsafe_b64encode(digest))
    return _remembered


def encrypt(value: str) -> str:
    return _PREFIX + _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt(value: str) -> str:
    """Entschluesseln. Unverschluesselte Werte werden durchgereicht."""
    if not value.startswith(_PREFIX):
        return value
    try:
        return _fernet().decrypt(value[len(_PREFIX) :].encode("utf-8")).decode("utf-8")
    except InvalidToken:
        # Laut statt still: Sonst ist eine Verbindung einfach "weg", und
        # nirgends steht, warum.
        logger.warning(
            "A stored credential cannot be decrypted with the current secret key. "
            "Was NEXBEAT_SECRET_KEY changed or data/secret.key lost? Enter the credential again."
        )
        return ""


def _aead() -> AESGCM:
    global _remembered_aead
    if _remembered_aead is None:
        secret = get_settings().resolved_secret_key().encode("utf-8")
        _remembered_aead = AESGCM(hashlib.sha256(b"nexbeat-sealed:" + secret).digest())
    return _remembered_aead


def seal(value: str, context: str) -> str:
    """Verschluesseln mit einem Kontext, etwa ``oidc-provider:7``: Ein Wert aus einem anderen Kontext laesst sich
    hier nicht oeffnen, auch nicht durch Umkopieren in der Datenbank. Leer bleibt leer."""
    if not value:
        return ""
    nonce = os.urandom(12)
    sealed = _aead().encrypt(nonce, value.encode("utf-8"), context.encode("utf-8"))
    return _SEALED + base64.urlsafe_b64encode(nonce + sealed).decode("ascii")


def unseal(value: str, context: str) -> str:
    """Gegenstueck zu ``seal``. Was sich nicht oeffnen laesst, ist leer, mit einer Zeile im Log."""
    if not value:
        return ""
    try:
        raw = base64.urlsafe_b64decode(value.removeprefix(_SEALED).encode("ascii"))
        return _aead().decrypt(raw[:12], raw[12:], context.encode("utf-8")).decode("utf-8")
    except (InvalidTag, ValueError, binascii.Error, UnicodeDecodeError):
        logger.warning(
            "A stored credential (%s) cannot be decrypted with the current secret key. Enter it again.", context
        )
        return ""


def mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "••••"
    return "••••" + value[-4:]
