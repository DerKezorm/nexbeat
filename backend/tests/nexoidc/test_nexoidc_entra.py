"""Contract, Bauplan 05 "Entra ID", Pflichttests 7 to 12, through the app's own routes."""

from __future__ import annotations

from typing import Any

import oidc_fakes as fakes
import pytest
from conftest import add_in_store
from oidc_contract import error_in, link_person, location, round_trip

COMMON = f"{fakes.ENTRA}/common/v2.0"


@pytest.fixture
def entra(net: fakes.Network) -> fakes.FakeEntra:
    return net.add(fakes.FakeEntra())


def add_entra(adapter: Any, entra: fakes.FakeEntra, slug: str = "entra", issuer: str = COMMON) -> Any:
    if adapter.only_authentik:
        saved = add_in_store(adapter, entra, slug)
        with adapter.store() as store:
            row = store.get_provider(saved["id"])
            store.update_provider(row.id, _values(adapter, row, issuer=issuer))
            store.commit()
        return None
    return adapter.add_provider(entra, slug=slug, label="Microsoft", issuer=issuer)


def _values(adapter: Any, row: Any, **changes: Any) -> Any:
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
    return package.ProviderValues(**values)


def test_07_common_and_organizations_can_be_entered(adapter: Any, entra: fakes.FakeEntra) -> None:
    if adapter.only_authentik:
        pytest.xfail("only authentik: Entra comes through authentik (Bauplan 06)")
    for slug, issuer in (("entra", COMMON), ("orgs", f"{fakes.ENTRA}/organizations/v2.0")):
        response = add_entra(adapter, entra, slug, issuer)
        assert response.status_code in (200, 201), response.text
        assert response.json()["issuer"] == issuer


@pytest.mark.parametrize(
    "issuer",
    [
        f"{fakes.ENTRA}/common/x/v2.0",
        f"{fakes.ENTRA}/v2.0",
        "https://login.example.com/common/v2.0",
        f"{fakes.ENTRA}/common/v1.0",
        f"{fakes.ENTRA}/{{tenantid}}/v2.0",
    ],
    ids=["two-segments", "no-segment", "other-host", "other-version", "the-placeholder"],
)
def test_08_the_placeholder_stands_for_exactly_one_segment(adapter: Any, entra: fakes.FakeEntra, issuer: str) -> None:
    if adapter.only_authentik:
        pytest.xfail("only authentik: Entra comes through authentik (Bauplan 06)")
    response = add_entra(adapter, entra, "entra", issuer)
    assert response.status_code == 422, response.text
    assert adapter.providers() == []


@pytest.mark.parametrize(
    "published",
    [
        f"{fakes.ENTRA}/x{{tenantid}}/v2.0",
        f"{fakes.ENTRA}/{{tenantid}}/v2",
        "https://login.example.com/{tenantid}/v2.0",
    ],
    ids=["part-of-a-segment", "other-version", "other-host"],
)
def test_08_a_discovery_with_the_placeholder_elsewhere_is_refused(
    adapter: Any, entra: fakes.FakeEntra, published: str
) -> None:
    if adapter.only_authentik:
        pytest.xfail("only authentik: Entra comes through authentik (Bauplan 06)")
    entra.published = published
    response = add_entra(adapter, entra)
    assert response.status_code == 422 and adapter.error_code(response) == "oidc_issuer_mismatch"


def test_09_a_token_of_its_tenant_signs_in_and_so_does_any_tenant_whose_iss_and_tid_agree(
    adapter: Any, entra: fakes.FakeEntra
) -> None:
    add_entra(adapter, entra)
    adapter.make_account("max")
    link_person(adapter, "max", "entra", entra)
    browser, response = round_trip(adapter, entra, "entra")
    assert location(response) == adapter.home and adapter.who(browser) == "max"
    entra.tenant = fakes.OTHER_TENANT
    entra.person = {**entra.person, "sub": "entra-subject-2", "preferred_username": "kim@example.com"}
    adapter.make_account("kim")
    link_person(adapter, "kim", "entra", entra)
    browser, response = round_trip(adapter, entra, "entra")
    assert adapter.who(browser) == "kim"
    with adapter.store() as store:
        provider = store.provider_by_slug("entra")
        assert store.find_link(provider.id, "entra-subject-2").issuer == f"{fakes.ENTRA}/{fakes.OTHER_TENANT}/v2.0"


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": f"{fakes.ENTRA}/{fakes.OTHER_TENANT}/v2.0"},
        {"iss": fakes.ENTRA_PUBLISHED},
        {"tid": fakes.DROP},
        {"tid": "common", "iss": COMMON},
        {"tid": fakes.TENANT + "0", "iss": f"{fakes.ENTRA}/{fakes.TENANT}0/v2.0"},
        {"tid": f" {fakes.TENANT}", "iss": f"{fakes.ENTRA}/ {fakes.TENANT}/v2.0"},
        {"tid": fakes.TENANT + "\n", "iss": f"{fakes.ENTRA}/{fakes.TENANT}\n/v2.0"},
        {"tid": [fakes.TENANT]},
        {"tid": {"id": fakes.TENANT}},
    ],
    ids=[
        "other-tenant",
        "placeholder",
        "no-tid",
        "tid-common",
        "tid-longer",
        "tid-space",
        "tid-newline",
        "tid-list",
        "tid-object",
    ],
)
def test_10_a_token_whose_issuer_is_not_its_tenant_is_refused(
    adapter: Any, entra: fakes.FakeEntra, claims: dict
) -> None:
    add_entra(adapter, entra)
    adapter.make_account("max")
    link_person(adapter, "max", "entra", entra)
    entra.token_claims = claims
    browser, response = round_trip(adapter, entra, "entra")
    assert error_in(response) == "oidc_token_invalid" and adapter.who(browser) is None


def test_11_a_single_tenant_issuer_works_and_refuses_other_tenants(adapter: Any, entra: fakes.FakeEntra) -> None:
    add_entra(adapter, entra, "tenant", f"{fakes.ENTRA}/{fakes.TENANT}/v2.0")
    adapter.make_account("max")
    link_person(adapter, "max", "tenant", entra)
    assert location(round_trip(adapter, entra, "tenant")[1]) == adapter.home
    entra.tenant = fakes.OTHER_TENANT
    assert error_in(round_trip(adapter, entra, "tenant")[1]) == "oidc_token_invalid"


def test_12_a_new_account_is_named_after_the_part_before_the_at(adapter: Any, entra: fakes.FakeEntra) -> None:
    add_entra(adapter, entra)
    if adapter.single_account:
        browser, response = round_trip(adapter, entra, "entra")
        assert error_in(response) == "oidc_no_account" and adapter.who(browser) is None
        return
    key = adapter.make_invite("member")
    browser, response = round_trip(adapter, entra, "entra", invite=key)
    assert location(response) == adapter.home and adapter.who(browser) == "max"
