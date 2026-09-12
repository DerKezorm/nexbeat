"""Suche, Genres, Kuenstler- und Albumseiten, Kuenstlerbilder."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import RedirectResponse

from ..deps import CurrentUser, DbSession
from ..meldungen import fehler
from ..services import catalog, genres
from ..services.deezer import DeezerError
from ..services.listenbrainz import ListenBrainzError
from ..services.musicbrainz import MusicBrainzError
from ..services.settings_service import load_settings

router = APIRouter(tags=["catalog"])


def _mbid(value: str) -> str:
    if not catalog.valid_mbid(value):
        raise fehler("invalid_mbid", "This is not a MusicBrainz ID.", 422)
    return value


def _genre(value: str) -> str:
    tag = genres.normalize_tag(value)
    if tag is None:
        raise fehler("invalid_genre", "This is not a valid genre.", 422)
    return tag


def _musicbrainz_problem(error: MusicBrainzError) -> HTTPException:
    status = 404 if error.code == "musicbrainz_not_found" else 503
    return fehler(error.code, "MusicBrainz could not answer.", status)


def _source_problem(error: ListenBrainzError | DeezerError) -> HTTPException:
    return fehler(error.code, "A data source could not answer.", 503)


@router.get("/api/search/artists", summary="Search artists in MusicBrainz")
async def search_artists(user: CurrentUser, db: DbSession, q: str = Query(max_length=200)) -> list[dict[str, Any]]:
    try:
        return await catalog.search_artists(db, load_settings(db), q)
    except MusicBrainzError as error:
        raise _musicbrainz_problem(error) from error


@router.get("/api/search/albums", summary="Search albums, EPs and singles in MusicBrainz")
async def search_albums(user: CurrentUser, db: DbSession, q: str = Query(max_length=200)) -> list[dict[str, Any]]:
    try:
        return await catalog.search_albums(db, load_settings(db), user, q)
    except MusicBrainzError as error:
        raise _musicbrainz_problem(error) from error


@router.get("/api/genres/artists", summary="Popular artists of a genre and related genres")
async def genre_artists(user: CurrentUser, db: DbSession, tag: str = Query(max_length=200)) -> dict[str, Any]:
    try:
        return await genres.genre_artists(db, load_settings(db), _genre(tag))
    except MusicBrainzError as error:
        raise _musicbrainz_problem(error) from error


@router.get("/api/genres/albums", summary="Popular albums of a genre")
async def genre_albums(user: CurrentUser, db: DbSession, tag: str = Query(max_length=200)) -> dict[str, Any]:
    try:
        return await genres.genre_albums(db, load_settings(db), user, _genre(tag))
    except MusicBrainzError as error:
        raise _musicbrainz_problem(error) from error
    except ListenBrainzError as error:
        raise _source_problem(error) from error


@router.get("/api/artists/{mbid}", summary="Artist page head: details, request state and quota")
async def artist_page(mbid: str, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    try:
        return await catalog.artist_page(db, load_settings(db), user, _mbid(mbid))
    except MusicBrainzError as error:
        raise _musicbrainz_problem(error) from error


@router.get("/api/artists/{mbid}/discography", summary="Every release of an artist from MusicBrainz")
async def artist_discography(mbid: str, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    try:
        return await catalog.artist_discography(db, load_settings(db), user, _mbid(mbid))
    except MusicBrainzError as error:
        raise _musicbrainz_problem(error) from error


@router.get("/api/artists/{mbid}/popular", summary="Most listened albums of an artist from ListenBrainz")
async def artist_popular(mbid: str, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    try:
        return await catalog.artist_popular(db, load_settings(db), user, _mbid(mbid))
    except ListenBrainzError as error:
        raise _source_problem(error) from error


@router.get("/api/artists/{mbid}/similar", summary="Similar artists from ListenBrainz")
async def artist_similar(mbid: str, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    try:
        return await catalog.artist_similar(db, load_settings(db), _mbid(mbid))
    except ListenBrainzError as error:
        raise _source_problem(error) from error


@router.get("/api/artists/{mbid}/top-tracks", summary="Popular tracks with previews from Deezer")
async def artist_top_tracks(
    mbid: str, user: CurrentUser, db: DbSession, name: str = Query(default="", max_length=200)
) -> dict[str, Any]:
    try:
        return await catalog.artist_top_tracks(db, load_settings(db), _mbid(mbid), name)
    except DeezerError as error:
        raise _source_problem(error) from error


@router.get("/api/albums/{mbid}", summary="Album page: tracks, previews, library and request state")
async def album_page(mbid: str, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    try:
        return await catalog.album_page(db, load_settings(db), user, _mbid(mbid))
    except MusicBrainzError as error:
        raise _musicbrainz_problem(error) from error


@router.get("/api/images/artist/{mbid}", include_in_schema=False)
async def artist_image(mbid: str, db: DbSession, name: str = Query(default="", max_length=200)) -> Response:
    """Leitet auf das Kuenstlerbild weiter.

    ⚠️ Ohne Anmeldung erreichbar, weil ``<img>`` keinen Authorization-Kopf
    mitschickt. Preisgegeben wird nur ein oeffentliches Bild zu einer
    oeffentlichen Kennung. Jede sichere Antwort, auch "kein Bild", liegt im
    Zwischenspeicher, damit sich die Adresse nicht zum Anstossen von Suchen
    missbrauchen laesst. Nur eine Ablehnung durch die Quelle nicht: Das Bild
    fehlte sonst noch lange, nachdem die Quelle wieder antwortet.
    """
    if not catalog.valid_mbid(mbid):
        return Response(status_code=404)
    url = await catalog.resolve_artist_image(db, load_settings(db), mbid, name)
    if url is None:
        return Response(status_code=404, headers={"Cache-Control": "no-store"})
    if not url:
        return Response(status_code=404, headers={"Cache-Control": "public, max-age=3600"})
    return RedirectResponse(url, status_code=302, headers={"Cache-Control": "public, max-age=86400"})
