"""Was ein Metadatenprofil in Lidarr zulaesst, und wann es nur Studioalben sind.

12.09.2026: Mit einem Profil, das auch Live, Sammlungen und Bootlegs zuliess, legte
"Ganzer Kuenstler" eine Band mit weit ueber tausend Alben an. Seitdem zeigt nexbeat, was ein Profil
zulaesst, und nimmt fuer ganze Kuenstler nur eines, das allein Studioalben zulaesst.
"""

from __future__ import annotations

import asyncio

import httpx

from app.services import http
from app.services.lidarr import LidarrClient, profile_summary, studio_only

STANDARD = {
    "primaryAlbumTypes": [
        {"albumType": {"name": "Album"}, "allowed": True},
        {"albumType": {"name": "EP"}, "allowed": False},
    ],
    "secondaryAlbumTypes": [
        {"albumType": {"name": "Studio"}, "allowed": True},
        {"albumType": {"name": "Live"}, "allowed": False},
    ],
    "releaseStatuses": [
        {"releaseStatus": {"name": "Official"}, "allowed": True},
        {"releaseStatus": {"name": "Bootleg"}, "allowed": False},
    ],
}
WIDE = {
    "primaryAlbumTypes": [{"albumType": {"name": "Album"}, "allowed": True}],
    "secondaryAlbumTypes": [
        {"albumType": {"name": "Studio"}, "allowed": True},
        {"albumType": {"name": "Live"}, "allowed": True},
        {"albumType": {"name": "Compilation"}, "allowed": True},
    ],
    "releaseStatuses": [{"releaseStatus": {"name": "Official"}, "allowed": True}],
}


def test_studio_only_means_albums_without_extras_and_only_official() -> None:
    assert studio_only(STANDARD)
    assert profile_summary(STANDARD) == {"primary": ["Album"], "secondary": ["Studio"], "statuses": ["Official"]}
    assert not studio_only(WIDE)
    bootlegs = [{"releaseStatus": {"name": "Official"}, "allowed": True}, {"releaseStatus": {"name": "Bootleg"}, "allowed": True}]
    assert not studio_only({**STANDARD, "releaseStatuses": bootlegs})
    eps = [{"albumType": {"name": "Album"}, "allowed": True}, {"albumType": {"name": "EP"}, "allowed": True}]
    assert not studio_only({**STANDARD, "primaryAlbumTypes": eps})


def test_lidarr_metadata_profiles_say_what_they_allow() -> None:
    profiles = [{"id": 1, "name": "Standard", **STANDARD}, {"id": 3, "name": "Wide", **WIDE}]
    http.use_transport(httpx.MockTransport(lambda _request: httpx.Response(200, json=profiles)))

    listed = asyncio.run(LidarrClient("http://lidarr.test", "key").metadata_profiles())
    assert [(item["id"], item["name"], item["studio_only"]) for item in listed] == [(1, "Standard", True), (3, "Wide", False)]
    assert listed[1]["secondary"] == ["Studio", "Live", "Compilation"]
