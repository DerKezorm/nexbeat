"""Zwischenspeicher fuer Antworten externer Dienste, in der Datenbank.

Gelesen und geschrieben wird ueber Kernausdruecke statt ueber ORM-Objekte. Ein
geladenes Objekt bliebe sonst in der Sitzung haengen und wuerde nach einem
Schreiben durch eine andere Stelle veraltet zurueckgegeben.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from ..models import CacheEntry, utcnow

_MAX_KEY = 200


def _key(key: str) -> str:
    if len(key) <= _MAX_KEY:
        return key
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"{key[:120]}#{digest}"


#: Abgelaufenes bleibt so lange liegen, bevor das taegliche Aufraeumen es loescht. ``read_stale`` lebt davon.
PURGE_GRACE = timedelta(days=2)


def read(db: Session, key: str) -> Any | None:
    value, fresh = read_stale(db, key)
    return value if fresh else None


def read_stale(db: Session, key: str) -> tuple[Any | None, bool]:
    """Auch Abgelaufenes, dazu ob es noch gilt. Fuer Stellen, die lieber kurz Altes zeigen als warten."""
    row = db.execute(select(CacheEntry.payload, CacheEntry.expires_at).where(CacheEntry.key == _key(key))).first()
    if row is None:
        return None, False
    try:
        value = json.loads(row.payload)
    except json.JSONDecodeError:
        return None, False
    return value, row.expires_at > utcnow()


def write(db: Session, key: str, value: Any, ttl: timedelta) -> None:
    payload = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    expires_at = utcnow() + ttl
    statement = insert(CacheEntry).values(key=_key(key), payload=payload, expires_at=expires_at)
    statement = statement.on_conflict_do_update(
        index_elements=[CacheEntry.key],
        set_={"payload": payload, "expires_at": expires_at},
    )
    db.execute(statement)
    db.commit()


async def cached(db: Session, key: str, ttl: timedelta, factory: Callable[[], Awaitable[Any]]) -> Any:
    """Aus dem Speicher oder neu beschaffen. Leere Ergebnisse zaehlen als Treffer."""
    hit = read(db, key)
    if hit is not None:
        return hit
    value = await factory()
    write(db, key, value, ttl)
    return value


def forget(db: Session, key: str) -> None:
    db.execute(delete(CacheEntry).where(CacheEntry.key == _key(key)))
    db.commit()


def expire(db: Session, key: str) -> None:
    """Sofort ungueltig, aber nicht weg: ``read`` liefert nichts mehr, ``read_stale`` noch den alten Stand."""
    db.execute(update(CacheEntry).where(CacheEntry.key == _key(key)).values(expires_at=utcnow()))
    db.commit()


def forget_prefix(db: Session, prefix: str) -> None:
    db.execute(delete(CacheEntry).where(CacheEntry.key.startswith(prefix)))
    db.commit()


def purge_expired(db: Session) -> int:
    result = db.execute(delete(CacheEntry).where(CacheEntry.expires_at <= utcnow() - PURGE_GRACE))
    db.commit()
    return int(result.rowcount or 0)
