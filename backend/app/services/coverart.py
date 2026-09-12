"""Bildadressen beim Cover Art Archive.

Die Adressen leiten weiter (``307`` nach archive.org). Der Browser folgt dem
selbst, nexbeat muss dafuer nichts abfragen.
"""

from __future__ import annotations


def release_group_front(release_group_mbid: str, size: int = 500) -> str:
    return f"https://coverartarchive.org/release-group/{release_group_mbid}/front-{size}"


def release_image(release_mbid: str | None, caa_id: int | str | None, size: int = 250) -> str:
    if not release_mbid or not caa_id:
        return ""
    return f"https://coverartarchive.org/release/{release_mbid}/{caa_id}-{size}.jpg"
