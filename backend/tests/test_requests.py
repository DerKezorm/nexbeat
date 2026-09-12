from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import LibraryArtist, MusicRequest, utcnow
from app.services import requests_service
from app.services.lidarr import LidarrError
from app.services.settings_service import load_settings
from tests.conftest import ARTIST, OTHER_RELEASE_GROUP, RELEASE_GROUP, auth_headers, create_user
from tests.fakes import FakeLidarr


def _request(client: TestClient, headers: dict[str, str], mbid: str = RELEASE_GROUP) -> Any:
    return client.post("/api/requests", json={"release_group_mbid": mbid}, headers=headers)


def _refresh() -> int:
    with SessionLocal() as db:
        return asyncio.run(requests_service.refresh_open(db, load_settings(db)))


def test_new_artist_is_added_with_only_this_album(admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups) -> None:
    create_user("lena")
    response = _request(admin_client, auth_headers(admin_client, "lena"))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["request"]["status"] == "searching"
    assert body["quota"]["used"] == 1

    added = next(call[1] for call in fake_lidarr.calls if call[0] == "add_artist")
    assert added["foreignArtistId"] == ARTIST
    # 12.09.2026: Mit monitor "none" legte Lidarr den Kuenstler unueberwacht an. Die
    # Suche nach dem Anlegen nimmt nur Alben ueberwachter Kuenstler, geladen wurde
    # nichts. "unknown" laesst ihn ueberwacht, und die Liste bestimmt das Album.
    # "all" ginge auch, wuerde bei leerer Liste aber alles ueberwachen.
    assert added["addOptions"] == {
        "monitor": "unknown",
        "albumsToMonitor": [RELEASE_GROUP],
        "monitored": True,
        "searchForMissingAlbums": True,
    }
    assert fake_lidarr.artist_rows[-1]["monitored"] is True
    assert added["monitorNewItems"] == "none"
    assert (added["rootFolderPath"], added["qualityProfileId"], added["metadataProfileId"]) == ("/music", 1, 1)


def test_existing_artist_only_gets_the_album_monitored(admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups) -> None:
    fake_lidarr.artist_rows.append({"id": 7, "foreignArtistId": ARTIST})
    fake_lidarr.album_rows.append({"id": 70, "artistId": 7, "foreignAlbumId": RELEASE_GROUP, "monitored": False, "statistics": {}})
    create_user("lena")

    assert _request(admin_client, auth_headers(admin_client, "lena")).json()["request"]["status"] == "searching"
    assert ("monitor_albums", [70]) in fake_lidarr.calls
    assert ("search_albums", [70]) in fake_lidarr.calls
    assert "add_artist" not in fake_lidarr.writes()


def test_album_unknown_to_lidarr_fails_and_does_not_count(admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups) -> None:
    fake_lidarr.artist_rows.append({"id": 7, "foreignArtistId": ARTIST})
    create_user("lena")

    body = _request(admin_client, auth_headers(admin_client, "lena")).json()
    assert body["request"]["status"] == "failed"
    assert body["request"]["error_code"] == "album_not_in_lidarr"
    assert body["quota"]["used"] == 0
    assert fake_lidarr.writes() == []


def test_excluded_release_type_is_refused_before_a_request_exists(
    admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups
) -> None:
    # 12.09.2026: Eine Anfrage fuer einen Soundtrack scheiterte still. nexbeat legte sie
    # an, Lidarr schloss die Art aus, und die Seite zeigte wieder "Anfragen". Dreimal.
    release_groups[RELEASE_GROUP]["primary_type"] = "Single"
    create_user("lena")
    headers = auth_headers(admin_client, "lena")

    single = _request(admin_client, headers)
    assert single.status_code == 422
    assert single.json()["detail"]["code"] == "release_type_excluded"

    release_groups[OTHER_RELEASE_GROUP]["secondary_types"] = ["Live"]
    live = _request(admin_client, headers, OTHER_RELEASE_GROUP)
    assert live.json()["detail"]["code"] == "release_type_excluded"

    assert admin_client.get("/api/requests/mine", headers=headers).json() == []
    assert fake_lidarr.writes() == []


def test_album_lidarr_already_lists_passes_whatever_the_default_profile_says(
    admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups
) -> None:
    # Ein Kuenstler in Lidarr kann ein anderes Metadatenprofil haben als das aus den
    # Einstellungen. Listet Lidarr das Album, laesst sein Profil es zu.
    release_groups[RELEASE_GROUP]["secondary_types"] = ["Live"]
    with SessionLocal() as db:
        db.add(LibraryArtist(mbid=ARTIST, lidarr_id=7, name="Test Artist"))
        db.commit()
    fake_lidarr.artist_rows.append({"id": 7, "foreignArtistId": ARTIST})
    fake_lidarr.album_rows.append({"id": 70, "artistId": 7, "foreignAlbumId": RELEASE_GROUP, "monitored": False, "statistics": {}})
    create_user("lena")

    response = _request(admin_client, auth_headers(admin_client, "lena"))
    assert response.status_code == 201, response.text
    assert response.json()["request"]["status"] == "searching"
    assert ("search_albums", [70]) in fake_lidarr.calls


def test_type_is_checked_again_when_an_admin_approves(
    admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups
) -> None:
    # Die Vorpruefung liest das Profil aus dem Zwischenspeicher. Bis zur Freigabe kann
    # es in Lidarr geaendert sein, deshalb liest die Uebergabe es frisch.
    create_user("lena", requires_approval=True)
    waiting = _request(admin_client, auth_headers(admin_client, "lena")).json()["request"]
    assert waiting["status"] == "pending_approval"

    fake_lidarr.profile = {"primaryAlbumTypes": [{"albumType": {"name": "Album"}, "allowed": False}]}
    approved = admin_client.post(f"/api/admin/requests/{waiting['id']}/approve").json()
    assert (approved["status"], approved["error_code"]) == ("failed", "release_type_excluded")
    assert fake_lidarr.writes() == []


def test_artist_in_lidarr_is_checked_against_its_own_profile(
    admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups
) -> None:
    # 12.09.2026: Das Profil aus den Einstellungen gilt nur fuer Kuenstler, die nexbeat neu
    # anlegt. Steht der Kuenstler schon in Lidarr, zaehlt sein eigenes.
    fake_lidarr.profiles[2] = {"primaryAlbumTypes": [{"albumType": {"name": "Album"}, "allowed": False}]}
    with SessionLocal() as db:
        db.add(LibraryArtist(mbid=ARTIST, lidarr_id=7, name="Test Artist", metadata_profile_id=2))
        db.commit()
    create_user("lena")
    headers = auth_headers(admin_client, "lena")

    refused = _request(admin_client, headers)
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "artist_profile_excludes_type"
    assert admin_client.get("/api/requests/mine", headers=headers).json() == []
    assert fake_lidarr.writes() == []


def test_hand_over_reads_the_artist_profile_fresh(
    admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups
) -> None:
    # Der Abgleich laeuft nur alle zehn Minuten. Bis zur Freigabe kann der Kuenstler in
    # Lidarr ein anderes Profil bekommen haben.
    create_user("lena", requires_approval=True)
    waiting = _request(admin_client, auth_headers(admin_client, "lena")).json()["request"]
    assert waiting["status"] == "pending_approval"

    fake_lidarr.profiles[2] = {"primaryAlbumTypes": [{"albumType": {"name": "Album"}, "allowed": False}]}
    fake_lidarr.artist_rows.append({"id": 7, "foreignArtistId": ARTIST, "metadataProfileId": 2})
    approved = admin_client.post(f"/api/admin/requests/{waiting['id']}/approve").json()
    assert (approved["status"], approved["error_code"]) == ("failed", "artist_profile_excludes_type")
    assert fake_lidarr.writes() == []


def test_dry_run_sends_nothing(admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups) -> None:
    admin_client.put("/api/settings", json={"lidarr_dry_run": True})
    create_user("lena")

    body = _request(admin_client, auth_headers(admin_client, "lena")).json()
    assert body["request"]["status"] == "approved"
    assert body["request"]["error_code"] == "dry_run"
    assert fake_lidarr.writes() == []
    assert _refresh() == 0
    assert fake_lidarr.writes() == []


def test_quota_is_enforced(admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups) -> None:
    create_user("lena", quota_limit=1)
    headers = auth_headers(admin_client, "lena")
    assert _request(admin_client, headers).status_code == 201

    second = _request(admin_client, headers, OTHER_RELEASE_GROUP)
    assert second.status_code == 429
    assert second.json()["detail"]["code"] == "quota_exhausted"
    assert second.json()["detail"]["limit"] == 1


def test_duplicate_request_is_refused(admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups) -> None:
    create_user("lena")
    create_user("tom")
    assert _request(admin_client, auth_headers(admin_client, "lena")).status_code == 201

    again = _request(admin_client, auth_headers(admin_client, "tom"))
    assert again.status_code == 409
    assert again.json()["detail"] == {**again.json()["detail"], "code": "already_requested", "mine": False}


def test_approval_flow_and_refund_on_rejection(admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups) -> None:
    create_user("lena", requires_approval=True, quota_limit=5)
    headers = auth_headers(admin_client, "lena")

    waiting = _request(admin_client, headers).json()
    assert waiting["request"]["status"] == "pending_approval"
    assert fake_lidarr.writes() == []

    approved = admin_client.post(f"/api/admin/requests/{waiting['request']['id']}/approve")
    assert approved.json()["status"] == "searching"
    assert "add_artist" in fake_lidarr.writes()

    second = _request(admin_client, headers, OTHER_RELEASE_GROUP).json()
    assert second["quota"]["used"] == 2
    rejected = admin_client.post(f"/api/admin/requests/{second['request']['id']}/reject", json={"reason": "Nicht jetzt"})
    assert rejected.json()["status"] == "rejected"
    assert admin_client.get("/api/auth/me", headers=headers).json()["quota"]["used"] == 1


def test_user_cannot_approve(admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups) -> None:
    create_user("lena", requires_approval=True)
    headers = auth_headers(admin_client, "lena")
    request_id = _request(admin_client, headers).json()["request"]["id"]
    assert admin_client.post(f"/api/admin/requests/{request_id}/approve", headers=headers).status_code == 403


def test_timeout_keeps_the_request_open_until_checked(admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups) -> None:
    fake_lidarr.fail_with["add_artist"] = LidarrError("lidarr_timeout", uncertain=True)
    create_user("lena")

    body = _request(admin_client, auth_headers(admin_client, "lena")).json()["request"]
    assert body["status"] == "approved"
    assert body["error_code"] == "lidarr_timeout"

    # Lidarr hatte den Auftrag doch angenommen: Kuenstler und Album tauchen auf.
    fake_lidarr.artist_rows.append({"id": 501, "foreignArtistId": ARTIST})
    fake_lidarr.album_rows.append({"id": 90, "artistId": 501, "foreignAlbumId": RELEASE_GROUP, "monitored": True, "statistics": {}})
    assert _refresh() == 1
    mine = admin_client.get("/api/requests/mine", headers=auth_headers(admin_client, "lena")).json()[0]
    assert mine["status"] == "searching"
    assert mine["error_code"] == ""


def test_background_check_marks_downloaded(admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups) -> None:
    create_user("lena")
    headers = auth_headers(admin_client, "lena")
    assert _request(admin_client, headers).json()["request"]["status"] == "searching"

    fake_lidarr.album_rows.append(
        {
            "id": 80,
            "artistId": 501,
            "foreignAlbumId": RELEASE_GROUP,
            "monitored": True,
            "statistics": {"trackFileCount": 10, "totalTrackCount": 10, "percentOfTracks": 100.0},
        }
    )
    assert _refresh() == 1
    mine = admin_client.get("/api/requests/mine", headers=headers).json()[0]
    assert (mine["status"], mine["progress"]) == ("downloaded", 100)
    assert mine["completed_at"].endswith("Z")


def test_album_that_never_appears_fails_after_a_while(admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups) -> None:
    create_user("lena")
    headers = auth_headers(admin_client, "lena")
    request_id = _request(admin_client, headers).json()["request"]["id"]

    assert _refresh() == 0
    with SessionLocal() as db:
        db.get(MusicRequest, request_id).submitted_at = utcnow() - timedelta(minutes=31)
        db.commit()
    assert _refresh() == 1
    mine = admin_client.get("/api/requests/mine", headers=headers).json()[0]
    assert (mine["status"], mine["error_code"]) == ("failed", "album_not_in_lidarr")


def test_requests_need_a_ready_lidarr(admin_client: TestClient, release_groups) -> None:
    response = _request(admin_client, {})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "requests_not_ready"


def test_cancel_waiting_request(admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups) -> None:
    create_user("lena", requires_approval=True)
    create_user("tom")
    headers = auth_headers(admin_client, "lena")
    request_id = _request(admin_client, headers).json()["request"]["id"]

    foreign = admin_client.post(f"/api/requests/{request_id}/cancel", headers=auth_headers(admin_client, "tom"))
    assert foreign.status_code == 404
    assert admin_client.post(f"/api/requests/{request_id}/cancel", headers=headers).json()["status"] == "cancelled"


def _age(request_id: int, minutes: int) -> None:
    with SessionLocal() as db:
        db.get(MusicRequest, request_id).submitted_at = utcnow() - timedelta(minutes=minutes)
        db.commit()


def _searches(fake: FakeLidarr) -> list[Any]:
    return [call[1] for call in fake.calls if call[0] == "search_albums"]


def test_search_is_started_again_once_when_nothing_happened(
    admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups
) -> None:
    # 12.09.2026: Lidarrs Suche nach dem Anlegen fiel mit "database is locked" aus und wurde
    # nie wiederholt. Erst eine Suche von Hand lud die Alben.
    create_user("lena")
    request_id = _request(admin_client, auth_headers(admin_client, "lena")).json()["request"]["id"]
    fake_lidarr.album_rows.append({"id": 80, "artistId": 501, "foreignAlbumId": RELEASE_GROUP, "monitored": True, "statistics": {}})

    _age(request_id, 5)
    _refresh()
    assert _searches(fake_lidarr) == []

    _age(request_id, 11)
    _refresh()
    assert _searches(fake_lidarr) == [[80]]

    _refresh()
    assert _searches(fake_lidarr) == [[80]]


def test_no_second_search_while_lidarr_is_downloading(
    admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups
) -> None:
    create_user("lena")
    request_id = _request(admin_client, auth_headers(admin_client, "lena")).json()["request"]["id"]
    fake_lidarr.album_rows.append({"id": 80, "artistId": 501, "foreignAlbumId": RELEASE_GROUP, "monitored": True, "statistics": {}})
    fake_lidarr.queue_rows.append({"artistId": 501, "albumId": 80})

    _age(request_id, 11)
    _refresh()
    assert _searches(fake_lidarr) == []


def test_no_second_search_after_a_partial_download(
    admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups
) -> None:
    create_user("lena")
    request_id = _request(admin_client, auth_headers(admin_client, "lena")).json()["request"]["id"]
    partial = {"trackFileCount": 3, "totalTrackCount": 10, "percentOfTracks": 30.0}
    fake_lidarr.album_rows.append({"id": 80, "artistId": 501, "foreignAlbumId": RELEASE_GROUP, "monitored": True, "statistics": partial})

    _age(request_id, 11)
    _refresh()
    assert _searches(fake_lidarr) == []
