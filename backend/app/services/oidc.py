"""OpenID Connect: Discovery, Anmeldeadresse, Code-Tausch und ID-Token.

Authorization Code Flow mit PKCE, wie in nexdeck. Zustand, Nonce und Verifier reisen in einem kurzlebigen,
unterschriebenen Cookie; zwischen den beiden Haelften merkt sich der Server nichts.

Entra ID (Microsoft) geht mit drei Eigenheiten mit, alle hier und in ``routers/oidc.py``:

- Mit ``common`` oder ``organizations`` als Aussteller steht in der Discovery ``{tenantid}`` als Platzhalter
  fuer den Mandanten. Der echte Aussteller im Token traegt die Kennung aus ``tid``.
- ``preferred_username`` ist dort die volle UPN (``max@example.com``). Als Benutzername dient der Teil vor dem @.
- ``email`` kommt nur als optionaler Claim, ``email_verified`` gar nicht. nexbeat ordnet ohnehin nur ueber
  ``sub`` zu, die Adresse ist Beiwerk.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from ..security import ALGORITHM, _signing_key
from . import http

COOKIE_NAME = "nexbeat_oidc"
#: Unter ``sitzung.COOKIE_PATH``, damit Anmeldung und Ruecksprung in einem Pfad liegen.
COOKIE_PATH = "/api/auth/oidc"
ATTEMPT_MINUTES = 10
DISCOVERY_SECONDS = 3600
TENANT_PLACEHOLDER = "{tenantid}"

_discovery: dict[str, tuple[float, dict[str, Any]]] = {}
#: Ein Schluessel-Client je Adresse, fuer die Lebensdauer des Prozesses. Neu gebaut cachte er in ein
#: Objekt, das gleich wieder wegfiel (nexdeck, 2026).
_jwks_clients: dict[str, jwt.PyJWKClient] = {}

#: Womit ein ID-Token unterschrieben sein darf. **Kein HS256**: Ein mit dem Client-Geheimnis unterschriebenes
#: Token wuerde mit dem Client-Geheimnis geprueft, und ein gefaelschter ``alg``-Kopf ist der bekannteste
#: Trick gegen JWT.
ALGORITHMS = ["RS256", "ES256", "RS384", "RS512", "ES384", "ES512", "PS256"]

NO_SIGNING_KEY = (
    "The identity provider signs with its client secret or publishes no signing key. "
    "Choose a signing key for the provider; in authentik that is Signing Key on the provider."
)


class OidcError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _client() -> httpx.AsyncClient:
    return http.client("oidc", timeout=15.0)


def forget_discovery(issuer_url: str) -> None:
    """Das gemerkte Dokument verwerfen, damit die naechste Anmeldung den Anbieter frisch liest."""
    _discovery.pop(issuer_url.rstrip("/"), None)


async def discovery(issuer_url: str) -> dict[str, Any]:
    issuer = issuer_url.rstrip("/")
    hit = _discovery.get(issuer)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    try:
        response = await _client().get(f"{issuer}/.well-known/openid-configuration", timeout=10)
    except httpx.HTTPError as error:
        raise OidcError("oidc_unreachable", "The identity provider could not be reached.") from error
    if response.status_code != 200:
        raise OidcError("oidc_unreachable", f"The identity provider answered with HTTP {response.status_code}.")
    try:
        document = response.json()
    except ValueError as error:
        raise OidcError("oidc_bad_discovery", "The discovery document is not JSON.") from error
    if not isinstance(document, dict):
        raise OidcError("oidc_bad_discovery", "The discovery document is not an object.")
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if key not in document:
            raise OidcError("oidc_bad_discovery", f"The discovery document lacks {key}.")
    _discovery[issuer] = (time.monotonic() + DISCOVERY_SECONDS, document)
    return document


def new_attempt() -> dict[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return {
        "state": secrets.token_urlsafe(24),
        "nonce": secrets.token_urlsafe(24),
        "verifier": verifier,
        "challenge": challenge,
    }


def pack_state(slug: str, attempt: dict[str, str], purpose: str = "login", user_id: int | None = None) -> str:
    payload = {
        "type": "oidc",
        "slug": slug,
        "state": attempt["state"],
        "nonce": attempt["nonce"],
        "verifier": attempt["verifier"],
        "purpose": purpose,
        "user_id": user_id,
        "exp": int(time.time()) + ATTEMPT_MINUTES * 60,
    }
    return jwt.encode(payload, _signing_key(), algorithm=ALGORITHM)


def unpack_state(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        payload = jwt.decode(raw, _signing_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    # ⚠️ Derselbe Schluessel unterschreibt auch die Sitzungs-Tokens. Ohne die Art galte ein Erneuerungs-Token
    # hier als Anmeldeversuch und umgekehrt.
    return payload if payload.get("type") == "oidc" else None


def authorization_url(
    document: dict[str, Any], client_id: str, redirect_uri: str, scopes: str, attempt: dict[str, str]
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes or "openid profile email",
        "state": attempt["state"],
        "nonce": attempt["nonce"],
        "code_challenge": attempt["challenge"],
        "code_challenge_method": "S256",
    }
    return f"{document['authorization_endpoint']}?{urlencode(params)}"


async def exchange(
    document: dict[str, Any], client_id: str, client_secret: str, redirect_uri: str, code: str, verifier: str
) -> dict[str, Any]:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": verifier,
    }
    # Geheimnis im Formular (client_secret_post): Das koennen authentik, Entra ID, Keycloak, Authelia und
    # Pocket ID gleichermassen, und es braucht keine Kodierung von Sonderzeichen wie HTTP Basic.
    if client_secret:
        data["client_secret"] = client_secret
    try:
        response = await _client().post(
            document["token_endpoint"], data=data, headers={"Accept": "application/json"}, timeout=15
        )
    except httpx.HTTPError as error:
        raise OidcError("oidc_unreachable", "The identity provider could not be reached for the token.") from error
    if response.status_code != 200:
        raise OidcError("oidc_token_refused", f"The identity provider refused the code (HTTP {response.status_code}).")
    try:
        tokens = response.json()
    except ValueError as error:
        raise OidcError("oidc_token_refused", "The identity provider answered the code without JSON.") from error
    return tokens if isinstance(tokens, dict) else {}


def _jwks_client(uri: str) -> jwt.PyJWKClient:
    existing = _jwks_clients.get(uri)
    if existing is None:
        existing = jwt.PyJWKClient(uri, cache_keys=True)
        _jwks_clients[uri] = existing
    return existing


def accepted_issuers(issuer_url: str, document: dict[str, Any], payload: dict[str, Any]) -> set[str]:
    """Wer das Token ausgestellt haben darf: die eingetragene Adresse und die aus der Discovery.

    ⚠️ Entra ID mit ``common`` oder ``organizations``: Die Discovery nennt ``.../{tenantid}/v2.0``. Eingesetzt
    wird die Kennung aus ``tid`` desselben, bereits unterschriebenen Tokens. Welche Mandanten hineinduerfen,
    regelt dort die App-Registrierung (Single oder Multi Tenant), nicht nexbeat.
    """
    accepted = {issuer_url.rstrip("/")}
    published = str(document.get("issuer") or "").rstrip("/")
    if published:
        accepted.add(published)
        tenant = str(payload.get("tid") or "")
        if TENANT_PLACEHOLDER in published and re.fullmatch(r"[0-9a-fA-F-]{36}", tenant):
            accepted.add(published.replace(TENANT_PLACEHOLDER, tenant))
    accepted.discard("")
    return {issuer for issuer in accepted if TENANT_PLACEHOLDER not in issuer}


async def claims(
    document: dict[str, Any], client_id: str, id_token: str, nonce: str, issuer_url: str
) -> dict[str, Any]:
    try:
        algorithm = str(jwt.get_unverified_header(id_token).get("alg") or "")
    except jwt.PyJWTError as error:
        raise OidcError("oidc_bad_token", f"The ID token could not be read: {error.__class__.__name__}.") from error
    if algorithm.upper().startswith("HS"):
        raise OidcError("oidc_no_signing_key", f"{NO_SIGNING_KEY} The ID token came signed with {algorithm}.")
    try:
        # PyJWKClient holt mit urllib, also blockierend: in einen Thread, sonst steht der Server, solange der
        # Anbieter braucht.
        key = await asyncio.to_thread(_jwks_client(document["jwks_uri"]).get_signing_key_from_jwt, id_token)
        payload = jwt.decode(
            id_token, key.key, algorithms=ALGORITHMS, audience=client_id, options={"verify_iss": False}
        )
    except jwt.PyJWKSetError as error:
        raise OidcError("oidc_no_signing_key", f"{NO_SIGNING_KEY} The key set said: {error}") from error
    except jwt.PyJWTError as error:
        raise OidcError("oidc_bad_token", f"The ID token could not be verified: {error.__class__.__name__}.") from error
    issued_by = str(payload.get("iss", "")).rstrip("/")
    if issued_by not in accepted_issuers(issuer_url, document, payload):
        raise OidcError("oidc_bad_token", "The ID token was issued by someone else.")
    if payload.get("nonce") != nonce:
        raise OidcError("oidc_bad_token", "The ID token does not belong to this attempt.")
    return payload


async def userinfo(document: dict[str, Any], access_token: str) -> dict[str, Any]:
    endpoint = document.get("userinfo_endpoint")
    if not endpoint or not access_token:
        return {}
    try:
        response = await _client().get(endpoint, headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
        data = response.json() if response.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def username_from(preferred: str) -> str:
    """Benutzername aus ``preferred_username``: bei einer Adresse oder UPN (Entra ID) nur der Teil vor dem @."""
    name = preferred.strip()
    if "@" in name:
        name = name.split("@", 1)[0]
    return re.sub(r"[^a-zA-Z0-9._-]", "-", name).strip("-.")[:56]


def redirect_uri(public_url: str, slug: str) -> str:
    base = public_url.rstrip("/")
    if not base:
        raise OidcError("oidc_no_public_url", "The public address is not set. Set it under Settings, System first.")
    return f"{base}{COOKIE_PATH}/{slug}/callback"
