"""Kuenstler gleichen Namens: Foto und Top-Titel gehoeren dem, dessen Kennung es ist.

25.09.2026: Die Suche nach "logic" zeigte zwoelf verschiedene Kuenstler namens Logic mit demselben Foto. Auf der
Seite eines britischen Rappers standen Foto und Top-Titel des bekannten US-Rappers, weil nexbeat Deezer nur nach
dem Namen fragte und den mit den meisten Fans nahm. Gemessen am 26.09.2026: MusicBrainz fuehrt beim US-Rapper
einen Verweis auf seine Deezer-Seite (``free streaming``), beim britischen keinen, und die Rueckfrage nach der
Deezer-Adresse nennt genau den US-Rapper.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.services import http

pytestmark = pytest.mark.usefixtures("deezer_on")

FAMOUS = "77777777-7777-4777-8777-777777777777"
NAMESAKE = "66666666-6666-4666-8666-666666666666"
UNLINKED = "55555555-5555-4555-8555-555555555555"
NAME = "Example Name"

FAMOUS_DEEZER = 7
#: Hat auf Deezer mehr Fans, gehoert aber zu keinem der Kuenstler hier.
LOUDER_DEEZER = 9


def _sources(owners: dict[int, str] | None = None, *, louder: bool = False) -> tuple[httpx.MockTransport, list[str]]:
    owners = {FAMOUS_DEEZER: FAMOUS} if owners is None else owners
    seen: list[str] = []

    def artist(mbid: str, country: str, note: str, links: list[str]) -> dict[str, Any]:
        relations = [{"type": "free streaming", "url": {"resource": link}} for link in links]
        return {
            "id": mbid,
            "name": NAME,
            "type": "Person",
            "country": country,
            "disambiguation": note,
            "relations": relations,
        }

    artists = {
        FAMOUS: artist(FAMOUS, "US", "US rapper", ["https://www.deezer.com/artist/7", "https://example.com/famous"]),
        NAMESAKE: artist(NAMESAKE, "GB", "UK rapper", []),
        UNLINKED: artist(UNLINKED, "AU", "jazz band", []),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        host, path, params = request.url.host, request.url.path, request.url.params
        seen.append(f"{host}{path}")
        if host == "musicbrainz.org" and path.startswith("/ws/2/artist/"):
            return httpx.Response(200, json=artists[path.rsplit("/", 1)[-1]])
        if host == "musicbrainz.org" and path == "/ws/2/artist":
            found = [{key: value for key, value in row.items() if key != "relations"} for row in artists.values()]
            return httpx.Response(
                200, json={"artists": [*found, {"id": "44444444-4444-4444-8444-444444444444", "name": "Other"}]}
            )
        if host == "musicbrainz.org" and path == "/ws/2/url":
            deezer_id = int(params["resource"].rsplit("/", 1)[-1])
            if deezer_id not in owners:
                return httpx.Response(404, json={"error": "Not Found"})
            relation = {"type": "free streaming", "artist": {"id": owners[deezer_id], "name": NAME}}
            return httpx.Response(200, json={"resource": params["resource"], "relations": [relation]})
        if host == "api.deezer.com" and path == "/search/artist":
            rows = [
                {"id": FAMOUS_DEEZER, "name": NAME, "nb_fan": 500, "picture_xl": "https://img.example.com/famous.jpg"}
            ]
            if louder:
                rows.append(
                    {
                        "id": LOUDER_DEEZER,
                        "name": NAME,
                        "nb_fan": 900,
                        "picture_xl": "https://img.example.com/louder.jpg",
                    }
                )
            return httpx.Response(200, json={"data": rows})
        if host == "api.deezer.com" and path == f"/artist/{FAMOUS_DEEZER}":
            return httpx.Response(
                200,
                json={
                    "id": FAMOUS_DEEZER,
                    "name": NAME,
                    "nb_fan": 500,
                    "picture_xl": "https://img.example.com/famous.jpg",
                },
            )
        if host == "api.deezer.com" and path.endswith("/top"):
            deezer_id = path.split("/")[2]
            return httpx.Response(200, json={"data": [{"title": f"Hit of {deezer_id}", "preview": "", "album": {}}]})
        raise AssertionError(f"Unexpected request: {request.url}")

    return httpx.MockTransport(handler), seen


def _image(client: TestClient, path: str) -> str | None:
    response = client.get(path, follow_redirects=False)
    return response.headers["location"] if response.status_code == 302 else None


def _page(client: TestClient, mbid: str) -> tuple[str | None, list[str]]:
    """Kopf, Bild und Top-Titel, in der Reihenfolge der Seite."""
    head = client.get(f"/api/artists/{mbid}")
    assert head.status_code == 200, head.text
    artist = head.json()["artist"]
    tracks = client.get(f"/api/artists/{mbid}/top-tracks", params={"name": artist["name"]}).json()["tracks"]
    return _image(client, artist["image"]), [track["title"] for track in tracks]


def test_the_page_takes_photo_and_top_tracks_from_the_artists_own_deezer_link(admin_client: TestClient) -> None:
    transport, _seen = _sources(louder=True)
    http.use_transport(transport)
    # Deezer nennt unter diesem Namen einen mit mehr Fans. Es zaehlt der Verweis in MusicBrainz.
    assert _page(admin_client, FAMOUS) == ("https://img.example.com/famous.jpg", [f"Hit of {FAMOUS_DEEZER}"])


def test_a_namesake_does_not_get_the_photo_and_top_tracks_of_the_famous_one(admin_client: TestClient) -> None:
    transport, seen = _sources()
    http.use_transport(transport)
    assert _page(admin_client, NAMESAKE) == (None, [])
    # Ohne eigenen Verweis fragt nexbeat Deezer nach dem Namen und MusicBrainz, wem der Treffer gehoert: einmal.
    assert seen.count("musicbrainz.org/ws/2/url") == 1


def test_an_artist_without_link_keeps_a_name_match_nobody_else_owns(admin_client: TestClient) -> None:
    transport, _seen = _sources(owners={})
    http.use_transport(transport)
    assert _page(admin_client, UNLINKED) == ("https://img.example.com/famous.jpg", [f"Hit of {FAMOUS_DEEZER}"])


def test_search_marks_namesakes_and_gives_only_the_owner_the_photo(admin_client: TestClient) -> None:
    transport, seen = _sources()
    http.use_transport(transport)
    found = admin_client.get("/api/search/artists", params={"q": "example"}).json()
    by_mbid = {item["mbid"]: item for item in found}
    assert [by_mbid[mbid]["namesakes"] for mbid in (FAMOUS, NAMESAKE, UNLINKED)] == [True, True, True]
    assert by_mbid["44444444-4444-4444-8444-444444444444"]["namesakes"] is False
    assert (by_mbid[NAMESAKE]["country"], by_mbid[NAMESAKE]["disambiguation"]) == ("GB", "UK rapper")

    # Die Karten der Suche fragen MusicBrainz nicht je Kuenstler, sondern einmal, wem der Deezer-Treffer gehoert.
    images = {mbid: _image(admin_client, by_mbid[mbid]["image"]) for mbid in (FAMOUS, NAMESAKE, UNLINKED)}
    assert images == {FAMOUS: "https://img.example.com/famous.jpg", NAMESAKE: None, UNLINKED: None}
    assert seen.count("musicbrainz.org/ws/2/url") == 1
    assert not any(path.startswith("musicbrainz.org/ws/2/artist/") for path in seen)
