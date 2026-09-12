from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services import poller
from tests.fakes import FakeLidarr


def test_webhook_needs_the_secret_and_only_wakes(admin_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    woken: list[bool] = []
    monkeypatch.setattr(poller, "wake", lambda: woken.append(True))
    info = admin_client.get("/api/settings/webhook").json()
    assert info["username"] == "nexbeat"
    assert len(info["password"]) >= 24

    wrong = admin_client.post("/api/webhooks/lidarr", json={"eventType": "Download"}, auth=("nexbeat", "falsch"))
    assert wrong.status_code == 401
    assert wrong.json()["detail"]["code"] == "webhook_rejected"
    assert woken == []

    right = admin_client.post("/api/webhooks/lidarr", json={"eventType": "Download"}, auth=(info["username"], info["password"]))
    assert right.status_code == 204
    assert woken == [True]


def test_webhook_secret_stays_the_same(admin_client: TestClient) -> None:
    first = admin_client.get("/api/settings/webhook").json()["password"]
    assert admin_client.get("/api/settings/webhook").json()["password"] == first
    assert "webhook_secret" not in admin_client.get("/api/settings").json()


def test_lidarr_options_come_from_lidarr(admin_client: TestClient, fake_lidarr: FakeLidarr) -> None:
    options = admin_client.get("/api/settings/lidarr/options").json()
    assert options["root_folders"][0]["path"] == "/music"
    assert options["quality_profiles"] == [{"id": 1, "name": "Lossless"}]
