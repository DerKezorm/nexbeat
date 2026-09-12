"""Vorgangsnummer je Anfrage und das Format der Protokollzeilen.

Jede Zeile zeigt ``[vorgang u:benutzer]``. Die Nummer steht auch in der
Kopfzeile ``X-Request-Id`` und in jeder 500er-Antwort, damit sich eine Meldung
aus der Oberflaeche im Protokoll wiederfinden laesst.
"""

from __future__ import annotations

import contextvars
import logging
import secrets
from typing import Any

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_actor: contextvars.ContextVar[str] = contextvars.ContextVar("actor", default="-")


def current_request_id() -> str:
    return _request_id.get()


def set_actor(name: str) -> None:
    _actor.set(name)


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.rid = _request_id.get()
        record.actor = _actor.get()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(_ContextFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(rid)s u:%(actor)s] %(name)s: %(message)s"))
    logger = logging.getLogger("nexbeat")
    logger.handlers[:] = [handler]
    logger.setLevel(level)
    logger.propagate = False


class RequestIdMiddleware:
    """Reines ASGI statt BaseHTTPMiddleware, damit Streaming-Antworten nicht puffern."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = secrets.token_hex(3)
        # Auch im Scope, denn die Fehlerbehandlung fuer 500 laeuft ausserhalb
        # dieser Middleware und sieht die Kontextvariable nicht mehr.
        scope.setdefault("state", {})["request_id"] = rid
        rid_token = _request_id.set(rid)
        actor_token = _actor.set("-")

        async def send_with_id(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", rid.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            _request_id.reset(rid_token)
            _actor.reset(actor_token)
