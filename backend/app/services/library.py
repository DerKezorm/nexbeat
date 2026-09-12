"""Der Lidarr-Bestand aus Sicht von nexbeat.

Kuenstler werden regelmaessig nach ``library_artists`` gespiegelt, damit
Empfehlungen und Abzeichen ohne Lidarr-Aufruf auskommen. Die Alben eines
Kuenstlers kommen bei Bedarf und leben fuenf Minuten im Zwischenspeicher,
ebenso die Metadatenprofile.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import LibraryArtist, utcnow
from . import cache, lidarr
from .settings_service import AppSettings

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


async def sync_artists(db: Session, settings: AppSettings) -> int | None:
    """Kuenstlerliste aus Lidarr uebernehmen. ``None``, wenn Lidarr fehlt."""
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


async def album_states(db: Session, settings: AppSettings, artist_mbid: str) -> dict[str, dict[str, Any]]:
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


def profile_key(profile_id: int) -> str:
    return f"lidarr:metadata-profile:{profile_id}"


async def _relevant_profile(
    db: Session, settings: AppSettings, artist_mbid: str
) -> tuple[dict[str, Any] | None, bool]:
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
