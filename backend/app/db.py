"""SQLite-Anbindung und das Nachziehen neuer Spalten beim Start.

Es gibt kein Alembic. Neue Tabellen legt ``create_all`` an, neue Spalten
``_add_missing_columns``. Umbenennen oder Loeschen passiert nie automatisch.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from enum import Enum
from typing import Any

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import Base

logger = logging.getLogger("nexbeat.db")

_settings = get_settings()
_settings.data_dir.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{_settings.database_path}",
    connect_args={"check_same_thread": False, "timeout": 5},
)


@event.listens_for(engine, "connect")
def _pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def init_db() -> None:
    Base.metadata.create_all(engine)
    _add_missing_columns()


def _sql_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, Enum):
        value = value.value
    return "'" + str(value).replace("'", "''") + "'"


def _add_missing_columns() -> None:
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            existing = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                default = None
                if column.default is not None and not callable(column.default.arg):
                    default = column.default.arg
                if not column.nullable and default is None:
                    # ⚠️ Lieber laut abbrechen als eine Pflichtspalte ohne Wert
                    # anzulegen, die jede bestehende Zeile ungueltig macht.
                    raise RuntimeError(
                        f"Column {table.name}.{column.name} is required but has no default. "
                        "Give it a default before starting."
                    )
                column_type = column.type.compile(dialect=engine.dialect)
                statement = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column_type}'
                if default is not None:
                    statement += f" DEFAULT {_sql_literal(default)}"
                # Tabellen- und Spaltennamen stammen aus dem eigenen Modell, nie von aussen.
                connection.execute(text(statement))
                logger.info("Added column %s.%s", table.name, column.name)
