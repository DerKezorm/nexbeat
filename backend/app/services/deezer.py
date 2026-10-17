"""Deezer: Kuenstlerbilder und 30-Sekunden-Hoerproben.

Optional und ab Werk aus. Die Schnittstelle antwortet ohne Token, das
Entwicklerportal vergibt seit etwa Mitte 2025 keine neuen Tokens. Ob nexbeat sie
fragt, entscheidet der Betreiber in den Einstellungen, und nichts in nexbeat
haengt davon ab.

Deezer kennt keine MusicBrainz-Kennungen. Die Zuordnung laeuft ueber den Verweis auf die
Deezer-Seite, den MusicBrainz bei vielen Kuenstlern fuehrt (``catalog.deezer_artist_for``), sonst
ueber den Namen. Gezaehlt werden dann nur exakte Treffer. Ein falsches Bild ist schlimmer als gar keins.

⚠️ Viele Anfragen auf einmal lehnt Deezer ab. Gemessen am 11.09.2026: Beim ersten
Aufbau der Startseite kamen binnen 0,7 Sekunden 15 Ablehnungen mit "Quota limit
exceeded". Deshalb ein fester Abstand, prozessweit wie bei MusicBrainz.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

import httpx

from . import http
from .pacing import Spacer

logger = logging.getLogger("nexbeat.deezer")

BASE_URL = "https://api.deezer.com"
MIN_INTERVAL_SECONDS = 0.15

spacer = Spacer(MIN_INTERVAL_SECONDS)


class DeezerError(Exception):
    def __init__(self, code: str = "deezer_unavailable") -> None:
        super().__init__(code)
        self.code = code


#: Deezers Kennung fuer "gibt es nicht", etwa ein Kuenstler, den Deezer entfernt hat.
NO_DATA = 800


async def _get(path: str, params: dict[str, Any] | None = None, *, missing_ok: bool = False) -> dict[str, Any]:
    await spacer.wait()
    try:
        response = await http.client("deezer").get(f"{BASE_URL}{path}", params=params)
    except httpx.HTTPError as error:
        raise DeezerError() from error
    if response.status_code >= 400:
        raise DeezerError()
    try:
        data = response.json()
    except ValueError as error:
        raise DeezerError() from error
    # Deezer meldet Fehler mit Status 200 und einem ``error``-Feld.
    if isinstance(data, dict) and data.get("error"):
        if missing_ok and (data["error"] or {}).get("code") == NO_DATA:
            return {}
        logger.info("Deezer refused %s: %s", path, data.get("error"))
        raise DeezerError()
    return data if isinstance(data, dict) else {}


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", plain.casefold())


async def find_artist(name: str) -> dict[str, Any]:
    data = await _get("/search/artist", {"q": name, "limit": 10})
    wanted = normalize(name)
    matches = [item for item in data.get("data") or [] if normalize(item.get("name", "")) == wanted]
    if not wanted or not matches:
        return {}
    return _artist(max(matches, key=lambda item: int(item.get("nb_fan") or 0)))


async def artist(artist_id: int) -> dict[str, Any]:
    """Ein Kuenstler nach seiner Deezer-Nummer. Leer, wenn Deezer ihn nicht (mehr) kennt."""
    data = await _get(f"/artist/{artist_id}", missing_ok=True)
    return _artist(data) if data.get("id") else {}


def artist_url(artist_id: int) -> str:
    """Die Adresse der Deezer-Seite, wie MusicBrainz sie speichert."""
    return f"https://www.deezer.com/artist/{artist_id}"


def _artist(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "name": item.get("name", ""),
        "picture": item.get("picture_xl") or item.get("picture_big") or "",
        "fans": int(item.get("nb_fan") or 0),
    }


async def top_tracks(artist_id: int, limit: int = 10) -> list[dict[str, Any]]:
    data = await _get(f"/artist/{artist_id}/top", {"limit": limit})
    return [
        {
            "title": item.get("title", ""),
            "preview": item.get("preview") or "",
            "duration": int(item.get("duration") or 0),
            "album_title": (item.get("album") or {}).get("title", ""),
            "cover": (item.get("album") or {}).get("cover_medium", ""),
            "explicit": bool(item.get("explicit_lyrics")),
        }
        for item in data.get("data") or []
    ]


async def artist_albums(artist_id: int) -> list[dict[str, Any]]:
    data = await _get(f"/artist/{artist_id}/albums", {"limit": 100})
    return [
        {
            "id": item.get("id"),
            "title": item.get("title", ""),
            "record_type": item.get("record_type") or "",
            "release_date": item.get("release_date") or "",
            "cover": item.get("cover_xl") or "",
        }
        for item in data.get("data") or []
    ]


async def album_tracks(album_id: int) -> list[dict[str, Any]]:
    data = await _get(f"/album/{album_id}/tracks", {"limit": 200})
    return [
        {
            "title": item.get("title", ""),
            "preview": item.get("preview") or "",
            "duration": int(item.get("duration") or 0),
            "position": int(item.get("track_position") or 0),
            "disc": int(item.get("disk_number") or 1),
            "explicit": bool(item.get("explicit_lyrics")),
        }
        for item in data.get("data") or []
    ]
