"""Viele gleichzeitige Anfragen, die waehrend eines Netzaufrufs eine Sitzung halten.

12.09.2026 auf einer echten Installation hinter einem HTTP/2-Proxy: Die Startseite lud rund 40
Kuenstlerbilder auf einmal. Jede Anfrage hielt ihre Datenbankverbindung, waehrend sie auf Deezer
wartete. Der Pool gab 15 her, die sechzehnte wartete blockierend auf eine freie Verbindung und
hielt damit die Ereignisschleife an, auch fuer die Anfragen, die ihre Verbindung gerade
zurueckgeben wollten. nexbeat antwortete nicht mehr, der Proxy meldete 504.
"""

from __future__ import annotations

import asyncio
import threading

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Setting


async def _hold_a_session_while_waiting() -> None:
    with SessionLocal() as db:
        db.execute(select(Setting.key)).first()
        # Steht fuer den Aufruf bei Deezer, MusicBrainz oder Lidarr.
        await asyncio.sleep(0.05)


def test_many_requests_waiting_on_a_service_do_not_freeze_the_server() -> None:
    finished = threading.Event()

    def burst() -> None:
        async def at_once() -> None:
            await asyncio.gather(*(_hold_a_session_while_waiting() for _ in range(40)))

        asyncio.run(at_once())
        finished.set()

    # In einem eigenen Faden: Friert die Schleife ein, laeuft die Pruefung trotzdem weiter.
    threading.Thread(target=burst, daemon=True).start()
    assert finished.wait(timeout=10), "40 requests holding a session at once froze the event loop"
