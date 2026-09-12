"""Deezer: Kuenstlerbilder und 30-Sekunden-Hoerproben.

⚠️ Rechtlich eine Grauzone. Die API antwortet ohne Token, aber das
Entwicklerportal vergibt seit etwa Mitte 2025 keine Tokens mehr. Deshalb ist
Deezer in den Einstellungen abschaltbar, und nichts in nexbeat haengt davon ab.

Die Zuordnung zu MusicBrainz laeuft nur ueber Namen. Gezaehlt werden deshalb nur
exakte Treffer. Ein falsches Bild ist schlimmer als gar keins.

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


async def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
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
    best = max(matches, key=lambda item: int(item.get("nb_fan") or 0))
    return {
        "id": best.get("id"),
        "name": best.get("name", ""),
        "picture": best.get("picture_xl") or best.get("picture_big") or "",
        "fans": int(best.get("nb_fan") or 0),
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
