"""Einstellungen fuer Admins: Adresse, Mail, Lidarr oder nexcrate, Quellen, Kontingent."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..deps import AdminUser, DbSession
from ..meldungen import fehler
from ..models import LibraryArtist
from ..schemas import TestMailIn
from ..services import (
    cache,
    library,
    lidarr,
    listenbrainz,
    mail,
    mail_templates,
    nexcrate,
    nexcrate_events,
    poller,
)
from ..services.lidarr import LidarrError
from ..services.mail import MailConfig, MailError
from ..services.nexcrate import NexcrateError
from ..services.settings_service import (
    SettingsError,
    delete_secret,
    delete_secret_internal,
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
    before = load_settings(db).mode
    try:
        settings = save_settings(db, payload)
    except SettingsError as error:
        raise _settings_error(error) from error
    if any(key.startswith("lidarr_") for key in payload):
        # Ein anderes Lidarr hat andere Alben. Alte Antworten gelten nicht mehr.
        cache.forget_prefix(db, "lidarr:")
    if settings.mode != before:
        # Offene Anfragen, die vorher ans andere Ziel gingen, reicht der Abgleich einmal nach.
        save_settings(db, {"request_mode_changed_at": datetime.now(UTC).isoformat()}, internal=True)
        _changed_target(db)
    elif settings.mode == "nex" and any(key.startswith("nexcrate_") for key in payload):
        _changed_target(db)
    return public_settings(load_settings(db))


def _changed_target(db: DbSession) -> None:
    """Anderes Ziel, andere Alben: Zwischenspeicher und Bestand gelten nicht mehr, der Strom verbindet neu.

    Nur bei einem Wechsel des Modus oder einer anderen nexcrate im NEX-Modus. Wer im ARR-Modus eine
    nexcrate eintraegt, verliert den Bestand aus Lidarr nicht.
    """
    cache.forget_prefix(db, "nexcrate:")
    cache.forget_prefix(db, "lidarr:")
    db.query(LibraryArtist).delete()
    db.commit()
    save_settings(db, {"nexcrate_marker": ""}, internal=True)
    nexcrate_events.restart()
    # Sofort neu einlesen, nicht erst im naechsten planmaessigen Abgleich. 22.09.2026: Nach dem Koppeln war der
    # Bestand bis zu zehn Minuten leer, Entdecken zeigte Kuenstler aus nexcrate als neu, und eine Anfrage
    # dafuer ging durch, als fehlten sie.
    poller.wake(library_too=True)


@router.delete("/secret/{key}", summary="Remove a stored secret")
def remove_secret(key: str, _admin: AdminUser, db: DbSession) -> dict[str, Any]:
    try:
        settings = delete_secret(db, key)
    except SettingsError as error:
        raise _settings_error(error) from error
    if key == "nexcrate_api_key" and settings.mode == "nex":
        _changed_target(db)
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


class NexcrateTestIn(BaseModel):
    url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=200)


def _nexcrate_problem(error: NexcrateError) -> HTTPException:
    return fehler(error.code, "nexcrate could not be reached or refused.", 502, detail=error.detail[:300])


async def _nexcrate_facts(client: nexcrate.NexcrateClient) -> dict[str, Any]:
    """Was nexbeat ueber eine nexcrate wissen muss: Fassung, Vertrag, Rechte, Musik und ihre Fassung."""
    system = await client.system()
    capabilities = system.get("capabilities") or {}
    contract = system.get("contract") or {}
    scopes = list(system.get("scopes") or [])
    music = bool(capabilities.get("music"))
    versions = await client.music_versions() if music else []
    return {
        "ok": True,
        "version": system.get("version") or "",
        "contract": contract.get("major"),
        "stage": contract.get("stage"),
        "music": music,
        "scopes": scopes,
        "can_request": "request" in scopes,
        "music_versions": [
            {
                "name": item.get("name") or "",
                "tier": item.get("tier"),
                "ready": bool(item.get("ready")),
                "reasons": [reason.get("code") for reason in item.get("reasons") or [] if reason.get("code")],
            }
            for item in versions
        ],
    }


@router.post("/test/nexcrate", summary="Check nexcrate with saved or unsaved values")
async def test_nexcrate(payload: NexcrateTestIn, _admin: AdminUser, db: DbSession) -> dict[str, Any]:
    settings = load_settings(db)
    url = (payload.url or settings.text("nexcrate_url")).strip().rstrip("/")
    typed = payload.api_key or ""
    key = typed if typed and not typed.startswith("•") else settings.text("nexcrate_api_key")
    if not url or not key:
        raise fehler("nexcrate_not_configured", "Connect nexcrate first.", 422)
    if not url.startswith(("http://", "https://")):
        raise fehler("invalid_setting", "This setting is unknown or its value is not allowed.", 422, key="nexcrate_url")
    try:
        return await _nexcrate_facts(nexcrate.NexcrateClient(url, key))
    except NexcrateError as error:
        raise _nexcrate_problem(error) from error


@router.get("/nexcrate/status", summary="How the connection to nexcrate stands")
async def nexcrate_status(_admin: AdminUser, db: DbSession) -> dict[str, Any]:
    settings = load_settings(db)
    base = {
        "url": settings.text("nexcrate_url"),
        "connected": settings.nexcrate_configured,
        "key_hint": settings.text("nexcrate_api_key")[-4:] if settings.nexcrate_configured else None,
        "events": nexcrate_events.status(),
        "artists": db.query(LibraryArtist).count(),
        "facts": None,
        "error": None,
    }
    if not settings.nexcrate_configured:
        return base
    try:
        client = nexcrate.NexcrateClient(settings.text("nexcrate_url"), settings.text("nexcrate_api_key"))
        base["facts"] = await _nexcrate_facts(client)
    except NexcrateError as error:
        base["error"] = {"code": error.code, "detail": error.detail[:300]}
    return base


class PairingIn(BaseModel):
    url: str = Field(min_length=1, max_length=500)


def _pairing(db: DbSession) -> dict[str, Any] | None:
    raw = load_settings(db).text("nexcrate_pairing")
    try:
        stored = json.loads(raw) if raw else None
    except ValueError:
        return None
    return stored if isinstance(stored, dict) else None


def _forget_pairing(db: DbSession) -> None:
    delete_secret_internal(db, "nexcrate_pairing")


@router.post("/nexcrate/pairing", summary="Ask nexcrate for a key; the owner confirms it there")
async def start_pairing(payload: PairingIn, _admin: AdminUser, db: DbSession) -> dict[str, Any]:
    url = payload.url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise fehler("invalid_setting", "This setting is unknown or its value is not allowed.", 422, key="nexcrate_url")
    try:
        asked = await nexcrate.NexcrateClient(url).pairing_ask("nexbeat", nexcrate.SCOPES)
    except NexcrateError as error:
        raise _nexcrate_problem(error) from error
    stored = {
        "url": url,
        "id": asked.get("pairing_id"),
        "secret": asked.get("secret"),
        "code": asked.get("code"),
        "expires_at": asked.get("expires_at"),
        "poll_seconds": asked.get("poll_seconds") or 2,
    }
    save_settings(db, {"nexcrate_pairing": json.dumps(stored)}, internal=True)
    return {"state": "pending", **{key: stored[key] for key in ("url", "code", "expires_at", "poll_seconds")}}


@router.get("/nexcrate/pairing", summary="Whether the owner confirmed in nexcrate; stores the key once it comes")
async def poll_pairing(_admin: AdminUser, db: DbSession) -> dict[str, Any]:
    stored = _pairing(db)
    if stored is None:
        return {"state": "none"}
    shown = {key: stored.get(key) for key in ("url", "code", "expires_at", "poll_seconds")}
    try:
        answer = await nexcrate.NexcrateClient(stored["url"]).pairing_poll(str(stored["id"]), str(stored["secret"]))
    except NexcrateError as error:
        if error.code == "nexcrate_pairing_gone":
            # Abgelaufen oder bei nexcrate vergessen. Ohne Geheimnis sagt nexcrate dasselbe.
            _forget_pairing(db)
            return {"state": "expired", **shown}
        if error.transient:
            return {"state": "pending", **shown, "error": error.code}
        raise _nexcrate_problem(error) from error
    state = answer.get("state") or "pending"
    if state == "confirmed" and answer.get("key"):
        # ⚠️ Zuerst speichern: nexcrate liefert den Schluessel genau einmal.
        save_settings(db, {"nexcrate_url": stored["url"], "nexcrate_api_key": answer["key"]})
        _forget_pairing(db)
        if load_settings(db).mode == "nex":
            _changed_target(db)
        return {"state": "confirmed", **shown, "scopes": answer.get("scopes") or []}
    if state in ("denied", "expired", "delivered"):
        _forget_pairing(db)
        # "delivered" ohne Schluessel in der Hand: die Antwort mit ihm ging verloren. Neu koppeln.
        return {"state": "denied" if state == "denied" else "expired", **shown}
    if _expired(stored.get("expires_at")):
        _forget_pairing(db)
        return {"state": "expired", **shown}
    return {"state": "pending", **shown}


def _expired(value: Any) -> bool:
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return False
    return moment.tzinfo is not None and moment < datetime.now(UTC)


@router.delete("/nexcrate/pairing", status_code=204, summary="Stop waiting for the owner")
def cancel_pairing(_admin: AdminUser, db: DbSession) -> None:
    # nexcrate kennt kein Zuruecknehmen einer Bitte; sie laeuft dort nach zehn Minuten ab.
    _forget_pairing(db)


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


@router.post("/library/sync", summary="Read the artist list from Lidarr or nexcrate now")
async def sync_library(_admin: AdminUser, db: DbSession) -> dict[str, Any]:
    settings = load_settings(db)
    try:
        count = await library.sync_artists(db, settings)
    except LidarrError as error:
        raise fehler(error.code, "Lidarr could not be reached.", 502, detail=error.detail[:300]) from error
    except NexcrateError as error:
        raise _nexcrate_problem(error) from error
    if count is None and settings.mode == "nex":
        raise fehler("nexcrate_not_configured", "Connect nexcrate first.", 409)
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
