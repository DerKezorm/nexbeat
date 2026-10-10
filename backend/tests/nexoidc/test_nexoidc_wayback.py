"""Contract, Bauplan 01 "Umstieg" 4 and 22 of Bauplan 05: up again after the way back.

The app mirrors the entry ``oidc`` into its old settings and the old column after every change, and stores a
fingerprint of what it wrote. At the next start (``adapter.run_migration``) it takes over what the version before the
list changed since (``migrate.resync``), and nothing else. ``adapter.legacy_setup`` between two starts is that older
version at work: it writes the old settings and subjects the way the older version did.

Only for apps that kept one provider in their settings (``legacy_model == "single"``); the others have no way back.
"""

from __future__ import annotations

import logging
from typing import Any

import oidc_contract
import oidc_fakes as fakes
from conftest import add_in_store
from oidc_contract import location, start


def _one_provider(adapter: Any) -> bool:
    if adapter.legacy_model != "single":
        assert adapter.legacy_model in ("list", "none")
        return False
    return True


def migrated(adapter: Any, sso: fakes.FakeProvider, **subjects: str) -> dict[str, int]:
    """alex (and bob, where there are two accounts) and the old provider, migrated: the entry ``oidc`` with alex
    linked as ``person-1``. Returns the account ids by name."""
    ids = {"alex": adapter.make_account("alex")}
    if not adapter.single_account:
        ids["bob"] = adapter.make_account("bob")
    older(adapter, sso, subjects={"alex": "person-1", **subjects})
    adapter.run_migration()
    return ids


def older(adapter: Any, sso: fakes.FakeProvider, *, subjects: dict[str, str], **settings: str) -> None:
    """The version before the list writes its settings (as given, else the fake's) and the subjects named."""
    values = {
        "issuer": sso.issuer,
        "client_id": sso.client_id,
        "client_secret": sso.client_secret,
        "label": "Company",
        **settings,
    }
    adapter.legacy_setup(subjects=subjects, **values)


def the_entry(adapter: Any) -> Any:
    with adapter.store() as store:
        return store.provider_by_slug("oidc")


def linked(adapter: Any) -> dict[str, str]:
    """The links of the entry ``oidc``: account name to subject."""
    with adapter.store() as store:
        entry = store.provider_by_slug("oidc")
        if entry is None:
            return {}
        return {store.account_state(link.account_id).name: link.subject for link in store.links_of_provider(entry.id)}


def change_entry(adapter: Any, oidc: Any, **values: Any) -> None:
    """The new version changes the entry ``oidc`` (through the store, as every route does; the commit mirrors)."""
    with adapter.store() as store:
        entry = store.provider_by_slug("oidc")
        store.update_provider(entry.id, oidc.providers.values_of(entry, **values))
        store.commit()


def test_22_up_again_what_the_new_version_did_stays_when_the_older_one_changed_nothing(
    adapter: Any, sso: fakes.FakeProvider, oidc: Any
) -> None:
    if not _one_provider(adapter):
        return
    ids = migrated(adapter, sso)
    adapter.run_migration()
    assert linked(adapter) == {"alex": "person-1"}
    # Unlinked here: a start without a change in the older version does not bring the link back.
    with adapter.store() as store:
        assert store.remove_link(store.provider_by_slug("oidc").id, ids["alex"])
        store.commit()
    adapter.run_migration()
    assert linked(adapter) == {}
    # Off here, and on without the second factor checked by the provider: the mirror wrote "no provider" itself, and
    # that is no change of the older version.
    change_entry(adapter, oidc, enabled=False)
    adapter.run_migration()
    assert the_entry(adapter) is not None and the_entry(adapter).enabled is False
    change_entry(adapter, oidc, enabled=True, trusts_second_factor=False)
    adapter.run_migration()
    entry = the_entry(adapter)
    assert (entry.enabled, entry.trusts_second_factor) == (True, False)
    # Removed here: it stays removed.
    with adapter.store() as store:
        store.delete_provider(store.provider_by_slug("oidc").id)
        store.commit()
    adapter.run_migration()
    assert the_entry(adapter) is None


def test_22_up_again_a_subject_the_older_version_emptied_or_set_is_taken_over(
    adapter: Any, sso: fakes.FakeProvider
) -> None:
    if not _one_provider(adapter):
        return
    migrated(adapter, sso)
    older(adapter, sso, subjects={"alex": ""})
    adapter.run_migration()
    assert linked(adapter) == {}
    browser, response = oidc_contract.round_trip(adapter, sso, "oidc", legacy=True)
    assert oidc_contract.error_in(response) == "oidc_no_account" and adapter.who(browser) is None
    older(adapter, sso, subjects={"alex": "person-7"})
    adapter.run_migration()
    assert linked(adapter) == {"alex": "person-7"}
    if adapter.single_account:
        return
    older(adapter, sso, subjects={"bob": "person-2"})
    adapter.run_migration()
    assert linked(adapter) == {"alex": "person-7", "bob": "person-2"}
    # A subject another account holds here: the holder keeps it, and alex loses person-7 all the same (the older
    # version gave it up; it must not sign in again).
    older(adapter, sso, subjects={"alex": "person-2"})
    adapter.run_migration()
    assert linked(adapter) == {"bob": "person-2"}
    assert adapter.legacy_read()["subjects"] == {"bob": "person-2"}


def test_22_up_again_a_subject_that_moved_or_swapped_is_taken_over_in_any_order_of_the_accounts(
    adapter: Any, sso: fakes.FakeProvider
) -> None:
    """alex was made before bob. A subject that moves from bob to alex, from alex to bob, and two that swap: each
    taken over, nobody keeps a subject the older version took from them."""
    if not _one_provider(adapter) or adapter.single_account:
        return
    cases = [
        ({"alex": "person-2", "bob": ""}, {"alex": "person-2"}),
        ({"alex": "", "bob": "person-1"}, {"bob": "person-1"}),
        ({"alex": "person-2", "bob": "person-1"}, {"alex": "person-2", "bob": "person-1"}),
    ]
    migrated(adapter, sso)
    for subjects, expected in cases:
        older(adapter, sso, subjects={"alex": "person-1", "bob": "person-2"})
        adapter.run_migration()
        assert linked(adapter) == {"alex": "person-1", "bob": "person-2"}
        older(adapter, sso, subjects=subjects)
        adapter.run_migration()
        assert linked(adapter) == expected, subjects
        adapter.run_migration()
        assert linked(adapter) == expected, subjects
    # The one who gave a subject up cannot sign in with it any more; the one who got it can.
    browser, response = oidc_contract.round_trip(adapter, sso, "oidc", legacy=True)
    assert location(response) == adapter.home and adapter.who(browser) == "bob"


#: What the version before the list finds when the way back is closed (rule 3): no provider and no subject.
CLOSED = {"issuer": "", "client_id": "", "client_secret": "", "label": "", "auto_create": False, "subjects": {}}


def found(adapter: Any, *, like: dict[str, Any] = CLOSED) -> dict[str, Any]:
    """What the version before the list finds now, in the keys of ``like``."""
    read = adapter.legacy_read()
    return {key: read[key] for key in like}


def in_full(adapter: Any, sso: fakes.FakeProvider, **changes: Any) -> dict[str, Any]:
    """Rule 1: the entry ``oidc`` of ``migrated`` in full, as the version before the list finds it."""
    return {
        # As the version before the list wrote it (``older``), not the entry's form (since 1.0.11).
        "issuer": sso.issuer.strip(),
        "client_id": sso.client_id,
        "client_secret": sso.client_secret,
        "label": "Company",
        "auto_create": False,
        "subjects": {"alex": "person-1"},
        **changes,
    }


def set_issuer(adapter: Any, oidc: Any, issuer: str) -> None:
    """The new version changes the issuer of the entry ``oidc``, as the form does after its discovery."""
    with adapter.store() as store:
        entry = store.provider_by_slug("oidc")
        oidc.providers.change_issuer(store, entry, issuer)
        store.update_provider(entry.id, oidc.providers.values_of(entry, issuer=issuer))
        store.commit()


def test_22_rules_1_and_2_in_full_while_on_and_trusted_else_issuer_name_and_subjects_without_a_client(
    adapter: Any, sso: fakes.FakeProvider, oidc: Any
) -> None:
    """Rule 1: the entry in full while it is on and the provider checks the second factor. Rule 2: off, or not
    trusted, the issuer and the name stay, client id and secret are empty, "new people" off, the subjects stay. The
    version before the list knows neither switch: without a client it lets nobody in; if it sets another issuer up,
    its own comparison drops the old subjects; on again brings everything back (nexcanvas finding 2, 10.10.2026)."""
    if not _one_provider(adapter):
        return
    migrated(adapter, sso)
    many = not adapter.single_account
    # An app whose older version asked the code (nexdiary, nexpaper) migrated to an entry that does not trust the
    # provider; trusted, its settings are written in full.
    change_entry(adapter, oidc, trusts_second_factor=True, auto_create=many)
    full = in_full(adapter, sso, auto_create=many)
    assert found(adapter, like=full) == full
    without = {**full, "client_id": "", "client_secret": "", "auto_create": False}
    for values in (
        {"trusts_second_factor": False},
        {"enabled": False},
        {"enabled": False, "trusts_second_factor": True},
    ):
        change_entry(adapter, oidc, **values)
        for _ in range(2):
            assert found(adapter, like=full) == without, values
            adapter.run_migration()
        change_entry(adapter, oidc, enabled=True, trusts_second_factor=True)
        assert found(adapter, like=full) == full, values


def test_22_rule_3_an_issuer_changed_here_closes_the_way_back_for_good_until_the_older_version_sets_one_up(
    adapter: Any, sso: fakes.FakeProvider, oidc: Any
) -> None:
    """Another issuer at the entry than the one the version before the list knows: it finds nothing, not the new
    issuer, or its bridge over a confirmed address would sign anyone in as an account without a subject, and its
    "new people" would let strangers in (nexcanvas finding 1, nextasks finding 1). For good: through starts, off and
    on, a link made here, and the issuer set back. Rule 4: only a provider the older version sets up opens it."""
    if not _one_provider(adapter):
        return
    ids = migrated(adapter, sso)
    change_entry(adapter, oidc, auto_create=not adapter.single_account)
    set_issuer(adapter, oidc, "https://other.example.com")
    assert found(adapter) == CLOSED
    adapter.run_migration()
    assert found(adapter) == CLOSED
    change_entry(adapter, oidc, enabled=False)
    change_entry(adapter, oidc, enabled=True)
    with adapter.store() as store:
        entry = store.provider_by_slug("oidc")
        store.add_link(oidc.Link(provider_id=entry.id, subject="other-1", account_id=ids["alex"], issuer="x"))
        store.commit()
    assert found(adapter) == CLOSED
    # A subject the older version writes without a provider names nobody at the entry.
    older(adapter, sso, subjects={"alex": "person-5"}, issuer="", client_id="", client_secret="", label="")
    adapter.run_migration()
    assert "person-5" not in linked(adapter).values()
    assert found(adapter) == CLOSED
    set_issuer(adapter, oidc, sso.issuer)
    adapter.run_migration()
    assert found(adapter) == CLOSED
    older(adapter, sso, subjects={"alex": "person-1"}, label="Again")
    adapter.run_migration()
    entry = the_entry(adapter)
    assert (entry.label, entry.enabled) == ("Again", True)
    assert linked(adapter) == {"alex": "person-1"}
    assert found(adapter, like=in_full(adapter, sso)) == in_full(adapter, sso, label="Again")


def test_22_rule_3_an_entry_removed_here_stays_closed_also_for_a_new_entry_oidc(
    adapter: Any, sso: fakes.FakeProvider, oidc: Any
) -> None:
    if not _one_provider(adapter):
        return
    migrated(adapter, sso)
    with adapter.store() as store:
        store.delete_provider(store.provider_by_slug("oidc").id)
        store.commit()
    assert found(adapter) == CLOSED
    old = oidc.migrate.Legacy(issuer=sso.issuer, client_id=sso.client_id, client_secret=sso.client_secret)
    with adapter.store() as store:
        store.insert_provider(oidc.migrate.plan(old, [], trusts_second_factor=True).provider)
        store.commit()
    for _ in range(2):
        assert found(adapter) == CLOSED
        adapter.run_migration()
    assert the_entry(adapter) is not None


def test_22_rule_2_on_again_is_no_change_and_a_provider_removed_in_the_older_version_while_off_takes_the_entry(
    adapter: Any, sso: fakes.FakeProvider, oidc: Any
) -> None:
    """Off here, the issuer stays (rule 2): starts change nothing, and on again is the new version's own doing, no
    change of the older one. Off, and "remove the provider" there: since 1.0.10 the fingerprint keeps the issuer
    alone, so that is seen, and it does what removing does everywhere: the entry goes with its links, the way back
    closes (nexbrand finding 2, nextrmnl and nexsift finding M-2)."""
    if not _one_provider(adapter):
        return
    migrated(adapter, sso)
    change_entry(adapter, oidc, enabled=False, trusts_second_factor=True)
    adapter.run_migration()
    change_entry(adapter, oidc, enabled=True)
    adapter.run_migration()
    entry = the_entry(adapter)
    assert entry is not None and entry.enabled is True and linked(adapter) == {"alex": "person-1"}
    assert found(adapter, like=in_full(adapter, sso)) == in_full(adapter, sso)
    change_entry(adapter, oidc, enabled=False)
    adapter.run_migration()
    assert the_entry(adapter) is not None and linked(adapter) == {"alex": "person-1"}
    older(adapter, sso, subjects={"alex": "person-1"}, issuer="", client_id="", client_secret="", label="")
    adapter.run_migration()
    assert the_entry(adapter) is None and linked(adapter) == {}
    assert found(adapter) == CLOSED


def test_22_the_issuer_stays_as_the_older_version_wrote_it_letter_by_letter(
    adapter: Any, sso: fakes.FakeProvider, oidc: Any
) -> None:
    """Most versions before the list compare their issuer setting letter by letter when a provider is saved
    (nexcanvas, nextasks, nexbrand, nextrmnl, nexsift, nexcrate), and their authentik button writes it with a slash.
    Written back without one, the next press of that button there took it for another provider and dropped every
    subject. So the way back writes the issuer the older version knows, character by character: after the
    migration, through off and on, a save here and a start; the entry keeps its own form (since 1.0.11)."""
    if not _one_provider(adapter):
        return
    bare = sso.issuer.strip().rstrip("/")
    slashed = bare + "/"
    adapter.make_account("alex")
    older(adapter, sso, subjects={"alex": "person-1"}, issuer=slashed)
    adapter.run_migration()
    assert the_entry(adapter).issuer == bare

    def issuer_there() -> str:
        return adapter.legacy_read()["issuer"]

    assert issuer_there() == slashed
    for values in ({"enabled": False}, {"enabled": True}, {"label": "Renamed"}, {"trusts_second_factor": False}):
        change_entry(adapter, oidc, **values)
        assert issuer_there() == slashed, values
        adapter.run_migration()
        assert issuer_there() == slashed, values
    change_entry(adapter, oidc, trusts_second_factor=True, label="Company")
    assert found(adapter, like=in_full(adapter, sso)) == in_full(adapter, sso, issuer=slashed)
    browser, response = oidc_contract.round_trip(adapter, sso, "oidc", legacy=True)
    assert location(response) == adapter.home and adapter.who(browser) == "alex"
    # The older version's form writes it without the slash: that text from now on, and the links stay.
    older(adapter, sso, subjects={"alex": "person-1"}, issuer=bare, label="Form")
    adapter.run_migration()
    change_entry(adapter, oidc, enabled=False)
    change_entry(adapter, oidc, enabled=True)
    assert issuer_there() == bare and linked(adapter) == {"alex": "person-1"}
    # Its button writes it with the slash again, with another name (taken over) and then alone (no change at all in
    # the fingerprint): the way back follows both times, through a start and a save here.
    for issuer, label in ((slashed, "authentik"), (bare, "authentik"), (slashed, "authentik")):
        older(adapter, sso, subjects={"alex": "person-1"}, issuer=issuer, label=label)
        adapter.run_migration()
        change_entry(adapter, oidc, enabled=True)
        assert issuer_there() == issuer and linked(adapter) == {"alex": "person-1"}, issuer


class _Lines(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


def test_22_every_commit_writes_the_way_back_also_when_an_account_is_deleted(
    adapter: Any, sso: fakes.FakeProvider, oidc: Any
) -> None:
    """Every commit that changes accounts, links or the entry writes the way back and its fingerprint, also one that
    goes around the store (deleting an account): else the next start takes the stale fingerprint for a change of the
    older version (a line in the log, a backup for nothing; nextrmnl and nexsuite, 10.10.2026)."""
    if not _one_provider(adapter) or adapter.single_account:
        return
    migrated(adapter, sso, bob="person-2")
    assert linked(adapter) == {"alex": "person-1", "bob": "person-2"}
    adapter.delete_account("bob")
    # Straight to the next start: no other commit in between that would write the fingerprint anew.
    lines = _Lines()
    logger = logging.getLogger(oidc.config.current().log_name)
    logger.addHandler(lines)
    try:
        adapter.run_migration()
    finally:
        logger.removeHandler(lines)
    assert not [line for line in lines.lines if "took over" in line], lines.lines
    assert linked(adapter) == {"alex": "person-1"} and adapter.legacy_read()["subjects"] == {"alex": "person-1"}


def test_22_a_start_without_any_provider_stores_the_fingerprint_so_one_set_up_later_in_the_older_version_comes_in(
    adapter: Any, sso: fakes.FakeProvider
) -> None:
    """The first start finds no provider, nothing to migrate: the fingerprint ("no provider") is stored all the same,
    or the next start could not tell that the older version set one up since, and its mirror would throw it away
    (nexbrand finding 1)."""
    if not _one_provider(adapter):
        return
    adapter.make_account("alex")
    adapter.run_migration()
    assert found(adapter) == CLOSED and the_entry(adapter) is None
    adapter.run_migration()
    older(adapter, sso, subjects={"alex": "person-1"})
    adapter.run_migration()
    entry = the_entry(adapter)
    assert entry is not None and entry.enabled and entry.label == "Company"
    assert linked(adapter) == {"alex": "person-1"}
    assert found(adapter, like=in_full(adapter, sso)) == in_full(adapter, sso)
    browser, response = oidc_contract.round_trip(adapter, sso, "oidc", legacy=True)
    assert location(response) == adapter.home and adapter.who(browser) == "alex"


def test_22_up_again_a_provider_the_older_version_removed_is_gone(adapter: Any, sso: fakes.FakeProvider) -> None:
    if not _one_provider(adapter):
        return
    migrated(adapter, sso)
    older(adapter, sso, subjects={"alex": ""}, issuer="", client_id="", client_secret="", label="")
    adapter.run_migration()
    assert the_entry(adapter) is None
    assert oidc_contract.error_in(start(adapter, adapter.browser(), "oidc")) == "oidc_not_configured"


def test_22_up_again_a_provider_the_older_version_set_up_comes_back_as_the_entry_oidc(
    adapter: Any, sso: fakes.FakeProvider
) -> None:
    if not _one_provider(adapter):
        return
    migrated(adapter, sso)
    with adapter.store() as store:
        store.delete_provider(store.provider_by_slug("oidc").id)
        store.commit()
    adapter.run_migration()
    assert the_entry(adapter) is None
    older(adapter, sso, subjects={"alex": "person-1"}, label="Again")
    adapter.run_migration()
    entry = the_entry(adapter)
    assert entry is not None and (entry.label, entry.enabled, entry.redirect_path) == ("Again", True, "")
    assert linked(adapter) == {"alex": "person-1"}
    browser = adapter.browser()
    target = location(start(adapter, browser, "oidc"))
    assert fakes.query_of(target)["redirect_uri"].endswith(adapter.path("legacy_callback"))
    response = oidc_contract.come_back(adapter, browser, "oidc", sso.authorize(target), legacy=True)
    assert location(response) == adapter.home and adapter.who(browser) == "alex"


def test_22_up_again_new_values_for_the_same_issuer_are_taken_over_and_the_links_stay(
    adapter: Any, sso: fakes.FakeProvider
) -> None:
    if not _one_provider(adapter):
        return
    migrated(adapter, sso)
    older(
        adapter,
        sso,
        subjects={"alex": "person-1"},
        issuer=sso.issuer + "/",
        client_id="client-of-the-older-version",
        client_secret="secret-of-the-older-version",
        label="Renamed",
    )
    adapter.run_migration()
    entry = the_entry(adapter)
    assert (entry.issuer, entry.label, entry.client_id, entry.client_secret) == (
        sso.issuer,
        "Renamed",
        "client-of-the-older-version",
        "secret-of-the-older-version",
    )
    assert linked(adapter) == {"alex": "person-1"}


def test_22_up_again_another_issuer_drops_the_links_and_takes_the_values(adapter: Any, sso: fakes.FakeProvider) -> None:
    if not _one_provider(adapter):
        return
    migrated(adapter, sso)
    other = "https://other.example.com"
    # alex's subject stands unchanged: it was the old issuer's, and goes with it.
    older(adapter, sso, subjects={"alex": "person-1"}, issuer=other, client_id="other-client", label="Other")
    adapter.run_migration()
    entry = the_entry(adapter)
    assert (entry.issuer, entry.client_id, entry.label) == (other, "other-client", "Other")
    assert linked(adapter) == {}
    older(adapter, sso, subjects={"alex": "other-7"}, issuer=other, client_id="other-client", label="Other")
    adapter.run_migration()
    assert linked(adapter) == {"alex": "other-7"}


def test_22_up_again_a_provider_set_up_while_the_entry_was_off_turns_it_on(
    adapter: Any, sso: fakes.FakeProvider, oidc: Any
) -> None:
    if not _one_provider(adapter):
        return
    migrated(adapter, sso)
    change_entry(adapter, oidc, enabled=False)
    adapter.run_migration()
    older(adapter, sso, subjects={"alex": "person-1"}, label="On again")
    adapter.run_migration()
    entry = the_entry(adapter)
    assert (entry.enabled, entry.label, entry.trusts_second_factor) == (True, "On again", adapter.trusted_before)
    assert linked(adapter) == {"alex": "person-1"}


def test_22_up_again_nothing_is_taken_over_while_coupled(adapter: Any, sso: fakes.FakeProvider, oidc: Any) -> None:
    if not _one_provider(adapter) or not adapter.supports_coupling:
        return
    ids = migrated(adapter, sso)
    suite = fakes.FakeProvider("https://suite.example.com")
    with adapter.store() as store:
        coupled = oidc.coupling.couple(
            store,
            issuer=suite.issuer,
            client_id=suite.client_id,
            client_secret=suite.client_secret,
            label="Suite",
            people=[(ids["alex"], "p-alex")],
        )
    adapter.run_migration()
    before = sorted((item["slug"], item["issuer"], item["enabled"]) for item in adapter.providers())
    older(adapter, sso, subjects={"alex": "elsewhere"}, issuer="https://other.example.com", client_id="other")
    adapter.run_migration()
    assert sorted((item["slug"], item["issuer"], item["enabled"]) for item in adapter.providers()) == before
    # The anchor outlives the coupling: uncoupled, the way back shows the own entry in full again.
    with adapter.store() as store:
        oidc.coupling.uncouple(store, coupled)
    adapter.run_migration()
    assert linked(adapter) == {"alex": "person-1"}
    assert found(adapter, like=in_full(adapter, sso)) == in_full(adapter, sso)


def test_22_the_helper_for_entries_in_the_store_is_untouched_by_the_way_back(adapter: Any, net: fakes.Network) -> None:
    """Another entry than ``oidc`` is no business of the way back: a start leaves it alone."""
    if not _one_provider(adapter):
        return
    fake = net.add(fakes.FakeProvider("https://store.example.com"))
    add_in_store(adapter, fake, "stored")
    adapter.run_migration()
    adapter.run_migration()
    with adapter.store() as store:
        assert [item.slug for item in store.list_providers()] == ["stored"]
