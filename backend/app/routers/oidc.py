"""Anmelden ueber OpenID Connect, das eigene Konto verknuepfen, die Anbieter verwalten, der authentik-Knopf.

Der Ablauf selbst steht im gemeinsamen Modul ``app.vendor.nexoidc``,
hier nur, was nexbeat dazugibt: Sitzung, Bremse, Passwort, Rechte und die Antworten. Pfade:

| Methode | Pfad | Wer |
|---|---|---|
| GET | ``/api/oidc/providers`` | alle: Kurzname und Name der aktiven Anbieter (Anmelde- und Einladungsseite) |
| GET, POST | ``/api/oidc/admin/providers`` | Admin: die Liste, einen anlegen |
| PUT, DELETE | ``/api/oidc/admin/providers/{id}`` | Admin: speichern, entfernen |
| GET | ``/api/oidc/admin/providers/{id}/impact?issuer=`` | Admin: Zahlen fuer die beiden Rueckfragen |
| PUT | ``/api/oidc/admin/providers/order`` | Admin: Reihenfolge |
| GET | ``/api/oidc/{slug}/start[?invite=]`` | alle: zum Anbieter |
| GET | ``/api/oidc/{slug}/callback`` | alle: zurueck vom Anbieter |
| GET | ``/api/auth/oidc/{slug}/callback`` | alle: dasselbe fuer die Anbieter aus 1.3.0 (``redirect_path``) |
| GET | ``/api/oidc/me`` | angemeldet: die aktiven Anbieter mit ``linked`` |
| POST, DELETE | ``/api/oidc/{slug}/link`` | angemeldet im Browser: verknuepfen (mit Passwort), loesen |
| DELETE | ``/api/oidc/admin/accounts/{konto}/links/{anbieter}`` | Admin, mit eigenem Passwort |
| POST | ``/api/oidc/authentik/setup`` | Admin: der Knopf, immer 200 |
| GET, POST | ``/api/oidc/authentik/address`` | Admin: was die authentik-Karte zur Adresse zeigt; "Nur uebernehmen" |
| GET | ``/api/oidc/authentik/blueprint`` | Admin: ``nexbeat-authentik.yaml`` |

⚠️ Die Rueckkehr ist eine Weiterleitung des Browsers ohne ``Authorization``-Kopf. Wer dort angemeldet ist, sagt das
Sitzungs-Cookie ``nexbeat_refresh``; es liegt deshalb seit dieser Fassung unter ``/api`` (``sitzung.COOKIE_PATH``).
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import AdminUser, DbSession, SessionUser
from ..meldungen import fehler
from ..models import OidcLink, OidcProvider, User, utcnow
from ..security import decode_token, has_usable_password, verify_password
from ..services import anmeldebremse, sitzung
from ..services.oidc_store import SqlStore
from ..vendor.nexoidc import OidcError, ProviderInvalid, accounts, authentik, flow, providers
from ..vendor.nexoidc.attempt import read as read_attempt
from ..vendor.nexoidc.config import current

router = APIRouter(tags=["oidc"])
logger = logging.getLogger("nexbeat.oidc")

API = "/api"


class ProviderIn(BaseModel):
    label: str = Field(max_length=200)
    slug: str = Field(default="", max_length=100)
    issuer: str = Field(max_length=600)
    client_id: str = Field(max_length=300)
    client_secret: str = Field(default="", max_length=2000)
    scopes: str = Field(default="openid profile email", max_length=500)
    enabled: bool = True
    auto_create: bool = False
    trusts_second_factor: bool = True


class PasswordIn(BaseModel):
    password: str = Field(default="", max_length=200)


class SetupIn(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    token: str = Field(min_length=1, max_length=2000)
    confirm_issuer_change: bool = False
    #: Die Adresse, die der Betreiber in der Karte bestaetigt hat (die des Browsers), solange nexbeat keine hat.
    public_url: str = Field(default="", max_length=600)


class AddressIn(BaseModel):
    public_url: str = Field(max_length=600)
    confirm: bool = False


class OrderIn(BaseModel):
    ids: list[int] = Field(max_length=200)


def _form_error(error: ProviderInvalid) -> Any:
    return fehler(error.code, error.message, 422, field=error.field)


def _admin_view(store: SqlStore, entry: Any, request: Request) -> dict[str, Any]:
    return providers.admin_view(entry, str(request.base_url), len(store.links_of_provider(entry.id)))


# -- Bremse und Sitzung --------------------------------------------------------


def sender(request: Request) -> str:
    """Wer fragt: die Adresse, die uvicorn als Absender nennt (hinter einem vertrauten Proxy der Besucher)."""
    return request.client.host if request.client else "?"


def braked(request: Request) -> bool:
    return anmeldebremse.wait_seconds(anmeldebremse.oidc_key(sender(request))) > 0


def session_user(request: Request, db: Session) -> User | None:
    """Das Konto der Browsersitzung (Cookie ``nexbeat_refresh``), wie ``/api/auth/refresh`` es pruefte."""
    raw = sitzung.read(request)
    content = decode_token(raw, "refresh") if raw else None
    if raw is None or content is None:
        return None
    user = db.get(User, content.user_id)
    if user is None or not user.is_active or not sitzung.still_valid(content, user):
        return None
    return None if sitzung.revoked(db, raw, content) else user


def _to_response(redirect: flow.Redirect) -> RedirectResponse:
    response = RedirectResponse(redirect.location, status_code=303)
    _cookie(response, redirect.cookie)
    return response


def _cookie(response: Response, cookie: flow.Cookie) -> None:
    if cookie.max_age == 0:
        response.delete_cookie(cookie.name, path=cookie.path, secure=cookie.secure, httponly=True, samesite="lax")
    else:
        response.set_cookie(
            cookie.name,
            cookie.value,
            max_age=cookie.max_age,
            path=cookie.path,
            httponly=cookie.http_only,
            samesite="lax",
            secure=cookie.secure,
        )


# -- Oeffentlich: Anbieter, Start, Rueckkehr ------------------------------------


@router.get(f"{API}/oidc/providers", summary="The active sign-in providers, for the sign-in and invitation pages")
def public_providers_route(db: DbSession) -> list[dict[str, str]]:
    return providers.public_list(SqlStore(db))


def public_providers(db: Session) -> list[dict[str, str]]:
    return providers.public_list(SqlStore(db))


@router.get(f"{API}/oidc/{{slug}}/start", summary="Start a sign-in at an identity provider")
async def start(slug: str, request: Request, db: DbSession, invite: str | None = None) -> RedirectResponse:
    store = SqlStore(db)
    try:
        if braked(request):
            raise OidcError("too_many_attempts", "sender is braked")
        redirect = await flow.begin(store, slug, request_base=str(request.base_url), invite=invite)
    except OidcError as error:
        return _to_response(flow.refused(error, None))
    return _to_response(redirect)


async def _returned(slug: str, request: Request, db: Session) -> RedirectResponse:
    cookie = request.cookies.get(current().cookie_name)
    store = SqlStore(db)
    try:
        if braked(request):
            raise OidcError("too_many_attempts", "sender is braked")
        arrival = await flow.finish(store, slug, cookie=cookie, params=dict(request.query_params))
        if arrival.started.purpose == "link":
            account = session_user(request, db)
            accounts.link(store, arrival, account.id if account else None)
            return _to_response(flow.arrived(arrival, flow.linked_page(slug)))
        signed = accounts.sign_in(store, arrival)
    except OidcError as error:
        # ⚠️ Nur eine Rueckkehr mit gueltigem Anlauf-Cookie zaehlt fuer die Bremse. Sonst sperrte jeder mit
        # ``?error=``, einem erfundenen Kurznamen oder Muell alle anderen hinter demselben Proxy aus.
        if error.code not in ("oidc_state_mismatch", "too_many_attempts") and read_attempt(cookie) is not None:
            anmeldebremse.failed(anmeldebremse.oidc_key(sender(request)))
        return _to_response(flow.refused(error, cookie))
    user = db.get(User, signed.account_id)
    if user is None or not user.is_active:
        return _to_response(flow.refused(OidcError("account_blocked", "account gone or blocked"), cookie))
    user.last_login_at = utcnow()
    db.commit()
    response = _to_response(flow.arrived(arrival))
    sitzung.remember_device(response, request, user)
    sitzung.start(response, request, user)
    return response


@router.get(f"{API}/oidc/callback", summary="Return from the provider of the entry oidc")
async def legacy_callback(request: Request, db: DbSession) -> RedirectResponse:
    return await _returned("oidc", request, db)


@router.get(f"{API}/auth/oidc/{{slug}}/callback", summary="Return from a provider set up in nexbeat 1.3.0")
async def old_callback(slug: str, request: Request, db: DbSession) -> RedirectResponse:
    """Die Adresse, die die Anbieter aus nexbeat 1.3.0 kennen (``redirect_path`` ihres Eintrags)."""
    return await _returned(slug, request, db)


@router.get(f"{API}/oidc/{{slug}}/callback", summary="Return from the identity provider")
async def callback(slug: str, request: Request, db: DbSession) -> RedirectResponse:
    return await _returned(slug, request, db)


# -- Mein Konto ----------------------------------------------------------------


@router.get(f"{API}/oidc/me", summary="The active providers and whether this account is linked to each")
def my_providers(user: SessionUser, db: DbSession) -> list[dict[str, Any]]:
    store = SqlStore(db)
    linked = {link.provider_id for link in store.links_of_account(user.id)}
    return [
        {"slug": entry.slug, "label": entry.label, "linked": entry.id in linked}
        for entry in store.list_providers()
        if entry.enabled
    ]


@router.post(f"{API}/oidc/{{slug}}/link", summary="Start linking this account; the password confirms it")
async def link_start(
    slug: str, payload: PasswordIn, request: Request, user: SessionUser, db: DbSession
) -> JSONResponse:
    """Antwortet mit der Adresse, zu der es geht, und setzt dabei das Anlauf-Cookie.

    Ein POST mit Zugangs-Token und Passwort, kein Link: So stoesst keine fremde Seite eine Verknuepfung an.
    """
    if braked(request):
        raise fehler("too_many_attempts", "Too many attempts. Try again later.", 429)
    key = anmeldebremse.password_change_key(user.id)
    if anmeldebremse.wait_seconds(key):
        raise fehler("too_many_attempts", "Too many wrong passwords. Try again later.", 429)
    if not has_usable_password(user.password_hash) or not verify_password(payload.password, user.password_hash):
        anmeldebremse.failed(key)
        raise fehler("wrong_password", "The password is wrong.", 400)
    anmeldebremse.succeeded(key)
    try:
        redirect = await flow.begin(SqlStore(db), slug, request_base=str(request.base_url), link_account_id=user.id)
    except OidcError as error:
        raise fehler(error.code, error.message, 409) from error
    response = JSONResponse({"url": redirect.location})
    _cookie(response, redirect.cookie)
    return response


@router.delete(f"{API}/oidc/{{slug}}/link", status_code=204, summary="Undo the link to an identity provider")
def link_remove(slug: str, user: SessionUser, db: DbSession) -> None:
    store = SqlStore(db)
    entry = store.provider_by_slug(slug)
    if entry is None:
        raise fehler("oidc_not_configured", "This provider is not set up.", 404)
    try:
        accounts.unlink(store, user.id, entry.id)
    except OidcError as error:
        raise fehler(error.code, error.message, 409) from error


@router.delete(
    f"{API}/oidc/admin/accounts/{{account_id}}/links/{{provider_id}}",
    status_code=204,
    summary="Remove an account's link, with the administrator's own password",
)
def operator_unlink(account_id: int, provider_id: int, payload: PasswordIn, admin: AdminUser, db: DbSession) -> None:
    key = anmeldebremse.password_change_key(admin.id)
    if anmeldebremse.wait_seconds(key):
        raise fehler("too_many_attempts", "Too many wrong passwords. Try again later.", 429)
    if not has_usable_password(admin.password_hash) or not verify_password(payload.password, admin.password_hash):
        anmeldebremse.failed(key)
        raise fehler("wrong_password", "The password is wrong.", 400)
    anmeldebremse.succeeded(key)
    try:
        accounts.unlink(SqlStore(db), account_id, provider_id)
    except OidcError as error:
        raise fehler(error.code, error.message, 409) from error
    logger.info("Link of account %s to provider %s removed by=%s", account_id, provider_id, admin.username)


# -- Anbieterliste -------------------------------------------------------------


@router.get(f"{API}/oidc/admin/providers", summary="The sign-in providers, never a secret")
def admin_providers(request: Request, _admin: AdminUser, db: DbSession) -> list[dict[str, Any]]:
    store = SqlStore(db)
    return [_admin_view(store, entry, request) for entry in store.list_providers()]


@router.post(f"{API}/oidc/admin/providers", status_code=201, summary="Add a sign-in provider")
async def add_provider(payload: ProviderIn, request: Request, _admin: AdminUser, db: DbSession) -> dict[str, Any]:
    store = SqlStore(db)
    try:
        created = await providers.create(store, providers.Form(**payload.model_dump()))
    except ProviderInvalid as error:
        raise _form_error(error) from error
    return providers.admin_view(created, str(request.base_url), 0)


@router.put(f"{API}/oidc/admin/providers/order", summary="Put the sign-in buttons in order")
def order(payload: OrderIn, _admin: AdminUser, db: DbSession) -> list[dict[str, str]]:
    store = SqlStore(db)
    providers.reorder(store, payload.ids)
    return providers.public_list(store)


@router.put(f"{API}/oidc/admin/providers/{{provider_id}}", summary="Save a sign-in provider")
async def save_provider(
    provider_id: int, payload: ProviderIn, request: Request, _admin: AdminUser, db: DbSession
) -> dict[str, Any]:
    store = SqlStore(db)
    try:
        saved, dropped = await providers.update(store, provider_id, providers.Form(**payload.model_dump()))
    except ProviderInvalid as error:
        raise _form_error(error) from error
    return {**_admin_view(store, saved, request), "dropped": dropped}


@router.get(f"{API}/oidc/admin/providers/{{provider_id}}/impact", summary="Numbers for the two confirmations")
def impact(provider_id: int, _admin: AdminUser, db: DbSession, issuer: str = "") -> dict[str, Any]:
    store = SqlStore(db)
    if store.get_provider(provider_id) is None:
        raise fehler("provider_unknown", "This provider no longer exists.", 404)
    removal = providers.removal_impact(store, provider_id)
    change = providers.issuer_change_impact(store, provider_id, issuer) if issuer else 0
    return {"issuer_change": change, **asdict(removal)}


@router.delete(f"{API}/oidc/admin/providers/{{provider_id}}", summary="Remove a sign-in provider and its links")
def remove_provider(provider_id: int, _admin: AdminUser, db: DbSession) -> dict[str, Any]:
    try:
        return asdict(providers.remove(SqlStore(db), provider_id))
    except ProviderInvalid as error:
        raise _form_error(error) from error


# -- authentik -----------------------------------------------------------------


@router.post(f"{API}/oidc/authentik/setup", summary="Set up provider and application in authentik with a token")
async def authentik_setup(payload: SetupIn, request: Request, admin: AdminUser, db: DbSession) -> dict[str, Any]:
    """⚠️ Das Token gilt nur fuer diesen Lauf: nicht gespeichert, nicht protokolliert, nicht zurueckgegeben."""
    logger.info("authentik setup started by=%s", admin.username)
    result = await authentik.setup(
        SqlStore(db),
        payload.url,
        payload.token,
        str(request.base_url),
        confirm_issuer_change=payload.confirm_issuer_change,
        public_url=payload.public_url,
        headers=request.headers,
    )
    return result.as_dict()


@router.get(f"{API}/oidc/authentik/address", summary="What the authentik card shows about the public address")
def authentik_address(request: Request, _admin: AdminUser, db: DbSession) -> dict[str, Any]:
    return authentik.address_view(SqlStore(db), str(request.base_url), request.headers)


@router.post(f"{API}/oidc/authentik/address", summary="Save the public address the authentik card suggests")
def authentik_save_address(payload: AddressIn, request: Request, _admin: AdminUser, db: DbSession) -> dict[str, Any]:
    try:
        return authentik.save_public_url(
            SqlStore(db), payload.public_url, str(request.base_url), confirm=payload.confirm
        )
    except ValueError as error:
        raise fehler("public_url_invalid", "This is not a usable public address.", 422) from error
    except authentik.PublicUrlChange as asked:
        raise fehler("public_url_change", "Saving changes the redirect addresses.", 409, **asked.question) from asked
    except authentik.PublicUrlNotKept as error:
        raise fehler("public_url_needed", "The public address could not be stored.", 409) from error


@router.get(f"{API}/oidc/authentik/blueprint", summary="A blueprint that creates the same objects in authentik")
def authentik_blueprint(request: Request, _admin: AdminUser, db: DbSession) -> Response:
    try:
        redirect = authentik.blueprint_redirect(SqlStore(db), str(request.base_url))
    except authentik.PublicUrlNeeded as error:
        raise fehler("public_url_needed", "Set the public address first.", 409) from error
    name = authentik.blueprint_filename()
    return Response(
        authentik.blueprint(redirect),
        media_type="application/yaml",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# -- Fuer andere Router ----------------------------------------------------------


def links_by_account(db: Session) -> dict[int, list[dict[str, Any]]]:
    """Je Konto die Anbieter, mit denen es verknuepft ist (Marken in der Kontenliste)."""
    labels = {row.id: (row.slug, row.label) for row in db.scalars(select(OidcProvider))}
    result: dict[int, list[dict[str, Any]]] = {}
    for link in db.scalars(select(OidcLink).order_by(OidcLink.provider_id)):
        slug, label = labels.get(link.provider_id, ("", ""))
        result.setdefault(link.account_id, []).append({"id": link.provider_id, "slug": slug, "label": label})
    return result


def any_active_provider(db: Session) -> bool:
    return any(entry.enabled for entry in SqlStore(db).list_providers())
