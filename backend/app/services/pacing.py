"""Mindestabstand zu fremden Diensten, prozessweit.

MusicBrainz lehnt schneller als eine Anfrage pro Sekunde ab, Deezer bei vielen
Anfragen auf einmal. Beide bekommen deshalb eine Schlange mit festem Abstand.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


class Spacer:
    """Haelt zwischen zwei Anfragen den Mindestabstand ein, prozessweit."""

    def __init__(
        self,
        interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.interval = interval
        self.clock = clock
        self.sleep = sleep
        self._next = 0.0
        self._lock: asyncio.Lock | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _get_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._loop is not loop:
            self._lock = asyncio.Lock()
            self._loop = loop
        return self._lock

    async def wait(self) -> None:
        async with self._get_lock():
            now = self.clock()
            delay = self._next - now
            if delay > 0:
                await self.sleep(delay)
            self._next = max(now, self._next) + self.interval
