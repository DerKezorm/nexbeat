"""Der authentik-Knopf gegen ein nachgestelltes authentik (API v3), und der Blueprint.

Uebernommen aus nexdeck. Die Attrappe beantwortet die Aufrufe in der Reihenfolge des Dienstes und merkt sich
jede Anfrage: So pruefen die Tests, dass der Token nur im Authorization-Kopf reist, dass der Lauf beim ersten
Fehler stehen bleibt und dass ein vorhandener Provider aktualisiert statt verdoppelt wird. Kein Netz.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.crypto import decrypt
from app.db import SessionLocal
from app.main import app
from app.models import OidcLink, OidcProvider, Role, User
from app.services import authentik_setup, oidc
from tests.conftest import auth_headers, create_user

URL = "https://auth.example.com"
TOKEN = "one-time-token-that-must-stay-out-of-everything"
ISSUER = f"{URL}/application/o/nexbeat/"
PUBLIC = "https://music.example.com"
REDIRECT = f"{PUBLIC}/api/auth/oidc/authentik/callback"


@dataclass
class Recorded:
    method: str
    path: str
    query: dict[str, str]
    auth: str
    body: dict | None


@dataclass
class FakeAuthentik:
    """authentik as a MockTransport handler. ``existing`` says which objects are already there."""

    existing: set[str] = field(default_factory=set)
    fail: tuple[str, str, int] | None = None
    discovery_ok: bool = True
    provider_redirect: str = ""
    calls: list[Recorded] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host != "auth.example.com":
            raise httpx.ConnectError("no such host")
        method, path = request.method, request.url.path
        query = dict(request.url.params.items())
        body = json.loads(request.content) if request.content else None
        self.calls.append(Recorded(method, path, query, request.headers.get("authorization", ""), body))
        if self.fail and (method, path) == self.fail[:2]:
            return httpx.Response(self.fail[2], text="<html>authentik error page with secrets of its own</html>")
        if path.endswith("/.well-known/openid-configuration"):
            if not self.discovery_ok:
                return httpx.Response(404, text="not found")
            issuer = path.removesuffix(".well-known/openid-configuration")
            return httpx.Response(
                200,
                json={
                    "issuer": f"{URL}{issuer}",
                    "authorization_endpoint": f"{URL}{issuer}authorize/",
                    "token_endpoint": f"{URL}/application/o/token/",
                    "jwks_uri": f"{URL}{issuer}jwks/",
                },
            )
        if not path.startswith("/api/v3/"):
            return httpx.Response(404)
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(403, json={"detail": "Authentication credentials were not provided."})
        return self._api(method, path[len("/api/v3") :], query, body)

    def _api(self, method: str, path: str, query: dict[str, str], body: dict | None) -> httpx.Response:
        if (method, path) == ("GET", "/admin/version/"):
            return httpx.Response(200, json={"version_current": "2026.8.1"})
        if (method, path) == ("GET", "/crypto/certificatekeypairs/"):
            rows = [{"pk": "cert-uuid", "name": "nexbeat"}] if "cert" in self.existing else []
            return httpx.Response(200, json={"results": rows})
        if (method, path) == ("POST", "/crypto/certificatekeypairs/generate/"):
            return httpx.Response(200, json={"pk": "cert-uuid", "name": body["common_name"]})
        if (method, path) == ("GET", "/propertymappings/provider/scope/"):
            rows = [
                {
                    "pk": "map-openid",
                    "managed": "goauthentik.io/providers/oauth2/scope-openid",
                    "name": "default openid",
                },
                {
                    "pk": "map-profile",
                    "managed": "goauthentik.io/providers/oauth2/scope-profile",
                    "name": "default profile",
                },
                {"pk": "map-email", "managed": "goauthentik.io/providers/oauth2/scope-email", "name": "default email"},
            ]
            if "mapping" in self.existing:
                rows.append({"pk": "map-own", "managed": None, "name": "nexbeat email_verified"})
            if "name" in query:
                rows = [row for row in rows if row["name"] == query["name"]]
            if "managed" in query:
                rows = [row for row in rows if row["managed"] == query["managed"]]
            return httpx.Response(200, json={"results": rows})
        if (method, path) == ("POST", "/propertymappings/provider/scope/"):
            return httpx.Response(201, json={"pk": "map-own", "name": body["name"]})
        if (method, path) == ("GET", "/flows/instances/"):
            if query.get("designation") == "authorization":
                rows = [
                    {"pk": "flow-explicit", "slug": "default-provider-authorization-explicit-consent"},
                    {"pk": "flow-implicit", "slug": "default-provider-authorization-implicit-consent"},
                ]
            else:
                rows = [{"pk": "flow-invalidation", "slug": "default-provider-invalidation-flow"}]
            return httpx.Response(200, json={"results": rows})
        if (method, path) == ("GET", "/providers/oauth2/"):
            rows = [{"pk": 7, "name": "nexbeat"}] if "provider" in self.existing else []
            if rows and self.provider_redirect:
                rows[0]["redirect_uris"] = [{"matching_mode": "strict", "url": self.provider_redirect}]
            if "name" in query:
                rows = [row for row in rows if row["name"] == query["name"]]
            return httpx.Response(200, json={"results": rows})
        if (method, path) in (("POST", "/providers/oauth2/"), ("PATCH", "/providers/oauth2/7/")):
            return httpx.Response(
                201 if method == "POST" else 200,
                json={**body, "pk": 7, "client_id": "generated-client-id", "client_secret": "generated-secret"},
            )
        if (method, path) == ("GET", "/core/applications/"):
            rows = [{"pk": "app-uuid", "slug": "nexbeat"}] if "application" in self.existing else []
            if "slug" in query:
                rows = [row for row in rows if row["slug"] == query["slug"]]
            return httpx.Response(200, json={"results": rows})
        if method in ("POST", "PATCH") and path.startswith("/core/applications/"):
            return httpx.Response(201 if method == "POST" else 200, json={**body, "pk": "app-uuid"})
        return httpx.Response(404, json={"detail": f"no fake answer for {method} {path}"})


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeAuthentik]:
    server = FakeAuthentik()
    transport = httpx.MockTransport(server)
    monkeypatch.setattr(authentik_setup, "transport_for_tests", transport)
    # Die Discovery laeuft ueber den gemeinsamen OIDC-Client; auch der bekommt die Attrappe.
    discovery_client = httpx.AsyncClient(transport=transport)
    monkeypatch.setattr(oidc, "_client", lambda: discovery_client)
    monkeypatch.setattr(oidc, "_discovery", {})
    yield server


@pytest.fixture
def admin(admin_client: TestClient) -> TestClient:
    assert admin_client.put("/api/settings", json={"public_url": PUBLIC}).status_code == 200
    return admin_client


def run_setup(client: TestClient, url: str = URL, token: str = TOKEN) -> dict:
    response = client.post("/api/oidc/authentik/setup", json={"url": url, "token": token})
    assert response.status_code == 200, response.text
    return response.json()


def steps(result: dict) -> list[tuple[str, bool]]:
    return [(step["key"], step["ok"]) for step in result["steps"]]


def stored() -> OidcProvider | None:
    with SessionLocal() as db:
        return db.scalar(select(OidcProvider).where(OidcProvider.slug == "authentik"))


def test_setup_creates_everything_and_adds_the_sign_in_provider(admin: TestClient, fake: FakeAuthentik) -> None:
    result = run_setup(admin)
    assert result["ok"] is True
    assert steps(result) == [(key, True) for key in authentik_setup.STEP_KEYS]
    assert result["client_id"] == "generated-client-id" and result["issuer"] == ISSUER
    assert "2026.8.1" in result["steps"][0]["detail"]

    row = stored()
    assert row is not None
    assert row.issuer_url == ISSUER.rstrip("/") and row.client_id == "generated-client-id" and row.enabled
    assert row.client_secret != "generated-secret" and decrypt(row.client_secret) == "generated-secret"
    # Ein Anbieter vom Knopf legt keine Konten an.
    assert row.auto_create is False and row.default_role == Role.user
    # Die Anmeldeseite bietet ihn an.
    assert {"slug": "authentik", "label": "authentik"} in admin.get("/api/config").json()["oidc_providers"]

    created = [call for call in fake.calls if (call.method, call.path) == ("POST", "/api/v3/providers/oauth2/")]
    assert len(created) == 1
    sent = created[0].body
    assert sent is not None
    assert sent["name"] == "nexbeat" and sent["client_type"] == "confidential"
    # authentik 2026.8 lehnt jede Anmeldung ab, deren Grant nicht am Provider steht.
    assert sent["grant_types"] == ["authorization_code"]
    assert sent["redirect_uris"] == [{"matching_mode": "strict", "url": REDIRECT}]
    assert sent["signing_key"] == "cert-uuid" and sent["sub_mode"] == "user_uuid"
    assert sent["authorization_flow"] == "flow-implicit" and sent["invalidation_flow"] == "flow-invalidation"
    assert sorted(sent["property_mappings"]) == ["map-openid", "map-own", "map-profile"]


def test_the_token_goes_only_into_the_authorization_header(
    admin: TestClient, fake: FakeAuthentik, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    result = run_setup(admin)
    for call in fake.calls:
        if call.path.startswith("/api/v3/"):
            assert call.auth == f"Bearer {TOKEN}"
        assert TOKEN not in json.dumps(call.body or {}) and TOKEN not in json.dumps(call.query)
    assert TOKEN not in json.dumps(result)
    assert TOKEN not in caplog.text
    with SessionLocal() as db:
        for row in db.scalars(select(OidcProvider)):
            assert TOKEN not in (row.client_secret + row.client_id + row.issuer_url)


def test_pressing_it_again_updates_instead_of_duplicating(admin: TestClient, fake: FakeAuthentik) -> None:
    run_setup(admin)
    fake.existing |= {"cert", "mapping", "provider", "application"}
    fake.calls.clear()
    result = run_setup(admin)
    assert result["ok"] is True
    methods = {(call.method, call.path) for call in fake.calls}
    assert ("PATCH", "/api/v3/providers/oauth2/7/") in methods
    assert ("PATCH", "/api/v3/core/applications/nexbeat/") in methods
    assert not any(method == "POST" for method, _ in methods), methods
    with SessionLocal() as db:
        assert len(db.scalars(select(OidcProvider)).all()) == 1


def test_the_first_failure_stops_the_run_and_names_the_status_not_the_answer(
    admin: TestClient, fake: FakeAuthentik
) -> None:
    fake.fail = ("POST", "/api/v3/providers/oauth2/", 403)
    result = run_setup(admin)
    assert result["ok"] is False
    assert steps(result) == [("reached", True), ("signingKey", True), ("mapping", True), ("provider", False)]
    detail = result["steps"][-1]["detail"]
    assert "403" in detail and "may not" in detail
    assert "secrets of its own" not in detail, "the body of a foreign answer must not go back to the browser"
    assert stored() is None


def test_a_wrong_token_stops_at_the_first_step(admin: TestClient, fake: FakeAuthentik) -> None:
    result = run_setup(admin, token="not-the-token")
    assert steps(result) == [("reached", False)]
    assert stored() is None


def test_an_unreachable_authentik_is_named(admin: TestClient, fake: FakeAuthentik) -> None:
    result = run_setup(admin, url="https://nowhere.example.com")
    assert steps(result) == [("reached", False)]
    assert "not reachable" in result["steps"][0]["detail"]


def test_a_second_nexbeat_does_not_take_over_the_first_ones_provider(admin: TestClient, fake: FakeAuthentik) -> None:
    fake.existing |= {"provider"}
    fake.provider_redirect = "https://music.other.example.com/api/auth/oidc/authentik/callback"
    result = run_setup(admin)
    assert result["ok"] is True
    assert result["issuer"] == f"{URL}/application/o/nexbeat-music-example-com/"
    created = [call for call in fake.calls if (call.method, call.path) == ("POST", "/api/v3/providers/oauth2/")]
    assert created and created[0].body is not None and created[0].body["name"] == "nexbeat (music.example.com)"


def test_a_failed_discovery_keeps_what_authentik_handed_out(admin: TestClient, fake: FakeAuthentik) -> None:
    fake.discovery_ok = False
    result = run_setup(admin)
    assert steps(result)[-1] == ("filled", False)
    assert "discovery" in result["steps"][-1]["detail"]
    row = stored()
    assert row is not None and row.client_id == "generated-client-id"


def test_a_new_issuer_drops_the_links_of_the_old_one(admin: TestClient, fake: FakeAuthentik) -> None:
    """Ein ``sub`` bedeutet nur beim Aussteller etwas, der es vergeben hat."""
    made = admin.post(
        "/api/oidc/providers",
        json={
            "slug": "authentik",
            "label": "authentik",
            "issuer_url": "https://old.example.com/application/o/beat/",
            "client_id": "old",
            "client_secret": "old-secret",
        },
    )
    assert made.status_code == 201, made.text
    with SessionLocal() as db:
        user = db.scalars(select(User)).first()
        assert user is not None
        db.add(OidcLink(provider_id=made.json()["id"], user_id=user.id, subject="from-the-old-issuer", email=""))
        db.commit()
    assert run_setup(admin)["ok"] is True
    with SessionLocal() as db:
        assert db.scalars(select(OidcLink)).all() == []
        assert len(db.scalars(select(OidcProvider)).all()) == 1


def test_only_an_administrator_may_press_it(admin: TestClient, fake: FakeAuthentik) -> None:
    create_user("kim")
    browser = TestClient(app)
    headers = auth_headers(browser, "kim")
    refused = browser.post("/api/oidc/authentik/setup", json={"url": URL, "token": TOKEN}, headers=headers)
    assert refused.status_code == 403
    assert browser.get("/api/oidc/authentik/blueprint", headers=headers).status_code == 403
    assert fake.calls == []


def test_without_a_public_address_nothing_is_sent(admin_client: TestClient, fake: FakeAuthentik) -> None:
    refused = admin_client.post("/api/oidc/authentik/setup", json={"url": URL, "token": TOKEN})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "oidc_no_public_url"
    assert fake.calls == []


def test_an_address_without_a_scheme_is_refused(admin: TestClient, fake: FakeAuthentik) -> None:
    refused = admin.post("/api/oidc/authentik/setup", json={"url": "auth.example.com", "token": TOKEN})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "oidc_bad_url"
    assert fake.calls == []


def test_the_blueprint_describes_the_same_objects(admin: TestClient) -> None:
    answer = admin.get("/api/oidc/authentik/blueprint")
    assert answer.status_code == 200
    data = answer.json()
    assert data["filename"] == "nexbeat-authentik.yaml"
    text = data["content"]
    models = [line.split(":", 1)[1].strip() for line in text.splitlines() if line.strip().startswith("- model:")]
    assert models == [
        "authentik_providers_oauth2.scopemapping",
        "authentik_providers_oauth2.oauth2provider",
        "authentik_core.application",
    ]
    assert "        - authorization_code" in text
    assert f"          url: {json.dumps(REDIRECT)}" in text
    assert "nexdeck" not in text
