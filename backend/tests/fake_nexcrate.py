"""Attrappe fuer nexcrates ``/api/v1`` auf HTTP-Ebene, nach den Antworten einer echten Wegwerf-Instanz
(nexcrate 0.1.0, Vertrag V5, gemessen am 22.09.2026).

Sie steht unter ``http.use_transport``, also laeuft der echte Client mit Kopfzeilen, Fehlerform und
Stromformat. Alles andere als ``nexcrate.test`` scheitert laut, wie in ``no_network``.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

HOST = "nexcrate.test"
URL = f"http://{HOST}:8390"
KEY = "nxc_test_key_only_for_tests_aaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
VERSION_ID = "v_0a0a0a0a"


def _error(status: int, code: str, message: str = "", **params: Any) -> httpx.Response:
    return httpx.Response(status, json={"code": code, "message": message or code, "params": params})


class FakeNexcrate:
    def __init__(self) -> None:
        self.installation_id = "install0a"
        self.key = KEY
        self.scopes = ["read", "request"]
        self.music = True
        self.music_version: dict[str, Any] | None = {"ready": True, "reasons": [], "tier": "lossless"}
        #: Alben und Kuenstler nach MBID. Ein Album: name, artist, versions (Liste), tracks.
        self.albums: dict[str, dict[str, Any]] = {}
        self.artists: dict[str, dict[str, Any]] = {}
        #: Studioalben eines Kuenstlers laut "MusicBrainz", fuer eine Kuenstleranfrage.
        self.studio: dict[str, list[str]] = {}
        #: Aenderungsmarke: je Titel (kind, mbid) die Nummer, Grabsteine extra.
        self.seq = 0
        self.changed: dict[tuple[str, str], int] = {}
        self.tombstones: dict[tuple[str, str], int] = {}
        self.oldest_marker = 0
        self.events: list[dict[str, Any]] = []
        self.pairings: dict[str, dict[str, Any]] = {}
        #: Naechste Antwort je "METHODE pfad" vorgeben, einmal verbraucht.
        self.next_answer: dict[str, httpx.Response | Exception] = {}
        self.calls: list[tuple[str, str, Any]] = []
        #: Antworten fuer andere Dienste im selben Test (etwa MusicBrainz), sonst scheitert jede Anfrage.
        self.other: Any = None

    # ---- Aufbau fuer Tests ----------------------------------------------------------

    def touch(self, kind: str, mbid: str) -> None:
        self.seq += 1
        self.changed[(kind, mbid)] = self.seq
        self.tombstones.pop((kind, mbid), None)

    def add_artist(self, mbid: str, name: str = "Example Artist", **artist: Any) -> None:
        self.artists[mbid] = {"name": name, "loading": False, **artist}
        self.touch("artist", mbid)

    def add_album(
        self,
        mbid: str,
        artist: str,
        *,
        state: str | None = None,
        have: int = 0,
        total: int = 10,
        monitored: bool = True,
        name: str = "Example Album",
    ) -> None:
        versions = [] if state is None else [{"state": state, "monitored": monitored}]
        self.albums[mbid] = {"name": name, "artist": artist, "versions": versions, "tracks": (have, total)}
        self.touch("album", mbid)

    def remove_artist(self, mbid: str) -> None:
        self.artists.pop(mbid, None)
        self.changed.pop(("artist", mbid), None)
        self.seq += 1
        self.tombstones[("artist", mbid)] = self.seq

    def event(self, type_: str, kind: str, mbid: str) -> None:
        self.events.append(
            {
                "seq": len(self.events) + 1,
                "type": type_,
                "at": "2026-09-22T06:00:00Z",
                "title": {"kind": kind, "ref": f"mbid:{mbid}", "name": "x"},
                "version_id": None,
                "origin": None,
                "download_id": None,
                "params": {},
            }
        )

    def requests_sent(self) -> list[dict[str, Any]]:
        return [body for method, path, body in self.calls if method == "POST" and path == "/api/v1/requests"]

    # ---- Formen wie /api/v1 --------------------------------------------------------

    def _album_title(self, mbid: str) -> dict[str, Any]:
        album = self.albums[mbid]
        have, total = album["tracks"]
        tracks = {"have": have, "total": total} if album["versions"] else None
        versions = [
            {
                "version_id": VERSION_ID,
                "state": v["state"],
                "monitored": v["monitored"],
                "size_bytes": None,
                "quality": None,
                "origin": None,
                "album": {"tracks": tracks},
            }
            for v in album["versions"]
        ]
        return {
            "kind": "album",
            "ref": f"mbid:{mbid}",
            "refs": [f"mbid:{mbid}"],
            "name": album["name"],
            "year": 2020,
            "poster_path": None,
            "origin": None,
            "monitored": bool(versions),
            "versions": versions,
            "tags": [],
            "album": {
                "artists": [{"ref": f"mbid:{album['artist']}", "name": "Example Artist"}],
                "type": "Album",
                "secondary_types": [],
                "group": "studio",
                "first_release_date": "2020-01-01",
                "cover_url": None,
                "target_release": None,
                "tracks": tracks,
                "media": [],
            },
        }

    def _artist_title(self, mbid: str, *, catalogue: bool) -> dict[str, Any]:
        artist = self.artists[mbid]
        own = [m for m, a in self.albums.items() if a["artist"] == mbid]
        watched = [m for m in own if any(v["monitored"] for v in self.albums[m]["versions"])]
        available = [m for m in watched if self.albums[m]["versions"][0]["state"] == "available"]
        return {
            "kind": "artist",
            "ref": f"mbid:{mbid}",
            "refs": [f"mbid:{mbid}"],
            "name": artist["name"],
            "year": 1990,
            "poster_path": None,
            "origin": None,
            "monitored": True,
            "versions": [],
            "tags": [],
            "artist": {
                "sort_name": artist["name"],
                "type": "Group",
                "country": "GB",
                "disambiguation": None,
                "new_albums": "all",
                "album_types": ["studio"],
                "albums": {
                    "total": len(own),
                    "watched": len(watched),
                    "available": len(available),
                    "missing": len(watched) - len(available),
                },
                "loading": artist["loading"],
                "catalogue": [self._album_title(m) for m in own] if catalogue else None,
            },
        }

    def _title(self, kind: str, mbid: str, *, catalogue: bool = True) -> dict[str, Any] | None:
        if kind == "album" and mbid in self.albums:
            return self._album_title(mbid)
        if kind == "artist" and mbid in self.artists:
            return self._artist_title(mbid, catalogue=catalogue)
        return None

    # ---- Adressen -------------------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.host != HOST and self.other is not None:
            return self.other(request)
        if request.url.host != HOST:
            raise AssertionError(f"Unexpected network access in a test: {request.method} {request.url}")
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, path, body))
        planned = self.next_answer.pop(f"{request.method} {path}", None)
        if isinstance(planned, Exception):
            raise planned
        if planned is not None:
            return planned
        if not path.startswith("/api/v1/"):
            return httpx.Response(404, json={"detail": {"code": "not_found", "message": "Not found."}})
        if path.startswith("/api/v1/pairing"):
            return self._pairing(request, path, body)
        if request.headers.get("authorization") != f"Bearer {self.key}":
            return _error(401, "api_key_invalid", "This key is not valid.")
        return self._route(request, path, body)

    def _route(self, request: httpx.Request, path: str, body: Any) -> httpx.Response:
        query = request.url.params
        if path == "/api/v1/system":
            return httpx.Response(
                200,
                json={
                    "app": "nexcrate",
                    "version": "0.1.0",
                    "contract": {"major": 1, "stage": "V5"},
                    "installation_id": self.installation_id,
                    "scopes": self.scopes,
                    "capabilities": {"music": self.music, "events": True, "stream": True},
                },
            )
        if path == "/api/v1/versions":
            items = []
            if self.music_version is not None:
                items.append(
                    {
                        "version_id": VERSION_ID,
                        "kind": "album",
                        "name": "Music",
                        "order": 1,
                        "tier": self.music_version["tier"],
                        "ready": self.music_version["ready"],
                        "reasons": [{"code": code, "params": {}} for code in self.music_version["reasons"]],
                    }
                )
            return httpx.Response(200, json={"items": items})
        if path == "/api/v1/requests":
            return self._request(body)
        if path == "/api/v1/titles/lookup":
            items = []
            for item in body["items"]:
                title = self._title(item["kind"], item["ref"].partition(":")[2])
                items.append(
                    {
                        "kind": item["kind"],
                        "ref": item["ref"],
                        "known": title is not None,
                        "title": title,
                        "error": None,
                    }
                )
            return httpx.Response(200, json={"items": items})
        if path == "/api/v1/titles":
            return self._list(int(query["after"]), query.get("kind"), int(query.get("limit", "500")))
        if path.startswith("/api/v1/titles/"):
            _, _, rest = path.partition("/api/v1/titles/")
            kind, _, ref = rest.partition("/")
            title = self._title(kind, ref.partition(":")[2])
            if title is None:
                return _error(404, "title_not_found", "nexcrate does not have this title.", kind=kind, ref=ref)
            return httpx.Response(200, json=title)
        if path == "/api/v1/events":
            after, limit = int(query["after"]), int(query.get("limit", "100"))
            items = [e for e in self.events if e["seq"] > after][:limit]
            return httpx.Response(
                200,
                json={
                    "items": items,
                    "next_after": items[-1]["seq"] if items else after,
                    "more": False,
                    "latest": len(self.events),
                },
            )
        if path == "/api/v1/events/stream":
            after = int(query["after"])
            lines = ["retry: 3000", ""]
            for event in (e for e in self.events if e["seq"] > after):
                lines += [f"id: {event['seq']}", f"event: {event['type']}", f"data: {json.dumps(event)}", ""]
            lines += [": keep-alive", ""]
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content="\n".join(lines).encode())
        return _error(404, "not_found", "This address does not exist.")

    def _list(self, after: int, kind: str | None, limit: int) -> httpx.Response:
        if after and after < self.oldest_marker:
            return _error(410, "marker_too_old", "This number is too old.")
        rows = sorted((seq, k, m) for (k, m), seq in self.changed.items() if seq > after and (kind in (None, k)))
        page = rows[:limit]
        items = [{**(self._title(k, m, catalogue=False) or {}), "seq": seq} for seq, k, m in page]
        removed = [
            {"kind": k, "ref": f"mbid:{m}", "seq": seq}
            for (k, m), seq in self.tombstones.items()
            if seq > after and kind in (None, k)
        ]
        more = len(rows) > limit
        next_after = page[-1][0] if more else max([after, self.seq] if rows or removed else [after])
        return httpx.Response(
            200, json={"items": items, "removed": removed, "next_after": next_after, "more": more, "latest": self.seq}
        )

    def _request(self, body: dict[str, Any]) -> httpx.Response:
        if "request" not in self.scopes:
            return _error(403, "scope_missing", "This key lacks a scope.", scope="request")
        mbid = body["ref"].partition(":")[2]
        if body["kind"] == "album":
            if self.music_version is None:
                return _error(409, "version_not_available", "No music version.")
            created = mbid not in self.albums
            if created:
                self.add_album(mbid, "99999999-9999-4999-8999-999999999999")
            album = self.albums[mbid]
            outcome = "unchanged" if album["versions"] else "added"
            if not album["versions"]:
                album["versions"] = [{"state": "wanted", "monitored": True}]
                self.touch("album", mbid)
            return httpx.Response(
                201 if created else 200,
                json={
                    "created": created,
                    "versions": [{"version_id": VERSION_ID, "outcome": outcome}],
                    "albums_watched": None,
                    "search": "queued",
                    "notes": [],
                    "title": self._album_title(mbid),
                },
            )
        created = mbid not in self.artists
        if created:
            self.add_artist(mbid)
        watched = 0
        for album_mbid in self.studio.get(mbid, []):
            if album_mbid not in self.albums:
                self.add_album(album_mbid, mbid)
            if not self.albums[album_mbid]["versions"]:
                self.albums[album_mbid]["versions"] = [{"state": "wanted", "monitored": True}]
                watched += 1
        return httpx.Response(
            201 if created else 200,
            json={
                "created": created,
                "versions": [],
                "albums_watched": watched,
                "search": "queued",
                "notes": [],
                "title": self._artist_title(mbid, catalogue=False),
            },
        )

    def _pairing(self, request: httpx.Request, path: str, body: Any) -> httpx.Response:
        if request.method == "POST":
            pairing_id = f"pair{len(self.pairings) + 1}"
            self.pairings[pairing_id] = {
                "state": "pending",
                "secret": "s3cret",
                "app": body["app"],
                "scopes": body["scopes"],
            }
            return httpx.Response(
                201,
                json={
                    "pairing_id": pairing_id,
                    "secret": "s3cret",
                    "code": "5Z3-M4G",
                    "expires_at": "2099-01-01T00:00:00Z",
                    "poll_seconds": 2,
                },
            )
        pairing_id = path.rsplit("/", 1)[1]
        pairing = self.pairings.get(pairing_id)
        if pairing is None or request.headers.get("x-pairing-secret") != pairing["secret"]:
            return _error(404, "pairing_not_found", "This pairing does not exist, or not any more.")
        state, key = pairing["state"], None
        if state == "confirmed":
            key = self.key
            pairing["state"] = "delivered"
        return httpx.Response(
            200,
            json={
                "state": state,
                "key": key,
                "scopes": pairing["scopes"] if key else None,
                "expires_at": "2099-01-01T00:00:00Z",
            },
        )
