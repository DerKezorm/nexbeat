"""Stand-ins for the outside world: an OpenID Connect provider, Microsoft Entra ID with ``common``, and authentik's
API v3, all answered through one ``httpx.MockTransport``. No test touches the network.

The providers sign with RSA keys generated here at import; every secret, client id and token is made at run time, so
nothing in the repository looks like a credential. The token endpoint checks code, PKCE verifier, redirect address and
client authentication as a real one would: whatever passes against it and is refused by the tampered variants is the
standard, not luck.

Shipped with the module's contract tests and used by its own tests; changed only in ``bauplaene/oidc``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, unquote_plus, urlencode, urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def _pem(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
SIGNING_PEM = _pem(SIGNING_KEY)
#: A key no provider publishes: a token signed with it is forged.
FOREIGN_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
FOREIGN_PEM = _pem(FOREIGN_KEY)
KID = "key-1"
#: Leave a claim out of a token: ``token_claims={"azp": DROP}``.
DROP = object()


def public_jwk(key: rsa.RSAPrivateKey = SIGNING_KEY, kid: str = KID) -> dict[str, Any]:
    entry = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    entry.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return entry


def made_up_secret() -> str:
    return secrets.token_urlsafe(24)


def sign(
    claims: dict[str, Any], *, key: bytes | str = SIGNING_PEM, algorithm: str = "RS256", kid: str | None = KID
) -> str:
    return jwt.encode(claims, key, algorithm=algorithm, headers={"kid": kid} if kid else None)


def query_of(url: str) -> dict[str, str]:
    return {name: values[0] for name, values in parse_qs(urlsplit(url).query).items()}


@dataclass
class Grant:
    client_id: str
    redirect_uri: str
    nonce: str
    challenge: str
    method: str
    claims: dict[str, Any]


class FakeProvider:
    """An OpenID Connect provider at ``issuer``. ``published`` is what its discovery calls itself (default: the
    issuer as written, slash and all, the way authentik writes it).

    The browser's visit is ``authorize(url)``: it reads what the app sent, remembers it under a fresh code and returns
    the query the provider sends the browser back with. ``person`` is who signs in; ``token_claims`` bends the next
    id token (``DROP`` removes a claim), ``token_key``/``token_algorithm``/``token_kid`` sign it differently,
    ``raw_token`` replaces it. ``userinfo`` chooses the userinfo answer: ``json``, ``signed``, ``signed-foreign``,
    ``other-subject``, ``error``, ``garbage``, ``none`` (no endpoint)."""

    def __init__(
        self,
        issuer: str = "https://sso.example.com",
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        auth_methods: list[str] | None = None,
        userinfo: str = "json",
    ) -> None:
        self.issuer = issuer
        self.base = issuer.rstrip("/")
        self.published = issuer
        self.client_id = client_id or f"client-{secrets.token_hex(4)}"
        self.client_secret = made_up_secret() if client_secret is None else client_secret
        self.auth_methods = auth_methods
        self.userinfo = userinfo
        self.userinfo_claims: dict[str, Any] = {}
        self.person: dict[str, Any] = {
            "sub": "person-1",
            "preferred_username": "alex",
            "name": "Alex Example",
            "email": "alex@example.com",
        }
        self.token_claims: dict[str, Any] = {}
        self.token_key: bytes | str = SIGNING_PEM
        self.token_algorithm = "RS256"
        self.token_kid: str | None = KID
        self.raw_token: str | None = None
        self.keys: list[dict[str, Any]] = [public_jwk()]
        self.reachable = True
        self.grants: dict[str, Grant] = {}
        self.token_calls: list[dict[str, Any]] = []
        self.userinfo_calls = 0

    # --- the browser's side ----------------------------------------------------------------------------------------
    @property
    def host(self) -> str:
        return urlsplit(self.base).netloc

    def authorize(self, url: str, *, error: str | None = None) -> dict[str, str]:
        """The browser at the authorization endpoint: the query of the way back to the app."""
        query = query_of(url)
        assert url.startswith(f"{self.base}/authorize?"), url
        assert query["response_type"] == "code" and query["client_id"] == self.client_id
        assert query["code_challenge_method"] == "S256" and "openid" in query["scope"].split()
        if error:
            return {"error": error, "error_description": "the person said no", "state": query["state"]}
        code = secrets.token_urlsafe(16)
        self.grants[code] = Grant(
            client_id=query["client_id"],
            redirect_uri=query["redirect_uri"],
            nonce=query["nonce"],
            challenge=query["code_challenge"],
            method=query["code_challenge_method"],
            claims=dict(self.person),
        )
        return {"code": code, "state": query["state"]}

    # --- what the provider publishes ---------------------------------------------------------------------------------
    def description(self, published: str) -> dict[str, Any]:
        data: dict[str, Any] = {
            "issuer": published,
            "authorization_endpoint": f"{self.base}/authorize",
            "token_endpoint": f"{self.base}/token",
            "jwks_uri": f"{self.base}/jwks",
        }
        if self.userinfo != "none":
            data["userinfo_endpoint"] = f"{self.base}/userinfo"
        if self.auth_methods is not None:
            data["token_endpoint_auth_methods_supported"] = self.auth_methods
        return data

    def discovery_answer(self, path: str) -> dict[str, Any] | None:
        """The document for a discovery path, or None when this provider has none there."""
        if path == urlsplit(self.base).path + "/.well-known/openid-configuration":
            return self.description(self.published)
        return None

    def token_issuer(self, claims: dict[str, Any]) -> str:
        return self.published

    def id_token(self, grant: Grant) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": "",
            "aud": grant.client_id,
            "exp": now + 300,
            "iat": now,
            "nonce": grant.nonce,
            **grant.claims,
        }
        claims["iss"] = self.token_issuer(claims)
        claims.update(self.token_claims)
        claims = {name: value for name, value in claims.items() if value is not DROP}
        return sign(claims, key=self.token_key, algorithm=self.token_algorithm, kid=self.token_kid)

    def _client_ok(self, request: httpx.Request, form: dict[str, str]) -> tuple[bool, str]:
        header = request.headers.get("authorization", "")
        if header.startswith("Basic "):
            # RFC 6749 2.3.1: id and secret arrive form-encoded inside the Basic header; a provider decodes them.
            try:
                pair = base64.b64decode(header[6:]).decode()
            except ValueError:
                return False, "client_secret_basic"
            user, _, password = pair.partition(":")
            self.basic_raw = pair
            ok = unquote_plus(user) == self.client_id and unquote_plus(password) == self.client_secret
            return ok, "client_secret_basic"
        if "client_secret" in form:
            ok = form.get("client_id") == self.client_id and form["client_secret"] == self.client_secret
            return ok, "client_secret_post"
        return form.get("client_id") == self.client_id and not self.client_secret, "none"

    def token(self, request: httpx.Request) -> httpx.Response:
        form = {name: values[0] for name, values in parse_qs(request.content.decode()).items()}
        ok, method = self._client_ok(request, form)
        self.token_calls.append({"method": method, "form": {k: v for k, v in form.items() if k != "client_secret"}})
        if self.auth_methods is not None and method != "none" and method not in self.auth_methods:
            return httpx.Response(401, json={"error": "invalid_client", "error_description": "method not allowed"})
        if not ok:
            return httpx.Response(401, json={"error": "invalid_client"})
        grant = self.grants.pop(form.get("code", ""), None)
        if grant is None or form.get("grant_type") != "authorization_code":
            return httpx.Response(400, json={"error": "invalid_grant"})
        if form.get("redirect_uri") != grant.redirect_uri:
            return httpx.Response(400, json={"error": "invalid_grant", "error_description": "redirect_uri"})
        digest = hashlib.sha256(form.get("code_verifier", "").encode()).digest()
        if base64.urlsafe_b64encode(digest).rstrip(b"=").decode() != grant.challenge:
            return httpx.Response(400, json={"error": "invalid_grant", "error_description": "pkce"})
        self._last_subject = grant.claims.get("sub")
        self._last_claims = grant.claims
        token = self.raw_token if self.raw_token is not None else self.id_token(grant)
        return httpx.Response(
            200, json={"id_token": token, "access_token": "at-" + secrets.token_hex(8), "token_type": "Bearer"}
        )

    def userinfo_answer(self) -> httpx.Response:
        self.userinfo_calls += 1
        claims = {**getattr(self, "_last_claims", self.person), **self.userinfo_claims}
        if self.userinfo == "error":
            return httpx.Response(500, text="broken")
        if self.userinfo == "garbage":
            return httpx.Response(200, text="<html>portal</html>", headers={"content-type": "text/html"})
        if self.userinfo == "other-subject":
            return httpx.Response(200, json={**claims, "sub": "somebody-else"})
        if self.userinfo in ("signed", "signed-foreign"):
            now = int(time.time())
            body = {**claims, "iss": self.token_issuer(claims), "aud": self.client_id, "iat": now}
            key = FOREIGN_PEM if self.userinfo == "signed-foreign" else SIGNING_PEM
            return httpx.Response(200, text=sign(body, key=key), headers={"content-type": "application/jwt"})
        return httpx.Response(200, json=claims)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if not self.reachable:
            raise httpx.ConnectError("provider down")
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            answer = self.discovery_answer(path)
            return httpx.Response(200, json=answer) if answer is not None else httpx.Response(404, text="not found")
        if path == urlsplit(self.base).path + "/jwks":
            return httpx.Response(200, json={"keys": self.keys})
        if path == urlsplit(self.base).path + "/token" and request.method == "POST":
            return self.token(request)
        if path == urlsplit(self.base).path + "/userinfo":
            return self.userinfo_answer()
        return httpx.Response(404, text="not found")


ENTRA = "https://login.microsoftonline.com"
ENTRA_PUBLISHED = f"{ENTRA}/{{tenantid}}/v2.0"
TENANT = "72f988bf-86f1-41af-91ab-2d7cd011db47"
OTHER_TENANT = "0e3e2e88-8caf-41ca-b4da-e3b33b6c52ec"


class FakeEntra(FakeProvider):
    """Microsoft Entra ID: the discovery under ``common`` and ``organizations`` names ``{tenantid}``; under a tenant
    id it names that tenant. Tokens carry ``tid`` and are issued by the tenant. The keys live under
    ``/common/discovery/v2.0/keys``."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(f"{ENTRA}/common/v2.0", **kwargs)
        self.published = ENTRA_PUBLISHED
        self.tenant = TENANT
        self.person = {
            "sub": "entra-subject-1",
            "preferred_username": "max@example.com",
            "name": "Max Example",
            "email": "max@example.com",
        }

    def description(self, published: str) -> dict[str, Any]:
        data = super().description(published)
        data.update(
            authorization_endpoint=f"{ENTRA}/common/oauth2/v2.0/authorize",
            token_endpoint=f"{ENTRA}/common/oauth2/v2.0/token",
            jwks_uri=f"{ENTRA}/common/discovery/v2.0/keys",
            userinfo_endpoint="https://graph.microsoft.com/oidc/userinfo",
        )
        return data

    def discovery_answer(self, path: str) -> dict[str, Any] | None:
        found = re.fullmatch(r"/([^/]+)/v2\.0/\.well-known/openid-configuration", path)
        if not found:
            return None
        segment = found.group(1)
        if segment in ("common", "organizations"):
            return self.description(self.published)
        return self.description(f"{ENTRA}/{segment}/v2.0")

    def authorize(self, url: str, *, error: str | None = None) -> dict[str, str]:
        assert url.startswith(f"{ENTRA}/common/oauth2/v2.0/authorize?"), url
        patched = url.replace(f"{ENTRA}/common/oauth2/v2.0/authorize", f"{self.base}/authorize")
        params = super().authorize(patched, error=error)
        if "code" in params:
            self.grants[params["code"]].claims.setdefault("tid", self.tenant)
        return params

    def token_issuer(self, claims: dict[str, Any]) -> str:
        return f"{ENTRA}/{claims.get('tid', self.tenant)}/v2.0"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "graph.microsoft.com":
            # Entra's userinfo lives at Graph and usually answers nothing that fits the app: planned for.
            return httpx.Response(401, json={"error": {"code": "InvalidAuthenticationToken"}})
        path = request.url.path
        if path == "/common/discovery/v2.0/keys":
            return httpx.Response(200, json={"keys": self.keys})
        if path == "/common/oauth2/v2.0/token" and request.method == "POST":
            return self.token(request)
        return super().__call__(request)

    @property
    def host(self) -> str:
        return "login.microsoftonline.com"


# ---------------------------------------------------------------------------
# authentik's API v3
# ---------------------------------------------------------------------------

AUTHENTIK = "https://auth.example.com"
MANAGED = (
    "goauthentik.io/providers/oauth2/scope-openid",
    "goauthentik.io/providers/oauth2/scope-email",
    "goauthentik.io/providers/oauth2/scope-profile",
)


@dataclass
class Call:
    method: str
    path: str
    query: dict[str, str]
    authorization: str
    body: Any


@dataclass
class FakeAuthentik:
    """authentik as a MockTransport handler, with state: providers and applications made through the API are there
    on the next call. ``token`` is made at run time; every other token is refused (403, or 401 for ``expired``).
    ``fail = (method, path, status)`` makes one call fail. ``page_size`` cuts lists to their first page.

    It also answers the discovery of ``<authentik>/application/o/<slug>/`` for every application with a provider,
    as authentik does, unless ``discovery_ok`` is False."""

    base: str = AUTHENTIK
    token: str = field(default_factory=made_up_secret)
    version: str = "2026.8.1"
    providers: list[dict[str, Any]] = field(default_factory=list)
    applications: list[dict[str, Any]] = field(default_factory=list)
    certificates: list[dict[str, Any]] = field(default_factory=list)
    bindings: list[dict[str, Any]] = field(default_factory=list)
    managed_mappings: tuple[str, ...] = MANAGED
    fail: tuple[str, str, int] | None = None
    discovery_ok: bool = True
    page_size: int | None = None
    calls: list[Call] = field(default_factory=list)
    user: dict[str, Any] = field(default_factory=lambda: {"pk": 4, "username": "owner"})
    #: authentik signing people in (``sign_in_with``): a FakeProvider behind authorize, token, keys and userinfo.
    signer: FakeProvider | None = None
    _next_pk: int = 40

    def sign_in_with(self, issuer: str, client_id: str, client_secret: str) -> FakeProvider:
        """Let this authentik sign people in for the application whose issuer is ``issuer`` (as authentik writes
        it, with the slash): the returned FakeProvider is the browser's side (``authorize``) and signs the tokens."""
        signer = FakeProvider(f"{self.base}/application/o", client_id=client_id, client_secret=client_secret)
        signer.published = issuer
        self.signer = signer
        return signer

    def _signer_paths(self) -> set[str]:
        return {f"/application/o/{name}" for name in ("authorize", "token", "jwks", "userinfo")}

    @property
    def host(self) -> str:
        return urlsplit(self.base).netloc

    # --- setting the scene -----------------------------------------------------------------------------------------
    def add_provider(
        self,
        name: str,
        redirect: str,
        *,
        client_id: str | None = None,
        slug: str | None = None,
        app_name: str | None = None,
    ) -> dict[str, Any]:
        """A provider already there, with its application under ``slug`` (None: without one)."""
        provider = {
            "pk": self._pk(),
            "name": name,
            "client_id": client_id or f"cid-{secrets.token_hex(6)}",
            "client_secret": made_up_secret(),
            "redirect_uris": [{"matching_mode": "strict", "url": redirect}],
        }
        self.providers.append(provider)
        if slug is not None:
            self.applications.append(
                {"pk": f"app-{self._pk()}", "slug": slug, "name": app_name or name, "provider": provider["pk"]}
            )
        return provider

    def add_application(self, slug: str, name: str, provider: int | None) -> dict[str, Any]:
        application = {"pk": f"app-{self._pk()}", "slug": slug, "name": name, "provider": provider}
        self.applications.append(application)
        return application

    def provider_named(self, name: str) -> dict[str, Any] | None:
        return next((entry for entry in self.providers if entry["name"] == name), None)

    def application(self, slug: str) -> dict[str, Any] | None:
        return next((entry for entry in self.applications if entry["slug"] == slug), None)

    def _pk(self) -> int:
        self._next_pk += 1
        return self._next_pk

    # --- the API ---------------------------------------------------------------------------------------------------
    def __call__(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        query = dict(request.url.params.items())
        if self.signer is not None and path in self._signer_paths():
            return self.signer(request)
        body = json.loads(request.content) if request.content else None
        self.calls.append(Call(method, path, query, request.headers.get("authorization", ""), body))
        if self.fail and (method, path) == self.fail[:2]:
            return httpx.Response(
                self.fail[2], text="<html>authentik error page</html>", headers={"content-type": "text/html"}
            )
        found = re.fullmatch(r"/application/o/([^/]+)/\.well-known/openid-configuration", path)
        if found:
            application = self.application(found.group(1))
            if not self.discovery_ok or application is None or application["provider"] is None:
                return httpx.Response(404, text="not found")
            issuer = f"{self.base}/application/o/{found.group(1)}/"
            return httpx.Response(
                200,
                json={
                    "issuer": issuer,
                    "authorization_endpoint": f"{self.base}/application/o/authorize",
                    "token_endpoint": f"{self.base}/application/o/token",
                    "jwks_uri": f"{self.base}/application/o/jwks",
                    "userinfo_endpoint": f"{self.base}/application/o/userinfo",
                },
            )
        if not path.startswith("/api/v3/"):
            return httpx.Response(404, text="not found")
        authorization = request.headers.get("authorization", "")
        if authorization == "Bearer expired":
            return httpx.Response(401, json={"detail": "Token invalid/expired"})
        if authorization != f"Bearer {self.token}":
            return httpx.Response(403, json={"detail": "Authentication credentials were not provided."})
        return self._api(method, path[len("/api/v3") :], query, body)

    def _list(self, rows: list[dict[str, Any]]) -> httpx.Response:
        return httpx.Response(200, json={"pagination": {"count": len(rows)}, "results": rows[: self.page_size]})

    def _provider_view(self, provider: dict[str, Any]) -> dict[str, Any]:
        assigned = next((app for app in self.applications if app["provider"] == provider["pk"]), None)
        return {
            **provider,
            "assigned_application_slug": assigned["slug"] if assigned else "",
            "assigned_application_name": assigned["name"] if assigned else "",
        }

    def _api(self, method: str, path: str, query: dict[str, str], body: Any) -> httpx.Response:
        if (method, path) == ("GET", "/admin/version/"):
            return httpx.Response(200, json={"version_current": self.version})
        if (method, path) == ("GET", "/core/users/me/"):
            return httpx.Response(200, json={"user": self.user})
        if (method, path) == ("GET", "/crypto/certificatekeypairs/"):
            return self._list([row for row in self.certificates if row["name"] == query.get("name", row["name"])])
        if (method, path) == ("POST", "/crypto/certificatekeypairs/generate/"):
            row = {"pk": f"cert-{self._pk()}", "name": body["common_name"], **body}
            self.certificates.append(row)
            return httpx.Response(200, json=row)
        if (method, path) == ("GET", "/propertymappings/provider/scope/"):
            rows = [
                {"pk": f"map-{name.rsplit('-', 1)[1]}", "managed": name, "name": name} for name in self.managed_mappings
            ]
            if "managed" in query:
                rows = [row for row in rows if row["managed"] == query["managed"]]
            return self._list(rows)
        if (method, path) == ("GET", "/flows/instances/"):
            if query.get("designation") == "authorization":
                return self._list(
                    [
                        {"pk": "flow-explicit", "slug": "default-provider-authorization-explicit-consent"},
                        {"pk": "flow-implicit", "slug": "default-provider-authorization-implicit-consent"},
                    ]
                )
            return self._list([{"pk": "flow-invalidation", "slug": "default-provider-invalidation-flow"}])
        if (method, path) == ("GET", "/providers/oauth2/"):
            rows = [self._provider_view(row) for row in self.providers]
            for key in ("name", "client_id"):
                if key in query:
                    rows = [row for row in rows if row[key] == query[key]]
            return self._list(rows)
        if (method, path) == ("POST", "/providers/oauth2/"):
            provider = {
                **body,
                "pk": self._pk(),
                "client_id": f"cid-{secrets.token_hex(6)}",
                "client_secret": made_up_secret(),
            }
            self.providers.append(provider)
            return httpx.Response(201, json=self._provider_view(provider))
        found = re.fullmatch(r"/providers/oauth2/(\d+)/", path)
        if found and method == "PATCH":
            provider = next((row for row in self.providers if row["pk"] == int(found.group(1))), None)
            if provider is None:
                return httpx.Response(404, json={"detail": "Not found."})
            provider.update(body)
            return httpx.Response(200, json=self._provider_view(provider))
        if (method, path) == ("GET", "/core/applications/"):
            # authentik lists only what the token's user may open unless asked for the full list; it filters by
            # slug, never by provider (an unknown filter is ignored).
            if query.get("superuser_full_list") != "true":
                return self._list([])
            rows = list(self.applications)
            if "slug" in query:
                rows = [row for row in rows if row["slug"] == query["slug"]]
            return self._list(rows)
        if (method, path) == ("POST", "/core/applications/"):
            if self.application(body["slug"]) is not None:
                return httpx.Response(400, json={"slug": ["Application with this slug already exists."]})
            if len(body["slug"]) > 50:
                return httpx.Response(400, json={"slug": ["Ensure this field has no more than 50 characters."]})
            application = {"pk": f"app-{self._pk()}", **body}
            self.applications.append(application)
            return httpx.Response(201, json=application)
        found = re.fullmatch(r"/core/applications/([^/]+)/", path)
        if found and method == "PATCH":
            application = self.application(found.group(1))
            if application is None:
                return httpx.Response(404, json={"detail": "Not found."})
            application.update(body)
            return httpx.Response(200, json=application)
        if (method, path) == ("GET", "/policies/bindings/"):
            return self._list([row for row in self.bindings if str(row["target"]) == query.get("target")])
        if (method, path) == ("POST", "/policies/bindings/"):
            row = {"pk": str(uuid.uuid4()), **body}
            self.bindings.append(row)
            return httpx.Response(201, json=row)
        return httpx.Response(404, json={"detail": f"no fake answer for {method} {path}"})


class Network:
    """One MockTransport handler for several fakes, chosen by host. An unknown host cannot be reached."""

    def __init__(self, *fakes: Any) -> None:
        self.fakes = list(fakes)

    def add(self, fake: Any) -> Any:
        self.fakes.append(fake)
        return fake

    def __call__(self, request: httpx.Request) -> httpx.Response:
        netloc = request.url.netloc
        netloc = netloc.decode("ascii") if isinstance(netloc, bytes) else netloc
        for fake in self.fakes:
            hosts = {fake.host} | ({"graph.microsoft.com"} if isinstance(fake, FakeEntra) else set())
            if netloc in hosts:
                return fake(request)
        raise httpx.ConnectError(f"no such host {request.url.host}")

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def callback_query(params: dict[str, str]) -> str:
    return urlencode(params)
