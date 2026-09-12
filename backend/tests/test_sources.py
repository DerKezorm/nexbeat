from __future__ import annotations

import asyncio
from urllib.parse import unquote

import httpx
import pytest

from app.db import SessionLocal
from app.services import catalog, deezer, http, listenbrainz, musicbrainz
from app.services.lidarr import LidarrClient, LidarrError, image_url, type_allowed
from tests.conftest import ARTIST

SEED_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SEED_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
SIMILAR_X = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
SIMILAR_Y = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
SIMILAR_Z = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"


def test_musicbrainz_retries_when_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [0.0]
    urls: list[str] = []
    asked_at: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        asked_at.append(clock[0])
        if len(urls) < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"artists": [{"id": ARTIST, "name": "Found", "score": 100, "tags": [{"name": "rock", "count": 3}]}]})

    http.use_transport(httpx.MockTransport(handler))

    async def fake_sleep(seconds: float) -> None:
        clock[0] += seconds

    monkeypatch.setattr(musicbrainz, "spacer", musicbrainz.Spacer(1.1, clock=lambda: clock[0], sleep=fake_sleep))
    result = asyncio.run(musicbrainz.search_artists("AC/DC"))

    assert result[0]["mbid"] == ARTIST
    assert result[0]["tags"] == ["rock"]
    # 12.09.2026 gemessen: 2 von 8 Abrufen mit 503, direkt nacheinander, danach
    # wieder 200. Kurze Pausen reichen, lange liessen die Seite nur warten. Die
    # 1,1 Sekunden Abstand haelt der Spacer trotzdem ein.
    assert asked_at == pytest.approx([0.0, 1.1, 3.1])
    assert "AC\\/DC" in unquote(urls[0])


def test_spacer_keeps_the_distance() -> None:
    clock = [0.0]
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] += seconds

    spacer = musicbrainz.Spacer(1.1, clock=lambda: clock[0], sleep=fake_sleep)

    async def three_calls() -> None:
        for _ in range(3):
            await spacer.wait()

    asyncio.run(three_calls())
    assert sleeps == pytest.approx([1.1, 1.1])


def test_musicbrainz_gives_up_after_retries() -> None:
    http.use_transport(httpx.MockTransport(lambda _request: httpx.Response(503)))
    with pytest.raises(musicbrainz.MusicBrainzError) as caught:
        asyncio.run(musicbrainz.search_artists("anything"))
    assert caught.value.code == "musicbrainz_busy"


def test_similar_artists_are_asked_per_seed_without_duplicates() -> None:
    # 11.09.2026 gemessen: Mit drei Ausgangskuenstlern in einem Aufruf lieferte
    # ListenBrainz einem 152 Zeilen fuer 100 Kuenstler und einem anderen 57 von 100.
    # Auf der Startseite stand Metallica dreimal in einer Reihe.
    full = {
        # X zuerst mit dem besseren Score: Gewinnt die spaetere Zeile, faellt es auf.
        SEED_A: [(SIMILAR_X, "X", 50.0), (SIMILAR_Y, "Y", 70.0), (SIMILAR_X, "X", 40.0), (SEED_A, "A", 999.0)],
        SEED_B: [(SIMILAR_X, "X", 30.0), (SIMILAR_Z, "Z", 20.0)],
    }
    asked: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seeds = request.url.params.get_list("artist_mbids")
        asked.append(seeds)
        rows = [
            {"artist_mbid": mbid, "name": name, "score": score, "reference_mbid": seed}
            for seed in seeds
            for mbid, name, score in full[seed]
        ]
        if len(seeds) > 1:
            rows = rows[:2] * 2
        return httpx.Response(200, json=rows)

    http.use_transport(httpx.MockTransport(handler))
    with SessionLocal() as db:
        result = asyncio.run(catalog.similar_for(db, [SEED_A, SEED_B]))

    assert asked and all(len(seeds) == 1 for seeds in asked)
    assert [(item["mbid"], item["score"]) for item in result[SEED_A]] == [(SIMILAR_Y, 70.0), (SIMILAR_X, 50.0)]
    assert [item["mbid"] for item in result[SEED_B]] == [SIMILAR_X, SIMILAR_Z]


def test_sitewide_lists_have_each_entry_once() -> None:
    # 11.09.2026 gemessen: Die Wochenliste fuehrte zwei Alben je zweimal.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/release-groups"):
            return httpx.Response(
                200,
                json={
                    "payload": {
                        "release_groups": [
                            {"release_group_mbid": SIMILAR_X, "release_group_name": "Hit", "artist_mbids": [SEED_A], "listen_count": 90},
                            {"release_group_mbid": SIMILAR_X, "release_group_name": "Hit", "artist_mbids": [SEED_A], "listen_count": 80},
                            {"release_group_mbid": SIMILAR_Y, "release_group_name": "Other", "artist_mbids": [SEED_B], "listen_count": 70},
                        ]
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "payload": {
                    "artists": [
                        {"artist_mbid": SEED_A, "artist_name": "A", "listen_count": 9},
                        {"artist_mbid": SEED_A, "artist_name": "A", "listen_count": 8},
                    ]
                }
            },
        )

    http.use_transport(httpx.MockTransport(handler))

    async def both() -> tuple[list[dict], list[dict]]:
        return await listenbrainz.sitewide_release_groups(), await listenbrainz.sitewide_artists()

    albums, artists = asyncio.run(both())
    assert [(item["mbid"], item["listen_count"]) for item in albums] == [(SIMILAR_X, 90), (SIMILAR_Y, 70)]
    assert [item["mbid"] for item in artists] == [SEED_A]


def test_lidarr_image_ignores_local_paths() -> None:
    # 11.09.2026 gemessen: Lidarr traegt in remoteUrl auch lokale Pfade ein, etwa
    # /config/MediaCover/324/poster.jpg. Der Browser laedt die nie.
    images = [
        {"coverType": "poster", "url": "/MediaCover/7/poster.jpg", "remoteUrl": "/config/MediaCover/7/poster.jpg"},
        {"coverType": "fanart", "url": "/MediaCover/7/fanart.jpg", "remoteUrl": "https://images.example.com/fanart.jpg"},
    ]
    assert image_url(images, "poster", "fanart") == "https://images.example.com/fanart.jpg"
    assert image_url(images[:1], "poster", "fanart") == ""


def test_deezer_takes_only_exact_names() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": 1, "name": "Example Band Tribute", "nb_fan": 999_999, "picture_xl": "https://img.example.com/wrong.jpg"},
                    {"id": 27, "name": "Example Band", "nb_fan": 10, "picture_xl": "https://img.example.com/right.jpg"},
                ]
            },
        )

    http.use_transport(httpx.MockTransport(handler))
    assert asyncio.run(deezer.find_artist("example band"))["id"] == 27

    http.use_transport(httpx.MockTransport(lambda _r: httpx.Response(200, json={"data": [{"id": 1, "name": "Example Band Tribute"}]})))
    assert asyncio.run(deezer.find_artist("Example Band")) == {}


def test_deezer_error_in_a_200_answer_is_an_error() -> None:
    http.use_transport(httpx.MockTransport(lambda _r: httpx.Response(200, json={"error": {"code": 4, "message": "Quota"}})))
    with pytest.raises(deezer.DeezerError):
        asyncio.run(deezer.find_artist("Anyone"))


def test_deezer_calls_keep_a_distance(monkeypatch: pytest.MonkeyPatch) -> None:
    # 11.09.2026: Die Startseite loeste 15 Bildsuchen in 0,7 Sekunden aus, Deezer
    # antwortete darauf mit "Quota limit exceeded".
    clock = [0.0]
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(deezer, "spacer", musicbrainz.Spacer(0.15, clock=lambda: clock[0], sleep=fake_sleep))
    http.use_transport(httpx.MockTransport(lambda _r: httpx.Response(200, json={"data": []})))

    async def three_lookups() -> None:
        for name in ("A", "B", "C"):
            await deezer.find_artist(name)

    asyncio.run(three_lookups())
    assert sleeps == pytest.approx([0.15, 0.15])


@pytest.mark.parametrize(
    ("status", "code"),
    [(401, "lidarr_key_rejected"), (404, "lidarr_path_unknown"), (500, "lidarr_http_error")],
)
def test_lidarr_errors_are_named(status: int, code: str) -> None:
    http.use_transport(httpx.MockTransport(lambda _r: httpx.Response(status, text="boom")))
    with pytest.raises(LidarrError) as caught:
        asyncio.run(LidarrClient("http://lidarr.test", "key").system_status())
    assert caught.value.code == code
    assert caught.value.uncertain is False


def test_lidarr_timeout_is_uncertain() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    http.use_transport(httpx.MockTransport(slow))
    with pytest.raises(LidarrError) as caught:
        asyncio.run(LidarrClient("http://lidarr.test", "key").add_artist({}))
    assert (caught.value.code, caught.value.uncertain) == ("lidarr_timeout", True)


def test_lidarr_sends_the_key_and_uses_api_v1() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["key"] = request.headers["X-Api-Key"]
        return httpx.Response(200, json={"version": "3.1.0.0"})

    http.use_transport(httpx.MockTransport(handler))
    assert asyncio.run(LidarrClient("http://lidarr.test/", "secret-key").system_status())["version"] == "3.1.0.0"
    assert seen == {"path": "/api/v1/system/status", "key": "secret-key"}


def test_type_check_ignores_unknown_names() -> None:
    profile = {
        "primaryAlbumTypes": [{"albumType": {"name": "Album"}, "allowed": True}, {"albumType": {"name": "Single"}, "allowed": False}],
        "secondaryAlbumTypes": [{"albumType": {"name": "Studio"}, "allowed": True}, {"albumType": {"name": "Live"}, "allowed": False}],
    }
    assert type_allowed(profile, "Album", []) is True
    assert type_allowed(profile, "Single", []) is False
    assert type_allowed(profile, "Album", ["Live"]) is False
    assert type_allowed(profile, "Album", ["Field recording"]) is True
    assert type_allowed({}, "Single", ["Live"]) is True
