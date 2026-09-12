"""Einstellungen aus der Umgebung, Praefix ``NEXBEAT_``.

Was der Betreiber im Betrieb aendert (Mail, Lidarr, Kontingente), steht in der
Datenbank, siehe ``services/settings_service.py``. Hier steht nur, was vor dem
ersten Start feststehen muss.
"""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import PrivateAttr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEXBEAT_",
        env_file=(PROJECT_DIR / ".env", BACKEND_DIR / ".env"),
        extra="ignore",
    )

    data_dir: Path = PROJECT_DIR / "data"
    secret_key: str = ""
    access_token_minutes: int = 30
    refresh_token_days: int = 30
    bcrypt_rounds: int = 12
    cookie_secure: str = "auto"
    disable_background: bool = False
    frontend_dist: Path = PROJECT_DIR / "frontend" / "dist"

    _remembered_key: str | None = PrivateAttr(default=None)

    @field_validator("data_dir", "frontend_dist")
    @classmethod
    def _relative_to_project(cls, value: Path) -> Path:
        # Ein relativer Pfad meint das Projekt, nicht das Verzeichnis, aus dem
        # zufaellig gestartet wurde. Sonst entsteht beim Start aus backend/
        # still eine zweite, leere Datenbank.
        return value if value.is_absolute() else PROJECT_DIR / value

    @property
    def database_path(self) -> Path:
        return self.data_dir / "nexbeat.db"

    def resolved_secret_key(self) -> str:
        if self.secret_key:
            return self.secret_key
        if self._remembered_key:
            return self._remembered_key
        self.data_dir.mkdir(parents=True, exist_ok=True)
        key_file = self.data_dir / "secret.key"
        if key_file.exists():
            self._remembered_key = key_file.read_text(encoding="utf-8").strip()
        else:
            self._remembered_key = secrets.token_urlsafe(48)
            key_file.write_text(self._remembered_key, encoding="utf-8")
        # ⚠️ Mit dieser Datei ist jedes gespeicherte Geheimnis lesbar. Windows
        # kennt keine Modusbits, dort ist ein Fehlschlag keiner.
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass
        return self._remembered_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
