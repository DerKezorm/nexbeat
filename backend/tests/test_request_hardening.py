"""Anfragen unter Last und nach Stoerungen.

Befunde aus der Pruefung vom 12.09.2026: Gleichzeitige Anfragen umgingen Kontingent und
Doppelpruefung, eine unterbrochene Uebergabe blieb fuer immer haengen, und nach einer
Zeitueberschreitung galt eine Anfrage als erledigt, obwohl Lidarr nie alles bekommen hatte.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import MusicRequest, RequestStatus, User, utcnow
from app.services import catalog, library, requests_service
from app.services.lidarr import LidarrError
from app.services.requests_service import RequestProblem
from app.services.settings_service import load_settings
from tests.conftest import ARTIST, OTHER_RELEASE_GROUP, RELEASE_GROUP, auth_headers, create_user
from tests.fakes import FakeLidarr

STUDIO_ONE = "44444444-4444-4444-8444-444444444444"
STUDIO_TWO = "55555555-5555-4555-8555-555555555555"
OTHER_ARTIST = "99999999-9999-4999-8999-999999999999"


def _refresh() -> int:
    with SessionLocal() as db:
        return asyncio.run(requests_service.refresh_open(db, load_settings(db)))


def _row(request_id: int) -> MusicRequest:
    with SessionLocal() as db:
        return db.get(MusicRequest, request_id)


def _age(request_id: int, minutes: int) -> None:
    with SessionLocal() as db:
        db.get(MusicRequest, request_id).submitted_at = utcnow() - timedelta(minutes=minutes)
        db.commit()


def _calls(fake: FakeLidarr, name: str) -> list[Any]:
    return [call[1] for call in fake.calls if call[0] == name]


def _request(client: TestClient, headers: dict[str, str], mbid: str = RELEASE_GROUP) -> Any:
    return client.post("/api/requests", json={"release_group_mbid": mbid}, headers=headers)


async def _together(*jobs: Any) -> list[Any]:
    return await asyncio.gather(*jobs, return_exceptions=True)


def test_safety_net_stays_quiet_in_dry_run(admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups) -> None:
    create_user("lena")
    request_id = _request(admin_client, auth_headers(admin_client, "lena")).json()["request"]["id"]
    fake_lidarr.album_rows.append({"id": 80, "artistId": 501, "foreignAlbumId": RELEASE_GROUP, "monitored": True, "statistics": {}})
    admin_client.put("/api/settings", json={"lidarr_dry_run": True})

    _age(request_id, 11)
    _refresh()
    assert _calls(fake_lidarr, "search_albums") == []


def test_dry_run_leaves_an_open_hand_over_alone(admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups) -> None:
    fake_lidarr.fail_with["add_artist"] = LidarrError("lidarr_timeout", uncertain=True)
    create_user("lena")
    request_id = _request(admin_client, auth_headers(admin_client, "lena")).json()["request"]["id"]
    del fake_lidarr.fail_with["add_artist"]
    admin_client.put("/api/settings", json={"lidarr_dry_run": True})

    _age(request_id, 11)
    _refresh()
    request = _row(request_id)
    assert (request.status, request.error_code) == (RequestStatus.approved, "lidarr_timeout")
    assert len(_calls(fake_lidarr, "add_artist")) == 1


def test_two_users_asking_for_the_same_album_at_once_make_one_request(
    admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = library.album_states

    async def slow(*args: Any, **kwargs: Any) -> dict[str, Any]:
        await asyncio.sleep(0.05)
        return await original(*args, **kwargs)

    monkeypatch.setattr(library, "album_states", slow)
    lena, tom = create_user("lena"), create_user("tom")

    async def ask(user_id: int) -> Any:
        with SessionLocal() as db:
            return await requests_service.create(db, load_settings(db), db.get(User, user_id), RELEASE_GROUP)

    results = asyncio.run(_together(ask(lena), ask(tom)))
    assert sorted(type(result).__name__ for result in results) == ["MusicRequest", "RequestProblem"]
    with SessionLocal() as db:
        assert db.query(MusicRequest).count() == 1


def test_whole_artist_requests_at_once_stay_within_the_quota(
    admin_client: TestClient, fake_lidarr: FakeLidarr, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def artist_info(_db: Any, mbid: str) -> dict[str, Any]:
        await asyncio.sleep(0.05)
        return {"mbid": mbid, "name": f"Artist {mbid[:4]}"}

    async def studio_albums(_db: Any, mbid: str) -> list[dict[str, Any]]:
        await asyncio.sleep(0.05)
        return [{"mbid": STUDIO_ONE if mbid == ARTIST else STUDIO_TWO}]

    monkeypatch.setattr(catalog, "artist_info", artist_info)
    monkeypatch.setattr(catalog, "studio_albums", studio_albums)
    lena = create_user("lena", quota_limit=1)

    async def ask(mbid: str) -> Any:
        with SessionLocal() as db:
            return await requests_service.create_artist(db, load_settings(db), db.get(User, lena), mbid)

    results = asyncio.run(_together(ask(ARTIST), ask(OTHER_ARTIST)))
    assert [result.code for result in results if isinstance(result, RequestProblem)] == ["quota_exhausted"]


def test_interrupted_hand_over_is_picked_up_by_the_background_check(
    admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups
) -> None:
    create_user("lena")
    fake_lidarr.fail_with["add_artist"] = RuntimeError("process stopped")
    with pytest.raises(RuntimeError):
        _request(admin_client, auth_headers(admin_client, "lena"))
    with SessionLocal() as db:
        request = db.query(MusicRequest).one()
        assert (request.status, request.error_code) == (RequestStatus.approved, "lidarr_pending")
        request_id = request.id

    # Lidarr hatte den Kuenstler doch angelegt: Der Abgleich bringt die Uebergabe zu Ende.
    del fake_lidarr.fail_with["add_artist"]
    fake_lidarr.artist_rows.append({"id": 501, "foreignArtistId": ARTIST})
    fake_lidarr.album_rows.append({"id": 80, "artistId": 501, "foreignAlbumId": RELEASE_GROUP, "monitored": False, "statistics": {}})
    _refresh()
    request = _row(request_id)
    assert (request.status, request.error_code) == (RequestStatus.searching, "")
    assert [80] in _calls(fake_lidarr, "monitor_albums")


def test_hand_over_that_never_reached_lidarr_is_sent_again(
    admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups
) -> None:
    create_user("lena")
    fake_lidarr.fail_with["add_artist"] = RuntimeError("process stopped")
    with pytest.raises(RuntimeError):
        _request(admin_client, auth_headers(admin_client, "lena"))
    del fake_lidarr.fail_with["add_artist"]
    with SessionLocal() as db:
        request_id = db.query(MusicRequest).one().id

    # Kurz danach kann die Uebergabe noch unterwegs sein. Ein zweites Anlegen scheiterte in Lidarr.
    _refresh()
    assert len(_calls(fake_lidarr, "add_artist")) == 1

    _age(request_id, 11)
    _refresh()
    assert len(_calls(fake_lidarr, "add_artist")) == 2
    assert _row(request_id).status == RequestStatus.searching


def test_timeout_waits_while_lidarr_still_reads_the_new_artist(
    admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups
) -> None:
    fake_lidarr.fail_with["add_artist"] = LidarrError("lidarr_timeout", uncertain=True)
    create_user("lena")
    request_id = _request(admin_client, auth_headers(admin_client, "lena")).json()["request"]["id"]
    del fake_lidarr.fail_with["add_artist"]

    # Lidarr hat den Kuenstler angelegt, seine Alben aber noch nicht eingelesen.
    fake_lidarr.artist_rows.append({"id": 501, "foreignArtistId": ARTIST})
    _age(request_id, 11)
    _refresh()
    request = _row(request_id)
    assert (request.status, request.error_code) == (RequestStatus.approved, "lidarr_timeout")
    assert len(_calls(fake_lidarr, "add_artist")) == 1

    _age(request_id, 31)
    _refresh()
    request = _row(request_id)
    assert (request.status, request.error_code) == (RequestStatus.failed, "lidarr_timeout")


def test_timeout_while_monitoring_is_finished_by_the_background_check(
    admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups
) -> None:
    fake_lidarr.artist_rows.append({"id": 7, "foreignArtistId": ARTIST})
    fake_lidarr.album_rows.append({"id": 70, "artistId": 7, "foreignAlbumId": RELEASE_GROUP, "monitored": False, "statistics": {}})
    fake_lidarr.fail_with["monitor_albums"] = LidarrError("lidarr_timeout", uncertain=True)
    create_user("lena")
    body = _request(admin_client, auth_headers(admin_client, "lena")).json()["request"]
    assert (body["status"], body["error_code"]) == ("approved", "lidarr_timeout")

    del fake_lidarr.fail_with["monitor_albums"]
    _refresh()
    assert _calls(fake_lidarr, "monitor_albums") == [[70], [70]]
    assert _calls(fake_lidarr, "search_albums") == [[70]]
    assert _row(body["id"]).status == RequestStatus.searching


def test_timeout_while_updating_an_artist_is_finished_by_the_background_check(
    admin_client: TestClient, fake_lidarr: FakeLidarr, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def artist_info(_db: Any, mbid: str) -> dict[str, Any]:
        return {"mbid": mbid, "name": "Test Artist"}

    async def studio_albums(_db: Any, _mbid: str) -> list[dict[str, Any]]:
        return [{"mbid": STUDIO_ONE}, {"mbid": STUDIO_TWO}]

    monkeypatch.setattr(catalog, "artist_info", artist_info)
    monkeypatch.setattr(catalog, "studio_albums", studio_albums)
    fake_lidarr.artist_rows.append({"id": 7, "foreignArtistId": ARTIST, "monitored": False, "monitorNewItems": "none"})
    complete = {"trackFileCount": 10, "totalTrackCount": 10, "percentOfTracks": 100.0}
    fake_lidarr.album_rows.extend(
        [
            {"id": 71, "artistId": 7, "foreignAlbumId": STUDIO_ONE, "albumType": "Album", "secondaryTypes": [], "monitored": True, "statistics": complete},
            {"id": 72, "artistId": 7, "foreignAlbumId": STUDIO_TWO, "albumType": "Album", "secondaryTypes": [], "monitored": False, "statistics": {}},
        ]
    )
    fake_lidarr.fail_with["update_artist"] = LidarrError("lidarr_timeout", uncertain=True)
    create_user("lena")
    body = admin_client.post("/api/requests/artist", json={"artist_mbid": ARTIST}, headers=auth_headers(admin_client, "lena")).json()["request"]
    assert (body["status"], body["error_code"]) == ("approved", "lidarr_timeout")

    del fake_lidarr.fail_with["update_artist"]
    _refresh()
    # Vorher galt die Anfrage hier als geladen: Das eine ueberwachte Album war ja komplett.
    assert [72] in _calls(fake_lidarr, "monitor_albums")
    assert [72] in _calls(fake_lidarr, "search_albums")
    assert _row(body["id"]).status == RequestStatus.searching


def test_retry_waits_while_the_background_check_follows_a_timeout(
    admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups
) -> None:
    fake_lidarr.fail_with["add_artist"] = LidarrError("lidarr_timeout", uncertain=True)
    create_user("lena")
    request_id = _request(admin_client, auth_headers(admin_client, "lena")).json()["request"]["id"]

    retried = admin_client.post(f"/api/admin/requests/{request_id}/retry")
    assert retried.status_code == 409
    assert retried.json()["detail"]["code"] == "request_still_checking"


def test_retry_respects_the_quota(admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups) -> None:
    create_user("lena", quota_limit=1)
    headers = auth_headers(admin_client, "lena")
    fake_lidarr.fail_with["add_artist"] = LidarrError("lidarr_http_error", "broken")
    failed = _request(admin_client, headers).json()["request"]
    assert failed["status"] == "failed"
    del fake_lidarr.fail_with["add_artist"]

    assert _request(admin_client, headers, OTHER_RELEASE_GROUP).status_code == 201
    over_quota = admin_client.post(f"/api/admin/requests/{failed['id']}/retry")
    assert over_quota.status_code == 429
    assert over_quota.json()["detail"]["code"] == "quota_exhausted"


def test_retry_does_not_double_an_open_request(admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups) -> None:
    create_user("lena")
    create_user("tom")
    fake_lidarr.fail_with["add_artist"] = LidarrError("lidarr_http_error", "broken")
    failed = _request(admin_client, auth_headers(admin_client, "lena")).json()["request"]
    del fake_lidarr.fail_with["add_artist"]

    assert _request(admin_client, auth_headers(admin_client, "tom")).status_code == 201
    doubled = admin_client.post(f"/api/admin/requests/{failed['id']}/retry")
    assert doubled.status_code == 409
    assert doubled.json()["detail"]["code"] == "already_requested"


def test_retry_gives_the_safety_net_another_chance(admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups) -> None:
    create_user("lena")
    fake_lidarr.fail_with["add_artist"] = LidarrError("lidarr_http_error", "broken")
    failed = _request(admin_client, auth_headers(admin_client, "lena")).json()["request"]
    with SessionLocal() as db:
        db.get(MusicRequest, failed["id"]).search_retried_at = utcnow()
        db.commit()
    del fake_lidarr.fail_with["add_artist"]

    assert admin_client.post(f"/api/admin/requests/{failed['id']}/retry").status_code == 200
    assert _row(failed["id"]).search_retried_at is None
