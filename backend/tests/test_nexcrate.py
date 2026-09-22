"""NEX-Modus: Anfragen an nexcrate statt an Lidarr (``docs/plan-nexcrate.md``).

Die Attrappe steht auf HTTP-Ebene (``tests/fake_nexcrate.py``), also laufen Client, Fehlerform und
Stromformat echt.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import LibraryArtist, MusicRequest, utcnow
from app.services import http, library, nexcrate, nexcrate_events, poller, requests_service
from app.services.settings_service import load_settings
from tests.conftest import ARTIST, OTHER_RELEASE_GROUP, RELEASE_GROUP, auth_headers, create_user
from tests.fake_nexcrate import KEY, URL, FakeNexcrate
from tests.fakes import FakeLidarr

STUDIO_ONE = "44444444-4444-4444-8444-444444444444"
STUDIO_TWO = "55555555-5555-4555-8555-555555555555"


@pytest.fixture
def fake_nexcrate(admin_client: TestClient) -> Iterator[FakeNexcrate]:
    """Verbundene nexcrate im NEX-Modus, dahinter die Attrappe."""
    fake = FakeNexcrate()
    http.use_transport(httpx.MockTransport(fake.handle))
    response = admin_client.put(
        "/api/settings", json={"request_mode": "nex", "nexcrate_url": URL, "nexcrate_api_key": KEY}
    )
    assert response.status_code == 200, response.text
    yield fake


def _request(client: TestClient, headers: dict[str, str], mbid: str = RELEASE_GROUP) -> Any:
    return client.post("/api/requests", json={"release_group_mbid": mbid}, headers=headers)


def _refresh(now: Any = None) -> int:
    with SessionLocal() as db:
        return asyncio.run(requests_service.refresh_open(db, load_settings(db), now))


def _sync() -> int | None:
    with SessionLocal() as db:
        return asyncio.run(library.sync_artists(db, load_settings(db)))


def _stored(request_id: int) -> MusicRequest:
    with SessionLocal() as db:
        found = db.get(MusicRequest, request_id)
        assert found is not None
        db.expunge(found)
        return found


# ---- Modus --------------------------------------------------------------------------------------


def test_an_installation_with_lidarr_stays_in_arr_mode(admin_client: TestClient, fake_lidarr: FakeLidarr) -> None:
    with SessionLocal() as db:
        settings = load_settings(db)
    assert settings.text("request_mode") == ""
    assert settings.mode == "arr"
    assert settings.target == "lidarr"
    assert admin_client.get("/api/auth/me").json()["request_target"] == "lidarr"


def test_without_a_choice_and_without_lidarr_nothing_is_ready(admin_client: TestClient) -> None:
    with SessionLocal() as db:
        settings = load_settings(db)
    assert (settings.mode, settings.requests_ready, settings.target) == (None, False, None)
    assert admin_client.put("/api/settings", json={"request_mode": "both"}).status_code == 422


def test_nex_mode_never_touches_lidarr(
    admin_client: TestClient, fake_lidarr: FakeLidarr, fake_nexcrate: FakeNexcrate, release_groups
) -> None:
    # Lidarr bleibt eingetragen, gewaehlt ist nexcrate: Lidarr bekommt nicht einmal eine Lesefrage.
    create_user("lena")
    assert _request(admin_client, auth_headers(admin_client, "lena")).status_code == 201
    _refresh()
    _sync()
    assert fake_lidarr.calls == []
    assert len(fake_nexcrate.requests_sent()) == 1
    assert admin_client.get("/api/auth/me").json()["request_target"] == "nexcrate"


# ---- Anfragen -----------------------------------------------------------------------------------


def test_an_album_goes_to_nexcrate_with_its_origin(
    admin_client: TestClient, fake_nexcrate: FakeNexcrate, release_groups
) -> None:
    create_user("lena")
    body = _request(admin_client, auth_headers(admin_client, "lena")).json()
    assert body["request"]["status"] == "searching"
    assert body["quota"]["used"] == 1
    assert fake_nexcrate.requests_sent() == [
        {
            "kind": "album",
            "ref": f"mbid:{RELEASE_GROUP}",
            "origin": f"nexbeat:request:{body['request']['id']}",
            "search_now": True,
        }
    ]


def test_a_whole_artist_asks_for_studio_albums_only(
    admin_client: TestClient, fake_nexcrate: FakeNexcrate, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def info(_db: Any, mbid: str) -> dict[str, Any]:
        return {"mbid": mbid, "name": "Example Artist"}

    async def studio(_db: Any, _mbid: str) -> list[dict[str, Any]]:
        return [{"mbid": STUDIO_ONE}, {"mbid": STUDIO_TWO}]

    monkeypatch.setattr(requests_service.catalog, "artist_info", info)
    monkeypatch.setattr(requests_service.catalog, "studio_albums", studio)
    fake_nexcrate.studio[ARTIST] = [STUDIO_ONE, STUDIO_TWO]
    create_user("lena")
    response = admin_client.post(
        "/api/requests/artist", json={"artist_mbid": ARTIST}, headers=auth_headers(admin_client, "lena")
    )
    assert response.status_code == 201, response.text
    sent = fake_nexcrate.requests_sent()
    assert sent[0]["kind"] == "artist"
    assert sent[0]["ref"] == f"mbid:{ARTIST}"
    # Entschieden am 22.09.2026: nur Studioalben. nexcrates Vorgabe waeren Studioalben und EPs.
    assert sent[0]["artist"] == {"albums": "studio", "types": ["studio"]}


def test_a_dry_run_sends_nothing_to_nexcrate(
    admin_client: TestClient, fake_nexcrate: FakeNexcrate, release_groups
) -> None:
    admin_client.put("/api/settings", json={"lidarr_dry_run": True})
    create_user("lena")
    body = _request(admin_client, auth_headers(admin_client, "lena")).json()
    assert body["request"]["error_code"] == "dry_run"
    _refresh()
    assert fake_nexcrate.requests_sent() == []


@pytest.mark.parametrize(
    ("answer", "code"),
    [
        (httpx.ReadTimeout("slow"), "nexcrate_timeout"),
        (httpx.ConnectError("down"), "nexcrate_unreachable"),
        (
            httpx.Response(429, json={"code": "rate_limited", "message": "x", "params": {"retry_after": 1}}),
            "nexcrate_busy",
        ),
        (httpx.Response(500, json={"code": "internal_error", "message": "x", "params": {}}), "nexcrate_pending"),
        (httpx.Response(502, text="<html><body>502 Bad Gateway</body></html>"), "nexcrate_unavailable"),
    ],
)
def test_an_open_outcome_is_simply_sent_again(
    admin_client: TestClient, fake_nexcrate: FakeNexcrate, release_groups, answer: Any, code: str
) -> None:
    # nexcrate nimmt Anfragen idempotent an. Kein Warten wie bei Lidarr, ob etwas angekommen ist.
    fake_nexcrate.next_answer["POST /api/v1/requests"] = answer
    create_user("lena")
    request = _request(admin_client, auth_headers(admin_client, "lena")).json()["request"]
    assert (request["status"], request["error_code"]) == ("approved", code)
    # Nicht sofort: die erste Uebergabe kann noch unterwegs sein.
    assert _refresh() == 0
    assert _refresh(utcnow() + timedelta(minutes=2)) == 1
    assert _stored(request["id"]).status.value == "searching"
    assert len(fake_nexcrate.requests_sent()) == 2


def test_the_owner_can_send_an_open_one_again_by_hand(
    admin_client: TestClient, fake_nexcrate: FakeNexcrate, release_groups
) -> None:
    fake_nexcrate.next_answer["POST /api/v1/requests"] = httpx.ConnectError("down")
    create_user("lena")
    request = _request(admin_client, auth_headers(admin_client, "lena")).json()["request"]
    response = admin_client.post(f"/api/admin/requests/{request['id']}/retry")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "searching"


def test_no_music_version_fails_and_does_not_count(
    admin_client: TestClient, fake_nexcrate: FakeNexcrate, release_groups
) -> None:
    fake_nexcrate.music_version = None
    create_user("lena")
    body = _request(admin_client, auth_headers(admin_client, "lena")).json()
    assert (body["request"]["status"], body["request"]["error_code"]) == ("failed", "nexcrate_no_music_version")
    assert body["quota"]["used"] == 0
    assert _refresh() == 0
    assert len(fake_nexcrate.requests_sent()) == 1


def test_a_revoked_key_fails_the_request(admin_client: TestClient, fake_nexcrate: FakeNexcrate, release_groups) -> None:
    fake_nexcrate.key = "nxc_other"
    create_user("lena")
    body = _request(admin_client, auth_headers(admin_client, "lena")).json()
    assert (body["request"]["status"], body["request"]["error_code"]) == ("failed", "nexcrate_key_rejected")


# ---- Stand ----------------------------------------------------------------------------------------


def test_the_background_check_follows_an_album_to_downloaded(
    admin_client: TestClient, fake_nexcrate: FakeNexcrate, release_groups
) -> None:
    create_user("lena")
    request_id = _request(admin_client, auth_headers(admin_client, "lena")).json()["request"]["id"]
    assert _refresh() == 0

    fake_nexcrate.albums[RELEASE_GROUP]["tracks"] = (4, 10)
    fake_nexcrate.albums[RELEASE_GROUP]["versions"][0]["state"] = "downloading"
    assert _refresh() == 1
    assert _stored(request_id).progress == 40

    fake_nexcrate.albums[RELEASE_GROUP]["tracks"] = (10, 10)
    fake_nexcrate.albums[RELEASE_GROUP]["versions"][0]["state"] = "available"
    assert _refresh() == 1
    stored = _stored(request_id)
    assert (stored.status.value, stored.progress) == ("downloaded", 100)
    # Ein Stapel fuer alle offenen Anfragen, nicht ein Aufruf je Titel.
    assert [path for _m, path, _b in fake_nexcrate.calls].count("/api/v1/titles/lookup") == 3


def test_an_album_taken_back_in_nexcrate_fails(
    admin_client: TestClient, fake_nexcrate: FakeNexcrate, release_groups
) -> None:
    create_user("lena")
    request_id = _request(admin_client, auth_headers(admin_client, "lena")).json()["request"]["id"]
    fake_nexcrate.albums[RELEASE_GROUP]["versions"] = []
    assert _refresh() == 1
    assert _stored(request_id).error_code == "nexcrate_not_watched"


def test_a_title_gone_from_nexcrate_fails_only_after_a_while(
    admin_client: TestClient, fake_nexcrate: FakeNexcrate, release_groups
) -> None:
    create_user("lena")
    request_id = _request(admin_client, auth_headers(admin_client, "lena")).json()["request"]["id"]
    del fake_nexcrate.albums[RELEASE_GROUP]
    assert _refresh() == 0
    assert _refresh(utcnow() + timedelta(hours=1)) == 1
    assert _stored(request_id).error_code == "nexcrate_title_gone"


def test_a_whole_artist_is_done_when_every_watched_album_is_there(
    admin_client: TestClient, fake_nexcrate: FakeNexcrate, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def info(_db: Any, mbid: str) -> dict[str, Any]:
        return {"mbid": mbid, "name": "Example Artist"}

    async def studio(_db: Any, _mbid: str) -> list[dict[str, Any]]:
        return [{"mbid": STUDIO_ONE}, {"mbid": STUDIO_TWO}]

    monkeypatch.setattr(requests_service.catalog, "artist_info", info)
    monkeypatch.setattr(requests_service.catalog, "studio_albums", studio)
    fake_nexcrate.studio[ARTIST] = [STUDIO_ONE, STUDIO_TWO]
    request_id = admin_client.post("/api/requests/artist", json={"artist_mbid": ARTIST}).json()["request"]["id"]

    fake_nexcrate.albums[STUDIO_ONE]["versions"][0]["state"] = "available"
    assert _refresh() == 1
    assert _stored(request_id).progress == 50
    fake_nexcrate.artists[ARTIST]["loading"] = True
    fake_nexcrate.albums[STUDIO_TWO]["versions"][0]["state"] = "available"
    # Solange nexcrate den Katalog noch laedt, kann ein Album dazukommen.
    _refresh()
    assert _stored(request_id).status.value == "searching"
    fake_nexcrate.artists[ARTIST]["loading"] = False
    _refresh()
    assert _stored(request_id).status.value == "downloaded"


# ---- Bestand ------------------------------------------------------------------------------------


def test_artists_are_read_whole_then_by_marker(admin_client: TestClient, fake_nexcrate: FakeNexcrate) -> None:
    fake_nexcrate.add_artist(ARTIST, "First Artist")
    fake_nexcrate.add_album(RELEASE_GROUP, ARTIST, state="available", have=10)
    fake_nexcrate.add_artist(STUDIO_ONE, "Second Artist")
    assert _sync() == 2
    with SessionLocal() as db:
        row = db.get(LibraryArtist, ARTIST)
        assert row is not None
        assert (row.name, row.track_file_count, row.album_count) == ("First Artist", 1, 1)

    fake_nexcrate.remove_artist(STUDIO_ONE)
    fake_nexcrate.add_artist(STUDIO_TWO, "Third Artist")
    assert _sync() == 2
    reads = [c for c in fake_nexcrate.calls if c[1] == "/api/v1/titles"]
    assert len(reads) == 2
    with SessionLocal() as db:
        assert {row.mbid for row in db.query(LibraryArtist)} == {ARTIST, STUDIO_TWO}


def test_a_marker_from_another_nexcrate_reads_everything_again(
    admin_client: TestClient, fake_nexcrate: FakeNexcrate
) -> None:
    fake_nexcrate.add_artist(ARTIST)
    fake_nexcrate.add_artist(STUDIO_ONE)
    fake_nexcrate.add_artist(STUDIO_TWO)
    assert _sync() == 3
    # Neu aufgesetzt, dieselbe Adresse: die Nummern beginnen von vorn, ueber latest ist nichts.
    fresh = FakeNexcrate()
    fresh.installation_id = fake_nexcrate.installation_id
    fresh.add_artist(ARTIST)
    http.use_transport(httpx.MockTransport(fresh.handle))
    assert _sync() == 1


def test_a_marker_too_old_reads_everything_again(admin_client: TestClient, fake_nexcrate: FakeNexcrate) -> None:
    fake_nexcrate.add_artist(ARTIST)
    _sync()
    fake_nexcrate.add_artist(STUDIO_ONE)
    fake_nexcrate.oldest_marker = 100
    assert _sync() == 2


def test_album_states_come_from_the_artist_catalogue(admin_client: TestClient, fake_nexcrate: FakeNexcrate) -> None:
    fake_nexcrate.add_artist(ARTIST)
    fake_nexcrate.add_album(RELEASE_GROUP, ARTIST, state="incomplete", have=3, total=12)
    fake_nexcrate.add_album(OTHER_RELEASE_GROUP, ARTIST)
    fake_nexcrate.add_album(STUDIO_ONE, ARTIST, state="wanted")
    fake_nexcrate.add_album(STUDIO_TWO, ARTIST, state="available", have=9, total=9)
    _sync()
    with SessionLocal() as db:
        states = asyncio.run(library.album_states(db, load_settings(db), ARTIST))
    assert states[RELEASE_GROUP] == {"state": "partial", "percent": 25, "lidarr_id": None}
    assert states[OTHER_RELEASE_GROUP]["state"] == "known"
    assert states[STUDIO_ONE]["state"] == "wanted"
    assert states[STUDIO_TWO]["state"] == "available"


@pytest.mark.parametrize(
    ("state", "have", "monitored", "expected"),
    [
        ("available", 0, True, "available"),
        ("upgrade", 10, True, "available"),
        ("incomplete", 5, True, "partial"),
        # Je ein Weg allein: nexcrate sagt "Titel fehlen", zaehlt aber noch keinen; oder es laedt, und
        # ein Teil ist schon da.
        ("incomplete", 0, True, "partial"),
        ("downloading", 4, True, "partial"),
        ("downloading", 0, True, "wanted"),
        ("problem", 0, True, "wanted"),
        ("unmonitored", 0, False, "known"),
        ("some_future_state", 0, True, "wanted"),
    ],
)
def test_album_view_names_every_state(state: str, have: int, monitored: bool, expected: str) -> None:
    title = {"versions": [{"state": state, "monitored": monitored, "album": {"tracks": {"have": have, "total": 10}}}]}
    assert nexcrate.album_view(title).state == expected


def test_metadata_profile_blocks_do_not_apply(
    admin_client: TestClient, fake_nexcrate: FakeNexcrate, release_groups
) -> None:
    release_groups[RELEASE_GROUP]["primary_type"] = "Single"
    create_user("lena")
    assert _request(admin_client, auth_headers(admin_client, "lena")).status_code == 201


# ---- Einstellungen, Koppeln ---------------------------------------------------------------------


def test_the_check_names_what_the_music_version_lacks(admin_client: TestClient, fake_nexcrate: FakeNexcrate) -> None:
    fake_nexcrate.music_version = {"ready": False, "reasons": ["no_indexer", "no_download_client"], "tier": None}
    body = admin_client.post("/api/settings/test/nexcrate", json={}).json()
    assert (body["version"], body["contract"], body["music"], body["can_request"]) == ("0.1.0", 1, True, True)
    assert body["music_versions"] == [
        {"name": "Music", "tier": None, "ready": False, "reasons": ["no_indexer", "no_download_client"]}
    ]
    status = admin_client.get("/api/settings/nexcrate/status").json()
    assert (status["connected"], status["key_hint"]) == (True, KEY[-4:])


def test_pairing_stores_the_key_the_owner_confirmed(admin_client: TestClient) -> None:
    fake = FakeNexcrate()
    http.use_transport(httpx.MockTransport(fake.handle))
    started = admin_client.post("/api/settings/nexcrate/pairing", json={"url": URL + "/"}).json()
    assert (started["state"], started["code"]) == ("pending", "5Z3-M4G")
    assert fake.pairings["pair1"]["scopes"] == ["read", "request"]
    assert admin_client.get("/api/settings/nexcrate/pairing").json()["state"] == "pending"

    fake.pairings["pair1"]["state"] = "confirmed"
    assert admin_client.get("/api/settings/nexcrate/pairing").json()["state"] == "confirmed"
    settings = admin_client.get("/api/settings").json()
    assert (settings["nexcrate_url"], settings["nexcrate_api_key_set"]) == (URL, True)
    assert "nexcrate_pairing" not in settings
    # Der Schluessel kam genau einmal; danach wartet nichts mehr.
    assert admin_client.get("/api/settings/nexcrate/pairing").json()["state"] == "none"


@pytest.mark.parametrize(("state", "shown"), [("denied", "denied"), ("delivered", "expired")])
def test_pairing_ends_without_a_key(admin_client: TestClient, state: str, shown: str) -> None:
    fake = FakeNexcrate()
    http.use_transport(httpx.MockTransport(fake.handle))
    admin_client.post("/api/settings/nexcrate/pairing", json={"url": URL})
    fake.pairings["pair1"]["state"] = state
    assert admin_client.get("/api/settings/nexcrate/pairing").json()["state"] == shown
    assert admin_client.get("/api/settings").json()["nexcrate_api_key_set"] is False


def test_a_forgotten_pairing_is_expired(admin_client: TestClient) -> None:
    fake = FakeNexcrate()
    http.use_transport(httpx.MockTransport(fake.handle))
    admin_client.post("/api/settings/nexcrate/pairing", json={"url": URL})
    fake.pairings.clear()
    assert admin_client.get("/api/settings/nexcrate/pairing").json()["state"] == "expired"


def test_switching_the_target_forgets_the_library(admin_client: TestClient, fake_nexcrate: FakeNexcrate) -> None:
    fake_nexcrate.add_artist(ARTIST)
    _sync()
    admin_client.put("/api/settings", json={"request_mode": "arr"})
    with SessionLocal() as db:
        assert db.query(LibraryArtist).count() == 0
        assert load_settings(db).text("nexcrate_marker") == ""


# ---- Fehlerform und Strom -------------------------------------------------------------------------


def test_both_error_forms_are_read() -> None:
    flat = httpx.Response(409, json={"code": "version_not_available", "message": "x", "params": {"kind": "album"}})
    nested = httpx.Response(404, json={"detail": {"code": "not_found", "message": "Not found."}})
    assert nexcrate._error_from(flat, "/x").code == "nexcrate_no_music_version"
    assert nexcrate._error_from(flat, "/x").params == {"kind": "album"}
    assert nexcrate._error_from(nested, "/x").code == "nexcrate_path_unknown"
    assert nexcrate._error_from(httpx.Response(502, text="Bad Gateway"), "/x").transient is True


def test_the_stream_wakes_the_check_for_music_only(admin_client: TestClient, fake_nexcrate: FakeNexcrate) -> None:
    fake_nexcrate.event("request.made", "album", RELEASE_GROUP)
    fake_nexcrate.event("download.imported", "movie", "1")
    fake_nexcrate.event("title.added", "artist", ARTIST)
    woken: list[bool] = []
    client = nexcrate.NexcrateClient(URL, KEY)

    async def read() -> None:
        nexcrate_events._status["last_seq"] = 0
        await nexcrate_events._consume(client, woken.append)

    asyncio.run(read())
    assert woken == [False, True]
    assert nexcrate_events.status()["last_seq"] == 3
    assert ("GET", "/api/v1/events/stream", None) in fake_nexcrate.calls


# ---- Umschalten ---------------------------------------------------------------------------------


def test_open_lidarr_requests_move_to_nexcrate_after_the_switch(
    admin_client: TestClient, fake_lidarr: FakeLidarr, release_groups
) -> None:
    create_user("lena")
    request_id = _request(admin_client, auth_headers(admin_client, "lena")).json()["request"]["id"]
    assert _stored(request_id).status.value == "searching"

    fake = FakeNexcrate()
    http.use_transport(httpx.MockTransport(fake.handle))
    admin_client.put("/api/settings", json={"request_mode": "nex", "nexcrate_url": URL, "nexcrate_api_key": KEY})
    assert _refresh() == 1
    assert [body["ref"] for body in fake.requests_sent()] == [f"mbid:{RELEASE_GROUP}"]
    assert _stored(request_id).status.value == "searching"
    # Einmal: danach ist sie nexcrates Anfrage wie jede andere.
    _refresh()
    assert len(fake.requests_sent()) == 1


def test_open_nexcrate_requests_move_to_lidarr_after_the_switch(
    admin_client: TestClient, fake_lidarr: FakeLidarr, fake_nexcrate: FakeNexcrate, release_groups
) -> None:
    create_user("lena")
    request_id = _request(admin_client, auth_headers(admin_client, "lena")).json()["request"]["id"]
    assert fake_lidarr.writes() == []

    admin_client.put("/api/settings", json={"request_mode": "arr"})
    _refresh()
    assert "add_artist" in fake_lidarr.writes()
    assert _stored(request_id).status.value == "searching"


def test_entering_a_nexcrate_in_arr_mode_keeps_the_lidarr_library(
    admin_client: TestClient, fake_lidarr: FakeLidarr
) -> None:
    fake_lidarr.artist_rows.append({"id": 7, "foreignArtistId": ARTIST, "artistName": "Test Artist"})
    _sync()
    admin_client.put("/api/settings", json={"nexcrate_url": URL})
    with SessionLocal() as db:
        assert db.query(LibraryArtist).count() == 1
        assert load_settings(db).mode == "arr"


def test_times_of_the_stream_carry_their_zone() -> None:
    # Ohne "Z" las der Browser die Zeit als Ortszeit und zeigte sie zwei Stunden daneben (22.09.2026).
    moment = utcnow()
    assert nexcrate_events._iso(moment) == moment.isoformat() + "Z"


@pytest.mark.parametrize("how", ["pairing", "switch"])
def test_the_library_is_read_right_after_connecting_or_switching(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    # 22.09.2026: Nach dem Koppeln war der Bestand bis zum naechsten planmaessigen Abgleich (zehn Minuten) leer.
    # Entdecken zeigte einen Kuenstler aus nexcrate als neu, und die Anfrage dafuer ging durch.
    woken: list[bool] = []
    monkeypatch.setattr(poller, "wake", lambda library_too=False: woken.append(library_too))
    fake = FakeNexcrate()
    http.use_transport(httpx.MockTransport(fake.handle))
    admin_client.put("/api/settings", json={"request_mode": "nex"})
    woken.clear()
    if how == "pairing":
        admin_client.post("/api/settings/nexcrate/pairing", json={"url": URL})
        fake.pairings["pair1"]["state"] = "confirmed"
        assert admin_client.get("/api/settings/nexcrate/pairing").json()["state"] == "confirmed"
    else:
        admin_client.put("/api/settings", json={"request_mode": "arr"})
    assert True in woken


def test_a_proxy_error_page_says_nexcrate_is_not_there() -> None:
    # 22.09.2026: nexcrate wurde neu aufgespielt, der Proxy davor antwortete 502 mit HTML. nexbeat sagte
    # "abgelehnt", und niemand kam darauf, dass nexcrate gar nicht lief.
    page = "<html>\n<body>502 Bad Gateway</body>\n</html>"
    error = nexcrate._error_from(httpx.Response(502, text=page), "/system")
    assert (error.code, error.transient) == ("nexcrate_unavailable", True)
    assert error.detail == "HTTP 502: <html> <body>502 Bad Gateway</body> </html>"
