from __future__ import annotations

from fastapi.testclient import TestClient

from app.crypto import decrypt
from app.db import SessionLocal
from app.models import Setting
from app.services import mail


def _stored(key: str) -> str:
    with SessionLocal() as session:
        row = session.get(Setting, key)
        return row.value if row else ""


def test_secret_is_encrypted_and_masked(admin_client: TestClient) -> None:
    response = admin_client.put("/api/settings", json={"smtp_password": "geheim-1234"})
    assert response.status_code == 200
    body = response.json()
    assert body["smtp_password"] == "••••1234"
    assert body["smtp_password_set"] is True

    raw = _stored("smtp_password")
    assert raw.startswith("enc:")
    assert "geheim" not in raw
    assert decrypt(raw) == "geheim-1234"


def test_masked_value_never_overwrites_the_secret(admin_client: TestClient) -> None:
    admin_client.put("/api/settings", json={"lidarr_api_key": "echter-schluessel-abcd"})
    admin_client.put("/api/settings", json={"lidarr_api_key": "••••abcd", "lidarr_url": "http://lidarr.example:8686/"})
    assert decrypt(_stored("lidarr_api_key")) == "echter-schluessel-abcd"
    assert admin_client.get("/api/settings").json()["lidarr_url"] == "http://lidarr.example:8686"


def test_unknown_and_invalid_settings_are_refused(admin_client: TestClient) -> None:
    unknown = admin_client.put("/api/settings", json={"gibt_es_nicht": "1"})
    assert unknown.status_code == 422
    assert unknown.json()["detail"] == {**unknown.json()["detail"], "code": "unknown_setting", "key": "gibt_es_nicht"}

    invalid = admin_client.put("/api/settings", json={"smtp_security": "tls"})
    assert invalid.json()["detail"]["code"] == "invalid_setting"

    # Das Webhook-Geheimnis schreibt nur der Server selbst.
    assert admin_client.put("/api/settings", json={"webhook_secret": "x"}).status_code == 422


def test_delete_secret(admin_client: TestClient) -> None:
    admin_client.put("/api/settings", json={"smtp_password": "geheim-1234"})
    response = admin_client.delete("/api/settings/secret/smtp_password")
    assert response.json()["smtp_password_set"] is False


def test_smtp_check_reports_a_code(admin_client: TestClient, monkeypatch) -> None:
    def refuse(_config: mail.MailConfig) -> None:
        raise mail.MailError("mail_login_failed", "535 authentication failed")

    monkeypatch.setattr(mail, "_check", refuse)
    response = admin_client.post("/api/settings/test/smtp", json={"host": "smtp.example.com", "username": "x", "password": "y"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "mail_login_failed"


def test_test_mail_goes_to_the_admin(admin_client: TestClient, mail_ready) -> None:
    response = admin_client.post("/api/settings/test-mail", json={})
    assert response.json() == {"sent": True}
    assert mail_ready[0]["To"] == "admin@example.com"
