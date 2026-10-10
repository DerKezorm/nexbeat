"""Who the identity is (Bauplan 01, "Wer ist das?"), linking and unlinking, and the second factor.

The order on a return, and nothing else:

1. the link ``(provider_id, subject)``: found, signed in, whatever name and address the provider sends today; a
   valid invitation in the attempt is accepted with that account (its rights added, the invitation used up by the
   same one-row statement as below). One that ran out or was used meanwhile changes nothing: the link comes first,
   so the person is signed in all the same, and ``SignedIn.invitation`` says ``invalid`` for a hint;
2. the invitation in the attempt: a new account with the rights of the invitation, which is used up by one statement
   that must hit exactly one row (two people returning at once: only one gets in);
3. ``auto_create`` of the provider: a new account as a member;
4. otherwise refused with ``oidc_no_account``.

Never by the address, not even with ``email_verified: true``: authentik sends ``false`` by default, Entra sends none,
and in authentik everybody changes their own address. The address from the provider is kept at the link for display.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from . import config, protocol
from .attempt import INVITE, LINK
from .errors import OidcError
from .flow import Arrival
from .model import AccountState, Identity, Link, Store

#: ``SignedIn.invitation``: what became of an invitation that came along with a known link.
INVITATION_ACCEPTED = "accepted"
INVITATION_INVALID = "invalid"
#: How far numbering goes when a name is taken (``max-2``, ``max-3`` …) before the module gives up.
NAME_TRIES = 1000
FALLBACK_NAME = "user"


def _log() -> logging.Logger:
    return logging.getLogger(config.current().log_name)


@dataclass(frozen=True)
class SignedIn:
    """The account the identity signs in as. ``second_factor_due``: the app asks for the code of its own second
    factor before the session counts (provider does not check it, and the account has one). ``invitation``: for a
    known link that came with an invitation, ``accepted`` (rights added, invitation used) or ``invalid`` (ran out or
    used meanwhile; signed in all the same, the app may say so); empty otherwise."""

    account_id: int
    name: str
    created: bool
    second_factor_due: bool
    invitation: str = ""


def name_for(identity: Identity, clean: Callable[[str], str], taken: Callable[[str], bool]) -> str:
    """The name of a new account: ``preferred_username`` (the part before the @ of an address or UPN), else ``name``,
    else the part of the address before the @, else ``user``; cleaned by the app's rules and numbered on a collision
    (``max-2``)."""
    claims = {"preferred_username": identity.preferred_username or "", "name": identity.name or ""}
    raw = protocol.username_from(claims)
    if not raw and identity.email:
        raw = identity.email.split("@", 1)[0].strip()
    base = clean(raw) if raw else ""
    if not base:
        base = clean(FALLBACK_NAME) or FALLBACK_NAME
    if not taken(base):
        return base
    for number in range(2, NAME_TRIES):
        candidate = clean(f"{base}-{number}")
        if candidate and not taken(candidate):
            return candidate
    raise RuntimeError(f"no free account name from {base!r}")


def second_factor_due(trusts_second_factor: bool, state: AccountState) -> bool:
    """Bauplan 01, "Zweiter Faktor": the code is asked after the provider only when the provider is not trusted to
    check one itself and the account has one in the app."""
    return not trusts_second_factor and state.has_second_factor


def _state(store: Store, account_id: int) -> AccountState:
    state = store.account_state(account_id)
    if state is None:
        # A link without an account cannot exist (``ON DELETE CASCADE``); a store that loses one is broken.
        raise OidcError("oidc_no_account", f"account {account_id} of a link is gone")
    if state.blocked:
        raise OidcError("account_blocked", f"the account is blocked name={state.name}")
    return state


def sign_in(store: Store, arrival: Arrival) -> SignedIn:
    """The account for a return whose purpose is signing in or an invitation. Commits what it wrote; on a refusal
    after a write it rolls back (a consumed invitation comes back) and raises ``OidcError``."""
    cfg = config.current()
    provider, identity, started = arrival.provider, arrival.identity, arrival.started
    if started.purpose == LINK:
        raise OidcError("oidc_link_mismatch", "a linking attempt cannot sign anybody in")
    link = store.find_link(provider.id, identity.subject)
    if link is not None:
        state = _state(store, link.account_id)
        invitation = ""
        if started.purpose == INVITE and started.invite and not cfg.single_account:
            invitation = _accept(store, state, started.invite)
        try:
            store.touch_link(provider.id, identity.subject, identity.email)
        except Exception:
            store.rollback()
            raise
        store.commit()
        _log().info("Signed in via OIDC name=%s provider=%s", state.name, provider.slug)
        if invitation == INVITATION_ACCEPTED:
            _log().info("Invitation accepted via OIDC name=%s provider=%s", state.name, provider.slug)
        return SignedIn(
            state.id, state.name, False, second_factor_due(provider.trusts_second_factor, state), invitation
        )
    invite = None
    if started.purpose == INVITE and started.invite and not cfg.single_account:
        invite = store.find_invite(started.invite)
        if invite is None or not store.consume_invite(invite):
            store.rollback()
            raise OidcError("invite_invalid", "the invitation ran out or was used meanwhile")
    elif cfg.single_account or not provider.auto_create:
        raise OidcError(
            "oidc_no_account",
            f"no account for this identity at provider {provider.slug} (address {protocol.masked(identity.email)})",
        )
    try:
        name = name_for(identity, store.clean_name, store.name_taken)
        account_id = store.create_account(name, invite=invite, email=identity.email)
        store.add_link(
            Link(
                provider_id=provider.id,
                subject=identity.subject,
                account_id=account_id,
                issuer=identity.issuer,
                email=identity.email,
            )
        )
    except Exception:
        store.rollback()
        raise
    store.commit()
    _log().info(
        "Account created via OIDC provider=%s (%s) name=%s",
        provider.slug,
        "invitation" if invite else "auto_create",
        name,
    )
    return SignedIn(account_id, name, True, False)


def _accept(store: Store, state: AccountState, key: str) -> str:
    """The invitation of the attempt for an account that is known already (Bauplan 01, "Wer ist das?" 1): used up with
    the one-row statement, then its rights added. Nothing committed here; a failure rolls the use back."""
    invite = store.find_invite(key)
    if invite is None or not store.consume_invite(invite):
        store.rollback()
        return INVITATION_INVALID
    try:
        store.accept_invite(state.id, invite)
    except Exception:
        store.rollback()
        raise
    return INVITATION_ACCEPTED


def link(store: Store, arrival: Arrival, signed_in_account_id: int | None) -> None:
    """Store the identity on the account that started the linking (Bauplan 01, "Verknüpfen und Lösen"). The person
    must still be signed in as that account; an identity that belongs to another account is refused."""
    provider, identity, started = arrival.provider, arrival.identity, arrival.started
    if started.purpose != LINK or started.link_account_id is None:
        raise OidcError("oidc_link_mismatch", "the attempt was not a linking")
    if signed_in_account_id is None or signed_in_account_id != started.link_account_id:
        raise OidcError("oidc_link_mismatch", "the linking attempt does not belong to the signed-in account")
    state = _state(store, started.link_account_id)
    existing = store.find_link(provider.id, identity.subject)
    if existing is not None and existing.account_id != state.id:
        raise OidcError("oidc_subject_taken", f"this identity at {provider.slug} belongs to another account already")
    if existing is None:
        # One identity per provider and account: a new one takes the place of the old.
        store.remove_link(provider.id, state.id)
        store.add_link(
            Link(
                provider_id=provider.id,
                subject=identity.subject,
                account_id=state.id,
                issuer=identity.issuer,
                email=identity.email,
            )
        )
    else:
        store.touch_link(provider.id, identity.subject, identity.email)
    store.commit()
    _log().info("OIDC link to provider %s made by its owner name=%s", provider.slug, state.name)


def unlink(store: Store, account_id: int, provider_id: int) -> bool:
    """Remove the account's link to a provider. The last link of an account without a password stays
    (``oidc_only_account``): it would lock the account out. False when there was no link."""
    state = store.account_state(account_id)
    if state is None:
        return False
    links = store.links_of_account(account_id)
    if not any(entry.provider_id == provider_id for entry in links):
        return False
    if not state.has_password and len(links) <= 1:
        raise OidcError("oidc_only_account", f"the account signs in through this provider only name={state.name}")
    removed = store.remove_link(provider_id, account_id)
    store.commit()
    entry = store.get_provider(provider_id)
    _log().info("OIDC link to provider %s removed name=%s", entry.slug if entry else provider_id, state.name)
    return removed


def signs_in_only_through(store: Store, account_id: int) -> list[int]:
    """The providers an account without a password depends on; empty when it has a password."""
    state = store.account_state(account_id)
    if state is None or state.has_password:
        return []
    return [entry.provider_id for entry in store.links_of_account(account_id)]
