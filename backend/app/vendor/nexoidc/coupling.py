"""Coupling to nexsuite (Bauplan 06, "Apps im Verbund mit nexsuite"): nexcanvas, nextasks, nexbrand, nexlore.

While an app is coupled, nexsuite is its provider: one entry with ``managed = "nexsuite"`` and the slug ``oidc``,
whose callback is ``<api>/oidc/callback`` (nexsuite compares it exactly and never changes it). The app's own entries
are set aside: switched off and, the migrated entry ``oidc``, parked under another slug, because nexsuite needs that
one. Uncoupling removes the nexsuite entry with its links and puts every own entry back as it was.

Why this is simpler than the single-provider apps had it: a link belongs to its provider (``provider_id``). The own
links of the accounts stay where they are, with their switched-off entry; a subject "3" of authentik never passes for
person 3 of nexsuite, because they are rows of different providers. There is no ``oidc_subject_local`` to keep.

Which account is which person of nexsuite is the app's business (it matches them when coupling); the module takes the
pairs. While coupled the list changes through the coupling only (``providers`` refuses the form).

``Coupling`` is what the app keeps until it uncouples (as JSON in its settings, ``as_dict``/``from_dict``).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from . import config, flow, protocol, providers
from .errors import ProviderInvalid
from .model import (
    DEFAULT_SCOPES,
    LEGACY_SLUG,
    MANAGED_NEXSUITE,
    Link,
    ProviderValues,
    Store,
)

#: Where the own entry ``oidc`` waits while nexsuite holds the slug.
PARKED_SLUG = "oidc-own"


def _log() -> logging.Logger:
    return logging.getLogger(config.current().log_name)


@dataclass
class Coupling:
    """The nexsuite entry, and how each own entry looked before it was set aside."""

    provider_id: int
    set_aside: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"provider_id": self.provider_id, "set_aside": [dict(item) for item in self.set_aside]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Coupling:
        return cls(provider_id=int(data["provider_id"]), set_aside=[dict(item) for item in data.get("set_aside", [])])


def _set_aside(store: Store) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for entry in store.list_providers():
        if entry.managed == MANAGED_NEXSUITE:
            raise ProviderInvalid("id", "provider_managed", "The app is coupled already.")
        kept.append(
            {"id": entry.id, "slug": entry.slug, "enabled": entry.enabled, "redirect_path": entry.redirect_path}
        )
        if entry.slug == LEGACY_SLUG:
            # Parked under another slug, the entry keeps the callback its provider knows (``<api>/oidc/callback``):
            # the button and the blueprint name that one while coupled, and it holds again after uncoupling.
            path = flow.callback_path(entry.slug, entry.redirect_path)
            parked = providers.values_of(
                entry, slug=providers.free_slug(store, PARKED_SLUG), enabled=False, redirect_path=path
            )
        else:
            parked = providers.values_of(entry, enabled=False)
        store.update_provider(entry.id, parked)
    return kept


def _nexsuite_entry(
    store: Store, *, issuer: str, client_id: str, client_secret: str, label: str, trusts_second_factor: bool
) -> int:
    created = store.insert_provider(
        ProviderValues(
            slug=LEGACY_SLUG,
            label=" ".join(label.split()) or "nexsuite",
            issuer=protocol.normalize_issuer(issuer),
            client_id=client_id.strip(),
            client_secret=client_secret,
            scopes=DEFAULT_SCOPES,
            enabled=True,
            auto_create=False,
            trusts_second_factor=trusts_second_factor,
            managed=MANAGED_NEXSUITE,
            position=-1,
        )
    )
    return created.id


def couple(
    store: Store,
    *,
    issuer: str,
    client_id: str,
    client_secret: str,
    label: str,
    people: Iterable[tuple[int, str]],
    trusts_second_factor: bool = True,
) -> Coupling:
    """Set the own entries aside, enter nexsuite as the provider with slug ``oidc``, link each account to its person
    (``people``: account id and the person's subject at nexsuite). One transaction; the app keeps the result."""
    kept = _set_aside(store)
    provider_id = _nexsuite_entry(
        store,
        issuer=issuer,
        client_id=client_id,
        client_secret=client_secret,
        label=label,
        trusts_second_factor=trusts_second_factor,
    )
    count = _link_people(store, provider_id, protocol.normalize_issuer(issuer), people)
    store.commit()
    protocol.clear_caches()
    _log().warning("OIDC: coupled to nexsuite, %d own entries set aside, %d accounts linked", len(kept), count)
    return Coupling(provider_id=provider_id, set_aside=kept)


def _link_people(store: Store, provider_id: int, issuer: str, people: Iterable[tuple[int, str]]) -> int:
    seen_accounts: set[int] = set()
    seen_subjects: set[str] = set()
    for account_id, subject in people:
        # One identity per account and provider (Bauplan 01): a second pair for an account, or a subject twice,
        # is left out.
        if not subject or not subject.strip() or subject in seen_subjects or account_id in seen_accounts:
            continue
        seen_accounts.add(account_id)
        seen_subjects.add(subject)
        store.add_link(Link(provider_id=provider_id, subject=subject, account_id=account_id, issuer=issuer))
    return len(seen_accounts)


def uncouple(store: Store, coupling: Coupling) -> int:
    """Remove the nexsuite entry with its links and put the own entries back as they were; the number of links that
    went with nexsuite."""
    dropped = 0
    current = store.get_provider(coupling.provider_id)
    if current is not None and current.managed == MANAGED_NEXSUITE:
        dropped = len(store.links_of_provider(current.id))
        store.delete_provider(current.id)
    for item in coupling.set_aside:
        entry = store.get_provider(int(item["id"]))
        if entry is None:
            continue
        back = providers.values_of(
            entry,
            slug=str(item["slug"]),
            enabled=bool(item["enabled"]),
            redirect_path=str(item.get("redirect_path", entry.redirect_path)),
        )
        store.update_provider(entry.id, back)
    store.commit()
    protocol.clear_caches()
    _log().warning(
        "OIDC: uncoupled from nexsuite, %d links went with it, %d own entries back", dropped, len(coupling.set_aside)
    )
    return dropped


__all__ = ["PARKED_SLUG", "Coupling", "couple", "uncouple"]
