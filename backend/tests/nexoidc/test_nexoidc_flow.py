"""Contract, Bauplan 05 "Anmeldeablauf", Pflichttests 1 to 6, through the app's own routes."""

from __future__ import annotations

import time
from http.cookies import SimpleCookie
from typing import Any

import oidc_fakes as fakes
import pytest
from conftest import add_in_store, oidc_package
from oidc_contract import (
    come_back,
    entry,
    error_in,
    link_person,
    location,
    round_trip,
    start,
)


def test_01_the_start_sets_the_attempt_cookie_and_sends_the_browser_off_with_pkce_state_and_nonce(
    adapter: Any, oidc: Any, sso: fakes.FakeProvider, with_sso: dict
) -> None:
    response = start(adapter, adapter.browser(), "sso")
    target = location(response)
    query = fakes.query_of(target)
    assert target.startswith(f"{sso.base}/authorize?")
    assert query["code_challenge_method"] == "S256" and len(query["code_challenge"]) == 43
    assert query["state"] and query["nonce"] and query["state"] != query["nonce"]
    assert query["redirect_uri"].endswith(adapter.path("callback", slug="sso"))
    cookies = SimpleCookie()
    for header in response.headers.get_list("set-cookie"):
        cookies.load(header)
    name = oidc.current().cookie_name
    assert name in cookies, response.headers.get_list("set-cookie")
    morsel = cookies[name]
    assert morsel["httponly"] and morsel["samesite"].lower() == "lax"
    assert morsel["path"] == f"{adapter.api}/oidc" and int(morsel["max-age"]) == 600
    assert query["state"] not in morsel.value


def test_01_a_whole_run_signs_in(adapter: Any, sso: fakes.FakeProvider, with_sso: dict) -> None:
    adapter.make_account("alex")
    link_person(adapter, "alex", "sso", sso)
    browser, response = round_trip(adapter, sso, "sso")
    assert location(response) == adapter.home and adapter.who(browser) == "alex"


def test_02_a_wrong_state_a_missing_cookie_and_a_second_return_are_refused(
    adapter: Any, sso: fakes.FakeProvider, with_sso: dict
) -> None:
    adapter.make_account("alex")
    link_person(adapter, "alex", "sso", sso)
    browser = adapter.browser()
    params = sso.authorize(location(start(adapter, browser, "sso")))
    forged = come_back(adapter, browser, "sso", {**params, "state": "forged"})
    assert error_in(forged) == "oidc_state_mismatch" and adapter.who(browser) is None
    # The refusal deleted the cookie: the right state does not help any more.
    assert error_in(come_back(adapter, browser, "sso", params)) == "oidc_state_mismatch"
    stranger = adapter.browser()
    assert error_in(come_back(adapter, stranger, "sso", params)) == "oidc_state_mismatch"
    # An attempt started at one provider does not come back through another one's callback.
    other = fakes.FakeProvider("https://other.example.com")
    _network_of(adapter).add(other)
    if adapter.only_authentik:
        add_in_store(adapter, other, "other")
    else:
        assert adapter.add_provider(other, slug="other", label="Other").status_code in (200, 201)
    browser = adapter.browser()
    params = sso.authorize(location(start(adapter, browser, "sso")))
    assert error_in(come_back(adapter, browser, "other", params)) == "oidc_state_mismatch"
    assert adapter.who(browser) is None
    # A second return with the same state, cookie and all.
    browser = adapter.browser()
    params = sso.authorize(location(start(adapter, browser, "sso")))
    cookies = dict(browser.cookies)
    assert location(come_back(adapter, browser, "sso", params)) == adapter.home
    replay = adapter.browser()
    for name, value in cookies.items():
        replay.cookies.set(name, value)
    assert error_in(come_back(adapter, replay, "sso", params)) == "oidc_state_mismatch"
    assert adapter.who(replay) is None


@pytest.mark.parametrize(
    "bend",
    [
        {"token_key": fakes.FOREIGN_PEM},
        {"token_algorithm": "HS256"},
        {"token_claims": {"aud": "someone-else"}},
        {"token_claims": {"azp": "someone-else"}},
        {"token_claims": {"exp": int(time.time()) - 600}},
        {"token_claims": {"nonce": "another-run"}},
        {"token_claims": {"sub": ""}},
    ],
    ids=["foreign-signature", "hs256", "aud", "azp", "expired", "nonce", "empty-sub"],
)
def test_03_a_bent_token_is_refused(adapter: Any, sso: fakes.FakeProvider, with_sso: dict, bend: dict) -> None:
    adapter.make_account("alex")
    link_person(adapter, "alex", "sso", sso)
    for name, value in bend.items():
        setattr(sso, name, value)
    if bend.get("token_algorithm") == "HS256":
        sso.token_key = sso.client_secret
    browser, response = round_trip(adapter, sso, "sso")
    expected = "oidc_no_signing_key" if "token_algorithm" in bend else "oidc_token_invalid"
    assert error_in(response) == expected and adapter.who(browser) is None


def test_04_a_discovery_naming_another_issuer_is_not_saved(adapter: Any, net: fakes.Network) -> None:
    liar = net.add(fakes.FakeProvider("https://liar.example.com"))
    liar.published = "https://someone-else.example.com"
    response = adapter.add_provider(liar, slug="liar")
    if adapter.only_authentik:
        # nexsuite: the form takes no entry at all (Bauplan 06); the button's discovery is test_23.
        assert response.status_code >= 400
    else:
        assert response.status_code == 422 and adapter.error_code(response) == "oidc_issuer_mismatch"
    assert [item["slug"] for item in adapter.providers()] == []


def test_05_an_issuer_with_a_slash_at_the_end_takes_exactly_that_issuer(adapter: Any, net: fakes.Network) -> None:
    from conftest import add_in_store

    slashed = net.add(fakes.FakeProvider("https://auth.example.com/application/o/app/"))
    if adapter.only_authentik:
        add_in_store(adapter, slashed, "slash")
    else:
        response = adapter.add_provider(slashed, slug="slash", issuer="https://auth.example.com/application/o/app")
        assert response.status_code in (200, 201), response.text
    adapter.make_account("alex")
    link_person(adapter, "alex", "slash", slashed)
    assert location(round_trip(adapter, slashed, "slash")[1]) == adapter.home
    slashed.token_claims = {"iss": "https://auth.example.com/application/o/app"}
    assert error_in(round_trip(adapter, slashed, "slash")[1]) == "oidc_token_invalid"


@pytest.mark.parametrize("mode", ["json", "signed", "signed-foreign", "other-subject", "error"])
def test_06_userinfo_is_checked_and_its_failures_break_nothing(
    adapter: Any, sso: fakes.FakeProvider, with_sso: dict, mode: str
) -> None:
    adapter.make_account("alex")
    # The token names no address: whatever arrives comes from userinfo. (Where both name one, the token wins.)
    sso.person = {"sub": "person-1", "preferred_username": "alex"}
    link_person(adapter, "alex", "sso", sso)
    sso.userinfo = mode
    sso.userinfo_claims = {"email": "from-userinfo@example.com"}
    browser, response = round_trip(adapter, sso, "sso")
    assert location(response) == adapter.home and adapter.who(browser) == "alex"
    with adapter.store() as store:
        link = store.find_link(entry(adapter, "sso")["id"], "person-1")
    # A signed answer counts after the same checks as the token; a foreign signature, another subject or an error
    # leave nothing behind.
    assert link.email == ("from-userinfo@example.com" if mode in ("json", "signed") else None)


def _network_of(adapter: Any) -> fakes.Network:
    return oidc_package(adapter).config.transport().handler  # type: ignore[union-attr]
