"""Die Seite "Ueber nexbeat", die Update-Pruefung und die zuletzt gesehene Fassung fuer "Was ist neu"."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.services import http, updates
from tests.conftest import auth_headers, create_user

GITHUB = "api.github.com"


@pytest.fixture
def github() -> Iterator[dict[str, object]]:
    """GitHub antwortet mit ``state["tag"]``; ``state["calls"]`` zaehlt die Anfragen."""
    state: dict[str, object] = {"tag": "v99.0.0", "calls": 0, "status": 200}
    updates.reset()

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host != GITHUB:
            raise AssertionError(f"Unexpected network access in a test: {request.method} {request.url}")
        state["calls"] = int(state["calls"]) + 1  # type: ignore[call-overload]
        return httpx.Response(int(state["status"]), json={"tag_name": state["tag"]})  # type: ignore[call-overload]

    http.use_transport(httpx.MockTransport(handle))
    yield state
    updates.reset()


def test_a_user_sees_version_and_origin_but_no_update_state(admin_client: TestClient, github) -> None:
    create_user("lena")
    body = admin_client.get("/api/about", headers=auth_headers(admin_client, "lena")).json()
    assert body["version"] == __version__
    assert body["repo_url"] == "https://github.com/DerKezorm/nexbeat"
    assert body["update"] is None
    assert github["calls"] == 0


def test_an_admin_sees_a_newer_version_once_a_day(admin_client: TestClient, github) -> None:
    first = admin_client.get("/api/about").json()["update"]
    assert (first["enabled"], first["latest"], first["available"]) == (True, "v99.0.0", True)
    admin_client.get("/api/about")
    assert github["calls"] == 1
    # "Jetzt nachsehen" fragt trotzdem.
    admin_client.post("/api/about/check")
    assert github["calls"] == 2
    assert admin_client.get("/api/auth/me").json()["update_available"] is True


def test_the_same_or_an_older_version_is_no_update(admin_client: TestClient, github) -> None:
    github["tag"] = f"v{__version__}"
    assert admin_client.get("/api/about").json()["update"]["available"] is False
    assert admin_client.get("/api/auth/me").json()["update_available"] is False


def test_switched_off_nothing_goes_out(admin_client: TestClient, github) -> None:
    admin_client.put("/api/settings", json={"update_check": False})
    body = admin_client.get("/api/about").json()
    assert body["update"]["enabled"] is False
    assert admin_client.post("/api/about/check").json()["update"]["latest"] is None
    assert github["calls"] == 0


def test_a_failing_github_breaks_nothing_and_is_asked_again_later(admin_client: TestClient, github) -> None:
    github["status"] = 503
    assert admin_client.get("/api/about").json()["update"]["available"] is False
    admin_client.get("/api/about")
    # Nicht bei jedem Seitenaufruf noch einmal; erst nach der Wartezeit oder auf Knopfdruck.
    assert github["calls"] == 1


def test_only_admins_ask_now(admin_client: TestClient, github) -> None:
    create_user("lena")
    assert admin_client.post("/api/about/check", headers=auth_headers(admin_client, "lena")).status_code == 403


@pytest.mark.parametrize(
    ("latest", "current", "newer"),
    [
        ("v1.1.0", "1.0.0", True),
        ("1.0.0", "1.0.0", False),
        ("v0.9.9", "1.0.0", False),
        ("garbage", "1.0.0", False),
        ("v2.0.0-beta", "1.9.9", True),
    ],
)
def test_versions_compare_by_their_numbers(latest: str, current: str, newer: bool) -> None:
    assert updates.is_newer(latest, current) is newer


def test_the_seen_version_is_stored_and_checked(admin_client: TestClient) -> None:
    assert admin_client.patch("/api/auth/me", json={"seen_version": "1.1.0"}).json()["seen_version"] == "1.1.0"
    assert admin_client.patch("/api/auth/me", json={"seen_version": "<script>"}).status_code == 422


def test_a_new_account_starts_with_the_running_version(admin_client: TestClient) -> None:
    # Ein neues Konto soll nicht als Erstes lesen, was sich vor seiner Zeit geaendert hat.
    assert admin_client.get("/api/auth/me").json()["seen_version"] == __version__


def test_an_account_from_before_has_seen_nothing(admin_client: TestClient) -> None:
    create_user("lena")
    assert admin_client.get("/api/auth/me", headers=auth_headers(admin_client, "lena")).json()["seen_version"] is None


def test_the_background_check_fills_the_menu_hint(admin_client: TestClient, github) -> None:
    asyncio.run(updates.status(enabled=True))
    assert admin_client.get("/api/auth/me").json()["update_available"] is True


def test_a_user_gets_no_update_hint(admin_client: TestClient, github) -> None:
    asyncio.run(updates.status(enabled=True))
    create_user("lena")
    assert (
        admin_client.get("/api/auth/me", headers=auth_headers(admin_client, "lena")).json()["update_available"] is False
    )
