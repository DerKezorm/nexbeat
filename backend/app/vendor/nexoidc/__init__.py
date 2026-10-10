"""nexoidc: sign-in with OpenID Connect and the authentik button, the same in every nex app.

This package is copied unchanged into ``backend/app/vendor/nexoidc/`` of each app by ``bauplaene/oidc/tools/sync.py``
and changed only in ``bauplaene/oidc``. A test in every app compares the files with the checksums in ``MANIFEST.json``.

What lives here (Bauplan "Anmeldung mit OIDC und authentik", parts 01 to 03 and 06):

- ``config``: what the app tells the module about itself (``configure(AppConfig(...))``);
- ``model``: providers, links, identities, and the ``Store`` the app implements over its database;
- ``protocol``: discovery, ``same_issuer``, Entra's placeholder, PKCE, exchange, token checks, userinfo;
- ``attempt``: the signed attempt cookie and the single use of a ``state``;
- ``flow``: start and return as plain redirects and cookies;
- ``accounts``: who the identity is, linking, unlinking, the second factor;
- ``providers``: the provider list, issuer changes, removal;
- ``migrate``: from one provider in the settings to the list; the way back (way_back, anchor), up again (resync);
- ``coupling``: nexsuite as the provider of a coupled app, the own entries set aside and back;
- ``authentik``: the button and the blueprint;
- ``tls``: one TLS context for every call, read once outside the event loop (``warm()`` at the app's start).

Only httpx and PyJWT (with cryptography) are needed; nothing from an app is imported.
"""

from __future__ import annotations

from .config import AppConfig, configure, current, use_transport
from .errors import CODES, FORM_CODES, OidcError, ProviderInvalid
from .model import (
    DEFAULT_SCOPES,
    LEGACY_SLUG,
    MANAGED_AUTHENTIK,
    MANAGED_HAND,
    MANAGED_NEXSUITE,
    AccountState,
    Identity,
    Impact,
    Invite,
    Link,
    Provider,
    ProviderValues,
    Store,
    secret_context,
)
from .tls import warm

__version__ = "1.0.11"

__all__ = [
    "CODES",
    "DEFAULT_SCOPES",
    "FORM_CODES",
    "LEGACY_SLUG",
    "MANAGED_AUTHENTIK",
    "MANAGED_HAND",
    "MANAGED_NEXSUITE",
    "AccountState",
    "AppConfig",
    "Identity",
    "Impact",
    "Invite",
    "Link",
    "OidcError",
    "Provider",
    "ProviderInvalid",
    "ProviderValues",
    "Store",
    "__version__",
    "configure",
    "current",
    "secret_context",
    "use_transport",
    "warm",
]
