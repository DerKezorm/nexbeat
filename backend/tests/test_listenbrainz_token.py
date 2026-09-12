"""Der ListenBrainz-Schluessel: verschluesselt gespeichert, an die API geschickt, pruefbar.

12.09.2026 gemessen: Die Beliebtheit einzelner Kuenstler verlangt teils ein Token.
``/1/validate-token`` antwortet ohne Token mit 400 und mit falschem Token mit 200 und
``valid: false``. Ein falsches Token bei der Beliebtheit gibt dieselbe 401 wie keins.
"""

from __future__ import annotations

import asyncio

import httpx
from fastapi.testclient import TestClient

from app.crypto import decrypt
from app.db import SessionLocal
from app.models import Setting
from app.services import http, recommendations
from app.services.settings_service import load_settings
from tests.conftest import ARTIST

TOKEN = "lb-token-for-tests"
ALBUM = "88888888-8888-4888-8888-888888888888"


def _listenbrainz(seen: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        authorization = request.headers.get("Authorization", "")
        seen.append(f"{request.url.path} {authorization}")
        if request.url.path.endswith("/validate-token"):
            if authorization == f"Token {TOKEN}":
                return httpx.Response(200, json={"code": 200, "message": "Token valid.", "valid": True, "user_name": "tester"})
            return httpx.Response(200, json={"code": 200, "message": "Token invalid.", "valid": False})
        if authorization != f"Token {TOKEN}":
            return httpx.Response(401, json={"code": 401, "error": "you need to provide an Auth token"})
        if "top-release-groups-for-artist" in request.url.path:
            item = {"release_group_mbid": ALBUM, "release_group": {"name": "Record", "type": "Album"}, "total_listen_count": 5}
            return httpx.Response(200, json=[item])
        if request.url.path.endswith("/release-groups"):
            return httpx.Response(200, json={"payload": {"release_groups": []}})
        return httpx.Response(200, json={"payload": {"artists": []}})

    return httpx.MockTransport(handler)


def test_token_is_kept_secret_and_sent_to_listenbrainz(admin_client: TestClient) -> None:
    saved = admin_client.put("/api/settings", json={"listenbrainz_token": TOKEN})
    assert saved.status_code == 200, saved.text
    assert (saved.json()["listenbrainz_token"], saved.json()["listenbrainz_token_set"]) == ("••••ests", True)
    with SessionLocal() as session:
        raw = session.get(Setting, "listenbrainz_token").value
    assert raw.startswith("enc:")
    assert decrypt(raw) == TOKEN

    seen: list[str] = []
    http.use_transport(_listenbrainz(seen))
    popular = admin_client.get(f"/api/artists/{ARTIST}/popular")
    assert popular.status_code == 200, popular.text
    assert [album["mbid"] for album in popular.json()["albums"]] == [ALBUM]

    with SessionLocal() as db:
        asyncio.run(recommendations.trending(db, load_settings(db)))
    assert len(seen) == 3
    assert all(entry.endswith(f"Token {TOKEN}") for entry in seen), seen


def test_rejected_token_is_named(admin_client: TestClient) -> None:
    admin_client.put("/api/settings", json={"listenbrainz_token": "wrong-token"})
    http.use_transport(_listenbrainz([]))

    response = admin_client.get(f"/api/artists/{ARTIST}/popular")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "listenbrainz_token_rejected"


def test_token_check_uses_the_typed_or_the_saved_token(admin_client: TestClient) -> None:
    http.use_transport(_listenbrainz([]))
    missing = admin_client.post("/api/settings/test/listenbrainz", json={})
    assert missing.status_code == 422
    assert missing.json()["detail"]["code"] == "listenbrainz_token_missing"

    assert admin_client.post("/api/settings/test/listenbrainz", json={"token": TOKEN}).json() == {"ok": True, "user_name": "tester"}
    wrong = admin_client.post("/api/settings/test/listenbrainz", json={"token": "wrong-token"})
    assert wrong.status_code == 400
    assert wrong.json()["detail"]["code"] == "listenbrainz_token_rejected"

    admin_client.put("/api/settings", json={"listenbrainz_token": TOKEN})
    masked = admin_client.post("/api/settings/test/listenbrainz", json={"token": "••••ests"})
    assert masked.json() == {"ok": True, "user_name": "tester"}
