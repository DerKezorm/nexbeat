"""nexcrates Ereignisstrom als Wecker fuer den Abgleich (NEX-Modus).

Entschieden am 22.09.2026: Der Strom weckt, der Abgleich zaehlt. nexbeat glaubt einem Ereignis nichts ausser
"bei Musik hat sich etwas getan" und sieht dann ueber ``titles/lookup`` selbst nach. Faellt der Strom aus, laeuft
der Abgleich wie ohne ihn alle zwei Minuten; es geht also nichts verloren, es kommt nur spaeter.

Gemessen: Was aus nexcrates Verlauf kommt (Anfrage, Zuruecknehmen), ist nach gut einer Sekunde da, was die
Aenderungsmarke sieht (neuer Kuenstler, geaenderter Zustand), nach bis zu gut zehn Sekunden. nexcrate beendet
den Strom nach einer Stunde, nexbeat verbindet dann mit der letzten Nummer neu. Hoechstens fuenf Stroeme je
Schluessel, darueber ``429 too_many_streams``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ..db import SessionLocal
from ..models import utcnow
from . import nexcrate
from .settings_service import load_settings

logger = logging.getLogger("nexbeat.nexcrate.events")

#: Nach einem Fehler so lange warten, bevor der Strom neu verbunden wird.
RETRY_AFTER = 30.0
#: Ohne NEX-Modus oder Verbindung so oft nachsehen, ob sich das geaendert hat.
IDLE_CHECK = 30.0
MUSIC_KINDS = ("album", "artist")
#: Ereignisse, nach denen sich der Bestand an Kuenstlern geaendert haben kann.
LIBRARY_TYPES = ("title.added", "title.removed", "title.changed")

_restart: asyncio.Event | None = None
_status: dict[str, Any] = {
    "connected": False,
    "since": None,
    "last_event_at": None,
    "last_seq": None,
    "error": None,
    "detail": None,
}


def status() -> dict[str, Any]:
    return {
        **_status,
        "since": _iso(_status["since"]),
        "last_event_at": _iso(_status["last_event_at"]),
    }


def _iso(value: datetime | None) -> str | None:
    # ``utcnow`` ist ohne Zone. Ohne "Z" las der Browser die Zeit als Ortszeit (zwei Stunden daneben).
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z") if value else None


def restart() -> None:
    """Nach einer Aenderung an Adresse, Schluessel oder Modus: neu verbinden, von vorn."""
    _status["last_seq"] = None
    if _restart is not None:
        _restart.set()


def relevant(event: dict[str, Any]) -> tuple[bool, bool]:
    """(Abgleich wecken?, Bestand neu lesen?) fuer ein Ereignis."""
    title = event.get("title") or {}
    kind = title.get("kind") if isinstance(title, dict) else None
    kind = kind or (event.get("params") or {}).get("kind")
    if kind not in MUSIC_KINDS:
        return False, False
    return True, event.get("type") in LIBRARY_TYPES and kind == "artist"


async def _consume(client: nexcrate.NexcrateClient, wake: Callable[[bool], None]) -> None:
    after = _status["last_seq"]
    if after is None:
        after = await client.latest_event()
    _status.update(connected=True, since=utcnow(), error=None, detail=None, last_seq=after)
    logger.info("Listening to nexcrate events after %s", after)
    async for event in client.stream(after):
        seq = event.get("seq")
        if isinstance(seq, int):
            _status["last_seq"] = seq
        _status["last_event_at"] = utcnow()
        wake_up, library = relevant(event)
        if wake_up:
            wake(library)


async def run(stop: asyncio.Event, wake: Callable[[bool], None]) -> None:
    global _restart
    _restart = asyncio.Event()
    while not stop.is_set():
        with SessionLocal() as db:
            client = nexcrate.client_for(load_settings(db))
        if client is None:
            _status.update(connected=False, error=None)
            await _pause(stop, IDLE_CHECK)
            continue
        _restart.clear()
        task = asyncio.create_task(_consume(client, wake))
        waiters = [asyncio.create_task(stop.wait()), asyncio.create_task(_restart.wait())]
        await asyncio.wait([task, *waiters], return_when=asyncio.FIRST_COMPLETED)
        for waiter in waiters:
            waiter.cancel()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            _status["connected"] = False
            continue
        _status["connected"] = False
        error = task.exception()
        if error is None:
            # nexcrate hat den Strom nach seiner Stunde beendet: gleich weiter, ab der letzten Nummer.
            continue
        if isinstance(error, nexcrate.NexcrateError):
            if error.code == "nexcrate_marker_too_old":
                _status["last_seq"] = None
            _status["error"] = error.code
            _status["detail"] = error.detail[:300]
            logger.info("nexcrate event stream stopped: %s (%s)", error.code, error.detail[:300])
        else:
            _status["error"] = "nexcrate_unexpected_answer"
            logger.exception("nexcrate event stream failed", exc_info=error)
        # Verpasst wurde womoeglich etwas: einmal nachsehen, dann warten.
        wake(True)
        await _pause(stop, RETRY_AFTER)


async def _pause(stop: asyncio.Event, seconds: float) -> None:
    waiters = [asyncio.create_task(stop.wait())]
    if _restart is not None:
        waiters.append(asyncio.create_task(_restart.wait()))
    try:
        await asyncio.wait(waiters, timeout=seconds, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiter in waiters:
            waiter.cancel()
