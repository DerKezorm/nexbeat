"""Albumcover aus dem Cover Art Archive, einmal geholt und auf der Platte gehalten.

18.11.2026 gemessen: Ein Cover brauchte direkt vom Cover Art Archive 2 bis 7 Sekunden, jedes Mal wieder.
Die Adresse leitet zweimal weiter (``307`` nach archive.org, ``302`` auf einen Speicherknoten), keine der
Antworten darf der Browser behalten, und archive.org spricht HTTP/1.1 mit sechs Verbindungen je Browser.
Eine Startseite mit 58 Covern lud so eine halbe Minute nach. Seitdem holt nexbeat jedes Cover einmal
selbst und liefert es mit langer Gueltigkeit aus.

⚠️ Ohne Anmeldung erreichbar wie die Kuenstlerbilder, weil ``<img>`` keinen Authorization-Kopf mitschickt.
Angenommen werden nur die Adressformen, die nexbeat selbst ausgibt, nur bei coverartarchive.org, nur in den
Groessen 250 und 500. Ein fehlendes Cover merkt sich nexbeat eine Woche, damit sich die Adresse nicht zum
Anstossen von Abrufen missbrauchen laesst.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from ..config import get_settings
from . import cache, http

logger = logging.getLogger("nexbeat.covers")

BASE_URL = "https://coverartarchive.org"
PUBLIC_PREFIX = "/api/images/cover"
_MBID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_NAMES = {
    "release-group": re.compile(r"^front-(250|500)$"),
    "release": re.compile(r"^[0-9]{1,20}-(250|500)\.jpg$"),
}
_SOURCE = re.compile(rf"^{re.escape(BASE_URL)}/(release-group|release)/({_MBID})/([^/?#]+)$")
_VALID_MBID = re.compile(rf"^{_MBID}$")

MAX_BYTES = 5 * 1024 * 1024
TTL_MISSING = timedelta(days=7)
#: So viele Cover holt nexbeat gleichzeitig. Mehr nimmt archive.org ohnehin nicht schneller an.
FETCH_CONCURRENCY = 6
#: Cover, die so lange niemand abgerufen hat, raeumt das taegliche Aufraeumen weg.
KEEP_UNUSED = timedelta(days=90)
#: Seltener als so stellt nexbeat die Uhr einer Datei nicht nach, damit nicht jeder Abruf schreibt.
TOUCH_AFTER = timedelta(days=1)
#: So lange darf der Browser ein Cover behalten.
BROWSER_MAX_AGE = int(timedelta(days=30).total_seconds())

_running: dict[str, asyncio.Task[Path | None]] = {}
_gate: asyncio.Semaphore | None = None
_gate_loop: asyncio.AbstractEventLoop | None = None


class CoverUnavailable(Exception):
    """Das Cover Art Archive hat gerade nicht geantwortet. Nichts wird gemerkt."""


@dataclass(frozen=True)
class Cover:
    kind: str
    mbid: str
    name: str

    @property
    def source(self) -> str:
        return f"{BASE_URL}/{self.kind}/{self.mbid}/{self.name}"

    @property
    def key(self) -> str:
        return f"{self.kind}/{self.mbid}/{self.name}"


def parse(kind: str, mbid: str, name: str) -> Cover | None:
    """Nur was nexbeat selbst ausgibt. Alles andere ist kein Cover."""
    pattern = _NAMES.get(kind)
    if pattern is None or not _VALID_MBID.match(mbid) or not pattern.match(name):
        return None
    return Cover(kind, mbid, name)


def served(url: str) -> str:
    """Die Adresse, unter der nexbeat ein Cover ausliefert. Fremde Adressen bleiben, wie sie sind."""
    match = _SOURCE.match(url or "")
    if match is None or parse(*match.groups()) is None:
        return url or ""
    kind, mbid, name = match.groups()
    return f"{PUBLIC_PREFIX}/{kind}/{mbid}/{name}"


def directory() -> Path:
    return get_settings().data_dir / "covers"


def path_for(cover: Cover) -> Path:
    return directory() / cover.kind / cover.mbid[:2] / cover.mbid / f"{cover.name.removesuffix('.jpg')}.img"


def missing_key(cover: Cover) -> str:
    return f"caa:missing:{cover.key}"


def media_type(head: bytes) -> str:
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head.startswith(b"GIF8"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _store(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{path.name}.{os.getpid()}.part")
    partial.write_bytes(content)
    os.replace(partial, path)


def _touch(path: Path) -> None:
    try:
        if time.time() - path.stat().st_mtime > TOUCH_AFTER.total_seconds():
            os.utime(path)
    except OSError:
        pass


async def _download(cover: Cover) -> Path | None:
    """Holt das Cover. ``None``: Es gibt keins. ``CoverUnavailable``: gerade keine Antwort."""
    try:
        response = await http.client("coverart", timeout=20.0).get(cover.source)
    except httpx.HTTPError as error:
        logger.info("Cover Art Archive unreachable for %s: %s", cover.key, error)
        raise CoverUnavailable() from error
    if response.status_code == 404:
        return None
    content_type = response.headers.get("content-type", "")
    if response.status_code != 200 or not content_type.startswith("image/"):
        logger.info("Cover Art Archive answered %s (%s) for %s", response.status_code, content_type, cover.key)
        raise CoverUnavailable()
    if len(response.content) > MAX_BYTES:
        logger.info("Cover %s is larger than %d bytes, not kept", cover.key, MAX_BYTES)
        raise CoverUnavailable()
    path = path_for(cover)
    await asyncio.to_thread(_store, path, response.content)
    return path


def _fetch_once(cover: Cover) -> asyncio.Task[Path | None]:
    """Laufen zwei Abrufe fuer dasselbe Cover, holt nexbeat es trotzdem nur einmal."""
    global _gate, _gate_loop
    running = _running.get(cover.key)
    if running is not None and not running.done():
        return running
    loop = asyncio.get_running_loop()
    if _gate is None or _gate_loop is not loop:
        _gate = asyncio.Semaphore(FETCH_CONCURRENCY)
        _gate_loop = loop
    gate = _gate

    async def run() -> Path | None:
        try:
            async with gate:
                return await _download(cover)
        finally:
            if _running.get(cover.key) is task:
                del _running[cover.key]

    task = loop.create_task(run())
    _running[cover.key] = task
    return task


async def obtain(db: Session, cover: Cover) -> Path | None:
    """Die Datei des Covers, bei Bedarf erst geholt. ``None``: Das Archiv hat keins."""
    path = path_for(cover)
    if path.is_file():
        _touch(path)
        return path
    if cache.read(db, missing_key(cover)) is not None:
        return None
    # Bricht der Browser ab, laeuft der Abruf weiter: Das naechste Mal liegt das Cover dann schon da.
    found = await asyncio.shield(_fetch_once(cover))
    if found is None:
        cache.write(db, missing_key(cover), True, TTL_MISSING)
    return found


def purge_unused(now: float | None = None) -> int:
    """Cover, die lange niemand abgerufen hat, und liegengebliebene Teilstuecke."""
    root = directory()
    if not root.is_dir():
        return 0
    moment = now if now is not None else time.time()
    limit = moment - KEEP_UNUSED.total_seconds()
    # Ein Teilstueck, das gerade geschrieben wird, bleibt; eins von vor einer Stunde ist liegengeblieben.
    partial_limit = moment - 3600
    removed = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            mtime = path.stat().st_mtime
            if mtime < (partial_limit if path.suffix == ".part" else limit):
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed
