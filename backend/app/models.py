"""Datenmodell von nexbeat.

Zeitpunkte sind naive UTC-Werte. SQLite speichert keine Zeitzone, und ein
Mischbetrieb aus naiven und zeitzonenbehafteten Werten wirft erst beim
Vergleich einen Fehler. Umgerechnet wird an der Aussengrenze.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


def enum_column(enum_class: type[StrEnum], **kwargs: Any) -> Any:
    # Als Text gespeichert: Ein neuer Wert braucht keine Tabellenmigration.
    return mapped_column(
        SAEnum(
            enum_class,
            native_enum=False,
            length=32,
            values_callable=lambda members: [member.value for member in members],
        ),
        **kwargs,
    )


class Role(StrEnum):
    admin = "admin"
    user = "user"


class TokenPurpose(StrEnum):
    invitation = "invitation"
    password_reset = "password_reset"


class RequestStatus(StrEnum):
    pending_approval = "pending_approval"
    approved = "approved"
    searching = "searching"
    downloaded = "downloaded"
    rejected = "rejected"
    failed = "failed"
    cancelled = "cancelled"


#: Zaehlen gegen das Kontingent. Abgelehnt, gescheitert und zurueckgezogen
#: fallen heraus. Damit ist das Zurueckbuchen kein eigener Schritt, den man
#: vergessen koennte.
COUNTED_STATUSES = (
    RequestStatus.pending_approval,
    RequestStatus.approved,
    RequestStatus.searching,
    RequestStatus.downloaded,
)

#: Noch unterwegs. Eine zweite Anfrage fuer dasselbe Album waere doppelt.
OPEN_STATUSES = (
    RequestStatus.pending_approval,
    RequestStatus.approved,
    RequestStatus.searching,
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = enum_column(Role, default=Role.user)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    # Leer heisst: die Vorgabe der Installation.
    language: Mapped[str] = mapped_column(String(8), default="")
    is_active: Mapped[bool] = mapped_column(default=True)
    requires_approval: Mapped[bool] = mapped_column(default=False)
    # None: Vorgabe der Installation, -1: unbegrenzt, 0: keine Anfragen.
    quota_limit: Mapped[int | None] = mapped_column(Integer, default=None)
    quota_reset_at: Mapped[datetime | None] = mapped_column(default=None)
    password_changed_at: Mapped[datetime | None] = mapped_column(default=None)
    sessions_valid_from: Mapped[datetime | None] = mapped_column(default=None)
    last_login_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    # Die Fassung, deren "Was ist neu" dieses Konto zuletzt geschlossen hat. Leer bei Konten von vor 1.1.0: sie
    # sehen das Fenster einmal. Neue Konten bekommen die laufende Fassung, sie kennen nichts Altes.
    seen_version: Mapped[str | None] = mapped_column(String(32), default=None)

    requests: Mapped[list[MusicRequest]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="MusicRequest.user_id",
    )

    @property
    def is_admin(self) -> bool:
        return self.role == Role.admin


class AuthToken(Base):
    """Einmal-Link fuer Einladung oder Passwort-Reset. Gespeichert wird nur der Hash."""

    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    purpose: Mapped[TokenPurpose] = enum_column(TokenPurpose, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=None)
    invite_role: Mapped[Role | None] = enum_column(Role, nullable=True, default=None)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime] = mapped_column()
    used_at: Mapped[datetime | None] = mapped_column(default=None)

    @property
    def open(self) -> bool:
        return self.used_at is None and self.expires_at > utcnow()


class RevokedSession(Base):
    """Abgemeldete Anmeldung, bis kein Erneuerungs-Token daraus mehr gelten koennte."""

    __tablename__ = "revoked_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(index=True)


class ApiKey(Base):
    """Persoenlicher API-Token fuer Skripte und Dashboards, wie in Nexview.

    Ein Token erbt die Rechte seines Kontos, mit ``read_only`` darf er nur lesen. Gespeichert wird
    nur die Pruefsumme; den Klartext gibt es genau einmal, in der Antwort aufs Anlegen.
    """

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Der Anfang des Klartexts, zum Wiedererkennen in der Liste.
    preview: Mapped[str] = mapped_column(String(16))
    read_only: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(default=None)

    user: Mapped[User] = relationship()


class OidcProvider(Base):
    """Ein Anmeldeanbieter per OpenID Connect: authentik, Entra ID, Keycloak, Pocket ID und andere.

    Die Spalten folgen dem Anmeldemodul, die Namen in der Datenbank aber denen von 1.3.0: Die alte
    Fassung liest dieselbe Tabelle. Umbenannt haette sie nach einem Rueckweg keinen Anbieter mehr gefunden.
    Deshalb heisst ``issuer`` in der Datenbank weiter ``issuer_url``, und das Geheimnis steht zweimal da:
    ``client_secret_enc`` mit dem Kontext des Eintrags, ``client_secret_legacy`` so, wie 1.3.0 es liest.

    ⚠️ Jede neue Spalte hat einen ``server_default``: 1.3.0 legt auf einer Datenbank dieser Fassung weiter
    Eintraege an und kennt die Spalten nicht. ``redirect_path`` bleibt dabei NULL, daran erkennt der Start einen
    Eintrag der alten Fassung (``services.oidc_migration``).
    """

    __tablename__ = "oidc_providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Teil der Rueckleitadresse, also fest, sobald der Anbieter sie kennt.
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    label: Mapped[str] = mapped_column(String(80))
    issuer: Mapped[str] = mapped_column("issuer_url", String(500))
    client_id: Mapped[str] = mapped_column(String(300))
    # Mit dem Kontext ``oidc-provider:<id>`` verschluesselt (``crypto.seal``), leer bei oeffentlichen Clients.
    client_secret_enc: Mapped[str] = mapped_column(String(4000), default="", server_default="")
    # Dasselbe Geheimnis fuer 1.3.0 (``crypto.encrypt``), bis die alte Fassung keinen Rueckweg mehr braucht.
    client_secret_legacy: Mapped[str] = mapped_column("client_secret", String(600), default="")
    scopes: Mapped[str] = mapped_column(String(500), default="openid profile email")
    enabled: Mapped[bool] = mapped_column(default=True)
    # "Neue Personen bekommen ein Konto", ab Werk aus.
    auto_create: Mapped[bool] = mapped_column(default=False, server_default="0")
    # Nur noch fuer 1.3.0, die damit Konten anlegte. Neue Konten sind Mitglieder.
    default_role: Mapped[Role] = enum_column(Role, default=Role.user, server_default=Role.user.value)
    # nexbeat hat keinen eigenen zweiten Faktor; die Spalte gehoert zum Modul und bleibt an.
    trusts_second_factor: Mapped[bool] = mapped_column(default=True, server_default="1")
    # "" von Hand, "authentik" vom authentik-Knopf.
    managed: Mapped[str] = mapped_column(String(20), default="", server_default="")
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Rueckleitpfad, den der Anbieter kennt; "" der Standard ``/api/oidc/<slug>/callback``. NULL: von 1.3.0
    # angelegt, der Start traegt dann deren Pfad ein.
    # Ohne Vorgabe, auch beim Nachziehen der Spalte: Bestehende Eintraege bekommen NULL.
    redirect_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(default=utcnow, nullable=True)
    # Die Rueckleitadresse, die der authentik-Knopf zuletzt in authentik eingetragen hat.
    registered_redirect: Mapped[str] = mapped_column(String(500), default="", server_default="")


class OidcLink(Base):
    """Welche Identitaet bei welchem Anbieter zu welchem Konto gehoert.

    ⚠️ Zugeordnet wird nur ueber ``(provider_id, subject)``, nie ueber die Mailadresse: Bei authentik kann jeder
    seine Adresse selbst aendern, und Entra ID buergt fuer keine. ``email`` steht nur zur Anzeige hier.
    ``account_id`` heisst in der Datenbank weiter ``user_id`` (1.3.0 liest dieselbe Tabelle).
    """

    __tablename__ = "oidc_links"
    __table_args__ = (
        UniqueConstraint("provider_id", "subject"),
        UniqueConstraint("provider_id", "user_id", name="uq_oidc_links_provider_account"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("oidc_providers.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column("user_id", ForeignKey("users.id", ondelete="CASCADE"), index=True)
    subject: Mapped[str] = mapped_column(String(300))
    # Das tatsaechliche ``iss`` des Tokens (bei Entra mit ``common`` der echte Mandant).
    issuer: Mapped[str] = mapped_column(String(500), default="", server_default="")
    email: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(default=None, nullable=True)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class CacheEntry(Base):
    """Zwischenspeicher fuer Antworten externer Dienste."""

    __tablename__ = "cache"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    payload: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(index=True)


#: Eine Anfrage gilt einem Release oder einem ganzen Kuenstler.
ALBUM_KIND = "album"
ARTIST_KIND = "artist"


class MusicRequest(Base):
    """Eine Anfrage fuer ein Release (Album, EP oder Single) oder einen ganzen Kuenstler.

    Beim ganzen Kuenstler ist ``release_group_mbid`` leer, und ``title`` traegt den Namen.
    """

    __tablename__ = "requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default=ALBUM_KIND)
    release_group_mbid: Mapped[str] = mapped_column(String(36), index=True)
    artist_mbid: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(512))
    artist_name: Mapped[str] = mapped_column(String(512))
    album_type: Mapped[str] = mapped_column(String(32), default="")
    # Ganzer Kuenstler im NEX-Modus: die gewaehlten Arten mit Kommas (``album_groups``). Leer: nur Studioalben.
    album_types: Mapped[str] = mapped_column(String(160), default="")
    release_date: Mapped[str] = mapped_column(String(10), default="")
    cover_url: Mapped[str] = mapped_column(String(1024), default="")
    status: Mapped[RequestStatus] = enum_column(RequestStatus, index=True, default=RequestStatus.pending_approval)
    requested_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), default=None)
    decided_at: Mapped[datetime | None] = mapped_column(default=None)
    rejection_reason: Mapped[str] = mapped_column(Text, default="")
    submitted_at: Mapped[datetime | None] = mapped_column(default=None)
    completed_at: Mapped[datetime | None] = mapped_column(default=None)
    lidarr_artist_id: Mapped[int | None] = mapped_column(Integer, default=None)
    lidarr_album_id: Mapped[int | None] = mapped_column(Integer, default=None)
    # Anteil der vorhandenen Titel in Prozent, laut Lidarr.
    progress: Mapped[int] = mapped_column(Integer, default=0)
    # Kennung fuer die Oberflaeche, z. B. ``album_not_in_lidarr`` oder ``dry_run``.
    error_code: Mapped[str] = mapped_column(String(64), default="")
    # Technischer Hinweis fuer Admins, englisch.
    error_message: Mapped[str] = mapped_column(Text, default="")
    # Wann nexbeat die Suche selbst noch einmal angestossen hat. Das passiert hoechstens einmal.
    search_retried_at: Mapped[datetime | None] = mapped_column(default=None)

    user: Mapped[User] = relationship(back_populates="requests", foreign_keys=[user_id])


class LibraryArtist(Base):
    """Kuenstler im Lidarr-Bestand, regelmaessig abgeglichen."""

    __tablename__ = "library_artists"

    mbid: Mapped[str] = mapped_column(String(36), primary_key=True)
    lidarr_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(512))
    image_url: Mapped[str] = mapped_column(String(1024), default="")
    track_file_count: Mapped[int] = mapped_column(Integer, default=0)
    album_count: Mapped[int] = mapped_column(Integer, default=0)
    # Das eigene Metadatenprofil des Kuenstlers in Lidarr. 0 heisst: noch nicht abgeglichen.
    metadata_profile_id: Mapped[int] = mapped_column(Integer, default=0)
    synced_at: Mapped[datetime] = mapped_column(default=utcnow)
