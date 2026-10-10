"""The authentik button and the blueprint (Bauplan 03).

The operator hands over the address of authentik and a one-time API token. The app then does through the authentik
API v3 what one would otherwise click together in a dozen forms: a signing key, the provider with authentik's own
scope mappings, the application, and finally its entry in the provider list. Every step reports ``ok``, a technical
``detail`` for the log, and on failure a ``reason`` with ``status`` that the page says as a sentence in the operator's
language. The first failure stops the run; what came before stays in authentik, and running the button again updates
instead of duplicating.

The token is used for these calls only: in the ``Authorization`` header and nowhere else, never stored, never logged.
The answer of a failed call goes to the log at DEBUG only, never to the page: the address comes from the operator and
could point at any service on the network.

No mapping of its own that vouches for ``email_verified``: the app never finds anybody by an address.

Several instances of one app can hang on one authentik (``_names``): first the own provider, found by the client id
stored here under whatever name (after a move to a new address, too); then an application the stored issuer names that
was left without a provider; else the plain names ``<app>``, unless a provider of that name sends people elsewhere,
then ``<app> (<host>)``. An application of another provider is never taken. Applications are searched with
``superuser_full_list``; otherwise the token sees only those its user may open.

Written against the authentik API v3 of 2024.x to 2026.8. Since 2026.8 a provider carries ``grant_types``, and the
authorize endpoint refuses every request whose grant is not listed there with ``invalid_request``; older versions
ignore the field.
"""

from __future__ import annotations

import json
import logging
import re
import ssl
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from . import config, flow, protocol, providers, tls
from .errors import OidcError
from .model import (
    DEFAULT_SCOPES,
    MANAGED_AUTHENTIK,
    MANAGED_HAND,
    Provider,
    ProviderValues,
    Store,
)

STEP_KEYS = ("reached", "signingKey", "mapping", "provider", "application", "filled")
#: Only in apps with one account (Bauplan 06): authentik lets only the token's own user into the application.
STEP_BINDING = "binding"
REASONS = (
    "unreachable",
    "unusable",
    "token",
    "malformed",
    "answered",
    "slug",
    "coupled",
    "issuer_change",
    "public_url_needed",
)
#: How much of a proxy header the card is shown; it comes from outside.
FORWARDED_MAX = 200
#: Scheme and host of an address, the same way ``frontend/oidc.ts`` (``authentikAddressMismatch``) takes them apart.
_ORIGIN = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://([^/?#]*)")
#: authentik's own mappings, found by their managed names.
MANAGED_MAPPINGS = (
    "goauthentik.io/providers/oauth2/scope-openid",
    "goauthentik.io/providers/oauth2/scope-email",
    "goauthentik.io/providers/oauth2/scope-profile",
)
#: The one grant the app uses: no refresh tokens, no client credentials, no device codes.
GRANT_TYPES = ("authorization_code",)
PREFERRED_AUTHORIZATION_FLOW = "default-provider-authorization-implicit-consent"
PREFERRED_INVALIDATION_FLOW = "default-provider-invalidation-flow"
BLUEPRINT_CERTIFICATE = "authentik Self-signed Certificate"
CERT_VALIDITY_DAYS = 3650
TIMEOUT = httpx.Timeout(15.0, connect=5.0)
DETAIL_MAX = 300
#: The entry the button keeps in the provider list.
ENTRY_SLUG = "authentik"
ENTRY_LABEL = "authentik"
#: Slugs of applications: authentik keeps them to 50 characters (a Django SlugField); a host suffix to 40.
SLUG_MAX = 50
HOST_MAX = 40
SLUG_TRIES = 10
#: The slug in an issuer the button wrote: ``<authentik>/application/o/<slug>/``.
_ISSUER_SLUG = re.compile(r"/application/o/([-A-Za-z0-9_]+)/?$")
_SPELLED_OUT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"})


def _log() -> logging.Logger:
    return logging.getLogger(f"{config.current().log_name}.authentik")


def step_keys() -> tuple[str, ...]:
    """The steps of this app, in their order."""
    return STEP_KEYS + ((STEP_BINDING,) if config.current().single_account else ())


def app_name() -> str:
    return config.current().app_name


class StepFailed(Exception):
    """``detail`` is the technical line for the log; ``reason`` (with ``status``) names the failure for the page."""

    def __init__(self, detail: str, reason: str = "answered", status: int = 0, count: int = 0) -> None:
        super().__init__(detail)
        if reason not in REASONS:
            raise ValueError(f"unknown reason {reason!r}")
        self.detail, self.reason, self.status, self.count = detail, reason, status, count


@dataclass
class Step:
    key: str
    ok: bool
    detail: str = ""
    reason: str = ""
    status: int = 0

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"key": self.key, "ok": self.ok, "detail": self.detail}
        if not self.ok:
            data["reason"] = self.reason
            data["status"] = self.status
        return data


@dataclass
class SetupResult:
    steps: list[Step] = field(default_factory=list)
    client_id: str = ""
    issuer: str = ""
    provider_id: int | None = None
    links_dropped: int = 0
    #: With ``reason: issuer_change``: how many accounts would have to link again.
    count: int = 0
    #: The public address this run stored (the one the operator confirmed), "" when the app had one already.
    public_url: str = ""
    #: With ``reason: public_url_needed``: what the card shows (``address_view``).
    address: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return len(self.steps) == len(step_keys()) and all(step.ok for step in self.steps)

    def as_dict(self) -> dict[str, Any]:
        """The answer of ``POST <api>/oidc/authentik/setup``: always 200 with the steps that ran. Never the token,
        never the client secret."""
        return {
            "ok": self.ok,
            "steps": [step.as_dict() for step in self.steps],
            "client_id": self.client_id,
            "issuer": self.issuer,
            "provider_id": self.provider_id,
            "links_dropped": self.links_dropped,
            "count": self.count,
            "public_url": self.public_url,
            "address": self.address,
        }


class _Api:
    """The few calls the button needs, with the token in the Authorization header and nowhere else."""

    def __init__(self, base_url: str, token: str, verify: ssl.SSLContext) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=TIMEOUT,
            transport=config.transport(),
            verify=verify,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def call(self, method: str, path: str, *, params: dict[str, str] | None = None, body: Any = None) -> Any:
        url = f"{self.base_url}/api/v3{path}"
        try:
            response = await self._client.request(method, url, params=params, json=body)
        except httpx.HTTPError as error:
            raise StepFailed(
                f"{method} {path}: authentik at {self.base_url} not reachable ({error.__class__.__name__})",
                "unreachable",
            ) from error
        except Exception as error:
            # ``httpx.InvalidURL`` and friends are not HTTPErrors; the address comes from the operator.
            raise StepFailed(
                f"{method} {path}: the address {self.base_url!r} cannot be used ({error.__class__.__name__})",
                "unusable",
            ) from error
        if not response.is_success:
            text = response.text.strip().replace("\n", " ")[:DETAIL_MAX]
            _log().debug("authentik %s %s answered %s: %r", method, path, response.status_code, text)
            kind = response.headers.get("content-type", "").split(";")[0].strip() or "no content type"
            raise StepFailed(
                f"{method} {path} answered {response.status_code} ({kind}); the log has the answer at debug level",
                "token" if response.status_code in (401, 403) else "answered",
                response.status_code,
            )
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as error:
            raise StepFailed(
                f"{method} {path} answered {response.status_code} without JSON", "answered", response.status_code
            ) from error

    async def results(self, path: str, params: dict[str, str]) -> list[dict[str, Any]]:
        data = await self.call("GET", path, params=params)
        entries = data.get("results", []) if isinstance(data, dict) else []
        return [entry for entry in entries if isinstance(entry, dict)]

    async def find_one(self, path: str, params: dict[str, str], key: str, value: str) -> dict[str, Any] | None:
        """The one list entry whose ``key`` equals ``value``: the filter narrows, the exact comparison makes sure a
        looser filter or an ignored parameter does not hand back a stranger."""
        for entry in await self.results(path, params):
            if str(entry.get(key) or "") == value:
                return entry
        return None


def _pk(entry: Any, what: str) -> Any:
    pk = entry.get("pk") if isinstance(entry, dict) else None
    if pk in (None, ""):
        raise StepFailed(f"{what} has no pk in authentik's answer", "answered", 200)
    return pk


# ---------------------------------------------------------------------------
# The steps
# ---------------------------------------------------------------------------


async def _reached(api: _Api) -> str:
    data = await api.call("GET", "/admin/version/")
    version = str(data.get("version_current") or "") if isinstance(data, dict) else ""
    return f"authentik {version}" if version else "authentik reached, version unknown"


async def _signing_key(api: _Api) -> tuple[Any, str]:
    name = app_name()
    existing = await api.find_one("/crypto/certificatekeypairs/", {"name": name}, "name", name)
    if existing is not None:
        return _pk(existing, "the certificate"), f"using the existing certificate {name!r}"
    created = await api.call(
        "POST",
        "/crypto/certificatekeypairs/generate/",
        body={"common_name": name, "subject_alt_name": "", "validity_days": CERT_VALIDITY_DAYS, "alg": "rsa"},
    )
    return _pk(created, "the generated certificate"), f"generated the certificate {name!r} ({CERT_VALIDITY_DAYS} days)"


async def _mappings(api: _Api) -> tuple[list[Any], str]:
    ids = []
    for managed in MANAGED_MAPPINGS:
        found = await api.find_one("/propertymappings/provider/scope/", {"managed": managed}, "managed", managed)
        if found is None:
            raise StepFailed(f"authentik's own scope mapping {managed!r} was not found", "answered", 200)
        ids.append(_pk(found, "a scope mapping"))
    return ids, "using authentik's own mappings for openid, email and profile"


async def _flow(api: _Api, designation: str, preferred: str) -> Any:
    entries = await api.results("/flows/instances/", {"designation": designation})
    if not entries:
        raise StepFailed(f"no flow with designation {designation!r} in authentik", "answered", 200)
    for entry in entries:
        if entry.get("slug") == preferred:
            return _pk(entry, "a flow")
    return _pk(entries[0], "a flow")


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text.translate(_SPELLED_OUT)).encode("ascii", "ignore").decode("ascii")


def instance_names(redirect_uri: str) -> tuple[str, str]:
    """Name and slug of this instance when another instance of the app holds the plain names already."""
    host = urlsplit(redirect_uri).netloc.lower()
    # The host part takes at most 40 characters, and the whole slug stays within authentik's 50 (Bauplan 03).
    room = min(HOST_MAX, SLUG_MAX - len(app_name()) - 1)
    suffix = re.sub(r"[^a-z0-9]+", "-", _ascii(host)).strip("-")[:room].strip("-") or "instance"
    return f"{app_name()} ({host})", f"{app_name()}-{suffix}"


async def _application_by_slug(api: _Api, slug: str) -> dict[str, Any] | None:
    return await api.find_one("/core/applications/", {"slug": slug, "superuser_full_list": "true"}, "slug", slug)


async def _free_slug(api: _Api, name: str, pk: str) -> str:
    """A slug for a new application of the own provider: from its name, then with the provider's number, then counted
    on, each at most 50 characters with the ending. Free: no application has it, or the one there has no provider or
    this one. An application of another provider is never taken."""
    base = re.sub(r"[^a-z0-9]+", "-", _ascii(name.lower())).strip("-") or app_name()
    suffixes = ["", f"-{pk}"] + [f"-{pk}-{number}" for number in range(2, SLUG_TRIES)]
    tries = [f"{base[: SLUG_MAX - len(suffix)].rstrip('-')}{suffix}" for suffix in suffixes]
    for candidate in tries:
        taken = await _application_by_slug(api, candidate)
        if taken is None or str(taken.get("provider") or "") in ("", pk):
            return candidate
    raise StepFailed(
        f"every slug from {tries[0]!r} to {tries[-1]!r} belongs to an application of another provider", "slug"
    )


async def _own_names(api: _Api, entry: Provider | None) -> tuple[str, str] | None:
    """Name and slug of what this instance signed in with so far, or None when authentik holds nothing of it."""
    if entry is None:
        return None
    found = _ISSUER_SLUG.search(entry.issuer + "/")
    slug = found.group(1) if found else ""
    named = await _application_by_slug(api, slug) if slug else None
    own = None
    if entry.client_id:
        own = await api.find_one("/providers/oauth2/", {"client_id": entry.client_id}, "client_id", entry.client_id)
    if own is not None:
        pk, name = str(own.get("pk") or ""), str(own.get("name") or app_name())
        # The provider's own answer names its application; the application list cannot be filtered by provider.
        assigned = str(own.get("assigned_application_slug") or "")
        if assigned:
            return name, assigned
        if slug and (named is None or not named.get("provider")):
            return name, slug
        return name, await _free_slug(api, name, pk)
    if named is not None and not named.get("provider"):
        name = str(named.get("name") or app_name())
        # A provider of that name belongs to another instance: taking it would bend that one.
        if await api.find_one("/providers/oauth2/", {"name": name}, "name", name) is None:
            return name, slug
    return None


async def _names(api: _Api, entry: Provider | None, redirect_uri: str) -> tuple[str, str]:
    names = await _own_names(api, entry)
    if names is not None:
        return names
    plain = app_name()
    existing = await api.find_one("/providers/oauth2/", {"name": plain}, "name", plain)
    if existing is None:
        return plain, plain
    urls = {str(item.get("url", "")) for item in existing.get("redirect_uris") or [] if isinstance(item, dict)}
    if not urls or redirect_uri in urls:
        return plain, plain
    return instance_names(redirect_uri)


async def _entry(store: Store, api: _Api) -> Provider | None:
    """The entry of the list the button looks after: the one it made (``managed = "authentik"``), else a hand-made
    entry at this authentik whose client id names a provider there (the operator typed in by hand what the button
    would have made)."""
    entries = store.list_providers()
    managed = [entry for entry in entries if entry.managed == MANAGED_AUTHENTIK]
    if managed:
        return managed[0]
    prefix = f"{api.base_url}/application/o/".lower()
    for entry in entries:
        if entry.managed != MANAGED_HAND or not (entry.issuer + "/").lower().startswith(prefix) or not entry.client_id:
            continue
        if await api.find_one("/providers/oauth2/", {"client_id": entry.client_id}, "client_id", entry.client_id):
            return entry
    return None


async def _provider(
    api: _Api, redirect_uri: str, signing_key: Any, mappings: list[Any], name: str
) -> tuple[Any, str, str, str]:
    authorization = await _flow(api, "authorization", PREFERRED_AUTHORIZATION_FLOW)
    invalidation = await _flow(api, "invalidation", PREFERRED_INVALIDATION_FLOW)
    body = {
        "name": name,
        "authorization_flow": authorization,
        "invalidation_flow": invalidation,
        "client_type": "confidential",
        "grant_types": list(GRANT_TYPES),
        "redirect_uris": [{"matching_mode": "strict", "url": redirect_uri}],
        "signing_key": signing_key,
        "sub_mode": "user_uuid",
        "property_mappings": mappings,
        "include_claims_in_id_token": True,
    }
    existing = await api.find_one("/providers/oauth2/", {"name": name}, "name", name)
    if existing is None:
        answer = await api.call("POST", "/providers/oauth2/", body=body)
        note = f"created the provider {name!r}"
    else:
        answer = await api.call("PATCH", f"/providers/oauth2/{_pk(existing, 'the provider')}/", body=body)
        note = f"updated the existing provider {name!r}"
    if not isinstance(answer, dict):
        raise StepFailed("the provider call answered without an object", "answered", 200)
    client_id = str(answer.get("client_id") or "")
    client_secret = str(answer.get("client_secret") or "")
    if not client_id or not client_secret:
        raise StepFailed("authentik's provider answer carries no client_id or client_secret", "answered", 200)
    return _pk(answer, "the provider"), client_id, client_secret, note


async def _application(api: _Api, provider_pk: Any, name: str, slug: str) -> tuple[Any, str, str]:
    """Create or update the application of the provider: (its pk, its slug, the detail). When the slug the names step
    chose belongs to an application of another provider, a replacement slug is taken (``_free_slug``): that
    application is never taken over."""
    existing = await _application_by_slug(api, slug)
    if existing is not None and str(existing.get("provider") or "") not in ("", str(provider_pk)):
        slug = await _free_slug(api, name, str(provider_pk))
        existing = await _application_by_slug(api, slug)
    body = {"name": name, "slug": slug, "provider": provider_pk}
    if existing is None:
        answer = await api.call("POST", "/core/applications/", body=body)
        return _pk(answer, "the application"), slug, f"created the application {slug!r}"
    answer = await api.call("PATCH", f"/core/applications/{slug}/", body=body)
    pk = answer.get("pk") if isinstance(answer, dict) and answer.get("pk") else _pk(existing, "the application")
    return pk, slug, f"updated the existing application {slug!r}"


async def _binding(api: _Api, application_pk: Any) -> str:
    """Only the token's own user may open the application: with a binding in place, authentik lets in only whoever
    passes one. The app refuses every other identity anyway; authentik then turns them away before."""
    data = await api.call("GET", "/core/users/me/")
    user = data.get("user") if isinstance(data, dict) else None
    if not isinstance(user, dict):
        raise StepFailed("authentik's answer names no user for this token", "answered", 200)
    user_pk, username = _pk(user, "the token's user"), str(user.get("username") or "")
    for entry in await api.results("/policies/bindings/", {"target": str(application_pk)}):
        if str(entry.get("user") or "") == str(user_pk):
            return f"the application already lets {username!r} in"
    await api.call(
        "POST",
        "/policies/bindings/",
        body={"target": application_pk, "user": user_pk, "order": 0, "enabled": True, "negate": False, "timeout": 30},
    )
    return f"the application lets only {username!r} in"


def normalize_base(base_url: str) -> str:
    """The address of authentik as the button uses it: scheme and host in small letters, the path as typed, no slash
    at the end. authentik writes its issuer that way, and the issuer is compared letter by letter (``same_issuer``):
    ``HTTPS://Auth.Example.com/`` typed on a phone would otherwise read as another issuer. An address that cannot be
    taken apart stays as it is; building the client then names it unusable."""
    raw = base_url.strip()
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw.rstrip("/")
    if parts.scheme and parts.netloc:
        userinfo, at, host = parts.netloc.rpartition("@")
        raw = urlunsplit((parts.scheme.lower(), userinfo + at + host.lower(), parts.path, parts.query, parts.fragment))
    return raw.rstrip("/")


def issuer_for(base_url: str, slug: str) -> str:
    """The issuer as authentik writes it."""
    return f"{base_url.rstrip('/')}/application/o/{slug}/"


def _accounts_of(store: Store, entry: Provider) -> int:
    return len({link.account_id for link in store.links_of_provider(entry.id)})


def _issuer_change(entry: Provider, issuer: str, count: int, *, foreseen: bool) -> StepFailed:
    when = "would change" if foreseen else "changes"
    return StepFailed(
        f"the issuer of entry {entry.slug!r} {when} from {entry.issuer} to {issuer}; {count} accounts would have to"
        " link again, and the operator has not confirmed that yet",
        "issuer_change",
        0,
        count,
    )


async def _ask_first(store: Store, api: _Api, base_url: str, request_base: str) -> None:
    """Bauplan 03, "Rückfrage vor dem Wechsel": raise ``issuer_change`` when the run would give an entry with links
    another issuer, found with reading calls only (the same ones the run makes later). Nothing to ask without an entry
    or without links. An issuer that cannot be told in advance (the application slug belongs to another provider and
    the own provider does not exist yet, so the replacement slug carries a number authentik has not handed out) counts
    as another one: asking once too often costs a click, dropping links unasked costs the people their way in."""
    entry = await _entry(store, api)
    count = _accounts_of(store, entry) if entry is not None else 0
    if entry is None or not count:
        return
    redirect = flow.redirect_uri(entry.slug, request_base, entry.redirect_path)
    name, slug = await _names(api, entry, redirect)
    existing = await api.find_one("/providers/oauth2/", {"name": name}, "name", name)
    pk = str(existing.get("pk") or "") if existing is not None else ""
    application = await _application_by_slug(api, slug)
    if application is not None and str(application.get("provider") or "") not in ("", pk):
        if not pk:
            raise _issuer_change(entry, f"a new application at {base_url}", count, foreseen=True)
        try:
            slug = await _free_slug(api, name, pk)
        except StepFailed:
            # The run stops at the application with reason "slug" before it reaches the list.
            return
    issuer = issuer_for(base_url, slug)
    if not protocol.same_issuer(entry.issuer, issuer):
        raise _issuer_change(entry, issuer, count, foreseen=True)


async def _fill(
    store: Store,
    entry: Provider | None,
    entry_slug: str,
    issuer: str,
    client_id: str,
    client_secret: str,
    confirmed: bool,
    redirect: str,
) -> tuple[Provider, int, str]:
    """Confirm the new issuer with one discovery, then write the entry. Probed first: a failed discovery changes
    nothing in the list, and links only go when an issuer that answers really replaces the old one (Bauplan 02). What
    authentik handed out stays there; running the button again once authentik is reachable fills the entry. A new
    entry is on, makes no new accounts and trusts authentik with the second factor; an existing one keeps the
    operator's choices and only gets issuer, client id and secret. Either way the entry remembers the redirect
    address this run registered at authentik (``registered_redirect``). The number returned is the links really
    dropped.

    The guard behind the question at the start: should authentik have handed out another issuer than foreseen, an
    unconfirmed change stops here too, with nothing written in the app (what the run made in authentik stays, and the
    confirmed run updates it)."""
    if entry is not None and not confirmed and not protocol.same_issuer(entry.issuer, issuer):
        count = _accounts_of(store, entry)
        if count:
            raise _issuer_change(entry, issuer, count, foreseen=False)
    try:
        await protocol.discovery(issuer, fresh=True)
    except OidcError as error:
        reason = "unreachable" if error.code == "oidc_provider_unreachable" else "answered"
        raise StepFailed(
            f"discovery at {issuer} failed: {error.code}; the list is unchanged",
            reason,
            200 if reason == "answered" else 0,
        ) from error
    dropped = 0
    if entry is None:
        position = max((item.position for item in store.list_providers()), default=-1) + 1
        saved = store.insert_provider(
            ProviderValues(
                slug=entry_slug,
                label=ENTRY_LABEL,
                issuer=protocol.normalize_issuer(issuer),
                client_id=client_id,
                client_secret=client_secret,
                scopes=DEFAULT_SCOPES,
                enabled=True,
                auto_create=False,
                trusts_second_factor=True,
                managed=MANAGED_AUTHENTIK,
                position=position,
                registered_redirect=redirect,
            )
        )
        note = f"entry {saved.slug!r} added"
    else:
        dropped = providers.change_issuer(store, entry, issuer)
        saved = store.update_provider(
            entry.id,
            ProviderValues(
                slug=entry.slug,
                label=entry.label,
                issuer=protocol.normalize_issuer(issuer),
                client_id=client_id,
                client_secret=client_secret,
                scopes=entry.scopes,
                enabled=entry.enabled,
                auto_create=entry.auto_create,
                trusts_second_factor=entry.trusts_second_factor,
                managed=MANAGED_AUTHENTIK,
                position=entry.position,
                redirect_path=entry.redirect_path,
                registered_redirect=redirect,
            ),
        )
        note = f"entry {saved.slug!r} updated" + (f", {dropped} links dropped" if dropped else "")
    store.commit()
    protocol.clear_caches()
    return saved, dropped, f"discovery at {issuer} confirmed; {note}"


async def setup(
    store: Store,
    base_url: str,
    token: str,
    request_base: str,
    *,
    confirm_issuer_change: bool = False,
    public_url: str = "",
    headers: Mapping[str, str] | None = None,
) -> SetupResult:
    """The whole run, step by step. Stops at the first failure; the result lists every step that ran.

    The button never registers an address it guessed from the request (Bauplan 03, "Rückleitadresse", decided on
    10.10.2026). Without a public address of the app it needs ``public_url``, the address the operator confirmed in the
    card (the one the browser uses); it stores that through ``AppConfig.save_public_url`` and only then sets up.
    Without either it stops at the first step, before any call, with ``reason: public_url_needed`` and ``address``
    (``address_view``, ``headers`` are the request's). An address the app has already wins over a confirmed one.

    Would the run give the entry another issuer while accounts are linked to it, it stops at the first step, after
    reading calls only, with ``reason: issuer_change`` and ``count`` (Bauplan 03): nothing is written in authentik or
    in the app. The page asks the operator with ``oidc.admin.issuerChangeConfirm`` and runs the button again with
    ``confirm_issuer_change=True``, which changes the issuer and drops the links."""
    base_url = normalize_base(base_url)
    result = SetupResult()
    if providers.coupled(store):
        # While coupled, sign-in comes through nexsuite (Bauplan 06): the button touches neither authentik nor the
        # list, and says so at the first step. The app locks the card meanwhile; this is the guard behind it.
        detail = "the app is coupled to nexsuite; the button changes nothing until it is uncoupled"
        result.steps.append(Step(STEP_KEYS[0], False, detail, "coupled", 0))
        _log().warning("authentik setup stopped at step %s: %s", STEP_KEYS[0], detail)
        return result
    try:
        if not token.isascii() or not token.isprintable() or any(char.isspace() for char in token):
            # No HTTP header carries it, so no authentik token looks like this (Bauplan 03: reason "malformed").
            raise StepFailed("the token holds characters an HTTP header cannot carry", "malformed", 0)
        try:
            result.public_url = _public_url_first(store, public_url, request_base)
        except StepFailed:
            result.address = address_view(store, request_base, headers)
            raise
        api = _Api(base_url, token, await tls.context())
    except StepFailed as error:
        result.steps.append(Step(STEP_KEYS[0], False, error.detail, error.reason, error.status))
        _log().warning("authentik setup stopped at step %s: %s", STEP_KEYS[0], error.detail)
        return result
    except Exception as error:  # noqa: BLE001
        # Whatever else keeps the client from being built comes from the address the operator typed.
        detail = f"the address {base_url!r} cannot be used ({error.__class__.__name__})"
        result.steps.append(Step(STEP_KEYS[0], False, detail, "unusable", 0))
        _log().warning("authentik setup stopped at step %s: %s", STEP_KEYS[0], detail)
        return result
    signing_key: Any = None
    mappings: list[Any] = []
    provider_pk: Any = None
    application_pk: Any = None
    entry: Provider | None = None
    entry_slug = ENTRY_SLUG
    client_id = client_secret = ""
    name = slug = app_name()
    try:
        for key in step_keys():
            try:
                if key == "reached":
                    detail = await _reached(api)
                    if not confirm_issuer_change:
                        await _ask_first(store, api, base_url, request_base)
                elif key == "signingKey":
                    signing_key, detail = await _signing_key(api)
                elif key == "mapping":
                    mappings, detail = await _mappings(api)
                elif key == "provider":
                    entry = await _entry(store, api)
                    entry_slug = entry.slug if entry is not None else providers.free_slug(store, ENTRY_SLUG)
                    redirect = flow.redirect_uri(entry_slug, request_base, entry.redirect_path if entry else "")
                    name, slug = await _names(api, entry, redirect)
                    result.issuer = issuer_for(base_url, slug)
                    provider_pk, client_id, client_secret, detail = await _provider(
                        api, redirect, signing_key, mappings, name
                    )
                    result.client_id = client_id
                elif key == "application":
                    application_pk, slug, detail = await _application(api, provider_pk, name, slug)
                    result.issuer = issuer_for(base_url, slug)
                elif key == "filled":
                    saved, result.links_dropped, detail = await _fill(
                        store,
                        entry,
                        entry_slug,
                        result.issuer,
                        client_id,
                        client_secret,
                        confirm_issuer_change,
                        redirect,
                    )
                    result.provider_id = saved.id
                else:
                    detail = await _binding(api, application_pk)
            except StepFailed as error:
                result.steps.append(Step(key, False, error.detail, error.reason, error.status))
                result.count = error.count
                _log().warning("authentik setup stopped at step %s: %s", key, error.detail)
                break
            result.steps.append(Step(key, True, detail))
            _log().info("authentik setup step %s done: %s", key, detail)
    finally:
        await api.close()
    return result


# ---------------------------------------------------------------------------
# The public address (Bauplan 03 "Rückleitadresse", 04 "Karte 3"; 1.0.10)
# ---------------------------------------------------------------------------


class PublicUrlNeeded(Exception):
    """The app has no public address yet. The blueprint names none it guessed from the request: its route answers 409
    with the code ``public_url_needed``, and the card offers the browser's address first."""


def _public_url_first(store: Store, confirmed: str, request_base: str) -> str:
    """Make sure the app has a public address before anything is registered: the one it has, else the one the
    operator confirmed, stored through ``save_public_url``. The address stored now, or "" when the app had one. An
    entry of the button from before 1.0.10 first gets the redirect address it had (``_remember_registered``): should
    the run fail after the address is stored, the card still reports ``stale``."""
    if flow.configured_public_url():
        return ""
    if not confirmed.strip():
        raise StepFailed(
            "the app has no public address and the operator confirmed none; nothing was registered",
            "public_url_needed",
        )
    try:
        address = flow.clean_public_url(confirmed)
    except ValueError as error:
        raise StepFailed(f"the confirmed public address cannot be used ({error})", "public_url_needed") from error
    try:
        _remember_registered(store, request_base)
        _store_public_url(address)
    except PublicUrlNotKept as error:
        # Nothing is registered without it.
        raise StepFailed(str(error), "public_url_needed") from error
    _log().info("public address set to %s, confirmed in the authentik card", address)
    return address


def _header(headers: Mapping[str, str] | None, name: str) -> str:
    """The first value of a request header, for the card only (never trusted for an address)."""
    for key, value in (headers or {}).items():
        if str(key).lower() == name:
            first = str(value).split(",")[0].strip()[:FORWARDED_MAX]
            return first if first.isprintable() else ""
    return ""


def address_mismatch(proposal: str, seen: str) -> str:
    """How the address the browser uses differs from the one the server sees: ``scheme`` (http here, https there:
    a proxy ends TLS and the app does not take its word), ``host``, or "" when they agree. The browser helper
    ``authentikAddressMismatch`` answers the same."""
    browser, server = _ORIGIN.match(proposal.strip()), _ORIGIN.match(seen.strip())
    if browser is None or server is None:
        return ""
    if browser.group(1).lower() != server.group(1).lower():
        return "scheme"
    if browser.group(2).lower() != server.group(2).lower():
        return "host"
    return ""


def _managed(store: Store) -> Provider | None:
    managed = [entry for entry in store.list_providers() if entry.managed == MANAGED_AUTHENTIK]
    return managed[0] if managed else None


def address_view(store: Store, request_base: str, headers: Mapping[str, str] | None = None) -> dict[str, Any]:
    """What the authentik card shows about the address (``GET <api>/oidc/authentik/address``, and ``address`` of a
    run refused with ``public_url_needed``):

    - ``public_url``: the app's public address, "" for none (then the card suggests the browser's own);
    - ``seen``: the address of this request as the server sees it, ``forwarded_proto`` and ``forwarded_host`` what a
      proxy said, ``proxy_ignored`` whether that differs from what the app took (the card warns);
    - ``callback_path``: what the button registers behind the public address, ``redirect_uri`` the redirect address
      the sign-in sends today;
    - ``registered_redirect_uri``: what the button registered last, ``stale`` whether that is no longer today's.
    """
    seen = request_base.strip().rstrip("/")
    entry = _managed(store)
    slug = entry.slug if entry is not None else providers.free_slug(store, ENTRY_SLUG)
    callback = flow.callback_path(slug, entry.redirect_path if entry is not None else "")
    redirect = flow.base_address(seen) + callback
    registered = entry.registered_redirect if entry is not None else ""
    proto, host = _header(headers, "x-forwarded-proto"), _header(headers, "x-forwarded-host")
    origin = _ORIGIN.match(seen)
    scheme, netloc = (origin.group(1).lower(), origin.group(2).lower()) if origin else ("", "")
    return {
        "public_url": flow.configured_public_url(),
        "seen": seen,
        "forwarded_proto": proto,
        "forwarded_host": host,
        "proxy_ignored": bool(proto and proto.lower() != scheme) or bool(host and host.lower() != netloc),
        "callback_path": callback,
        "redirect_uri": redirect,
        "registered_redirect_uri": registered,
        "stale": bool(registered) and registered != redirect,
    }


def public_url_change(store: Store, new_url: str, request_base: str = "") -> dict[str, Any]:
    """What saving ``new_url`` as the public address leaves behind (the question of card 1, Bauplan 04):

    - ``entries`` and ``count``: the entries the button set up whose redirect address at authentik the new address
      leaves behind (``address``: the first one's, for ``oidc.admin.addressChangeConfirm``). An entry the button made
      before 1.0.10 (no ``registered_redirect``) counts with the redirect address of today.
    - ``hand``: the active entries made by hand whose redirect address changes with it; the operator changes it at
      their provider (``oidc.admin.addressChangeHand`` with ``count`` = ``hand``). The module cannot reach them.

    ``count`` and ``hand`` both 0: save without asking. ``count`` 0 and ``hand`` above 0 asks as well, with
    ``oidc.admin.addressChangeHand`` alone (no entry of the button, so no ``addressChangeConfirm``). ``new_url`` ""
    removes the address (the sign-in then falls back to the request); anything else must pass
    ``flow.clean_public_url`` (raises ``ValueError``). Apps call ``public_url_guard`` (their own route) or
    ``save_public_url`` (the module's route), which ask with this."""
    new = flow.clean_public_url(new_url) if new_url.strip() else ""
    base = new or request_base.strip().rstrip("/")
    old = flow.base_address(request_base)
    entries = []
    hand = 0
    for entry in store.list_providers():
        callback = flow.callback_path(entry.slug, entry.redirect_path)
        target = base + callback if base else ""
        if entry.managed == MANAGED_HAND:
            hand += int(entry.enabled and bool(old) and old + callback != target)
            continue
        if entry.managed != MANAGED_AUTHENTIK:
            continue
        known = entry.registered_redirect or (old + callback if old else "")
        if known and known != target:
            entries.append({"slug": entry.slug, "label": entry.label, "registered": known, "redirect": target})
    return {
        "count": len(entries),
        "entries": entries,
        "address": entries[0]["registered"] if entries else "",
        "hand": hand,
    }


def _remember_registered(store: Store, request_base: str) -> int:
    """Before the public address changes: every entry of the button from before 1.0.10 (no ``registered_redirect``)
    gets the redirect address it has today, the one the button registered with the address before. Then the
    authentik card reports ``stale`` once the new address is saved. Only here, where the operator confirmed the
    change: at start-up nothing is guessed. The number of entries filled."""
    old = flow.base_address(request_base)
    filled = 0
    for entry in store.list_providers():
        if entry.managed != MANAGED_AUTHENTIK or entry.registered_redirect or not old:
            continue
        known = old + flow.callback_path(entry.slug, entry.redirect_path)
        store.update_provider(entry.id, providers.values_of(entry, registered_redirect=known))
        filled += 1
    if filled:
        store.commit()
        _log().info("redirect address of %s entries from before 1.0.10 noted before the address changed", filled)
    return filled


def public_url_guard(store: Store, new_url: str, request_base: str, *, confirm: bool) -> dict[str, Any] | None:
    """For an app that saves the public address in a route of its own (card 1, or its own settings page): call it
    before saving, with the address the operator typed. The question (``public_url_change``) while it asks: the
    route answers 409 ``{"code": "public_url_change", **question}`` and saves nothing; the page asks with
    ``oidc.admin.addressChangeConfirm`` when ``count`` and ``oidc.admin.addressChangeHand`` when ``hand`` (at least
    one of the two) and sends again with ``confirm``. None: save now. With ``confirm`` the entries from before 1.0.10
    get what authentik knows first (committed), so that the card reports ``stale`` afterwards. Raises ``ValueError``
    for an address that is none."""
    change = public_url_change(store, new_url, request_base)
    if not change["count"] and not change["hand"]:
        return None
    if not confirm:
        return change
    _remember_registered(store, request_base)
    return None


class PublicUrlChange(Exception):
    """``save_public_url`` asks first: ``question`` is ``public_url_change``'s answer; the route answers 409 with the
    code ``public_url_change`` and it."""

    def __init__(self, question: dict[str, Any]) -> None:
        super().__init__("the public address changes what authentik knows; the operator has not confirmed it")
        self.question = question


class PublicUrlNotKept(Exception):
    """The app could not store the address (no ``save_public_url``, its own check, its database)."""


def _store_public_url(address: str) -> None:
    """Store a clean address through ``AppConfig.save_public_url`` and read it back."""
    save = config.current().save_public_url
    if save is None:
        raise PublicUrlNotKept(
            f"the app cannot store a public address (no save_public_url); set {app_name().upper()}_PUBLIC_URL"
        )
    try:
        save(address)
    except Exception as error:
        # Whatever keeps the app from storing it (its database, its own check).
        raise PublicUrlNotKept(f"the app could not store the public address ({error.__class__.__name__})") from error
    try:
        kept = flow.clean_public_url(flow.configured_public_url())
    except ValueError:
        kept = ""
    if kept != address:
        raise PublicUrlNotKept("the app did not keep the public address")


def save_public_url(store: Store, new_url: str, request_base: str, *, confirm: bool = False) -> dict[str, Any]:
    """``POST <api>/oidc/authentik/address`` (``{"public_url", "confirm"}``): "Use it only" in the authentik card,
    and card 1 of an app that has no route of its own for the address. Cleans the address (``ValueError``: 422
    ``public_url_invalid``), asks like ``public_url_guard`` (``PublicUrlChange``: 409), stores it through
    ``AppConfig.save_public_url`` and reads it back (``PublicUrlNotKept``: 409 ``public_url_needed``). Answers
    ``address_view`` with the new address."""
    address = flow.clean_public_url(new_url)
    question = public_url_guard(store, address, request_base, confirm=confirm)
    if question is not None:
        raise PublicUrlChange(question)
    _store_public_url(address)
    _log().info("public address set to %s", address)
    return address_view(store, request_base)


# ---------------------------------------------------------------------------
# The blueprint
# ---------------------------------------------------------------------------


def blueprint_filename() -> str:
    return f"{app_name()}-authentik.yaml"


def blueprint(redirect_uri: str) -> str:
    """A blueprint (schema v1) that creates what the button creates, with fixed plain names, ``grant_types``,
    authentik's own self-signed certificate (a blueprint cannot generate one) and the callback of the entry. Client id
    and secret go into the provider form afterwards.

    ``!Find`` and ``!KeyOf`` are authentik's YAML tags, so the file is written as text. Every value that comes from
    outside is emitted as a JSON string, a valid double-quoted YAML scalar whatever it carries."""
    name = app_name()
    quoted = json.dumps
    mappings = "\n".join(
        f"        - !Find [authentik_providers_oauth2.scopemapping, [managed, {quoted(managed)}]]"
        for managed in MANAGED_MAPPINGS
    )
    grants = "\n".join(f"        - {grant}" for grant in GRANT_TYPES)
    return f"""# {name}: OpenID Connect provider and application for authentik.
#
# Apply it under Customization, Blueprints (create a blueprint from this file) or drop it into the blueprints/custom/
# directory of the authentik worker. Afterwards copy client id and client secret from the provider "{name}"
# (Applications, Providers) into {name} under Settings, Server, Sign-in, Sign-in providers, with the issuer
# <authentik address>/application/o/{name}/.
#
# The signing key is authentik's own self-signed certificate: a blueprint cannot generate one. Pick another
# certificate at the provider afterwards if you prefer. grant_types exists since authentik 2026.8, where a provider
# without it refuses every sign-in; older versions ignore the line.
#
# Give the entry in {name} the short name of the redirect address below ({{slug}} in .../oidc/{{slug}}/callback),
# so that the address the provider knows and the one {name} sends are the same.
#
# A second instance of {name} at the same authentik: the plain names "{name}" belong to the first one. Rename provider
# and application in this file first (for example "{name} (host)" and slug "{name}-host"), or applying it takes over
# the first instance's provider and sends its people to this address. The button in {name} does that by itself.
version: 1
metadata:
  name: {quoted(name)}
  labels:
    blueprints.goauthentik.io/description: {quoted("OpenID Connect provider and application for " + name)}
entries:
  - model: authentik_providers_oauth2.oauth2provider
    state: present
    id: {name}-provider
    identifiers:
      name: {quoted(name)}
    attrs:
      authorization_flow: !Find [authentik_flows.flow, [slug, {PREFERRED_AUTHORIZATION_FLOW}]]
      invalidation_flow: !Find [authentik_flows.flow, [slug, {PREFERRED_INVALIDATION_FLOW}]]
      client_type: confidential
      grant_types:
{grants}
      redirect_uris:
        - matching_mode: strict
          url: {quoted(redirect_uri)}
      signing_key: !Find [authentik_crypto.certificatekeypair, [name, {quoted(BLUEPRINT_CERTIFICATE)}]]
      sub_mode: user_uuid
      include_claims_in_id_token: true
      property_mappings:
{mappings}
  - model: authentik_core.application
    state: present
    identifiers:
      slug: {quoted(name)}
    attrs:
      name: {quoted(name)}
      provider: !KeyOf {name}-provider
"""


def blueprint_redirect(store: Store, request_base: str) -> str:
    """The callback the blueprint names: that of the button's entry, else of the entry the button would make, behind
    the app's public address. Without one it raises ``PublicUrlNeeded``: an address guessed from the request is
    ``http`` behind a proxy that ends TLS, and a blueprint with it would fail at the first sign-in (Bauplan 03,
    1.0.10). ``request_base`` is kept for the apps' calls; it is not used for the address."""
    if not flow.configured_public_url():
        raise PublicUrlNeeded("the app has no public address; the blueprint names no guessed one")
    managed = _managed(store)
    if managed is not None:
        return flow.provider_redirect_uri(managed, request_base)
    return flow.redirect_uri(providers.free_slug(store, ENTRY_SLUG), request_base)
