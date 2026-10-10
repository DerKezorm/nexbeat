"""Contract, Bauplan 05 "authentik-Knopf", Pflichttests 23 to 32, through the app's own routes.

31 (every step and reason has a text, in both languages) is checked by the module's own tests against the wording
files the app copies, and in the app by the frontend test from ``tests-fuer-apps/frontend``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import oidc_fakes as fakes
import pytest
from oidc_contract import entry, form_of, link_person


@pytest.fixture
def ak(net: fakes.Network) -> fakes.FakeAuthentik:
    return net.add(fakes.FakeAuthentik())


def setup(
    adapter: Any,
    ak: fakes.FakeAuthentik,
    *,
    token: str | None = None,
    url: str | None = None,
    confirm: bool = False,
) -> dict:
    response = adapter.setup_authentik(
        url or ak.base, ak.token if token is None else token, confirm_issuer_change=confirm
    )
    assert response.status_code == 200, response.text
    return response.json()


def keys(adapter: Any, oidc: Any) -> list[str]:
    return list(oidc.authentik.step_keys())


def steps(result: dict) -> list[tuple[str, bool]]:
    return [(step["key"], step["ok"]) for step in result["steps"]]


def test_23_the_button_makes_everything_and_a_second_run_updates_instead_of_doubling(
    adapter: Any, oidc: Any, ak: fakes.FakeAuthentik
) -> None:
    first = setup(adapter, ak)
    assert steps(first) == [(key, True) for key in keys(adapter, oidc)]
    # Bauplan 03 and 06: six steps in this order, "binding" as the seventh only in an app with one account.
    six = ["reached", "signingKey", "mapping", "provider", "application", "filled"]
    assert [key for key, _ in steps(first)] == six + (["binding"] if adapter.single_account else [])
    item = entry(adapter, "authentik")
    assert (item["label"], item["managed"], item["enabled"], item["auto_create"], item["trusts_second_factor"]) == (
        "authentik",
        "authentik",
        True,
        False,
        True,
    )
    assert item["client_id"] == ak.providers[0]["client_id"] and item["has_secret"] is True
    second = setup(adapter, ak)
    assert steps(second) == steps(first)
    assert len(ak.providers) == 1 and len(ak.applications) == 1 and len(ak.certificates) == 1
    assert [item["slug"] for item in adapter.providers()] == ["authentik"]


def test_24_the_token_travels_only_in_the_authorization_header(
    adapter: Any, ak: fakes.FakeAuthentik, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    response = adapter.setup_authentik(ak.base, ak.token)
    api_calls = [call for call in ak.calls if call.path.startswith("/api/v3/")]
    assert api_calls and all(call.authorization == f"Bearer {ak.token}" for call in api_calls)
    assert all(ak.token not in json.dumps(call.body) + json.dumps(call.query) for call in api_calls)
    assert ak.token not in response.text and ak.token not in caplog.text
    assert ak.token not in json.dumps(adapter.providers())
    with adapter.store() as store:
        assert all(ak.token not in repr(item) for item in store.list_providers())


@pytest.mark.parametrize(
    ("case", "reason", "status"),
    [
        ("unreachable", "unreachable", 0),
        ("unusable", "unusable", 0),
        ("forbidden", "token", 403),
        ("expired", "token", 401),
        ("malformed", "malformed", 0),
        ("answered", "answered", 500),
    ],
)
def test_25_the_first_failure_stops_and_names_its_reason(
    adapter: Any, ak: fakes.FakeAuthentik, case: str, reason: str, status: int
) -> None:
    url, token = ak.base, ak.token
    if case == "unreachable":
        url = "https://elsewhere.example.com"
    elif case == "unusable":
        url = "https://host:abc"
    elif case == "forbidden":
        token = "not-the-token"
    elif case == "expired":
        token = "expired"
    elif case == "malformed":
        token = "tökén aus authentik"
    else:
        ak.fail = ("POST", "/api/v3/providers/oauth2/", 500)
    result = setup(adapter, ak, url=url, token=token)
    failed = result["steps"][-1]
    assert not failed["ok"] and (failed["reason"], failed["status"]) == (reason, status)
    if case == "malformed":
        # Bauplan 03: before any call, at the first step.
        assert [step["key"] for step in result["steps"]] == ["reached"] and ak.calls == []
    assert all(step["ok"] for step in result["steps"][:-1])
    assert "authentik error page" not in json.dumps(result)


def test_25_every_slug_taken_by_other_providers_is_the_reason_slug(adapter: Any, ak: fakes.FakeAuthentik) -> None:
    stranger = ak.add_provider("stranger", "https://stranger.example.com/cb")
    original = ak._api

    def every_slug_taken(method, path, query, body):  # type: ignore[no-untyped-def]
        if (method, path) == ("GET", "/core/applications/") and "slug" in query:
            import httpx

            row = {"pk": "a", "slug": query["slug"], "name": "x", "provider": stranger["pk"]}
            return httpx.Response(200, json={"results": [row]})
        return original(method, path, query, body)

    ak._api = every_slug_taken  # type: ignore[method-assign]
    result = setup(adapter, ak)
    assert steps(result)[-1] == ("application", False) and result["steps"][-1]["reason"] == "slug"


def test_26_the_provider_names_its_grant(adapter: Any, ak: fakes.FakeAuthentik) -> None:
    setup(adapter, ak)
    assert ak.providers[0]["grant_types"] == ["authorization_code"]
    assert ak.providers[0]["redirect_uris"][0]["url"] == entry(adapter, "authentik")["redirect_uri"]


def test_27_a_second_instance_takes_names_of_its_own_and_leaves_the_first_alone(
    adapter: Any, ak: fakes.FakeAuthentik
) -> None:
    first = ak.add_provider(
        adapter_app(adapter), "https://first.example.com/api/oidc/authentik/callback", slug=adapter_app(adapter)
    )
    before = json.dumps(first, sort_keys=True)
    result = setup(adapter, ak)
    assert result["ok"] is True and json.dumps(first, sort_keys=True) == before
    own = [item for item in ak.providers if item is not first]
    assert len(own) == 1 and own[0]["name"].startswith(f"{adapter_app(adapter)} (")


def test_28_a_move_finds_the_own_provider_by_client_id_and_keeps_issuer_and_links(
    adapter: Any, ak: fakes.FakeAuthentik
) -> None:
    first = setup(adapter, ak)
    adapter.make_account("alex")
    _link_through_authentik(adapter, ak)
    ak.providers[0]["name"] = f"{adapter_app(adapter)} (old address)"
    adapter.set_public_url("https://moved.example.com")
    second = setup(adapter, ak)
    assert second["ok"] and second["issuer"] == first["issuer"] and second["links_dropped"] == 0
    assert ak.providers[0]["redirect_uris"][0]["url"].startswith("https://moved.example.com/")
    assert len(ak.providers) == 1 and _link_count(adapter) == 1


def test_29_an_application_of_another_provider_is_never_taken(adapter: Any, ak: fakes.FakeAuthentik) -> None:
    stranger = ak.add_provider("stranger", "https://stranger.example.com/cb", slug=adapter_app(adapter))
    result = setup(adapter, ak)
    assert result["ok"] and ak.application(adapter_app(adapter))["provider"] == stranger["pk"]
    slug = result["issuer"].rstrip("/").rsplit("/", 1)[1]
    assert slug != adapter_app(adapter) and len(slug) <= 50
    searches = [call for call in ak.calls if call.path == "/api/v3/core/applications/" and call.method == "GET"]
    assert searches and all(call.query.get("superuser_full_list") == "true" for call in searches)


def test_30_the_form_after_the_button_and_the_button_after_the_form_keep_the_links(
    adapter: Any, ak: fakes.FakeAuthentik
) -> None:
    setup(adapter, ak)
    adapter.make_account("alex")
    _link_through_authentik(adapter, ak)
    item = entry(adapter, "authentik")
    if not adapter.only_authentik:
        saved = adapter.save_provider(item["id"], form_of(item, issuer=item["issuer"] + "/"))
        assert saved.status_code == 200, saved.text
        assert _link_count(adapter) == 1
    again = setup(adapter, ak)
    assert again["ok"] and again["links_dropped"] == 0 and _link_count(adapter) == 1


def test_30_the_address_in_other_letters_is_the_same_authentik_and_keeps_the_links(
    adapter: Any, ak: fakes.FakeAuthentik
) -> None:
    first = setup(adapter, ak)
    adapter.make_account("alex")
    _link_through_authentik(adapter, ak)
    scheme, rest = ak.base.split("://", 1)
    typed = f"{scheme.upper()}://{rest.title()}/"
    assert typed != ak.base
    again = setup(adapter, ak, url=typed)
    assert again["ok"] and again["issuer"] == first["issuer"] and again["links_dropped"] == 0
    assert entry(adapter, "authentik")["issuer"] == first["issuer"].rstrip("/") and _link_count(adapter) == 1


def test_30_a_new_issuer_whose_discovery_fails_changes_nothing(
    adapter: Any, ak: fakes.FakeAuthentik, net: fakes.Network
) -> None:
    setup(adapter, ak)
    adapter.make_account("alex")
    _link_through_authentik(adapter, ak)
    before = entry(adapter, "authentik")
    other = net.add(fakes.FakeAuthentik(base="https://auth2.example.com"))
    other.discovery_ok = False
    result = setup(adapter, other, confirm=True)
    assert steps(result)[-1] == ("filled", False) and result["links_dropped"] == 0
    assert entry(adapter, "authentik") == before and _link_count(adapter) == 1
    # Once it answers, the links go, and the answer says how many.
    other.discovery_ok = True
    moved = setup(adapter, other, confirm=True)
    assert moved["ok"] and moved["links_dropped"] == 1 and _link_count(adapter) == 0


def test_30_another_authentik_asks_first_and_the_route_takes_the_confirmation(
    adapter: Any, ak: fakes.FakeAuthentik, net: fakes.Network
) -> None:
    setup(adapter, ak)
    adapter.make_account("alex")
    _link_through_authentik(adapter, ak)
    before = entry(adapter, "authentik")
    other = net.add(fakes.FakeAuthentik(base="https://auth2.example.com"))
    asked = setup(adapter, other)
    assert steps(asked) == [("reached", False)] and asked["steps"][0]["reason"] == "issuer_change"
    assert asked["count"] == 1 and asked["links_dropped"] == 0
    assert [call for call in other.calls if call.method != "GET"] == []
    assert entry(adapter, "authentik") == before and _link_count(adapter) == 1
    confirmed = setup(adapter, other, confirm=True)
    assert confirmed["ok"] and confirmed["links_dropped"] == 1 and _link_count(adapter) == 0


def test_32_the_blueprint_makes_the_same_objects_with_grant_types_and_the_callback(
    adapter: Any, ak: fakes.FakeAuthentik
) -> None:
    # Without a public address the blueprint names none guessed from the request (1.0.10): 409, and the card offers
    # the browser's address first.
    refused = adapter.blueprint()
    assert refused.status_code == 409 and adapter.error_code(refused) == "public_url_needed"
    assert "redirect_uris" not in refused.text
    adapter.set_public_url("https://app.example.org")
    response = adapter.blueprint()
    assert response.status_code == 200
    assert '"https://app.example.org/' in response.text and "http://testserver" not in response.text
    name = adapter_app(adapter)
    assert f'filename="{name}-authentik.yaml"' in response.headers["content-disposition"]
    text = response.text
    assert "grant_types:\n        - authorization_code" in text
    assert "authentik_providers_oauth2.oauth2provider" in text and "authentik_core.application" in text
    assert "email_verified" not in text and "scopemapping, [managed" in text
    setup(adapter, ak)
    assert json.dumps(entry(adapter, "authentik")["redirect_uri"]) in adapter.blueprint().text


# --- helpers -------------------------------------------------------------------------------------------------------


def adapter_app(adapter: Any) -> str:
    import conftest

    return conftest.oidc_package(adapter).current().app_name


def _link_through_authentik(adapter: Any, ak: fakes.FakeAuthentik) -> None:
    """alex links himself through the provider the button made: authentik signs him in."""
    item = entry(adapter, "authentik")
    provider = next(row for row in ak.providers if row["client_id"] == item["client_id"])
    signer = ak.sign_in_with(item["issuer"] + "/", provider["client_id"], provider["client_secret"])
    link_person(adapter, "alex", "authentik", signer)


def _link_count(adapter: Any) -> int:
    with adapter.store() as store:
        return len(store.links_of_provider(store.provider_by_slug("authentik").id))
