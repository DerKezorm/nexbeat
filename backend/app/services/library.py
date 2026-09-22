"""Der Bestand aus Sicht von nexbeat, aus Lidarr (ARR-Modus) oder nexcrate (NEX-Modus).

Kuenstler werden regelmaessig nach ``library_artists`` gespiegelt, damit
Empfehlungen und Abzeichen ohne Aufruf nach aussen auskommen. Die Alben eines
Kuenstlers kommen bei Bedarf und leben fuenf Minuten im Zwischenspeicher,
ebenso die Metadatenprofile.

Im NEX-Modus liest nexbeat die Kuenstler ueber nexcrates Aenderungsmarke: einmal
ganz, danach nur, was sich seit der Nummer geaendert hat. ``track_file_count``
zaehlt dort die vorhandenen Alben, nicht Titeldateien; gebraucht wird nur "> 0".
Metadatenprofile gibt es in nexcrate nicht, die Sperren danach entfallen.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import LibraryArtist, utcnow
from . import cache, lidarr, nexcrate
from .settings_service import AppSettings, save_settings

logger = logging.getLogger("nexbeat.library")

ALBUM_TTL = timedelta(minutes=5)
PROFILE_TTL = timedelta(minutes=5)
#: Warum Lidarr etwas nicht nehmen soll, je Kennung. Englisch, fuer API und Protokoll.
TYPE_BLOCKS = {
    "release_type_excluded": "The metadata profile in Lidarr does not include this release type.",
    "artist_profile_excludes_type": "The artist's metadata profile in Lidarr does not include this release type.",
    "profile_not_studio_only": "The metadata profile in the settings allows more than studio albums.",
    "artist_profile_not_studio_only": "The artist's metadata profile in Lidarr allows more than studio albums.",
}


#: Einmal am Tag liest nexbeat die Kuenstler aus nexcrate ganz, auch wenn die Marke weiterzaehlt.
#: Eine Marke, die eine Aenderung verpasst, zeigte sonst fuer immer einen falschen Bestand.
NEXCRATE_FULL_READ = timedelta(hours=24)


async def sync_artists(db: Session, settings: AppSettings) -> int | None:
    """Kuenstlerliste abgleichen. ``None``, wenn kein Ziel eingerichtet ist."""
    if settings.mode == "nex":
        return await _sync_from_nexcrate(db, settings)
    client = lidarr.client_for(settings)
    if client is None:
        return None
    artists = await client.artists()
    existing = {row.mbid: row for row in db.scalars(select(LibraryArtist))}
    seen: set[str] = set()
    now = utcnow()
    for item in artists:
        mbid = item.get("foreignArtistId")
        if not mbid or mbid in seen:
            continue
        seen.add(mbid)
        statistics = item.get("statistics") or {}
        row = existing.get(mbid)
        if row is None:
            row = LibraryArtist(mbid=mbid, lidarr_id=0, name="")
            db.add(row)
        row.lidarr_id = int(item.get("id") or 0)
        row.name = item.get("artistName") or ""
        row.image_url = lidarr.image_url(item.get("images") or [], "poster", "fanart")
        row.track_file_count = int(statistics.get("trackFileCount") or 0)
        row.album_count = int(statistics.get("albumCount") or 0)
        row.metadata_profile_id = int(item.get("metadataProfileId") or 0)
        row.synced_at = now
    for mbid, row in existing.items():
        if mbid not in seen:
            db.delete(row)
    db.commit()
    logger.info("Library sync: %d artists", len(seen))
    return len(seen)


def _marker(settings: AppSettings) -> dict[str, Any]:
    try:
        stored = json.loads(settings.text("nexcrate_marker") or "{}")
    except ValueError:
        return {}
    return stored if isinstance(stored, dict) else {}


def _apply_artist(row: LibraryArtist | None, item: dict[str, Any], db: Session, now: datetime) -> None:
    albums = (item.get("artist") or {}).get("albums") or {}
    if row is None:
        row = LibraryArtist(mbid=nexcrate.mbid_of(item.get("ref")), lidarr_id=0, name="")
        db.add(row)
    row.lidarr_id = 0
    row.name = item.get("name") or ""
    row.image_url = ""
    row.track_file_count = int(albums.get("available") or 0)
    row.album_count = int(albums.get("total") or 0)
    row.metadata_profile_id = 0
    row.synced_at = now


def _stale(marker: dict[str, Any], url: str, installation: str, now: datetime) -> bool:
    if marker.get("url") != url or marker.get("installation") != installation or not marker.get("full_at"):
        return True
    try:
        return now - datetime.fromisoformat(marker["full_at"]) > NEXCRATE_FULL_READ
    except (TypeError, ValueError):
        return True


async def _read_artists(client: nexcrate.NexcrateClient, after: int) -> tuple[list[Any], list[Any], int, int]:
    """Alle Seiten ab ``after``: Kuenstler, Verschwundene, ``latest`` und die Nummer fuers naechste Mal."""
    items: list[Any] = []
    removed: list[Any] = []
    cursor, latest = after, 0
    while True:
        page = await client.titles(after=cursor, kind="artist")
        items.extend(item for item in page.get("items") or [] if item.get("kind") == "artist")
        removed.extend(page.get("removed") or [])
        latest = int(page.get("latest") or 0)
        cursor = int(page.get("next_after") or cursor)
        if not page.get("more"):
            return items, removed, latest, cursor


async def _sync_from_nexcrate(db: Session, settings: AppSettings) -> int | None:
    """Kuenstler aus nexcrate, ganz oder seit der letzten Nummer.

    Ganz gelesen wird beim ersten Mal, nach ``410 marker_too_old``, einmal am Tag, und wenn die Marke
    nicht zu dieser nexcrate passt: andere Adresse, andere ``installation_id``, oder eine Nummer ueber
    ``latest``. Gemessen am 22.09.2026: nexcrate beantwortet ``after`` ueber ``latest`` still mit einer
    leeren Seite. Eine neu aufgesetzte nexcrate hiesse sonst fuer immer "nichts geaendert".
    """
    client = nexcrate.client_for(settings)
    if client is None:
        return None
    now = utcnow()
    installation = str((await client.system()).get("installation_id") or "")
    marker = _marker(settings)
    after = int(marker.get("after") or 0)
    fresh = _stale(marker, settings.text("nexcrate_url"), installation, now)
    try:
        items, removed, latest, cursor = await _read_artists(client, 0 if fresh else after)
    except nexcrate.NexcrateError as error:
        if error.code != "nexcrate_marker_too_old":
            raise
        fresh = True
        items, removed, latest, cursor = await _read_artists(client, 0)
    if not fresh and after > latest:
        fresh = True
        items, removed, latest, cursor = await _read_artists(client, 0)

    existing = {row.mbid: row for row in db.scalars(select(LibraryArtist))}
    seen: set[str] = set()
    for item in items:
        mbid = nexcrate.mbid_of(item.get("ref"))
        if mbid and mbid not in seen:
            seen.add(mbid)
            _apply_artist(existing.get(mbid), item, db, now)
    if fresh:
        gone = [row for mbid, row in existing.items() if mbid not in seen]
    else:
        gone_mbids = {nexcrate.mbid_of(entry.get("ref")) for entry in removed if entry.get("kind") == "artist"}
        gone = [existing[mbid] for mbid in gone_mbids if mbid in existing and mbid not in seen]
    for row in gone:
        db.delete(row)
    for mbid in seen:
        cache.forget(db, nexcrate_albums_key(mbid))
    db.commit()
    record = {
        "url": settings.text("nexcrate_url"),
        "installation": installation,
        "after": max(cursor, latest) if fresh else max(cursor, after),
        "full_at": now.isoformat() if fresh else marker.get("full_at"),
    }
    save_settings(db, {"nexcrate_marker": json.dumps(record)}, internal=True)
    count = len(list(db.scalars(select(LibraryArtist.mbid))))
    logger.info(
        "Library sync from nexcrate (%s): %d changed, %d gone, %d artists",
        "full" if fresh else f"after {after}",
        len(seen),
        len(gone),
        count,
    )
    return count


def album_state(album: dict[str, Any]) -> dict[str, Any]:
    """Zustand eines Lidarr-Albums fuer die Oberflaeche.

    ``available`` alle Titel da, ``partial`` einige, ``wanted`` ueberwacht ohne
    Dateien, ``known`` in Lidarr bekannt, aber nicht ueberwacht.
    """
    statistics = album.get("statistics") or {}
    files = int(statistics.get("trackFileCount") or 0)
    percent = float(statistics.get("percentOfTracks") or 0)
    if files > 0 and percent >= 100:
        state = "available"
    elif files > 0:
        state = "partial"
    elif album.get("monitored"):
        state = "wanted"
    else:
        state = "known"
    return {"state": state, "percent": min(100, round(percent)), "lidarr_id": album.get("id")}


def albums_key(lidarr_artist_id: int) -> str:
    return f"lidarr:albums:{lidarr_artist_id}"


def nexcrate_albums_key(artist_mbid: str) -> str:
    return f"nexcrate:albums:{artist_mbid}"


async def _nexcrate_album_states(db: Session, settings: AppSettings, artist_mbid: str) -> dict[str, dict[str, Any]]:
    """Der Katalog des Kuenstlers aus nexcrate, mit dem Zustand je Album."""
    client = nexcrate.client_for(settings)
    if client is None or db.get(LibraryArtist, artist_mbid) is None:
        return {}

    async def load() -> list[dict[str, Any]]:
        title = await client.title("artist", artist_mbid)
        catalogue = ((title or {}).get("artist") or {}).get("catalogue") or []
        return [
            {"ref": item.get("ref"), **nexcrate.album_view(item).__dict__}
            for item in catalogue
            if item.get("kind") == "album"
        ]

    try:
        albums = await cache.cached(db, nexcrate_albums_key(artist_mbid), ALBUM_TTL, load)
    except nexcrate.NexcrateError as error:
        logger.warning("Album states for artist %s unavailable: %s", artist_mbid, error.code)
        return {}
    states: dict[str, dict[str, Any]] = {}
    for album in albums:
        mbid = nexcrate.mbid_of(album.get("ref"))
        if mbid:
            states[mbid] = {"state": album["state"], "percent": album["percent"], "lidarr_id": None}
    return states


async def album_states(db: Session, settings: AppSettings, artist_mbid: str) -> dict[str, dict[str, Any]]:
    if settings.mode == "nex":
        return await _nexcrate_album_states(db, settings, artist_mbid)
    row = db.get(LibraryArtist, artist_mbid)
    client = lidarr.client_for(settings)
    if row is None or client is None:
        return {}

    async def load() -> list[dict[str, Any]]:
        return [lidarr.compact_album(album) for album in await client.albums_for_artist(row.lidarr_id)]

    try:
        albums = await cache.cached(db, albums_key(row.lidarr_id), ALBUM_TTL, load)
    except lidarr.LidarrError as error:
        logger.warning("Album states for artist %s unavailable: %s", artist_mbid, error.code)
        return {}
    return {album["foreignAlbumId"]: album_state(album) for album in albums if album.get("foreignAlbumId")}


def forget_albums(db: Session, lidarr_artist_id: int | None) -> None:
    if lidarr_artist_id:
        cache.forget(db, albums_key(lidarr_artist_id))


def forget_nexcrate_albums(db: Session, artist_mbid: str | None) -> None:
    if artist_mbid:
        cache.forget(db, nexcrate_albums_key(artist_mbid))


def profile_key(profile_id: int) -> str:
    return f"lidarr:metadata-profile:{profile_id}"


async def _relevant_profile(db: Session, settings: AppSettings, artist_mbid: str) -> tuple[dict[str, Any] | None, bool]:
    """Das massgebliche Metadatenprofil aus dem Zwischenspeicher, und ob es das des Kuenstlers ist.

    Steht der Kuenstler schon in Lidarr, zaehlt sein eigenes Profil. Das aus den
    Einstellungen gilt nur fuer Kuenstler, die nexbeat neu anlegt. 12.09.2026: In
    nexbeat stand ein Profil mit Soundtracks, der Kuenstler hatte in Lidarr
    "Standard", und die Anfrage scheiterte.

    Vorpruefung fuer Seiten und Anfragen: Eine Aenderung am Profil kommt nach
    spaetestens fuenf Minuten an, ein anderes Profil am Kuenstler mit dem naechsten
    Abgleich. Antwortet Lidarr nicht, kommt None, und die Vorpruefung haelt nichts
    auf. Die Uebergabe prueft ohnehin frisch.
    """
    client = lidarr.client_for(settings)
    if client is None:
        # Im NEX-Modus gibt es kein Metadatenprofil. Welche Alben ein ganzer Kuenstler bringt, legt
        # nexbeat selbst fest (``nexcrate.WHOLE_ARTIST``).
        return None, False
    row = db.get(LibraryArtist, artist_mbid) if artist_mbid else None
    artist_profile = row.metadata_profile_id if row is not None else 0
    profile_id = artist_profile or settings.number("lidarr_metadata_profile_id")
    if client is None or not profile_id:
        return None, False

    async def load() -> dict[str, Any]:
        return await client.metadata_profile(profile_id)

    try:
        profile = await cache.cached(db, profile_key(profile_id), PROFILE_TTL, load)
    except lidarr.LidarrError as error:
        logger.warning("Metadata profile %s unavailable: %s", profile_id, error.code)
        return None, False
    return profile, bool(artist_profile)


async def type_block(db: Session, settings: AppSettings, group: dict[str, Any]) -> str | None:
    """Schliesst das massgebliche Profil diese Art Release aus? Dann die Kennung."""
    profile, from_artist = await _relevant_profile(db, settings, group.get("artist_mbid") or "")
    primary, secondary = group.get("primary_type") or "", group.get("secondary_types") or []
    if profile is None or lidarr.type_allowed(profile, primary, secondary):
        return None
    return "artist_profile_excludes_type" if from_artist else "release_type_excluded"


async def whole_artist_block(db: Session, settings: AppSettings, artist_mbid: str) -> str | None:
    """Laesst das massgebliche Profil mehr als Studioalben zu? Dann die Kennung.

    "Ganzer Kuenstler" ueberwacht auch alle kuenftigen Alben. Nur ein Profil, das
    allein Studioalben zulaesst, haelt das bei Studioalben. 12.09.2026: Mit einem
    weiten Profil kam eine Band mit weit ueber tausend Alben nach Lidarr.
    """
    profile, from_artist = await _relevant_profile(db, settings, artist_mbid)
    if profile is None or lidarr.studio_only(profile):
        return None
    return "artist_profile_not_studio_only" if from_artist else "profile_not_studio_only"
