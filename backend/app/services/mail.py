"""E-Mail-Versand ueber einen eigenen SMTP-Server.

Mit der Standardbibliothek. ``smtplib`` blockiert, deshalb laeuft der Versand
in einem Thread. Fehler tragen eine Kennung statt eines Satzes, den Satz baut
die Oberflaeche in der eingestellten Sprache.
"""

from __future__ import annotations

import asyncio
import logging
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

logger = logging.getLogger("nexbeat.mail")

TIMEOUT_SECONDS = 15
ADDRESS_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SECURITY_MODES = ("none", "starttls", "ssl")


class MailError(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class MailConfig:
    host: str
    port: int
    security: str
    username: str
    password: str
    from_address: str
    from_name: str

    @property
    def configured(self) -> bool:
        return bool(self.host and self.from_address)


def valid_address(address: str) -> bool:
    return bool(ADDRESS_PATTERN.match(address.strip()))


def _connect(config: MailConfig) -> smtplib.SMTP:
    # Zertifikate werden geprueft. Ein selbst ausgestelltes faellt auf, statt
    # still eine unverschluesselte Verbindung vorzutaeuschen.
    context = ssl.create_default_context()
    try:
        if config.security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(config.host, config.port, timeout=TIMEOUT_SECONDS, context=context)
        else:
            server = smtplib.SMTP(config.host, config.port, timeout=TIMEOUT_SECONDS)
            if config.security == "starttls":
                server.starttls(context=context)
                server.ehlo()
    except ssl.SSLError as error:
        raise MailError("mail_tls_failed", str(error)) from error
    except TimeoutError as error:
        raise MailError("mail_timeout", str(error)) from error
    except ConnectionRefusedError as error:
        raise MailError("mail_connection_refused", str(error)) from error
    except OSError as error:
        code = "mail_host_unknown" if "getaddrinfo" in str(error) else "mail_connect_failed"
        raise MailError(code, str(error)) from error
    except smtplib.SMTPException as error:
        raise MailError("mail_connect_failed", str(error)) from error

    if config.username:
        try:
            server.login(config.username, config.password)
        except smtplib.SMTPException as error:
            server.close()
            raise MailError("mail_login_failed", str(error)) from error
    return server


def _check(config: MailConfig) -> None:
    server = _connect(config)
    try:
        server.noop()
    finally:
        server.quit()


def _send(config: MailConfig, message: EmailMessage) -> None:
    server = _connect(config)
    try:
        server.send_message(message)
    except smtplib.SMTPRecipientsRefused as error:
        raise MailError("mail_recipient_refused", str(error)) from error
    except smtplib.SMTPSenderRefused as error:
        raise MailError("mail_sender_refused", str(error)) from error
    except smtplib.SMTPException as error:
        raise MailError("mail_rejected", str(error)) from error
    finally:
        server.quit()


async def verify(config: MailConfig) -> None:
    """Verbindung und Anmeldung pruefen, ohne etwas zu verschicken."""
    if not config.host:
        raise MailError("mail_not_configured")
    await asyncio.to_thread(_check, config)


async def send(config: MailConfig, to: str, subject: str, html: str, text: str) -> None:
    """Immer mit Text- und HTML-Fassung. Reines HTML landet eher im Spam."""
    if not config.configured:
        raise MailError("mail_not_configured")
    if not valid_address(to):
        raise MailError("invalid_email")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((config.from_name or "nexbeat", config.from_address))
    message["To"] = to.strip()
    message["Message-ID"] = make_msgid(domain=config.from_address.split("@")[-1])
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    await asyncio.to_thread(_send, config, message)
    # Die Adresse bleibt aus dem Protokoll heraus.
    logger.info("Mail %r sent via %s", subject, config.host)
