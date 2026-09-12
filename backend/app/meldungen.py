"""Fehlerantworten mit Kennung.

⚠️ **Das Backend uebersetzt nicht, es benennt.** Die Sprache der Oberflaeche
kennt nur der Browser. Jede Meldung traegt deshalb eine Kennung, den Satz baut
das Frontend aus ``errors.byCode`` in ``de.json`` und ``en.json``.

Der englische Text dahinter ist der Rueckfall fuer alles, was die API ohne die
Oberflaeche benutzt. ``tests/test_fehlercodes.py`` prueft, dass jede Kennung in
beiden Sprachen uebersetzt ist.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def meldung(code: str, text: str, **values: Any) -> dict[str, Any]:
    return {"code": code, "message": text, **values}


def fehler(code: str, text: str, status_code: int = 400, **values: Any) -> HTTPException:
    return HTTPException(status_code=status_code, detail=meldung(code, text, **values))
