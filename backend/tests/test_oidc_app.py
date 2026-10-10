"""Was nur nexbeat an der Anmeldung ueber Anbieter leistet; das Gemeinsame pruefen die Vertragstests in ``nexoidc/``.

- Die Liste aus 1.3.0 wandert beim Start: alte Rueckleitadresse, Knopf-Eintrag, Geheimnis mit Kontext, Sicherung.
- 1.3.0 laeuft auf einer Datenbank dieser Fassung weiter (Rueckweg): jede neue Spalte hat eine Vorgabe.
- Das Sitzungs-Cookie liegt unter ``/api``, damit die Rueckkehr beim Verknuepfen die Sitzung sieht.
- Die Bremse zaehlt nur Rueckkehrer mit gueltigem Anlauf-Cookie.
- Feste Routen verdecken keinen Anbieter mit dem Kurznamen ``authentik``.
- Oeffentliche Adresse speichern fragt erst, auch beim Leeren; Passwort-Anmeldung abschaltbar.
- Das Schema eines vertrauten Proxys: der rechteste Wert, ohne Gross und klein, nur http und https.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text

from app.crypto import encrypt, unseal
from app.db import SessionLocal, engine, init_db
from app.main import app
from app.models import Base, OidcLink, OidcProvider, User
from app.proxy import behind_proxy, forwarded_scheme
from app.services import anmeldebremse, oidc_migration
from app.vendor import nexoidc
from app.vendor.nexoidc import attempt, protocol, secret_context
from tests.conftest import ADMIN, USER_PASSWORD, auth_headers, create_user

sys.path.insert(0, str(Path(__file__).resolve().parent / "nexoidc"))
fakes = importlib.import_module("oidc_fakes")

OLD_CALLBACK = "/api/auth/oidc/{slug}/callback"
#: Die beiden Tabellen, wie nexbeat 1.3.0 sie anlegte (``git show v1.3.0:backend/app/models.py``).
OLD_TABLES = (
    """CREATE TABLE oidc_providers (
        id INTEGER NOT NULL, slug VARCHAR(40) NOT NULL, label VARCHAR(80) NOT NULL,
        issuer_url VARCHAR(300) NOT NULL, client_id VARCHAR(300) NOT NULL, client_secret VARCHAR(600) NOT NULL,
        scopes VARCHAR(200) NOT NULL, enabled BOOLEAN NOT NULL, auto_create BOOLEAN NOT NULL,
        default_role VARCHAR(5) NOT NULL, PRIMARY KEY (id), UNIQUE (slug))""",
    """CREATE TABLE oidc_links (
        id INTEGER NOT NULL, provider_id INTEGER NOT NULL, user_id INTEGER NOT NULL, subject VARCHAR(300) NOT NULL,
        email VARCHAR(300) NOT NULL, created_at DATETIME NOT NULL, PRIMARY KEY (id),
        UNIQUE (provider_id, subject),
        FOREIGN KEY(provider_id) REFERENCES oidc_providers (id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE)""",
)
OLD_PROVIDER_COLUMNS = (
    "id, slug, label, issuer_url, client_id, client_secret, scopes, enabled, auto_create, default_role"
)


@pytest.fixture
def net() -> Iterator[Any]:
    network = fakes.Network()
    nexoidc.use_transport(network.transport())
    protocol.clear_caches()
    attempt.forget_used_states()
    yield network
    nexoidc.use_transport(None)
    protocol.clear_caches()
    attempt.forget_used_states()


@pytest.fixture
def old_tables() -> Iterator[None]:
    """Die Anbietertabellen in der Form von 1.3.0; danach wieder die heutigen."""
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE oidc_links"))
        connection.execute(text("DROP TABLE oidc_providers"))
        for statement in OLD_TABLES:
            connection.execute(text(statement))
    yield
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS oidc_links"))
        connection.execute(text("DROP TABLE IF EXISTS oidc_providers"))
    Base.metadata.create_all(engine)


def _old_provider(slug: str, issuer: str, client_id: str, secret: str, *, auto_create: bool = False) -> int:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO oidc_providers (slug, label, issuer_url, client_id, client_secret, scopes, enabled, "
                "auto_create, default_role) VALUES "
                "(:slug, :label, :issuer, :client_id, :secret, 'openid profile email', 1, :auto, 'user')"
            ),
            {
                "slug": slug,
                "label": slug.title(),
                "issuer": issuer,
                "client_id": client_id,
                "secret": encrypt(secret) if secret else "",
                "auto": auto_create,
            },
        )
        return int(connection.execute(text("SELECT id FROM oidc_providers WHERE slug = :s"), {"s": slug}).scalar())


def _old_link(provider_id: int, user_id: int, subject: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO oidc_links (provider_id, user_id, subject, email, created_at) "
                "VALUES (:p, :u, :s, '', '2026-10-09 10:00:00')"
            ),
            {"p": provider_id, "u": user_id, "s": subject},
        )


def _row(slug: str) -> OidcProvider:
    with SessionLocal() as db:
        row = db.scalar(select(OidcProvider).where(OidcProvider.slug == slug))
        assert row is not None
        return row


def _backups() -> list[Path]:
    from app.config import get_settings

    return sorted(get_settings().database_path.parent.glob("nexbeat-before-oidc-*.db"))


def _round_trip(browser: TestClient, fake: Any, slug: str) -> Any:
    started = browser.get(f"/api/oidc/{slug}/start", follow_redirects=False)
    assert started.status_code == 303, started.text
    target = started.headers["location"]
    callback = fakes.query_of(target)["redirect_uri"].split("://", 1)[1].split("/", 1)[1]
    params = fake.authorize(target)
    return browser.get(f"/{callback}", params=params, follow_redirects=False)


def _add(admin: TestClient, fake: Any, slug: str, **extra: Any) -> dict[str, Any]:
    body = {
        "label": extra.pop("label", "SSO"),
        "slug": slug,
        "issuer": fake.issuer,
        "client_id": fake.client_id,
        "client_secret": fake.client_secret,
        **extra,
    }
    made = admin.post("/api/oidc/admin/providers", json=body)
    assert made.status_code == 201, made.text
    return made.json()


def _who(browser: TestClient) -> str | None:
    refreshed = browser.post("/api/auth/refresh")
    if refreshed.status_code != 200:
        return None
    me = browser.get("/api/auth/me", headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"})
    return me.json()["username"] if me.status_code == 200 else None


# --- Wanderung der Liste aus 1.3.0 -------------------------------------------------------------------------------------


def test_the_list_of_1_3_0_keeps_its_redirect_addresses_and_signs_in_there(old_tables: None, net: Any) -> None:
    for old in _backups():
        old.unlink()
    authentik = net.add(fakes.FakeProvider("https://auth.example.com/application/o/nexbeat/"))
    keycloak = net.add(fakes.FakeProvider("https://id.example.com/realms/home"))
    alex = create_user("alex")
    kim = create_user("kim")
    # Wie 1.3.0 schrieb: Aussteller ohne Schraegstrich am Ende, Geheimnis mit ``crypto.encrypt``.
    first = _old_provider("authentik", authentik.issuer.rstrip("/"), authentik.client_id, authentik.client_secret)
    second = _old_provider("keycloak", keycloak.issuer, keycloak.client_id, keycloak.client_secret)
    _old_link(first, alex, "person-1")
    _old_link(second, kim, "person-7")

    init_db()

    assert len(_backups()) == 1
    made = _row("authentik")
    assert made.redirect_path == "/api/auth/oidc/authentik/callback" and made.managed == "authentik"
    assert made.issuer == authentik.issuer.rstrip("/"), "the issuer stays as 1.3.0 wrote it"
    assert unseal(made.client_secret_enc, secret_context(made.id)) == authentik.client_secret
    by_hand = _row("keycloak")
    assert by_hand.redirect_path == "/api/auth/oidc/keycloak/callback" and by_hand.managed == ""
    with SessionLocal() as db:
        links = {link.subject: (link.account_id, link.issuer) for link in db.scalars(select(OidcLink))}
    assert links == {"person-1": (alex, made.issuer), "person-7": (kim, by_hand.issuer)}
    names = {index["name"] for index in inspect(engine).get_indexes("oidc_links")}
    assert oidc_migration.UNIQUE_INDEX in names

    # Die Anbieter kennen nur die alte Adresse: Dort geht die Anmeldung weiter.
    keycloak.person = {"sub": "person-7", "preferred_username": "kim"}
    browser = TestClient(app)
    started = browser.get("/api/oidc/keycloak/start", follow_redirects=False)
    assert fakes.query_of(started.headers["location"])["redirect_uri"] == (
        "http://testserver/api/auth/oidc/keycloak/callback"
    )
    response = _round_trip(browser, keycloak, "keycloak")
    assert response.headers["location"] == "/" and _who(browser) == "kim"

    # Ein zweiter Start aendert nichts und sichert nichts.
    init_db()
    assert len(_backups()) == 1
    assert _row("keycloak").redirect_path == "/api/auth/oidc/keycloak/callback"


def test_only_the_button_entry_of_1_3_0_counts_as_set_up_through_authentik(old_tables: None) -> None:
    _old_provider("authentik", "https://id.example.com/realms/home", "x", "s")
    _old_provider("company", "https://auth.example.com/application/o/nexbeat/", "y", "s")
    init_db()
    assert _row("authentik").managed == "" and _row("company").managed == ""


def test_a_secret_changed_in_1_3_0_is_taken_over_at_the_next_start(admin_client: TestClient, net: Any) -> None:
    sso = net.add(fakes.FakeProvider())
    made = admin_client.post(
        "/api/oidc/admin/providers",
        json={"label": "SSO", "slug": "sso", "issuer": sso.issuer, "client_id": sso.client_id, "client_secret": "a"},
    )
    assert made.status_code == 201, made.text
    row = _row("sso")
    assert unseal(row.client_secret_enc, secret_context(row.id)) == "a"
    # 1.3.0 liest und schreibt nur ``client_secret``.
    with engine.begin() as connection:
        connection.execute(text("UPDATE oidc_providers SET client_secret = :s"), {"s": encrypt(sso.client_secret)})
    init_db()
    row = _row("sso")
    assert unseal(row.client_secret_enc, secret_context(row.id)) == sso.client_secret
    assert row.redirect_path == "", "an entry of this version keeps the standard redirect address"


# --- Rueckweg: 1.3.0 auf einer Datenbank dieser Fassung -------------------------------------------------------------


@pytest.mark.parametrize(
    ("table", "old_columns"),
    [
        ("oidc_providers", OLD_PROVIDER_COLUMNS),
        ("oidc_links", "id, provider_id, user_id, subject, email, created_at"),
    ],
)
def test_every_new_column_has_a_default_for_the_older_version(table: str, old_columns: str) -> None:
    old = {name.strip() for name in old_columns.split(",")}
    with engine.connect() as connection:
        columns = connection.execute(text(f"PRAGMA table_info({table})")).mappings().all()
    newer = [column for column in columns if column["name"] not in old]
    assert newer, "the table has the columns of the Bauplan"
    missing = [column["name"] for column in newer if column["notnull"] and column["dflt_value"] is None]
    assert missing == []


def test_the_older_version_adds_providers_and_links_on_a_fresh_database(net: Any) -> None:
    """Wie 1.3.0 Zeilen anlegt (nur ihre Spalten): Das geht, und der naechste Start uebernimmt den Eintrag."""
    sso = net.add(fakes.FakeProvider())
    user = create_user("alex")
    provider = _old_provider("sso", sso.issuer.rstrip("/"), sso.client_id, sso.client_secret, auto_create=True)
    _old_link(provider, user, "person-1")
    init_db()
    row = _row("sso")
    assert row.redirect_path == "/api/auth/oidc/sso/callback" and row.trusts_second_factor and row.position == 0
    browser = TestClient(app)
    response = _round_trip(browser, sso, "sso")
    assert response.headers["location"] == "/" and _who(browser) == "alex"


# --- Sitzung, Bremse, Routen -----------------------------------------------------------------------------------------


def test_the_session_cookie_lies_under_api_and_the_old_one_goes(client: TestClient) -> None:
    assert client.post("/api/setup/admin", json=ADMIN).status_code == 201
    response = client.post("/api/auth/login", json={"login": ADMIN["username"], "password": ADMIN["password"]})
    cookies = response.headers.get_list("set-cookie")
    current = [c for c in cookies if c.startswith("nexbeat_refresh=") and "Path=/api;" in c and "Max-Age=0" not in c]
    gone = [c for c in cookies if c.startswith("nexbeat_refresh=") and "Path=/api/auth" in c]
    assert len(current) == 1 and len(gone) == 1
    assert "Max-Age=0" in gone[0]


def test_a_return_without_a_valid_attempt_never_feeds_the_brake(admin_client: TestClient, net: Any) -> None:
    sso = net.add(fakes.FakeProvider())
    _add(admin_client, sso, "sso")
    stranger = TestClient(app)
    for _ in range(12):
        for path in (
            "/api/oidc/sso/callback?error=access_denied&state=x",
            "/api/oidc/nobody/callback?code=x&state=y",
            "/api/oidc/sso/callback?code=garbage&state=garbage",
            "/api/auth/oidc/sso/callback?error=x",
        ):
            assert stranger.get(path, follow_redirects=False).status_code == 303
    assert anmeldebremse.wait_seconds(anmeldebremse.oidc_key("testclient")) == 0
    # Ein echter Anlauf, der beim Anbieter scheitert, zaehlt dagegen.
    refused = []
    for _ in range(anmeldebremse.FREE_ATTEMPTS + 1):
        started = stranger.get("/api/oidc/sso/start", follow_redirects=False)
        state = fakes.query_of(started.headers["location"])["state"]
        back = stranger.get(f"/api/oidc/sso/callback?code=unknown&state={state}", follow_redirects=False)
        refused.append(back.headers["location"])
    assert refused == ["/login?error=oidc_token_refused"] * (anmeldebremse.FREE_ATTEMPTS + 1)
    assert anmeldebremse.wait_seconds(anmeldebremse.oidc_key("testclient")) > 0
    braked = stranger.get("/api/oidc/sso/start", follow_redirects=False)
    assert braked.headers["location"] == "/login?error=too_many_attempts"


def test_a_provider_named_authentik_is_not_hidden_by_the_fixed_routes(admin_client: TestClient, net: Any) -> None:
    sso = net.add(fakes.FakeProvider())
    _add(admin_client, sso, "authentik", label="authentik", auto_create=True)
    browser = TestClient(app)
    response = _round_trip(browser, sso, "authentik")
    assert response.headers["location"] == "/" and _who(browser) == "alex"
    assert admin_client.get("/api/oidc/authentik/address").status_code == 200


def test_a_linking_return_sees_the_session_of_the_browser(admin_client: TestClient, net: Any) -> None:
    sso = net.add(fakes.FakeProvider())
    _add(admin_client, sso, "sso")
    create_user("kim")
    browser = TestClient(app)
    headers = auth_headers(browser, "kim")
    answer = browser.post("/api/oidc/sso/link", json={"password": USER_PASSWORD}, headers=headers)
    assert answer.status_code == 200, answer.text
    url = answer.json()["url"]
    callback = fakes.query_of(url)["redirect_uri"].split("://", 1)[1].split("/", 1)[1]
    back = browser.get(f"/{callback}", params=sso.authorize(url), follow_redirects=False)
    assert back.headers["location"] == "/profil?linked=sso"
    with SessionLocal() as db:
        assert [link.subject for link in db.scalars(select(OidcLink))] == ["person-1"]


def test_linking_asks_the_password_and_an_api_token_cannot(admin_client: TestClient, net: Any) -> None:
    sso = net.add(fakes.FakeProvider())
    _add(admin_client, sso, "sso")
    create_user("kim")
    browser = TestClient(app)
    headers = auth_headers(browser, "kim")
    wrong = browser.post("/api/oidc/sso/link", json={"password": "not-it"}, headers=headers)
    assert wrong.status_code == 400 and wrong.json()["detail"]["code"] == "wrong_password"
    token = browser.post("/api/auth/me/keys", json={"name": "deck"}, headers=headers)
    assert token.status_code == 201, token.text
    key = {"Authorization": f"Bearer {token.json()['token']}"}
    refused = browser.post("/api/oidc/sso/link", json={"password": USER_PASSWORD}, headers=key)
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "api_key_not_here"
    # Der Token-Weg fuer nexdeck bleibt, wie er war.
    assert browser.get("/api/v1/me", headers=key).status_code == 200


# --- Oeffentliche Adresse und Passwort-Anmeldung ----------------------------------------------------------------------


def test_saving_or_clearing_the_public_address_asks_while_a_provider_knows_it(
    admin_client: TestClient, net: Any
) -> None:
    sso = net.add(fakes.FakeProvider())
    assert admin_client.put("/api/settings", json={"public_url": "https://music.example.com"}).status_code == 200
    _add(admin_client, sso, "sso")
    for wanted in ("https://other.example.com", ""):
        asked = admin_client.put("/api/settings", json={"public_url": wanted})
        assert asked.status_code == 409, asked.text
        assert asked.json()["detail"]["code"] == "public_url_change" and asked.json()["detail"]["hand"] == 1
        assert admin_client.get("/api/settings").json()["public_url"] == "https://music.example.com"
    done = admin_client.put("/api/settings", json={"public_url": "", "confirm_address": True})
    assert done.status_code == 200 and done.json()["public_url"] == ""
    # Unveraendert gespeichert fragt nichts.
    assert admin_client.put("/api/settings", json={"public_url": ""}).status_code == 200


@pytest.mark.parametrize(
    "address", ["https://exa mple.com", "https://music.example.com/?x=1", "https://user@music.example.com", "ftp://x.y"]
)
def test_the_public_address_is_no_laxer_than_the_module(admin_client: TestClient, address: str) -> None:
    refused = admin_client.put("/api/settings", json={"public_url": address})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "invalid_setting"


def test_password_sign_in_switches_off_only_with_an_active_provider(admin_client: TestClient, net: Any) -> None:
    refused = admin_client.put("/api/settings", json={"password_login": False})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "password_login_needs_provider"
    sso = net.add(fakes.FakeProvider())
    made = _add(admin_client, sso, "sso")
    assert admin_client.put("/api/settings", json={"password_login": False}).status_code == 200
    create_user("kim")
    other = TestClient(app)
    off = other.post("/api/auth/login", json={"login": "kim", "password": USER_PASSWORD})
    assert off.status_code == 403 and off.json()["detail"]["code"] == "password_login_off"
    assert other.get("/api/config").json()["password_login"] is False
    # Der Admin kommt immer mit Passwort herein (Rueckweg, falls der Anbieter ausfaellt).
    assert other.post("/api/auth/login", json={"login": "admin", "password": ADMIN["password"]}).status_code == 200
    # Ohne aktiven Anbieter gilt das Passwort wieder fuer alle.
    body = {"label": "SSO", "issuer": sso.issuer, "client_id": sso.client_id, "enabled": False}
    assert admin_client.put(f"/api/oidc/admin/providers/{made['id']}", json=body).status_code == 200
    assert other.post("/api/auth/login", json={"login": "kim", "password": USER_PASSWORD}).status_code == 200
    assert other.get("/api/config").json()["password_login"] is True


def test_the_account_list_shows_the_links_of_each_account(admin_client: TestClient, net: Any) -> None:
    sso = net.add(fakes.FakeProvider())
    _add(admin_client, sso, "sso", auto_create=True)
    browser = TestClient(app)
    _round_trip(browser, sso, "sso")
    listed = {user["username"]: user for user in admin_client.get("/api/users").json()}
    assert [(item["slug"], item["label"]) for item in listed["alex"]["providers"]] == [("sso", "SSO")]
    assert listed["alex"]["has_password"] is False and listed["admin"]["providers"] == []
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "alex"))
        assert user is not None and user.email == "alex@example.com" and user.role.value == "user"


# --- Proxy -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("headers", "scheme"),
    [
        ([(b"x-forwarded-proto", b"https")], "https"),
        ([(b"x-forwarded-proto", b"HTTPS")], "https"),
        ([(b"x-forwarded-proto", b"http, https")], "https"),
        ([(b"x-forwarded-proto", b"https, http")], "http"),
        ([(b"X-Forwarded-Proto", b" https ")], "https"),
        ([(b"x-forwarded-proto", b"wss")], None),
        ([(b"x-forwarded-proto", b"gopher")], None),
        ([], None),
    ],
)
def test_the_scheme_is_the_rightmost_value_without_regard_to_case(headers: list, scheme: str | None) -> None:
    assert forwarded_scheme(headers) == scheme


@pytest.mark.parametrize(
    ("peer", "kind", "header", "seen"),
    [
        ("127.0.0.1", "http", b"http, HTTPS", "https"),
        ("127.0.0.1", "http", b"wss", "http"),
        ("127.0.0.1", "websocket", b"https", "wss"),
        ("203.0.113.9", "http", b"https", "http"),
    ],
)
async def test_only_a_trusted_proxy_is_believed(peer: str, kind: str, header: bytes, seen: str) -> None:
    found: dict[str, str] = {}

    async def inner(scope: dict, _receive: Any, _send: Any) -> None:
        found["scheme"] = scope["scheme"]

    wrapped = behind_proxy(inner, "127.0.0.1")
    scope = {
        "type": kind,
        "scheme": "ws" if kind == "websocket" else "http",
        "client": (peer, 5000),
        "headers": [(b"x-forwarded-proto", header), (b"x-forwarded-for", b"198.51.100.4")],
    }
    await wrapped(scope, None, None)
    assert found["scheme"] == seen
