from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import httpx
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import LibraryArtist
from app.services import cache, catalog, http
from app.services.lidarr import LidarrError
from app.services.recommendations import TRENDING_ALBUMS_KEY, TRENDING_ARTISTS_KEY
from app.services.settings_service import save_settings
from tests.fakes import FakeLidarr

SEED = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OWNED = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
NEW_ONE = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
NEW_TWO = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
TRENDING_ALBUM = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
# In Lidarr, aber ohne Dateien und damit nie Ausgangskuenstler. Nur die
# Bestandsregel kann ihn aus den Empfehlungen halten, nicht die Seed-Regel.
KNOWN_EMPTY = "ffffffff-ffff-4fff-8fff-ffffffffffff"
ALBUM = "12121212-1212-4212-8212-121212121212"
FIRST_RELEASE = "34343434-3434-4343-8343-343434343434"
LATER_RELEASE = "56565656-5656-4565-8565-565656565656"


def _prepare_library() -> None:
    with SessionLocal() as db:
        db.add(LibraryArtist(mbid=SEED, lidarr_id=1, name="Seed Band", track_file_count=10))
        db.add(LibraryArtist(mbid=OWNED, lidarr_id=2, name="Owned Band", track_file_count=5))
        db.add(LibraryArtist(mbid=KNOWN_EMPTY, lidarr_id=3, name="Known Empty", track_file_count=0))
        db.commit()
        day = timedelta(days=1)
        cache.write(
            db,
            catalog.similar_key(SEED),
            [
                {"mbid": OWNED, "name": "Owned Band", "score": 90},
                {"mbid": KNOWN_EMPTY, "name": "Known Empty", "score": 85},
                {"mbid": NEW_ONE, "name": "New One", "score": 80},
                {"mbid": NEW_TWO, "name": "New Two", "score": 40},
            ],
            day,
        )
        cache.write(db, catalog.similar_key(OWNED), [{"mbid": NEW_TWO, "name": "New Two", "score": 50}], day)
        cache.write(
            db,
            TRENDING_ALBUMS_KEY,
            [{"mbid": TRENDING_ALBUM, "title": "Hit", "artist_mbid": NEW_ONE, "artist_name": "New One", "listen_count": 5, "cover": ""}],
            day,
        )
        cache.write(db, TRENDING_ARTISTS_KEY, [], day)


def test_for_you_skips_known_artists_and_explains(admin_client: TestClient) -> None:
    _prepare_library()
    body = admin_client.get("/api/discover").json()
    rows = {row["id"]: row for row in body["rows"]}

    for_you = rows["for_you"]["items"]
    assert [item["mbid"] for item in for_you] == [NEW_TWO, NEW_ONE]
    # New Two passt zu beiden Ausgangskuenstlern und steht deshalb vorn. Best
    # ist 90, damit zaehlt New One 80/90 und New Two 40/90 + 50/50.
    assert sorted(for_you[0]["reasons"]) == ["Owned Band", "Seed Band"]
    assert for_you[1]["reasons"] == ["Seed Band"]
    assert all(item["image"].startswith("/api/images/artist/") for item in for_you)

    trending = rows["trending_albums"]["items"]
    assert trending[0]["cover"] == f"https://coverartarchive.org/release-group/{TRENDING_ALBUM}/front-250"
    assert "trending_artists" not in rows
    assert body["library_size"] == 3


def test_without_listenbrainz_there_are_no_rows(admin_client: TestClient) -> None:
    _prepare_library()
    admin_client.put("/api/settings", json={"source_listenbrainz": False})
    assert admin_client.get("/api/discover").json()["rows"] == []


def test_artist_image_redirects_to_the_library_poster(client: TestClient) -> None:
    with SessionLocal() as db:
        db.add(LibraryArtist(mbid=SEED, lidarr_id=1, name="Seed Band", image_url="https://images.example.com/poster.jpg"))
        db.commit()
        save_settings(db, {"source_deezer": False})

    found = client.get(f"/api/images/artist/{SEED}?name=Seed%20Band", follow_redirects=False)
    assert found.status_code == 302
    assert found.headers["location"] == "https://images.example.com/poster.jpg"

    missing = client.get(f"/api/images/artist/{NEW_ONE}?name=Nobody", follow_redirects=False)
    assert missing.status_code == 404
    assert client.get("/api/images/artist/not-an-mbid", follow_redirects=False).status_code == 404


def test_failed_image_lookup_is_not_kept_by_the_browser(client: TestClient) -> None:
    # 11.09.2026: Deezer lehnte bei vielen Bildern auf einmal ab. Die 404 blieb eine
    # Stunde im Browser, auch als Deezer laengst wieder antwortete.
    quota = {"error": {"type": "Exception", "message": "Quota limit exceeded", "code": 4}}
    http.use_transport(httpx.MockTransport(lambda _r: httpx.Response(200, json=quota)))
    failed = client.get(f"/api/images/artist/{NEW_ONE}?name=Busy%20Band", follow_redirects=False)
    assert failed.status_code == 404
    assert failed.headers["cache-control"] == "no-store"

    http.use_transport(httpx.MockTransport(lambda _r: httpx.Response(200, json={"data": []})))
    unknown = client.get(f"/api/images/artist/{NEW_ONE}?name=Busy%20Band", follow_redirects=False)
    assert unknown.status_code == 404
    assert "max-age" in unknown.headers["cache-control"]


def test_artist_search_is_cached(admin_client: TestClient) -> None:
    calls = [0]

    def handler(_request: httpx.Request) -> httpx.Response:
        calls[0] += 1
        return httpx.Response(200, json={"artists": [{"id": NEW_ONE, "name": "Found Band", "score": 90}]})

    http.use_transport(httpx.MockTransport(handler))
    first = admin_client.get("/api/search/artists", params={"q": "found"})
    second = admin_client.get("/api/search/artists", params={"q": "  FOUND "})
    assert first.status_code == 200, first.text
    assert first.json() == second.json()
    assert calls[0] == 1
    assert first.json()[0]["image"] == f"/api/images/artist/{NEW_ONE}?name=Found%20Band"


def test_unreachable_musicbrainz_is_reported(admin_client: TestClient) -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    http.use_transport(httpx.MockTransport(broken))
    response = admin_client.get(f"/api/artists/{NEW_ONE}")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "musicbrainz_unreachable"
    assert admin_client.get("/api/artists/kaputt").json()["detail"]["code"] == "invalid_mbid"


def _release(release_id: str, date: str, titles: list[str]) -> dict[str, Any]:
    """Ein Release, wie es der Browse-Aufruf mit Titeln und Release-Group liefert."""
    return {
        "id": release_id,
        "status": "Official",
        "date": date,
        "country": "XE",
        "release-group": {
            "id": ALBUM,
            "title": "Record",
            "primary-type": "Album",
            "secondary-types": [],
            "first-release-date": "1999-03-01",
            "artist-credit": [{"name": "Band", "joinphrase": "", "artist": {"id": NEW_ONE, "name": "Band"}}],
        },
        "media": [
            {
                "position": 1,
                "tracks": [
                    {"position": index, "title": title, "length": 180000, "recording": {"title": title}}
                    for index, title in enumerate(titles, start=1)
                ],
            }
        ],
    }


def test_album_page_needs_one_musicbrainz_call(admin_client: TestClient) -> None:
    # 11.09.2026 gemessen: Zur Spitzenzeit lehnte MusicBrainz reihenweise mit 503 ab,
    # die Albumseite brauchte 15 Sekunden. Jeder Aufruf weniger ist ein Risiko weniger.
    admin_client.put("/api/settings", json={"source_deezer": False})
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        releases = [_release(LATER_RELEASE, "2001-05-01", ["Late Version"]), _release(FIRST_RELEASE, "1999-03-01", ["Opener", "Closer"])]
        return httpx.Response(200, json={"release-count": 2, "releases": releases})

    http.use_transport(httpx.MockTransport(handler))
    page = admin_client.get(f"/api/albums/{ALBUM}")
    assert page.status_code == 200, page.text
    body = page.json()
    assert (body["album"]["title"], body["album"]["artist_name"], body["album"]["artist_mbid"]) == ("Record", "Band", NEW_ONE)
    assert [track["title"] for track in body["tracks"]] == ["Opener", "Closer"]
    assert paths == ["/ws/2/release"]

    # Wer danach anfragt, loest bei MusicBrainz nichts mehr aus.
    with SessionLocal() as db:
        group = asyncio.run(catalog.release_group_info(db, ALBUM))
    assert group["title"] == "Record"
    assert paths == ["/ws/2/release"]


def test_album_page_says_when_lidarr_would_refuse_the_type(admin_client: TestClient, fake_lidarr: FakeLidarr) -> None:
    # 12.09.2026: Einen Soundtrack konnte man anfragen, und die Anfrage scheiterte still.
    # Jetzt sagt die Seite vorher, dass das Metadatenprofil in Lidarr die Art ausschliesst.
    admin_client.put("/api/settings", json={"source_deezer": False})

    def handler(_request: httpx.Request) -> httpx.Response:
        release = _release(FIRST_RELEASE, "1999-03-01", ["Opener"])
        release["release-group"]["secondary-types"] = ["Live"]
        return httpx.Response(200, json={"release-count": 1, "releases": [release]})

    http.use_transport(httpx.MockTransport(handler))
    for _ in range(2):
        assert admin_client.get(f"/api/albums/{ALBUM}").json()["blocked"] == "release_type_excluded"
    # Das Profil kommt aus dem Zwischenspeicher, nicht bei jedem Seitenaufruf aus Lidarr.
    assert [call for call in fake_lidarr.calls if call[0] == "metadata_profile"] == [("metadata_profile", 1)]

    # Listet Lidarr das Album beim Kuenstler, laesst dessen Profil es offenbar zu.
    with SessionLocal() as db:
        db.add(LibraryArtist(mbid=NEW_ONE, lidarr_id=9, name="Band"))
        db.commit()
    fake_lidarr.album_rows.append({"id": 90, "artistId": 9, "foreignAlbumId": ALBUM, "monitored": False, "statistics": {}})
    assert admin_client.get(f"/api/albums/{ALBUM}").json()["blocked"] is None


def test_album_page_loads_when_lidarr_does_not_answer(admin_client: TestClient, fake_lidarr: FakeLidarr) -> None:
    # Die Vorpruefung ist eine Hilfe, keine Bedingung. Faellt Lidarr aus, bleibt die Seite da.
    admin_client.put("/api/settings", json={"source_deezer": False})
    fake_lidarr.fail_with["metadata_profile"] = LidarrError("lidarr_unreachable")
    body = {"release-count": 1, "releases": [_release(FIRST_RELEASE, "1999-03-01", ["Opener"])]}
    http.use_transport(httpx.MockTransport(lambda _r: httpx.Response(200, json=body)))

    page = admin_client.get(f"/api/albums/{ALBUM}")
    assert page.status_code == 200, page.text
    assert page.json()["blocked"] is None


def test_album_page_uses_the_profile_the_artist_has_in_lidarr(admin_client: TestClient, fake_lidarr: FakeLidarr) -> None:
    # 12.09.2026: In nexbeat stand ein Profil mit Soundtracks, der Kuenstler hatte in Lidarr
    # "Standard". Die Seite bot die Anfrage an, und Lidarr fuehrte das Album nie.
    admin_client.put("/api/settings", json={"source_deezer": False})
    fake_lidarr.profiles[2] = {"primaryAlbumTypes": [{"albumType": {"name": "Album"}, "allowed": False}]}
    with SessionLocal() as db:
        db.add(LibraryArtist(mbid=NEW_ONE, lidarr_id=9, name="Band", metadata_profile_id=2))
        db.commit()
    body = {"release-count": 1, "releases": [_release(FIRST_RELEASE, "1999-03-01", ["Opener"])]}
    http.use_transport(httpx.MockTransport(lambda _r: httpx.Response(200, json=body)))

    assert admin_client.get(f"/api/albums/{ALBUM}").json()["blocked"] == "artist_profile_excludes_type"


def test_library_sync_keeps_the_artist_profile(admin_client: TestClient, fake_lidarr: FakeLidarr) -> None:
    fake_lidarr.artist_rows.append({"id": 9, "foreignArtistId": NEW_ONE, "artistName": "Band", "metadataProfileId": 2})
    assert admin_client.post("/api/settings/library/sync").json() == {"artists": 1}
    with SessionLocal() as db:
        assert db.get(LibraryArtist, NEW_ONE).metadata_profile_id == 2


def test_artist_image_cannot_be_chosen_by_the_first_caller(client: TestClient) -> None:
    # 12.09.2026: Wer ohne Anmeldung zuerst mit einem falschen Namen fragte, bestimmte das Bild.
    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.params.get("q", "")
        picture = "https://cdn.example.com/real.jpg" if name == "Real Band" else "https://cdn.example.com/wrong.jpg"
        return httpx.Response(200, json={"data": [{"id": 1, "name": name, "nb_fan": 10, "picture_xl": picture}]})

    http.use_transport(httpx.MockTransport(handler))
    wrong = client.get(f"/api/images/artist/{NEW_ONE}?name=Someone%20Else", follow_redirects=False)
    real = client.get(f"/api/images/artist/{NEW_ONE}?name=Real%20Band", follow_redirects=False)
    assert wrong.headers["location"] == "https://cdn.example.com/wrong.jpg"
    assert real.headers["location"] == "https://cdn.example.com/real.jpg"
