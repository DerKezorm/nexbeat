"""Eingang fuer Webhooks von Lidarr.

Lidarr meldet sich mit Basic-Auth, das Passwort ist ``webhook_secret``. Der
Inhalt wird nicht geglaubt: Ein Aufruf weckt nur den Abgleich, der dann bei
Lidarr selbst nachsieht. So kann ein gefaelschter Aufruf nichts eintragen.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import logging

from fastapi import APIRouter, Request

from ..deps import DbSession
from ..meldungen import fehler
from ..services import poller
from ..services.settings_service import load_settings

logger = logging.getLogger("nexbeat.webhooks")

router = APIRouter(tags=["webhooks"])


def _basic_password(header: str) -> str:
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "basic" or not value:
        return ""
    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return ""
    return decoded.partition(":")[2]


@router.post("/api/webhooks/lidarr", status_code=204, summary="Receive a Lidarr webhook")
async def lidarr_webhook(request: Request, db: DbSession) -> None:
    expected = load_settings(db).text("webhook_secret")
    password = _basic_password(request.headers.get("authorization", ""))
    if not expected or not hmac.compare_digest(password.encode("utf-8"), expected.encode("utf-8")):
        raise fehler("webhook_rejected", "The webhook credentials are wrong.", 401)
    try:
        body = await request.json()
    except ValueError:
        body = {}
    event = body.get("eventType") if isinstance(body, dict) else None
    logger.info("Lidarr webhook received: %s", event)
    poller.wake()
