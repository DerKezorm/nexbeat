from __future__ import annotations

import asyncio
from datetime import timedelta
import os
import shutil
import time
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import MusicRequest
from app.services import covers, http
from tests.conftest import ARTIST, RELEASE_GROUP

RELEASE = "45454545-4545-4545-8545-454545454545"
JPEG = b"\xff\xd8\xff\xe0" + b"cover" * 50
PNG = b"\x89PNG\r\n\x1a\n" + b"cover" * 50


@pytest.fixture(autouse=True)
def empty_cover_store() -> Iterator[None]:
    # Die Datenbank leert ``clean_db`` je Test, die Cover auf der Platte nicht.
    shutil.rmtree(covers.directory(), ignore_errors=True)
    yield
    shutil.rmtree(covers.directory(), ignore_errors=True)


def _archive(asked: list[httpx.Request], status: int = 200, body: bytes = JPEG, kind: str = "image/jpeg") -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        return httpx.Response(status, content=body, headers={"content-type": kind})

    http.use_transport(httpx.MockTransport(handler))


def test_only_addresses_nexbeat_gives_out_are_served() -> None:
    group = f"https://coverartarchive.org/release-group/{RELEASE_GROUP}/front-250"
    release = f"https://coverartarchive.org/release/{RELEASE}/77-500.jpg"
    assert covers.served(group) == f"/api/images/cover/release-group/{RELEASE_GROUP}/front-250"
    assert covers.served(release) == f"/api/images/cover/release/{RELEASE}/77-500.jpg"
    for other in (
        "",
        "https://cdn-images.dzcdn.net/images/cover/abc/250x250.jpg",
        f"https://coverartarchive.org/release-group/{RELEASE_GROUP}/front-1200",
        f"https://coverartarchive.org/release-group/{RELEASE_GROUP}/front",
        f"http://coverartarchive.org/release-group/{RELEASE_GROUP}/front-250",
        f"https://coverartarchive.org/artist/{RELEASE_GROUP}/front-250",
        f"https://coverartarchive.org/release-group/{RELEASE_GROUP}/front-250?x=1",
    ):
        assert covers.served(other) == other


def test_a_cover_is_fetched_once_and_then_comes_from_disk(client: TestClient) -> None:
    asked: list[httpx.Request] = []
    _archive(asked)
    address = f"/api/images/cover/release-group/{RELEASE_GROUP}/front-250"

    first = client.get(address)
    assert first.status_code == 200
    assert first.content == JPEG
    assert first.headers["content-type"] == "image/jpeg"
    assert first.headers["cache-control"] == f"public, max-age={covers.BROWSER_MAX_AGE}"
    assert [str(request.url) for request in asked] == [
        f"https://coverartarchive.org/release-group/{RELEASE_GROUP}/front-250"
    ]

    _archive(asked, status=500)
    second = client.get(address)
    assert second.status_code == 200
    assert second.content == JPEG
    assert len(asked) == 1


def test_a_png_cover_is_served_as_png(client: TestClient) -> None:
    _archive([], body=PNG, kind="image/png")
    response = client.get(f"/api/images/cover/release/{RELEASE}/77-250.jpg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


def test_a_missing_cover_is_remembered(client: TestClient) -> None:
    asked: list[httpx.Request] = []
    _archive(asked, status=404, body=b"not found", kind="text/plain")
    address = f"/api/images/cover/release-group/{RELEASE_GROUP}/front-500"
    assert client.get(address).status_code == 404
    assert client.get(address).status_code == 404
    assert len(asked) == 1


def test_a_missing_cover_is_asked_for_again_the_same_day(client: TestClient) -> None:
    """New albums get their cover in the archive days after release; "missing" must not stick for a week."""
    asked: list[httpx.Request] = []
    _archive(asked, status=404, body=b"not found", kind="text/plain")
    address = f"/api/images/cover/release-group/{RELEASE_GROUP}/front-250"
    first = client.get(address)
    assert first.status_code == 404
    assert first.headers["cache-control"] == "public, max-age=3600"
    assert covers.TTL_MISSING <= timedelta(hours=6)
    # Six hours later the archive has it: nexbeat asks again and keeps it.
    from app.models import CacheEntry
    with SessionLocal() as db:
        for row in db.query(CacheEntry).all():
            row.expires_at = row.expires_at - covers.TTL_MISSING
        db.commit()
    _archive(asked, status=200, body=JPEG, kind="image/jpeg")
    assert client.get(address).status_code == 200
    assert len(asked) == 2


def test_an_unreachable_archive_sends_the_browser_there_and_keeps_nothing(client: TestClient) -> None:
    asked: list[httpx.Request] = []
    _archive(asked, status=503, body=b"busy", kind="text/plain")
    address = f"/api/images/cover/release-group/{RELEASE_GROUP}/front-250"
    response = client.get(address, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == f"https://coverartarchive.org/release-group/{RELEASE_GROUP}/front-250"
    assert response.headers["cache-control"] == "no-store"

    # Eine Seite statt eines Bildes zaehlt auch nicht als Cover.
    _archive(asked, status=200, body=b"<html>", kind="text/html")
    assert client.get(address, follow_redirects=False).status_code == 302
    _archive(asked)
    assert client.get(address).status_code == 200
    assert len(asked) == 3


def test_nothing_else_reaches_the_archive(client: TestClient) -> None:
    # ``no_network`` laesst jede Anfrage scheitern: Keine dieser Adressen darf eine ausloesen.
    for address in (
        f"/api/images/cover/release-group/{RELEASE_GROUP}/front-1200",
        f"/api/images/cover/release-group/{RELEASE_GROUP}/back-250",
        f"/api/images/cover/release/{RELEASE}/77-250.png",
        f"/api/images/cover/artist/{RELEASE_GROUP}/front-250",
        "/api/images/cover/release-group/not-an-mbid/front-250",
        "/api/images/cover/release-group/ABABABAB-ABAB-4BAB-8BAB-ABABABABABAB/front-250",
        f"/api/images/cover/release-group/{RELEASE_GROUP}/..%2F..%2Fsecret.key",
    ):
        assert client.get(address).status_code == 404, address


def test_two_requests_for_the_same_cover_fetch_it_once() -> None:
    asked: list[httpx.Request] = []
    _archive(asked)
    cover = covers.parse("release-group", RELEASE_GROUP, "front-250")
    assert cover is not None

    async def both() -> list[object]:
        with SessionLocal() as one, SessionLocal() as two:
            return list(await asyncio.gather(covers.obtain(one, cover), covers.obtain(two, cover)))

    first, second = asyncio.run(both())
    assert first == second == covers.path_for(cover)
    assert len(asked) == 1


def test_covers_nobody_asked_for_in_a_long_time_are_removed() -> None:
    old = covers.parse("release-group", RELEASE_GROUP, "front-250")
    recent = covers.parse("release-group", RELEASE_GROUP, "front-500")
    assert old is not None and recent is not None
    for cover in (old, recent):
        path = covers.path_for(cover)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(JPEG)
    stale_part = covers.path_for(recent).with_name("x.img.1.part")
    stale_part.write_bytes(b"half")
    fresh_part = covers.path_for(recent).with_name("y.img.1.part")
    fresh_part.write_bytes(b"half")
    now = time.time()
    long_ago = now - covers.KEEP_UNUSED.total_seconds() - 60
    os.utime(covers.path_for(old), (long_ago, long_ago))
    os.utime(stale_part, (now - 7200, now - 7200))

    assert covers.purge_unused(now) == 2
    assert not covers.path_for(old).exists()
    assert not stale_part.exists()
    assert covers.path_for(recent).exists()
    assert fresh_part.exists()


def test_request_lists_show_covers_through_nexbeat(admin_client: TestClient) -> None:
    stored = f"https://coverartarchive.org/release-group/{RELEASE_GROUP}/front-500"
    with SessionLocal() as db:
        request = MusicRequest(
            user_id=1,
            release_group_mbid=RELEASE_GROUP,
            artist_mbid=ARTIST,
            artist_name="Test Artist",
            title="Album",
            cover_url=stored,
        )
        db.add(request)
        db.commit()
    body = admin_client.get("/api/requests/mine").json()
    items = body["items"] if isinstance(body, dict) else body
    assert items[0]["cover_url"] == f"/api/images/cover/release-group/{RELEASE_GROUP}/front-500"
