"""Contract: what only the app's routes can keep (Bauplan 01, 02), so that no app can drop it unseen.

- every operator route refuses a browser without a session and a signed-in member;
- the brake holds a sender back before start and return (``too_many_attempts``, the cookie goes);
- a returning linking takes the account from the session, never from the attempt;
- the operator removes a link only with the operator's own password;
- a refused sign-in ends on the sign-in page, the attempt cookie deleted.
"""

from __future__ import annotations

from http.cookies import SimpleCookie
from typing import Any

import oidc_contract
import oidc_fakes as fakes
from oidc_contract import entry, error_in, link_person, location, start


def _deleted(response: Any, name: str) -> bool:
    cookies = SimpleCookie()
    for header in response.headers.get_list("set-cookie"):
        cookies.load(header)
    if name not in cookies:
        return False
    morsel = cookies[name]
    return morsel.value in ("", '""') and (morsel["max-age"] in ("0", 0) or bool(morsel["expires"]))


def _calls(adapter: Any, client: Any, routes: list[tuple[str, str, Any]]) -> list[tuple[str, str, int]]:
    answers = []
    for method, path, body in routes:
        response = client.request(method, path, json=body) if body is not None else client.request(method, path)
        answers.append((method, path, response.status_code))
    return answers


def test_operator_routes_refuse_a_browser_without_session_and_a_member(
    adapter: Any, sso: fakes.FakeProvider, with_sso: dict, net: fakes.Network
) -> None:
    ak = net.add(fakes.FakeAuthentik())
    owner = adapter.make_account("owner")
    link_person(adapter, "owner", "sso", sso)
    routes = adapter.operator_routes(with_sso["id"], owner)
    for method, path, status in _calls(adapter, adapter.browser(), routes):
        assert status in adapter.anonymous_status, (method, path, status)
    if not adapter.single_account:
        for method, path, status in _calls(adapter, adapter.member(), routes):
            assert status in adapter.member_status, (method, path, status)
    # Nothing changed, and authentik was never asked.
    assert [item["slug"] for item in adapter.providers()] == ["sso"] and ak.calls == []
    assert "intruder" not in adapter.read_public_url()
    with adapter.store() as store:
        assert len(store.links_of_account(owner)) == 1


def test_the_operator_removes_a_link_only_with_the_own_password(
    adapter: Any, sso: fakes.FakeProvider, with_sso: dict
) -> None:
    owner = adapter.make_account("owner")
    link_person(adapter, "owner", "sso", sso)
    if adapter.single_account:
        # Bauplan 06: no account list, so no operator unlinking another account; the one account unlinks its own
        # link on its account page (it has a password, so the link may go).
        browser = adapter.browser()
        adapter.sign_in_with_password(browser, "owner")
        assert adapter.unlink(browser, "sso").status_code in (200, 204)
        with adapter.store() as store:
            assert store.links_of_account(owner) == []
        return
    operator = adapter.operator()
    refused = adapter.operator_unlink(operator, owner, with_sso["id"], "not-the-password")
    assert refused.status_code in (400, 401, 403)
    with adapter.store() as store:
        assert len(store.links_of_account(owner)) == 1
    done = adapter.operator_unlink(operator, owner, with_sso["id"], adapter.password_for(adapter.operator_name))
    assert done.status_code in (200, 204), done.text
    with adapter.store() as store:
        assert store.links_of_account(owner) == []


def test_the_brake_holds_a_sender_back_at_start_and_return(
    adapter: Any, oidc: Any, sso: fakes.FakeProvider, with_sso: dict
) -> None:
    name = oidc.current().cookie_name
    adapter.make_account("alex")
    link_person(adapter, "alex", "sso", sso)
    # A return that was started before the brake took hold.
    browser = adapter.browser()
    target = location(start(adapter, browser, "sso"))
    params = sso.authorize(target)
    adapter.trip_throttle(browser)
    back = oidc_contract.come_back(adapter, browser, "sso", params, path=oidc_contract.sent_callback(target))
    assert error_in(back) == "too_many_attempts" and location(back).startswith(adapter.login_page)
    assert _deleted(back, name) and adapter.who(browser) is None
    braked = start(adapter, adapter.browser(), "sso")
    assert error_in(braked) == "too_many_attempts" and location(braked).startswith(adapter.login_page)
    assert "authorize" not in location(braked)


def test_a_braked_linking_ends_on_the_account_page(adapter: Any, sso: fakes.FakeProvider, with_sso: dict) -> None:
    adapter.make_account("alex")
    browser = adapter.browser()
    adapter.sign_in_with_password(browser, "alex")
    answer = adapter.link_start(browser, "sso", adapter.password_for("alex"))
    assert answer.status_code == 200, answer.text
    url = answer.json()["url"]
    adapter.trip_throttle(browser)
    back = oidc_contract.come_back(adapter, browser, "sso", sso.authorize(url), path=oidc_contract.sent_callback(url))
    assert error_in(back) == "too_many_attempts" and location(back).startswith(adapter.account_page)
    refused = adapter.link_start(browser, "sso", adapter.password_for("alex"))
    assert refused.status_code >= 400 and adapter.error_code(refused) == "too_many_attempts"


def test_a_returning_linking_takes_the_account_from_the_session(
    adapter: Any, oidc: Any, sso: fakes.FakeProvider, with_sso: dict
) -> None:
    alex = adapter.make_account("alex")
    browser = adapter.browser()
    adapter.sign_in_with_password(browser, "alex")
    answer = adapter.link_start(browser, "sso", adapter.password_for("alex"))
    url = answer.json()["url"]
    params = sso.authorize(url)
    attempt = {oidc.current().cookie_name: browser.cookies.get(oidc.current().cookie_name)}
    cases = [("without a session", adapter.browser())]
    if not adapter.single_account:
        adapter.make_account("bob")
        bob = adapter.browser()
        adapter.sign_in_with_password(bob, "bob")
        cases.append(("as another account", bob))
    for label, other in cases:
        for name, value in attempt.items():
            other.cookies.set(name, value)
        back = oidc_contract.come_back(adapter, other, "sso", params, path=oidc_contract.sent_callback(url))
        assert error_in(back) == "oidc_link_mismatch", label
        assert location(back).startswith(adapter.account_page), label
        with adapter.store() as store:
            assert store.links_of_provider(with_sso["id"]) == [], label
            assert store.links_of_account(alex) == [], label
        # The state of this attempt is used up now; the next case needs a fresh one.
        url = adapter.link_start(browser, "sso", adapter.password_for("alex")).json()["url"]
        params = sso.authorize(url)
        attempt = {oidc.current().cookie_name: browser.cookies.get(oidc.current().cookie_name)}


def test_a_refused_sign_in_ends_on_the_sign_in_page_and_the_cookie_goes(
    adapter: Any, oidc: Any, sso: fakes.FakeProvider, with_sso: dict
) -> None:
    browser = adapter.browser()
    target = location(start(adapter, browser, "sso"))
    back = oidc_contract.come_back(
        adapter, browser, "sso", sso.authorize(target), path=oidc_contract.sent_callback(target)
    )
    assert location(back).startswith(adapter.login_page + "?") and error_in(back) == "oidc_no_account"
    assert _deleted(back, oidc.current().cookie_name)
    assert entry(adapter, "sso")["enabled"]
