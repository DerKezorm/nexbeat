"""Arbeit im Hintergrund.

Zwei Schleifen. Die erste gleicht alle zehn Minuten den Lidarr-Bestand ab,
sieht alle zwei Minuten nach offenen Anfragen und raeumt einmal am Tag auf. Die
zweite waermt die Empfehlungen vor, alle sechs Stunden. Sie ist getrennt, weil
sie Minuten dauern kann und den Anfragestand nicht aufhalten soll.

Ein Webhook von Lidarr weckt die erste Schleife vorzeitig. Seinem Inhalt wird
nicht geglaubt, er ist nur der Anstoss, bei Lidarr nachzusehen.

Im NEX-Modus weckt nexcrates Ereignisstrom (``nexcrate_events``, eine dritte
Schleife). Ein Ereignis zu einem Kuenstler laesst dabei auch den Bestand vorzeitig
nachlesen; das kostet nur die Aenderungen seit der letzten Nummer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable
from typing import Any

from ..db import SessionLocal
from . import cache, library, nexcrate_events, recommendations, requests_service, sitzung, tokens, updates
from .settings_service import load_settings

logger = logging.getLogger("nexbeat.poller")

REQUEST_INTERVAL = 120.0
LIBRARY_INTERVAL = 600.0
WARM_INTERVAL = 6 * 3600.0
PURGE_INTERVAL = 24 * 3600.0
START_DELAY = 5.0
WARM_START_DELAY = 45.0
#: Eine Serie von Webhooks soll eine Runde ergeben, nicht zehn.
MIN_ROUND_GAP = 10.0

_wake_event: asyncio.Event | None = None
_library_due = False


def wake(library_too: bool = False) -> None:
    global _library_due
    if library_too:
        _library_due = True
    if _wake_event is not None:
        _wake_event.set()


async def _guarded(label: str, awaitable: Awaitable[Any]) -> None:
    try:
        await awaitable
    except Exception:
        logger.exception("Background task '%s' failed", label)


async def _wait(stop: asyncio.Event, seconds: float, wake_event: asyncio.Event | None = None) -> bool:
    """Warten, bis die Zeit um ist, ein Weckruf kommt oder gestoppt wird. True heisst: stoppen."""
    waiters = [asyncio.create_task(stop.wait())]
    if wake_event is not None:
        waiters.append(asyncio.create_task(wake_event.wait()))
    try:
        await asyncio.wait(waiters, timeout=seconds, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiter in waiters:
            waiter.cancel()
    return stop.is_set()


async def _requests_loop(stop: asyncio.Event) -> None:
    global _wake_event, _library_due
    _wake_event = asyncio.Event()
    last = {"library": float("-inf"), "purge": float("-inf")}
    if await _wait(stop, START_DELAY):
        return
    while not stop.is_set():
        started = time.monotonic()
        with SessionLocal() as db:
            settings = load_settings(db)
            if _library_due or started - last["library"] >= LIBRARY_INTERVAL:
                last["library"] = started
                _library_due = False
                await _guarded("library sync", library.sync_artists(db, settings))
            await _guarded("request status", requests_service.refresh_open(db, settings))
            # Einmal am Tag, damit der Hinweis im Menue steht, ohne dass jemand die Ueber-Seite oeffnet.
            await _guarded("update check", updates.status(enabled=settings.flag("update_check")))
            if started - last["purge"] >= PURGE_INTERVAL:
                last["purge"] = started
                try:
                    cache.purge_expired(db)
                    tokens.purge_expired(db)
                    sitzung.purge_revoked(db)
                except Exception:
                    logger.exception("Background task 'purge' failed")
        _wake_event.clear()
        if await _wait(stop, REQUEST_INTERVAL, _wake_event):
            return
        remaining = MIN_ROUND_GAP - (time.monotonic() - started)
        if remaining > 0 and await _wait(stop, remaining):
            return


async def _warm_loop(stop: asyncio.Event) -> None:
    if await _wait(stop, WARM_START_DELAY):
        return
    while not stop.is_set():
        with SessionLocal() as db:
            await _guarded("recommendation warm-up", recommendations.warm(db, load_settings(db)))
        if await _wait(stop, WARM_INTERVAL):
            return


async def run(stop: asyncio.Event) -> None:
    await asyncio.gather(_requests_loop(stop), _warm_loop(stop), nexcrate_events.run(stop, wake))
