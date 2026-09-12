"""Zugriff auf Lidarr (API v1).

⚠️ **nexbeat aendert keine Einstellungen in Lidarr.** Geschrieben wird nur, was
eine Anfrage braucht: einen Kuenstler anlegen, ein Album ueberwachen, eine Suche
anstossen. Profile, Benennung, Groessen und Verbindungen bleiben unberuehrt:
Die Sammlung gehoert dem Betreiber, nicht nexbeat.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from . import http
from .settings_service import AppSettings

logger = logging.getLogger("nexbeat.lidarr")

#: Beim Anlegen holt Lidarr die Metadaten ueber seinen eigenen Dienst, und der
#: ist dokumentiert langsam. 15 Sekunden reichen dafuer nicht.
SLOW_TIMEOUT = httpx.Timeout(90.0, connect=6.0)


class LidarrError(Exception):
    """``uncertain`` trennt "hat nicht geklappt" von "wissen wir nicht".

    Eine Zeitueberschreitung heisst nicht, dass nichts passiert ist. Nexview hat
    das erlebt: "fehlgeschlagen" vermerkt, waehrend Sonarr laengst suchte.
    """

    def __init__(self, code: str, detail: str = "", *, uncertain: bool = False, status_code: int | None = None) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.uncertain = uncertain
        self.status_code = status_code


class LidarrClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Any = None,
        json_body: Any = None,
        timeout: httpx.Timeout | None = None,
    ) -> Any:
        url = f"{self.base_url}/api/v1{path}"
        options: dict[str, Any] = {"params": params, "headers": {"X-Api-Key": self.api_key}}
        if json_body is not None:
            options["json"] = json_body
        if timeout is not None:
            options["timeout"] = timeout
        try:
            response = await http.client("lidarr", timeout=20.0).request(method, url, **options)
        except httpx.TimeoutException as error:
            raise LidarrError("lidarr_timeout", str(error), uncertain=True) from error
        except httpx.HTTPError as error:
            raise LidarrError("lidarr_unreachable", str(error)) from error
        if response.status_code in (401, 403):
            raise LidarrError("lidarr_key_rejected", status_code=response.status_code)
        if response.status_code == 404:
            raise LidarrError("lidarr_path_unknown", path, status_code=404)
        if response.status_code >= 400:
            logger.warning("Lidarr answered %s to %s %s: %s", response.status_code, method, path, response.text[:300])
            raise LidarrError("lidarr_http_error", response.text[:300], status_code=response.status_code)
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as error:
            raise LidarrError("lidarr_unexpected_answer", response.text[:200]) from error

    async def system_status(self) -> dict[str, Any]:
        return await self._request("GET", "/system/status") or {}

    async def quality_profiles(self) -> list[dict[str, Any]]:
        items = await self._request("GET", "/qualityprofile") or []
        return [{"id": item["id"], "name": item.get("name", "")} for item in items]

    async def metadata_profiles(self) -> list[dict[str, Any]]:
        """Alle Metadatenprofile mit dem, was sie zulassen. Der Name allein verraet das nicht."""
        items = await self._request("GET", "/metadataprofile") or []
        return [
            {"id": item["id"], "name": item.get("name", ""), **profile_summary(item), "studio_only": studio_only(item)}
            for item in items
        ]

    async def metadata_profile(self, profile_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/metadataprofile/{profile_id}") or {}

    async def root_folders(self) -> list[dict[str, Any]]:
        items = await self._request("GET", "/rootfolder") or []
        return [
            {
                "path": item.get("path", ""),
                "free_space": item.get("freeSpace"),
                "accessible": item.get("accessible", True),
            }
            for item in items
        ]

    async def artists(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/artist", timeout=SLOW_TIMEOUT) or []

    async def albums_for_artist(self, artist_id: int) -> list[dict[str, Any]]:
        return await self._request("GET", "/album", params={"artistId": artist_id}) or []

    async def albums_by_foreign_id(self, release_group_mbid: str) -> list[dict[str, Any]]:
        return await self._request("GET", "/album", params={"foreignAlbumId": release_group_mbid}) or []

    async def queue(self) -> list[dict[str, Any]]:
        """Was gerade laedt oder auf den Import wartet, je Eintrag mit ``artistId`` und ``albumId``."""
        data = await self._request("GET", "/queue", params={"page": 1, "pageSize": 1000}) or {}
        return data.get("records") or []

    async def lookup_artist(self, artist_mbid: str) -> dict[str, Any] | None:
        results = await self._request(
            "GET", "/artist/lookup", params={"term": f"lidarr:{artist_mbid}"}, timeout=SLOW_TIMEOUT
        )
        return next((item for item in results or [] if item.get("foreignArtistId") == artist_mbid), None)

    async def add_artist(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/artist", json_body=payload, timeout=SLOW_TIMEOUT) or {}

    async def monitor_albums(self, album_ids: list[int]) -> None:
        await self._request("PUT", "/album/monitor", json_body={"albumIds": album_ids, "monitored": True})

    async def search_albums(self, album_ids: list[int]) -> None:
        await self._request("POST", "/command", json_body={"name": "AlbumSearch", "albumIds": album_ids})

    async def update_artist(self, artist: dict[str, Any]) -> dict[str, Any]:
        """Das ganze Kuenstlerobjekt zurueck, wie Lidarr es beim Bearbeiten selbst tut."""
        return await self._request("PUT", f"/artist/{artist['id']}", json_body=artist, timeout=SLOW_TIMEOUT) or {}


def is_studio_album(album: dict[str, Any]) -> bool:
    """Ein Album ohne Zusatztyp: keine EP, keine Single, kein Live-Mitschnitt, keine Sammlung.

    "Studio" zaehlt nicht als Zusatztyp. Lidarr fuehrt es in den Profilen als Art.
    """
    names = [item.get("name") if isinstance(item, dict) else item for item in album.get("secondaryTypes") or []]
    extra = [name for name in names if name and str(name).casefold() != "studio"]
    return str(album.get("albumType") or "").casefold() == "album" and not extra


def _allowed(entries: Any) -> tuple[set[str], set[str]] | None:
    """Erlaubte und bekannte Typnamen eines Metadatenprofils, oder None bei fremdem Format."""
    if not isinstance(entries, list) or not entries:
        return None
    allowed: set[str] = set()
    known: set[str] = set()
    for entry in entries:
        kind = entry.get("albumType") if isinstance(entry, dict) else None
        name = kind.get("name") if isinstance(kind, dict) else None
        if not name:
            continue
        known.add(name.casefold())
        if entry.get("allowed"):
            allowed.add(name.casefold())
    return allowed, known


def type_allowed(profile: dict[str, Any], primary: str, secondary: list[str]) -> bool:
    """Laesst das Metadatenprofil diese Art Release zu? Unbekannte Namen blockieren nicht.

    Was das Profil ausschliesst, nimmt Lidarr nicht in die Alben eines Kuenstlers auf.
    Eine Anfrage dafuer liefe ins Leere.
    """
    primaries = _allowed(profile.get("primaryAlbumTypes"))
    if primaries is not None and primary:
        allowed, known = primaries
        if primary.casefold() in known and primary.casefold() not in allowed:
            return False
    secondaries = _allowed(profile.get("secondaryAlbumTypes"))
    if secondaries is not None:
        allowed, known = secondaries
        for name in [item.casefold() for item in secondary] or ["studio"]:
            if name in known and name not in allowed:
                return False
    return True


def profile_summary(profile: dict[str, Any]) -> dict[str, list[str]]:
    """Was ein Metadatenprofil zulaesst, mit Lidarrs Namen: Hauptarten, Zusatztypen, Status."""

    def names(entries: Any, field: str) -> list[str]:
        found: list[str] = []
        for entry in entries if isinstance(entries, list) else []:
            kind = entry.get(field) if isinstance(entry, dict) else None
            name = kind.get("name") if isinstance(kind, dict) else None
            if name and entry.get("allowed"):
                found.append(name)
        return found

    return {
        "primary": names(profile.get("primaryAlbumTypes"), "albumType"),
        "secondary": names(profile.get("secondaryAlbumTypes"), "albumType"),
        "statuses": names(profile.get("releaseStatuses"), "releaseStatus"),
    }


def studio_only(profile: dict[str, Any]) -> bool:
    """Laesst das Profil nur Studioalben zu, und nur offizielle?

    Nur dann bringt "Ganzer Kuenstler" mit ``monitorNewItems: all`` nichts anderes mit.
    12.09.2026: Mit einem Profil, das auch Live, Sammlungen und Bootlegs zuliess, legte
    "Ganzer Kuenstler" eine Band mit weit ueber tausend Alben an.
    """
    summary = profile_summary(profile)
    return (
        {name.casefold() for name in summary["primary"]} <= {"album"}
        and {name.casefold() for name in summary["secondary"]} <= {"studio"}
        and {name.casefold() for name in summary["statuses"]} <= {"official"}
    )


def client_for(settings: AppSettings) -> LidarrClient | None:
    if not settings.lidarr_configured:
        return None
    return LidarrClient(settings.text("lidarr_url"), settings.text("lidarr_api_key"))


def image_url(images: list[dict[str, Any]], *cover_types: str) -> str:
    """Die Adresse beim Bildanbieter. Die lokale ``url`` braeuchte den Lidarr-Schluessel.

    ⚠️ ``remoteUrl`` ist nicht immer eine Adresse im Netz. Gemessen am 11.09.2026:
    Bei gut der Haelfte der Poster stand ein lokaler Pfad darin, etwa
    ``/config/MediaCover/<id>/poster.jpg``. Den laedt kein Browser.
    """
    for cover_type in cover_types:
        for image in images:
            remote = str(image.get("remoteUrl") or "")
            if image.get("coverType") == cover_type and remote.startswith(("https://", "http://")):
                return remote
    return ""


def compact_album(album: dict[str, Any]) -> dict[str, Any]:
    """Nur was nexbeat braucht. Ein Lidarr-Album traegt sonst alle Releases mit."""
    return {
        "id": album.get("id"),
        "artistId": album.get("artistId"),
        "foreignAlbumId": album.get("foreignAlbumId"),
        "monitored": bool(album.get("monitored")),
        "statistics": album.get("statistics") or {},
    }
