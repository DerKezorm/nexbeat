"""Einstellungen fuer Admins: Adresse, Mail, Lidarr, Quellen, Kontingent."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..deps import AdminUser, DbSession
from ..meldungen import fehler
from ..schemas import TestMailIn
from ..services import cache, library, lidarr, listenbrainz, mail, mail_templates
from ..services.lidarr import LidarrError
from ..services.mail import MailConfig, MailError
from ..services.settings_service import (
    SettingsError,
    delete_secret,
    ensure_webhook_secret,
    load_settings,
    public_settings,
    save_settings,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _settings_error(error: SettingsError) -> HTTPException:
    return fehler(error.code, "This setting is unknown or its value is not allowed.", 422, key=error.key)


@router.get("", summary="All settings, secrets masked")
def read_settings(_admin: AdminUser, db: DbSession) -> dict[str, Any]:
    return public_settings(load_settings(db))


@router.put("", summary="Change some settings")
def update_settings(payload: dict[str, Any], _admin: AdminUser, db: DbSession) -> dict[str, Any]:
    try:
        settings = save_settings(db, payload)
    except SettingsError as error:
        raise _settings_error(error) from error
    if any(key.startswith("lidarr_") for key in payload):
        # Ein anderes Lidarr hat andere Alben. Alte Antworten gelten nicht mehr.
        cache.forget_prefix(db, "lidarr:")
    return public_settings(settings)


@router.delete("/secret/{key}", summary="Remove a stored secret")
def remove_secret(key: str, _admin: AdminUser, db: DbSession) -> dict[str, Any]:
    try:
        settings = delete_secret(db, key)
    except SettingsError as error:
        raise _settings_error(error) from error
    return public_settings(settings)


class SmtpTestIn(BaseModel):
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    security: str | None = None
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=255)


@router.post("/test/smtp", summary="Check the mail server with saved or unsaved values")
async def test_smtp(payload: SmtpTestIn, _admin: AdminUser, db: DbSession) -> dict[str, bool]:
    base = load_settings(db).mail_config
    password = payload.password if payload.password and not payload.password.startswith("•") else base.password
    config = MailConfig(
        host=payload.host if payload.host is not None else base.host,
        port=payload.port or base.port,
        security=payload.security or base.security,
        username=payload.username if payload.username is not None else base.username,
        password=password,
        from_address=base.from_address,
        from_name=base.from_name,
    )
    try:
        await mail.verify(config)
    except MailError as error:
        raise fehler(error.code, "The mail server check failed.", 400, detail=error.detail[:300]) from error
    return {"ok": True}


class LidarrTestIn(BaseModel):
    url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=200)


@router.post("/test/lidarr", summary="Check Lidarr with saved or unsaved values")
async def test_lidarr(payload: LidarrTestIn, _admin: AdminUser, db: DbSession) -> dict[str, Any]:
    settings = load_settings(db)
    url = (payload.url or settings.text("lidarr_url")).strip().rstrip("/")
    typed = payload.api_key or ""
    key = typed if typed and not typed.startswith("•") else settings.text("lidarr_api_key")
    if not url or not key:
        raise fehler("lidarr_not_configured", "Enter the Lidarr address and API key first.", 422)
    if not url.startswith(("http://", "https://")):
        raise fehler("invalid_setting", "This setting is unknown or its value is not allowed.", 422, key="lidarr_url")
    try:
        status = await lidarr.LidarrClient(url, key).system_status()
    except LidarrError as error:
        raise fehler(error.code, "Lidarr could not be reached.", 502, detail=error.detail[:300]) from error
    return {"ok": True, "version": status.get("version", "")}


class ListenBrainzTestIn(BaseModel):
    token: str | None = Field(default=None, max_length=200)


@router.post("/test/listenbrainz", summary="Check a ListenBrainz token, typed or saved")
async def test_listenbrainz(payload: ListenBrainzTestIn, _admin: AdminUser, db: DbSession) -> dict[str, Any]:
    typed = (payload.token or "").strip()
    token = typed if typed and not typed.startswith("•") else load_settings(db).text("listenbrainz_token")
    if not token:
        raise fehler("listenbrainz_token_missing", "Enter a ListenBrainz token first.", 422)
    try:
        result = await listenbrainz.validate_token(token)
    except listenbrainz.ListenBrainzError as error:
        raise fehler(error.code, "ListenBrainz could not be reached.", 502) from error
    if not result["valid"]:
        raise fehler("listenbrainz_token_rejected", "ListenBrainz does not accept this token.", 400)
    return {"ok": True, "user_name": result["user_name"]}


@router.get("/lidarr/options", summary="Quality profiles, metadata profiles and root folders from Lidarr")
async def lidarr_options(_admin: AdminUser, db: DbSession) -> dict[str, Any]:
    client = lidarr.client_for(load_settings(db))
    if client is None:
        raise fehler("lidarr_not_configured", "Enter the Lidarr address and API key first.", 409)
    try:
        quality, metadata, roots = await asyncio.gather(
            client.quality_profiles(), client.metadata_profiles(), client.root_folders()
        )
    except LidarrError as error:
        raise fehler(error.code, "Lidarr could not be reached.", 502, detail=error.detail[:300]) from error
    return {"quality_profiles": quality, "metadata_profiles": metadata, "root_folders": roots}


@router.get("/webhook", summary="What to enter in Lidarr for the optional webhook")
def webhook_info(_admin: AdminUser, db: DbSession) -> dict[str, Any]:
    return {
        "path": "/api/webhooks/lidarr",
        "username": "nexbeat",
        "password": ensure_webhook_secret(db),
        "events": ["On Release Import", "On Grab", "On Album Delete"],
    }


@router.post("/library/sync", summary="Read the artist list from Lidarr now")
async def sync_library(_admin: AdminUser, db: DbSession) -> dict[str, Any]:
    try:
        count = await library.sync_artists(db, load_settings(db))
    except LidarrError as error:
        raise fehler(error.code, "Lidarr could not be reached.", 502, detail=error.detail[:300]) from error
    if count is None:
        raise fehler("lidarr_not_configured", "Enter the Lidarr address and API key first.", 409)
    return {"artists": count}


@router.post("/test-mail", summary="Send a test mail")
async def send_test_mail(payload: TestMailIn, admin: AdminUser, db: DbSession) -> dict[str, bool]:
    settings = load_settings(db)
    rendered = mail_templates.render("test", admin.language or settings.default_language)
    try:
        await mail.send(settings.mail_config, payload.to or admin.email, rendered.subject, rendered.html, rendered.text)
    except MailError as error:
        raise fehler(error.code, "The test mail could not be sent.", 400, detail=error.detail[:300]) from error
    return {"sent": True}
