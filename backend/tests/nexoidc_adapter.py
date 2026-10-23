"""nexoidc contract tests: nexbeat's adapter (from the module's adapter template).

The contract tests in ``tests/nexoidc/`` are the same in every app and never edited here. Everything nexbeat does its
own way is answered below: accounts in ``users``, invitations in ``auth_tokens``, a sign-in that answers with an access
token in the body and keeps the session in the cookie ``nexbeat_refresh``.

nexbeat had a provider list before the module (1.3.0, ``legacy_model = "list"``); its providers know the redirect
address ``/api/auth/oidc/<slug>/callback``. nexbeat has no second factor of its own and is never coupled to another app.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any

import httpx
from fastapi.testclient import TestClient
from oidc_contract import StandardAdapter
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import Role, TokenPurpose, User
from app.security import UNUSABLE_PASSWORD, hash_password
from app.services import anmeldebremse, tokens
from app.services.oidc_store import SqlStore
from app.services.settings_service import load_settings, save_settings

OPERATOR = "operator"


class Adapter(StandardAdapter):
    package = "app.vendor.nexoidc"
    api = "/api"
    single_account = False
    has_invitations = True  # nexbeat has invitations (auth_tokens)
    only_authentik = False
    # nexbeat is never coupled to another app.
    supports_coupling = False
    has_second_factor = False
    legacy_model = "list"
    trusted_before = True
    old_callback_paths: tuple[str, ...] = ("/api/auth/oidc/{slug}/callback",)
    operator_name = OPERATOR
    origin = "http://testserver"
    anonymous_status: tuple[int, ...] = (401,)
    member_status: tuple[int, ...] = (403,)
    account_page = "/profil"

    def start(self) -> None:
        # The database is emptied by ``clean_db`` in ``tests/conftest.py`` before every test.
        self._operator: TestClient | None = None
        browser = self.browser()
        made = browser.post(
            "/api/setup/admin",
            json={
                "username": OPERATOR,
                "email": "operator@example.com",
                "password": self.password_for(OPERATOR),
                "language": "en",
            },
        )
        assert made.status_code == 201, made.text

    def browser(self) -> TestClient:
        return TestClient(app, base_url="http://testserver", follow_redirects=False)

    def operator(self) -> TestClient:
        if self._operator is None:
            self._operator = self.browser()
            self.sign_in_with_password(self._operator, OPERATOR)
        return self._operator

    def make_account(self, name: str, *, password: bool = True, second_factor: bool = False) -> int:
        assert not second_factor, "nexbeat has no second factor of its own"
        with SessionLocal() as db:
            user = User(
                username=name,
                email=f"{name}@example.com",
                password_hash=hash_password(self.password_for(name)) if password else UNUSABLE_PASSWORD,
                display_name=name,
                role=Role.user,
            )
            db.add(user)
            db.commit()
            return user.id

    def sign_in_with_password(self, client: Any, name: str) -> None:
        response = client.post("/api/auth/login", json={"login": name, "password": self.password_for(name)})
        assert response.status_code == 200, response.text
        client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"

    def who(self, client: Any) -> str | None:
        # The session is the refresh cookie (the return from a provider sets nothing else). The page does what it
        # does after every load: it trades the cookie for an access token and sends that along from then on.
        refreshed = client.post("/api/auth/refresh", headers={"Authorization": ""})
        if refreshed.status_code != 200:
            client.headers.pop("Authorization", None)
            return None
        client.headers["Authorization"] = f"Bearer {refreshed.json()['access_token']}"
        me = client.get("/api/auth/me")
        return me.json()["username"] if me.status_code == 200 else None

    def second_factor_asked(self, client: Any, response: httpx.Response) -> bool:
        return False

    def make_invite(self, rights: str) -> str:
        role = Role.admin if rights == "editor" else Role.user
        with SessionLocal() as db:
            operator = db.scalar(select(User).where(User.username == OPERATOR))
            raw, _token = tokens.create(
                db,
                TokenPurpose.invitation,
                f"invited-{secrets.token_hex(4)}@example.com",
                created_by=operator.id if operator else None,
                invite_role=role,
            )
        return raw

    def rights_of(self, name: str) -> str | None:
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.username == name))
            if user is None:
                return None
            return "editor" if user.role == Role.admin else "member"

    def account_names(self) -> list[str]:
        with SessionLocal() as db:
            return sorted(db.scalars(select(User.username)))

    def store(self) -> AbstractContextManager[Any]:
        @contextmanager
        def opened() -> Iterator[SqlStore]:
            with SessionLocal() as db:
                yield SqlStore(db)

        return opened()

    def trip_throttle(self, client: Any) -> None:
        # nexbeat's brake counts start and return per sender; every TestClient comes from "testclient".
        for _ in range(8):
            anmeldebremse.failed(anmeldebremse.oidc_key("testclient"))

    def set_public_url(self, url: str) -> None:
        with SessionLocal() as db:
            save_settings(db, {"public_url": url})

    def read_public_url(self) -> str:
        with SessionLocal() as db:
            return load_settings(db).public_url

    def save_public_url_route(self, url: str, *, confirm: bool = False) -> httpx.Response:
        """Card 1 saves the public address through ``PUT /api/settings``, which asks the module first."""
        body: dict[str, Any] = {"public_url": url}
        if confirm:
            body["confirm_address"] = True
        return self.operator().put("/api/settings", json=body)
