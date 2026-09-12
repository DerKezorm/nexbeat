from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import AuthToken, utcnow
from tests.conftest import USER_PASSWORD, auth_headers, create_user, link_from


def test_invitation_by_mail_can_be_used_once(admin_client: TestClient, mail_ready: list[Any]) -> None:
    created = admin_client.post("/api/users/invitations", json={"email": "Neu@Example.com"})
    assert created.status_code == 201, created.text
    assert created.json()["delivery"] == {"sent": True, "manual_link": None, "error_code": None}
    assert len(mail_ready) == 1
    assert mail_ready[0]["To"] == "neu@example.com"

    raw = link_from(mail_ready[0], "einladung")
    info = admin_client.get(f"/api/onboarding/invitation/{raw}")
    assert info.json() == {"email": "neu@example.com", "role": "user"}

    accepted = admin_client.post(f"/api/onboarding/invitation/{raw}", json={"username": "neu", "password": "neues-passwort"})
    assert accepted.status_code == 201
    assert auth_headers(admin_client, "neu", "neues-passwort")

    again = admin_client.post(f"/api/onboarding/invitation/{raw}", json={"username": "neu2", "password": "neues-passwort"})
    assert again.status_code == 404
    assert again.json()["detail"]["code"] == "invitation_invalid"


def test_invitation_without_mail_server_returns_link(admin_client: TestClient) -> None:
    created = admin_client.post("/api/users/invitations", json={"email": "neu@example.com"}, headers={"Origin": "http://localhost:5180"})
    delivery = created.json()["delivery"]
    assert delivery["sent"] is False
    assert delivery["error_code"] == "mail_not_configured"
    assert delivery["manual_link"].startswith("http://localhost:5180/einladung/")

    raw = delivery["manual_link"].rsplit("/", 1)[1]
    assert admin_client.post(f"/api/onboarding/invitation/{raw}", json={"username": "neu", "password": "neues-passwort"}).status_code == 201


def test_expired_invitation_is_rejected(admin_client: TestClient) -> None:
    delivery = admin_client.post("/api/users/invitations", json={"email": "neu@example.com"}).json()["delivery"]
    raw = delivery["manual_link"].rsplit("/", 1)[1]
    with SessionLocal() as session:
        token = session.scalars(select(AuthToken)).one()
        token.expires_at = utcnow() - timedelta(minutes=1)
        session.commit()
    assert admin_client.get(f"/api/onboarding/invitation/{raw}").status_code == 404


def test_withdrawn_invitation_cannot_be_used(admin_client: TestClient) -> None:
    created = admin_client.post("/api/users/invitations", json={"email": "neu@example.com"}).json()
    raw = created["delivery"]["manual_link"].rsplit("/", 1)[1]
    assert admin_client.delete(f"/api/users/invitations/{created['invitation']['id']}").status_code == 204
    assert admin_client.get(f"/api/onboarding/invitation/{raw}").status_code == 404
    assert admin_client.get("/api/users/invitations").json() == []


def test_invitation_for_existing_address_is_refused(admin_client: TestClient) -> None:
    create_user("lena")
    response = admin_client.post("/api/users/invitations", json={"email": "lena@example.com"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "email_taken"


def test_forgot_password_answers_the_same_and_resets(admin_client: TestClient, mail_ready: list[Any]) -> None:
    create_user("lena")
    unknown = admin_client.post("/api/onboarding/forgot-password", json={"email": "niemand@example.com"})
    known = admin_client.post("/api/onboarding/forgot-password", json={"email": "lena@example.com"})
    assert unknown.status_code == known.status_code == 202
    assert unknown.json() == known.json()
    assert len(mail_ready) == 1

    old_session = auth_headers(admin_client, "lena")
    raw = link_from(mail_ready[0], "passwort")
    assert admin_client.get(f"/api/onboarding/password/{raw}").status_code == 200
    assert admin_client.post(f"/api/onboarding/password/{raw}", json={"password": "anderes-passwort"}).status_code == 204

    assert admin_client.get("/api/auth/me", headers=old_session).status_code == 401
    assert admin_client.post("/api/auth/login", json={"login": "lena", "password": USER_PASSWORD}).status_code == 401
    assert auth_headers(admin_client, "lena", "anderes-passwort")
    assert admin_client.post(f"/api/onboarding/password/{raw}", json={"password": "noch-ein-passwort"}).status_code == 404


def test_forgot_password_is_limited_per_address(admin_client: TestClient, mail_ready: list[Any]) -> None:
    create_user("lena")
    for _ in range(8):
        admin_client.post("/api/onboarding/forgot-password", json={"email": "lena@example.com"})
    assert len(mail_ready) == 5


def test_admin_can_hand_out_a_password_link(admin_client: TestClient) -> None:
    user_id = create_user("lena")
    delivery = admin_client.post(f"/api/users/{user_id}/password-reset").json()
    assert delivery["sent"] is False
    assert "/passwort/" in delivery["manual_link"]
