"""OpenID Connect itself (Bauplan 02): discovery, the address at the provider, the code exchange, the token checks,
userinfo. No accounts, no database, no cookies; ``flow.py`` puts these pieces together and ``accounts.py`` decides
who the identity is.

The flow is the Authorization Code Flow with PKCE (S256), always. Why three random values although they look alike:
``state`` stops somebody from planting a foreign answer into a browser (CSRF on the return leg), ``nonce`` sits inside
the token and stops an intercepted id token from being redeemed a second time, and the PKCE ``verifier`` makes an
intercepted code worthless. On top of that every ``state`` is consumed once on the server (``attempt.py``).

No OIDC library: httpx fetches the documents, PyJWT checks the signatures. The standard is small enough to write out,
and a library would bring a second HTTP stack and a second reading of JWT.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

import httpx
import jwt

from . import config, tls
from .errors import OidcError
from .model import Identity, Provider

#: Asymmetric signature algorithms only. RS256 is what the standard requires and what nearly every provider uses; the
#: others are common variants (Pocket ID lets one pick ES512 and EdDSA). Never HS…: a symmetrically signed token would
#: be checked with the client secret, and bending the ``alg`` header is the best known JWT attack.
ALGORITHMS = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA")
#: Clock tolerance in seconds. Self-hosted providers run on machines whose clock has been known to lag.
CLOCK_LEEWAY = 60
#: Discovery document and keys are cached: they rarely change, and without the cache every sign-in would start with
#: three fetches. Saving a provider fetches fresh.
CACHE_SECONDS = 3600
#: Discovery, keys and the token exchange. Small self-hosted providers occasionally need a few seconds.
TIMEOUT_SECONDS = 10
#: userinfo hangs on every sign-in and its absence is bearable: a shorter leash.
USERINFO_SECONDS = 5
#: What the discovery document must name.
REQUIRED_DISCOVERY = ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri")

#: Microsoft Entra ID with ``common`` or ``organizations``: the discovery document names
#: ``https://login.microsoftonline.com/{tenantid}/v2.0``. Every token carries the real tenant in ``tid``.
TENANT_PLACEHOLDER = "{tenantid}"
#: A tenant id as Entra writes it: a GUID. Anything else in ``tid`` fills in no placeholder.
_TENANT_ID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
#: One path segment in place of the placeholder: anything but a slash, at least one character.
_SEGMENT = re.compile(r"[^/?#\s]+")
_JWT_PART = re.compile(r"[A-Za-z0-9_-]+")


def _log() -> logging.Logger:
    return logging.getLogger(config.current().log_name)


# ---------------------------------------------------------------------------
# Issuers
# ---------------------------------------------------------------------------


def normalize_issuer(issuer: str) -> str:
    """How an issuer is stored and compared: without spaces around it and without a slash at the end."""
    return issuer.strip().rstrip("/")


def _placeholder_well_placed(published: str) -> bool:
    """The placeholder counts only as a whole path segment, and only once."""
    parts = published.split("/")
    return published.count(TENANT_PLACEHOLDER) == 1 and parts.count(TENANT_PLACEHOLDER) == 1


def _placeholder_pattern(published: str) -> re.Pattern[str] | None:
    """The configured addresses a published issuer with the Entra placeholder stands for, or None when it has none.

    ``/x{tenantid}/`` or two placeholders are no licence for anything: then the pattern matches nothing at all."""
    if TENANT_PLACEHOLDER not in published:
        return None
    if not _placeholder_well_placed(published):
        return re.compile(r"(?!)")
    parts = published.split("/")
    whole = [index for index, part in enumerate(parts) if part == TENANT_PLACEHOLDER]
    before = "/".join(parts[: whole[0]])
    after = "/".join(parts[whole[0] + 1 :])
    tail = "/" + re.escape(after) if whole[0] + 1 < len(parts) else ""
    return re.compile(re.escape(before) + "/" + _SEGMENT.pattern + tail)


def _comparable(issuer: str) -> str:
    """An issuer as ``same_issuer`` compares it: ``normalize_issuer``, then scheme and host in small letters (they name
    the same server in any case, RFC 3986, "Case Normalization"). Userinfo, path, query and fragment stay exactly as
    written: a path may tell two issuers apart by its letters. Taken apart by hand, not with ``urlsplit``, which drops
    tabs and line breaks and would make ``/tab<TAB>x`` look like ``/tabx``."""
    issuer = normalize_issuer(issuer)
    scheme, separator, rest = issuer.partition("://")
    if not separator or not scheme:
        return issuer
    end = min((index for index in (rest.find(mark) for mark in "/?#") if index >= 0), default=len(rest))
    userinfo, at, host = rest[:end].rpartition("@")
    return f"{scheme.lower()}://{userinfo}{at}{host.lower()}{rest[end:]}"


def same_issuer(a: str, b: str) -> bool:
    """Whether two ways of writing name one issuer.

    Compared without spaces around and without a slash at the end (authentik hands its issuer out with one, a form
    stores it without; taken for two providers, every link was dropped on a plain save), and with scheme and host in
    any case (an older version that stored ``https://SSO.EXAMPLE.COM`` names the same issuer; since 1.0.9). The path
    is compared letter by letter. When one side is a published issuer with Entra's placeholder, the other matches if it
    is the same with exactly one path segment in its place (``common``, ``organizations`` or a tenant id), compared as
    a whole, never as a prefix and never across segments.

    Only for telling whether a configuration names one issuer. The ``iss`` of a token is compared with the issuer of
    the discovery document character by character (``accepted_issuer``), never through this.
    """
    left, right = _comparable(a), _comparable(b)
    if not left or not right:
        return False
    for published, configured in ((left, right), (right, left)):
        pattern = _placeholder_pattern(published)
        if pattern is not None:
            return TENANT_PLACEHOLDER not in configured and pattern.fullmatch(configured) is not None
    return left == right


def accepted_issuer(description: dict[str, Any], claims: dict[str, Any]) -> str | None:
    """Who may have issued this token: the issuer of the discovery document, character by character.

    With Entra's placeholder the tenant id from the token's own ``tid`` takes its place, but only a tenant id in the
    form of a GUID. The token is signed by then, so ``tid`` is the provider's word; which tenants get in is the app
    registration's business at Entra. Without such a ``tid`` there is no issuer to accept: the placeholder itself never
    passes."""
    published = str(description.get("issuer") or "")
    if TENANT_PLACEHOLDER not in published:
        return published or None
    tenant = claims.get("tid")
    if not isinstance(tenant, str) or not _TENANT_ID.fullmatch(tenant):
        return None
    if not _placeholder_well_placed(published):
        return None
    return published.replace(TENANT_PLACEHOLDER, tenant)


def username_from(claims: dict[str, Any]) -> str:
    """The name a new account starts from: ``preferred_username``, and when that is an address or a UPN (Entra sends
    ``max@example.com``) only the part before the @; else ``name``. "" when neither gives anything."""
    preferred = str(claims.get("preferred_username") or "").strip()
    if "@" in preferred:
        preferred = preferred.split("@", 1)[0].strip()
    return preferred or str(claims.get("name") or "").strip()


def masked(email: str | None) -> str:
    """An address for the log: recognisable, not complete. The log runs for weeks and travels with bug reports."""
    if not email:
        return "none"
    local, _, domain = email.partition("@")
    return f"{local[:2]}***@{domain}" if domain else f"{local[:2]}***"


# ---------------------------------------------------------------------------
# One attempt
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Attempt:
    """The three random values of one sign-in attempt."""

    state: str
    nonce: str
    verifier: str

    @property
    def challenge(self) -> str:
        """The PKCE challenge for the verifier (S256)."""
        digest = hashlib.sha256(self.verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def new_attempt() -> Attempt:
    return Attempt(state=secrets.token_urlsafe(24), nonce=secrets.token_urlsafe(24), verifier=secrets.token_urlsafe(48))


# ---------------------------------------------------------------------------
# Calls to the provider
# ---------------------------------------------------------------------------

#: issuer -> (document, fetched at); jwks_uri -> (key set, fetched at). Losing them at a restart costs one fetch.
_discovery_cache: dict[str, tuple[dict[str, Any], float]] = {}
_jwks_cache: dict[str, tuple[dict[str, Any], float]] = {}


def clear_caches() -> None:
    """For the tests, and when the operator changes a provider."""
    _discovery_cache.clear()
    _jwks_cache.clear()


async def _client(timeout: float = TIMEOUT_SECONDS) -> httpx.AsyncClient:
    # A fresh client per operation: the app runs under different event loops in tests, and a sign-in is rare enough
    # that connection reuse buys nothing. Redirects are not followed: a redirect is a misconfiguration to report.
    # The TLS context is read once for the module (``tls.py``), never per client and never in the event loop.
    return httpx.AsyncClient(timeout=timeout, transport=config.transport(), verify=await tls.context())


def _content_type(response: httpx.Response) -> str:
    return response.headers.get("content-type", "").split(";")[0].strip().lower()


def _as_object(response: httpx.Response, purpose: str, url: str) -> dict[str, Any]:
    """The body as a JSON object, or the real reason why not. The body itself never goes into the log: the token
    response carries tokens."""
    try:
        data = response.json()
    except ValueError as error:
        _log().warning(
            "OIDC: the %s at %r is not JSON (content-type %s, %d bytes)",
            purpose,
            url,
            _content_type(response) or "none",
            len(response.content),
        )
        raise OidcError("oidc_provider_invalid", "The provider's answer cannot be understood.") from error
    if not isinstance(data, dict):
        _log().warning("OIDC: the %s at %r is JSON but not an object (%s)", purpose, url, type(data).__name__)
        raise OidcError("oidc_provider_invalid", "The provider's answer cannot be understood.")
    return data


async def _fetch_json(url: str, purpose: str) -> dict[str, Any]:
    try:
        async with await _client() as client:
            response = await client.get(url)
    except httpx.HTTPError as error:
        _log().warning("OIDC: fetching the %s from %r failed: %r", purpose, url, error)
        raise OidcError("oidc_provider_unreachable", "The provider cannot be reached right now.") from error
    except Exception as error:
        # ``httpx.InvalidURL`` is not an HTTPError and comes before any request: the address is from outside.
        _log().warning("OIDC: the address for the %s cannot be used at all (%r): %r", purpose, url, error)
        raise OidcError("oidc_provider_unreachable", "The provider cannot be reached right now.") from error
    if not response.is_success:
        target = response.headers.get("location")
        _log().warning(
            "OIDC: fetching the %s from %r answered %d (content-type %s%s)",
            purpose,
            url,
            response.status_code,
            _content_type(response) or "none",
            f", redirect to {target!r}" if target else "",
        )
        raise OidcError("oidc_provider_unreachable", "The provider cannot be reached right now.")
    return _as_object(response, purpose, url)


async def discovery(issuer: str, *, fresh: bool = False) -> dict[str, Any]:
    """The provider's discovery document, cached for an hour.

    The ``issuer`` inside must be the configured one (``same_issuer``): it is later compared character by character
    with the ``iss`` of every token, and a provider answering under one address and claiming another would silently
    defeat that check."""
    key = normalize_issuer(issuer)
    if not fresh:
        cached = _discovery_cache.get(key)
        if cached is not None and time.monotonic() - cached[1] < CACHE_SECONDS:
            return cached[0]
    data = await _fetch_json(f"{key}/.well-known/openid-configuration", "provider description")
    missing = [name for name in REQUIRED_DISCOVERY if not isinstance(data.get(name), str) or not data.get(name)]
    if missing:
        _log().warning("OIDC: the provider description at %r is missing %s", key, ", ".join(missing))
        raise OidcError("oidc_provider_invalid", "The provider's answer cannot be understood.")
    if not same_issuer(str(data["issuer"]), key):
        _log().warning("OIDC: provider at %r calls itself %r, refusing the mismatch", key, data["issuer"])
        raise OidcError("oidc_issuer_mismatch", "The provider calls itself something other than what was entered.")
    _discovery_cache[key] = (data, time.monotonic())
    return data


#: The key type an algorithm needs: a key of another type never checks a token (an ``oct`` key least of all).
KEY_TYPES = {"RS": "RSA", "PS": "RSA", "ES": "EC", "Ed": "OKP"}


def _find_key(jwks: dict[str, Any], kid: str | None, algorithm: str) -> dict[str, Any] | None:
    """The signing key for ``kid``: only keys meant for signatures (``use`` missing or ``sig``) of the type the
    algorithm needs. Without a kid the situation is unambiguous only with exactly one such key; guessing is worse."""
    wanted = KEY_TYPES.get(algorithm[:2])
    keys = [
        key
        for key in jwks.get("keys", [])
        if isinstance(key, dict) and key.get("use") in (None, "sig") and wanted is not None and key.get("kty") == wanted
    ]
    if kid is None:
        return keys[0] if len(keys) == 1 else None
    return next((key for key in keys if key.get("kid") == kid), None)


async def _signing_key(jwks_uri: str, kid: str | None, algorithm: str) -> dict[str, Any]:
    """The key for this ``kid``. An unknown kid triggers one fresh fetch: providers rotate their keys."""
    cached = _jwks_cache.get(jwks_uri)
    if cached is not None and time.monotonic() - cached[1] < CACHE_SECONDS:
        found = _find_key(cached[0], kid, algorithm)
        if found is not None:
            return found
    data = await _fetch_json(jwks_uri, "signing keys")
    _jwks_cache[jwks_uri] = (data, time.monotonic())
    found = _find_key(data, kid, algorithm)
    if found is None:
        offered = [str(entry.get("kid")) for entry in data.get("keys", []) if isinstance(entry, dict)]
        _log().warning(
            "OIDC: no signing key for kid %r at %r, the provider offers %s",
            kid,
            jwks_uri,
            ", ".join(offered) or "no keys at all",
        )
        raise OidcError("oidc_token_invalid", "The provider's token could not be checked.")
    return found


def authorization_url(description: dict[str, Any], provider: Provider, redirect_uri: str, attempt: Attempt) -> str:
    base = str(description["authorization_endpoint"])
    separator = "&" if "?" in base else "?"
    scopes = " ".join(provider.scopes.split()) or "openid"
    return (
        base
        + separator
        + urlencode(
            {
                "response_type": "code",
                "client_id": provider.client_id,
                "redirect_uri": redirect_uri,
                "scope": scopes,
                "state": attempt.state,
                "nonce": attempt.nonce,
                "code_challenge": attempt.challenge,
                "code_challenge_method": "S256",
            }
        )
    )


def _oauth_error(response: httpx.Response) -> str:
    """Why the provider refused, in one line for the log (RFC 6749 5.2). No JSON means something in front of the
    provider answered, not the provider."""
    try:
        data = response.json()
    except ValueError:
        return (
            f"no JSON body (content-type {_content_type(response) or 'none'}, {len(response.content)} bytes), "
            "usually a proxy or an error page in front of the provider"
        )
    if not isinstance(data, dict):
        return "a JSON body that is not an object"
    code = str(data.get("error") or "").strip()
    explanation = str(data.get("error_description") or "").strip()
    if not code and not explanation:
        return f"a JSON body without the error field (it carries: {', '.join(sorted(data)) or 'nothing at all'})"
    if not explanation:
        return (
            f"error={code} (no error_description); invalid_client points at the client id or the secret, "
            "invalid_grant at the code or at a redirect_uri the provider does not have on file"
        )
    return f"error={code or 'none'} error_description={explanation[:300]!r}"


def token_auth_method(description: dict[str, Any], client_secret: str) -> str:
    """How the client authenticates at the token endpoint: ``client_secret_basic``, unless the discovery names only
    ``client_secret_post`` (not basic); without a secret a public client (``none``), secured by PKCE alone."""
    if not client_secret:
        return "none"
    supported = description.get("token_endpoint_auth_methods_supported")
    if isinstance(supported, list) and "client_secret_post" in supported and "client_secret_basic" not in supported:
        return "client_secret_post"
    return "client_secret_basic"


async def exchange_code(
    description: dict[str, Any], provider: Provider, code: str, redirect_uri: str, verifier: str
) -> tuple[str, str | None]:
    """The one-time code for the tokens: (id_token, access_token or None)."""
    url = str(description["token_endpoint"])
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "code_verifier": verifier}
    method = token_auth_method(description, provider.client_secret)
    auth: tuple[str, str] | None = None
    if method == "client_secret_basic":
        # RFC 6749 2.3.1: id and secret are form-encoded before they go into the Basic header; a provider decodes
        # them again. Unreserved characters (letters, digits, "-._~") stay as they are.
        auth = (quote(provider.client_id, safe=""), quote(provider.client_secret, safe=""))
    else:
        form["client_id"] = provider.client_id
        if method == "client_secret_post":
            form["client_secret"] = provider.client_secret
    try:
        async with await _client() as client:
            response = await client.post(url, auth=auth, data=form)
    except httpx.HTTPError as error:
        _log().warning("OIDC: the token exchange at %r could not be sent: %r", url, error)
        raise OidcError("oidc_provider_unreachable", "The provider cannot be reached right now.") from error
    except Exception as error:
        _log().warning("OIDC: the token endpoint address %r cannot be used at all: %r", url, error)
        raise OidcError("oidc_provider_unreachable", "The provider cannot be reached right now.") from error
    if response.status_code != 200:
        _log().warning(
            "OIDC: the token endpoint at %r refused the exchange (%s) with %d: %s",
            url,
            method,
            response.status_code,
            _oauth_error(response),
        )
        raise OidcError("oidc_token_refused", "The provider did not redeem the code.")
    data = _as_object(response, "token response", url)
    id_token = data.get("id_token")
    if not isinstance(id_token, str) or not id_token:
        # Field names, never values: the values are tokens.
        _log().warning(
            "OIDC: the token endpoint at %r answered 200 without an id_token (the response carries: %s)",
            url,
            ", ".join(sorted(data)) or "nothing at all",
        )
        raise OidcError("oidc_token_refused", "The provider did not redeem the code.")
    access_token = data.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        access_token = None
    return id_token, access_token


async def verify_token(
    description: dict[str, Any], client_id: str, token: str, *, purpose: str, required: tuple[str, ...]
) -> dict[str, Any]:
    """Check and open a signed document of the provider: the id token, or a signed userinfo answer with the same
    demands (a milder second check would be the hole). Signature against the published keys, algorithm from the list,
    audience, expiry with leeway, ``azp``, issuer through ``accepted_issuer``."""
    invalid = OidcError("oidc_token_invalid", "The provider's token could not be checked.")
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as error:
        _log().warning("OIDC: %s is not a readable JWT: %s", purpose, error)
        raise invalid from error
    algorithm = str(header.get("alg") or "")
    if algorithm.upper().startswith("HS"):
        # Signed with the client secret: the provider has no signing key (authentik without one does exactly that).
        _log().warning(
            "OIDC: %s is signed with %s, the client secret; the provider needs a signing key", purpose, algorithm
        )
        raise OidcError("oidc_no_signing_key", "The provider signs without a key.")
    if algorithm not in ALGORITHMS:
        _log().warning("OIDC: %s is signed with %r, which is not on the list", purpose, algorithm)
        raise invalid
    kid = header.get("kid")
    jwks_uri = str(description["jwks_uri"])
    jwk = await _signing_key(jwks_uri, kid if isinstance(kid, str) else None, algorithm)
    try:
        key = jwt.PyJWK(jwk).key
    except jwt.PyJWTError as error:
        _log().warning(
            "OIDC: unusable signing key from %r (kid %r, kty %r, crv %r): %s",
            jwks_uri,
            jwk.get("kid"),
            jwk.get("kty"),
            jwk.get("crv"),
            error,
        )
        raise invalid from error
    try:
        claims = jwt.decode(
            token,
            key=key,
            algorithms=list(ALGORITHMS),
            audience=client_id,
            leeway=CLOCK_LEEWAY,
            # The issuer is checked below: with Entra's placeholder the accepted one depends on the token's tid.
            options={"require": list(required), "verify_iss": False},
        )
    except jwt.PyJWTError as error:
        _log().warning(
            "OIDC: %s was rejected (alg %r, kid %r, expected issuer %r): %s",
            purpose,
            algorithm,
            kid,
            description.get("issuer"),
            error,
        )
        raise invalid from error
    expected = accepted_issuer(description, claims)
    if expected is None or claims.get("iss") != expected:
        _log().warning(
            "OIDC: %s was rejected (alg %r, kid %r, expected issuer %r): issued by %r",
            purpose,
            algorithm,
            kid,
            expected or description.get("issuer"),
            claims.get("iss"),
        )
        raise invalid
    # ``azp`` must be this client whenever it is present (OIDC Core, "ID Token Validation"): a token for another
    # application that merely mentions this one in ``aud`` would pass otherwise.
    if "azp" in claims and claims.get("azp") != client_id:
        _log().warning("OIDC: %s carries azp %r, which is not this client", purpose, claims.get("azp"))
        raise invalid
    return claims


def _looks_signed(response: httpx.Response) -> bool:
    """Is the body a JWT instead of a JSON object? ``application/jwt`` decides (Core 5.3.2); a look at the body is
    the fallback for a proxy that bends headers."""
    if _content_type(response) == "application/jwt":
        return True
    parts = response.text.strip().split(".")
    return len(parts) == 3 and all(_JWT_PART.fullmatch(part) for part in parts)


async def _read_userinfo(
    description: dict[str, Any], client_id: str, response: httpx.Response, url: str
) -> dict[str, Any] | None:
    if _looks_signed(response):
        try:
            # Without ``exp``: the standard requires it for the id token, not for a signed userinfo answer.
            return await verify_token(
                description,
                client_id,
                response.text.strip(),
                purpose="the signed userinfo",
                required=("iss", "aud", "sub"),
            )
        except OidcError:
            return None
    try:
        data = response.json()
    except ValueError:
        _log().warning(
            "OIDC: userinfo at %r answered neither JSON nor a signed token (content-type %s, %d bytes)",
            url,
            _content_type(response) or "none",
            len(response.content),
        )
        return None
    if not isinstance(data, dict):
        _log().warning("OIDC: userinfo at %r did not answer with an object but with %s", url, type(data).__name__)
        return None
    return data


async def ask_userinfo(description: dict[str, Any], client_id: str, access_token: str, subject: str) -> dict[str, Any]:
    """What the provider says about this person at ``userinfo``, asked always when the document names the endpoint
    (Authelia and Zitadel keep the address only there). A failure breaks nothing: the fallback is "no additional
    information". An answer for another ``sub`` is discarded (Core 5.3.2)."""
    url = description.get("userinfo_endpoint")
    if not isinstance(url, str) or not url:
        return {}
    try:
        async with await _client(USERINFO_SECONDS) as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {access_token}"})
        response.raise_for_status()
        data = await _read_userinfo(description, client_id, response, url)
    except Exception as error:  # noqa: BLE001
        # Every exception on purpose: whoever gets in today without this call must get in tomorrow too. Entra's
        # Graph endpoint usually answers nothing that fits; that is planned for.
        _log().warning("OIDC: userinfo at %r could not be read: %r", url, error)
        return {}
    if data is None:
        return {}
    if str(data.get("sub") or "") != subject:
        _log().warning("OIDC: userinfo at %r answered for a different subject, discarded", url)
        return {}
    return data


async def verify_id_token(
    description: dict[str, Any], client_id: str, id_token: str, nonce: str, access_token: str | None
) -> Identity:
    """Check the id token, ask userinfo, and hand out the identity. The id token wins where both name a claim."""
    claims = await verify_token(
        description, client_id, id_token, purpose="the id_token", required=("exp", "iss", "aud", "sub")
    )
    carried = claims.get("nonce")
    if not nonce or not isinstance(carried, str) or not hmac.compare_digest(carried.encode(), nonce.encode()):
        _log().warning(
            "OIDC: the id_token does not belong to this sign-in, it carries %s",
            "no nonce at all" if claims.get("nonce") is None else "a different nonce",
        )
        raise OidcError("oidc_token_invalid", "The provider's token could not be checked.")
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        # ``require`` only insists the claim exists. An empty subject would match every account that has none.
        _log().warning("OIDC: the id_token carries an empty subject")
        raise OidcError("oidc_token_invalid", "The provider's token could not be checked.")
    if access_token:
        extra = await ask_userinfo(description, client_id, access_token, subject)
        claims = {**extra, **claims}
    email = str(claims.get("email") or "").strip() or None
    preferred = str(claims.get("preferred_username") or "").strip() or None
    name = str(claims.get("name") or "").strip() or None
    return Identity(issuer=str(claims["iss"]), subject=subject, email=email, preferred_username=preferred, name=name)
