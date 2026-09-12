"""Attrappe fuer Lidarr: haelt Kuenstler und Alben im Speicher und schreibt jeden Aufruf mit."""

from __future__ import annotations

from typing import Any

from app.services import lidarr

WRITE_CALLS = ("add_artist", "update_artist", "monitor_albums", "search_albums")


class FakeLidarr:
    def __init__(self) -> None:
        self.artist_rows: list[dict[str, Any]] = []
        self.album_rows: list[dict[str, Any]] = []
        self.queue_rows: list[dict[str, Any]] = []
        self.calls: list[tuple[Any, ...]] = []
        self.fail_with: dict[str, Exception] = {}
        self.profile: dict[str, Any] = {
            "id": 1,
            "name": "Standard",
            "primaryAlbumTypes": [
                {"albumType": {"name": "Album"}, "allowed": True},
                {"albumType": {"name": "EP"}, "allowed": False},
                {"albumType": {"name": "Single"}, "allowed": False},
            ],
            "secondaryAlbumTypes": [
                {"albumType": {"name": "Studio"}, "allowed": True},
                {"albumType": {"name": "Live"}, "allowed": False},
            ],
        }
        #: Weitere Profile nach Kennung. Jede andere Kennung bekommt ``profile``.
        self.profiles: dict[int, dict[str, Any]] = {}

    def _step(self, name: str, *args: Any) -> None:
        self.calls.append((name, *args))
        error = self.fail_with.get(name)
        if error is not None:
            raise error

    def writes(self) -> list[str]:
        return [call[0] for call in self.calls if call[0] in WRITE_CALLS]

    async def system_status(self) -> dict[str, Any]:
        self._step("system_status")
        return {"version": "3.1.0.0"}

    async def quality_profiles(self) -> list[dict[str, Any]]:
        return [{"id": 1, "name": "Lossless"}]

    async def metadata_profiles(self) -> list[dict[str, Any]]:
        # Wie der echte Client: mit dem, was das Profil zulaesst.
        summary = lidarr.profile_summary(self.profile)
        return [{"id": 1, "name": "Standard", **summary, "studio_only": lidarr.studio_only(self.profile)}]

    async def metadata_profile(self, profile_id: int) -> dict[str, Any]:
        self._step("metadata_profile", profile_id)
        return self.profiles.get(profile_id, self.profile)

    async def root_folders(self) -> list[dict[str, Any]]:
        return [{"path": "/music", "free_space": 1, "accessible": True}]

    async def artists(self) -> list[dict[str, Any]]:
        self._step("artists")
        return list(self.artist_rows)

    async def lookup_artist(self, artist_mbid: str) -> dict[str, Any] | None:
        self._step("lookup_artist", artist_mbid)
        return {"foreignArtistId": artist_mbid, "artistName": "Test Artist", "images": []}

    async def add_artist(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._step("add_artist", payload)
        created = {**payload, "id": 501}
        # Wie Lidarr (AddArtistService): Mit monitor "none" wird der Kuenstler nie
        # ueberwacht, egal was in "monitored" steht. Gemessen am 12.09.2026.
        if (payload.get("addOptions") or {}).get("monitor") == "none":
            created["monitored"] = False
        self.artist_rows.append(created)
        return created

    async def update_artist(self, artist: dict[str, Any]) -> dict[str, Any]:
        self._step("update_artist", artist)
        self.artist_rows = [{**row, **artist} if row.get("id") == artist.get("id") else row for row in self.artist_rows]
        return artist

    async def albums_for_artist(self, artist_id: int) -> list[dict[str, Any]]:
        self._step("albums_for_artist", artist_id)
        return [album for album in self.album_rows if album["artistId"] == artist_id]

    async def albums_by_foreign_id(self, release_group_mbid: str) -> list[dict[str, Any]]:
        self._step("albums_by_foreign_id", release_group_mbid)
        return [album for album in self.album_rows if album["foreignAlbumId"] == release_group_mbid]

    async def queue(self) -> list[dict[str, Any]]:
        self._step("queue")
        return list(self.queue_rows)

    async def monitor_albums(self, album_ids: list[int]) -> None:
        self._step("monitor_albums", album_ids)

    async def search_albums(self, album_ids: list[int]) -> None:
        self._step("search_albums", album_ids)
