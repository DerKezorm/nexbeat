from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models import Role
from app.services import mail
from tests.conftest import auth_headers, create_user


def _user(admin_client: TestClient, user_id: int) -> dict:
    return next(user for user in admin_client.get("/api/users").json() if user["id"] == user_id)


def test_quota_modes_and_approval_flag(admin_client: TestClient) -> None:
    user_id = create_user("lena")
    assert _user(admin_client, user_id)["quota"]["limit"] == 10

    response = admin_client.patch(f"/api/users/{user_id}", json={"quota": 3, "requires_approval": True})
    assert response.status_code == 200
    assert response.json()["quota"]["limit"] == 3
    assert response.json()["requires_approval"] is True

    assert admin_client.patch(f"/api/users/{user_id}", json={"quota": "unlimited"}).json()["quota"]["limit"] is None
    assert admin_client.patch(f"/api/users/{user_id}", json={"quota": "default"}).json()["quota_limit"] is None

    too_high = admin_client.patch(f"/api/users/{user_id}", json={"quota": 10_001})
    assert too_high.status_code == 422
    assert too_high.json()["detail"]["code"] == "invalid_quota"


def test_last_admin_stays(admin_client: TestClient) -> None:
    admin_id = admin_client.get("/api/auth/me").json()["id"]
    demote = admin_client.patch(f"/api/users/{admin_id}", json={"role": "user"})
    assert demote.status_code == 409
    assert demote.json()["detail"]["code"] == "last_admin"
    assert admin_client.delete(f"/api/users/{admin_id}").json()["detail"]["code"] == "cannot_delete_self"


def test_deactivating_ends_sessions(admin_client: TestClient) -> None:
    user_id = create_user("lena")
    headers = auth_headers(admin_client, "lena")
    assert admin_client.get("/api/auth/me", headers=headers).status_code == 200
    assert admin_client.patch(f"/api/users/{user_id}", json={"is_active": False}).status_code == 200
    assert admin_client.get("/api/auth/me", headers=headers).status_code == 401


def test_delete_user(admin_client: TestClient) -> None:
    user_id = create_user("lena")
    assert admin_client.delete(f"/api/users/{user_id}").status_code == 204
    assert all(user["id"] != user_id for user in admin_client.get("/api/users").json())


@pytest.mark.parametrize("change", ["demote", "deactivate", "delete"])
def test_links_from_an_admin_who_loses_the_rights_stop_working(admin_client: TestClient, change: str) -> None:
    # 12.09.2026: Einladungen eines Admins galten weiter, nachdem er abgesetzt oder geloescht war.
    helper = create_user("helper", role=Role.admin)
    invited = admin_client.post(
        "/api/users/invitations",
        json={"email": "new@example.com", "role": "admin"},
        headers=auth_headers(admin_client, "helper"),
    )
    assert invited.status_code == 201, invited.text
    raw = invited.json()["delivery"]["manual_link"].rsplit("/", 1)[1]
    assert admin_client.get(f"/api/onboarding/invitation/{raw}").status_code == 200

    if change == "demote":
        assert admin_client.patch(f"/api/users/{helper}", json={"role": "user"}).status_code == 200
    elif change == "deactivate":
        assert admin_client.patch(f"/api/users/{helper}", json={"is_active": False}).status_code == 200
    else:
        assert admin_client.delete(f"/api/users/{helper}").status_code == 204
    assert admin_client.get(f"/api/onboarding/invitation/{raw}").status_code == 404


def test_password_link_for_another_admin_is_never_handed_out(admin_client: TestClient) -> None:
    # 12.09.2026: Ein Admin konnte sich einen Link fuer das Konto eines anderen Admins geben
    # lassen und es damit uebernehmen.
    helper = create_user("helper", role=Role.admin)
    refused = admin_client.post(f"/api/users/{helper}/password-reset")
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "admin_link_needs_mail"

    own = admin_client.get("/api/auth/me").json()["id"]
    assert admin_client.post(f"/api/users/{own}/password-reset").json()["manual_link"]


def test_password_link_for_another_admin_goes_by_mail(
    admin_client: TestClient, mail_ready: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = create_user("helper", role=Role.admin)
    sent = admin_client.post(f"/api/users/{helper}/password-reset").json()
    assert (sent["sent"], sent["manual_link"]) == (True, None)
    assert len(mail_ready) == 1

    def broken(_config: Any, _message: Any) -> None:
        raise mail.MailError("mail_rejected")

    monkeypatch.setattr(mail, "_send", broken)
    failed = admin_client.post(f"/api/users/{helper}/password-reset")
    assert failed.status_code == 502
    assert failed.json()["detail"]["code"] == "mail_rejected"
    assert "/passwort/" not in failed.text
