"""Arten von Alben, die ein ganzer Kuenstler im NEX-Modus bringt.

Die Namen sind nexcrates Gruppen (``artist.types`` in ``POST /api/v1/requests``): Primaertyp und erster
Zusatztyp aus MusicBrainz, ``studio`` ist ein Album ohne Zusatztyp. Im ARR-Modus entscheidet Lidarrs
Metadatenprofil, dort gibt es nur Studioalben.
"""

from __future__ import annotations

from collections.abc import Iterable

#: In der Reihenfolge von nexcrates Kuenstlerseite.
GROUPS = ("studio", "ep", "single", "live", "compilation", "soundtrack", "remix", "spoken", "other")
#: Ab Werk, und was ein ganzer Kuenstler im ARR-Modus immer bringt.
DEFAULT = ("studio",)


def clean(values: Iterable[str]) -> list[str]:
    """Bekannte Arten ohne Doppelte, in der Reihenfolge von ``GROUPS``. Leer oder unbekannt: ValueError."""
    chosen = {str(value).strip() for value in values}
    chosen.discard("")
    if not chosen or not chosen <= set(GROUPS):
        raise ValueError("unknown or no album types")
    return [group for group in GROUPS if group in chosen]


def parse(text: str) -> list[str]:
    """Gespeichert als Text mit Kommas; leer heisst ``DEFAULT``."""
    try:
        return clean(text.split(","))
    except ValueError:
        return list(DEFAULT)


def as_text(values: Iterable[str]) -> str:
    return ",".join(clean(values))
