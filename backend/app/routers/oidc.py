"""Anmelden ueber OpenID Connect, das eigene Konto verknuepfen und die Anbieter verwalten.

Gebaut wie in nexdeck. Anmeldung und Ruecksprung liegen unter ``/api/auth``, damit das Sitzungs-Cookie
(Pfad ``/api/auth``) im Ruecksprung gesetzt werden kann. Jeder Ausgang des Ruecksprungs ist eine
Weiterleitung in die Oberflaeche mit einer Kennung in der Adresse, nie JSON.
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import __version__
from ..crypto import decrypt, encrypt
from ..deps import AdminUser, DbSession, SessionUser
from ..meldungen import fehler
from ..models import OidcLink, OidcProvider, User, utcnow
from ..schemas import AuthentikSetupIn, OidcProviderIn
from ..security import UNUSABLE_PASSWORD, has_usable_password
from ..services import authentik_setup, oidc, sitzung
from ..services.settings_service import load_settings
from ..services.tokens import normalize_email

router = APIRouter(tags=["oidc"])
logger = logging.getLogger("nexbeat.oidc")

#: Wohin ein Verknuepfungsversuch zurueckfuehrt, mit ``oidc_linked`` oder ``oidc_error`` in der Adresse.
PROFILE_PAGE = "/profil"
LOGIN_PAGE = "/login"
#: Ersatzadresse fuer Konten, deren Anbieter keine (oder eine schon vergebene) Adresse nennt. ``.invalid``
#: ist reserviert und kann nie zugestellt werden.
PLACEHOLDER_DOMAIN = "oidc.invalid"
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _enabled_provider(db: Session, slug: str) -> OidcProvider:
    provider = db.scalar(select(OidcProvider).where(OidcProvider.slug == slug, OidcProvider.enabled.is_(True)))
    if provider is None:
        raise fehler("oidc_unknown_provider", "There is no such sign-in provider.", 404)
    return provider


def _to_app(path: str, **params: str) -> RedirectResponse:
    query = "&".join(f"{key}={value}" for key, value in params.items())
    return RedirectResponse(f"{path}{'?' + query if query else ''}", status_code=303)


def _redirect_uri(db: Session, slug: str) -> str:
    return oidc.redirect_uri(load_settings(db).public_url, slug)


def _attempt_cookie(response: RedirectResponse | JSONResponse, request: Request, value: str) -> None:
    response.set_cookie(
        oidc.COOKIE_NAME,
        value,
        max_age=oidc.ATTEMPT_MINUTES * 60,
        path=oidc.COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=sitzung.cookie_secure(request),
    )


def _drop_attempt(response: RedirectResponse) -> RedirectResponse:
    response.delete_cookie(oidc.COOKIE_NAME, path=oidc.COOKIE_PATH)
    return response


# -- Anmelden ----------------------------------------------------------------


@router.get("/api/auth/oidc/{slug}/login", summary="Start a sign-in at an identity provider")
async def oidc_login(slug: str, request: Request, db: DbSession) -> RedirectResponse:
    provider = _enabled_provider(db, slug)
    try:
        document = await oidc.discovery(provider.issuer_url)
        redirect = _redirect_uri(db, slug)
    except oidc.OidcError as failure:
        logger.warning("OIDC sign-in via %r could not start: %s", slug, failure.message)
        return _to_app(LOGIN_PAGE, oidc_error=failure.code)
    attempt = oidc.new_attempt()
    response = RedirectResponse(
        oidc.authorization_url(document, provider.client_id, redirect, provider.scopes, attempt), status_code=302
    )
    _attempt_cookie(response, request, oidc.pack_state(slug, attempt))
    return response


def _free_username(db: Session, wanted: str, subject: str) -> str | None:
    """Ein freier Benutzername aus dem Wunsch des Anbieters, notfalls mit Zusatz."""
    base = wanted if len(wanted) >= 3 else f"user-{re.sub(r'[^a-zA-Z0-9]', '', subject)[:8] or 'oidc'}"
    candidate = base

    def taken(name: str) -> bool:
        return db.scalar(select(User.id).where(func.lower(User.username) == name.lower())) is not None

    number = 2
    while taken(candidate):
        candidate = f"{base[:56]}-{number}"
        number += 1
        if number > 50:
            return None
    return candidate


def _address_for(db: Session, claimed: str, username: str) -> str | None:
    """Die Adresse fuers neue Konto. ``None``: Ein anderes Konto hat sie schon.

    ⚠️ Ein vorhandenes Konto mit derselben Adresse wird **nicht** uebernommen. Wer es hat, meldet sich mit
    Passwort an und verknuepft es unter Profil.
    """
    address = normalize_email(claimed)
    if not EMAIL_PATTERN.match(address) or len(address) > 255:
        return f"{username.lower()}@{PLACEHOLDER_DOMAIN}"
    if db.scalar(select(User.id).where(User.email == address)) is not None:
        return None
    return address


@router.get("/api/auth/oidc/{slug}/callback", summary="Return from the identity provider")
async def oidc_callback(slug: str, request: Request, db: DbSession) -> RedirectResponse:
    provider = _enabled_provider(db, slug)
    attempt = oidc.unpack_state(request.cookies.get(oidc.COOKIE_NAME))
    linking = attempt is not None and attempt.get("purpose") == "link"

    def refuse(code: str, reason: str) -> RedirectResponse:
        logger.warning("OIDC callback refused for %r: %s", slug, reason)
        return _drop_attempt(_to_app(PROFILE_PAGE if linking else LOGIN_PAGE, oidc_error=code))

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if request.query_params.get("error"):
        return refuse("oidc_denied", f"provider returned {request.query_params.get('error')!r}")
    if attempt is None or attempt.get("slug") != slug or not code or not state or attempt.get("state") != state:
        return refuse("oidc_state_mismatch", "state or cookie does not match the running attempt")
    try:
        document = await oidc.discovery(provider.issuer_url)
        redirect = _redirect_uri(db, slug)
        secret = decrypt(provider.client_secret) if provider.client_secret else ""
        tokens = await oidc.exchange(document, provider.client_id, secret, redirect, code, str(attempt["verifier"]))
        id_token = tokens.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise oidc.OidcError("oidc_bad_token", "The provider sent no ID token.")
        payload = await oidc.claims(document, provider.client_id, id_token, str(attempt["nonce"]), provider.issuer_url)
        info = await oidc.userinfo(document, str(tokens.get("access_token") or ""))
    except oidc.OidcError as failure:
        return refuse(failure.code, failure.message)
    subject = str(payload.get("sub") or "")
    if not subject:
        # ⚠️ Ohne diese Pruefung waere die leere Zeichenkette der Schluessel der Identitaet, und die zweite
        # Person ohne ``sub`` kaeme ins Konto der ersten.
        return refuse("oidc_bad_token", "the ID token has no subject")
    claimed = str(payload.get("email") or info.get("email") or "")
    if linking:
        return _finish_link(db, provider, attempt, subject, claimed, refuse)

    link = db.scalar(select(OidcLink).where(OidcLink.provider_id == provider.id, OidcLink.subject == subject))
    if link is not None:
        user = db.get(User, link.user_id)
    else:
        if not provider.auto_create:
            return refuse("oidc_no_account", "no linked account and creating accounts is off")
        preferred = str(payload.get("preferred_username") or info.get("preferred_username") or claimed or "")
        username = _free_username(db, oidc.username_from(preferred), subject)
        if username is None:
            return refuse("oidc_name_taken", "no free user name could be made from the provider's claims")
        address = _address_for(db, claimed, username)
        if address is None:
            return refuse("oidc_email_taken", "an account with this address exists; it has to be linked under Profile")
        display = str(payload.get("name") or info.get("name") or username)
        user = User(
            username=username,
            email=address,
            password_hash=UNUSABLE_PASSWORD,
            role=provider.default_role,
            display_name=display.strip()[:128],
            seen_version=__version__,
        )
        db.add(user)
        db.flush()
        db.add(OidcLink(provider_id=provider.id, user_id=user.id, subject=subject[:300], email=claimed[:300]))
        db.commit()
        logger.info("OIDC created the account %r via %r.", user.username, slug)
    if user is None or not user.is_active:
        return refuse("oidc_disabled", "the linked account is disabled or gone")
    user.last_login_at = utcnow()
    db.commit()
    response = _drop_attempt(_to_app("/"))
    sitzung.remember_device(response, request, user)
    sitzung.start(response, request, user)
    logger.info("%s signed in via %r.", user.username, slug)
    return response


def _finish_link(
    db: Session, provider: OidcProvider, attempt: dict, subject: str, email: str, refuse
) -> RedirectResponse:
    """Die Identitaet an das Konto haengen, das darum gebeten hat, statt jemanden anzumelden.

    ⚠️ Nur so, nie ueber die Adresse: Bei authentik kann jeder seine Adresse selbst aendern, und wer die des
    Admins eintraegt, kaeme sonst in dessen Konto.
    """
    user = db.get(User, int(attempt.get("user_id") or 0))
    if user is None or not user.is_active:
        return refuse("oidc_disabled", "the account that asked to link is disabled or gone")
    taken = db.scalar(select(OidcLink).where(OidcLink.provider_id == provider.id, OidcLink.subject == subject))
    if taken is not None and taken.user_id != user.id:
        return refuse("oidc_taken", f"that identity is linked to another account already (user id {taken.user_id})")
    if taken is None:
        # Eine Identitaet je Anbieter und Konto: erneut verknuepfen ersetzt die alte.
        for old in db.scalars(select(OidcLink).where(OidcLink.provider_id == provider.id, OidcLink.user_id == user.id)):
            db.delete(old)
        db.add(OidcLink(provider_id=provider.id, user_id=user.id, subject=subject[:300], email=email[:300]))
        db.commit()
    logger.info("%s linked their account to %r.", user.username, provider.slug)
    return _drop_attempt(_to_app(PROFILE_PAGE, oidc_linked=provider.slug))


# -- Eigene Verknuepfungen -----------------------------------------------------


@router.get("/api/oidc/links", summary="The sign-in providers and whether this account is linked to each")
def my_links(user: SessionUser, db: DbSession) -> list[dict]:
    linked = {link.provider_id for link in db.scalars(select(OidcLink).where(OidcLink.user_id == user.id))}
    return [
        {"slug": provider.slug, "label": provider.label, "linked": provider.id in linked}
        for provider in db.scalars(select(OidcProvider).where(OidcProvider.enabled.is_(True)).order_by(OidcProvider.id))
    ]


@router.post("/api/oidc/links/{slug}", summary="Start linking this account to an identity provider")
async def link_start(slug: str, request: Request, user: SessionUser, db: DbSession) -> JSONResponse:
    """Antwortet mit der Adresse, zu der es geht, und setzt dabei das Cookie des Versuchs.

    Ein POST mit Zugangs-Token, kein Link zum Folgen: So kann keine fremde Seite in jemandes Browser eine
    Verknuepfung anstossen.
    """
    provider = _enabled_provider(db, slug)
    try:
        document = await oidc.discovery(provider.issuer_url)
        redirect = _redirect_uri(db, slug)
    except oidc.OidcError as failure:
        raise fehler(failure.code, failure.message, 502) from None
    attempt = oidc.new_attempt()
    response = JSONResponse(
        {"url": oidc.authorization_url(document, provider.client_id, redirect, provider.scopes, attempt)}
    )
    _attempt_cookie(response, request, oidc.pack_state(slug, attempt, purpose="link", user_id=user.id))
    return response


@router.delete("/api/oidc/links/{slug}", status_code=204, summary="Undo the link to an identity provider")
def link_remove(slug: str, user: SessionUser, db: DbSession) -> None:
    provider = db.scalar(select(OidcProvider).where(OidcProvider.slug == slug))
    if provider is None:
        raise fehler("oidc_unknown_provider", "There is no such sign-in provider.", 404)
    links = list(db.scalars(select(OidcLink).where(OidcLink.user_id == user.id)))
    mine = [link for link in links if link.provider_id == provider.id]
    if mine and not has_usable_password(user.password_hash) and len(links) == len(mine):
        # ⚠️ Der letzte Weg in ein Konto ohne Passwort.
        raise fehler("oidc_would_lock_out", "This is the only way into this account. Set a password first.", 409)
    for link in mine:
        db.delete(link)
    db.commit()


# -- Verwaltung ----------------------------------------------------------------


def _authentik_redirect(db: Session) -> str:
    try:
        return _redirect_uri(db, authentik_setup.PROVIDER_SLUG)
    except oidc.OidcError as failure:
        raise fehler(failure.code, failure.message, 422) from None


@router.post("/api/oidc/authentik/setup", summary="Set up provider and application in authentik with a one-time token")
async def authentik_setup_run(body: AuthentikSetupIn, admin: AdminUser, db: DbSession) -> dict:
    """⚠️ Der Token gilt nur fuer diesen Lauf: nicht gespeichert, nicht protokolliert, nicht zurueckgegeben."""
    url = body.url.strip().rstrip("/")
    if not url.lower().startswith(("http://", "https://")):
        raise fehler("oidc_bad_url", "The authentik address must start with http:// or https://.", 422)
    redirect = _authentik_redirect(db)
    logger.info("authentik setup started for %s by %s.", url, admin.username)
    result = await authentik_setup.setup(db, url, body.token.strip(), redirect)
    return result.as_dict()


@router.get("/api/oidc/authentik/blueprint", summary="A blueprint that creates the same objects in authentik")
def authentik_blueprint(_admin: AdminUser, db: DbSession) -> dict[str, str]:
    """Als JSON statt als Datei: Der Zugangs-Token reist im Kopf, und den setzt ein schlichter Link nicht."""
    return {"filename": "nexbeat-authentik.yaml", "content": authentik_setup.blueprint(_authentik_redirect(db))}


def _provider_out(db: Session, provider: OidcProvider) -> dict:
    linked = db.scalar(select(func.count()).select_from(OidcLink).where(OidcLink.provider_id == provider.id)) or 0
    return {
        "id": provider.id,
        "slug": provider.slug,
        "label": provider.label,
        "issuer_url": provider.issuer_url,
        "client_id": provider.client_id,
        "has_secret": bool(provider.client_secret),
        "scopes": provider.scopes,
        "enabled": provider.enabled,
        "auto_create": provider.auto_create,
        "default_role": provider.default_role.value,
        "linked_accounts": int(linked),
    }


@router.get("/api/oidc/providers", summary="List identity providers")
def list_providers(_admin: AdminUser, db: DbSession) -> list[dict]:
    return [_provider_out(db, provider) for provider in db.scalars(select(OidcProvider).order_by(OidcProvider.id))]


def _slug_taken(db: Session, slug: str, except_id: int | None = None) -> bool:
    query = select(OidcProvider.id).where(OidcProvider.slug == slug)
    if except_id is not None:
        query = query.where(OidcProvider.id != except_id)
    return db.scalar(query) is not None


@router.post("/api/oidc/providers", status_code=201, summary="Add an identity provider")
def create_provider(body: OidcProviderIn, _admin: AdminUser, db: DbSession) -> dict:
    if _slug_taken(db, body.slug):
        raise fehler("oidc_slug_taken", "That short name is taken.", 409)
    provider = OidcProvider(
        slug=body.slug,
        label=body.label.strip(),
        issuer_url=body.issuer_url.strip().rstrip("/"),
        client_id=body.client_id.strip(),
        client_secret=encrypt(body.client_secret.strip()) if body.client_secret.strip() else "",
        scopes=body.scopes.strip() or "openid profile email",
        enabled=body.enabled,
        auto_create=body.auto_create,
        default_role=body.default_role,
    )
    db.add(provider)
    db.commit()
    return _provider_out(db, provider)


@router.patch("/api/oidc/providers/{provider_id}", summary="Change an identity provider")
def patch_provider(provider_id: int, body: OidcProviderIn, _admin: AdminUser, db: DbSession) -> dict:
    provider = db.get(OidcProvider, provider_id)
    if provider is None:
        raise fehler("oidc_unknown_provider", "There is no such sign-in provider.", 404)
    if _slug_taken(db, body.slug, provider_id):
        raise fehler("oidc_slug_taken", "That short name is taken.", 409)
    issuer = body.issuer_url.strip().rstrip("/")
    if issuer != provider.issuer_url.rstrip("/"):
        # ⚠️ Ein ``sub`` bedeutet nur beim Aussteller etwas, der es vergeben hat. Ueber einen Wechsel behalten,
        # kaeme ein zufaellig gleiches ``sub`` des neuen in ein fremdes Konto.
        gone = list(db.scalars(select(OidcLink).where(OidcLink.provider_id == provider.id)))
        for link in gone:
            db.delete(link)
        if gone:
            logger.warning(
                "The issuer of %r changed; %d link(s) to the old one were removed.", provider.slug, len(gone)
            )
        oidc.forget_discovery(provider.issuer_url)
    provider.slug = body.slug
    provider.label = body.label.strip()
    provider.issuer_url = issuer
    provider.client_id = body.client_id.strip()
    if body.client_secret.strip():
        provider.client_secret = encrypt(body.client_secret.strip())
    provider.scopes = body.scopes.strip() or "openid profile email"
    provider.enabled = body.enabled
    provider.auto_create = body.auto_create
    provider.default_role = body.default_role
    db.commit()
    return _provider_out(db, provider)


@router.delete("/api/oidc/providers/{provider_id}", status_code=204, summary="Remove an identity provider")
def delete_provider(provider_id: int, _admin: AdminUser, db: DbSession, force: bool = False) -> None:
    """⚠️ Mit dem Anbieter gehen seine Verknuepfungen (``ondelete=CASCADE``).

    Ein Konto, das ueber ihn entstand, hat kein Passwort und sonst keinen Weg hinein. Erst zaehlen und die
    Zahl nennen; ``force=true`` loescht trotzdem.
    """
    provider = db.get(OidcProvider, provider_id)
    if provider is None:
        raise fehler("oidc_unknown_provider", "There is no such sign-in provider.", 404)
    if not force:
        stranded = sorted(
            user.username
            for link in db.scalars(select(OidcLink).where(OidcLink.provider_id == provider.id))
            if (user := db.get(User, link.user_id)) is not None
            and not has_usable_password(user.password_hash)
            and db.scalar(select(func.count()).select_from(OidcLink).where(OidcLink.user_id == link.user_id)) == 1
        )
        if stranded:
            raise fehler(
                "oidc_provider_strands",
                f"{len(stranded)} account(s) have no password and no other provider: {', '.join(stranded[:5])}.",
                409,
                count=len(stranded),
                names=", ".join(stranded[:5]),
            )
    db.delete(provider)
    db.commit()
    oidc.forget_discovery(provider.issuer_url)


def public_providers(db: Session) -> list[dict[str, str]]:
    """Fuer die Anmeldeseite: nur Kurzname und Beschriftung der eingeschalteten Anbieter."""
    return [
        {"slug": provider.slug, "label": provider.label}
        for provider in db.scalars(select(OidcProvider).where(OidcProvider.enabled.is_(True)).order_by(OidcProvider.id))
    ]
