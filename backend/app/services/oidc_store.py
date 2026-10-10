"""Die Anbindung des gemeinsamen Anmeldemoduls (``app.vendor.nexoidc``) an die Tabellen von nexbeat.

Das Modul fragt ueber einen ``Store``; hier steht er, ueber ``oidc_providers``, ``oidc_links``, ``users`` und die
Einladungen in ``auth_tokens``. Eine Instanz gilt fuer eine Datenbanksitzung, also eine Anfrage.

⚠️ Zugeordnet wird nur ueber ``(provider_id, subject)``. Die Adresse vom Anbieter landet hoechstens als Adresse eines
neuen Kontos, und nur, wenn kein anderes sie hat; sie findet nie ein bestehendes.

Das Geheimnis eines Anbieters steht zweimal da: mit dem Kontext des Eintrags (``client_secret_enc``, gelesen) und so,
wie 1.3.0 es liest (``client_secret_legacy``, nur geschrieben). Damit findet die alte Fassung nach einem Rueckweg
jeden Anbieter samt Geheimnis vor; was sie dort aendert, holt der Start zurueck (``oidc_migration``).
"""

from __future__ import annotations

import re

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .. import __version__
from ..crypto import encrypt, seal, unseal
from ..models import AuthToken, OidcLink, OidcProvider, Role, TokenPurpose, User, utcnow
from ..security import UNUSABLE_PASSWORD, has_usable_password
from ..vendor.nexoidc.model import AccountState, Invite, Link, Provider, ProviderValues, secret_context
from . import tokens

#: Ersatzadresse fuer Konten, deren Anbieter keine (oder eine schon vergebene) Adresse nennt. ``.invalid`` ist
#: reserviert und kann nie zugestellt werden.
PLACEHOLDER_DOMAIN = "oidc.invalid"
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
#: Zeichen wie ``schemas.USERNAME_PATTERN`` (Buchstaben, Ziffern, Punkt, Unterstrich, Bindestrich), hoechstens 32.
#: Kuerzer als drei darf ein Name vom Anbieter sein ("jo"): Die Untergrenze gilt nur fuer selbst gewaehlte Namen,
#: und sonst hiesse jede kurze Identitaet "user-2", "user-3".
NAME_MIN, NAME_MAX = 1, 32
_NOT_IN_NAME = re.compile(r"[^a-z0-9._-]+")


class SqlStore:
    """``nexoidc.model.Store`` ueber die Tabellen von nexbeat, in einer SQLAlchemy-Sitzung."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Anbieter -------------------------------------------------------------------------------------------------
    def _provider(self, row: OidcProvider | None) -> Provider | None:
        if row is None:
            return None
        return Provider(
            id=row.id,
            slug=row.slug,
            label=row.label,
            issuer=row.issuer,
            client_id=row.client_id,
            client_secret=unseal(row.client_secret_enc or "", secret_context(row.id)),
            scopes=row.scopes,
            enabled=bool(row.enabled),
            auto_create=bool(row.auto_create),
            trusts_second_factor=bool(row.trusts_second_factor),
            managed=row.managed or "",
            position=row.position or 0,
            redirect_path=row.redirect_path or "",
            created_at=row.created_at,
            registered_redirect=row.registered_redirect or "",
        )

    def list_providers(self) -> list[Provider]:
        rows = self.db.scalars(select(OidcProvider).order_by(OidcProvider.position, OidcProvider.id))
        return [provider for row in rows if (provider := self._provider(row)) is not None]

    def get_provider(self, provider_id: int) -> Provider | None:
        return self._provider(self.db.get(OidcProvider, provider_id))

    def provider_by_slug(self, slug: str) -> Provider | None:
        return self._provider(self.db.scalar(select(OidcProvider).where(OidcProvider.slug == slug)))

    def _apply(self, row: OidcProvider, values: ProviderValues) -> None:
        row.slug, row.label, row.issuer, row.client_id = values.slug, values.label, values.issuer, values.client_id
        row.scopes, row.enabled, row.auto_create = values.scopes, values.enabled, values.auto_create
        row.trusts_second_factor, row.managed, row.position = (
            values.trusts_second_factor,
            values.managed,
            values.position,
        )
        row.redirect_path = values.redirect_path
        if values.registered_redirect is not None:
            row.registered_redirect = values.registered_redirect

    def _secret(self, row: OidcProvider, secret: str) -> None:
        row.client_secret_enc = seal(secret, secret_context(row.id))
        # Fuer 1.3.0, bis die alte Fassung keinen Rueckweg mehr braucht.
        row.client_secret_legacy = encrypt(secret) if secret else ""

    def insert_provider(self, values: ProviderValues) -> Provider:
        row = OidcProvider(default_role=Role.user, created_at=utcnow())
        self._apply(row, values)
        if values.registered_redirect is None:
            row.registered_redirect = ""
        self.db.add(row)
        self.db.flush()
        self._secret(row, values.client_secret or "")
        self.db.flush()
        return self._provider(row)  # type: ignore[return-value]

    def update_provider(self, provider_id: int, values: ProviderValues) -> Provider:
        row = self.db.get(OidcProvider, provider_id)
        if row is None:
            raise LookupError(f"no provider {provider_id}")
        self._apply(row, values)
        if values.client_secret is not None:
            self._secret(row, values.client_secret)
        self.db.flush()
        return self._provider(row)  # type: ignore[return-value]

    def delete_provider(self, provider_id: int) -> None:
        # ON DELETE CASCADE gilt in SQLite nur mit PRAGMA foreign_keys=ON (``db._pragmas``); trotzdem ausdruecklich.
        for link in self.db.scalars(select(OidcLink).where(OidcLink.provider_id == provider_id)):
            self.db.delete(link)
        row = self.db.get(OidcProvider, provider_id)
        if row is not None:
            self.db.delete(row)
        self.db.flush()

    # --- Verknuepfungen -------------------------------------------------------------------------------------------
    @staticmethod
    def _link(row: OidcLink) -> Link:
        return Link(
            provider_id=row.provider_id,
            subject=row.subject,
            account_id=row.account_id,
            issuer=row.issuer or "",
            email=row.email or None,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
        )

    def find_link(self, provider_id: int, subject: str) -> Link | None:
        row = self.db.scalar(select(OidcLink).where(OidcLink.provider_id == provider_id, OidcLink.subject == subject))
        return self._link(row) if row is not None else None

    def links_of_provider(self, provider_id: int) -> list[Link]:
        query = select(OidcLink).where(OidcLink.provider_id == provider_id).order_by(OidcLink.id)
        return [self._link(row) for row in self.db.scalars(query)]

    def links_of_account(self, account_id: int) -> list[Link]:
        query = select(OidcLink).where(OidcLink.account_id == account_id).order_by(OidcLink.id)
        return [self._link(row) for row in self.db.scalars(query)]

    def add_link(self, link: Link) -> None:
        self.db.add(
            OidcLink(
                provider_id=link.provider_id,
                subject=link.subject,
                account_id=link.account_id,
                issuer=link.issuer,
                email=(link.email or "")[:300],
                created_at=utcnow(),
                last_used_at=utcnow(),
            )
        )
        self.db.flush()

    def remove_link(self, provider_id: int, account_id: int) -> bool:
        rows = list(
            self.db.scalars(
                select(OidcLink).where(OidcLink.provider_id == provider_id, OidcLink.account_id == account_id)
            )
        )
        for row in rows:
            self.db.delete(row)
        self.db.flush()
        return bool(rows)

    def drop_links(self, provider_id: int) -> int:
        rows = list(self.db.scalars(select(OidcLink).where(OidcLink.provider_id == provider_id)))
        for row in rows:
            self.db.delete(row)
        self.db.flush()
        return len(rows)

    def touch_link(self, provider_id: int, subject: str, email: str | None) -> None:
        self.db.execute(
            update(OidcLink)
            .where(OidcLink.provider_id == provider_id, OidcLink.subject == subject)
            .values(last_used_at=utcnow(), email=(email or "")[:300])
        )

    # --- Konten ---------------------------------------------------------------------------------------------------
    def account_state(self, account_id: int) -> AccountState | None:
        user = self.db.get(User, account_id)
        if user is None:
            return None
        return AccountState(
            id=user.id,
            name=user.username,
            blocked=not user.is_active,
            has_password=has_usable_password(user.password_hash),
            # nexbeat hat keinen eigenen zweiten Faktor.
            has_second_factor=False,
        )

    def clean_name(self, raw: str) -> str:
        """Die Namensregeln von nexbeat (``schemas.USERNAME_PATTERN``); "" wenn nichts Brauchbares bleibt."""
        cleaned = _NOT_IN_NAME.sub("-", raw.strip().lower())
        cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-._")[:NAME_MAX].rstrip("-._")
        return cleaned if len(cleaned) >= NAME_MIN else ""

    def name_taken(self, name: str) -> bool:
        return self.db.scalar(select(User.id).where(func.lower(User.username) == name.lower())) is not None

    def _address_taken(self, address: str) -> bool:
        return self.db.scalar(select(User.id).where(User.email == address)) is not None

    def _address_for(self, name: str, *candidates: str | None) -> str:
        """Die erste brauchbare, noch freie Adresse, sonst ``<name>@oidc.invalid``.

        ⚠️ Eine vergebene Adresse fuehrt nie zu deren Konto; das neue Konto bekommt dann nur die Ersatzadresse.
        """
        for candidate in candidates:
            address = tokens.normalize_email(candidate or "")
            if EMAIL_PATTERN.match(address) and len(address) <= 255 and not self._address_taken(address):
                return address
        return f"{name.lower()}@{PLACEHOLDER_DOMAIN}"

    def create_account(self, name: str, *, invite: Invite | None, email: str | None) -> int:
        role = invite.rights if invite is not None and isinstance(invite.rights, Role) else Role.user
        invited = invite_email(self.db, invite)
        user = User(
            username=name,
            email=self._address_for(name, invited, email),
            password_hash=UNUSABLE_PASSWORD,
            role=role,
            display_name=name,
            seen_version=__version__,
        )
        self.db.add(user)
        self.db.flush()
        return user.id

    # --- Einladungen ----------------------------------------------------------------------------------------------
    def find_invite(self, key: str) -> Invite | None:
        if not key:
            return None
        token = tokens.find(self.db, key, TokenPurpose.invitation)
        if token is None:
            return None
        return Invite(key=key, id=token.id, rights=token.invite_role or Role.user)

    def consume_invite(self, invite: Invite) -> bool:
        """Eine Anweisung, die genau eine Zeile treffen muss: Zwei gleichzeitige Rueckkehrer, nur einer kommt durch."""
        now = utcnow()
        result = self.db.execute(
            update(AuthToken)
            .where(
                AuthToken.id == invite.id,
                AuthToken.purpose == TokenPurpose.invitation,
                AuthToken.used_at.is_(None),
                AuthToken.expires_at > now,
            )
            .values(used_at=now)
        )
        return int(getattr(result, "rowcount", 0) or 0) == 1

    def accept_invite(self, account_id: int, invite: Invite) -> None:
        """Die Rechte der Einladung dazu, nie weniger: Ein Admin bleibt Admin."""
        user = self.db.get(User, account_id)
        if user is not None and invite.rights == Role.admin and user.role != Role.admin:
            user.role = Role.admin
            self.db.flush()

    # --- Transaktion ----------------------------------------------------------------------------------------------
    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()


def invite_email(db: Session, invite: Invite | None) -> str:
    """Die Adresse, an die die Einladung ging (der Admin hat sie eingetragen), fuer das neue Konto."""
    if invite is None:
        return ""
    token = db.get(AuthToken, invite.id)
    return token.email if token is not None else ""
