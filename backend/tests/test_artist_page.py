"""Die Kuenstlerseite in Teilen: Kopf, Diskografie, Beliebt, Aehnliche, Top-Titel.

12.09.2026: Die Seite wartete auf alle Quellen zugleich. Scheiterte MusicBrainz bei
der Diskografie, stand dort "keine Veroeffentlichungen". Jetzt hat jeder Teil einen
eigenen Aufruf, und ein Ausfall kommt als Fehler an, nie als leere Liste.
"""

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import LibraryArtist
from app.services import http
from tests.conftest import ARTIST
from tests.fakes import FakeLidarr

ALBUM = "88888888-8888-4888-8888-888888888888"
SIMILAR = "99999999-9999-4999-8999-999999999999"
GUEST_ALBUM = "abababab-abab-4bab-8bab-abababababab"
OTHER_ARTIST = "cdcdcdcd-cdcd-4dcd-8dcd-cdcdcdcdcdcd"


def _sources(*, browse_status: int = 200, popularity_status: int = 200) -> tuple[httpx.MockTransport, list[str]]:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        official = request.url.params.get("release-group-status") == "website-default"
        seen.append(host + path + ("?official" if official else ""))
        if host == "musicbrainz.org" and path.endswith(f"/artist/{ARTIST}"):
            return httpx.Response(200, json={"id": ARTIST, "name": "Test Artist", "type": "Group"})
        if host == "musicbrainz.org" and path.endswith("/release-group"):
            if browse_status != 200:
                return httpx.Response(browse_status)
            group = {"id": ALBUM, "title": "Record", "primary-type": "Album", "secondary-types": [], "first-release-date": "2001-02-03"}
            return httpx.Response(200, json={"release-groups": [group]})
        if host == "api.listenbrainz.org" and "top-release-groups-for-artist" in path:
            if popularity_status != 200:
                return httpx.Response(popularity_status, json={"code": popularity_status, "error": "you need to provide an Auth token"})
            own = {
                "release_group_mbid": ALBUM,
                "release_group": {"name": "Record", "type": "Album", "date": "2001"},
                "total_listen_count": 50,
                "artist": {"artists": [{"artist_mbid": ARTIST, "name": "Test Artist"}]},
            }
            # Ein fremdes Album, auf dem der Kuenstler nur mitsingt. ListenBrainz zaehlt es mit.
            guest = {
                "release_group_mbid": GUEST_ALBUM,
                "release_group": {"name": "Someone Else's Record", "type": "Album", "date": "2020"},
                "total_listen_count": 80,
                "artist": {"artists": [{"artist_mbid": OTHER_ARTIST, "name": "Other Singer"}]},
            }
            return httpx.Response(200, json=[guest, own])
        if host == "labs.api.listenbrainz.org":
            return httpx.Response(200, json=[{"artist_mbid": SIMILAR, "name": "Similar Band", "score": 10, "reference_mbid": ARTIST}])
        if host == "api.deezer.com" and path == "/search/artist":
            return httpx.Response(200, json={"data": [{"id": 5, "name": "Test Artist", "nb_fan": 1, "picture_xl": "https://img.example.com/a.jpg"}]})
        if host == "api.deezer.com" and path == "/artist/5/top":
            track = {"title": "Hit", "preview": "https://cdn.example.com/hit.mp3", "duration": 200, "album": {"title": "Record"}}
            return httpx.Response(200, json={"data": [track]})
        raise AssertionError(f"Unexpected request: {request.url}")

    return httpx.MockTransport(handler), seen


def test_artist_head_does_not_wait_for_the_discography(admin_client: TestClient) -> None:
    transport, seen = _sources(browse_status=503)
    http.use_transport(transport)

    response = admin_client.get(f"/api/artists/{ARTIST}")
    assert response.status_code == 200, response.text
    assert response.json()["artist"]["name"] == "Test Artist"
    assert seen == [f"musicbrainz.org/ws/2/artist/{ARTIST}"]


def test_busy_musicbrainz_is_reported_not_shown_as_no_releases(admin_client: TestClient) -> None:
    transport, _seen = _sources(browse_status=503)
    http.use_transport(transport)
    busy = admin_client.get(f"/api/artists/{ARTIST}/discography")
    assert busy.status_code == 503
    assert busy.json()["detail"]["code"] == "musicbrainz_busy"

    # Nichts Leeres im Zwischenspeicher: Beim naechsten Versuch kommt die Diskografie.
    transport, seen = _sources()
    http.use_transport(transport)
    albums = admin_client.get(f"/api/artists/{ARTIST}/discography").json()["albums"]
    assert [(album["mbid"], album["listen_count"]) for album in albums] == [(ALBUM, 50)]
    # 12.09.2026 gemessen: Ohne diesen Filter kamen bei einem Duo 48 statt 23 Alben,
    # darunter inoffizielle wie eine "Beta Version".
    assert "musicbrainz.org/ws/2/release-group?official" in seen


def test_discography_reads_every_page(admin_client: TestClient) -> None:
    # 12.09.2026 gemessen: Eine Saengerin hatte 101 offizielle Veroeffentlichungen, nexbeat
    # las nur die ersten 100. MusicBrainz liefert hoechstens 100 je Aufruf.
    offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/release-group"):
            offset = int(request.url.params.get("offset", "0"))
            offsets.append(offset)
            total = 101
            groups = [
                {
                    "id": f"{index:08d}-0000-4000-8000-000000000000",
                    "title": f"Release {index}",
                    "primary-type": "Single",
                    "secondary-types": [],
                    "first-release-date": "2020-01-01",
                }
                for index in range(offset, min(total, offset + 100))
            ]
            return httpx.Response(200, json={"release-group-count": total, "release-group-offset": offset, "release-groups": groups})
        if "top-release-groups-for-artist" in request.url.path:
            return httpx.Response(200, json=[])
        raise AssertionError(f"Unexpected request: {request.url}")

    http.use_transport(httpx.MockTransport(handler))
    albums = admin_client.get(f"/api/artists/{ARTIST}/discography").json()["albums"]
    assert len(albums) == 101
    assert offsets == [0, 100]


def test_popularity_without_token_is_named(admin_client: TestClient) -> None:
    # 12.09.2026 gemessen: ListenBrainz verlangt fuer die Beliebtheit je nach Kuenstler einen Schluessel.
    transport, _seen = _sources(popularity_status=401)
    http.use_transport(transport)

    response = admin_client.get(f"/api/artists/{ARTIST}/popular")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "listenbrainz_token_required"


def test_popular_similar_and_top_tracks_come_on_their_own(admin_client: TestClient) -> None:
    transport, _seen = _sources()
    http.use_transport(transport)

    # 12.09.2026: Bei einer Saengerin stand ein Album von jemand anderem unter "Am meisten
    # gehoert", weil sie dort mitsingt. Es zaehlen nur Alben, die ihr gehoeren.
    popular = admin_client.get(f"/api/artists/{ARTIST}/popular").json()["albums"]
    assert [(album["mbid"], album["title"], album["primary_type"]) for album in popular] == [(ALBUM, "Record", "Album")]
    similar = admin_client.get(f"/api/artists/{ARTIST}/similar").json()["artists"]
    assert [item["mbid"] for item in similar] == [SIMILAR]
    tracks = admin_client.get(f"/api/artists/{ARTIST}/top-tracks", params={"name": "Test Artist"}).json()["tracks"]
    assert [track["title"] for track in tracks] == ["Hit"]


def test_artist_head_says_when_a_whole_artist_would_bring_more_than_studio_albums(
    admin_client: TestClient, fake_lidarr: FakeLidarr
) -> None:
    # 12.09.2026: Mit einem weiten Metadatenprofil brachte "Ganzer Kuenstler" weit ueber tausend Alben nach Lidarr.
    transport, _seen = _sources()
    http.use_transport(transport)
    fake_lidarr.profile = {
        "primaryAlbumTypes": [{"albumType": {"name": "Album"}, "allowed": True}],
        "secondaryAlbumTypes": [
            {"albumType": {"name": "Studio"}, "allowed": True},
            {"albumType": {"name": "Live"}, "allowed": True},
        ],
    }
    assert admin_client.get(f"/api/artists/{ARTIST}").json()["blocked"] == "profile_not_studio_only"

    # Steht der Kuenstler schon in Lidarr, zaehlt sein eigenes Profil.
    fake_lidarr.profiles[2] = {
        "primaryAlbumTypes": [{"albumType": {"name": "Album"}, "allowed": True}],
        "secondaryAlbumTypes": [{"albumType": {"name": "Studio"}, "allowed": True}],
    }
    with SessionLocal() as db:
        db.add(LibraryArtist(mbid=ARTIST, lidarr_id=7, name="Test Artist", metadata_profile_id=2))
        db.commit()
    assert admin_client.get(f"/api/artists/{ARTIST}").json()["blocked"] is None
