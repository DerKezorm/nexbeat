"""Ganzer Kuenstler: alle Studioalben und die kuenftigen, als eine Anfrage.

Entschieden am 12.09.2026: Zaehlt als eine Anfrage, Freigabe wie bei Alben.
Nur Alben ohne Zusatztyp, also keine EPs, Singles, Live-Mitschnitte oder
Sammlungen.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any

import httpx
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import LibraryArtist, MusicRequest, utcnow
from app.services import http, requests_service
from app.services.lidarr import LidarrClient, is_studio_album
from app.services.settings_service import load_settings
from tests.conftest import ARTIST, auth_headers, create_user
from tests.fakes import FakeLidarr

STUDIO_ONE = "44444444-4444-4444-8444-444444444444"
STUDIO_TWO = "55555555-5555-4555-8555-555555555555"
LIVE_ALBUM = "66666666-6666-4666-8666-666666666666"
AN_EP = "77777777-7777-4777-8777-777777777777"

#: Laesst neben Studioalben auch Live-Alben zu. Damit braechte "alle kuenftigen" auch die mit.
WIDE_PROFILE = {
    "primaryAlbumTypes": [{"albumType": {"name": "Album"}, "allowed": True}],
    "secondaryAlbumTypes": [
        {"albumType": {"name": "Studio"}, "allowed": True},
        {"albumType": {"name": "Live"}, "allowed": True},
    ],
}


def _musicbrainz(groups: list[dict[str, Any]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(f"/artist/{ARTIST}"):
            return httpx.Response(200, json={"id": ARTIST, "name": "Test Artist", "type": "Group"})
        if request.url.path.endswith("/release-group"):
            assert request.url.params["type"] == "album"
            # Nur offizielle: Sonst bekaeme Lidarr auch Bootlegs auf die Liste.
            assert request.url.params.get("release-group-status") == "website-default"
            body = {"release-group-count": len(groups), "release-group-offset": 0, "release-groups": groups}
            return httpx.Response(200, json=body)
        raise AssertionError(f"Unexpected request: {request.url}")

    return httpx.MockTransport(handler)


GROUPS = [
    {"id": STUDIO_ONE, "title": "First", "primary-type": "Album", "secondary-types": []},
    {"id": LIVE_ALBUM, "title": "Live at Home", "primary-type": "Album", "secondary-types": ["Live"]},
    {"id": STUDIO_TWO, "title": "Second", "primary-type": "Album", "secondary-types": []},
]


def _request_artist(client: TestClient, headers: dict[str, str]) -> Any:
    return client.post("/api/requests/artist", json={"artist_mbid": ARTIST}, headers=headers)


def _refresh() -> int:
    with SessionLocal() as db:
        return asyncio.run(requests_service.refresh_open(db, load_settings(db)))


def _album(album_id: int, mbid: str, *, kind: str = "Album", secondary: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "id": album_id,
        "artistId": extra.pop("artist_id", 7),
        "foreignAlbumId": mbid,
        "albumType": kind,
        "secondaryTypes": secondary or [],
        "monitored": extra.pop("monitored", False),
        "statistics": extra.pop("statistics", {}),
    }


def test_new_artist_gets_all_studio_albums_and_future_ones(admin_client: TestClient, fake_lidarr: FakeLidarr) -> None:
    http.use_transport(_musicbrainz(GROUPS))
    create_user("lena")

    response = _request_artist(admin_client, auth_headers(admin_client, "lena"))
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["request"]["kind"], body["request"]["status"], body["request"]["title"]) == ("artist", "searching", "Test Artist")
    assert body["quota"]["used"] == 1

    added = next(call[1] for call in fake_lidarr.calls if call[0] == "add_artist")
    assert (added["monitored"], added["monitorNewItems"]) == (True, "all")
    assert added["addOptions"] == {
        "monitor": "unknown",
        "albumsToMonitor": [STUDIO_ONE, STUDIO_TWO],
        "monitored": True,
        "searchForMissingAlbums": True,
    }
    assert fake_lidarr.artist_rows[-1]["monitored"] is True


def test_artist_in_lidarr_is_monitored_and_missing_studio_albums_are_searched(
    admin_client: TestClient, fake_lidarr: FakeLidarr
) -> None:
    http.use_transport(_musicbrainz(GROUPS))
    fake_lidarr.artist_rows.append(
        {"id": 7, "foreignArtistId": ARTIST, "artistName": "Test Artist", "monitored": False, "monitorNewItems": "none"}
    )
    fake_lidarr.album_rows.extend(
        [
            _album(71, STUDIO_ONE, statistics={"trackFileCount": 0, "percentOfTracks": 0}),
            _album(72, STUDIO_TWO, monitored=True, statistics={"trackFileCount": 9, "percentOfTracks": 100.0}),
            _album(73, LIVE_ALBUM, secondary=["Live"]),
            _album(74, AN_EP, kind="EP"),
        ]
    )
    create_user("lena")

    body = _request_artist(admin_client, auth_headers(admin_client, "lena")).json()
    assert body["request"]["status"] == "searching", body

    updated = next(call[1] for call in fake_lidarr.calls if call[0] == "update_artist")
    assert (updated["id"], updated["monitored"], updated["monitorNewItems"]) == (7, True, "all")
    # Nur das fehlende Studioalbum: Das vorhandene ist schon ueberwacht und komplett,
    # Live-Album und EP bleiben aussen vor.
    assert ("monitor_albums", [71]) in fake_lidarr.calls
    assert ("search_albums", [71]) in fake_lidarr.calls
    assert "add_artist" not in fake_lidarr.writes()


def test_whole_artist_counts_once_and_cannot_be_doubled(admin_client: TestClient, fake_lidarr: FakeLidarr) -> None:
    http.use_transport(_musicbrainz(GROUPS))
    create_user("lena", quota_limit=2)
    headers = auth_headers(admin_client, "lena")

    assert _request_artist(admin_client, headers).status_code == 201
    again = _request_artist(admin_client, headers)
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "already_requested"
    assert admin_client.get("/api/auth/me", headers=headers).json()["quota"]["used"] == 1


def test_artist_without_studio_albums_is_refused(admin_client: TestClient, fake_lidarr: FakeLidarr) -> None:
    http.use_transport(_musicbrainz([GROUPS[1]]))
    create_user("lena")

    response = _request_artist(admin_client, auth_headers(admin_client, "lena"))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "artist_without_albums"
    assert fake_lidarr.writes() == []


def test_whole_artist_in_dry_run_sends_nothing(admin_client: TestClient, fake_lidarr: FakeLidarr) -> None:
    http.use_transport(_musicbrainz(GROUPS))
    admin_client.put("/api/settings", json={"lidarr_dry_run": True})
    create_user("lena")

    body = _request_artist(admin_client, auth_headers(admin_client, "lena")).json()
    assert (body["request"]["status"], body["request"]["error_code"]) == ("approved", "dry_run")
    assert fake_lidarr.writes() == []


def test_background_check_follows_every_monitored_album(admin_client: TestClient, fake_lidarr: FakeLidarr) -> None:
    http.use_transport(_musicbrainz(GROUPS))
    create_user("lena")
    headers = auth_headers(admin_client, "lena")
    assert _request_artist(admin_client, headers).json()["request"]["status"] == "searching"

    complete = {"trackFileCount": 10, "totalTrackCount": 10, "percentOfTracks": 100.0}
    fake_lidarr.album_rows.extend(
        [
            _album(81, STUDIO_ONE, artist_id=501, monitored=True, statistics=complete),
            _album(82, STUDIO_TWO, artist_id=501, monitored=True, statistics={"trackFileCount": 0, "percentOfTracks": 0}),
            _album(83, LIVE_ALBUM, artist_id=501, secondary=["Live"]),
        ]
    )
    _refresh()
    mine = admin_client.get("/api/requests/mine", headers=headers).json()[0]
    assert (mine["status"], mine["progress"]) == ("searching", 50)

    fake_lidarr.album_rows[1]["statistics"] = complete
    assert _refresh() == 1
    mine = admin_client.get("/api/requests/mine", headers=headers).json()[0]
    assert (mine["status"], mine["progress"]) == ("downloaded", 100)


def test_whole_artist_is_searched_again_once_when_nothing_happened(admin_client: TestClient, fake_lidarr: FakeLidarr) -> None:
    # 12.09.2026: Lidarrs Suche nach dem Anlegen fiel mit "database is locked" aus und wurde
    # nie wiederholt. Gesucht wird dann einmal nach den ueberwachten Studioalben.
    http.use_transport(_musicbrainz(GROUPS))
    create_user("lena")
    request_id = _request_artist(admin_client, auth_headers(admin_client, "lena")).json()["request"]["id"]
    fake_lidarr.album_rows.extend(
        [
            _album(81, STUDIO_ONE, artist_id=501, monitored=True),
            _album(82, STUDIO_TWO, artist_id=501, monitored=True),
            _album(83, LIVE_ALBUM, artist_id=501, secondary=["Live"]),
        ]
    )
    with SessionLocal() as db:
        db.get(MusicRequest, request_id).submitted_at = utcnow() - timedelta(minutes=11)
        db.commit()

    _refresh()
    _refresh()
    assert [call[1] for call in fake_lidarr.calls if call[0] == "search_albums"] == [[81, 82]]


def test_whole_artist_needs_a_profile_with_studio_albums_only(admin_client: TestClient, fake_lidarr: FakeLidarr) -> None:
    # 12.09.2026: Mit einem Profil, das auch Live, Sammlungen und Bootlegs zuliess, legte
    # "Ganzer Kuenstler" eine Band mit weit ueber tausend Alben an, bis zum Ende des Abgleichs alle ueberwacht.
    http.use_transport(_musicbrainz(GROUPS))
    fake_lidarr.profile = WIDE_PROFILE
    create_user("lena")
    headers = auth_headers(admin_client, "lena")

    refused = _request_artist(admin_client, headers)
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "profile_not_studio_only"
    assert admin_client.get("/api/requests/mine", headers=headers).json() == []
    assert fake_lidarr.writes() == []


def test_whole_artist_checks_the_profile_the_artist_has_in_lidarr(admin_client: TestClient, fake_lidarr: FakeLidarr) -> None:
    http.use_transport(_musicbrainz(GROUPS))
    fake_lidarr.profiles[2] = WIDE_PROFILE
    with SessionLocal() as db:
        db.add(LibraryArtist(mbid=ARTIST, lidarr_id=7, name="Test Artist", metadata_profile_id=2))
        db.commit()
    create_user("lena")

    refused = _request_artist(admin_client, auth_headers(admin_client, "lena"))
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "artist_profile_not_studio_only"
    assert fake_lidarr.writes() == []


def test_whole_artist_hand_over_reads_the_profile_fresh(admin_client: TestClient, fake_lidarr: FakeLidarr) -> None:
    # Bis zur Freigabe kann der Kuenstler in Lidarr ein weiteres Profil bekommen haben.
    http.use_transport(_musicbrainz(GROUPS))
    create_user("lena", requires_approval=True)
    waiting = _request_artist(admin_client, auth_headers(admin_client, "lena")).json()["request"]
    assert waiting["status"] == "pending_approval"

    fake_lidarr.profiles[2] = WIDE_PROFILE
    fake_lidarr.artist_rows.append({"id": 7, "foreignArtistId": ARTIST, "metadataProfileId": 2, "monitored": False})
    approved = admin_client.post(f"/api/admin/requests/{waiting['id']}/approve").json()
    assert (approved["status"], approved["error_code"]) == ("failed", "artist_profile_not_studio_only")
    assert fake_lidarr.writes() == []


def test_studio_album_means_album_without_secondary_types() -> None:
    # 12.09.2026 gemessen: Lidarr liefert secondaryTypes als Liste von Namen, bei Studioalben leer.
    assert is_studio_album({"albumType": "Album", "secondaryTypes": []})
    assert is_studio_album({"albumType": "Album", "secondaryTypes": ["Studio"]})
    assert not is_studio_album({"albumType": "Album", "secondaryTypes": ["Live"]})
    assert not is_studio_album({"albumType": "Album", "secondaryTypes": [{"name": "Compilation"}]})
    assert not is_studio_album({"albumType": "EP", "secondaryTypes": []})


def test_lidarr_update_artist_sends_the_whole_artist_back() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(method=request.method, path=request.url.path, body=json.loads(request.content))
        return httpx.Response(202, json=seen["body"])

    http.use_transport(httpx.MockTransport(handler))
    artist = {"id": 7, "artistName": "Band", "monitored": True, "monitorNewItems": "all", "path": "/music/Band"}
    asyncio.run(LidarrClient("http://lidarr.test", "key").update_artist(artist))
    assert (seen["method"], seen["path"]) == ("PUT", "/api/v1/artist/7")
    assert seen["body"] == artist
