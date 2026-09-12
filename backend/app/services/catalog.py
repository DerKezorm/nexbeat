"""Was die Seiten zeigen: Suche, Kuenstler, Album.

Zusammengesetzt aus MusicBrainz, ListenBrainz, Deezer und dem Lidarr-Bestand,
jeweils mit Zwischenspeicher. Faellt eine Quelle aus, bleibt die Seite stehen und
nur der Abschnitt leer. Pflicht ist allein MusicBrainz, ohne es gibt es keine
Identitaet.

⚠️ Kuenstlerbilder stehen nicht als fertige Adresse in den Antworten, sondern
als ``/api/images/artist/<mbid>``. Der Browser laedt sie erst, wenn die Karte
sichtbar wird, und erst dann sucht nexbeat bei Deezer. Sonst hinge der Aufbau
einer Seite an Dutzenden Bildsuchen.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections.abc import Awaitable
from datetime import timedelta
from typing import Any
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ARTIST_KIND, COUNTED_STATUSES, LibraryArtist, MusicRequest, User
from . import cache, coverart, deezer, library, listenbrainz, musicbrainz, quota
from .deezer import DeezerError
from .lidarr import LidarrError
from .listenbrainz import ListenBrainzError
from .musicbrainz import MusicBrainzError
from .settings_service import AppSettings

logger = logging.getLogger("nexbeat.catalog")

TTL_SEARCH = timedelta(days=1)
TTL_ARTIST = timedelta(days=7)
TTL_BROWSE = timedelta(days=3)
TTL_RELEASE_GROUP = timedelta(days=30)
TTL_TRACKS = timedelta(days=30)
TTL_SIMILAR = timedelta(days=7)
TTL_POPULAR = timedelta(days=1)
TTL_DEEZER_MATCH = timedelta(days=30)
TTL_DEEZER_TOP = timedelta(days=1)
TTL_DEEZER_ALBUMS = timedelta(days=7)
#: So viele Kuenstler fragt nexbeat gleichzeitig bei ListenBrainz nach.
SIMILAR_CONCURRENCY = 4

MBID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
SOURCE_ERRORS = (MusicBrainzError, ListenBrainzError, DeezerError, LidarrError)


def valid_mbid(value: str) -> bool:
    return bool(MBID_PATTERN.match(value or ""))


def artist_image_path(mbid: str, name: str) -> str:
    return f"/api/images/artist/{mbid}?name={quote(name or '')}"


def similar_key(mbid: str) -> str:
    return f"lb:similar:{mbid}"


async def optional(awaitable: Awaitable[Any], label: str) -> Any:
    """Eine Quelle, die fehlen darf. Ihr Ausfall leert nur den Abschnitt."""
    try:
        return await awaitable
    except SOURCE_ERRORS as error:
        logger.info("%s unavailable: %s", label, getattr(error, "code", error))
        return None


def library_mbids(db: Session, mbids: list[str]) -> set[str]:
    if not mbids:
        return set()
    return set(db.scalars(select(LibraryArtist.mbid).where(LibraryArtist.mbid.in_(mbids))))


def _request_state(row: MusicRequest, user: User) -> dict[str, Any]:
    return {
        "id": row.id,
        "status": row.status.value,
        "mine": row.user_id == user.id,
        "progress": row.progress,
        "error_code": row.error_code,
    }


def request_states(db: Session, user: User, release_group_mbids: list[str]) -> dict[str, dict[str, Any]]:
    """Anfragestand je Release. Wer angefragt hat, bleibt verborgen, nur "meine" nicht."""
    if not release_group_mbids:
        return {}
    rows = db.scalars(
        select(MusicRequest)
        .where(MusicRequest.release_group_mbid.in_(release_group_mbids), MusicRequest.status.in_(COUNTED_STATUSES))
        .order_by(MusicRequest.requested_at.desc())
    )
    states: dict[str, dict[str, Any]] = {}
    for row in rows:
        states.setdefault(row.release_group_mbid, _request_state(row, user))
    return states


def artist_request_state(db: Session, user: User, artist_mbid: str) -> dict[str, Any] | None:
    """Die juengste zaehlende Anfrage fuer den ganzen Kuenstler."""
    row = db.scalar(
        select(MusicRequest)
        .where(
            MusicRequest.kind == ARTIST_KIND,
            MusicRequest.artist_mbid == artist_mbid,
            MusicRequest.status.in_(COUNTED_STATUSES),
        )
        .order_by(MusicRequest.requested_at.desc())
        .limit(1)
    )
    return _request_state(row, user) if row is not None else None


def deezer_match_key(mbid: str, name: str) -> str:
    """Der Deezer-Treffer haengt am Namen, nicht nur an der Kennung.

    12.09.2026: Das Kuenstlerbild ist ohne Anmeldung abrufbar. Wer zuerst mit einem falschen
    Namen fragte, bestimmte das Bild fuer alle, bis der Zwischenspeicher ablief.
    """
    digest = hashlib.sha256(deezer.normalize(name).encode("utf-8")).hexdigest()[:16]
    return f"dz:artist:{mbid}:{digest}"


async def resolve_artist_image(db: Session, settings: AppSettings, mbid: str, name: str) -> str | None:
    """Adresse des Kuenstlerbilds. ``""`` heisst: gibt es nicht. ``None``: Deezer hat gerade abgelehnt."""
    row = db.get(LibraryArtist, mbid)
    if row is not None and row.image_url:
        return row.image_url
    if not settings.flag("source_deezer") or not name:
        return ""
    match = await optional(
        cache.cached(db, deezer_match_key(mbid, name), TTL_DEEZER_MATCH, lambda: deezer.find_artist(name)), "deezer"
    )
    if match is None:
        return None
    return match.get("picture", "")


async def similar_for(db: Session, seeds: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Aehnliche Kuenstler je Ausgangskuenstler, fehlende einzeln nachgeladen.

    Faellt ListenBrainz nur fuer einzelne aus, fehlen nur diese. Erst wenn gar
    nichts da ist, geht der Fehler weiter.
    """
    wanted = list(dict.fromkeys(seeds))
    found: dict[str, list[dict[str, Any]]] = {}
    missing: list[str] = []
    for seed in wanted:
        hit = cache.read(db, similar_key(seed))
        if hit is None:
            missing.append(seed)
        else:
            found[seed] = hit
    gate = asyncio.Semaphore(SIMILAR_CONCURRENCY)
    failures: list[ListenBrainzError] = []

    async def load(seed: str) -> None:
        try:
            async with gate:
                rows = (await listenbrainz.similar_artists(seed))[:60]
        except ListenBrainzError as error:
            failures.append(error)
            return
        cache.write(db, similar_key(seed), rows, TTL_SIMILAR)
        found[seed] = rows

    await asyncio.gather(*(load(seed) for seed in missing))
    if failures and not found:
        raise failures[0]
    return {seed: found[seed] for seed in wanted if seed in found}


def _clean(query: str) -> str:
    return " ".join((query or "").split())[:100]


async def search_artists(db: Session, settings: AppSettings, query: str) -> list[dict[str, Any]]:
    text = _clean(query)
    if len(text) < 2:
        return []
    results = await cache.cached(
        db, f"mb:search:artist:{text.casefold()}", TTL_SEARCH, lambda: musicbrainz.search_artists(text)
    )
    known = library_mbids(db, [item["mbid"] for item in results])
    return [
        {**item, "image": artist_image_path(item["mbid"], item["name"]), "in_library": item["mbid"] in known}
        for item in results
    ]


async def search_albums(db: Session, settings: AppSettings, user: User, query: str) -> list[dict[str, Any]]:
    text = _clean(query)
    if len(text) < 2:
        return []
    results = await cache.cached(
        db, f"mb:search:rg:{text.casefold()}", TTL_SEARCH, lambda: musicbrainz.search_release_groups(text)
    )
    states = request_states(db, user, [item["mbid"] for item in results])
    return [
        {**item, "cover": coverart.release_group_front(item["mbid"], 250), "request": states.get(item["mbid"])}
        for item in results
    ]


async def _deezer_artist(db: Session, mbid: str, name: str) -> dict[str, Any]:
    return await cache.cached(db, deezer_match_key(mbid, name), TTL_DEEZER_MATCH, lambda: deezer.find_artist(name))


async def artist_info(db: Session, mbid: str) -> dict[str, Any]:
    return await cache.cached(db, f"mb:artist:{mbid}", TTL_ARTIST, lambda: musicbrainz.artist(mbid))


async def studio_albums(db: Session, mbid: str) -> list[dict[str, Any]]:
    """Alben ohne Zusatztyp laut MusicBrainz, fuer die Anfrage "ganzer Kuenstler"."""
    return await cache.cached(db, f"mb:studio:official:{mbid}", TTL_BROWSE, lambda: musicbrainz.studio_albums(mbid))


async def artist_page(db: Session, settings: AppSettings, user: User, mbid: str) -> dict[str, Any]:
    """Der Kopf der Kuenstlerseite: Stammdaten, Anfragestand, Kontingent.

    12.09.2026: Die Seite wartete auf alle Quellen zugleich und zeigte bei einer
    ausgelasteten MusicBrainz "keine Veroeffentlichungen". Diskografie, Beliebt,
    Aehnliche und Top-Titel haben deshalb eigene Aufrufe mit eigenen Fehlern.
    """
    info = await artist_info(db, mbid)
    library_row = db.get(LibraryArtist, mbid)
    request = artist_request_state(db, user, mbid)
    blocked = None
    if settings.lidarr_ready and request is None:
        blocked = await library.whole_artist_block(db, settings, mbid)
    return {
        "blocked": blocked,
        "artist": {
            **info,
            "image": artist_image_path(mbid, info["name"]),
            "in_library": library_row is not None,
            "track_file_count": library_row.track_file_count if library_row else 0,
        },
        "sources": {"listenbrainz": settings.flag("source_listenbrainz"), "deezer": settings.flag("source_deezer")},
        "request": request,
        "requests_enabled": settings.lidarr_ready,
        "requires_approval": user.requires_approval and not user.is_admin,
        "dry_run": settings.flag("lidarr_dry_run"),
        "quota": quota.as_dict(quota.state(db, user, settings)),
    }


async def top_release_groups(db: Session, settings: AppSettings, mbid: str) -> list[dict[str, Any]]:
    token = settings.text("listenbrainz_token")
    # "v2" seit 12.09.2026: mit den Kuenstlern jeder Release-Group. Aeltere Eintraege hatten sie nicht.
    return await cache.cached(
        db, f"lb:top-rg:v2:{mbid}", TTL_POPULAR, lambda: listenbrainz.top_release_groups(mbid, token=token)
    )


async def _with_states(
    db: Session, settings: AppSettings, user: User, mbid: str, albums: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    states = await library.album_states(db, settings, mbid)
    requests = request_states(db, user, [album["mbid"] for album in albums])
    for album in albums:
        album["library"] = states.get(album["mbid"])
        album["request"] = requests.get(album["mbid"])
    return albums


async def artist_discography(db: Session, settings: AppSettings, user: User, mbid: str) -> dict[str, Any]:
    """Alle Veroeffentlichungen laut MusicBrainz. Faellt MusicBrainz aus, geht der Fehler weiter."""
    # Eigener Schluessel seit 12.09.2026: Aeltere Eintraege brachen nach 100 Release-Groups ab.
    groups = await cache.cached(db, f"mb:discography:{mbid}", TTL_BROWSE, lambda: musicbrainz.release_groups(mbid))
    popularity: dict[str, dict[str, Any]] = {}
    if settings.flag("source_listenbrainz"):
        popular = await optional(top_release_groups(db, settings, mbid), "listenbrainz") or []
        popularity = {item["mbid"]: item for item in popular}
    albums = []
    for group in groups:
        known = popularity.get(group["mbid"], {})
        albums.append(
            {
                "mbid": group["mbid"],
                "title": group["title"],
                "primary_type": group["primary_type"],
                "secondary_types": group["secondary_types"],
                "date": group["first_release_date"],
                "listen_count": known.get("listen_count", 0),
                "cover": known.get("cover") or coverart.release_group_front(group["mbid"], 250),
            }
        )
    albums.sort(key=lambda album: album["date"] or "0000", reverse=True)
    return {"albums": await _with_states(db, settings, user, mbid, albums)}


#: "Am meisten gehoert" zeigt Alben und EPs. ListenBrainz nennt manchmal keine Art.
POPULAR_TYPES = ("album", "ep", "")


def credited(item: dict[str, Any], mbid: str) -> bool:
    """Gehoert die Release-Group dem Kuenstler? Nennt ListenBrainz niemanden, im Zweifel ja."""
    artists = item.get("artist_mbids") or []
    return not artists or mbid in artists


async def artist_popular(db: Session, settings: AppSettings, user: User, mbid: str) -> dict[str, Any]:
    """Die meistgehoerten Alben laut ListenBrainz, ohne auf MusicBrainz zu warten.

    Nur Release-Groups des Kuenstlers selbst. ListenBrainz zaehlt auch fremde Alben mit, auf
    denen er nur mitsingt. 12.09.2026: Bei einer Saengerin stand so das Album einer anderen
    Kuenstlerin unter "Am meisten gehoert".
    """
    if not settings.flag("source_listenbrainz"):
        return {"albums": []}
    ranked = sorted(await top_release_groups(db, settings, mbid), key=lambda item: -item["listen_count"])
    albums = [
        {
            "mbid": item["mbid"],
            "title": item["title"],
            "primary_type": item["type"],
            "secondary_types": [],
            "date": item["date"],
            "listen_count": item["listen_count"],
            "cover": item["cover"] or coverart.release_group_front(item["mbid"], 250),
        }
        for item in ranked
        if (item["type"] or "").casefold() in POPULAR_TYPES and credited(item, mbid)
    ][:8]
    return {"albums": await _with_states(db, settings, user, mbid, albums)}


async def artist_similar(db: Session, settings: AppSettings, mbid: str) -> dict[str, Any]:
    if not settings.flag("source_listenbrainz"):
        return {"artists": []}
    similar = (await similar_for(db, [mbid])).get(mbid, [])[:24]
    known = library_mbids(db, [item["mbid"] for item in similar])
    return {
        "artists": [
            {
                "mbid": item["mbid"],
                "name": item["name"],
                "image": artist_image_path(item["mbid"], item["name"]),
                "in_library": item["mbid"] in known,
            }
            for item in similar
        ]
    }


async def artist_top_tracks(db: Session, settings: AppSettings, mbid: str, name: str) -> dict[str, Any]:
    """Beliebte Titel mit Hoerprobe laut Deezer. Der Name kommt aus den gespeicherten Stammdaten."""
    if not settings.flag("source_deezer"):
        return {"tracks": []}
    # Ein mitgeschickter Name zaehlt nur, solange MusicBrainz den Kuenstler noch nicht geliefert hat.
    name = (cache.read(db, f"mb:artist:{mbid}") or {}).get("name") or name.strip()
    if not name:
        return {"tracks": []}
    match = await _deezer_artist(db, mbid, name)
    if not match.get("id"):
        return {"tracks": []}
    deezer_id = match["id"]
    tracks = await cache.cached(db, f"dz:top:{deezer_id}", TTL_DEEZER_TOP, lambda: deezer.top_tracks(deezer_id))
    return {"tracks": tracks}


def album_key(release_group_mbid: str) -> str:
    return f"mb:album:{release_group_mbid}"


async def release_group_info(db: Session, release_group_mbid: str) -> dict[str, Any]:
    """Titel, Typen und Kuenstler einer Release-Group.

    War die Albumseite schon offen, kommt alles aus deren Zwischenspeicher. Eine
    Anfrage loest dann bei MusicBrainz nichts mehr aus.
    """
    detail = cache.read(db, album_key(release_group_mbid))
    if detail is not None:
        return detail["group"]
    return await cache.cached(
        db, f"mb:rg:{release_group_mbid}", TTL_RELEASE_GROUP, lambda: musicbrainz.release_group(release_group_mbid)
    )


async def _deezer_album_tracks(db: Session, group: dict[str, Any]) -> list[dict[str, Any]]:
    match = await _deezer_artist(db, group["artist_mbid"], group["artist_name"])
    if not match.get("id"):
        return []
    deezer_id = match["id"]
    albums = await cache.cached(
        db, f"dz:albums:{deezer_id}", TTL_DEEZER_ALBUMS, lambda: deezer.artist_albums(deezer_id)
    )
    wanted = deezer.normalize(group["title"])
    album = next((item for item in albums if deezer.normalize(item["title"]) == wanted), None)
    if album is None:
        return []
    album_id = album["id"]
    return await cache.cached(db, f"dz:album-tracks:{album_id}", TTL_TRACKS, lambda: deezer.album_tracks(album_id))


async def album_page(db: Session, settings: AppSettings, user: User, release_group_mbid: str) -> dict[str, Any]:
    detail = await cache.cached(
        db,
        album_key(release_group_mbid),
        TTL_TRACKS,
        lambda: musicbrainz.release_group_with_tracks(release_group_mbid),
    )
    group = detail["group"]
    tracks: list[dict[str, Any]] = [dict(track) for track in detail["tracks"]]

    deezer_tracks: list[dict[str, Any]] = []
    if settings.flag("source_deezer") and group.get("artist_name"):
        deezer_tracks = await optional(_deezer_album_tracks(db, group), "deezer") or []
    by_title = {deezer.normalize(item["title"]): item for item in deezer_tracks}
    if tracks:
        for track in tracks:
            match = by_title.get(deezer.normalize(track["title"]))
            track["preview"] = match["preview"] if match else ""
            track["explicit"] = bool(match and match["explicit"])
    else:
        tracks = [
            {
                "disc": item["disc"],
                "position": item["position"],
                "title": item["title"],
                "length_ms": item["duration"] * 1000,
                "preview": item["preview"],
                "explicit": item["explicit"],
            }
            for item in deezer_tracks
        ]

    states = await library.album_states(db, settings, group["artist_mbid"]) if group.get("artist_mbid") else {}
    # 12.09.2026: Ein Soundtrack liess sich anfragen, und die Anfrage scheiterte still am
    # Metadatenprofil. Listet Lidarr das Album schon, laesst das Profil des Kuenstlers es zu.
    blocked = None
    if settings.lidarr_ready and release_group_mbid not in states:
        blocked = await library.type_block(db, settings, group)
    return {
        "blocked": blocked,
        "album": {
            "mbid": group["mbid"],
            "title": group["title"],
            "primary_type": group["primary_type"],
            "secondary_types": group["secondary_types"],
            "date": group["first_release_date"],
            "artist_mbid": group["artist_mbid"],
            "artist_name": group["artist_name"],
            "cover": coverart.release_group_front(release_group_mbid, 500),
            "artist_image": artist_image_path(group["artist_mbid"], group["artist_name"]),
        },
        "tracks": tracks,
        "library": states.get(release_group_mbid),
        "request": request_states(db, user, [release_group_mbid]).get(release_group_mbid),
        "quota": quota.as_dict(quota.state(db, user, settings)),
        "requests_enabled": settings.lidarr_ready,
        "requires_approval": user.requires_approval and not user.is_admin,
        "dry_run": settings.flag("lidarr_dry_run"),
    }
