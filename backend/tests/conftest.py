"""Gemeinsame Test-Vorbereitung.

⚠️ Die Umgebungsvariablen muessen stehen, bevor ``app`` importiert wird. Sonst
legt nexbeat seine echte Datenbank unter ``data/`` an statt im Testverzeichnis.

⚠️ Tests beruehren nie das Netz. ``no_network`` setzt unter jeden HTTP-Client
eine Attrappe, die bei jeder unerwarteten Anfrage laut scheitert.
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

_TMP_DIR = Path(tempfile.mkdtemp(prefix="nexbeat-tests-"))
os.environ["NEXBEAT_DATA_DIR"] = str(_TMP_DIR)
os.environ["NEXBEAT_SECRET_KEY"] = "test-secret-key-only-for-tests"
os.environ["NEXBEAT_DISABLE_BACKGROUND"] = "true"
# bcrypt mit 12 Runden kostet je Hash rund 0,3 s. Die Mechanik bleibt dieselbe.
os.environ["NEXBEAT_BCRYPT_ROUNDS"] = "4"
os.environ["NEXBEAT_FRONTEND_DIST"] = str(_TMP_DIR / "no-frontend")

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, User  # noqa: E402
from app.routers import onboarding  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services import anmeldebremse, deezer, http, lidarr, mail, musicbrainz  # noqa: E402
from tests.fakes import FakeLidarr  # noqa: E402

ADMIN = {"username": "admin", "email": "admin@example.com", "password": "admin-password-123", "language": "de"}
USER_PASSWORD = "user-password-123"

ARTIST = "22222222-2222-4222-8222-222222222222"
RELEASE_GROUP = "11111111-1111-4111-8111-111111111111"
OTHER_RELEASE_GROUP = "33333333-3333-4333-8333-333333333333"


@pytest.fixture(autouse=True)
def clean_db() -> Iterator[None]:
    init_db()
    with SessionLocal() as session:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(delete(table))
        session.commit()
    # Beide Zaehler leben im Arbeitsspeicher, die Schleife oben erreicht sie nicht.
    anmeldebremse.reset_all()
    onboarding.reset_limits()
    yield


@pytest.fixture(autouse=True)
def no_network() -> Iterator[None]:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Unexpected network access in a test: {request.method} {request.url}")

    async def no_sleep(_seconds: float) -> None:
        return None

    http.use_transport(httpx.MockTransport(refuse))
    spacers = (musicbrainz.spacer, deezer.spacer)
    # Ohne Abstand und ohne echte Pausen: Die Wiederholungen bei 503 warteten
    # sonst 12 Sekunden wirklich ab, und die ganze Reihe dauerte das Fuenfzehnfache.
    musicbrainz.spacer = musicbrainz.Spacer(0.0, sleep=no_sleep)
    deezer.spacer = musicbrainz.Spacer(0.0, sleep=no_sleep)
    yield
    musicbrainz.spacer, deezer.spacer = spacers
    http.use_transport(None)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin_client(client: TestClient) -> TestClient:
    response = client.post("/api/setup/admin", json=ADMIN)
    assert response.status_code == 201, response.text
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
    return client


def create_user(username: str, password: str = USER_PASSWORD, **extra: Any) -> int:
    """Konto direkt in der Datenbank. Der echte Weg ueber die Einladung steht in test_onboarding.py."""
    with SessionLocal() as session:
        user = User(
            username=username,
            email=f"{username}@example.com",
            password_hash=hash_password(password),
            display_name=username,
        )
        for field, value in extra.items():
            setattr(user, field, value)
        session.add(user)
        session.commit()
        return user.id


def auth_headers(client: TestClient, login: str, password: str = USER_PASSWORD) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"login": login, "password": password}, headers={"Authorization": ""})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def mailbox(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Faengt jede Mail ab, statt sie zu verschicken."""
    sent: list[Any] = []

    def fake_send(_config: mail.MailConfig, message: Any) -> None:
        sent.append(message)

    monkeypatch.setattr(mail, "_send", fake_send)
    monkeypatch.setattr(mail, "_check", lambda _config: None)
    return sent


@pytest.fixture
def mail_ready(admin_client: TestClient, mailbox: list[Any]) -> list[Any]:
    response = admin_client.put(
        "/api/settings",
        json={"smtp_host": "smtp.example.com", "smtp_from_address": "nexbeat@example.com"},
    )
    assert response.status_code == 200, response.text
    return mailbox


def link_from(message: Any, kind: str) -> str:
    """Den Einmal-Link aus einer abgefangenen Mail holen."""
    body = message.get_body(preferencelist=("plain",)).get_content()
    match = re.search(rf"/{kind}/([A-Za-z0-9_-]+)", body)
    assert match, body
    return match.group(1)


@pytest.fixture
def fake_lidarr(admin_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> FakeLidarr:
    """Eingerichtetes Lidarr, dahinter die Attrappe."""
    fake = FakeLidarr()
    response = admin_client.put(
        "/api/settings",
        json={
            "lidarr_url": "http://lidarr.test:8686",
            "lidarr_api_key": "test-lidarr-key",
            "lidarr_root_folder": "/music",
            "lidarr_quality_profile_id": 1,
            "lidarr_metadata_profile_id": 1,
        },
    )
    assert response.status_code == 200, response.text
    real = lidarr.client_for
    # Dieselbe Pruefung wie der echte Client (eingetragen und ARR-Modus), nur mit der Attrappe dahinter.
    monkeypatch.setattr(lidarr, "client_for", lambda settings: fake if real(settings) is not None else None)
    return fake


@pytest.fixture
def release_groups(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    """MusicBrainz-Antworten fuer Releases, veraenderbar je Test."""
    known: dict[str, dict[str, Any]] = {
        mbid: {
            "mbid": mbid,
            "title": f"Album {mbid[:4]}",
            "primary_type": "Album",
            "secondary_types": [],
            "first_release_date": "2024-05-01",
            "artist_mbid": ARTIST,
            "artist_name": "Test Artist",
            "releases": [],
        }
        for mbid in (RELEASE_GROUP, OTHER_RELEASE_GROUP)
    }

    async def fake_release_group(mbid: str) -> dict[str, Any]:
        if mbid not in known:
            raise musicbrainz.MusicBrainzError("musicbrainz_not_found")
        return dict(known[mbid])

    monkeypatch.setattr(musicbrainz, "release_group", fake_release_group)
    return known
