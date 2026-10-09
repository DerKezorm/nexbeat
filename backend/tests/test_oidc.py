"""Anmelden ueber OpenID Connect, Konto verknuepfen und die Anbieter verwalten.

Die Unterschriftspruefung selbst ist die von pyjwt. Fuer den Weg durch nexbeat wird ``claims`` ersetzt, damit
die Tests sagen koennen, was der Anbieter behauptet. Die Pruefung des Ausstellers (Entra ID mit ``{tenantid}``)
laeuft dagegen mit echt unterschriebenen Tokens.
"""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import SessionLocal
from app.main import app
from app.models import OidcLink, OidcProvider, Role, User
from app.security import has_usable_password
from app.services import oidc as oidc_service
from tests.conftest import USER_PASSWORD, auth_headers, create_user

PUBLIC = "https://music.example.com"
PROVIDER = {
    "slug": "keycloak",
    "label": "Keycloak",
    "issuer_url": "https://id.example.com/realms/home",
    "client_id": "nexbeat",
    "client_secret": "client-secret-for-tests",
    "scopes": "openid profile email",
    "enabled": True,
    "auto_create": True,
    "default_role": "user",
}
DOCUMENT = {
    "issuer": PROVIDER["issuer_url"],
    "authorization_endpoint": f"{PROVIDER['issuer_url']}/auth",
    "token_endpoint": f"{PROVIDER['issuer_url']}/token",
    "jwks_uri": f"{PROVIDER['issuer_url']}/certs",
}


@pytest.fixture
def provider(admin_client: TestClient) -> dict[str, Any]:
    # Ohne oeffentliche Adresse gibt es keine Rueckleitadresse, und OIDC kommt nicht in Gang.
    assert admin_client.put("/api/settings", json={"public_url": PUBLIC}).status_code == 200
    made = admin_client.post("/api/oidc/providers", json=PROVIDER)
    assert made.status_code == 201, made.text
    return made.json()


class Claims:
    """Was der Anbieter behauptet; je Test veraenderbar."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, **claims: Any) -> None:
        self.claims = claims
        self.exchanged: list[tuple[Any, ...]] = []

        async def discovery(_issuer: str) -> dict[str, Any]:
            return DOCUMENT

        async def exchange(*args: Any) -> dict[str, Any]:
            self.exchanged.append(args)
            return {"id_token": "pretend", "access_token": "pretend"}

        async def claims_(*_args: Any) -> dict[str, Any]:
            return dict(self.claims)

        async def userinfo(*_args: Any) -> dict[str, Any]:
            return {}

        monkeypatch.setattr(oidc_service, "discovery", discovery)
        monkeypatch.setattr(oidc_service, "exchange", exchange)
        monkeypatch.setattr(oidc_service, "claims", claims_)
        monkeypatch.setattr(oidc_service, "userinfo", userinfo)


def _attempt_from(response: Any) -> dict[str, Any]:
    raw = ""
    for header, value in response.headers.multi_items():
        if header.lower() == "set-cookie" and value.startswith(f"{oidc_service.COOKIE_NAME}="):
            raw = value.split("=", 1)[1].split(";", 1)[0]
    attempt = oidc_service.unpack_state(raw)
    assert attempt is not None, "the attempt cookie was not set"
    return attempt


def sign_in(browser: TestClient, slug: str = "keycloak", state: str | None = None) -> str:
    """Anmeldung starten und den Ruecksprung ausfuehren. Gibt das Ziel der Weiterleitung zurueck."""
    started = browser.get(f"/api/auth/oidc/{slug}/login", follow_redirects=False)
    assert started.status_code == 302, started.text
    attempt = _attempt_from(started)
    back = browser.get(
        f"/api/auth/oidc/{slug}/callback",
        params={"code": "code-from-provider", "state": state or attempt["state"]},
        follow_redirects=False,
    )
    assert back.status_code == 303, back.text
    return back.headers["location"]


def signed_in_as(browser: TestClient) -> dict[str, Any] | None:
    refreshed = browser.post("/api/auth/refresh")
    if refreshed.status_code != 200:
        return None
    me = browser.get("/api/auth/me", headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"})
    assert me.status_code == 200, me.text
    return me.json()


def _user(username: str) -> User | None:
    with SessionLocal() as db:
        return db.scalar(select(User).where(User.username == username))


def _count(model: Any) -> int:
    with SessionLocal() as db:
        return int(db.scalar(select(func.count()).select_from(model)) or 0)


# -- Anmelden ------------------------------------------------------------------


def test_the_first_sign_in_creates_an_account_without_a_password(
    provider: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    Claims(monkeypatch, sub="subject-1", email="Kim@Example.com", preferred_username="kim", name="Kim K")
    browser = TestClient(app)
    assert sign_in(browser) == "/"
    me = signed_in_as(browser)
    assert me is not None and me["username"] == "kim" and me["email"] == "kim@example.com"
    assert me["role"] == "user" and me["has_password"] is False and me["display_name"] == "Kim K"
    user = _user("kim")
    assert user is not None and not has_usable_password(user.password_hash)
    # Konten ohne Passwort kommen mit keinem Passwort hinein, auch nicht mit der Markierung selbst.
    for guess in (user.password_hash, "", "x"):
        answer = TestClient(app).post("/api/auth/login", json={"login": "kim", "password": guess or "-"})
        assert answer.status_code == 401


def test_the_code_exchange_gets_the_return_address_and_the_secret(
    provider: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    pretend = Claims(monkeypatch, sub="subject-1", preferred_username="kim")
    sign_in(TestClient(app))
    _document, client_id, secret, redirect, code, _verifier = pretend.exchanged[0]
    assert client_id == "nexbeat" and secret == "client-secret-for-tests" and code == "code-from-provider"
    assert redirect == f"{PUBLIC}/api/auth/oidc/keycloak/callback"


def test_a_second_sign_in_finds_the_same_account(provider: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    Claims(monkeypatch, sub="subject-1", preferred_username="kim")
    sign_in(TestClient(app))
    sign_in(TestClient(app))
    assert _count(User) == 2 and _count(OidcLink) == 1


def test_a_token_without_a_subject_is_refused(provider: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ Sonst waere die leere Zeichenkette die Identitaet, und die zweite Person kaeme ins Konto der ersten."""
    Claims(monkeypatch, email="someone@example.com", preferred_username="someone")
    assert sign_in(TestClient(app)) == "/login?oidc_error=oidc_bad_token"
    assert _count(User) == 1


def test_a_foreign_state_is_refused(provider: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    Claims(monkeypatch, sub="subject-1", preferred_username="kim")
    assert sign_in(TestClient(app), state="not-the-state") == "/login?oidc_error=oidc_state_mismatch"
    assert _user("kim") is None


def test_a_callback_without_a_started_attempt_is_refused(provider: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    Claims(monkeypatch, sub="subject-1", preferred_username="kim")
    back = TestClient(app).get("/api/auth/oidc/keycloak/callback?code=c&state=s", follow_redirects=False)
    assert back.headers["location"] == "/login?oidc_error=oidc_state_mismatch"
    assert _user("kim") is None


def test_a_session_token_is_no_attempt(provider: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Derselbe Schluessel unterschreibt Sitzung und Versuch; die Art trennt sie."""
    from app.security import create_refresh_token

    assert oidc_service.unpack_state(create_refresh_token(1, "session")) is None


def test_without_auto_create_only_linked_accounts_get_in(
    admin_client: TestClient, provider: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    changed = admin_client.patch(f"/api/oidc/providers/{provider['id']}", json={**PROVIDER, "auto_create": False})
    assert changed.status_code == 200, changed.text
    Claims(monkeypatch, sub="subject-1", preferred_username="kim")
    assert sign_in(TestClient(app)) == "/login?oidc_error=oidc_no_account"
    assert _user("kim") is None


def test_an_address_of_an_existing_account_takes_nothing_over(provider: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ Wer bei authentik die Adresse eines anderen eintraegt, darf nicht in dessen Konto."""
    create_user("lou")
    Claims(monkeypatch, sub="intruder", email="LOU@example.com", preferred_username="lou-at-idp")
    browser = TestClient(app)
    assert sign_in(browser) == "/login?oidc_error=oidc_email_taken"
    assert signed_in_as(browser) is None
    assert _count(OidcLink) == 0 and _user("lou-at-idp") is None


def test_entra_without_email_gets_a_name_from_the_upn_and_a_placeholder(
    provider: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    Claims(monkeypatch, sub="entra-sub", preferred_username="max.muster@example.com", name="Max Muster")
    browser = TestClient(app)
    assert sign_in(browser) == "/"
    me = signed_in_as(browser)
    assert me is not None and me["username"] == "max.muster"
    assert me["email"] == "max.muster@oidc.invalid"


def test_a_taken_name_gets_a_suffix(provider: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    create_user("kim")
    Claims(monkeypatch, sub="subject-1", preferred_username="KIM", email="kim.other@example.com")
    browser = TestClient(app)
    sign_in(browser)
    me = signed_in_as(browser)
    assert me is not None and me["username"] == "KIM-2"


def test_the_role_of_new_accounts_follows_the_provider(
    admin_client: TestClient, provider: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin_client.patch(f"/api/oidc/providers/{provider['id']}", json={**PROVIDER, "default_role": "admin"})
    Claims(monkeypatch, sub="subject-1", preferred_username="kim")
    sign_in(TestClient(app))
    user = _user("kim")
    assert user is not None and user.role == Role.admin


def test_a_disabled_account_stays_out(provider: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    Claims(monkeypatch, sub="subject-1", preferred_username="kim")
    sign_in(TestClient(app))
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "kim"))
        assert user is not None
        user.is_active = False
        db.commit()
    browser = TestClient(app)
    assert sign_in(browser) == "/login?oidc_error=oidc_disabled"
    assert signed_in_as(browser) is None


def test_a_switched_off_provider_has_no_way_in(
    admin_client: TestClient, provider: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin_client.patch(f"/api/oidc/providers/{provider['id']}", json={**PROVIDER, "enabled": False})
    Claims(monkeypatch, sub="subject-1", preferred_username="kim")
    assert TestClient(app).get("/api/auth/oidc/keycloak/login", follow_redirects=False).status_code == 404
    assert TestClient(app).get("/api/config").json()["oidc_providers"] == []


def test_the_sign_in_page_lists_only_slug_and_label(provider: dict) -> None:
    assert TestClient(app).get("/api/config").json()["oidc_providers"] == [{"slug": "keycloak", "label": "Keycloak"}]


def test_without_a_public_address_the_sign_in_does_not_start(
    admin_client: TestClient, provider: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    Claims(monkeypatch, sub="subject-1", preferred_username="kim")
    admin_client.put("/api/settings", json={"public_url": ""})
    started = TestClient(app).get("/api/auth/oidc/keycloak/login", follow_redirects=False)
    assert started.headers["location"] == "/login?oidc_error=oidc_no_public_url"


def test_an_account_without_a_password_sets_its_first_one(provider: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    Claims(monkeypatch, sub="subject-1", preferred_username="kim")
    browser = TestClient(app)
    sign_in(browser)
    access = browser.post("/api/auth/refresh").json()["access_token"]
    headers = {"Authorization": f"Bearer {access}"}
    first = browser.post("/api/auth/me/password", json={"new_password": "first-password-1"}, headers=headers)
    assert first.status_code == 200, first.text
    headers = {"Authorization": f"Bearer {first.json()['access_token']}"}
    # Danach braucht jeder Wechsel das alte.
    second = browser.post("/api/auth/me/password", json={"new_password": "second-password-2"}, headers=headers)
    assert second.status_code == 400 and second.json()["detail"]["code"] == "wrong_password"
    assert (
        TestClient(app).post("/api/auth/login", json={"login": "kim", "password": "first-password-1"}).status_code
        == 200
    )


# -- Verknuepfen ---------------------------------------------------------------


def _link(browser: TestClient, headers: dict[str, str], slug: str = "keycloak") -> str:
    started = browser.post(f"/api/oidc/links/{slug}", headers=headers)
    assert started.status_code == 200, started.text
    assert started.json()["url"].startswith(DOCUMENT["authorization_endpoint"])
    attempt = _attempt_from(started)
    assert attempt["purpose"] == "link"
    back = browser.get(
        f"/api/auth/oidc/{slug}/callback",
        params={"code": "c", "state": attempt["state"]},
        follow_redirects=False,
    )
    return back.headers["location"]


def test_linking_puts_the_identity_on_the_asking_account(provider: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    lou = create_user("lou")
    browser = TestClient(app)
    headers = auth_headers(browser, "lou")
    Claims(monkeypatch, sub="lou-at-idp", email="whatever@example.com", preferred_username="someone-else")
    assert _link(browser, headers) == "/profil?oidc_linked=keycloak"
    listed = browser.get("/api/oidc/links", headers=headers).json()
    assert listed == [{"slug": "keycloak", "label": "Keycloak", "linked": True}]
    # Ab jetzt fuehrt die Anmeldung beim Anbieter in genau dieses Konto.
    fresh = TestClient(app)
    assert sign_in(fresh) == "/"
    me = signed_in_as(fresh)
    assert me is not None and me["id"] == lou and me["has_password"] is True
    assert _count(User) == 2


def test_an_identity_of_another_account_cannot_be_linked(provider: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    Claims(monkeypatch, sub="kims-identity", preferred_username="kim")
    sign_in(TestClient(app))
    create_user("lou")
    browser = TestClient(app)
    assert _link(browser, auth_headers(browser, "lou")) == "/profil?oidc_error=oidc_taken"


def test_linking_needs_a_browser_session_not_an_api_token(admin_client: TestClient, provider: dict) -> None:
    token = admin_client.post("/api/auth/me/keys", json={"name": "Dashboard"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert admin_client.post("/api/oidc/links/keycloak", headers=headers).status_code == 403
    assert admin_client.get("/api/oidc/links", headers=headers).status_code == 403


def test_the_last_way_into_an_account_without_a_password_stays(provider: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    Claims(monkeypatch, sub="subject-1", preferred_username="kim")
    browser = TestClient(app)
    sign_in(browser)
    headers = {"Authorization": f"Bearer {browser.post('/api/auth/refresh').json()['access_token']}"}
    refused = browser.delete("/api/oidc/links/keycloak", headers=headers)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "oidc_would_lock_out"
    assert _count(OidcLink) == 1


def test_an_account_with_a_password_may_unlink(provider: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    create_user("lou")
    browser = TestClient(app)
    headers = auth_headers(browser, "lou", USER_PASSWORD)
    Claims(monkeypatch, sub="lou-at-idp", preferred_username="lou")
    _link(browser, headers)
    assert browser.delete("/api/oidc/links/keycloak", headers=headers).status_code == 204
    assert _count(OidcLink) == 0


# -- Verwaltung ----------------------------------------------------------------


def test_only_admins_manage_providers(provider: dict) -> None:
    create_user("lou")
    browser = TestClient(app)
    headers = auth_headers(browser, "lou")
    assert browser.get("/api/oidc/providers", headers=headers).status_code == 403
    assert browser.post("/api/oidc/providers", json={**PROVIDER, "slug": "x"}, headers=headers).status_code == 403
    assert browser.delete(f"/api/oidc/providers/{provider['id']}", headers=headers).status_code == 403


def test_the_secret_never_comes_back_and_stays_when_left_empty(admin_client: TestClient, provider: dict) -> None:
    assert "client_secret" not in provider and provider["has_secret"] is True
    changed = admin_client.patch(f"/api/oidc/providers/{provider['id']}", json={**PROVIDER, "client_secret": ""})
    assert changed.status_code == 200 and changed.json()["has_secret"] is True
    with SessionLocal() as db:
        row = db.get(OidcProvider, provider["id"])
        assert row is not None and row.client_secret.startswith("enc:")


def test_a_taken_slug_is_refused(admin_client: TestClient, provider: dict) -> None:
    again = admin_client.post("/api/oidc/providers", json=PROVIDER)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "oidc_slug_taken"


def test_a_new_issuer_drops_the_links_of_the_old_one(
    admin_client: TestClient, provider: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⚠️ Ein ``sub`` bedeutet nur beim Aussteller etwas, der es vergeben hat."""
    Claims(monkeypatch, sub="subject-1", preferred_username="kim")
    sign_in(TestClient(app))
    moved = {**PROVIDER, "issuer_url": "https://other.example.com/realms/home"}
    assert admin_client.patch(f"/api/oidc/providers/{provider['id']}", json=moved).status_code == 200
    assert _count(OidcLink) == 0


def test_deleting_a_provider_that_strands_accounts_asks_first(
    admin_client: TestClient, provider: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    Claims(monkeypatch, sub="subject-1", preferred_username="kim")
    sign_in(TestClient(app))
    refused = admin_client.delete(f"/api/oidc/providers/{provider['id']}")
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "oidc_provider_strands" and refused.json()["detail"]["count"] == 1
    assert _count(OidcProvider) == 1
    assert admin_client.delete(f"/api/oidc/providers/{provider['id']}?force=true").status_code == 204
    assert _count(OidcProvider) == 0 and _count(OidcLink) == 0


def test_deleting_an_account_takes_its_links(
    admin_client: TestClient, provider: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    Claims(monkeypatch, sub="subject-1", preferred_username="kim")
    sign_in(TestClient(app))
    user = _user("kim")
    assert user is not None
    assert admin_client.delete(f"/api/users/{user.id}").status_code == 204
    assert _count(OidcLink) == 0


# -- Aussteller und Unterschrift, mit echten Tokens ------------------------------

ENTRA_TENANT = "9f3c2b1a-1111-4222-8333-444455556666"
ENTRA_COMMON = "https://login.microsoftonline.com/common/v2.0"
ENTRA_DOCUMENT = {
    "issuer": "https://login.microsoftonline.com/{tenantid}/v2.0",
    "authorization_endpoint": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
    "token_endpoint": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
    "jwks_uri": "https://login.microsoftonline.com/common/discovery/v2.0/keys",
}


@pytest.fixture
def signing_key(monkeypatch: pytest.MonkeyPatch) -> rsa.RSAPrivateKey:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Keys:
        def get_signing_key_from_jwt(self, _token: str) -> Any:
            return type("Found", (), {"key": key.public_key()})()

    monkeypatch.setattr(oidc_service, "_jwks_client", lambda _uri: Keys())
    return key


def _token(key: rsa.RSAPrivateKey, **claims: Any) -> str:
    now = int(time.time())
    payload = {"sub": "s", "aud": "client", "nonce": "n", "iat": now, "exp": now + 300, **claims}
    return jwt.encode(payload, key, algorithm="RS256")


def _claims(token: str, document: dict[str, Any], issuer_url: str) -> dict[str, Any]:
    import asyncio

    return asyncio.run(oidc_service.claims(document, "client", token, "n", issuer_url))


def test_entra_common_accepts_the_tenant_named_in_the_token(signing_key: rsa.RSAPrivateKey) -> None:
    issued = f"https://login.microsoftonline.com/{ENTRA_TENANT}/v2.0"
    claims = _claims(_token(signing_key, iss=issued, tid=ENTRA_TENANT), ENTRA_DOCUMENT, ENTRA_COMMON)
    assert claims["tid"] == ENTRA_TENANT


def test_entra_common_refuses_an_issuer_that_does_not_match_the_tenant(signing_key: rsa.RSAPrivateKey) -> None:
    other = "0a0a0a0a-1111-4222-8333-444455556666"
    token = _token(signing_key, iss=f"https://login.microsoftonline.com/{other}/v2.0", tid=ENTRA_TENANT)
    with pytest.raises(oidc_service.OidcError) as caught:
        _claims(token, ENTRA_DOCUMENT, ENTRA_COMMON)
    assert caught.value.code == "oidc_bad_token"


def test_the_placeholder_itself_is_never_an_accepted_issuer(signing_key: rsa.RSAPrivateKey) -> None:
    token = _token(signing_key, iss=ENTRA_DOCUMENT["issuer"])
    with pytest.raises(oidc_service.OidcError):
        _claims(token, ENTRA_DOCUMENT, ENTRA_COMMON)


def test_a_single_tenant_issuer_is_matched_as_entered(signing_key: rsa.RSAPrivateKey) -> None:
    issuer = f"https://login.microsoftonline.com/{ENTRA_TENANT}/v2.0"
    document = {**ENTRA_DOCUMENT, "issuer": issuer}
    assert _claims(_token(signing_key, iss=issuer, tid=ENTRA_TENANT), document, issuer)["sub"] == "s"
    with pytest.raises(oidc_service.OidcError):
        _claims(_token(signing_key, iss="https://evil.example.com"), document, issuer)


def test_a_wrong_nonce_or_audience_is_refused(signing_key: rsa.RSAPrivateKey) -> None:
    issuer = DOCUMENT["issuer"]
    with pytest.raises(oidc_service.OidcError):
        _claims(_token(signing_key, iss=issuer, nonce="other"), DOCUMENT, issuer)
    with pytest.raises(oidc_service.OidcError):
        _claims(_token(signing_key, iss=issuer, aud="someone-else"), DOCUMENT, issuer)


def test_a_token_signed_with_the_client_secret_is_refused() -> None:
    token = jwt.encode(
        {"sub": "s", "aud": "client", "nonce": "n", "iss": DOCUMENT["issuer"]}, "x" * 32, algorithm="HS256"
    )
    with pytest.raises(oidc_service.OidcError) as caught:
        _claims(token, DOCUMENT, DOCUMENT["issuer"])
    assert caught.value.code == "oidc_no_signing_key"


@pytest.mark.parametrize(
    ("preferred", "expected"),
    [
        ("kim", "kim"),
        ("max.muster@example.com", "max.muster"),
        ("Jürgen Müller", "J-rgen-M-ller"),
        ("@", ""),
    ],
)
def test_usernames_from_the_provider(preferred: str, expected: str) -> None:
    assert oidc_service.username_from(preferred) == expected
