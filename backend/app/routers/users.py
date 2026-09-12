"""Benutzerverwaltung fuer Admins: Konten, Einladungen, Kontingente."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import AdminUser, DbSession
from ..meldungen import fehler
from ..models import AuthToken, Role, TokenPurpose, User, utcnow
from ..schemas import (
    AdminUserOut,
    DeliveryOut,
    InvitationCreatedOut,
    InvitationIn,
    InvitationOut,
    UserOut,
    UserUpdate,
)
from ..services import accounts, quota, tokens
from ..services.mail import valid_address
from ..services.settings_service import AppSettings, load_settings
from ..services.tokens import normalize_email

router = APIRouter(prefix="/api/users", tags=["users"])

MAX_QUOTA = 10_000


def _out(db: Session, settings: AppSettings, user: User) -> AdminUserOut:
    state = quota.state(db, user, settings)
    return AdminUserOut.model_validate({**UserOut.model_validate(user).model_dump(), "quota": quota.as_dict(state)})


def _get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise fehler("user_not_found", "This account does not exist.", 404)
    return user


def _active_admins(db: Session) -> int:
    return int(db.scalar(select(func.count(User.id)).where(User.role == Role.admin, User.is_active.is_(True))) or 0)


def _invitation_out(token: AuthToken) -> InvitationOut:
    return InvitationOut(
        id=token.id,
        email=token.email,
        role=token.invite_role or Role.user,
        created_at=token.created_at,
        expires_at=token.expires_at,
    )


@router.get("/invitations", response_model=list[InvitationOut], summary="Open invitations")
def list_invitations(_admin: AdminUser, db: DbSession) -> list[InvitationOut]:
    rows = db.scalars(
        select(AuthToken)
        .where(
            AuthToken.purpose == TokenPurpose.invitation,
            AuthToken.used_at.is_(None),
            AuthToken.expires_at > utcnow(),
        )
        .order_by(AuthToken.created_at.desc())
    )
    return [_invitation_out(token) for token in rows]


@router.post("/invitations", status_code=201, response_model=InvitationCreatedOut, summary="Invite someone by email")
async def create_invitation(
    payload: InvitationIn, request: Request, admin: AdminUser, db: DbSession
) -> InvitationCreatedOut:
    email = normalize_email(payload.email)
    if not valid_address(email):
        raise fehler("invalid_email", "This is not a valid email address.", 422)
    if db.scalar(select(User.id).where(User.email == email)):
        raise fehler("email_taken", "An account with this email address already exists.", 409)
    raw, token = tokens.create(db, TokenPurpose.invitation, email, created_by=admin.id, invite_role=payload.role)
    settings = load_settings(db)
    delivery = await accounts.send_invitation(
        settings,
        raw=raw,
        email=email,
        inviter=admin.display_name or admin.username,
        language=settings.default_language,
        base_url=accounts.link_base(settings, request),
    )
    return InvitationCreatedOut(invitation=_invitation_out(token), delivery=DeliveryOut(**delivery.as_dict()))


@router.delete("/invitations/{invitation_id}", status_code=204, summary="Withdraw an invitation")
def withdraw_invitation(invitation_id: int, _admin: AdminUser, db: DbSession) -> None:
    token = db.get(AuthToken, invitation_id)
    if token is None or token.purpose != TokenPurpose.invitation or not token.open:
        raise fehler("invitation_invalid", "This invitation is invalid or has expired.", 404)
    token.used_at = utcnow()
    db.commit()


@router.get("", response_model=list[AdminUserOut], summary="All accounts with their quota")
def list_users(_admin: AdminUser, db: DbSession) -> list[AdminUserOut]:
    settings = load_settings(db)
    users = db.scalars(select(User).order_by(User.role, func.lower(User.username)))
    return [_out(db, settings, user) for user in users]


@router.patch("/{user_id}", response_model=AdminUserOut, summary="Change role, status, approval or quota")
def update_user(user_id: int, payload: UserUpdate, admin: AdminUser, db: DbSession) -> AdminUserOut:
    user = _get_user(db, user_id)
    losing_admin = user.is_admin and user.is_active and (
        (payload.role is not None and payload.role != Role.admin) or payload.is_active is False
    )
    if losing_admin and _active_admins(db) <= 1:
        raise fehler("last_admin", "The last active administrator cannot be removed.", 409)
    if user.id == admin.id and payload.is_active is False:
        raise fehler("cannot_disable_self", "You cannot deactivate your own account.", 409)

    if payload.role is not None:
        if user.is_admin and payload.role != Role.admin:
            # Wer die Rechte verliert, dessen offene Einladungen und Passwort-Links gelten nicht mehr.
            tokens.revoke_issued_by(db, user.id)
        user.role = payload.role
    if payload.is_active is not None:
        if not payload.is_active and user.is_active:
            # Deaktiviert heisst auch: ueberall abgemeldet, ausgegebene Links entwertet.
            user.sessions_valid_from = utcnow()
            tokens.revoke_issued_by(db, user.id)
        user.is_active = payload.is_active
    if payload.requires_approval is not None:
        user.requires_approval = payload.requires_approval
    if payload.display_name is not None:
        user.display_name = payload.display_name.strip()
    if payload.quota is not None:
        if payload.quota == "default":
            user.quota_limit = None
        elif payload.quota == "unlimited":
            user.quota_limit = -1
        elif 0 <= payload.quota <= MAX_QUOTA:
            user.quota_limit = payload.quota
        else:
            raise fehler("invalid_quota", "The quota must be between 0 and 10000.", 422)
    db.commit()
    return _out(db, load_settings(db), user)


@router.delete("/{user_id}", status_code=204, summary="Delete an account and its requests")
def delete_user(user_id: int, admin: AdminUser, db: DbSession) -> None:
    user = _get_user(db, user_id)
    if user.id == admin.id:
        raise fehler("cannot_delete_self", "You cannot delete your own account.", 409)
    if user.is_admin and user.is_active and _active_admins(db) <= 1:
        raise fehler("last_admin", "The last active administrator cannot be removed.", 409)
    # Vor dem Loeschen: Danach steht in ``created_by`` nichts mehr, woran sich die Links erkennen liessen.
    tokens.revoke_issued_by(db, user.id)
    db.delete(user)
    db.commit()


@router.post("/{user_id}/quota/reset", response_model=AdminUserOut, summary="Start counting the quota from now")
def reset_quota(user_id: int, _admin: AdminUser, db: DbSession) -> AdminUserOut:
    user = _get_user(db, user_id)
    user.quota_reset_at = utcnow()
    db.commit()
    return _out(db, load_settings(db), user)


@router.post("/{user_id}/password-reset", response_model=DeliveryOut, summary="Send or hand out a password link")
async def send_password_link(user_id: int, request: Request, admin: AdminUser, db: DbSession) -> DeliveryOut:
    user = _get_user(db, user_id)
    settings = load_settings(db)
    # Fuer einen anderen Admin nur per Mail an seine Adresse, nie zum Weitergeben. 12.09.2026:
    # Sonst konnte ein Admin sich einen Link geben lassen und das Konto des anderen uebernehmen.
    by_mail_only = user.is_admin and user.id != admin.id
    if by_mail_only and not settings.mail_configured:
        raise fehler(
            "admin_link_needs_mail",
            "A password link for another administrator can only be sent by mail. Set up mail first.",
            409,
        )
    raw, _token = tokens.create(db, TokenPurpose.password_reset, user.email, user=user, created_by=admin.id)
    delivery = await accounts.send_password_reset(
        settings,
        raw=raw,
        email=user.email,
        language=user.language or settings.default_language,
        base_url=accounts.link_base(settings, request),
    )
    if by_mail_only and not delivery.sent:
        tokens.invalidate(db, TokenPurpose.password_reset, user.email)
        db.commit()
        raise fehler(delivery.error_code or "mail_rejected", "The mail could not be sent.", 502)
    return DeliveryOut(**delivery.as_dict())
