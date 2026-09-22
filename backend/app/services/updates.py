"""Nachsehen, ob es eine neuere nexbeat-Fassung gibt.

Hoechstens einmal am Tag fragt nexbeat die oeffentliche GitHub-API nach der neuesten Veroeffentlichung. Uebertragen
wird dabei nichts ausser der Anfrage selbst mit der ueblichen Programmkennung: keine Konten, keine Einstellungen,
keine Titel. Ab Werk an, abschaltbar auf der Seite "Ueber nexbeat" (Schluessel ``update_check``). Aufbau wie in
nexpulse.

Grundsatz: Die Pruefung ist Beiwerk. Faellt GitHub aus oder ist kein Netz da, geht in der Oberflaeche nichts kaputt,
es steht dort nur kein Hinweis. Ein Hinweis, der falsch ist, waere schlimmer als keiner.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from .. import __version__
from . import http

logger = logging.getLogger("nexbeat.updates")

REPO = "DerKezorm/nexbeat"
REPO_URL = f"https://github.com/{REPO}"
RELEASES_URL = f"{REPO_URL}/releases"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
#: Hoechstens einmal am Tag. Ohne Anmeldung erlaubt GitHub 60 Anfragen je Stunde und Adresse.
CHECK_INTERVAL = timedelta(hours=24)
#: Nach einem Fehlschlag frueher noch einmal, aber nicht bei jedem Seitenaufruf.
RETRY_AFTER = timedelta(hours=6)

_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


@dataclass(frozen=True)
class UpdateStatus:
    current: str
    latest: str | None = None
    available: bool = False
    checked_at: datetime | None = None


_cached: UpdateStatus | None = None
_failed_at: datetime | None = None
_lock = asyncio.Lock()


def parse_version(text: str) -> tuple[int, int, int] | None:
    """``"v1.2.3"`` -> ``(1, 2, 3)``. Zusaetze wie ``-beta`` zaehlen nicht, Unlesbares ist ``None``."""
    found = _VERSION.match((text or "").strip())
    return (int(found[1]), int(found[2]), int(found[3])) if found else None


def is_newer(latest: str, current: str) -> bool:
    """Nur ja, wenn beide lesbar sind und ``latest`` groesser ist."""
    a, b = parse_version(latest), parse_version(current)
    return a is not None and b is not None and a > b


async def _ask() -> str | None:
    response = await http.client("github", timeout=6.0).get(API_URL, headers={"Accept": "application/vnd.github+json"})
    # 404: es gibt noch keine Veroeffentlichung. Kein Fehler.
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return str((response.json() or {}).get("tag_name") or "").strip() or None


def cached() -> UpdateStatus | None:
    """Der letzte Stand, ohne Anfrage nach draussen (fuer Menue und Kopf)."""
    return _cached


async def status(*, enabled: bool, force: bool = False) -> UpdateStatus:
    """Aus dem Zwischenspeicher oder frisch von GitHub. ``enabled=False`` geht nie nach draussen."""
    global _cached, _failed_at
    if not enabled:
        return UpdateStatus(current=__version__)
    now = datetime.now(UTC)

    def fresh() -> bool:
        if _cached is not None and _cached.checked_at is not None and now - _cached.checked_at < CHECK_INTERVAL:
            return True
        return _failed_at is not None and now - _failed_at < RETRY_AFTER

    if not force and fresh():
        return _cached or UpdateStatus(current=__version__)
    async with _lock:
        if not force and fresh():
            return _cached or UpdateStatus(current=__version__)
        try:
            latest = await _ask()
        except (httpx.HTTPError, ValueError) as error:
            logger.warning("Version check at GitHub failed: %s", error)
            _failed_at = now
            return _cached or UpdateStatus(current=__version__)
        _failed_at = None
        _cached = UpdateStatus(
            current=__version__,
            latest=latest,
            available=bool(latest) and is_newer(latest or "", __version__),
            checked_at=datetime.now(UTC),
        )
        if _cached.available:
            logger.info("A newer nexbeat is out: %s (running %s)", latest, __version__)
        return _cached


def reset() -> None:
    """Nur fuer Tests."""
    global _cached, _failed_at
    _cached = None
    _failed_at = None
