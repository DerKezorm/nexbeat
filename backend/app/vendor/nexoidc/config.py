"""What the module needs to know about the app it runs in.

The module imports nothing from an app. The app hands over what is its own business once at start-up, before the
first request, with ``configure(AppConfig(...))``: its name, its server secret, where its API lives, its public
address, whether it has only one account. Everything else (database, accounts, invitations, sessions) comes in
through the ``Store`` protocol (``model.py``) at the moment it is needed.

Tests replace the network with ``use_transport(httpx.MockTransport(...))``; nothing in the module then touches it.
"""

from __future__ import annotations

import re
import ssl
from collections.abc import Callable
from dataclasses import dataclass

import httpx

#: An app name as it appears in cookie names, key prefixes, authentik names and slugs.
_APP_NAME = re.compile(r"[a-z][a-z0-9-]{1,30}")
#: What an instance adds to its cookie names (letters, digits, "_"): two instances on one host with different ports
#: share their cookies, the browser tells no ports apart (nexcanvas, nextasks, nexbrand: ``cookie_name_suffix()``).
_COOKIE_SUFFIX = re.compile(r"[A-Za-z0-9_]*")
#: Where an API lives: ``/api`` for most apps, ``/api/v1`` for apps whose whole API sits there (Bauplan 06).
_API_PREFIX = re.compile(r"(/[a-z0-9]+)+")
#: At most this long, so that the standard callback stays shorter than ``flow.CALLBACK_MAX`` (since 1.0.10).
API_PREFIX_MAX = 100


def _no_public_url() -> str:
    return ""


@dataclass(frozen=True)
class AppConfig:
    """The app's side of the contract. Only ``app_name`` and ``server_secret`` are required.

    ``server_secret`` returns the app's own server secret (the one its sessions are signed with). The module never
    uses it directly: the attempt cookie gets a key derived from it with the prefix ``<app>-oidc-attempt:``, so an
    attempt never passes as a session and a session never as an attempt.

    ``public_url`` returns the address people use to reach the app, without a slash at the end, or "" when none is
    set: the app's setting first, then the environment variable ``<APP>_PUBLIC_URL``. Without one the sign-in falls
    back to the address of the request, which is wrong behind a proxy that ends TLS; the authentik button never
    registers such an address (it asks the operator to confirm one, ``save_public_url``).

    ``save_public_url`` stores an address the operator confirmed in the authentik card as the app's public address
    (the setting ``public_url`` reads first) and commits it at once, in a transaction of its own. None: the app cannot
    store one, and the button without a public address refuses with ``public_url_needed``.
    """

    app_name: str
    server_secret: Callable[[], str | bytes]
    api_prefix: str = "/api"
    public_url: Callable[[], str] = _no_public_url
    #: Since 1.0.10: stores a confirmed public address (see above).
    save_public_url: Callable[[str], None] | None = None
    #: nexcrate and nexsift: one account only. No invitations, no new accounts through a provider, and the authentik
    #: button adds the step ``binding`` (Bauplan 06).
    single_account: bool = False
    #: The logger the module writes to. Default ``<app>.oidc``.
    logger_name: str = ""
    #: Where the browser lands. A refused sign-in goes to ``login_page?error=<code>``, a refused linking to
    #: ``account_page?error=<code>``, a successful sign-in to ``home``.
    login_page: str = "/login"
    account_page: str = "/account"
    home: str = "/"
    #: The app's own suffix for every cookie of this instance (``Settings.cookie_name_suffix()`` where the app has
    #: one), so that a start at a second instance on the same host does not overwrite this one's attempt. "" for none.
    cookie_suffix: str = ""
    #: A TLS context of the app's own (with the trusted certificates already read) for every call the module makes;
    #: None: the module reads one once, in a worker thread (``tls.py``).
    ssl_context: ssl.SSLContext | None = None

    def __post_init__(self) -> None:
        if not _APP_NAME.fullmatch(self.app_name):
            raise ValueError(f"app_name {self.app_name!r} must be lower-case letters, digits and dashes")
        if not _API_PREFIX.fullmatch(self.api_prefix) or len(self.api_prefix) > API_PREFIX_MAX:
            raise ValueError(f"api_prefix {self.api_prefix!r} must look like /api or /api/v1")
        if not _COOKIE_SUFFIX.fullmatch(self.cookie_suffix):
            raise ValueError(f"cookie_suffix {self.cookie_suffix!r} takes letters, digits and _ only")
        for page in (self.login_page, self.account_page, self.home):
            if not page.startswith("/") or page.startswith("//"):
                raise ValueError(f"page {page!r} must be a path of this app")

    @property
    def log_name(self) -> str:
        return self.logger_name or f"{self.app_name}.oidc"

    @property
    def cookie_name(self) -> str:
        return f"{self.app_name.replace('-', '_')}_oidc{self.cookie_suffix}"

    @property
    def cookie_path(self) -> str:
        return f"{self.api_prefix}/oidc"


_config: AppConfig | None = None
_transport: httpx.BaseTransport | None = None


def configure(config: AppConfig) -> None:
    """Called once by the app at start-up. Calling it again replaces the configuration (tests do that)."""
    global _config
    _config = config


def current() -> AppConfig:
    if _config is None:
        raise RuntimeError("nexoidc is not configured: the app calls nexoidc.configure(AppConfig(...)) at start-up")
    return _config


def use_transport(transport: httpx.BaseTransport | None) -> None:
    """For tests: every call to a provider and to authentik goes through this transport. None: the network."""
    global _transport
    _transport = transport


def transport() -> httpx.BaseTransport | None:
    return _transport
