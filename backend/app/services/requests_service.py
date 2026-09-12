"""Anfragen: anlegen, entscheiden, an Lidarr uebergeben, Stand nachfuehren.

Ablauf einer Anfrage fuer genau ein Release:

1. Dubletten, Bestand, Art und Kontingent pruefen. Schliesst das Metadatenprofil in
   Lidarr die Art aus, entsteht gar keine Anfrage. 12.09.2026: Vorher entstand sie und
   scheiterte sofort, die Seite zeigte wieder "Anfragen", als sei nichts passiert.
   ⚠️ Dubletten und Kontingent stehen ein zweites Mal direkt vor dem Speichern, ohne
   ``await`` dazwischen. Sonst kamen zwei gleichzeitige Anfragen beide durch (12.09.2026).
2. Wer auf Freigabe steht, wartet auf einen Admin. Alle anderen gehen sofort weiter.
3. Bei der Uebergabe prueft nexbeat die Art noch einmal, frisch aus Lidarr. Sonst
   legte Lidarr einen Kuenstler an, dessen Album nie erscheint. Listet Lidarr das
   Album schon, laesst das Profil des Kuenstlers es offenbar zu.
4. Kennt Lidarr den Kuenstler nicht, wird er ueberwacht angelegt, mit genau diesem
   Album in ``albumsToMonitor`` und ``monitorNewItems: none``. Lidarr ueberwacht
   dann nur dieses Album und laedt nicht die ganze Diskografie.
   ⚠️ Nie ``monitor: none``: Damit setzt Lidarr den Kuenstler auf nicht ueberwacht,
   und die Suche nach dem Anlegen findet nichts. Gemessen am 12.09.2026.
5. Kennt Lidarr ihn schon, wird nur das Album ueberwacht und gesucht.
6. Der Abgleich im Hintergrund setzt "geladen", sobald Lidarr alle Titel hat.

Vor dem ersten Aufruf an Lidarr steht ``lidarr_pending`` in der Datenbank. Bricht die
Uebergabe ab oder antwortet Lidarr nicht rechtzeitig, bringt der Abgleich sie zu Ende,
sobald klar ist, was angekommen ist (``_resume_now``).

Ganzer Kuenstler, entschieden am 12.09.2026: zaehlt als eine Anfrage, Freigabe
wie bei Alben. Ueberwacht werden alle Alben ohne Zusatztyp und alle kuenftigen
Veroeffentlichungen (``monitorNewItems: all``). Bei kuenftigen filtert Lidarr
nicht nach Art, das tut nur sein Metadatenprofil.

⚠️ Im Probelauf (``lidarr_dry_run``) geht nichts an Lidarr, auch nicht aus dem Abgleich.
Die Anfrage bleibt mit der Kennung ``dry_run`` stehen und laesst sich spaeter erneut senden.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ALBUM_KIND, ARTIST_KIND, OPEN_STATUSES, MusicRequest, RequestStatus, User, utcnow
from . import catalog, coverart, library, lidarr, quota
from .musicbrainz import MusicBrainzError
from .settings_service import AppSettings

logger = logging.getLogger("nexbeat.requests")

#: So lange darf Lidarr brauchen, bis ein neu angelegter Kuenstler das Album zeigt.
ALBUM_APPEAR_TIMEOUT = timedelta(minutes=30)
#: Kennungen, bei denen offen ist, ob Lidarr den Auftrag bekommen hat. ``lidarr_pending``
#: steht waehrend jeder Uebergabe da und bleibt nur stehen, wenn sie abbrach.
UNCERTAIN_CODES = ("lidarr_timeout", "lidarr_pending")
#: Fehlt der Kuenstler in Lidarr nach dieser Zeit noch, kam das Anlegen nie an, und der Abgleich
#: sendet die Anfrage neu. Frueher kann die Uebergabe noch unterwegs sein, und ein zweites
#: Anlegen scheitert in Lidarr.
RESUME_AFTER = timedelta(minutes=10)


class RequestProblem(Exception):
    def __init__(self, code: str, message: str, status_code: int, **values: Any) -> None:
        super().__init__(code)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.values = values


def iso(value: datetime | None) -> str | None:
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z") if value else None


def serialize(request: MusicRequest, *, with_user: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": request.id,
        "kind": request.kind,
        "release_group_mbid": request.release_group_mbid,
        "artist_mbid": request.artist_mbid,
        "title": request.title,
        "artist_name": request.artist_name,
        "album_type": request.album_type,
        "release_date": request.release_date,
        "cover_url": request.cover_url,
        "status": request.status.value,
        "requested_at": iso(request.requested_at),
        "decided_at": iso(request.decided_at),
        "rejection_reason": request.rejection_reason,
        "submitted_at": iso(request.submitted_at),
        "completed_at": iso(request.completed_at),
        "progress": request.progress,
        "error_code": request.error_code,
    }
    if with_user:
        data["user"] = {
            "id": request.user.id,
            "username": request.user.username,
            "display_name": request.user.display_name,
        }
        data["error_message"] = request.error_message
    return data


def _check_quota(db: Session, settings: AppSettings, user: User) -> None:
    state = quota.state(db, user, settings)
    if state.exhausted:
        raise RequestProblem(
            "quota_exhausted",
            "The quota for this period is used up.",
            429,
            limit=state.limit,
            resets_at=iso(state.resets_at),
        )


def _check_duplicate(db: Session, user_id: int, kind: str, mbid: str, exclude: int | None = None) -> None:
    """Gibt es schon eine offene Anfrage fuer dasselbe Release oder denselben ganzen Kuenstler?"""
    if kind == ARTIST_KIND:
        query = select(MusicRequest).where(MusicRequest.kind == ARTIST_KIND, MusicRequest.artist_mbid == mbid)
    else:
        query = select(MusicRequest).where(MusicRequest.release_group_mbid == mbid)
    query = query.where(MusicRequest.status.in_(OPEN_STATUSES))
    if exclude is not None:
        query = query.where(MusicRequest.id != exclude)
    existing = db.scalar(query.limit(1))
    if existing is not None:
        subject = "artist" if kind == ARTIST_KIND else "release"
        raise RequestProblem(
            "already_requested", f"This {subject} has already been requested.", 409, mine=existing.user_id == user_id
        )


def _musicbrainz_problem(error: MusicBrainzError) -> RequestProblem:
    status = 404 if error.code == "musicbrainz_not_found" else 503
    return RequestProblem(error.code, "MusicBrainz could not answer.", status)


async def create(db: Session, settings: AppSettings, user: User, release_group_mbid: str) -> MusicRequest:
    if not settings.lidarr_ready:
        raise RequestProblem("requests_not_ready", "Requests are not set up yet.", 409)
    try:
        group = await catalog.release_group_info(db, release_group_mbid)
    except MusicBrainzError as error:
        raise _musicbrainz_problem(error) from error
    if not group.get("artist_mbid"):
        raise RequestProblem("album_without_artist", "This release has no artist in MusicBrainz.", 422)
    _check_duplicate(db, user.id, ALBUM_KIND, release_group_mbid)

    states = await library.album_states(db, settings, group["artist_mbid"])
    if (states.get(release_group_mbid) or {}).get("state") == "available":
        raise RequestProblem("already_available", "This release is already in the library.", 409)
    blocked = await library.type_block(db, settings, group) if release_group_mbid not in states else None
    if blocked:
        raise RequestProblem(blocked, library.TYPE_BLOCKS[blocked], 422)

    # Ab hier kein await bis zum Speichern, siehe Kopf der Datei.
    _check_duplicate(db, user.id, ALBUM_KIND, release_group_mbid)
    _check_quota(db, settings, user)

    needs_approval = user.requires_approval and not user.is_admin
    request = MusicRequest(
        user_id=user.id,
        release_group_mbid=release_group_mbid,
        artist_mbid=group["artist_mbid"],
        title=group["title"][:512],
        artist_name=group["artist_name"][:512],
        album_type=group.get("primary_type") or "",
        release_date=(group.get("first_release_date") or "")[:10],
        cover_url=coverart.release_group_front(release_group_mbid, 500),
        status=RequestStatus.pending_approval if needs_approval else RequestStatus.approved,
    )
    db.add(request)
    db.commit()
    logger.info("Request %s created (%s)", request.id, request.status.value)
    if not needs_approval:
        await submit(db, settings, request)
    return request


async def create_artist(db: Session, settings: AppSettings, user: User, artist_mbid: str) -> MusicRequest:
    """Alle Studioalben eines Kuenstlers und die kuenftigen, als eine Anfrage."""
    if not settings.lidarr_ready:
        raise RequestProblem("requests_not_ready", "Requests are not set up yet.", 409)
    _check_duplicate(db, user.id, ARTIST_KIND, artist_mbid)
    blocked = await library.whole_artist_block(db, settings, artist_mbid)
    if blocked:
        raise RequestProblem(blocked, library.TYPE_BLOCKS[blocked], 422)

    _check_quota(db, settings, user)

    try:
        info = await catalog.artist_info(db, artist_mbid)
        albums = await catalog.studio_albums(db, artist_mbid)
    except MusicBrainzError as error:
        raise _musicbrainz_problem(error) from error
    if not albums:
        raise RequestProblem("artist_without_albums", "MusicBrainz lists no studio albums for this artist.", 422)

    # Ab hier kein await bis zum Speichern, siehe Kopf der Datei.
    _check_duplicate(db, user.id, ARTIST_KIND, artist_mbid)
    _check_quota(db, settings, user)

    needs_approval = user.requires_approval and not user.is_admin
    name = (info.get("name") or "")[:512]
    request = MusicRequest(
        user_id=user.id,
        kind=ARTIST_KIND,
        release_group_mbid="",
        artist_mbid=artist_mbid,
        title=name,
        artist_name=name,
        cover_url=catalog.artist_image_path(artist_mbid, name),
        status=RequestStatus.pending_approval if needs_approval else RequestStatus.approved,
    )
    db.add(request)
    db.commit()
    logger.info("Artist request %s created (%s)", request.id, request.status.value)
    if not needs_approval:
        await submit(db, settings, request)
    return request


def _fail(db: Session, request: MusicRequest, code: str, message: str) -> None:
    request.status = RequestStatus.failed
    request.error_code = code
    request.error_message = (message or "")[:500]
    db.commit()
    logger.warning("Request %s failed: %s", request.id, code)


async def submit(db: Session, settings: AppSettings, request: MusicRequest) -> None:
    client = lidarr.client_for(settings)
    request.submitted_at = utcnow()
    if client is None or not settings.lidarr_ready:
        _fail(db, request, "requests_not_ready", "Lidarr is not configured.")
        return
    if settings.flag("lidarr_dry_run"):
        request.status = RequestStatus.approved
        request.error_code = "dry_run"
        request.error_message = "Dry run: nothing was sent to Lidarr."
        db.commit()
        logger.info("Dry run: request %s was not sent to Lidarr", request.id)
        return
    # Vor dem ersten Aufruf gespeichert. 12.09.2026: Brach die Uebergabe ab, blieb die Anfrage
    # fuer immer "freigegeben", und nichts sah wieder nach.
    request.error_code = "lidarr_pending"
    request.error_message = "Hand-over to Lidarr started, not confirmed yet."
    db.commit()
    try:
        if request.kind == ARTIST_KIND:
            await _submit_artist(db, client, settings, request)
        else:
            await _submit_album(db, client, settings, request)
    except lidarr.LidarrError as error:
        if error.uncertain:
            request.error_code = error.code
            request.error_message = "Lidarr did not answer in time. The background check will look again."
            db.commit()
        else:
            _fail(db, request, error.code, error.detail)
        return
    except MusicBrainzError as error:
        _fail(db, request, error.code, "MusicBrainz could not answer.")
        return
    db.commit()
    logger.info("Request %s handed to Lidarr", request.id)


def _lidarr_target(settings: AppSettings) -> dict[str, Any]:
    return {
        "qualityProfileId": settings.number("lidarr_quality_profile_id"),
        "metadataProfileId": settings.number("lidarr_metadata_profile_id"),
        "rootFolderPath": settings.text("lidarr_root_folder"),
    }


def _find_artist(artists: list[dict[str, Any]], artist_mbid: str) -> dict[str, Any] | None:
    return next((item for item in artists if item.get("foreignArtistId") == artist_mbid), None)


async def _submit_album(
    db: Session, client: lidarr.LidarrClient, settings: AppSettings, request: MusicRequest
) -> None:
    artist = _find_artist(await client.artists(), request.artist_mbid)
    listed: list[dict[str, Any]] = []
    if artist is not None:
        request.lidarr_artist_id = artist.get("id")
        listed = await client.albums_by_foreign_id(request.release_group_mbid)
    if not listed:
        # Listet Lidarr das Album, laesst das Profil des Kuenstlers es offenbar zu. Sonst
        # zaehlt bei einem Kuenstler in Lidarr sein eigenes Profil, bei einem neuen das aus
        # den Einstellungen. Frisch gelesen: Bis zur Freigabe kann es sich geaendert haben.
        group = await catalog.release_group_info(db, request.release_group_mbid)
        artist_profile = int((artist or {}).get("metadataProfileId") or 0)
        profile = await client.metadata_profile(artist_profile or settings.number("lidarr_metadata_profile_id") or 0)
        if not lidarr.type_allowed(profile, group.get("primary_type") or "", group.get("secondary_types") or []):
            if artist_profile:
                raise lidarr.LidarrError(
                    "artist_profile_excludes_type", library.TYPE_BLOCKS["artist_profile_excludes_type"]
                )
            raise lidarr.LidarrError("release_type_excluded", library.TYPE_BLOCKS["release_type_excluded"])
    if artist is None:
        await _add_artist(client, settings, request)
    else:
        await _monitor_existing(db, client, request, listed)


async def _add_artist(client: lidarr.LidarrClient, settings: AppSettings, request: MusicRequest) -> None:
    found = await client.lookup_artist(request.artist_mbid)
    if found is None:
        raise lidarr.LidarrError("artist_not_found_in_lidarr", request.artist_mbid)
    payload = {
        **found,
        **_lidarr_target(settings),
        "monitored": True,
        "monitorNewItems": "none",
        "addOptions": {
            # Nicht "none": Damit legt Lidarr den Kuenstler unueberwacht an, und die
            # Suche nach dem Anlegen laesst ihn aus. Nicht "all": Das ueberwachte bei
            # leerer Liste die ganze Diskografie. Mit Liste zaehlt nur die Liste.
            "monitor": "unknown",
            "albumsToMonitor": [request.release_group_mbid],
            "monitored": True,
            "searchForMissingAlbums": True,
        },
    }
    created = await client.add_artist(payload)
    request.lidarr_artist_id = created.get("id")
    request.status = RequestStatus.searching
    request.error_code = ""
    request.error_message = ""


async def _monitor_existing(
    db: Session, client: lidarr.LidarrClient, request: MusicRequest, albums: list[dict[str, Any]]
) -> None:
    album = next((item for item in albums if item.get("artistId") == request.lidarr_artist_id), None)
    if album is None and albums:
        album = albums[0]
    if album is None:
        raise lidarr.LidarrError(
            "album_not_in_lidarr",
            "Lidarr does not list this release for the artist. Its metadata may not be refreshed yet.",
        )
    request.lidarr_album_id = album.get("id")
    if not album.get("monitored"):
        await client.monitor_albums([album["id"]])
    await client.search_albums([album["id"]])
    request.status = RequestStatus.searching
    request.error_code = ""
    request.error_message = ""
    library.forget_albums(db, request.lidarr_artist_id)


async def _submit_artist(
    db: Session, client: lidarr.LidarrClient, settings: AppSettings, request: MusicRequest
) -> None:
    artist = _find_artist(await client.artists(), request.artist_mbid)
    # Nur ein Profil, das allein Studioalben zulaesst, haelt "alle kuenftigen" bei Studioalben.
    # Frisch gelesen: Bis zur Freigabe kann es sich geaendert haben.
    artist_profile = int((artist or {}).get("metadataProfileId") or 0)
    profile = await client.metadata_profile(artist_profile or settings.number("lidarr_metadata_profile_id") or 0)
    if not lidarr.studio_only(profile):
        if artist_profile:
            raise lidarr.LidarrError(
                "artist_profile_not_studio_only", library.TYPE_BLOCKS["artist_profile_not_studio_only"]
            )
        raise lidarr.LidarrError("profile_not_studio_only", library.TYPE_BLOCKS["profile_not_studio_only"])
    if artist is None:
        albums = await catalog.studio_albums(db, request.artist_mbid)
        if not albums:
            raise lidarr.LidarrError("artist_without_albums", "MusicBrainz lists no studio albums for this artist.")
        found = await client.lookup_artist(request.artist_mbid)
        if found is None:
            raise lidarr.LidarrError("artist_not_found_in_lidarr", request.artist_mbid)
        created = await client.add_artist(
            {
                **found,
                **_lidarr_target(settings),
                "monitored": True,
                "monitorNewItems": "all",
                "addOptions": {
                    "monitor": "unknown",
                    "albumsToMonitor": [album["mbid"] for album in albums],
                    "monitored": True,
                    "searchForMissingAlbums": True,
                },
            }
        )
        request.lidarr_artist_id = created.get("id")
    else:
        # Erst nachsehen, dann aendern: Ohne Studioalben bleibt der Kuenstler in Lidarr unberuehrt.
        albums = [album for album in await client.albums_for_artist(artist["id"]) if lidarr.is_studio_album(album)]
        if not albums:
            raise lidarr.LidarrError(
                "artist_albums_not_in_lidarr", "Lidarr lists no studio albums for this artist."
            )
        if artist.get("monitored") is not True or artist.get("monitorNewItems") != "all":
            await client.update_artist({**artist, "monitored": True, "monitorNewItems": "all"})
        unmonitored = [album["id"] for album in albums if not album.get("monitored")]
        if unmonitored:
            await client.monitor_albums(unmonitored)
        missing = [album["id"] for album in albums if library.album_state(album)["state"] != "available"]
        if missing:
            await client.search_albums(missing)
        request.lidarr_artist_id = artist["id"]
        library.forget_albums(db, artist["id"])
    request.status = RequestStatus.searching
    request.error_code = ""
    request.error_message = ""


async def approve(db: Session, settings: AppSettings, admin: User, request: MusicRequest) -> None:
    if request.status != RequestStatus.pending_approval:
        raise RequestProblem("request_not_pending", "This request is not waiting for approval.", 409)
    request.status = RequestStatus.approved
    request.decided_by = admin.id
    request.decided_at = utcnow()
    db.commit()
    await submit(db, settings, request)


def reject(db: Session, admin: User, request: MusicRequest, reason: str) -> None:
    if request.status != RequestStatus.pending_approval:
        raise RequestProblem("request_not_pending", "This request is not waiting for approval.", 409)
    request.status = RequestStatus.rejected
    request.decided_by = admin.id
    request.decided_at = utcnow()
    request.rejection_reason = reason.strip()[:500]
    db.commit()


def cancel(db: Session, user: User, request: MusicRequest) -> None:
    waiting = request.status == RequestStatus.pending_approval
    unsent = request.status == RequestStatus.approved and request.error_code == "dry_run"
    if not (waiting or unsent):
        raise RequestProblem("request_not_cancellable", "This request can no longer be withdrawn.", 409)
    request.status = RequestStatus.cancelled
    db.commit()


async def retry(db: Session, settings: AppSettings, request: MusicRequest) -> None:
    unsent = request.status == RequestStatus.approved and request.error_code == "dry_run"
    if request.status == RequestStatus.approved and not unsent:
        # Offen, ob Lidarr den Auftrag hat. 12.09.2026: Erneut gesendet scheiterte die Anfrage, wenn
        # Lidarr den Kuenstler inzwischen angelegt hatte. Der Abgleich bringt sie zu Ende.
        raise RequestProblem(
            "request_still_checking", "nexbeat is still checking whether Lidarr got this request.", 409
        )
    if request.status != RequestStatus.failed and not unsent:
        raise RequestProblem("request_not_retryable", "This request cannot be sent again.", 409)
    if request.status == RequestStatus.failed:
        # Eine gescheiterte Anfrage zaehlt nicht. Erneut gesendet zaehlt sie wieder, also gelten
        # Dubletten und Kontingent wie beim Anlegen.
        subject = request.artist_mbid if request.kind == ARTIST_KIND else request.release_group_mbid
        _check_duplicate(db, request.user_id, request.kind, subject, exclude=request.id)
        _check_quota(db, settings, request.user)
    request.status = RequestStatus.approved
    request.error_code = ""
    request.error_message = ""
    request.search_retried_at = None
    db.commit()
    await submit(db, settings, request)


async def _artist_albums(client: lidarr.LidarrClient, request: MusicRequest) -> list[dict[str, Any]]:
    if request.lidarr_artist_id is None:
        artist = _find_artist(await client.artists(), request.artist_mbid)
        if artist is None:
            return []
        request.lidarr_artist_id = artist.get("id")
    return await client.albums_for_artist(request.lidarr_artist_id)


def _wanted_studio_albums(albums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [album for album in albums if album.get("monitored") and lidarr.is_studio_album(album)]


def _follow_artist(db: Session, request: MusicRequest, albums: list[dict[str, Any]], now: datetime) -> int:
    """Stand einer Anfrage fuer den ganzen Kuenstler: alle ueberwachten Studioalben zusammen."""
    wanted = _wanted_studio_albums(albums)
    if not wanted:
        if request.submitted_at and now - request.submitted_at > ALBUM_APPEAR_TIMEOUT:
            _fail(db, request, "artist_albums_not_in_lidarr", "Lidarr still lists no monitored studio albums.")
            return 1
        return 0
    available = sum(1 for album in wanted if library.album_state(album)["state"] == "available")
    request.progress = round(100 * available / len(wanted))
    changed = 0
    if available == len(wanted):
        request.status = RequestStatus.downloaded
        request.completed_at = now
        request.error_code = ""
        request.error_message = ""
        changed = 1
    elif request.status == RequestStatus.approved:
        request.status = RequestStatus.searching
        request.error_code = ""
        request.error_message = ""
        changed = 1
    db.commit()
    return changed


def _album_of(request: MusicRequest, albums: list[dict[str, Any]]) -> dict[str, Any] | None:
    wanted_artist = request.lidarr_artist_id
    return next((item for item in albums if wanted_artist is None or item.get("artistId") == wanted_artist), None)


async def _resume_now(
    client: lidarr.LidarrClient, request: MusicRequest, albums: list[dict[str, Any]], now: datetime
) -> bool:
    """Laesst sich eine Uebergabe mit offenem Ausgang jetzt sicher zu Ende bringen?

    Ja, wenn Lidarr das Album listet, beim ganzen Kuenstler ein Studioalbum. Dann fehlen
    hoechstens Ueberwachen und Suche, und doppelt schadet beides nicht. 12.09.2026: Vorher galt
    eine Anfrage nach einer Zeitueberschreitung beim Ueberwachen als "sucht", obwohl Lidarr das
    Album nie ueberwachte. Ein ganzer Kuenstler galt als geladen, sobald die schon vorher
    ueberwachten Alben da waren.

    Ja auch, wenn der Kuenstler nach ``RESUME_AFTER`` noch fehlt: Dann kam das Anlegen nie an.
    Nein, solange Lidarr den Kuenstler kennt, aber noch nichts davon listet. Dann liest es
    womoeglich noch ein, und neu gesendet scheiterte die Anfrage mit ``album_not_in_lidarr``.
    """
    if request.kind == ARTIST_KIND:
        if any(lidarr.is_studio_album(album) for album in albums):
            return True
        artist_known = request.lidarr_artist_id is not None
    else:
        album = _album_of(request, albums)
        if album is not None:
            return library.album_state(album)["state"] != "available"
        artist_known = request.lidarr_artist_id is not None or (
            _find_artist(await client.artists(), request.artist_mbid) is not None
        )
    if artist_known:
        return False
    return request.submitted_at is not None and now - request.submitted_at > RESUME_AFTER


#: So lange darf eine Anfrage ohne Download und ohne Eintrag in Lidarrs Warteschlange stehen,
#: bevor nexbeat die Suche einmal selbst anstoesst. 12.09.2026: Lidarrs Suche nach dem Anlegen
#: fiel mit "database is locked" aus und wurde nie wiederholt. Geladen wurde erst nach einer
#: Suche von Hand.
SEARCH_AGAIN_AFTER = timedelta(minutes=10)


def _waiting_without_download(request: MusicRequest, albums: list[dict[str, Any]], now: datetime) -> bool:
    """Seit Minuten nichts geladen, und nexbeat hat noch nicht nachgesucht?"""
    return (
        request.status == RequestStatus.searching
        and request.search_retried_at is None
        and request.submitted_at is not None
        and now - request.submitted_at > SEARCH_AGAIN_AFTER
        and bool(albums)
        and all(int((album.get("statistics") or {}).get("trackFileCount") or 0) == 0 for album in albums)
    )


async def _search_again(
    db: Session, client: lidarr.LidarrClient, stuck: list[tuple[MusicRequest, list[int]]], now: datetime
) -> None:
    """Einmal nachsuchen, wenn auch Lidarrs Warteschlange nichts fuer diese Alben hat."""
    if not stuck:
        return
    try:
        queued = {record.get("albumId") for record in await client.queue()}
        for request, album_ids in stuck:
            if queued & set(album_ids):
                continue
            await client.search_albums(album_ids)
            request.search_retried_at = now
            db.commit()
            logger.info("Request %s: nothing loaded after %s, searched again", request.id, SEARCH_AGAIN_AFTER)
    except lidarr.LidarrError as error:
        logger.info("Search again skipped: %s", error.code)


async def refresh_open(db: Session, settings: AppSettings, now: datetime | None = None) -> int:
    """Stand der offenen Anfragen bei Lidarr nachsehen. Gibt die Zahl der Aenderungen zurueck."""
    client = lidarr.client_for(settings)
    if client is None:
        return 0
    now = now or utcnow()
    # Im Probelauf schreibt auch der Abgleich nichts nach Lidarr: kein Fortsetzen, kein Nachsuchen.
    writes = not settings.flag("lidarr_dry_run")
    changed = 0
    stuck: list[tuple[MusicRequest, list[int]]] = []
    open_requests = list(
        db.scalars(
            select(MusicRequest).where(MusicRequest.status.in_((RequestStatus.approved, RequestStatus.searching)))
        )
    )
    for request in open_requests:
        uncertain = request.status == RequestStatus.approved and request.error_code in UNCERTAIN_CODES
        # Freigegeben, aber nie gesendet (Probelauf): nichts nachzusehen.
        if request.status == RequestStatus.approved and not uncertain:
            continue
        try:
            if request.kind == ARTIST_KIND:
                albums = await _artist_albums(client, request)
            else:
                albums = await client.albums_by_foreign_id(request.release_group_mbid)
            resume = uncertain and writes and await _resume_now(client, request, albums, now)
        except lidarr.LidarrError as error:
            logger.info("Status check skipped for request %s: %s", request.id, error.code)
            if error.code in ("lidarr_unreachable", "lidarr_timeout", "lidarr_key_rejected"):
                break
            continue
        if resume:
            before = (request.status, request.error_code)
            logger.info("Request %s: finishing a hand-over that did not complete", request.id)
            await submit(db, settings, request)
            changed += int((request.status, request.error_code) != before)
            continue
        if request.kind == ARTIST_KIND:
            changed += _follow_artist(db, request, albums, now)
            wanted = _wanted_studio_albums(albums)
            if _waiting_without_download(request, wanted, now):
                stuck.append((request, [album["id"] for album in wanted]))
            continue
        album = _album_of(request, albums)
        if album is None:
            if request.submitted_at and now - request.submitted_at > ALBUM_APPEAR_TIMEOUT:
                code = "album_not_in_lidarr" if request.status == RequestStatus.searching else request.error_code
                _fail(db, request, code, "Lidarr still does not list this release.")
                changed += 1
            continue
        state = library.album_state(album)
        request.lidarr_album_id = album.get("id")
        request.lidarr_artist_id = request.lidarr_artist_id or album.get("artistId")
        request.progress = state["percent"]
        if state["state"] == "available":
            request.status = RequestStatus.downloaded
            request.completed_at = now
            request.error_code = ""
            request.error_message = ""
            changed += 1
        elif request.status == RequestStatus.approved:
            request.status = RequestStatus.searching
            request.error_code = ""
            request.error_message = ""
            changed += 1
        db.commit()
        if _waiting_without_download(request, [album], now):
            stuck.append((request, [album["id"]]))
    if writes:
        await _search_again(db, client, stuck, now)
    return changed
