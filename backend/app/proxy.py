"""Das Schema, das ein vertrauter Proxy meldet.

uvicorn nimmt ``X-Forwarded-Proto`` nur, wenn der ganze Wert genau ``http`` oder ``https`` ist. Ein Proxy, der an einen
mitgeschickten Kopf anhaengt ("http, https") oder ``HTTPS`` schreibt, gilt dann nicht, und die Anmeldung baut ihre
Rueckleitadresse mit ``http``. Diese Schicht sitzt vor uvicorns eigener und nimmt, nur fuer einen vertrauten Absender,
den RECHTESTEN Wert (den der Proxy schrieb; alles links davon kann vom Besucher stammen), ohne Ruecksicht auf Gross-
und Kleinschreibung, und nur ``http`` oder ``https``. Bei einem WebSocket wird daraus ``ws`` oder ``wss``. Den
Absender (``X-Forwarded-For``) setzt weiter uvicorns ``ProxyHeadersMiddleware``; ihr Schema (sie naehme auch ``wss``
fuer eine gewoehnliche Anfrage) wird danach wieder durch dieses ersetzt.

Vertraut wird den Adressen in ``FORWARDED_ALLOW_IPS`` (uvicorns eigene Einstellung: Adressen, Netze wie
``172.16.0.0/12``, ``*`` fuer alle), fuer Schema und Absender gleich. Ab Werk keinem (Bauplan OIDC, "Hinter einem
Proxy"): bis 1.4.0 galt uvicorns Vorgabe ``127.0.0.1``. Im Container mit eigenem Netz kommt von dort nur der Container
selbst, mit ``network_mode: host`` oder ohne Container aber jedes Programm auf dem Rechner, und das gab sich so ein
anderes Schema und fuer die Bremse eine andere Adresse. Das Abbild startet uvicorn mit ``--no-proxy-headers`` und
``app.main:asgi``; sonst laege uvicorns eigene Middleware aussen und glaubte ``127.0.0.1`` doch.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any

from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware, _TrustedHosts

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]

#: Ab Werk wird keinem Absender getraut.
DEFAULT_TRUSTED = ""


def trusted_proxies() -> str:
    return os.environ.get("FORWARDED_ALLOW_IPS", "").strip() or DEFAULT_TRUSTED


def forwarded_scheme(headers: list[tuple[bytes, bytes]]) -> str | None:
    """``http`` oder ``https`` aus dem rechtesten Wert des letzten ``X-Forwarded-Proto``, sonst None."""
    value: bytes | None = None
    for name, raw in headers:
        if name.lower() == b"x-forwarded-proto":
            value = raw
    if value is None:
        return None
    last = value.decode("latin1").rsplit(",", 1)[-1].strip().lower()
    return last if last in ("http", "https") else None


_KEPT = "nexbeat.scheme"


class ForwardedScheme:
    def __init__(self, app: Any, trusted: str) -> None:
        self.app = app
        self.trusted = _TrustedHosts(trusted)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            scheme = scope.get("scheme", "http")
            client = scope.get("client")
            # Wie in uvicorns Middleware: ohne Absender (Unix-Socket) traut nur ``*``.
            if (client[0] if client else None) in self.trusted:
                forwarded = forwarded_scheme(scope["headers"])
                if forwarded is not None:
                    scheme = forwarded.replace("http", "ws") if scope["type"] == "websocket" else forwarded
            scope[_KEPT] = scheme
        await self.app(scope, receive, send)


class _KeepScheme:
    """Innen, hinter uvicorns Middleware: das Schema von ``ForwardedScheme`` zurueck."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if _KEPT in scope:
            scope["scheme"] = scope.pop(_KEPT)
        await self.app(scope, receive, send)


def behind_proxy(app: Any, trusted: str) -> Any:
    """``app`` mit der Behandlung der vertrauten Proxys: dieses Schema, uvicorns Absender."""
    return ForwardedScheme(ProxyHeadersMiddleware(_KeepScheme(app), trusted_hosts=trusted), trusted)
