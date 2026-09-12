"""MusicBrainz: Suche, Kuenstler, Diskografie, Titellisten.

⚠️ **MusicBrainz drosselt hart.** Gemessen am 11.09.2026: Zwei Anfragen im
Abstand von 1,2 Sekunden ergaben zweimal 503, erst der dritte Versuch ging
durch. Zu anderer Zeit kam die Suche dreimal hintereinander mit 503 zurueck.
Die Kopfzeilen deuten auf eine Grenze fuer alle Nutzer zusammen, gegen die kein
eigener Abstand hilft. Deshalb eine prozessweite Schlange mit mindestens 1,1
Sekunden Abstand, Wiederholung bei 503 mit wachsender Pause, davor immer der
Zwischenspeicher und so wenige Aufrufe je Seite wie moeglich.
Beim Seitenaufruf nie in Schleifen abfragen.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from . import http
from .pacing import Spacer

logger = logging.getLogger("nexbeat.musicbrainz")

BASE_URL = "https://musicbrainz.org/ws/2"
MIN_INTERVAL_SECONDS = 1.1
RETRIES = 3
RELEASE_TYPES = "album|ep|single"
#: Nur, was musicbrainz.org standardmaessig zeigt. Gemessen am 12.09.2026: Bei einem Duo
#: kamen ohne den Filter 48 Alben, mit ihm 23. Weg waren inoffizielle wie eine Beta-Fassung.
OFFICIAL_ONLY = {"release-group-status": "website-default"}
_LUCENE_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')


class MusicBrainzError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


spacer = Spacer(MIN_INTERVAL_SECONDS)


def escape(query: str) -> str:
    return _LUCENE_SPECIAL.sub(r"\\\1", query)


async def _get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    query = {**params, "fmt": "json"}
    for attempt in range(RETRIES + 1):
        await spacer.wait()
        try:
            response = await http.client("musicbrainz", timeout=20.0).get(f"{BASE_URL}{path}", params=query)
        except httpx.HTTPError as error:
            logger.warning("MusicBrainz unreachable: %s", error)
            raise MusicBrainzError("musicbrainz_unreachable") from error
        if response.status_code == 503 and attempt < RETRIES:
            # 12.09.2026 gemessen: 2 von 8 Abrufen mit 503, direkt nacheinander, dann
            # wieder 200. Kurze Pausen reichen, lange liessen die Seite nur warten.
            await spacer.sleep(1.0 * (attempt + 1))
            continue
        if response.status_code in (400, 404):
            raise MusicBrainzError("musicbrainz_not_found")
        if response.status_code >= 400:
            raise MusicBrainzError("musicbrainz_busy" if response.status_code == 503 else "musicbrainz_error")
        return response.json()
    raise MusicBrainzError("musicbrainz_busy")


def _tags(entity: dict[str, Any]) -> list[str]:
    genres = sorted(entity.get("genres") or [], key=lambda item: -int(item.get("count") or 0))
    tags = sorted(entity.get("tags") or [], key=lambda item: -int(item.get("count") or 0))
    names = [item["name"] for item in genres if item.get("name")] or [item["name"] for item in tags if item.get("name")]
    return names[:8]


def _credit(entity: dict[str, Any]) -> tuple[str, str]:
    credits = entity.get("artist-credit") or []
    if not credits:
        return "", ""
    first = credits[0].get("artist") or {}
    name = "".join(f"{credit.get('name', '')}{credit.get('joinphrase', '')}" for credit in credits)
    return first.get("id", ""), name or first.get("name", "")


def _release_group(item: dict[str, Any]) -> dict[str, Any]:
    artist_mbid, artist_name = _credit(item)
    return {
        "mbid": item.get("id", ""),
        "title": item.get("title", ""),
        "primary_type": item.get("primary-type") or "",
        "secondary_types": item.get("secondary-types") or [],
        "first_release_date": item.get("first-release-date") or "",
        "artist_mbid": artist_mbid,
        "artist_name": artist_name,
    }


async def search_artists(query: str, limit: int = 12) -> list[dict[str, Any]]:
    data = await _get("/artist", {"query": escape(query), "limit": limit})
    return [
        {
            "mbid": item.get("id", ""),
            "name": item.get("name", ""),
            "type": item.get("type") or "",
            "country": item.get("country") or "",
            "disambiguation": item.get("disambiguation") or "",
            "score": int(item.get("score") or 0),
            "tags": _tags(item)[:3],
        }
        for item in data.get("artists") or []
        if item.get("id")
    ]


async def search_release_groups(query: str, limit: int = 12) -> list[dict[str, Any]]:
    data = await _get("/release-group", {"query": escape(query), "limit": limit})
    return [
        {**_release_group(item), "score": int(item.get("score") or 0)}
        for item in data.get("release-groups") or []
        if item.get("id")
    ]


async def artist(mbid: str) -> dict[str, Any]:
    data = await _get(f"/artist/{mbid}", {"inc": "genres tags"})
    life = data.get("life-span") or {}
    return {
        "mbid": data.get("id", mbid),
        "name": data.get("name", ""),
        "type": data.get("type") or "",
        "country": data.get("country") or "",
        "disambiguation": data.get("disambiguation") or "",
        "begin": life.get("begin") or "",
        "end": life.get("end") or "",
        "tags": _tags(data),
    }


async def release_groups(artist_mbid: str, max_pages: int = 5) -> list[dict[str, Any]]:
    """Alle Alben, EPs und Singles eines Kuenstlers, seitenweise zu je 100.

    12.09.2026 gemessen: Eine Saengerin hatte 101 offizielle Release-Groups, nexbeat las nur die
    ersten 100. Mehr als fuenf Seiten holt nexbeat nicht, jede kostet einen Aufruf.
    """
    groups: list[dict[str, Any]] = []
    offset = 0
    for _ in range(max_pages):
        params = {"artist": artist_mbid, "type": RELEASE_TYPES, "limit": 100, "offset": offset, **OFFICIAL_ONLY}
        data = await _get("/release-group", params)
        page = data.get("release-groups") or []
        groups.extend(_release_group(item) for item in page if item.get("id"))
        offset += len(page)
        if len(page) < 100 or offset >= int(data.get("release-group-count") or 0):
            break
    return groups


async def release_group(mbid: str) -> dict[str, Any]:
    data = await _get(f"/release-group/{mbid}", {"inc": "artist-credits releases"})
    result = _release_group(data)
    result["releases"] = [
        {
            "mbid": release.get("id", ""),
            "status": release.get("status") or "",
            "date": release.get("date") or "",
            "country": release.get("country") or "",
        }
        for release in data.get("releases") or []
    ]
    return result


def _tracks(release: dict[str, Any]) -> list[dict[str, Any]]:
    tracks: list[dict[str, Any]] = []
    for disc_index, medium in enumerate(release.get("media") or [], start=1):
        for track in medium.get("tracks") or []:
            recording = track.get("recording") or {}
            tracks.append(
                {
                    "disc": int(medium.get("position") or disc_index),
                    "position": int(track.get("position") or len(tracks) + 1),
                    "title": track.get("title") or recording.get("title", ""),
                    "length_ms": track.get("length") or recording.get("length"),
                }
            )
    return tracks


def pick_release(releases: list[dict[str, Any]]) -> str | None:
    """Das fruehste offizielle Release, sonst das fruehste ueberhaupt."""
    official = [release for release in releases if release.get("status") == "Official"] or releases
    ordered = sorted(official, key=lambda release: (release.get("date", "") == "", release.get("date", "")))
    return ordered[0]["mbid"] if ordered else None


async def release_group_with_tracks(mbid: str) -> dict[str, Any]:
    """Release-Group, ihre Releases und die Titel des fruehesten offiziellen, in einem Aufruf.

    Gemessen am 11.09.2026: Der Browse-Aufruf ueber ``/release`` mit ``recordings``,
    ``artist-credits`` und ``release-groups`` liefert bis zu 25 Releases, jedes mit
    Titelliste und Release-Group samt Kuenstler. Vorher waren es zwei Aufrufe, und
    jeder konnte an einer 503 haengen.
    """
    params = {"release-group": mbid, "inc": "recordings artist-credits release-groups", "limit": 25}
    data = await _get("/release", params)
    releases = [release for release in data.get("releases") or [] if release.get("id")]
    if not releases:
        return {"group": await release_group(mbid), "tracks": []}
    group = _release_group(releases[0].get("release-group") or {})
    group["mbid"] = group["mbid"] or mbid
    if not group["artist_mbid"]:
        group["artist_mbid"], group["artist_name"] = _credit(releases[0])
    group["releases"] = [
        {
            "mbid": release["id"],
            "status": release.get("status") or "",
            "date": release.get("date") or "",
            "country": release.get("country") or "",
        }
        for release in releases
    ]
    chosen = pick_release(group["releases"])
    picked = next((release for release in releases if release["id"] == chosen), releases[0])
    return {"group": group, "tracks": _tracks(picked)}


async def studio_albums(artist_mbid: str, max_pages: int = 5) -> list[dict[str, Any]]:
    """Alle Alben eines Kuenstlers ohne Zusatztyp, seitenweise zu je 100.

    Live, Compilation, Remix und Co. fallen heraus. Mehr als fuenf Seiten holt
    nexbeat nicht, das waeren 500 Release-Groups vom Typ Album.
    """
    albums: list[dict[str, Any]] = []
    offset = 0
    for _ in range(max_pages):
        params = {"artist": artist_mbid, "type": "album", "limit": 100, "offset": offset, **OFFICIAL_ONLY}
        data = await _get("/release-group", params)
        items = [item for item in data.get("release-groups") or [] if item.get("id")]
        albums.extend(
            _release_group(item)
            for item in items
            if (item.get("primary-type") or "").casefold() == "album" and not item.get("secondary-types")
        )
        offset += len(items)
        if len(items) < 100 or offset >= int(data.get("release-group-count") or 0):
            break
    return albums
