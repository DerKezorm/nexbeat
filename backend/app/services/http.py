"""Gemeinsame HTTP-Verbindungen zu Lidarr und den Metadaten-Diensten.

Ein Client je Dienst, einmal angelegt: Jede neue Verbindung kostet TLS-Handschlag
und Namensaufloesung. Tests setzen mit ``use_transport`` eine Attrappe darunter,
die jede Anfrage beantwortet, ohne das Netz zu beruehren.
"""

from __future__ import annotations

import httpx

from .. import __version__

# MusicBrainz verlangt eine Kontaktmoeglichkeit im User-Agent.
USER_AGENT = f"nexbeat/{__version__} ( https://github.com/DerKezorm/nexbeat )"

_clients: dict[str, httpx.AsyncClient] = {}
_transport: httpx.AsyncBaseTransport | None = None


def client(name: str, timeout: float = 15.0) -> httpx.AsyncClient:
    existing = _clients.get(name)
    if existing is not None and not existing.is_closed:
        return existing
    created = httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=6.0),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        follow_redirects=True,
        transport=_transport,
        limits=httpx.Limits(max_connections=8, max_keepalive_connections=8, keepalive_expiry=60.0),
    )
    _clients[name] = created
    return created


def use_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Nur fuer Tests: Alle Clients entstehen neu, mit dieser Attrappe darunter."""
    global _transport
    _transport = transport
    _clients.clear()


async def close_all() -> None:
    for existing in list(_clients.values()):
        await existing.aclose()
    _clients.clear()
