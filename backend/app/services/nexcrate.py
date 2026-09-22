"""Zugriff auf nexcrate (``/api/v1``, Vertrag 1, ab Etappe V5 mit Musik).

⚠️ **nexbeat aendert nichts an nexcrates Einstellungen.** Geschrieben wird nur ``POST /api/v1/requests``
fuer ein Album oder einen ganzen Kuenstler. Fassung, Profil, Ordner und Indexer richtet der Betreiber in
nexcrate ein; fehlt etwas, sagt nexbeat es, statt es anzulegen.

Gemessen am 22.09.2026 gegen eine Wegwerf-Instanz (``docs/plan-nexcrate.md``):

- Eine Anfrage ist idempotent ueber Art und Kennung. Ein zweiter Aufruf antwortet ``unchanged``. Eine
  Uebergabe mit offenem Ausgang wird deshalb einfach noch einmal gesendet.
- Fehler kommen flach als ``{code, message, params}``. Ausserhalb von ``/api/v1`` (eine vertippte Adresse)
  in der Form der Oberflaeche, ``{"detail": {...}}``. Beide werden gelesen.
- ``album.tracks`` ist ``null``, bis nexcrate eine Zielausgabe gewaehlt hat.
- Kennungen nur klein: ``MBID:`` ist ``ref_source_unknown``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from . import http
from .settings_service import AppSettings

logger = logging.getLogger("nexbeat.nexcrate")

#: Ein unbekannter Kuenstler kostet nexcrate Anfragen bei MusicBrainz im Takt von gut einer Sekunde.
#: Gemessen 1,6 s; ein grosser Katalog braucht laenger.
SLOW_TIMEOUT = httpx.Timeout(90.0, connect=6.0)
#: Der Strom schickt alle 15 s ein Lebenszeichen. Kommt eine Minute lang nichts, ist er tot.
STREAM_TIMEOUT = httpx.Timeout(connect=6.0, read=60.0, write=10.0, pool=10.0)
#: Hoechstens so viele Eintraege nimmt ``titles/lookup`` je Aufruf.
LOOKUP_BATCH = 100
#: Was ein ganzer Kuenstler bringt (entschieden am 22.09.2026): nur Studioalben, auch kuenftige.
WHOLE_ARTIST = {"albums": "studio", "types": ["studio"]}
#: Die Rechte, um die nexbeat beim Koppeln bittet. ``operate`` braucht es nicht.
SCOPES = ["read", "request"]

#: nexcrates Codes, die nexbeat unter eigenem Namen fuehrt. Alles andere wird ``nexcrate_refused``.
REMOTE_CODES = {
    "api_key_missing": "nexcrate_key_rejected",
    "api_key_invalid": "nexcrate_key_rejected",
    "scope_missing": "nexcrate_scope_missing",
    "version_not_available": "nexcrate_no_music_version",
    "musicbrainz_not_found": "musicbrainz_not_found",
    "not_found": "nexcrate_path_unknown",
    "method_not_allowed": "nexcrate_path_unknown",
    "pairing_not_found": "nexcrate_pairing_gone",
    "pairing_limit": "nexcrate_busy",
    "rate_limited": "nexcrate_busy",
    "too_many_streams": "nexcrate_busy",
    "marker_too_old": "nexcrate_marker_too_old",
}


class NexcrateError(Exception):
    """``transient``: nichts ist passiert, spaeter noch einmal (Zeitueberschreitung, nicht erreichbar,
    ueberlastet, Fehler im Server). Weil Anfragen idempotent sind, schadet ein zweiter Versuch nie.
    ``remote`` ist nexcrates eigener Code, fuer Protokoll und Admin."""

    def __init__(
        self,
        code: str,
        detail: str = "",
        *,
        transient: bool = False,
        status_code: int | None = None,
        remote: str = "",
        params: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.transient = transient
        self.status_code = status_code
        self.remote = remote
        self.params = params or {}


def _error_from(response: httpx.Response, path: str) -> NexcrateError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if isinstance(body, dict) and isinstance(body.get("detail"), dict):
        body = body["detail"]
    remote = str(body.get("code") or "") if isinstance(body, dict) else ""
    params = body.get("params") if isinstance(body, dict) and isinstance(body.get("params"), dict) else {}
    message = str(body.get("message") or "") if isinstance(body, dict) else ""
    status = response.status_code
    detail = f"{remote}: {message}" if remote else f"HTTP {status}: {' '.join(response.text.split())[:200]}"
    if remote in REMOTE_CODES:
        code = REMOTE_CODES[remote]
    elif status in (401, 403):
        code = "nexcrate_key_rejected"
    elif status == 404 and not remote:
        code = "nexcrate_path_unknown"
    elif status >= 500 and not remote:
        # 22.09.2026: Waehrend nexcrate neu aufgespielt wurde, antwortete der Proxy davor mit 502 und einer
        # HTML-Seite. Das hiess "abgelehnt", obwohl nexcrate gar nicht lief.
        code = "nexcrate_unavailable"
    else:
        code = "nexcrate_refused"
    transient = status >= 500 or code == "nexcrate_busy"
    if status >= 400 and code == "nexcrate_refused":
        logger.warning("nexcrate answered %s to %s: %s", status, path, detail)
    return NexcrateError(code, detail, transient=transient, status_code=status, remote=remote, params=params)


class NexcrateClient:
    def __init__(self, base_url: str, api_key: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        return {**headers, **(extra or {})}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Any = None,
        json_body: Any = None,
        timeout: httpx.Timeout | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        url = f"{self.base_url}/api/v1{path}"
        options: dict[str, Any] = {"params": params, "headers": self._headers(headers)}
        if json_body is not None:
            options["json"] = json_body
        if timeout is not None:
            options["timeout"] = timeout
        try:
            response = await http.client("nexcrate", timeout=20.0).request(method, url, **options)
        except httpx.TimeoutException as error:
            raise NexcrateError("nexcrate_timeout", str(error), transient=True) from error
        except httpx.HTTPError as error:
            raise NexcrateError("nexcrate_unreachable", str(error), transient=True) from error
        if response.status_code >= 400:
            raise _error_from(response, path)
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as error:
            raise NexcrateError("nexcrate_unexpected_answer", response.text[:200]) from error

    async def system(self) -> dict[str, Any]:
        return await self._request("GET", "/system") or {}

    async def music_versions(self) -> list[dict[str, Any]]:
        """Die Musik-Fassung, null oder eine, mit Bereitschaft und Gruenden."""
        data = await self._request("GET", "/versions", params={"kind": "album"}) or {}
        return list(data.get("items") or [])

    async def lookup(self, items: list[dict[str, str]]) -> list[dict[str, Any]]:
        """Viele Titel auf einmal, Antwort in derselben Reihenfolge. Stuecke zu je 100."""
        found: list[dict[str, Any]] = []
        for start in range(0, len(items), LOOKUP_BATCH):
            chunk = items[start : start + LOOKUP_BATCH]
            data = await self._request("POST", "/titles/lookup", json_body={"items": chunk}) or {}
            found.extend(data.get("items") or [])
        return found

    async def title(self, kind: str, mbid: str) -> dict[str, Any] | None:
        try:
            return await self._request("GET", f"/titles/{kind}/{ref(mbid)}")
        except NexcrateError as error:
            if error.remote == "title_not_found" or (error.status_code == 404 and error.remote != "not_found"):
                return None
            raise

    async def titles(self, *, after: int, kind: str, limit: int = 500) -> dict[str, Any]:
        return await self._request("GET", "/titles", params={"after": after, "kind": kind, "limit": limit}) or {}

    async def request(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/requests", json_body=body, timeout=SLOW_TIMEOUT) or {}

    async def latest_event(self) -> int:
        data = await self._request("GET", "/events", params={"after": 0, "limit": 1}) or {}
        return int(data.get("latest") or 0)

    async def stream(self, after: int) -> AsyncIterator[dict[str, Any]]:
        """Die Ereignisse als Server-Sent Events, eins nach dem anderen, ab ``after``.

        nexcrate beendet den Strom nach einer Stunde; der Aufrufer verbindet dann neu.
        """
        url = f"{self.base_url}/api/v1/events/stream"
        try:
            async with http.client("nexcrate-stream", timeout=60.0).stream(
                "GET", url, params={"after": after}, headers=self._headers(), timeout=STREAM_TIMEOUT
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise _error_from(response, "/events/stream")
                data: list[str] = []
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data.append(line[5:].lstrip())
                    elif line == "" and data:
                        try:
                            event = json.loads("\n".join(data))
                        except ValueError:
                            event = None
                        data = []
                        if isinstance(event, dict):
                            yield event
        except httpx.TimeoutException as error:
            raise NexcrateError("nexcrate_timeout", str(error), transient=True) from error
        except httpx.HTTPError as error:
            raise NexcrateError("nexcrate_unreachable", str(error), transient=True) from error

    async def pairing_ask(self, app: str, scopes: list[str]) -> dict[str, Any]:
        return await self._request("POST", "/pairing", json_body={"app": app, "scopes": scopes}) or {}

    async def pairing_poll(self, pairing_id: str, secret: str) -> dict[str, Any]:
        return await self._request("GET", f"/pairing/{pairing_id}", headers={"X-Pairing-Secret": secret}) or {}


def ref(mbid: str) -> str:
    return f"mbid:{mbid.lower()}"


def mbid_of(value: str | None) -> str:
    return (value or "").partition(":")[2] if (value or "").startswith("mbid:") else ""


def client_for(settings: AppSettings) -> NexcrateClient | None:
    if settings.mode != "nex" or not settings.nexcrate_configured:
        return None
    return NexcrateClient(settings.text("nexcrate_url"), settings.text("nexcrate_api_key"))


@dataclass(frozen=True)
class AlbumView:
    """Ein Album aus nexcrate, in nexbeats Worten: ``available``, ``partial``, ``wanted`` oder ``known``."""

    state: str
    percent: int
    watched: bool


def _tracks(title: dict[str, Any]) -> tuple[int, int] | None:
    versions = title.get("versions") or []
    for source in ((versions[0].get("album") if versions else None) or {}, title.get("album") or {}):
        tracks = source.get("tracks") if isinstance(source, dict) else None
        if isinstance(tracks, dict) and tracks.get("total"):
            return int(tracks.get("have") or 0), int(tracks["total"])
    return None


def album_view(title: dict[str, Any]) -> AlbumView:
    """Zustand eines Albums aus ``title``, wie ``/api/v1`` es liefert.

    Ohne Fassung ist das Album nur eine Zeile im Katalog seines Kuenstlers (``known``). Mit Fassung zaehlt ihr
    Zustand; einen unbekannten Zustand nimmt nexbeat als ``wanted``, solange die Fassung ueberwacht ist
    (Form 1 des Vertrags: Unbekanntes dulden).
    """
    versions = title.get("versions") or []
    tracks = _tracks(title)
    percent = min(100, round(100 * tracks[0] / tracks[1])) if tracks else 0
    if not versions:
        return AlbumView("known", 0, False)
    version = versions[0]
    state = version.get("state")
    monitored = bool(version.get("monitored"))
    if state in ("available", "upgrade") or (tracks and tracks[0] >= tracks[1]):
        return AlbumView("available", 100, monitored)
    if tracks and tracks[0] > 0:
        return AlbumView("partial", percent, monitored)
    if state == "incomplete":
        return AlbumView("partial", percent, monitored)
    if not monitored or state == "unmonitored":
        return AlbumView("known", 0, False)
    return AlbumView("wanted", 0, True)
