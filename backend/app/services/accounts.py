"""Einladung und Passwort-Link zustellen.

Ein fehlgeschlagener Versand haelt nichts auf: Der Admin bekommt den Link zum
Weitergeben zurueck. Ohne eingerichteten Mailserver ist das der Normalfall.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import Request

from . import mail, mail_templates
from .settings_service import AppSettings

logger = logging.getLogger("nexbeat.accounts")


@dataclass(frozen=True)
class Delivery:
    sent: bool
    link: str
    error_code: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "sent": self.sent,
            "manual_link": None if self.sent else self.link,
            "error_code": self.error_code,
        }


def link_base(settings: AppSettings, request: Request) -> str:
    """Wohin der Link zeigt: eingetragene Adresse, sonst die Seite, von der die Anfrage kam."""
    if settings.public_url:
        return settings.public_url
    origin = request.headers.get("origin")
    if origin and origin.startswith(("http://", "https://")):
        return origin.rstrip("/")
    return str(request.base_url).rstrip("/")


async def _deliver(settings: AppSettings, to: str, rendered: mail_templates.Mail, link: str) -> Delivery:
    if not settings.mail_configured:
        return Delivery(sent=False, link=link, error_code="mail_not_configured")
    try:
        await mail.send(settings.mail_config, to, rendered.subject, rendered.html, rendered.text)
    except mail.MailError as error:
        logger.warning("Mail could not be sent: %s", error.code)
        return Delivery(sent=False, link=link, error_code=error.code)
    return Delivery(sent=True, link=link)


async def send_invitation(
    settings: AppSettings, *, raw: str, email: str, inviter: str, language: str, base_url: str
) -> Delivery:
    link = f"{base_url}/einladung/{raw}"
    rendered = mail_templates.render("invitation", language, link=link, inviter=inviter)
    return await _deliver(settings, email, rendered, link)


async def send_password_reset(settings: AppSettings, *, raw: str, email: str, language: str, base_url: str) -> Delivery:
    link = f"{base_url}/passwort/{raw}"
    rendered = mail_templates.render("password_reset", language, link=link)
    return await _deliver(settings, email, rendered, link)
