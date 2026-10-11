"""The contract between the shared tests and an app: ``StandardAdapter``.

The tests in this folder (Pflichttests 1 to 32 of Bauplan 05) are the same in every app and are copied unchanged
by ``tools/sync.py``. What differs between apps (how an account is made, how one signs in with a password, where
the routes are) the app answers in ``backend/tests/nexoidc_adapter.py``: a class ``Adapter(StandardAdapter)``.
Everything marked "APP:" below must be written there; everything else has a default for the standard routes
(``reference/app.py``) and is overridden only when the app differs.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from contextlib import AbstractContextManager
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
import oidc_fakes as fakes


class StandardAdapter:
    #: Import path of the vendored package in the app.
    package = "app.vendor.nexoidc"
    #: The API prefix (``AppConfig.api_prefix``).
    api = "/api"
    #: nexcrate, nexsift: one account (Bauplan 06). Then invitations and new accounts are refused instead.
    single_account = False
    #: The app has invitations (since 1.0.12). False for nexdeck, nexsift and nexcrate: the tests of an invitation are
    #: skipped with the reason, and what they check besides it is checked through ``auto_create``. Apps with one
    #: account have none either; they keep their own answers (``single_account``).
    has_invitations = True
    #: nexsuite: only authentik, no second entry through the form (Bauplan 06). Entries are then made in the store.
    only_authentik = False
    #: The app can be coupled to nexsuite (Bauplan 06). False for the apps with one account (nexcrate, nexsift): they
    #: have no people to pair, and the coupling test checks instead that the list stays uncoupled.
    supports_coupling = True
    #: The app has a second factor of its own.
    has_second_factor = True
    #: "single": the app kept one provider in its settings and migrates (Pflichttest 22); "list" or "none": not.
    legacy_model = "single"
    #: legacy_model "single": how the version before the list behaved after the provider, as the app passes it to
    #: ``migrate.plan`` and ``migrate.resync`` (Bauplan 06 "Wanderung"): True asked no code, False (nexdiary, nexpaper)
    #: asked it.
    trusted_before = True
    #: Callback paths the app's providers knew before the module, with ``{slug}`` (nexbeat
    #: ``/api/auth/oidc/{slug}/callback``); the app routes them to the same return. Empty: none.
    old_callback_paths: tuple[str, ...] = ()
    #: The account the operator signs in with (its password: ``self.password_for(operator_name)``).
    operator_name = "operator"
    #: How the app refuses an operator route: without a session, and to a signed-in member. Override when the app
    #: answers otherwise (some say 404 to hide a route).
    anonymous_status: tuple[int, ...] = (401,)
    member_status: tuple[int, ...] = (403,)
    #: Where a successful sign-in ends, a refused one, and a second factor that is asked.
    home = "/"
    login_page = "/login"
    account_page = "/account"
    #: The address the test browser uses (``browser()``'s ``base_url``, with the app's base path if it has one): what
    #: the authentik card suggests as the public address when the app has none (since 1.0.10).
    origin = "http://testserver"

    def __init__(self) -> None:
        self.passwords: dict[str, str] = {}

    # --- APP: the app's own side ------------------------------------------------------------------------------------
    def start(self) -> None:
        """APP: an empty app (fresh database, nexoidc configured), before every test."""
        raise NotImplementedError

    def stop(self) -> None:
        """APP: clean up after every test."""

    def browser(self) -> Any:
        """APP: a new browser without session: a TestClient that does not follow redirects."""
        raise NotImplementedError

    def operator(self) -> Any:
        """APP: a browser signed in as the operator (with password ``self.passwords[<operator name>]``)."""
        raise NotImplementedError

    def make_account(self, name: str, *, password: bool = True, second_factor: bool = False) -> int:
        """APP: a member account; with ``password`` it gets ``self.password_for(name)``. Returns its id."""
        raise NotImplementedError

    def sign_in_with_password(self, client: Any, name: str) -> None:
        """APP: sign ``client`` in as ``name`` with its password."""
        raise NotImplementedError

    def who(self, client: Any) -> str | None:
        """APP: the name of the account ``client`` is fully signed in as (second factor done), else None."""
        raise NotImplementedError

    def second_factor_asked(self, client: Any, response: httpx.Response) -> bool:
        """APP: after the return from the provider, does the app ask for the code of its own second factor?"""
        raise NotImplementedError

    def make_invite(self, rights: str) -> str:
        """APP: an open invitation granting ``rights``; its key. Single account or ``has_invitations`` False:
        unused."""
        raise NotImplementedError

    def rights_of(self, name: str) -> str | None:
        """APP: the rights of an account in the words ``make_invite`` takes ("member" for a plain member)."""
        raise NotImplementedError

    def account_names(self) -> list[str]:
        """APP: the names of all accounts."""
        raise NotImplementedError

    def store(self) -> AbstractContextManager[Any]:
        """APP: the app's ``Store`` for one transaction (a context manager)."""
        raise NotImplementedError

    def trip_throttle(self, client: Any) -> None:
        """APP: make the app's brake hold this browser back (Bauplan 02, "Ablauf" 4), as many failed attempts from
        its sender would: the next start and the next return are refused with ``too_many_attempts``."""
        raise NotImplementedError

    def set_public_url(self, url: str) -> None:
        """APP: the public address of the app (setting)."""
        raise NotImplementedError

    def read_public_url(self) -> str:
        """APP (since 1.0.10): the public address as the app's setting holds it now, "" for none (what
        ``AppConfig.save_public_url`` stored)."""
        raise NotImplementedError

    def legacy_setup(
        self, *, issuer: str, client_id: str, client_secret: str, label: str, subjects: dict[str, str]
    ) -> None:
        """APP (legacy_model "single"): write the old settings and ``oidc_subject`` per account name, as the app did
        before the module."""
        raise NotImplementedError

    def run_migration(self) -> None:
        """APP (legacy_model "single"): what the app runs at every start-up: the migration to the provider list once;
        after it, ``migrate.resync`` with the fingerprint stored at the last mirror; then the mirror and the new
        fingerprint (since 1.0.9). ``legacy_setup`` between two calls is the version before the list at work."""
        raise NotImplementedError

    def legacy_read(self) -> dict[str, Any]:
        """APP (legacy_model "single", since 1.0.9): the old settings and ``oidc_subject`` as the app has them now
        (what the version before the list would find): ``issuer``, ``client_id``, ``client_secret`` (decrypted),
        ``label``, ``auto_create`` (bool, since 1.0.10) and ``subjects`` (account name to subject, accounts without
        one left out)."""
        raise NotImplementedError

    def delete_account(self, name: str) -> None:
        """APP (legacy_model "single" with more than one account, since 1.0.10): delete the account ``name`` the way
        the app does it (its own service or route, not the store), committed."""
        raise NotImplementedError

    # --- standard routes (override when the app differs) ------------------------------------------------------------
    def password_for(self, name: str) -> str:
        return self.passwords.setdefault(name, secrets.token_urlsafe(12))

    def path(self, name: str, **values: Any) -> str:
        api = self.api
        paths = {
            "public": f"{api}/oidc/providers",
            "providers": f"{api}/oidc/admin/providers",
            "provider": f"{api}/oidc/admin/providers/{values.get('id')}",
            "impact": f"{api}/oidc/admin/providers/{values.get('id')}/impact",
            "start": f"{api}/oidc/{values.get('slug')}/start",
            "callback": f"{api}/oidc/{values.get('slug')}/callback",
            "legacy_callback": f"{api}/oidc/callback",
            "me": f"{api}/oidc/me",
            "link": f"{api}/oidc/{values.get('slug')}/link",
            "setup": f"{api}/oidc/authentik/setup",
            "address": f"{api}/oidc/authentik/address",
            "blueprint": f"{api}/oidc/authentik/blueprint",
            "order": f"{api}/oidc/admin/providers/order",
            "operator_unlink": f"{api}/oidc/admin/accounts/{values.get('account')}/links/{values.get('provider')}",
        }
        return paths[name]

    def error_code(self, response: httpx.Response) -> str:
        """The code of a refused JSON request. Standard: ``{"detail": {"code": ...}}``."""
        detail = response.json().get("detail")
        return str(detail.get("code") if isinstance(detail, dict) else detail)

    def add_provider(
        self, fake: fakes.FakeProvider, *, slug: str, label: str = "SSO", issuer: str | None = None, **form: Any
    ) -> httpx.Response:
        body = {
            "label": label,
            "slug": slug,
            "issuer": issuer or fake.issuer,
            "client_id": fake.client_id,
            "client_secret": fake.client_secret,
            **form,
        }
        return self.operator().post(self.path("providers"), json=body)

    def providers(self) -> list[dict[str, Any]]:
        response = self.operator().get(self.path("providers"))
        assert response.status_code == 200, response.text
        return response.json()

    def save_provider(self, provider_id: int, body: dict[str, Any]) -> httpx.Response:
        return self.operator().put(self.path("provider", id=provider_id), json=body)

    def remove_provider(self, provider_id: int) -> httpx.Response:
        return self.operator().delete(self.path("provider", id=provider_id))

    def impact(self, provider_id: int, issuer: str = "") -> dict[str, Any]:
        response = self.operator().get(self.path("impact", id=provider_id), params={"issuer": issuer} if issuer else {})
        assert response.status_code == 200, response.text
        return response.json()

    def link_start(self, client: Any, slug: str, password: str) -> httpx.Response:
        return client.post(self.path("link", slug=slug), json={"password": password})

    def unlink(self, client: Any, slug: str) -> httpx.Response:
        return client.delete(self.path("link", slug=slug))

    def setup_authentik(
        self,
        url: str,
        token: str,
        *,
        confirm_issuer_change: bool = False,
        public_url: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """The button as the card presses it. ``public_url`` None: the card's "Use it and set up", which sends the
        browser's own address (``origin``; the server takes it only while the app has none); "": nothing confirmed."""
        body: dict[str, Any] = {"url": url, "token": token}
        if confirm_issuer_change:
            body["confirm_issuer_change"] = True
        confirmed = self.origin if public_url is None else public_url
        if confirmed:
            body["public_url"] = confirmed
        return self.operator().post(self.path("setup"), json=body, headers=headers or {})

    def adopt_only(self, url: str, *, confirm: bool = False) -> httpx.Response:
        """The card's "Use it only": the module's route ``POST <api>/oidc/authentik/address`` (since
        1.0.10). 200 saved (``address_view``), 409 ``public_url_change`` asks first, 422 ``public_url_invalid``."""
        body: dict[str, Any] = {"public_url": url}
        if confirm:
            body["confirm"] = True
        return self.operator().post(self.path("address"), json=body)

    def save_public_url_route(self, url: str, *, confirm: bool = False) -> httpx.Response:
        """APP if card 1 (or another settings page of the app) saves the public address in a route of its own (since
        1.0.10): save ``url`` there as the operator does, ``confirm`` after ``oidc.admin.addressChangeConfirm``. That
        route asks ``authentik.public_url_guard`` first and answers its question with 409, code
        ``public_url_change`` (``error_code``) and the question's fields (``error_detail``: ``count``, ``address``,
        ``hand``), saving nothing. Standard: the module's route (``adopt_only``)."""
        return self.adopt_only(url, confirm=confirm)

    def error_detail(self, response: httpx.Response) -> dict[str, Any]:
        """The fields of a refused JSON request beside its code. Standard: ``{"detail": {...}}``."""
        detail = response.json().get("detail")
        return detail if isinstance(detail, dict) else {}

    def address(self, headers: dict[str, str] | None = None) -> dict[str, Any]:
        """What the authentik card shows about the public address (``authentik.address_view``)."""
        response = self.operator().get(self.path("address"), headers=headers or {})
        assert response.status_code == 200, response.text
        return response.json()

    def blueprint(self) -> httpx.Response:
        return self.operator().get(self.path("blueprint"))

    def member(self) -> Any:
        """A browser signed in as a plain member (a new account each time)."""
        name = f"member{secrets.token_hex(3)}"
        self.make_account(name)
        browser = self.browser()
        self.sign_in_with_password(browser, name)
        return browser

    def operator_unlink(self, client: Any, account_id: int, provider_id: int, password: str) -> httpx.Response:
        """The operator removes an account's link, with the operator's own password (Bauplan 01)."""
        path = self.path("operator_unlink", account=account_id, provider=provider_id)
        return client.request("DELETE", path, json={"password": password})

    def operator_routes(self, provider_id: int, account_id: int) -> list[tuple[str, str, Any]]:
        """Every operator route of the module: (method, path, JSON body)."""
        form = {"label": "x", "issuer": "https://x.example.com", "client_id": "x"}
        return [
            ("GET", self.path("providers"), None),
            ("POST", self.path("providers"), {**form, "slug": "intruder"}),
            ("PUT", self.path("provider", id=provider_id), form),
            ("DELETE", self.path("provider", id=provider_id), None),
            ("GET", self.path("impact", id=provider_id), None),
            ("PUT", self.path("order"), {"ids": [provider_id]}),
            ("POST", self.path("setup"), {"url": "https://auth.example.com", "token": "t"}),
            ("GET", self.path("address"), None),
            ("POST", self.path("address"), {"public_url": "https://intruder.example.com"}),
            ("GET", self.path("blueprint"), None),
            ("DELETE", self.path("operator_unlink", account=account_id, provider=provider_id), {"password": "x"}),
        ]


# --- helpers the tests share ---


def location(response: httpx.Response) -> str:
    assert response.status_code in (302, 303, 307), (response.status_code, response.text[:200])
    return response.headers["location"]


def error_in(response: httpx.Response) -> str | None:
    """The ``error`` of a redirect to the sign-in or account page, else None."""
    query = dict(item.split("=", 1) for item in urlsplit(location(response)).query.split("&") if "=" in item)
    return query.get("error")


def start(adapter: StandardAdapter, client: Any, slug: str, *, invite: str | None = None) -> httpx.Response:
    params = {"invite": invite} if invite is not None else {}
    return client.get(adapter.path("start", slug=slug), params=params)


def come_back(
    adapter: StandardAdapter,
    client: Any,
    slug: str,
    params: dict[str, str],
    *,
    legacy: bool = False,
    path: str | None = None,
) -> httpx.Response:
    """The browser back at the app. ``path``: the callback the app sent to the provider (taken from the start, so an
    entry with an old callback comes back there), else the standard one."""
    if path is None:
        path = adapter.path("legacy_callback") if legacy else adapter.path("callback", slug=slug)
    return client.get(f"{path}?{urlencode(params)}")


def sent_callback(target: str) -> str:
    """The callback path the app named in its redirect to the provider."""
    return urlsplit(fakes.query_of(target)["redirect_uri"]).path


def round_trip(
    adapter: StandardAdapter,
    fake: fakes.FakeProvider,
    slug: str,
    *,
    client: Any = None,
    invite: str | None = None,
    legacy: bool = False,
) -> tuple[Any, httpx.Response]:
    """A browser through start, provider and return: (the browser, the answer of the return)."""
    browser = client if client is not None else adapter.browser()
    target = location(start(adapter, browser, slug, invite=invite))
    path = None if legacy else sent_callback(target)
    return browser, come_back(adapter, browser, slug, fake.authorize(target), legacy=legacy, path=path)


def link_person(adapter: StandardAdapter, name: str, slug: str, fake: fakes.FakeProvider) -> None:
    """Link the account ``name`` to the fake's current person the way a person does it: signed in with the password,
    "Link" with the password again, the provider, back to the account page."""
    browser = adapter.browser()
    adapter.sign_in_with_password(browser, name)
    answer = adapter.link_start(browser, slug, adapter.password_for(name))
    assert answer.status_code == 200, answer.text
    url = answer.json()["url"]
    back = come_back(adapter, browser, slug, fake.authorize(url), path=sent_callback(url))
    assert error_in(back) is None, location(back)
    assert location(back).startswith(adapter.account_page)


def entry(adapter: StandardAdapter, slug: str) -> dict[str, Any]:
    found = [item for item in adapter.providers() if item["slug"] == slug]
    assert found, f"no entry {slug}"
    return found[0]


def form_of(item: dict[str, Any], **changes: Any) -> dict[str, Any]:
    """The provider form as the page sends it back unchanged (no secret: keeps the stored one)."""
    body = {
        key: item[key]
        for key in ("label", "issuer", "client_id", "scopes", "enabled", "auto_create", "trusts_second_factor")
    }
    body.update(client_secret="", **changes)
    return body


def iterate(value: Any) -> Iterator[Any]:
    yield from value
