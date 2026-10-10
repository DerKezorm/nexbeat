"""The list of providers (Bauplan 01 "Tabellen", "Anbieter ändern oder entfernen"; 04 "Karte 2").

Saving checks the issuer with a fresh discovery first and stores nothing when it fails (``oidc_issuer_mismatch`` and
the other discovery codes at the issuer field). An issuer that really changes drops the links of that entry: a subject
is only meaningful together with its issuer, and user "3" at a new provider must not inherit what user "3" at the old
one owned. "Really" is ``same_issuer``: the same issuer written with or without a slash at the end drops nothing.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, replace

from . import config, protocol
from .errors import OidcError, ProviderInvalid
from .model import (
    DEFAULT_SCOPES,
    LEGACY_SLUG,
    MANAGED_AUTHENTIK,
    MANAGED_HAND,
    MANAGED_NEXSUITE,
    Impact,
    Provider,
    ProviderValues,
    Store,
)

#: A slug: part of the callback address, fixed once created.
SLUG_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?")
SLUG_MAX = 40
LABEL_MAX = 64
ISSUER_MAX = 500
CLIENT_ID_MAX = 255
SECRET_MAX = 2000
SCOPES_MAX = 500
#: Slugs an entry from the form may not take: the routes ``<api>/oidc/authentik/...`` and the old callback.
#: ``authentik`` is free: the blueprint names ``<api>/oidc/authentik/callback``, and the button's routes
#: (``<api>/oidc/authentik/setup``, ``/blueprint``) never meet ``<api>/oidc/<slug>/start|callback|link``.
RESERVED_SLUGS = frozenset({"callback", "admin", "providers", "me", LEGACY_SLUG})
#: A callback path of its own (``redirect_path``): absolute within the app, plain characters, no query.
REDIRECT_PATH = re.compile(r"/(?!/)[A-Za-z0-9._~/-]{1,300}")
_SPELLED_OUT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"})


def _log() -> logging.Logger:
    return logging.getLogger(config.current().log_name)


def slug_from_label(label: str) -> str:
    """The slug the form suggests for a name: lower case, German letters written out, other accents dropped,
    everything else a dash, at most 40 characters. ``frontend/oidc.ts`` does the same in the browser."""
    ascii_text = unicodedata.normalize("NFKD", label.translate(_SPELLED_OUT)).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:SLUG_MAX].rstrip("-")


def free_slug(store: Store, wanted: str) -> str:
    """``wanted`` or, when an entry has it already, ``wanted-2``, ``wanted-3`` …"""
    base = wanted[:SLUG_MAX].rstrip("-") or "provider"
    if store.provider_by_slug(base) is None:
        return base
    number = 2
    while True:
        suffix = f"-{number}"
        candidate = base[: SLUG_MAX - len(suffix)].rstrip("-") + suffix
        if store.provider_by_slug(candidate) is None:
            return candidate
        number += 1


@dataclass(frozen=True)
class Form:
    """What the provider form sends. ``slug`` counts only when creating; ``client_secret`` "" keeps the stored one
    when editing (a public client is made by creating without one)."""

    label: str
    issuer: str
    client_id: str
    client_secret: str = ""
    slug: str = ""
    scopes: str = DEFAULT_SCOPES
    enabled: bool = True
    auto_create: bool = False
    trusts_second_factor: bool = True


def _checked(form: Form) -> Form:
    label = " ".join(form.label.split())
    if not label or len(label) > LABEL_MAX:
        raise ProviderInvalid("label", "label_required", "The name on the button is missing or too long.")
    issuer = protocol.normalize_issuer(form.issuer)
    if (
        not issuer.lower().startswith(("https://", "http://"))
        or len(issuer) > ISSUER_MAX
        or any(c.isspace() for c in issuer)
    ):
        raise ProviderInvalid("issuer", "issuer_invalid", "The issuer must be an http:// or https:// address.")
    client_id = form.client_id.strip()
    if not client_id or len(client_id) > CLIENT_ID_MAX:
        raise ProviderInvalid("client_id", "client_id_required", "The client id is missing or too long.")
    scopes = " ".join(form.scopes.split()) or DEFAULT_SCOPES
    if "openid" not in scopes.split() or len(scopes) > SCOPES_MAX:
        raise ProviderInvalid("scopes", "scopes_invalid", "The scopes must contain openid.")
    if len(form.client_secret) > SECRET_MAX:
        raise ProviderInvalid("client_secret", "client_secret_invalid", "The client secret is too long.")
    return replace(
        form, label=label, issuer=issuer, client_id=client_id, scopes=scopes, client_secret=form.client_secret.strip()
    )


async def _discover(issuer: str) -> None:
    try:
        await protocol.discovery(issuer, fresh=True)
    except OidcError as error:
        raise ProviderInvalid("issuer", error.code, error.message) from error


def issuer_change_impact(store: Store, provider_id: int, issuer: str) -> int:
    """How many accounts must link again when the entry gets this issuer: 0 for the same issuer, however written."""
    current = store.get_provider(provider_id)
    if current is None or protocol.same_issuer(current.issuer, issuer):
        return 0
    return len({link.account_id for link in store.links_of_provider(provider_id)})


def removal_impact(store: Store, provider_id: int) -> Impact:
    """For the confirmation before removing: the accounts that lose their link, and those of them that sign in through
    this provider only (no password and no other link)."""
    impact = Impact()
    for entry in store.links_of_provider(provider_id):
        impact.count += 1
        state = store.account_state(entry.account_id)
        if state is None or state.has_password:
            continue
        if all(other.provider_id == provider_id for other in store.links_of_account(entry.account_id)):
            impact.only += 1
            impact.only_names.append(state.name)
    return impact


def change_issuer(store: Store, provider: Provider, issuer: str) -> int:
    """The links of an entry go when its issuer really changes; the number dropped, logged with the count."""
    if protocol.same_issuer(provider.issuer, issuer):
        return 0
    dropped = store.drop_links(provider.id)
    _log().warning(
        "OIDC issuer of provider %s changed from %r to %r, %d links dropped",
        provider.slug,
        provider.issuer,
        issuer,
        dropped,
    )
    return dropped


def coupled(store: Store) -> bool:
    """Whether the app is coupled to nexsuite: then nexsuite is its provider, and the list changes only through the
    coupling (Bauplan 06)."""
    return any(entry.managed == MANAGED_NEXSUITE for entry in store.list_providers())


def _not_coupled(store: Store) -> None:
    if coupled(store):
        raise ProviderInvalid(
            "id", "provider_managed", "While coupled, the providers change through the coupling only."
        )


def check_redirect_path(path: str) -> str:
    """A callback path a provider knew before the module, for a migration: kept as it is, refused when it is no
    plain path of this app."""
    if path and not REDIRECT_PATH.fullmatch(path):
        raise ValueError(f"{path!r} is no callback path of this app")
    return path


async def create(store: Store, form: Form) -> Provider:
    """A new entry from the form, after a fresh discovery. Defaults of Bauplan 01: on, no new accounts, the provider
    checks the second factor."""
    _not_coupled(store)
    form = _checked(form)
    slug = (form.slug or slug_from_label(form.label)).strip()
    if not SLUG_PATTERN.fullmatch(slug):
        raise ProviderInvalid("slug", "slug_invalid", "The short name takes a to z, digits and dashes, up to 40.")
    if slug in RESERVED_SLUGS or store.provider_by_slug(slug) is not None:
        raise ProviderInvalid("slug", "slug_taken", "Another entry has this short name already.")
    await _discover(form.issuer)
    position = max((entry.position for entry in store.list_providers()), default=-1) + 1
    created = store.insert_provider(
        ProviderValues(
            slug=slug,
            label=form.label,
            issuer=form.issuer,
            client_id=form.client_id,
            client_secret=form.client_secret,
            scopes=form.scopes,
            enabled=form.enabled,
            auto_create=form.auto_create and not config.current().single_account,
            trusts_second_factor=form.trusts_second_factor,
            managed=MANAGED_HAND,
            position=position,
        )
    )
    store.commit()
    _log().info("OIDC provider %s added (issuer %s)", created.slug, created.issuer)
    return created


async def update(store: Store, provider_id: int, form: Form) -> tuple[Provider, int]:
    """Save the form over an entry: (the entry, the number of links dropped). The slug stays. An entry of the nexsuite
    coupling is read-only here."""
    current = store.get_provider(provider_id)
    if current is None:
        raise ProviderInvalid("id", "provider_unknown", "No such provider.")
    if current.managed == MANAGED_NEXSUITE:
        raise ProviderInvalid("id", "provider_managed", "This provider changes through the coupling only.")
    _not_coupled(store)
    form = _checked(form)
    await _discover(form.issuer)
    dropped = change_issuer(store, current, form.issuer)
    saved = store.update_provider(
        provider_id,
        ProviderValues(
            slug=current.slug,
            label=form.label,
            issuer=form.issuer,
            client_id=form.client_id,
            client_secret=form.client_secret or None,
            scopes=form.scopes,
            enabled=form.enabled,
            auto_create=form.auto_create and not config.current().single_account,
            trusts_second_factor=form.trusts_second_factor,
            managed=current.managed,
            position=current.position,
            redirect_path=current.redirect_path,
        ),
    )
    store.commit()
    protocol.clear_caches()
    _log().info("OIDC provider %s saved (issuer %s)", saved.slug, saved.issuer)
    return saved, dropped


def remove(store: Store, provider_id: int) -> Impact:
    """Remove an entry with its links (the app asked first, naming ``removal_impact``)."""
    current = store.get_provider(provider_id)
    if current is None:
        raise ProviderInvalid("id", "provider_unknown", "No such provider.")
    if current.managed == MANAGED_NEXSUITE:
        raise ProviderInvalid("id", "provider_managed", "This provider changes through the coupling only.")
    _not_coupled(store)
    impact = removal_impact(store, provider_id)
    store.delete_provider(provider_id)
    store.commit()
    _log().warning("OIDC provider %s removed, %d links dropped", current.slug, impact.count)
    return impact


def reorder(store: Store, ids: list[int]) -> list[Provider]:
    """Put the entries in the order of ``ids`` (the drag handle). Unknown ids are ignored, missing ones go last."""
    _not_coupled(store)
    entries = {entry.id: entry for entry in store.list_providers()}
    order = [entry_id for entry_id in dict.fromkeys(ids) if entry_id in entries]
    order += [entry_id for entry_id in entries if entry_id not in order]
    for position, entry_id in enumerate(order):
        entry = entries[entry_id]
        if entry.position != position:
            store.update_provider(entry_id, values_of(entry, position=position))
    store.commit()
    return store.list_providers()


def values_of(provider: Provider, **changes: object) -> ProviderValues:
    values = ProviderValues(
        slug=provider.slug,
        label=provider.label,
        issuer=provider.issuer,
        client_id=provider.client_id,
        client_secret=None,
        scopes=provider.scopes,
        enabled=provider.enabled,
        auto_create=provider.auto_create,
        trusts_second_factor=provider.trusts_second_factor,
        managed=provider.managed,
        position=provider.position,
        redirect_path=provider.redirect_path,
    )
    return replace(values, **changes)  # type: ignore[arg-type]


def public_list(store: Store) -> list[dict[str, str]]:
    """What the sign-in and invitation pages may know: the active entries' slug and label, in order. Nothing else
    leaves the server without a session."""
    return [{"slug": entry.slug, "label": entry.label} for entry in store.list_providers() if entry.enabled]


def admin_view(provider: Provider, request_base: str, link_count: int, *, coupled: bool = False) -> dict[str, object]:
    """An entry as the operator's list and form show it: never the secret, only whether one is stored.

    ``registered_redirect_uri`` is what the authentik button registered at authentik for this entry ("" for none),
    ``redirect_stale`` whether that is no longer the redirect address the sign-in sends (the public address changed
    since): the authentik card then shows ``oidc.authentik.stale`` until the button ran again (since 1.0.10)."""
    from .flow import provider_redirect_uri

    redirect = provider_redirect_uri(provider, request_base)
    return {
        "id": provider.id,
        "slug": provider.slug,
        "label": provider.label,
        "issuer": provider.issuer,
        "client_id": provider.client_id,
        "has_secret": bool(provider.client_secret),
        "scopes": provider.scopes,
        "enabled": provider.enabled,
        "auto_create": provider.auto_create,
        "trusts_second_factor": provider.trusts_second_factor,
        "managed": provider.managed,
        "position": provider.position,
        "redirect_uri": redirect,
        "registered_redirect_uri": provider.registered_redirect,
        "redirect_stale": bool(provider.registered_redirect) and provider.registered_redirect != redirect,
        "links": link_count,
        # Bauplan 06: while coupled, the whole list is read-only (the set-aside entries show as "off"); the entry of
        # the coupling never changes through the form.
        "editable": not coupled and provider.managed != MANAGED_NEXSUITE,
    }


__all__ = [
    "MANAGED_AUTHENTIK",
    "Form",
    "admin_view",
    "change_issuer",
    "create",
    "free_slug",
    "issuer_change_impact",
    "public_list",
    "removal_impact",
    "remove",
    "reorder",
    "slug_from_label",
    "update",
]
