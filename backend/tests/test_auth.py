from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import RevokedSession, utcnow
from app.services import anmeldebremse, sitzung
from tests.conftest import ADMIN, USER_PASSWORD, auth_headers, create_user


def test_setup_creates_exactly_one_admin(client: TestClient) -> None:
    assert client.get("/api/setup/status").json() == {"needs_setup": True}
    first = client.post("/api/setup/admin", json=ADMIN)
    assert first.status_code == 201
    assert client.get("/api/setup/status").json() == {"needs_setup": False}

    second = client.post("/api/setup/admin", json={**ADMIN, "username": "other", "email": "other@example.com"})
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "setup_done"

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {first.json()['access_token']}"})
    assert me.json()["is_admin"] is True
    assert me.json()["quota"]["limit"] is None


def test_login_with_username_or_email(client: TestClient) -> None:
    create_user("lena")
    assert client.post("/api/auth/login", json={"login": "LENA", "password": USER_PASSWORD}).status_code == 200
    assert client.post("/api/auth/login", json={"login": "Lena@Example.com", "password": USER_PASSWORD}).status_code == 200

    wrong = client.post("/api/auth/login", json={"login": "lena", "password": "falsch-falsch"})
    assert wrong.status_code == 401
    assert wrong.json()["detail"]["code"] == "invalid_credentials"


def test_inactive_account_cannot_sign_in(client: TestClient) -> None:
    create_user("gesperrt", is_active=False)
    response = client.post("/api/auth/login", json={"login": "gesperrt", "password": USER_PASSWORD})
    assert response.status_code == 401


def test_refresh_and_logout_end_the_session_for_good(client: TestClient) -> None:
    create_user("lena")
    login = client.post("/api/auth/login", json={"login": "lena", "password": USER_PASSWORD})
    assert login.status_code == 200
    assert "nexbeat_refresh" in client.cookies
    copied = client.cookies["nexbeat_refresh"]

    refreshed = client.post("/api/auth/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]

    assert client.post("/api/auth/logout").status_code == 204
    assert client.post("/api/auth/refresh").status_code == 401

    # 12.09.2026: Ein vorher kopiertes Cookie bekam nach dem Abmelden weiter neue Zugaenge.
    assert client.post("/api/auth/refresh", headers={"Cookie": f"nexbeat_refresh={copied}"}).status_code == 401


def test_password_change_ends_other_sessions(client: TestClient) -> None:
    create_user("lena")
    other_session = auth_headers(client, "lena")
    this_session = auth_headers(client, "lena")

    changed = client.post(
        "/api/auth/me/password",
        json={"current_password": USER_PASSWORD, "new_password": "ganz-neues-passwort"},
        headers=this_session,
    )
    assert changed.status_code == 200

    assert client.get("/api/auth/me", headers=other_session).status_code == 401
    new_session = {"Authorization": f"Bearer {changed.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=new_session).status_code == 200


def test_brake_after_repeated_failures(client: TestClient) -> None:
    create_user("lena")
    for _ in range(4):
        assert client.post("/api/auth/login", json={"login": "lena", "password": "falsch-falsch"}).status_code == 401

    blocked = client.post("/api/auth/login", json={"login": "lena", "password": USER_PASSWORD})
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["code"] == "too_many_attempts"
    assert int(blocked.headers["Retry-After"]) >= 1


def test_brake_counts_one_account_whatever_the_login(client: TestClient) -> None:
    # 12.09.2026: Benutzername und E-Mail hatten getrennte Zaehler, das verdoppelte die Versuche.
    create_user("lena")
    for _ in range(4):
        client.post("/api/auth/login", json={"login": "lena", "password": "falsch-falsch"})

    via_email = client.post("/api/auth/login", json={"login": "lena@example.com", "password": USER_PASSWORD})
    assert via_email.status_code == 429


def test_brake_never_locks_an_account_for_long() -> None:
    # 12.09.2026: Ein Fehlversuch alle 15 Minuten hielt ein fremdes Konto dauerhaft gesperrt.
    for second in range(40):
        anmeldebremse.failed("account:1", now=float(second))
    assert anmeldebremse.wait_seconds("account:1", now=40.0) <= anmeldebremse.MAX_DELAY_SECONDS

    # Eine Stunde Ruhe, dann zaehlt es von vorn.
    anmeldebremse.failed("account:1", now=40.0 + anmeldebremse.FORGET_AFTER_SECONDS + 1)
    assert anmeldebremse.wait_seconds("account:1", now=40.0 + anmeldebremse.FORGET_AFTER_SECONDS + 2) == 0


def test_known_browser_signs_in_while_strangers_guess(client: TestClient) -> None:
    # 12.09.2026: Wer nur den Anmeldenamen kannte, hielt das Konto mit Fehlversuchen aus.
    create_user("lena")
    assert client.post("/api/auth/login", json={"login": "lena", "password": USER_PASSWORD}).status_code == 200

    stranger = TestClient(app)
    for _ in range(6):
        stranger.post("/api/auth/login", json={"login": "lena", "password": "falsch-falsch"})
    assert stranger.post("/api/auth/login", json={"login": "lena", "password": USER_PASSWORD}).status_code == 429
    assert client.post("/api/auth/login", json={"login": "lena", "password": USER_PASSWORD}).status_code == 200


def test_browser_known_to_another_account_counts_for_the_account(client: TestClient) -> None:
    create_user("lena")
    create_user("tom")
    assert client.post("/api/auth/login", json={"login": "tom", "password": USER_PASSWORD}).status_code == 200
    for _ in range(4):
        client.post("/api/auth/login", json={"login": "lena", "password": "falsch-falsch"})

    # Sonst holte sich ein Angreifer ueber das eigene Konto immer neue Zaehler fuer ein fremdes.
    elsewhere = TestClient(app)
    assert elsewhere.post("/api/auth/login", json={"login": "lena", "password": USER_PASSWORD}).status_code == 429


def test_purge_keeps_logouts_that_still_matter() -> None:
    with SessionLocal() as db:
        db.add(RevokedSession(session_id="expired", expires_at=utcnow() - timedelta(minutes=1)))
        db.add(RevokedSession(session_id="current", expires_at=utcnow() + timedelta(days=1)))
        db.commit()
        assert sitzung.purge_revoked(db) == 1
        assert [row.session_id for row in db.query(RevokedSession)] == ["current"]


def test_password_change_has_a_brake(client: TestClient) -> None:
    create_user("lena")
    headers = auth_headers(client, "lena")
    for _ in range(4):
        wrong = client.post(
            "/api/auth/me/password",
            json={"current_password": "falsch-falsch", "new_password": "ganz-neues-passwort"},
            headers=headers,
        )
        assert wrong.status_code == 400

    blocked = client.post(
        "/api/auth/me/password",
        json={"current_password": USER_PASSWORD, "new_password": "ganz-neues-passwort"},
        headers=headers,
    )
    assert blocked.status_code == 429


def test_reactivating_keeps_old_sessions_ended_for_every_account(admin_client: TestClient) -> None:
    # 12.09.2026: Konten ohne gespeicherten Passwortzeitpunkt behielten ihre alten Sitzungen.
    user_id = create_user("lena")
    old = auth_headers(admin_client, "lena")

    assert admin_client.patch(f"/api/users/{user_id}", json={"is_active": False}).status_code == 200
    assert admin_client.patch(f"/api/users/{user_id}", json={"is_active": True}).status_code == 200
    assert admin_client.get("/api/auth/me", headers=old).status_code == 401


def test_normal_user_cannot_reach_admin_routes(admin_client: TestClient) -> None:
    create_user("lena")
    headers = auth_headers(admin_client, "lena")
    response = admin_client.get("/api/users", headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "admins_only"
    assert admin_client.get("/api/settings", headers=headers).status_code == 403


def test_validation_errors_carry_a_code(client: TestClient) -> None:
    response = client.post("/api/setup/admin", json={**ADMIN, "password": "kurz"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_input"
    assert "password" in response.json()["detail"]["fields"]
