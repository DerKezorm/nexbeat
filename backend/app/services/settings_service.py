"""Einstellungen, die der Admin im Betrieb aendert.

Eine Schluessel-Wert-Tabelle. Geheimnisse liegen verschluesselt darin und
verlassen den Server nur maskiert. Ein maskierter Wert, der aus der
Oberflaeche zurueckkommt, ueberschreibt das echte Geheimnis nie.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..crypto import decrypt, encrypt, mask
from ..models import Setting
from .mail import SECURITY_MODES, MailConfig

DEFAULTS: dict[str, str] = {
    "public_url": "",
    "default_language": "de",
    "smtp_host": "",
    "smtp_port": "587",
    "smtp_security": "starttls",
    "smtp_username": "",
    "smtp_password": "",
    "smtp_from_address": "",
    "smtp_from_name": "nexbeat",
    "lidarr_url": "",
    "lidarr_api_key": "",
    "lidarr_root_folder": "",
    "lidarr_quality_profile_id": "",
    "lidarr_metadata_profile_id": "",
    "lidarr_dry_run": "false",
    "webhook_secret": "",
    "source_listenbrainz": "true",
    "source_deezer": "true",
    "lastfm_api_key": "",
    "listenbrainz_token": "",
    "quota_default_limit": "10",
    "quota_period": "week",
}

SECRET_KEYS = frozenset({"smtp_password", "lidarr_api_key", "lastfm_api_key", "listenbrainz_token", "webhook_secret"})
BOOL_KEYS = frozenset({"lidarr_dry_run", "source_listenbrainz", "source_deezer"})
INT_KEYS = frozenset({"smtp_port", "lidarr_quality_profile_id", "lidarr_metadata_profile_id", "quota_default_limit"})
CHOICES: dict[str, tuple[str, ...]] = {
    "smtp_security": SECURITY_MODES,
    "quota_period": ("day", "week", "month"),
    "default_language": ("de", "en"),
}
# Werden nur vom Server selbst geschrieben, nie ueber PUT /api/settings.
INTERNAL_KEYS = frozenset({"webhook_secret"})

_CACHE_KEY = "nexbeat_settings"


class SettingsError(Exception):
    def __init__(self, code: str, key: str) -> None:
        super().__init__(f"{code}: {key}")
        self.code = code
        self.key = key


@dataclass(frozen=True)
class AppSettings:
    values: dict[str, str]

    def text(self, key: str) -> str:
        return self.values.get(key, DEFAULTS[key])

    def flag(self, key: str) -> bool:
        return self.text(key) == "true"

    def number(self, key: str) -> int | None:
        raw = self.text(key)
        return int(raw) if raw.lstrip("-").isdigit() else None

    @property
    def public_url(self) -> str:
        return self.text("public_url")

    @property
    def default_language(self) -> str:
        return self.text("default_language")

    @property
    def mail_config(self) -> MailConfig:
        return MailConfig(
            host=self.text("smtp_host"),
            port=self.number("smtp_port") or 587,
            security=self.text("smtp_security"),
            username=self.text("smtp_username"),
            password=self.text("smtp_password"),
            from_address=self.text("smtp_from_address"),
            from_name=self.text("smtp_from_name"),
        )

    @property
    def mail_configured(self) -> bool:
        return self.mail_config.configured

    @property
    def lidarr_configured(self) -> bool:
        return bool(self.text("lidarr_url") and self.text("lidarr_api_key"))

    @property
    def lidarr_ready(self) -> bool:
        """Verbunden und mit Zielordner und Profilen, also bereit fuer Anfragen."""
        return (
            self.lidarr_configured
            and bool(self.text("lidarr_root_folder"))
            and self.number("lidarr_quality_profile_id") is not None
            and self.number("lidarr_metadata_profile_id") is not None
        )

    @property
    def quota_default_limit(self) -> int | None:
        value = self.number("quota_default_limit")
        return None if value is None or value < 0 else value


def load_settings(db: Session) -> AppSettings:
    cached = db.info.get(_CACHE_KEY)
    if cached is not None:
        return cached
    values = dict(DEFAULTS)
    for row in db.scalars(select(Setting)):
        if row.key in DEFAULTS:
            values[row.key] = decrypt(row.value) if row.key in SECRET_KEYS else row.value
    settings = AppSettings(values=values)
    db.info[_CACHE_KEY] = settings
    return settings


def forget(db: Session) -> None:
    db.info.pop(_CACHE_KEY, None)


def _normalize(key: str, raw: Any) -> str:
    if key in BOOL_KEYS:
        if isinstance(raw, bool):
            return "true" if raw else "false"
        if str(raw).lower() in ("true", "false"):
            return str(raw).lower()
        raise SettingsError("invalid_setting", key)
    value = "" if raw is None else str(raw).strip()
    if key in INT_KEYS:
        if value == "":
            return ""
        if not value.lstrip("-").isdigit():
            raise SettingsError("invalid_setting", key)
        if key == "smtp_port" and not 1 <= int(value) <= 65535:
            raise SettingsError("invalid_setting", key)
        if key == "quota_default_limit" and int(value) < -1:
            raise SettingsError("invalid_setting", key)
        return str(int(value))
    if key in CHOICES and value not in CHOICES[key]:
        raise SettingsError("invalid_setting", key)
    if key in ("public_url", "lidarr_url"):
        if value and not value.startswith(("http://", "https://")):
            raise SettingsError("invalid_setting", key)
        return value.rstrip("/")
    return value


def save_settings(db: Session, updates: dict[str, Any], *, internal: bool = False) -> AppSettings:
    for key in updates:
        if key not in DEFAULTS or (key in INTERNAL_KEYS and not internal):
            raise SettingsError("unknown_setting", key)
    for key, raw in updates.items():
        value = _normalize(key, raw)
        if key in SECRET_KEYS:
            # Leer oder maskiert heisst: unveraendert. Loeschen geht nur
            # ausdruecklich ueber ``delete_secret``.
            if value == "" or value.startswith("•"):
                continue
            value = encrypt(value)
        row = db.get(Setting, key)
        if row is None:
            db.add(Setting(key=key, value=value))
        else:
            row.value = value
    db.commit()
    forget(db)
    return load_settings(db)


def ensure_webhook_secret(db: Session) -> str:
    """Das Passwort, mit dem Lidarr den Webhook aufruft. Einmal erzeugt, dann fest."""
    secret = load_settings(db).text("webhook_secret")
    if not secret:
        secret = secrets.token_urlsafe(24)
        save_settings(db, {"webhook_secret": secret}, internal=True)
    return secret


def delete_secret(db: Session, key: str) -> AppSettings:
    if key not in SECRET_KEYS or key in INTERNAL_KEYS:
        raise SettingsError("unknown_setting", key)
    row = db.get(Setting, key)
    if row is not None:
        db.delete(row)
        db.commit()
    forget(db)
    return load_settings(db)


def public_settings(settings: AppSettings) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in DEFAULTS:
        if key in INTERNAL_KEYS:
            continue
        value = settings.text(key)
        if key in SECRET_KEYS:
            result[key] = mask(value)
            result[f"{key}_set"] = bool(value)
        elif key in BOOL_KEYS:
            result[key] = value == "true"
        elif key in INT_KEYS:
            result[key] = settings.number(key)
        else:
            result[key] = value
    return result
