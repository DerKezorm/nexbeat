"""The way from one provider in the settings to the list (Bauplan 01 "Umstieg", 06 "Wanderung").

nexlore, nexcanvas, nextasks, nexsuite, nexbrand, nexdiary, nexpaper, nexsift, nextrmnl and nexcrate keep one provider
in their settings (``oidc_issuer``, ``oidc_client_id`` …) and the subject at the account (``oidc_subject``; nexcrate
in its settings). At the first start with the module, inside the app's own migration and after its backup, these become:

1. an entry with the slug ``oidc``: name as before, ``auto_create`` as before, ``trusts_second_factor`` as the app
   behaved before (on for the apps that asked no code after the provider, off for nexdiary and nexpaper),
   ``managed = "authentik"`` when the issuer ends in ``/application/o/<slug>/`` and the button had set it up;
2. a link per stored subject (``issuer`` = the issuer so far);
3. the old callback ``<api>/oidc/callback`` stays valid for ever and belongs to that entry (``flow.callback_path``).

The bridge over a confirmed address is gone for everybody at once: accounts that found each other through it have
their subject stored already and move along. The old settings and the column stay readable for one version (the
app's business), then they go.

``plan`` is pure; ``apply`` writes the plan through the ``Store`` once (a second run finds the entry and does
nothing).

**Up again after the way back** (since 1.0.9). While the old settings stay, the app mirrors the entry ``oidc`` into
them after every change (the way back). An operator may go back to the older version, change something there and
come up again; the list would never see that change and the next mirror would overwrite it. So the app keeps a
``fingerprint`` of what its mirror wrote, and at start-up ``resync`` takes over what the older version changed
since: only the parts whose fingerprint differs, nothing else. The fingerprint holds hashes only, never a secret or a
subject in the clear.

**One rule for the way back** (since 1.0.10). What the old settings and the old column show is ``way_back``'s, not
the app's: it depends only on the entry ``oidc`` and the **anchor**, the issuer the older version knows (at the
migration the old issuer, after a take-over by ``resync`` the one taken over). The same issuer and the entry on and
trusted with the second factor: the entry in full. The same issuer and the entry off or not trusted: issuer and name
stay, no client, ``auto_create`` off, the subjects as they are. Another issuer than the anchor, or no entry: all
empty, and the anchor is closed for good (``CLOSED``); only ``resync`` opens it again, when the older version sets a
provider up.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace

from . import config, coupling, model, protocol, providers
from .model import (
    LEGACY_SLUG,
    MANAGED_AUTHENTIK,
    MANAGED_NEXSUITE,
    Link,
    Provider,
    ProviderValues,
    Store,
)

DEFAULT_LABEL = "OpenID Connect"
_AUTHENTIK_ISSUER = re.compile(r"/application/o/[-A-Za-z0-9_]+/?$")


def _log() -> logging.Logger:
    return logging.getLogger(config.current().log_name)


@dataclass(frozen=True)
class Legacy:
    """The single provider as the app stored it. ``set_up_by_button``: the authentik button wrote these settings
    (each app knows how it marked that, nexlore by the name "authentik")."""

    issuer: str
    client_id: str
    client_secret: str
    label: str = ""
    auto_create: bool = False
    set_up_by_button: bool = False
    #: The callback the provider knows when it is not ``<api>/oidc/callback`` (the app's old route), else "".
    redirect_path: str = ""


@dataclass(frozen=True)
class Plan:
    provider: ProviderValues
    links: list[tuple[int, str]] = field(default_factory=list)


def plan(legacy: Legacy, subjects: Iterable[tuple[int, str]], *, trusts_second_factor: bool) -> Plan | None:
    """The entry and the links the old settings become; None when no provider was set up (nothing to move)."""
    issuer = protocol.normalize_issuer(legacy.issuer)
    if not issuer or not legacy.client_id.strip():
        return None
    managed = (
        model.MANAGED_AUTHENTIK
        if legacy.set_up_by_button and _AUTHENTIK_ISSUER.search(legacy.issuer.strip())
        else model.MANAGED_HAND
    )
    values = ProviderValues(
        slug=LEGACY_SLUG,
        label=" ".join(legacy.label.split()) or DEFAULT_LABEL,
        issuer=issuer,
        client_id=legacy.client_id.strip(),
        client_secret=legacy.client_secret,
        scopes=model.DEFAULT_SCOPES,
        enabled=True,
        auto_create=legacy.auto_create and not config.current().single_account,
        trusts_second_factor=trusts_second_factor,
        managed=managed,
        position=0,
        redirect_path=providers.check_redirect_path(legacy.redirect_path),
    )
    seen: set[str] = set()
    links: list[tuple[int, str]] = []
    for account_id, subject in subjects:
        if not subject or not subject.strip() or subject in seen:
            continue
        seen.add(subject)
        links.append((account_id, subject))
    return Plan(provider=values, links=links)


def apply(store: Store, migration: Plan | None) -> Provider | None:
    """Write the plan once. Returns the new entry, or None when there was nothing to do (no old provider, or the entry
    ``oidc`` exists already)."""
    if migration is None or store.provider_by_slug(LEGACY_SLUG) is not None:
        return None
    entry = store.insert_provider(migration.provider)
    for account_id, subject in migration.links:
        store.add_link(Link(provider_id=entry.id, subject=subject, account_id=account_id, issuer=entry.issuer))
    store.commit()
    _log().warning(
        "OIDC: the provider from the settings became entry %s with %d links (issuer %s)",
        entry.slug,
        len(migration.links),
        entry.issuer,
    )
    return entry


def old_callback(template: str, slug: str) -> str:
    """The callback path a provider of an app with a list knew before the module, for that app's own migration of
    its table (Bauplan 01, last paragraph; 06 "Pfad der Schnittstelle"): nexbeat ``/api/auth/oidc/{slug}/callback``,
    nexdeck ``/api/v1/auth/oidc/{slug}/callback``, nexview, nexmail their own. The app stores it as the entry's
    ``redirect_path``; the start then sends it, the cookie follows it, and the app routes it to the same return."""
    return providers.check_redirect_path(template.format(slug=slug))


def apply_coupled(
    store: Store,
    *,
    nexsuite: Legacy,
    own: Legacy | None,
    people: Iterable[tuple[int, str]],
    own_subjects: Iterable[tuple[int, str]],
    trusts_second_factor: bool,
    label: str = "nexsuite",
) -> coupling.Coupling | None:
    """``trusts_second_factor`` is how the app behaved so far, for both entries: its own and the coupled one.

    The migration of an app that is coupled to nexsuite at the moment (Bauplan 06, Verbund): its own provider from
    before the coupling (the settings it saved for the way back, and the subjects it kept apart, nexcanvas
    ``oidc_subject_local``) becomes the entry ``oidc`` with its links, set aside at once; nexsuite becomes the coupled
    entry with the accounts' persons. Returns what the app keeps for uncoupling; None when there is a list already."""
    if store.list_providers():
        return None
    if own is not None:
        apply(store, plan(own, own_subjects, trusts_second_factor=trusts_second_factor))
    return coupling.couple(
        store,
        issuer=nexsuite.issuer,
        client_id=nexsuite.client_id,
        client_secret=nexsuite.client_secret,
        label=label,
        people=people,
        trusts_second_factor=trusts_second_factor,
    )


# ---------------------------------------------------------------------------
# Up again after the way back (fingerprint and resync)
# ---------------------------------------------------------------------------

#: The form of a fingerprint. Since 1.0.10 the provider part tells "only an issuer" (rule 2 of ``way_back``) from "no
#: provider", so that a provider the older version removes while the entry is off is seen.
FINGERPRINT_FORM = "nexoidc-fp2"
#: The forms ``resync`` compares: one stored by 1.0.9 is compared with the settings of now in its own form, so the
#: first start with 1.0.10 sees what the older version changed as 1.0.9 would have. A stored one of another form is
#: not compared (nothing taken over, a new one is stored).
_FORMS = ("nexoidc-fp1", FINGERPRINT_FORM)
#: Settings without an issuer: the older version knows no provider.
_NO_PROVIDER = "-"
#: Before a provider part: an issuer without a client id (``way_back`` rule 2), no provider to sign in through.
_ISSUER_ONLY = "~"
#: The anchor of a way back that is closed for good: the older version is shown no provider and no subject, whatever
#: the entry ``oidc`` says, until ``resync`` takes over a provider the older version set up (Bauplan 01 "Umstieg").
CLOSED = "-"


def _hashed(kind: str, value: object, form: str = FINGERPRINT_FORM) -> str:
    """128 bits of SHA-256 over a canonical form, base64url without padding: no character a fingerprint uses to
    separate its parts, and nothing the scanners take for a key. No key of the app goes in: a fingerprint must stay
    the same when the app's secret changes or a backup comes back, or a change that never happened would be taken
    over. The secret it covers is in the same database, encrypted, anyway."""
    canonical = json.dumps([form, kind, value], ensure_ascii=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("ascii")).digest()[:16]
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _has_provider(legacy: Legacy) -> bool:
    return bool(protocol.normalize_issuer(legacy.issuer)) and bool(legacy.client_id.strip())


def _settings_part(legacy: Legacy, form: str) -> str:
    if not _has_provider(legacy):
        issuer = protocol.normalize_issuer(legacy.issuer)
        if form == FINGERPRINT_FORM and issuer:
            return _ISSUER_ONLY + _hashed("issuer", issuer, form)
        return _NO_PROVIDER
    return _hashed(
        "settings",
        [
            protocol.normalize_issuer(legacy.issuer),
            legacy.client_id.strip(),
            # The secret only as a hash inside the hash: it never stands anywhere in the clear.
            hashlib.sha256(legacy.client_secret.encode("utf-8")).hexdigest(),
            " ".join(legacy.label.split()),
            bool(legacy.auto_create),
        ],
        form,
    )


def _subjects_of(subjects: Iterable[tuple[int, str]]) -> dict[int, str]:
    """Each account's old subject; empty ones are no subject. An account named twice keeps the first."""
    found: dict[int, str] = {}
    for account_id, subject in subjects:
        if subject and subject.strip() and int(account_id) not in found:
            found[int(account_id)] = subject
    return found


def fingerprint(legacy: Legacy, subjects: Iterable[tuple[int, str]]) -> str:
    """What the old settings and the old column say now, as the app reads them for ``plan`` (the same ``Legacy`` and
    the same subjects). Pure and stable: the same settings give the same fingerprint, in any order of the subjects.

    The app stores it after every mirror (inside the same transaction) and compares it at start-up. It holds one
    hash for the provider (issuer, client id, secret, name, ``auto_create``; without a client id the issuer alone,
    marked ``~``; or "no provider" without an issuer) and one per account with a subject, so that ``resync`` can tell
    which of them the older version changed."""
    return _fingerprint(legacy, subjects, FINGERPRINT_FORM)


def _fingerprint(legacy: Legacy, subjects: Iterable[tuple[int, str]], form: str) -> str:
    accounts = ",".join(
        f"{account_id}:{_hashed('subject', subject, form)}"
        for account_id, subject in sorted(_subjects_of(subjects).items())
    )
    return f"{form}|{_settings_part(legacy, form)}|{accounts}"


@dataclass(frozen=True)
class _Print:
    form: str
    settings: str
    accounts: dict[int, str]

    @property
    def provider(self) -> bool:
        """The older version had a provider to sign in through (issuer and client id)."""
        return self.settings != _NO_PROVIDER and not self.settings.startswith(_ISSUER_ONLY)


def _read(value: str | None) -> _Print | None:
    parts = (value or "").split("|")
    if len(parts) != 3 or parts[0] not in _FORMS or not parts[1]:
        return None
    accounts: dict[int, str] = {}
    for item in filter(None, parts[2].split(",")):
        account, _, digest = item.partition(":")
        if not account.isdigit() or not digest:
            return None
        accounts[int(account)] = digest
    return _Print(form=parts[0], settings=parts[1], accounts=accounts)


@dataclass(frozen=True)
class Changes:
    """What the older version changed since the stored fingerprint. ``known`` False: there is no stored fingerprint
    of a form it reads, or two different forms: nothing can be told and nothing is taken over."""

    known: bool = False
    settings: bool = False
    accounts: frozenset[int] = frozenset()

    @property
    def any(self) -> bool:
        return self.settings or bool(self.accounts)


def changes(previous: str | None, current: str) -> Changes:
    """Compare a stored fingerprint with the one of now. For an app that keeps the old settings somewhere else as
    well (nexcanvas ``oidc_way_back_held``): ``settings`` True means the older version wrote new settings, and they
    win over such a copy."""
    before, now = _read(previous), _read(current)
    if before is None or now is None or before.form != now.form:
        return Changes()
    touched = {
        account
        for account in before.accounts.keys() | now.accounts.keys()
        if before.accounts.get(account) != now.accounts.get(account)
    }
    return Changes(known=True, settings=before.settings != now.settings, accounts=frozenset(touched))


def changes_since(previous: str | None, legacy: Legacy, subjects: Iterable[tuple[int, str]]) -> Changes:
    """What the older version changed since the stored fingerprint ``previous``, read from the old settings and the
    old column as for ``plan``: the comparison ``resync`` makes, in the form ``previous`` was stored in (one of 1.0.9
    is compared as 1.0.9 would have). For an app that makes a backup before ``resync`` only when something changed:
    ``changes_since(...).any``. ``changes`` alone compares two fingerprints of one form and tells nothing across
    forms."""
    stored = _read(previous)
    return changes(previous, _fingerprint(legacy, list(subjects), stored.form if stored else FINGERPRINT_FORM))


@dataclass
class Resync:
    """What ``resync`` did. ``coupled``: nothing, because the app is coupled to nexsuite (the list changes through the
    coupling only, Bauplan 06)."""

    changes: Changes = field(default_factory=Changes)
    coupled: bool = False
    removed: bool = False
    created: bool = False
    issuer_changed: bool = False
    values_taken: bool = False
    linked: list[int] = field(default_factory=list)
    unlinked: list[int] = field(default_factory=list)
    #: Accounts whose new old subject another account holds already: without a link at the entry now (their old one
    #: went, the older version gave it up); they are in ``unlinked`` as well when they had one.
    refused: list[int] = field(default_factory=list)
    #: The anchor from now on (since 1.0.10): what the app stores for ``way_back`` (``keep_anchor`` got it already).
    anchor: str = CLOSED

    @property
    def wrote(self) -> bool:
        changed = self.removed or self.created or self.issuer_changed or self.values_taken
        return changed or bool(self.linked or self.unlinked)


def _current_subject(store: Store, entry: Provider, account_id: int) -> str:
    return next((link.subject for link in store.links_of_account(account_id) if link.provider_id == entry.id), "")


def _take_subjects(store: Store, entry: Provider, wanted: dict[int, str], done: Resync) -> None:
    """Each account in ``wanted`` has at the entry now the subject the older version set ("" none).

    Two rounds, so that the order of the accounts decides nothing: first every link the older version gave up goes
    (emptied, or the account has another subject now), then the new subjects are linked. One round per account in turn
    found a subject that moved from bob to alex still at bob when alex came first, and left alex at the subject the
    older version had taken from him. An account whose new subject another account still holds loses its old link all
    the same (the older version gave it up) and gets none: a line in the log."""
    dropped: list[int] = []
    for account_id, subject in sorted(wanted.items()):
        current = _current_subject(store, entry, account_id)
        if current and current != subject and store.remove_link(entry.id, account_id):
            dropped.append(account_id)
    for account_id, subject in sorted(wanted.items()):
        if not subject or _current_subject(store, entry, account_id) == subject:
            continue
        holder = store.find_link(entry.id, subject)
        if holder is not None:
            done.refused.append(account_id)
            _log().warning(
                "OIDC: the older version gave account %d a subject of entry %s that account %d holds; account %d is "
                "left without a link there",
                account_id,
                entry.slug,
                holder.account_id,
                account_id,
            )
            continue
        if store.account_state(account_id) is None:
            continue
        store.add_link(Link(provider_id=entry.id, subject=subject, account_id=account_id, issuer=entry.issuer))
        done.linked.append(account_id)
    done.unlinked.extend(account_id for account_id in dropped if account_id not in done.linked)


def resync(
    store: Store,
    legacy: Legacy,
    subjects: Iterable[tuple[int, str]],
    *,
    previous: str | None,
    trusts_second_factor: bool,
    anchor: str | None = None,
    keep_anchor: Callable[[str], None] | None = None,
) -> Resync:
    """At start-up, after the first migration, before the next mirror: take over what the older version changed in
    the old settings and the old column since the fingerprint ``previous`` was stored. ``legacy`` and ``subjects`` are
    read as for ``plan``; ``trusts_second_factor`` is how the older version behaved (as for ``plan``).

    Only what differs from the fingerprint counts, so an "empty" the mirror wrote itself (entry off, or the provider
    not checking the second factor) is no change. What changed:

    - the old settings now without a provider (no client id; also when only the issuer stood there, the entry off
      or not trusted, and the older version removed it): the entry ``oidc`` goes, with its links;
    - a provider there and no entry ``oidc``: the entry is made as by the migration (its old callback);
    - another issuer: like an issuer change (the entry's links go, the older version's values come in);
    - the same issuer: client id, secret, name and ``auto_create`` are taken over;
    - either way, if the older version set a provider up where it had none, the entry is on again and trusts the
      provider as the older version did (there, a provider that is set up is on);
    - an account's old subject emptied: its link at the entry goes; set or changed: it is linked, unless another
      account holds that subject (then its old link goes all the same and it gets none, a line in the log). All links
      given up go first, then the new ones are made: a subject that moved from one account to another, or two that
      swapped, are taken over in any order of the accounts.

    While the app is coupled to nexsuite, nothing (``Resync.coupled``). Commits once when it wrote anything; the app's
    commit mirrors again, and the app stores the new fingerprint.

    **The anchor** (since 1.0.10): ``anchor`` is the one the app stored (None or "" when it has none yet: a database
    migrated before 1.0.10). ``Resync.anchor`` is the one from now on: the issuer taken over when the older version
    set a provider up or changed it, ``CLOSED`` when it removed it, else the stored one. Without a stored one it is
    derived: the issuer of the entry ``oidc`` while the old settings name the same issuer, else ``CLOSED``. The app
    stores it through ``keep_anchor``, which is called once, always, before ``resync`` commits: the mirror inside that
    commit must see the new anchor, or it would close the way back on a take-over. A subject is taken over only while
    the anchor is the entry's issuer (a closed way back shows the older version no provider, so a subject it wrote
    then names nobody at the entry)."""
    subjects = list(subjects)
    stored = _read(previous)
    found = changes_since(previous, legacy, subjects)
    done = Resync(changes=found)
    entry = store.provider_by_slug(LEGACY_SLUG)
    coupled_now = providers.coupled(store) or (entry is not None and entry.managed == MANAGED_NEXSUITE)
    if not found.any or coupled_now:
        done.anchor = _kept(store, legacy, anchor)
        if keep_anchor is not None:
            keep_anchor(done.anchor)
        if found.any:
            done.coupled = True
            _log().warning("OIDC: the older version changed its sign-in settings while coupled; nothing taken over")
        return done
    olds = _subjects_of(subjects)
    touched = set(found.accounts)
    if found.settings:
        had_provider = stored is not None and stored.provider
        wanted = plan(legacy, sorted(olds.items()), trusts_second_factor=trusts_second_factor)
        # The issuer as the older version wrote it (slash and all): it compares its own setting letter by letter.
        done.anchor = CLOSED if wanted is None else _open(legacy.issuer) or CLOSED
        if wanted is None:
            if entry is not None:
                store.delete_provider(entry.id)
                done.removed = True
            entry = None
        elif entry is None:
            position = max((item.position for item in store.list_providers()), default=-1) + 1
            entry = store.insert_provider(replace(wanted.provider, position=position))
            done.created = True
            # A new entry: every old subject is the older version's, as at the migration.
            touched = set(olds)
        else:
            values = providers.values_of(
                entry,
                label=wanted.provider.label,
                client_id=wanted.provider.client_id,
                client_secret=wanted.provider.client_secret,
                auto_create=wanted.provider.auto_create,
            )
            if not protocol.same_issuer(entry.issuer, wanted.provider.issuer):
                providers.change_issuer(store, entry, wanted.provider.issuer)
                values = replace(values, issuer=wanted.provider.issuer, managed=wanted.provider.managed)
                done.issuer_changed = True
            if not had_provider:
                values = replace(values, enabled=True, trusts_second_factor=trusts_second_factor)
            entry = store.update_provider(entry.id, values)
            done.values_taken = True
    else:
        done.anchor = _kept(store, legacy, anchor)
    if entry is not None and _open(done.anchor) and protocol.same_issuer(entry.issuer, done.anchor):
        _take_subjects(store, entry, {account_id: olds.get(account_id, "") for account_id in touched}, done)
    if keep_anchor is not None:
        keep_anchor(done.anchor)
    if done.wrote:
        store.commit()
        protocol.clear_caches()
    _log().warning(
        "OIDC: took over what the older version changed: removed %s, created %s, issuer changed %s, values %s, "
        "%d linked, %d unlinked, %d left (subject held elsewhere)",
        done.removed,
        done.created,
        done.issuer_changed,
        done.values_taken,
        len(done.linked),
        len(done.unlinked),
        len(done.refused),
    )
    return done


# ---------------------------------------------------------------------------
# The way back: what the old settings show (since 1.0.10)
# ---------------------------------------------------------------------------

#: The old settings without a provider: what the older version finds when the way back is closed.
_EMPTY = Legacy(issuer="", client_id="", client_secret="")


def _open(anchor: str | None) -> str:
    """The issuer of an open anchor as the older version wrote it (without spaces around, a slash at the end kept),
    or "" when it is closed or unknown."""
    text = (anchor or "").strip()
    issuer = protocol.normalize_issuer(text)
    return "" if not issuer or issuer == CLOSED else text


def anchor_of(legacy: Legacy | None) -> str:
    """The anchor at the migration (``apply``, ``apply_coupled`` with ``own``): the issuer of the old settings, or
    ``CLOSED`` when they hold no provider (no issuer or no client id; then a provider the older version sets up later
    comes in through ``resync``, which opens the anchor). Stored by the app before the migration commits."""
    if legacy is None or not _has_provider(legacy):
        return CLOSED
    return _open(legacy.issuer) or CLOSED


def _kept(store: Store, legacy: Legacy, anchor: str | None) -> str:
    """The anchor when ``resync`` takes no provider over: the stored one, written as the old settings write it now
    when they name the same issuer (the older version may have written it again with a slash, its button does);
    without one (a database migrated before 1.0.10) the old settings' issuer while it is the entry's, else
    ``CLOSED``."""
    written = _open(legacy.issuer)
    if anchor:
        kept = _open(anchor)
        if not kept:
            return CLOSED
        return written if written and protocol.same_issuer(written, kept) else kept
    entry = store.provider_by_slug(LEGACY_SLUG)
    if entry is None or entry.managed == MANAGED_NEXSUITE or not written:
        return CLOSED
    return written if protocol.same_issuer(entry.issuer, written) else CLOSED


@dataclass(frozen=True)
class Mirror:
    """What the app writes into the old settings and the old column: ``legacy`` as the settings (in the app's own
    form, as it wrote them before the module; ``set_up_by_button`` for an app that marks the button's settings), each
    account's subject from ``subjects`` and "" for every other account, and ``anchor`` as its stored anchor."""

    legacy: Legacy
    subjects: dict[int, str]
    anchor: str


def way_back(entry: Provider | None, links: Iterable[tuple[int, str]], anchor: str | None) -> Mirror:
    """The way back (Bauplan 01 "Umstieg" 4), one rule for every app. Pure: the app calls it inside every commit,
    after the change, writes what comes back, then stores the fingerprint of what it reads back.

    ``entry`` is the entry ``oidc`` as the store gives it (secret decrypted), or None; ``links`` its links as
    (account, subject); ``anchor`` the stored anchor (None or "": none, the way back is closed).

    1. The entry on, the provider trusted with the second factor, and the same issuer as the anchor: the entry in
       full (client id, secret, name, ``auto_create``; the issuer as the anchor writes it, since 1.0.11), the
       subjects are its links.
    2. The entry off or not trusted, the same issuer: issuer and name stay, client id and secret empty,
       ``auto_create`` off, the subjects are its links. The older version lets nobody in without a client; if it sets
       another issuer up, its own comparison drops the old subjects, and with a new client for the same issuer they
       hold, rightly. On again brings everything back.
    3. Another issuer than the anchor (changed in the new version) or no entry ``oidc``: everything empty, the
       subjects too, and the anchor ``CLOSED`` for good, through off and on, and when the issuer is set back. The
       older version finds no provider, so its bridge over a confirmed address and its ``auto_create`` never act.
    4. Only ``resync`` opens it again (see there).

    While coupled (the entry ``oidc`` is nexsuite's): everything empty and the anchor as it was; a Verbund app keeps
    its own rule for that time and does not call this then."""
    if entry is not None and entry.managed == MANAGED_NEXSUITE:
        return Mirror(legacy=_EMPTY, subjects={}, anchor=_open(anchor) or CLOSED)
    known = _open(anchor)
    if entry is None or not known or not protocol.same_issuer(entry.issuer, known):
        return Mirror(legacy=_EMPTY, subjects={}, anchor=CLOSED)
    button = entry.managed == MANAGED_AUTHENTIK
    # The issuer as the older version knows it, not the entry's form: most older versions compare their setting
    # letter by letter when a provider is saved (nexcanvas, nextasks, nexbrand, nextrmnl, nexsift, nexcrate), and
    # their authentik button writes it with a slash; written without, the button dropped every subject there.
    if entry.enabled and entry.trusts_second_factor:
        legacy = Legacy(
            issuer=known,
            client_id=entry.client_id,
            client_secret=entry.client_secret or "",
            label=entry.label,
            auto_create=entry.auto_create,
            set_up_by_button=button,
        )
    else:
        legacy = Legacy(issuer=known, client_id="", client_secret="", label=entry.label, set_up_by_button=button)
    return Mirror(legacy=legacy, subjects=_subjects_of(links), anchor=known)
