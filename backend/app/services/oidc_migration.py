"""Beim Start: die Anbieterliste von 1.3.0 auf den Bauplan nachziehen, und was 1.3.0 nach einem Rueckweg geaendert hat.

nexbeat hatte schon eine Liste (``oidc_providers``, ``oidc_links``). Die neuen Spalten legt ``db._add_missing_columns``
an, alle mit Vorgabe, die Namen der alten bleiben (``models.OidcProvider``). Hier passiert der Rest, bei jedem Start,
in einer Transaktion:

1. **Eintraege, die 1.3.0 angelegt hat** (``redirect_path`` NULL, beim ersten Start also alle): Ihr Anbieter kennt die
   Rueckleitadresse ``/api/auth/oidc/<slug>/callback``; sie wird ihr ``redirect_path`` und bleibt gueltig (Bauplan 01,
   letzter Absatz). Der Eintrag mit dem Kurznamen ``authentik``, dessen Aussteller auf ``/application/o/<slug>/``
   endet, kam vom authentik-Knopf von 1.3.0 (der fand seinen Eintrag am Kurznamen): ``managed = "authentik"``.
2. **Geheimnis:** Was in der Spalte von 1.3.0 steht, gilt; weicht die Spalte mit Kontext davon ab (1.3.0 hat es
   geaendert oder den Eintrag angelegt), wird sie neu geschrieben.
3. **Verknuepfungen ohne Aussteller** (von 1.3.0): der Aussteller ihres Eintrags.
4. **Ein Konto, eine Identitaet je Anbieter** als eindeutiger Index; Doppelte (gab es in 1.3.0 nicht) bleiben mit der
   aeltesten Zeile.

Vor einer Aenderung an einer bestehenden Liste (Schritt 1 oder 4) wird die Datenbank gesichert, neben ihr als
``nexbeat-before-oidc-<Zeitpunkt>.db``. Aussteller, Kurznamen und Verknuepfungen bleiben dabei Zeichen fuer Zeichen,
wie 1.3.0 sie schrieb.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import UTC, datetime

from sqlalchemy import Engine, func, inspect, select, text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..crypto import decrypt, seal, unseal
from ..models import OidcLink, OidcProvider
from ..vendor.nexoidc import migrate, secret_context

logger = logging.getLogger("nexbeat.oidc")

#: Die Rueckleitadresse von 1.3.0. Der Anbieter jedes Eintrags von damals kennt nur sie.
OLD_CALLBACK = "/api/auth/oidc/{slug}/callback"
#: Kurzname und Aussteller, an denen der authentik-Knopf von 1.3.0 seinen Eintrag erkennt.
OLD_BUTTON_SLUG = "authentik"
_AUTHENTIK_ISSUER = re.compile(r"/application/o/[-A-Za-z0-9_]+/?$")
UNIQUE_INDEX = "uq_oidc_links_provider_account"


def _has_unique_index(engine: Engine) -> bool:
    inspector = inspect(engine)
    names = {index["name"] for index in inspector.get_indexes("oidc_links")}
    names |= {constraint["name"] for constraint in inspector.get_unique_constraints("oidc_links")}
    return UNIQUE_INDEX in names


def backup(engine: Engine) -> str:
    """Die ganze Datenbank als Kopie neben ihr (SQLite-Backup, auch waehrend sie offen ist)."""
    source_path = get_settings().database_path
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = source_path.with_name(f"nexbeat-before-oidc-{stamp}.db")
    raw = engine.raw_connection()
    try:
        destination = sqlite3.connect(target)
        try:
            raw.driver_connection.backup(destination)  # type: ignore[union-attr]
        finally:
            destination.close()
    finally:
        raw.close()
    logger.info("Backed up the database to %s before adapting the sign-in providers.", target.name)
    return str(target)


def run(engine: Engine) -> None:
    unique = _has_unique_index(engine)
    with Session(engine) as db:
        old_rows = list(db.scalars(select(OidcProvider).where(OidcProvider.redirect_path.is_(None))))
        if old_rows or not unique:
            has_rows = db.scalar(select(func.count()).select_from(OidcProvider)) or 0
            if has_rows:
                db.close()
                backup(engine)
    with Session(engine) as db:
        _adopt_old_rows(db)
        _sync_secrets(db)
        _fill_link_issuers(db)
        if not unique:
            _unique_links(db)
        db.commit()


def _adopt_old_rows(db: Session) -> None:
    rows = list(db.scalars(select(OidcProvider).where(OidcProvider.redirect_path.is_(None)).order_by(OidcProvider.id)))
    for row in rows:
        row.redirect_path = migrate.old_callback(OLD_CALLBACK, row.slug)
        if row.slug == OLD_BUTTON_SLUG and _AUTHENTIK_ISSUER.search(row.issuer or "") and not row.managed:
            row.managed = "authentik"
        if row.trusts_second_factor is None:
            row.trusts_second_factor = True
    if rows:
        logger.info(
            "%d sign-in provider(s) from nexbeat 1.3.0 keep their redirect address %s.",
            len(rows),
            OLD_CALLBACK,
        )


def _sync_secrets(db: Session) -> None:
    changed = 0
    for row in db.scalars(select(OidcProvider)):
        legacy = decrypt(row.client_secret_legacy or "")
        if unseal(row.client_secret_enc or "", secret_context(row.id)) != legacy:
            row.client_secret_enc = seal(legacy, secret_context(row.id))
            changed += 1
    if changed:
        logger.info("Took over the client secret of %d sign-in provider(s) as nexbeat 1.3.0 left it.", changed)


def _fill_link_issuers(db: Session) -> None:
    for link in db.scalars(select(OidcLink).where(OidcLink.issuer == "")):
        provider = db.get(OidcProvider, link.provider_id)
        if provider is not None:
            link.issuer = provider.issuer


def _unique_links(db: Session) -> None:
    """Hoechstens eine Identitaet je Anbieter und Konto (Bauplan 01). 1.3.0 hielt das schon im Code ein."""
    seen: set[tuple[int, int]] = set()
    dropped = 0
    for link in db.scalars(select(OidcLink).order_by(OidcLink.id)):
        key = (link.provider_id, link.account_id)
        if key in seen:
            db.delete(link)
            dropped += 1
        seen.add(key)
    db.flush()
    if dropped:
        logger.warning("Removed %d duplicate link(s): one identity per provider and account.", dropped)
    db.execute(text(f'CREATE UNIQUE INDEX IF NOT EXISTS "{UNIQUE_INDEX}" ON oidc_links (provider_id, user_id)'))
