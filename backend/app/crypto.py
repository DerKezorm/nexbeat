"""Verschluesselung der Geheimnisse, die in der Datenbank liegen.

Lidarr-Schluessel und SMTP-Passwort stehen damit nicht im Klartext in der
SQLite-Datei. Der Schluessel stammt aus ``NEXBEAT_SECRET_KEY`` oder der
automatisch erzeugten ``data/secret.key``.
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

logger = logging.getLogger("nexbeat.crypto")

_PREFIX = "enc:"
_remembered: Fernet | None = None


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


def mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "••••"
    return "••••" + value[-4:]
