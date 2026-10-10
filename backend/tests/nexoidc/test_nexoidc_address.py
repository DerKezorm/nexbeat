"""Contract, Bauplan 03 "Rückleitadresse" and 05 Pflichttests 36 to 38 (since 1.0.10), through the app's own routes.

Behind a proxy that ends TLS the app sees ``http`` while people use ``https``. The authentik button never registers
an address guessed from the request: without a public address it needs the one the operator confirmed in the card
(the browser's own), stores it and registers exactly that. When the public address changes later, the provider list
says that authentik still knows the old redirect address, and the next run of the button moves it there.
"""

from __future__ import annotations

from typing import Any

import oidc_fakes as fakes
import pytest
from oidc_contract import entry, form_of, location, start

#: What a proxy that ends TLS adds to the request it passes on as http.
PROXY = {"X-Forwarded-Proto": "https", "X-Forwarded-Host": "app.example.org"}
PUBLIC = "https://app.example.org"


@pytest.fixture
def ak(net: fakes.Network) -> fakes.FakeAuthentik:
    return net.add(fakes.FakeAuthentik())


def setup(adapter: Any, ak: fakes.FakeAuthentik, public_url: str) -> dict:
    response = adapter.setup_authentik(ak.base, ak.token, public_url=public_url, headers=PROXY)
    assert response.status_code == 200, response.text
    return response.json()


def registered(ak: fakes.FakeAuthentik) -> list[str]:
    return [item["url"] for provider in ak.providers for item in provider.get("redirect_uris") or []]


def test_36_without_a_public_address_behind_a_tls_proxy_the_button_registers_nothing(
    adapter: Any, oidc: Any, ak: fakes.FakeAuthentik
) -> None:
    assert adapter.read_public_url() == ""
    result = setup(adapter, ak, "")
    assert [(step["key"], step["ok"], step["reason"], step["status"]) for step in result["steps"]] == [
        ("reached", False, "public_url_needed", 0)
    ]
    # Not a single call to authentik, nothing in the list, no address stored: never an http address registered.
    assert ak.calls == [] and ak.providers == [] and registered(ak) == []
    assert adapter.providers() == [] and adapter.read_public_url() == ""
    address = result["address"]
    assert address["public_url"] == "" and address["forwarded_proto"] == "https"
    assert address["callback_path"] == adapter.path("callback", slug="authentik")
    if address["seen"].startswith("http://"):
        # The app did not take the proxy's word for the scheme: the card warns, and the browser's address differs.
        assert address["proxy_ignored"] is True
        assert oidc.authentik.address_mismatch(PUBLIC, address["seen"]) == "scheme"
    # The card's own route shows the same before the button is pressed.
    assert adapter.address(PROXY) == address
    # Something that is no address is not taken either.
    for wrong in ("ftp://app.example.org", "https://app.example.org/?next=x", "javascript:alert(1)"):
        refused = setup(adapter, ak, wrong)
        assert refused["steps"][-1]["reason"] == "public_url_needed" and adapter.read_public_url() == ""
    assert ak.calls == [] and adapter.providers() == []


def test_37_a_confirmed_https_address_is_stored_and_exactly_it_is_registered(
    adapter: Any, ak: fakes.FakeAuthentik
) -> None:
    result = setup(adapter, ak, PUBLIC + "/")
    assert result["ok"] is True and result["public_url"] == PUBLIC
    assert adapter.read_public_url().rstrip("/") == PUBLIC
    redirect = PUBLIC + adapter.path("callback", slug="authentik")
    assert registered(ak) == [redirect]
    item = entry(adapter, "authentik")
    assert item["redirect_uri"] == item["registered_redirect_uri"] == redirect and item["redirect_stale"] is False
    # The sign-in sends the same address; nothing http anywhere.
    target = location(start(adapter, adapter.browser(), "authentik"))
    assert fakes.query_of(target)["redirect_uri"] == redirect
    # Once the app has an address, a confirmed one does not replace it (the card sends one only while there is none).
    again = setup(adapter, ak, "https://elsewhere.example.org")
    assert again["ok"] is True and again["public_url"] == "" and adapter.read_public_url().rstrip("/") == PUBLIC
    assert registered(ak) == [redirect]


def test_38_a_new_public_address_is_reported_and_the_next_run_moves_the_redirect(
    adapter: Any, oidc: Any, ak: fakes.FakeAuthentik
) -> None:
    callback = adapter.path("callback", slug="authentik")
    old, new = PUBLIC + callback, "https://new.example.org" + callback
    assert setup(adapter, ak, PUBLIC)["ok"] is True
    with adapter.store() as store:
        asked = oidc.authentik.public_url_change(store, "https://new.example.org")
        assert oidc.authentik.public_url_change(store, PUBLIC)["count"] == 0
    assert asked["count"] == 1 and asked["address"] == old and asked["entries"][0]["redirect"] == new
    adapter.set_public_url("https://new.example.org")
    item = entry(adapter, "authentik")
    assert item["redirect_stale"] is True and item["registered_redirect_uri"] == old and item["redirect_uri"] == new
    assert adapter.address()["stale"] is True
    with adapter.store() as store:
        # The question names what authentik knows (the app's store kept it), and going back needs none.
        assert oidc.authentik.public_url_change(store, "https://third.example.org")["address"] == old
        assert oidc.authentik.public_url_change(store, PUBLIC)["count"] == 0
    if not adapter.only_authentik:
        # Saving the entry through the form keeps what the button registered (only the button writes it).
        saved = adapter.save_provider(item["id"], form_of(item, issuer=item["issuer"] + "/"))
        assert saved.status_code == 200, saved.text
        assert entry(adapter, "authentik")["registered_redirect_uri"] == old
    before = len(ak.calls)
    assert setup(adapter, ak, "")["ok"] is True
    moved = [
        call
        for call in ak.calls[before:]
        if call.method == "PATCH" and call.path.startswith("/api/v3/providers/oauth2/")
    ]
    assert moved and moved[-1].body["redirect_uris"] == [{"matching_mode": "strict", "url": new}]
    assert len(ak.providers) == 1 and registered(ak) == [new]
    item = entry(adapter, "authentik")
    assert item["redirect_stale"] is False and item["registered_redirect_uri"] == new
    assert adapter.address()["stale"] is False


WAYS = ("adopt_only", "save_public_url_route")


def active_by_hand(adapter: Any, oidc: Any) -> int:
    """The entries made by hand that are on now (the store's word)."""
    with adapter.store() as store:
        return sum(1 for item in store.list_providers() if item.managed == oidc.MANAGED_HAND and item.enabled)


@pytest.mark.parametrize("way", WAYS)
def test_39_saving_the_public_address_asks_first_and_the_card_reports_it_after(
    adapter: Any, oidc: Any, ak: fakes.FakeAuthentik, with_sso: dict, way: str
) -> None:
    """Pflichttest 39 (since 1.0.10): the module's route ("Use it only") and the app's own way of saving the public
    address (card 1, ``save_public_url_route`` in the adapter) both ask while an entry of the button would be left
    with an old redirect address, save nothing unasked, save once confirmed, and then the card says ``stale``. Also
    for an entry the button made before 1.0.10, which has no registered address of its own."""
    save = getattr(adapter, way)
    callback = adapter.path("callback", slug="authentik")
    first, second = "https://first.example.org", "https://second.example.org"
    third, fourth = "https://third.example.org", "https://fourth.example.org"
    # No entry of the button, but an active one by hand (sso): it asks all the same, ``count`` 0 and ``hand`` 1 (the
    # page shows ``addressChangeHand`` alone), saves nothing unasked and saves once confirmed.
    alone = save(first)
    assert alone.status_code == 409, alone.text
    assert adapter.error_code(alone) == "public_url_change"
    question = adapter.error_detail(alone)
    assert (question["count"], question["hand"], question["entries"]) == (0, 1, [])
    assert adapter.read_public_url() == ""
    saved = save(first, confirm=True)
    assert saved.status_code == 200, saved.text
    assert adapter.read_public_url().rstrip("/") == first
    assert setup(adapter, ak, "")["ok"] is True and registered(ak) == [first + callback]
    # Unconfirmed: 409 with the question, nothing saved, nothing reported.
    asked = save(second + "/")
    assert asked.status_code == 409, asked.text
    assert adapter.error_code(asked) == "public_url_change"
    question = adapter.error_detail(asked)
    assert question["count"] == 1 and question["address"] == first + callback
    # The entry made by hand (sso) needs its redirect address changed at its provider: the question says so. In an
    # app with authentik alone (nexsuite) the button may have switched entries by hand off (since 1.0.8, the app's
    # rule): then the question counts the ones still on, and no adapter has to switch them on again (1.0.11).
    if adapter.only_authentik:
        assert question["hand"] == active_by_hand(adapter, oidc)
    else:
        assert question["hand"] == 1 == active_by_hand(adapter, oidc)
    assert adapter.read_public_url().rstrip("/") == first and entry(adapter, "authentik")["redirect_stale"] is False
    # Confirmed: saved, and the card reports what authentik still knows until the button ran again.
    done = save(second, confirm=True)
    assert done.status_code == 200, done.text
    assert adapter.read_public_url().rstrip("/") == second
    item = entry(adapter, "authentik")
    assert item["redirect_stale"] is True and item["registered_redirect_uri"] == first + callback
    assert adapter.address()["stale"] is True
    # Changed again before the button ran: asked with what authentik knows, and that is what stays reported.
    again = save(third)
    assert again.status_code == 409 and adapter.error_detail(again)["address"] == first + callback
    assert save(third, confirm=True).status_code == 200
    assert entry(adapter, "authentik")["registered_redirect_uri"] == first + callback
    # An entry from before 1.0.10 (no registered address): asked with the address of today, and stale after.
    with adapter.store() as store:
        own = store.provider_by_slug("authentik")
        store.update_provider(own.id, oidc.providers.values_of(own, registered_redirect=""))
        store.commit()
    assert entry(adapter, "authentik")["redirect_stale"] is False
    asked = save(fourth)
    assert asked.status_code == 409 and adapter.error_detail(asked)["address"] == third + callback
    assert save(fourth, confirm=True).status_code == 200 and adapter.read_public_url().rstrip("/") == fourth
    item = entry(adapter, "authentik")
    assert item["redirect_stale"] is True and item["registered_redirect_uri"] == third + callback
    # The next run of the button moves the redirect, and the report goes.
    assert setup(adapter, ak, "")["ok"] is True and entry(adapter, "authentik")["redirect_stale"] is False


@pytest.mark.parametrize("way", WAYS)
def test_39_a_switched_off_entry_by_hand_and_no_entry_at_all_ask_nothing(
    adapter: Any, oidc: Any, with_sso: dict, way: str
) -> None:
    """Pflichttest 39, the other side: the question needs an entry of the button or an active one by hand. With
    only a switched-off entry by hand nothing changes at any provider, so the address is saved at once."""
    save = getattr(adapter, way)
    with adapter.store() as store:
        own = store.provider_by_slug("sso")
        store.update_provider(own.id, oidc.providers.values_of(own, enabled=False))
        store.commit()
    saved = save("https://first.example.org")
    assert saved.status_code == 200, saved.text
    assert adapter.read_public_url().rstrip("/") == "https://first.example.org"


def test_39_use_it_only_takes_no_address_that_is_none(adapter: Any) -> None:
    for wrong in ("https://exa mple.org", "https://app.example.org/../x", "https://bücher.example.org"):
        refused = adapter.adopt_only(wrong)
        assert refused.status_code == 422 and adapter.error_code(refused) == "public_url_invalid", wrong
    assert adapter.read_public_url() == ""
    saved = adapter.adopt_only(PUBLIC)
    assert saved.status_code == 200 and saved.json()["public_url"] == PUBLIC
