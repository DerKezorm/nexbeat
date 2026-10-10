"""Contract: the addresses (Bauplan 01 "Umstieg", 02 "Ablauf", 03 "Blueprint", 06 "Pfad der Schnittstelle" and
"Verbund"): ``Secure`` behind HTTPS, the blueprint's callback entered by hand, old callbacks per entry, the coupling."""

from __future__ import annotations

from http.cookies import SimpleCookie
from typing import Any

import oidc_fakes as fakes
from conftest import add_in_store, oidc_package
from oidc_contract import entry, error_in, link_person, location, round_trip, start


def _cookies(response: Any) -> SimpleCookie:
    cookies = SimpleCookie()
    for header in response.headers.get_list("set-cookie"):
        cookies.load(header)
    return cookies


def test_01_behind_https_the_attempt_cookie_is_secure(
    adapter: Any, oidc: Any, sso: fakes.FakeProvider, with_sso: dict
) -> None:
    name = oidc.current().cookie_name
    plain = _cookies(start(adapter, adapter.browser(), "sso"))[name]
    assert not plain["secure"]
    adapter.set_public_url("https://app.example.com")
    response = start(adapter, adapter.browser(), "sso")
    assert fakes.query_of(location(response))["redirect_uri"].startswith("https://app.example.com/")
    assert _cookies(response)[name]["secure"]


def test_32_the_blueprints_callback_entered_by_hand_signs_in_and_the_button_takes_the_entry_later(
    adapter: Any, oidc: Any, net: fakes.Network
) -> None:
    ak = net.add(fakes.FakeAuthentik())
    # The blueprint names a redirect address behind the public address only (1.0.10).
    adapter.set_public_url(adapter.origin)
    blueprint = adapter.blueprint()
    assert blueprint.status_code == 200
    app = oidc.current().app_name
    callback = f"/{adapter.api.strip('/')}/oidc/authentik/callback"
    assert callback in blueprint.text
    # As if the operator applied the blueprint: provider and application with the plain names.
    made = ak.add_provider(app, adapter.origin + callback, slug=app)
    issuer = f"{ak.base}/application/o/{app}/"
    signer = ak.sign_in_with(issuer, made["client_id"], made["client_secret"])
    if adapter.only_authentik:
        saved = add_in_store(adapter, signer, "authentik", label="authentik", issuer=issuer)
    else:
        response = adapter.add_provider(signer, slug="authentik", label="authentik", issuer=issuer)
        assert response.status_code in (200, 201), response.text
        saved = response.json()
        assert saved["redirect_uri"].endswith(callback)
    adapter.make_account("alex")
    link_person(adapter, "alex", "authentik", signer)
    browser, response = round_trip(adapter, signer, "authentik")
    assert location(response) == adapter.home and adapter.who(browser) == "alex"
    result = adapter.setup_authentik(ak.base, ak.token).json()
    assert result["ok"] and result["links_dropped"] == 0 and result["provider_id"] == saved["id"]
    item = entry(adapter, "authentik")
    assert item["managed"] == "authentik" and len(ak.providers) == 1
    assert ak.providers[0]["redirect_uris"][0]["url"].endswith(callback)
    assert adapter.who(round_trip(adapter, signer, "authentik")[0]) == "alex"


def test_22_an_entry_with_an_old_callback_signs_in_there(adapter: Any, oidc: Any, sso: fakes.FakeProvider) -> None:
    standard = add_in_store(adapter, sso, "plain")
    with adapter.store() as store:
        assert store.get_provider(standard["id"]).redirect_path == ""
    target = location(start(adapter, adapter.browser(), "plain"))
    assert fakes.query_of(target)["redirect_uri"].endswith(adapter.path("callback", slug="plain"))
    for number, template in enumerate(adapter.old_callback_paths):
        slug = f"old{number}"
        old = oidc.migrate.old_callback(template, slug)
        other = fakes.FakeProvider(f"https://old{number}.example.com")
        _network(adapter).add(other)
        made = add_in_store(adapter, other, slug)
        with adapter.store() as store:
            row = store.get_provider(made["id"])
            store.update_provider(row.id, oidc.providers.values_of(row, redirect_path=old))
            store.commit()
        assert entry(adapter, slug)["redirect_uri"].endswith(old)
        adapter.make_account(f"person{number}")
        link_person(adapter, f"person{number}", slug, other)
        browser, response = round_trip(adapter, other, slug)
        assert location(response) == adapter.home and adapter.who(browser) == f"person{number}"


def test_06_coupling_sets_the_own_entries_aside_and_uncoupling_puts_them_back(
    adapter: Any, oidc: Any, sso: fakes.FakeProvider, with_sso: dict, net: fakes.Network
) -> None:
    if not adapter.supports_coupling:
        # Apps with one account are never coupled (Bauplan 06 names only the apps of the Verbund): the list stays
        # the app's own, editable, and the authentik button is not held back.
        with adapter.store() as store:
            assert not oidc.providers.coupled(store)
        assert all(item["editable"] and item["managed"] != "nexsuite" for item in adapter.providers())
        ak = net.add(fakes.FakeAuthentik())
        reasons = [step.get("reason") for step in adapter.setup_authentik(ak.base, ak.token).json()["steps"]]
        assert "coupled" not in reasons and ak.calls
        return
    suite = net.add(fakes.FakeProvider("https://suite.example.com"))
    # The app's own migrated entry holds the slug nexsuite needs: it is parked while coupled.
    own = net.add(fakes.FakeProvider("https://own.example.com"))
    add_in_store(adapter, own, "oidc", label="Own")
    alex_id = adapter.make_account("alex")
    link_person(adapter, "alex", "sso", sso)
    bob_id = adapter.make_account("bob")
    with adapter.store() as store:
        joined = oidc.coupling.couple(
            store,
            issuer=suite.issuer,
            client_id=suite.client_id,
            client_secret=suite.client_secret,
            label="Suite",
            people=[(alex_id, "p-alex"), (bob_id, "person-1")],
        )
    public = adapter.browser().get(adapter.path("public")).json()
    assert [(item["slug"], item["label"]) for item in public] == [("oidc", "Suite")]
    # Bauplan 06: the set-aside entries stay in the list, off, and the whole list is read-only.
    listed = {item["slug"]: item for item in adapter.providers()}
    assert set(listed) == {"oidc", "oidc-own", "sso"}
    assert listed["oidc"]["managed"] == "nexsuite" and listed["oidc"]["enabled"]
    assert not listed["sso"]["enabled"] and not listed["oidc-own"]["enabled"]
    assert not any(item["editable"] for item in listed.values())
    # Subject "person-1" of the own provider is alex; person "person-1" of nexsuite is bob.
    browser, response = round_trip(adapter, suite, "oidc")
    assert fakes.query_of(location(start(adapter, adapter.browser(), "oidc")))["redirect_uri"].endswith(
        adapter.path("legacy_callback")
    )
    assert location(response) == adapter.home and adapter.who(browser) == "bob"
    assert error_in(start(adapter, adapter.browser(), "sso")) == "oidc_not_configured"
    # While coupled the authentik button touches neither authentik nor the list (the app locks its card too).
    ak = net.add(fakes.FakeAuthentik())
    answer = adapter.setup_authentik(ak.base, ak.token)
    assert answer.status_code == 200 and ak.calls == []
    assert [(step["key"], step["reason"], step["status"]) for step in answer.json()["steps"]] == [
        ("reached", "coupled", 0)
    ]
    assert len(adapter.providers()) == 3
    with adapter.store() as store:
        oidc.coupling.uncouple(store, oidc.coupling.Coupling.from_dict(joined.as_dict()))
    assert sorted(item["slug"] for item in adapter.browser().get(adapter.path("public")).json()) == ["oidc", "sso"]
    with adapter.store() as store:
        assert store.provider_by_slug("oidc").managed == "" and store.provider_by_slug("oidc").label == "Own"
    assert adapter.who(round_trip(adapter, sso, "sso")[0]) == "alex"


def _network(adapter: Any) -> fakes.Network:
    return oidc_package(adapter).config.transport().handler  # type: ignore[union-attr]
