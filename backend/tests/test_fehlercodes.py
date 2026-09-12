"""Jede Kennung, die der Server schicken kann, hat eine Uebersetzung in beiden Sprachen.

Ohne diesen Waechter stuende in der Oberflaeche der englische Rueckfall, und
niemand merkte es, bis jemand die deutsche Oberflaeche benutzt.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
I18N = Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n"

PATTERNS = [
    re.compile(
        r"\b(?:fehler|meldung|LidarrError|MusicBrainzError|RequestProblem|MailError|SettingsError)\(\s*"
        r'"([a-z][a-z0-9_]+)"'
    ),
    re.compile(r'_fail\(\s*db,\s*request,\s*"([a-z][a-z0-9_]+)"'),
]
# Kennungen, die nicht als erstes Argument dastehen: Vorgaben im Konstruktor,
# bedingte Ausdruecke und gespeicherte Zustaende.
EXTRA = {
    "listenbrainz_unavailable",
    "listenbrainz_token_required",
    "listenbrainz_token_rejected",
    "deezer_unavailable",
    "dry_run",
    "lidarr_pending",
    "mail_host_unknown",
    "mail_connect_failed",
    "musicbrainz_error",
}


def codes_in_source() -> set[str]:
    found: set[str] = set()
    for path in APP.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in PATTERNS:
            found.update(pattern.findall(text))
    return found | EXTRA


def by_code(language: str) -> dict[str, str]:
    return json.loads((I18N / f"{language}.json").read_text(encoding="utf-8"))["errors"]["byCode"]


def test_every_code_is_translated_in_both_languages() -> None:
    codes = codes_in_source()
    # Bodenschwelle: Ein kaputtes Suchmuster faende sonst nichts und bestuende.
    assert len(codes) >= 45, sorted(codes)
    for language in ("de", "en"):
        translated = by_code(language)
        assert sorted(code for code in codes if code not in translated) == [], language


def test_translations_are_not_empty() -> None:
    for language in ("de", "en"):
        assert [code for code, text in by_code(language).items() if not text.strip()] == []
