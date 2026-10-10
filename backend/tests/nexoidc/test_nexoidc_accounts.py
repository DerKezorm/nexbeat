"""Contract, Bauplan 05 "Konten", Pflichttests 13 to 22, through the app's own routes and store.

Apps with one account (Bauplan 06) answer 15 to 17 with "a foreign identity is refused" instead; the tests branch
on ``adapter.single_account`` and never skip.
"""

from __future__ import annotations

import threading
from typing import Any

import oidc_contract
import oidc_fakes as fakes
import pytest
from conftest import add_in_store
from oidc_contract import (
    entry,
    error_in,
    form_of,
    link_person,
    location,
    round_trip,
    start,
)


def links_of(adapter: Any, name: str) -> list[Any]:
    with adapter.store() as store:
        return [
            link
            for provider in store.list_providers()
            for link in store.links_of_provider(provider.id)
            if store.account_state(link.account_id).name == name
        ]


def set_auto_create(adapter: Any, slug: str, value: bool) -> None:
    item = entry(adapter, slug)
    response = adapter.save_provider(item["id"], form_of(item, auto_create=value))
    assert response.status_code == 200, response.text


# --- 13 -----------------------------------------------------------------------------------------------------------


def test_13_a_known_link_signs_in_whatever_name_and_address_say_today(
    adapter: Any, sso: fakes.FakeProvider, with_sso: dict
) -> None:
    adapter.make_account("alex")
    link_person(adapter, "alex", "sso", sso)
    sso.person = {"sub": "person-1", "preferred_username": "renamed", "email": "new@example.com"}
    browser, response = round_trip(adapter, sso, "sso")
    assert location(response) == adapter.home and adapter.who(browser) == "alex"
    assert "renamed" not in adapter.account_names()


# --- 14 -----------------------------------------------------------------------------------------------------------


def test_14_an_account_with_the_same_address_is_never_taken_over(
    adapter: Any, sso: fakes.FakeProvider, with_sso: dict
) -> None:
    adapter.make_account("alex")
    before = adapter.account_names()
    # The person at the provider has alex's name and a confirmed address: still nobody's link.
    sso.person = {
        "sub": "stranger-1",
        "preferred_username": "alex",
        "email": "alex@example.com",
        "email_verified": True,
    }
    browser, response = round_trip(adapter, sso, "sso")
    assert error_in(response) == "oidc_no_account" and adapter.who(browser) is None
    assert adapter.account_names() == before


# --- 15 to 17 -----------------------------------------------------------------------------------------------------


def test_15_without_link_invitation_or_auto_create_nobody_comes_in(
    adapter: Any, sso: fakes.FakeProvider, with_sso: dict
) -> None:
    before = adapter.account_names()
    browser, response = round_trip(adapter, sso, "sso")
    assert error_in(response) == "oidc_no_account" and adapter.who(browser) is None
    assert adapter.account_names() == before


def test_16_an_invitation_through_the_provider_makes_the_account_with_its_rights_once(
    adapter: Any, sso: fakes.FakeProvider, with_sso: dict
) -> None:
    if adapter.single_account:
        # Bauplan 06: no invitations; a foreign identity is refused.
        assert error_in(start(adapter, adapter.browser(), "sso", invite="any-key")) == "invite_invalid"
        browser, response = round_trip(adapter, sso, "sso")
        assert error_in(response) == "oidc_no_account" and adapter.who(browser) is None
        return
    key = adapter.make_invite("editor")
    browser, response = round_trip(adapter, sso, "sso", invite=key)
    assert location(response) == adapter.home and adapter.who(browser) == "alex"
    assert adapter.rights_of("alex") == "editor"
    # The same invitation a second time: it does not even start (two at once: the next test).
    assert error_in(start(adapter, adapter.browser(), "sso", invite=key)) == "invite_invalid"


def test_16_two_returning_at_once_with_one_invitation_make_one_account(
    adapter: Any, sso: fakes.FakeProvider, with_sso: dict
) -> None:
    if adapter.single_account:
        assert error_in(start(adapter, adapter.browser(), "sso", invite="any-key")) == "invite_invalid"
        return
    key = adapter.make_invite("member")
    ready = []
    for number in (1, 2):
        sso.person = {"sub": f"person-{number}", "preferred_username": f"p{number}"}
        browser = adapter.browser()
        ready.append((browser, sso.authorize(location(start(adapter, browser, "sso", invite=key)))))
    answers: list[Any] = [None, None]

    def back(index: int) -> None:
        browser, params = ready[index]
        answers[index] = oidc_contract.come_back(adapter, browser, "sso", params)

    threads = [threading.Thread(target=back, args=(index,)) for index in (0, 1)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    outcomes = sorted(error_in(answer) or "in" for answer in answers)
    assert outcomes == ["in", "invite_invalid"]
    assert len({"p1", "p2"} & set(adapter.account_names())) == 1


def test_16_a_known_identity_with_an_invitation_signs_in_and_takes_its_rights_once(
    adapter: Any, sso: fakes.FakeProvider, with_sso: dict
) -> None:
    if adapter.single_account:
        # Bauplan 06: no invitations, not even for the one account's own identity.
        adapter.make_account("owner")
        link_person(adapter, "owner", "sso", sso)
        assert error_in(start(adapter, adapter.browser(), "sso", invite="any-key")) == "invite_invalid"
        return
    adapter.make_account("alex")
    link_person(adapter, "alex", "sso", sso)
    assert adapter.rights_of("alex") == "member"
    names = adapter.account_names()
    key = adapter.make_invite("editor")
    browser, response = round_trip(adapter, sso, "sso", invite=key)
    assert location(response) == adapter.home and adapter.who(browser) == "alex"
    assert adapter.rights_of("alex") == "editor" and adapter.account_names() == names
    # Used up: it does not even start again.
    assert error_in(start(adapter, adapter.browser(), "sso", invite=key)) == "invite_invalid"
    # Rights are added, never taken away: a member's invitation leaves the editor an editor.
    browser, response = round_trip(adapter, sso, "sso", invite=adapter.make_invite("member"))
    assert adapter.who(browser) == "alex" and adapter.rights_of("alex") == "editor"


def test_16_a_known_and_a_new_identity_at_once_with_one_invitation_use_it_once(
    adapter: Any, sso: fakes.FakeProvider, with_sso: dict
) -> None:
    if adapter.single_account:
        assert error_in(start(adapter, adapter.browser(), "sso", invite="any-key")) == "invite_invalid"
        return
    adapter.make_account("alex")
    sso.person = {"sub": "person-1", "preferred_username": "alex"}
    link_person(adapter, "alex", "sso", sso)
    key = adapter.make_invite("editor")
    ready = []
    for number in (1, 2):
        sso.person = {"sub": f"person-{number}", "preferred_username": f"p{number}"}
        browser = adapter.browser()
        ready.append((browser, sso.authorize(location(start(adapter, browser, "sso", invite=key)))))
    answers: list[Any] = [None, None]

    def back(index: int) -> None:
        browser, params = ready[index]
        answers[index] = oidc_contract.come_back(adapter, browser, "sso", params)

    threads = [threading.Thread(target=back, args=(index,)) for index in (0, 1)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    # alex is in either way (the link comes first); the invitation went to exactly one of the two.
    assert error_in(answers[0]) is None and adapter.who(ready[0][0]) == "alex"
    took = adapter.rights_of("alex") == "editor"
    made = "p2" in adapter.account_names()
    assert took != made
    assert error_in(answers[1]) == ("invite_invalid" if took else None)


def test_17_auto_create_makes_a_member(adapter: Any, sso: fakes.FakeProvider, with_sso: dict) -> None:
    if adapter.only_authentik:
        with adapter.store() as store:
            row = store.provider_by_slug("sso")
        _set_in_store(adapter, row, auto_create=True)
    else:
        set_auto_create(adapter, "sso", True)
    browser, response = round_trip(adapter, sso, "sso")
    if adapter.single_account:
        # Bauplan 06: auto_create is off inside; a foreign identity is refused.
        assert error_in(response) == "oidc_no_account" and adapter.who(browser) is None
        return
    assert location(response) == adapter.home and adapter.who(browser) == "alex"
    assert adapter.rights_of("alex") == "member"


def _set_in_store(adapter: Any, row: Any, **changes: Any) -> None:
    import conftest

    package = conftest.oidc_package(adapter)
    values = {
        name: getattr(row, name)
        for name in (
            "slug",
            "label",
            "issuer",
            "client_id",
            "scopes",
            "enabled",
            "auto_create",
            "trusts_second_factor",
            "managed",
            "position",
        )
    }
    values.update(client_secret=None, **changes)
    with adapter.store() as store:
        store.update_provider(row.id, package.ProviderValues(**values))
        store.commit()


# --- 18 -----------------------------------------------------------------------------------------------------------


def test_18_linking_asks_for_the_password_and_refuses_an_identity_of_another_account(
    adapter: Any, sso: fakes.FakeProvider, with_sso: dict
) -> None:
    adapter.make_account("alex")
    browser = adapter.browser()
    adapter.sign_in_with_password(browser, "alex")
    refused = adapter.link_start(browser, "sso", "not-the-password")
    assert refused.status_code in (400, 401, 403) and "url" not in refused.text
    assert adapter.link_start(adapter.browser(), "sso", adapter.password_for("alex")).status_code in (401, 403)
    link_person(adapter, "alex", "sso", sso)
    if adapter.single_account:
        # Bauplan 06: there is no other account to take the identity. A foreign identity at the same provider does
        # not come in; linking another identity replaces the one account's link (one per provider, Bauplan 01).
        sso.person = {"sub": "person-2", "preferred_username": "stranger"}
        browser, response = round_trip(adapter, sso, "sso")
        assert error_in(response) == "oidc_no_account" and adapter.who(browser) is None
        link_person(adapter, "alex", "sso", sso)
        assert [link.subject for link in links_of(adapter, "alex")] == ["person-2"]
        assert adapter.who(round_trip(adapter, sso, "sso")[0]) == "alex"
        sso.person = {"sub": "person-1", "preferred_username": "alex"}
        assert error_in(round_trip(adapter, sso, "sso")[1]) == "oidc_no_account"
        assert adapter.account_names() == ["alex"]
        return
    adapter.make_account("bob")
    bob = adapter.browser()
    adapter.sign_in_with_password(bob, "bob")
    answer = adapter.link_start(bob, "sso", adapter.password_for("bob"))
    back = oidc_contract.come_back(adapter, bob, "sso", sso.authorize(answer.json()["url"]))
    assert error_in(back) == "oidc_subject_taken" and location(back).startswith(adapter.account_page)


def test_18_the_last_link_of_an_account_without_password_stays(
    adapter: Any, sso: fakes.FakeProvider, with_sso: dict
) -> None:
    if adapter.single_account:
        adapter.make_account("owner")
        link_person(adapter, "owner", "sso", sso)
        browser = adapter.browser()
        adapter.sign_in_with_password(browser, "owner")
        assert adapter.unlink(browser, "sso").status_code in (200, 204)
        return
    key = adapter.make_invite("member")
    browser, _ = round_trip(adapter, sso, "sso", invite=key)
    assert adapter.who(browser) == "alex"
    refused = adapter.unlink(browser, "sso")
    assert refused.status_code == 409 and adapter.error_code(refused) == "oidc_only_account"
    assert location(round_trip(adapter, sso, "sso")[1]) == adapter.home
    # With a password the link can go.
    adapter.make_account("pw")
    sso.person = {"sub": "person-9", "preferred_username": "pw"}
    link_person(adapter, "pw", "sso", sso)
    browser = adapter.browser()
    adapter.sign_in_with_password(browser, "pw")
    assert adapter.unlink(browser, "sso").status_code in (200, 204)
    assert error_in(round_trip(adapter, sso, "sso")[1]) == "oidc_no_account"


# --- 19 -----------------------------------------------------------------------------------------------------------


def test_19_the_second_factor_is_asked_only_when_the_provider_is_not_trusted(
    adapter: Any, sso: fakes.FakeProvider, with_sso: dict
) -> None:
    adapter.make_account("alex", second_factor=adapter.has_second_factor)
    link_person(adapter, "alex", "sso", sso)
    browser, response = round_trip(adapter, sso, "sso")
    assert not adapter.second_factor_asked(browser, response) and adapter.who(browser) == "alex"
    item = entry(adapter, "sso")
    if adapter.only_authentik:
        with adapter.store() as store:
            _set_in_store(adapter, store.provider_by_slug("sso"), trusts_second_factor=False)
    else:
        assert adapter.save_provider(item["id"], form_of(item, trusts_second_factor=False)).status_code == 200
    browser, response = round_trip(adapter, sso, "sso")
    if adapter.has_second_factor:
        assert adapter.second_factor_asked(browser, response) and adapter.who(browser) is None
    else:
        assert not adapter.second_factor_asked(browser, response) and adapter.who(browser) == "alex"


# --- 20 -----------------------------------------------------------------------------------------------------------


def test_20_the_same_subject_at_two_providers_is_two_identities_with_own_buttons_and_callbacks(
    adapter: Any, sso: fakes.FakeProvider, with_sso: dict, net: fakes.Network
) -> None:
    other = net.add(fakes.FakeProvider("https://other.example.com"))
    if adapter.only_authentik:
        # nexsuite: one provider only (Bauplan 06, without 20). The form takes no second one.
        assert adapter.add_provider(other, slug="other", label="Other").status_code >= 400
        return
    response = adapter.add_provider(other, slug="other", label="Other")
    assert response.status_code in (200, 201), response.text
    adapter.make_account("alex")
    link_person(adapter, "alex", "sso", sso)
    assert adapter.who(round_trip(adapter, sso, "sso")[0]) == "alex"
    assert error_in(round_trip(adapter, other, "other")[1]) == "oidc_no_account"
    public = adapter.browser().get(adapter.path("public")).json()
    assert [(item["slug"], item["label"]) for item in public] == [("sso", "SSO"), ("other", "Other")]
    uris = [
        fakes.query_of(location(start(adapter, adapter.browser(), slug)))["redirect_uri"] for slug in ("sso", "other")
    ]
    assert uris[0].endswith(adapter.path("callback", slug="sso")) and uris[1].endswith(
        adapter.path("callback", slug="other")
    )


# --- 21 -----------------------------------------------------------------------------------------------------------


def test_21_changing_the_issuer_drops_the_links_of_that_entry_only_and_a_slash_drops_nothing(
    adapter: Any, sso: fakes.FakeProvider, with_sso: dict, net: fakes.Network
) -> None:
    if adapter.only_authentik:
        pytest.xfail("only authentik: the issuer changes through the button only (test_30)")
    other = net.add(fakes.FakeProvider("https://other.example.com"))
    assert adapter.add_provider(other, slug="other", label="Other").status_code in (200, 201)
    adapter.make_account("alex")
    link_person(adapter, "alex", "sso", sso)
    link_person(adapter, "alex", "other", other)
    item = entry(adapter, "sso")
    for written in (item["issuer"] + "/", item["issuer"]):
        assert adapter.impact(item["id"], written)["issuer_change"] == 0
        assert adapter.save_provider(item["id"], form_of(item, issuer=written)).status_code == 200
    assert len(links_of(adapter, "alex")) == 2
    moved = net.add(
        fakes.FakeProvider("https://moved.example.com", client_id=sso.client_id, client_secret=sso.client_secret)
    )
    assert adapter.impact(item["id"], moved.issuer)["issuer_change"] == 1
    assert adapter.save_provider(item["id"], form_of(item, issuer=moved.issuer)).status_code == 200
    assert [link.provider_id for link in links_of(adapter, "alex")] == [entry(adapter, "other")["id"]]
    assert error_in(round_trip(adapter, moved, "sso")[1]) == "oidc_no_account"


def test_21_removing_an_entry_names_who_loses_access_and_takes_its_links(
    adapter: Any, sso: fakes.FakeProvider, with_sso: dict
) -> None:
    if adapter.only_authentik:
        pytest.xfail("only authentik: the one entry is not removed through the list")
    adapter.make_account("alex")
    link_person(adapter, "alex", "sso", sso)
    item = entry(adapter, "sso")
    impact = adapter.impact(item["id"])
    assert (impact["count"], impact["only"]) == (1, 0)
    assert adapter.remove_provider(item["id"]).status_code in (200, 204)
    assert adapter.providers() == []
    assert error_in(start(adapter, adapter.browser(), "sso")) == "oidc_not_configured"


# --- 22 -----------------------------------------------------------------------------------------------------------


def test_22_the_old_single_provider_becomes_the_entry_oidc_and_the_old_callback_still_signs_in(
    adapter: Any, sso: fakes.FakeProvider
) -> None:
    if adapter.legacy_model != "single":
        # Apps that had a list already adapt their tables instead (Bauplan 01); nothing to migrate here.
        assert adapter.legacy_model in ("list", "none")
        return
    adapter.make_account("alex")
    if not adapter.single_account:
        # Somebody without an identity, who stays without one.
        adapter.make_account("bob")
    adapter.legacy_setup(
        issuer=sso.issuer,
        client_id=sso.client_id,
        client_secret=sso.client_secret,
        label="Company",
        subjects={"alex": "person-1"},
    )
    adapter.run_migration()
    adapter.run_migration()
    with adapter.store() as store:
        entries = store.list_providers()
        assert [(item.slug, item.label) for item in entries] == [("oidc", "Company")]
        assert [(link.subject, link.issuer) for link in store.links_of_provider(entries[0].id)] == [
            ("person-1", sso.issuer)
        ]
    browser = adapter.browser()
    target = location(start(adapter, browser, "oidc"))
    assert fakes.query_of(target)["redirect_uri"].endswith(adapter.path("legacy_callback"))
    response = oidc_contract.come_back(adapter, browser, "oidc", sso.authorize(target), legacy=True)
    assert location(response) == adapter.home and adapter.who(browser) == "alex"


def test_22_never_in_store_only_by_route_for_add_in_store(adapter: Any, net: fakes.Network) -> None:
    """The helper for apps without a form writes a usable entry (keeps the other tests honest)."""
    fake = net.add(fakes.FakeProvider("https://store.example.com"))
    add_in_store(adapter, fake, "stored")
    with adapter.store() as store:
        assert store.provider_by_slug("stored").client_secret == fake.client_secret
