"""Nach Genre stoebern: Kuenstler aus der Tag-Suche, nach Hoerzahlen sortiert, Alben der Spitzenkuenstler.

12.09.2026 gemessen: Die Tag-Suche von MusicBrainz findet jeden, dem jemand den Tag je gegeben
hat. Nach Hoerzahlen sortiert fuehrten Lady Gaga und Madonna die Liste "jazz" an.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import LibraryArtist, MusicRequest, RequestStatus, User
from app.services import genres, http

JAZZ_STAR = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
POP_STAR = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
VOCALIST = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
DOWNVOTED = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
BRITISH_BAND = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
PLACEHOLDER = "ffffffff-ffff-4fff-8fff-ffffffffffff"
OTHER_ARTIST = "88888888-8888-4888-8888-888888888888"
VOCAL_HITS = "33333333-3333-4333-8333-333333333333"
SECOND_ALBUM = "44444444-4444-4444-8444-444444444444"
THIRD_ALBUM = "55555555-5555-4555-8555-555555555555"
GUEST_ALBUM = "66666666-6666-4666-8666-666666666666"
BIG_RECORD = "77777777-7777-4777-8777-777777777777"
VOCAL_EP = "99999999-9999-4999-8999-999999999999"
POP_RECORD = "abababab-abab-4bab-8bab-abababababab"


def _artist(mbid: str, name: str, votes: dict[str, int]) -> dict[str, Any]:
    return {"id": mbid, "name": name, "score": 100, "tags": [{"name": tag, "count": count} for tag, count in votes.items()]}


SEARCH = [
    _artist(genres.VARIOUS_ARTISTS, "Various Artists", {"jazz": 40}),
    _artist(POP_STAR, "Pop Star", {"pop": 30, "jazz": 1}),
    _artist(JAZZ_STAR, "Jazz Star", {"jazz": 10, "swing": 4}),
    # Nur Gegenstimmen. Die Suche findet die Band trotzdem.
    _artist(DOWNVOTED, "Downvoted Band", {"jazz": -2}),
    _artist(VOCALIST, "Vocalist", {"vocal jazz": 8, "pop": 4, "swing": 2}),
    _artist(BRITISH_BAND, "British Band", {"british": 50, "jazz": 6}),
    _artist(PLACEHOLDER, "[unknown]", {"jazz": 20}),
]
GENRE_NAMES = "jazz\npop\nrock\nswing\nvocal jazz\n"
LISTENS = {POP_STAR: 999, DOWNVOTED: 700, VOCALIST: 500, JAZZ_STAR: 100, BRITISH_BAND: 50}


def _top(mbid: str, title: str, listens: int, owner: str, kind: str = "Album") -> dict[str, Any]:
    return {
        "release_group_mbid": mbid,
        "release_group": {"name": title, "type": kind, "date": "2001"},
        "total_listen_count": listens,
        "artist": {"artists": [{"artist_mbid": owner, "name": "Someone"}]},
    }


TOP_GROUPS = {
    VOCALIST: [
        _top(GUEST_ALBUM, "Someone Else's Record", 900, OTHER_ARTIST),
        _top(VOCAL_EP, "Vocal EP", 800, VOCALIST, kind="EP"),
        _top(VOCAL_HITS, "Vocal Hits", 300, VOCALIST),
        _top(SECOND_ALBUM, "Second", 200, VOCALIST),
        _top(THIRD_ALBUM, "Third", 100, VOCALIST),
    ],
    BRITISH_BAND: [],
}
SITEWIDE = [
    {"release_group_mbid": POP_RECORD, "release_group_name": "Pop Record", "artist_mbids": [POP_STAR], "listen_count": 9999},
    {"release_group_mbid": BIG_RECORD, "release_group_name": "Big Record", "artist_mbids": [JAZZ_STAR], "listen_count": 5000},
    {"release_group_mbid": THIRD_ALBUM, "release_group_name": "Third", "artist_mbids": [VOCALIST], "listen_count": 150},
]


def _sources(
    calls: list[str],
    *,
    musicbrainz_status: int = 200,
    listenbrainz_status: int = 200,
    queries: list[str] | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        calls.append(f"{request.method} {host}{path}")
        if host == "musicbrainz.org" and path == "/ws/2/genre/all":
            assert request.url.params.get("fmt") == "txt"
            return httpx.Response(200, text=GENRE_NAMES)
        if host == "musicbrainz.org" and path == "/ws/2/artist":
            if queries is not None:
                queries.append(request.url.params.get("query", ""))
            if musicbrainz_status != 200:
                return httpx.Response(musicbrainz_status)
            return httpx.Response(200, json={"count": len(SEARCH), "artists": SEARCH})
        if host != "api.listenbrainz.org":
            raise AssertionError(f"Unexpected request: {request.method} {request.url}")
        if listenbrainz_status != 200:
            return httpx.Response(listenbrainz_status)
        if path == "/1/popularity/artist":
            asked = json.loads(request.content)["artist_mbids"]
            return httpx.Response(200, json=[{"artist_mbid": mbid, "total_listen_count": LISTENS.get(mbid, 0)} for mbid in asked])
        if path.startswith("/1/popularity/top-release-groups-for-artist/"):
            owner = path.rsplit("/", 1)[-1]
            if owner not in TOP_GROUPS:
                return httpx.Response(401, json={"code": 401, "error": "you need to provide an Auth token"})
            return httpx.Response(200, json=TOP_GROUPS[owner])
        if path == "/1/stats/sitewide/release-groups":
            rows = SITEWIDE if request.url.params.get("range") == "all_time" else []
            return httpx.Response(200, json={"payload": {"release_groups": rows}})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    return httpx.MockTransport(handler)


def test_genre_keeps_only_artists_who_carry_it_and_ranks_them_by_listens(admin_client: TestClient) -> None:
    # 12.09.2026 gemessen: Unter "jazz" standen Lady Gaga und Madonna vorn, mit einer Stimme fuer
    # Jazz gegen dreissig fuer Pop. Wer das Genre nur am Rand traegt, faellt heraus.
    with SessionLocal() as db:
        db.add(LibraryArtist(mbid=JAZZ_STAR, lidarr_id=1, name="Jazz Star"))
        db.commit()
    queries: list[str] = []
    http.use_transport(_sources([], queries=queries))

    response = admin_client.get("/api/genres/artists", params={"tag": "  Jazz "})
    assert response.status_code == 200, response.text
    body = response.json()
    assert queries == ['tag:"jazz"']
    assert [artist["name"] for artist in body["artists"]] == ["Vocalist", "Jazz Star", "British Band"]
    assert [artist["in_library"] for artist in body["artists"]] == [False, True, False]
    assert body["ranked"] is True
    # "british" ist kein Genre. Es zaehlt weder beim Anteil noch bei den verwandten Genres.
    assert body["related"] == ["swing"]


def test_genre_sources_are_cached(admin_client: TestClient) -> None:
    calls: list[str] = []
    http.use_transport(_sources(calls))
    first = admin_client.get("/api/genres/artists", params={"tag": "jazz"}).json()
    asked = list(calls)
    second = admin_client.get("/api/genres/artists", params={"tag": "JAZZ"}).json()
    assert first == second
    assert calls == asked
    assert len(asked) == 3


def test_without_listenbrainz_the_order_of_the_tag_search_stays(admin_client: TestClient) -> None:
    admin_client.put("/api/settings", json={"source_listenbrainz": False})
    calls: list[str] = []
    http.use_transport(_sources(calls))

    body = admin_client.get("/api/genres/artists", params={"tag": "jazz"}).json()
    assert [artist["name"] for artist in body["artists"]] == ["Jazz Star", "Vocalist", "British Band"]
    assert body["ranked"] is False
    assert [call for call in calls if "listenbrainz" in call] == []

    albums = admin_client.get("/api/genres/albums", params={"tag": "jazz"}).json()
    assert albums == {"available": False, "albums": []}


def test_failing_listenbrainz_leaves_the_artists_unranked(admin_client: TestClient) -> None:
    http.use_transport(_sources([], listenbrainz_status=502))
    response = admin_client.get("/api/genres/artists", params={"tag": "jazz"})
    assert response.status_code == 200, response.text
    assert response.json()["ranked"] is False
    assert [artist["name"] for artist in response.json()["artists"]] == ["Jazz Star", "Vocalist", "British Band"]


def test_busy_musicbrainz_is_reported_not_shown_as_an_empty_genre(admin_client: TestClient) -> None:
    http.use_transport(_sources([], musicbrainz_status=503))
    response = admin_client.get("/api/genres/artists", params={"tag": "jazz"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "musicbrainz_busy"

    # Nichts Leeres im Zwischenspeicher: Beim naechsten Versuch kommen die Kuenstler.
    http.use_transport(_sources([]))
    assert len(admin_client.get("/api/genres/artists", params={"tag": "jazz"}).json()["artists"]) == 3


@pytest.mark.parametrize("tag", ["", "   ", "x" * 61])
def test_invalid_genre_is_refused(admin_client: TestClient, tag: str) -> None:
    response = admin_client.get("/api/genres/artists", params={"tag": tag})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_genre"


def test_special_characters_in_a_genre_are_escaped(admin_client: TestClient) -> None:
    queries: list[str] = []
    http.use_transport(_sources([], queries=queries))
    admin_client.get("/api/genres/artists", params={"tag": "R&B"})
    assert queries == ['tag:"r\\&b"']


@pytest.mark.parametrize(
    ("genre", "tag", "expected"),
    [
        ("metal", "heavy metal", True),
        ("punk", "post-punk", True),
        ("hip hop", "east coast hip hop", True),
        ("pop", "k-pop", True),
        ("k-pop", "pop", False),
        ("electronic", "electronica", False),
        ("jazz", "jazz", True),
    ],
)
def test_what_counts_as_part_of_a_genre(genre: str, tag: str, expected: bool) -> None:
    assert genres.in_family(genre, tag) is expected


def test_genre_albums_come_from_the_top_artists_and_the_sitewide_list(admin_client: TestClient) -> None:
    # Die Albensuche nach Tag brachte am 12.09.2026 fast nur Unbekanntes. Die Alben kommen deshalb
    # von den Kuenstlern des Genres: ihre meistgehoerten und die aus der weltweiten Liste.
    with SessionLocal() as db:
        admin_id = db.scalar(select(User.id).where(User.username == "admin"))
        db.add(
            MusicRequest(
                user_id=admin_id,
                release_group_mbid=VOCAL_HITS,
                artist_mbid=VOCALIST,
                title="Vocal Hits",
                artist_name="Vocalist",
                status=RequestStatus.searching,
            )
        )
        db.commit()
    http.use_transport(_sources([]))

    response = admin_client.get("/api/genres/albums", params={"tag": "jazz"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["available"] is True
    # Jazz Star gibt ohne Schluessel nichts heraus (401), steht aber in der weltweiten Liste. Das
    # Gastalbum und die EP fallen heraus, Pop Star traegt das Genre nicht. "Third" waere das
    # dritte Album von Vocalist.
    assert [(album["title"], album["artist_name"]) for album in body["albums"]] == [
        ("Big Record", "Jazz Star"),
        ("Vocal Hits", "Vocalist"),
        ("Second", "Vocalist"),
    ]
    assert body["albums"][1]["request"]["status"] == "searching"
    assert body["albums"][2]["cover"] == f"https://coverartarchive.org/release-group/{SECOND_ALBUM}/front-250"


def test_genre_albums_report_when_listenbrainz_does_not_answer(admin_client: TestClient) -> None:
    http.use_transport(_sources([], listenbrainz_status=502))
    response = admin_client.get("/api/genres/albums", params={"tag": "jazz"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "listenbrainz_unavailable"
