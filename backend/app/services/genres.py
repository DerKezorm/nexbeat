"""Nach Genre stoebern: beliebte Kuenstler, beliebte Alben und verwandte Genres.

Die Kuenstler kommen aus der Tag-Suche von MusicBrainz, sortiert nach den Hoerzahlen von
ListenBrainz.

⚠️ Die Tag-Suche findet jeden, dem jemand den Tag je gegeben hat, auch nach Gegenstimmen.
Gemessen am 12.09.2026: Nach Hoerzahlen sortiert fuehrten Lady Gaga und Madonna die Liste
"jazz" an, Linkin Park und Nirvana die Liste "hip hop", mit je einer Stimme gegen 20 bis 70
fuer ihr eigentliches Genre. Deshalb zaehlt, wie stark ein Kuenstler das Genre traegt, siehe
``affinity``.

Die Alben kommen nicht aus der Tag-Suche. Die ordnet nach Treffergenauigkeit und brachte am
12.09.2026 fast nur Unbekanntes. Stattdessen die meistgehoerten Alben von Kuenstlern des Genres.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections import Counter
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..models import User
from . import cache, catalog, coverart, listenbrainz, musicbrainz
from .listenbrainz import ListenBrainzError
from .settings_service import AppSettings

TTL_TAG_ARTISTS = timedelta(days=7)
TTL_GENRE_NAMES = timedelta(days=30)
TTL_LISTENS = timedelta(days=3)
TTL_SITEWIDE_ALBUMS = timedelta(days=1)
#: Ab diesem Anteil traegt ein Kuenstler das Genre, siehe ``affinity``. Gemessen am 12.09.2026:
#: Mit 0,3 fuehrte Radiohead "electronic" an, und Elvis Presley stand unter "r&b".
MIN_AFFINITY = 0.5
ARTIST_LIMIT = 24
RELATED_LIMIT = 8
ALBUM_LIMIT = 18
#: Von so vielen Spitzenkuenstlern holt nexbeat die meistgehoerten Alben.
ALBUM_ARTISTS = 8
ALBUMS_PER_ARTIST = 2
#: Mehr als 1000 Alben je Zeitraum fuehrt die weltweite Liste nicht.
SITEWIDE_RANGES = ("all_time", "year")
SITEWIDE_COUNT = 1000
#: So viele Kuenstler fragt nexbeat gleichzeitig bei ListenBrainz nach.
CONCURRENCY = 4
MAX_TAG_LENGTH = 60
GENRE_NAMES_KEY = "mb:genre-names"
VARIOUS_ARTISTS = "89ad4ac3-39f7-470e-963a-56509c546377"
_WORDS = re.compile(r"[\s-]+")


def normalize_tag(value: str) -> str | None:
    """Klein geschrieben, mit einfachen Leerzeichen, hoechstens 60 Zeichen. Sonst None."""
    tag = " ".join((value or "").split()).casefold()
    return tag if 0 < len(tag) <= MAX_TAG_LENGTH else None


def in_family(genre: str, tag: str) -> bool:
    """Ist der Tag das Genre oder eine Spielart davon? "heavy metal" zaehlt fuer "metal", "post-punk" fuer "punk"."""
    wanted, words = _WORDS.split(genre), _WORDS.split(tag)
    return any(words[index : index + len(wanted)] == wanted for index in range(len(words) - len(wanted) + 1))


def affinity(genre: str, votes: dict[str, int], names: set[str]) -> float:
    """Wie stark ein Kuenstler das Genre traegt, von 0 bis 1.

    Die Stimmen fuer das Genre oder eine Spielart davon, geteilt durch die fuer sein staerkstes
    Genre. Gegenstimmen zaehlen nicht, Tags wie "british" auch nicht, sofern die Genre-Liste da ist.
    """
    counted = {name: count for name, count in votes.items() if count > 0 and (not names or name in names)}
    if not counted:
        return 0.0
    own = max((count for name, count in counted.items() if in_family(genre, name)), default=0)
    return own / max(counted.values())


def related_genres(genre: str, artists: list[dict[str, Any]], names: set[str]) -> list[str]:
    """Die Genres, die bei den Kuenstlern am haeufigsten mitstehen. Ohne Genre-Liste keine."""
    if not names:
        return []
    counts = Counter(
        name
        for artist in artists
        for name, count in artist["tags"].items()
        if count > 0 and name != genre and name in names
    )
    ranked = sorted(counts.items(), key=lambda entry: (-entry[1], entry[0]))
    return [name for name, count in ranked if count >= 2][:RELATED_LIMIT]


def _placeholder(artist: dict[str, Any]) -> bool:
    """Various Artists und Platzhalter in eckigen Klammern wie "[unknown]"."""
    name = artist["name"]
    return artist["mbid"] == VARIOUS_ARTISTS or (name.startswith("[") and name.endswith("]"))


async def _genre_names(db: Session) -> set[str]:
    names = await catalog.optional(
        cache.cached(db, GENRE_NAMES_KEY, TTL_GENRE_NAMES, musicbrainz.genre_names), "musicbrainz"
    )
    return set(names or [])


async def _carriers(db: Session, tag: str) -> tuple[list[dict[str, Any]], set[str]]:
    """Wer das Genre wirklich traegt, in der Reihenfolge der Tag-Suche. Dazu die Genre-Namen."""
    found = await cache.cached(db, f"mb:tag-artists:{tag}", TTL_TAG_ARTISTS, lambda: musicbrainz.artists_by_tag(tag))
    names = await _genre_names(db)
    carriers = [
        artist
        for artist in found
        if not _placeholder(artist) and affinity(tag, artist["tags"], names) >= MIN_AFFINITY
    ]
    return carriers, names


async def _by_listens(db: Session, settings: AppSettings, artists: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Nach Hoerzahlen sortiert. None, wenn ListenBrainz aus ist oder nicht antwortet."""
    if not settings.flag("source_listenbrainz"):
        return None
    mbids = sorted(artist["mbid"] for artist in artists)
    digest = hashlib.sha256(",".join(mbids).encode("utf-8")).hexdigest()[:16]
    token = settings.text("listenbrainz_token")
    listens = await catalog.optional(
        cache.cached(
            db, f"lb:artist-listens:{digest}", TTL_LISTENS, lambda: listenbrainz.artist_popularity(mbids, token=token)
        ),
        "listenbrainz",
    )
    if listens is None:
        return None
    # Stabil sortiert: Bei gleicher Zahl bleibt die Reihenfolge der Tag-Suche.
    return sorted(artists, key=lambda artist: -int(listens.get(artist["mbid"], 0)))


async def genre_artists(db: Session, settings: AppSettings, tag: str) -> dict[str, Any]:
    """Die beliebtesten Kuenstler des Genres und die Genres, die bei ihnen mitstehen."""
    carriers, names = await _carriers(db, tag)
    ranked = await _by_listens(db, settings, carriers)
    top = (carriers if ranked is None else ranked)[:ARTIST_LIMIT]
    known = catalog.library_mbids(db, [artist["mbid"] for artist in top])
    return {
        "tag": tag,
        "ranked": ranked is not None,
        "related": related_genres(tag, carriers, names),
        "artists": [
            {
                "mbid": artist["mbid"],
                "name": artist["name"],
                "image": catalog.artist_image_path(artist["mbid"], artist["name"]),
                "in_library": artist["mbid"] in known,
            }
            for artist in top
        ],
    }


def _offer(mbid: str, title: str, artist: dict[str, Any], cover: str, listens: int) -> dict[str, Any]:
    return {
        "mbid": mbid,
        "title": title,
        "artist_mbid": artist["mbid"],
        "artist_name": artist["name"],
        "cover": cover,
        "listen_count": listens,
    }


async def genre_albums(db: Session, settings: AppSettings, user: User, tag: str) -> dict[str, Any]:
    """Die meistgehoerten Alben von Kuenstlern des Genres, je Kuenstler hoechstens zwei.

    Zwei Quellen, weil jede allein Luecken hat. Die beliebtesten Alben eines Kuenstlers gibt
    ListenBrainz ohne Schluessel nicht fuer jeden heraus: Am 12.09.2026 kam bei 18 von 88
    Spitzenkuenstlern ``401``. Die weltweite Albenliste kennt nur die 1000 meistgehoerten Alben
    je Zeitraum und fand zu "latin" keins. Scheitert alles, geht der Fehler weiter.
    """
    if not settings.flag("source_listenbrainz"):
        return {"available": False, "albums": []}
    carriers, _names = await _carriers(db, tag)
    ranked = await _by_listens(db, settings, carriers)
    by_mbid = {artist["mbid"]: artist for artist in carriers}
    token = settings.text("listenbrainz_token")
    failures: list[ListenBrainzError] = []
    offers: dict[str, dict[str, Any]] = {}

    def offer(album: dict[str, Any]) -> None:
        known = offers.get(album["mbid"])
        if known is None or album["listen_count"] > known["listen_count"]:
            offers[album["mbid"]] = album

    gate = asyncio.Semaphore(CONCURRENCY)

    async def from_artist(artist: dict[str, Any]) -> None:
        try:
            async with gate:
                groups = await catalog.top_release_groups(db, settings, artist["mbid"])
        except ListenBrainzError as error:
            failures.append(error)
            return
        own = [
            group
            for group in groups
            if (group["type"] or "").casefold() in ("album", "") and catalog.credited(group, artist["mbid"])
        ]
        for group in sorted(own, key=lambda group: -group["listen_count"])[:ALBUMS_PER_ARTIST]:
            offer(_offer(group["mbid"], group["title"], artist, group["cover"], group["listen_count"]))

    await asyncio.gather(*(from_artist(artist) for artist in (carriers if ranked is None else ranked)[:ALBUM_ARTISTS]))

    for range_ in SITEWIDE_RANGES:
        try:
            rows = await cache.cached(
                db,
                f"lb:sitewide:release-groups:{range_}:{SITEWIDE_COUNT}",
                TTL_SITEWIDE_ALBUMS,
                lambda range_=range_: listenbrainz.sitewide_release_groups(SITEWIDE_COUNT, range_, token=token),
            )
        except ListenBrainzError as error:
            failures.append(error)
            continue
        for row in rows:
            artist = by_mbid.get(row["artist_mbid"])
            if artist is not None:
                offer(_offer(row["mbid"], row["title"], artist, row["cover"], row["listen_count"]))

    per_artist: Counter[str] = Counter()
    chosen: list[dict[str, Any]] = []
    for album in sorted(offers.values(), key=lambda album: -album["listen_count"]):
        if per_artist[album["artist_mbid"]] < ALBUMS_PER_ARTIST and len(chosen) < ALBUM_LIMIT:
            per_artist[album["artist_mbid"]] += 1
            chosen.append(album)
    if not chosen and failures:
        raise failures[0]
    states = catalog.request_states(db, user, [album["mbid"] for album in chosen])
    return {
        "available": True,
        "albums": [
            {
                "mbid": album["mbid"],
                "title": album["title"],
                "artist_mbid": album["artist_mbid"],
                "artist_name": album["artist_name"],
                "cover": album["cover"] or coverart.release_group_front(album["mbid"], 250),
                "request": states.get(album["mbid"]),
            }
            for album in chosen
        ],
    }
