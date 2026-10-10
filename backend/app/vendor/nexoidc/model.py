"""The data the module works with, and the ``Store`` the app implements over its own database.

The tables are the app's (Bauplan 01): ``oidc_providers`` and ``oidc_links`` with exactly the columns named there, in
the app's own models and migrations. The module never sees a database; it calls the ``Store`` methods below, and
the app answers them with SQLAlchemy, sqlite3 or whatever it uses. All methods are synchronous: every app runs its
database synchronously.

A ``Store`` works inside one transaction of the app. The module calls ``commit()`` once an outcome is settled and
``rollback()`` when it refuses after having written (a consumed invitation comes back that way). The app opens the
store per request and closes it afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

DEFAULT_SCOPES = "openid profile email"
#: The slug of the entry that came from the settings of a single-provider app, and of the nexsuite coupling: its
#: callback is the old address ``<api>/oidc/callback`` (Bauplan 01 "Umstieg", 06 "Verbund").
LEGACY_SLUG = "oidc"
#: ``managed`` values. Only the authentik button touches an entry with ``MANAGED_AUTHENTIK``; an entry with
#: ``MANAGED_NEXSUITE`` changes only through the coupling, never through the form.
MANAGED_HAND = ""
MANAGED_AUTHENTIK = "authentik"
MANAGED_NEXSUITE = "nexsuite"


@dataclass(frozen=True)
class Provider:
    """One row of ``oidc_providers``. ``client_secret`` is the decrypted secret ("" for a public client): the store
    decrypts it with the app's secret key under the context ``secret_context(id)`` and never hands it to a browser."""

    id: int
    slug: str
    label: str
    issuer: str
    client_id: str
    client_secret: str = ""
    scopes: str = DEFAULT_SCOPES
    enabled: bool = True
    auto_create: bool = False
    trusts_second_factor: bool = True
    managed: str = MANAGED_HAND
    position: int = 0
    #: The callback path the provider knows, relative to the app root; "" for the standard one
    #: (``<api>/oidc/<slug>/callback``, for the entry ``oidc`` ``<api>/oidc/callback``). Set only by a migration
    #: (an address a provider knew before the module) or a coupling, never by the form.
    redirect_path: str = ""
    created_at: datetime | None = None
    #: The redirect address the authentik button last registered at authentik for this entry, "" when it never did
    #: (an entry by hand, or one the button made before 1.0.10). Column ``registered_redirect`` (Bauplan 01, since
    #: 1.0.10, ``server_default ''``). Compared with today's redirect address it tells whether authentik still sends
    #: people to an old one (``providers.admin_view``: ``redirect_stale``).
    registered_redirect: str = ""


@dataclass(frozen=True)
class ProviderValues:
    """What the module writes into a row. ``client_secret`` None keeps the stored one (the form never shows it, so an
    untouched field must not delete it); "" stores none (a public client)."""

    slug: str
    label: str
    issuer: str
    client_id: str
    client_secret: str | None
    scopes: str
    enabled: bool
    auto_create: bool
    trusts_second_factor: bool
    managed: str
    position: int
    redirect_path: str = ""
    #: None keeps the stored value (every write but the button's), a string stores it; a new row without one gets "".
    registered_redirect: str | None = None


@dataclass(frozen=True)
class Link:
    """One row of ``oidc_links``: one identity at one provider, bound to one account. ``issuer`` is the ``iss`` of the
    token that made the link (with Entra ``common`` the real tenant); ``email`` is for display only, never for
    finding anybody."""

    provider_id: int
    subject: str
    account_id: int
    issuer: str
    email: str | None = None
    created_at: datetime | None = None
    last_used_at: datetime | None = None


@dataclass(frozen=True)
class Identity:
    """What is certain after a successful run at the provider. ``issuer`` plus ``subject`` is the identity; the rest
    may change at the provider any time. There is no ``email_verified``: the module never reads it (Bauplan 02)."""

    issuer: str
    subject: str
    email: str | None = None
    preferred_username: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class Invite:
    """An open invitation as the app knows it. ``key`` is what travels in the attempt cookie; ``rights`` is the app's
    own description of what the invitation grants (role, space, team), the module passes it through untouched."""

    key: str
    id: int | str = ""
    rights: object = None


@dataclass(frozen=True)
class AccountState:
    """What the module asks about an account: may it sign in, does it have a password, does it have a second
    factor of its own in the app."""

    id: int
    name: str
    blocked: bool = False
    has_password: bool = True
    has_second_factor: bool = False


@dataclass
class Impact:
    """For the confirmations of the provider list: how many accounts lose their link, and how many of them sign in
    through this provider only (no password, no other link)."""

    count: int = 0
    only: int = 0
    only_names: list[str] = field(default_factory=list)


class Store(Protocol):
    """Implemented by the app over its own tables. Methods marked "single account: unused" may raise
    ``NotImplementedError`` in nexcrate and nexsift."""

    # --- Providers -----------------------------------------------------------------------------------------------
    def list_providers(self) -> list[Provider]:
        """All entries, ordered by ``position``, then ``id``."""
        ...

    def get_provider(self, provider_id: int) -> Provider | None: ...

    def provider_by_slug(self, slug: str) -> Provider | None:
        """The slug compared exactly (slugs are stored lower-case)."""
        ...

    def insert_provider(self, values: ProviderValues) -> Provider:
        """A new row; ``created_at`` now. The secret is encrypted under ``secret_context(new id)``.
        ``values.registered_redirect`` None stores ""."""
        ...

    def update_provider(self, provider_id: int, values: ProviderValues) -> Provider:
        """Overwrite the row. ``values.client_secret`` None keeps the stored secret, ``values.registered_redirect``
        None the stored redirect address."""
        ...

    def delete_provider(self, provider_id: int) -> None:
        """Delete the row; its links go with it (``ON DELETE CASCADE``)."""
        ...

    # --- Links ---------------------------------------------------------------------------------------------------
    def find_link(self, provider_id: int, subject: str) -> Link | None: ...

    def links_of_provider(self, provider_id: int) -> list[Link]: ...

    def links_of_account(self, account_id: int) -> list[Link]: ...

    def add_link(self, link: Link) -> None:
        """Insert. ``(provider_id, subject)`` and ``(provider_id, account_id)`` are unique in the table."""
        ...

    def remove_link(self, provider_id: int, account_id: int) -> bool: ...

    def drop_links(self, provider_id: int) -> int:
        """Delete every link of the provider; the number deleted."""
        ...

    def touch_link(self, provider_id: int, subject: str, email: str | None) -> None:
        """``last_used_at`` now and the display address as the provider sends it today."""
        ...

    # --- Accounts ------------------------------------------------------------------------------------------------
    def account_state(self, account_id: int) -> AccountState | None: ...

    def clean_name(self, raw: str) -> str:
        """The app's naming rules applied to a suggested name; "" when nothing usable is left."""
        ...

    def name_taken(self, name: str) -> bool: ...

    def create_account(self, name: str, *, invite: Invite | None, email: str | None) -> int:
        """A new account that signs in through a provider only (no password). With ``invite`` it gets the rights
        of the invitation, without one it is a plain member. ``email`` is the provider's address; whether the account
        takes it as its own is the app's rule. Single account: unused."""
        ...

    # --- Invitations (single account: unused) ---------------------------------------------------------------------
    def find_invite(self, key: str) -> Invite | None:
        """An invitation that is open: not used, not expired, its inviter still allowed to invite."""
        ...

    def consume_invite(self, invite: Invite) -> bool:
        """Use the invitation up with one statement that must hit exactly one row; False when somebody else was
        faster (two people returning at the same moment: only one gets in)."""
        ...

    def accept_invite(self, account_id: int, invite: Invite) -> None:
        """Give an existing account the rights of the invitation in addition to its own (Bauplan 01, "Wer ist das?"
        1: a known identity that came through an invitation). Adds, never takes away: an account with more rights
        keeps them. Called after ``consume_invite`` succeeded, in the same transaction; the module commits."""
        ...

    # --- Transaction ---------------------------------------------------------------------------------------------
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


def secret_context(provider_id: int) -> str:
    """The encryption context of a provider's client secret (Bauplan 01): another provider's ciphertext does not
    decrypt under this one."""
    return f"oidc-provider:{provider_id}"
