"""Empfehlungen: "Fuer dich", "Weil du X hoerst" und Trends.

Grundlage sind aehnliche Kuenstler von ListenBrainz. Ausgangspunkte sind die
eigenen Anfragen und, taeglich wechselnd, Kuenstler aus dem Lidarr-Bestand. Was
Lidarr schon kennt, faellt heraus: Empfohlen wird, was neu waere.

"Fuer dich" zaehlt zusammen. Wer zu mehreren Ausgangskuenstlern passt, steht
weiter oben, und die Karte nennt, zu wem. Eigene Anfragen wiegen schwerer als
der Bestand, weil sie juenger sind und bewusster.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import defaultdict
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import COUNTED_STATUSES, LibraryArtist, MusicRequest, User, utcnow
from . import cache, catalog, coverart, listenbrainz
from .listenbrainz import ListenBrainzError
from .settings_service import AppSettings

logger = logging.getLogger("nexbeat.recommendations")

PERSONAL_SEEDS = 5
LIBRARY_SEEDS = 20
PERSONAL_WEIGHT = 1.5
ROW_SIZE = 18
MAX_SEED_ROWS = 4
MIN_ROW_ITEMS = 6
TTL_TRENDING = timedelta(hours=6)
TRENDING_ALBUMS_KEY = "lb:sitewide:release-groups:week"
TRENDING_ARTISTS_KEY = "lb:sitewide:artists:week"
WARM_PAUSE = 0.5
#: So viele Fehlschlaege in Folge, dann ist ListenBrainz vermutlich weg.
WARM_GIVE_UP_AFTER = 3


def daily_sample(items: list[str], count: int, salt: str) -> list[str]:
    """Taeglich wechselnd, aber am selben Tag stabil. Neu laden mischt nicht neu."""
    return sorted(items, key=lambda item: hashlib.sha256(f"{salt}:{item}".encode()).hexdigest())[:count]


def _requested_artists(db: Session, user: User) -> list[tuple[str, str]]:
    rows = db.execute(
        select(MusicRequest.artist_mbid, MusicRequest.artist_name)
        .where(MusicRequest.user_id == user.id, MusicRequest.status.in_(COUNTED_STATUSES))
        .order_by(MusicRequest.requested_at.desc())
        .limit(50)
    ).all()
    seen: dict[str, str] = {}
    for mbid, name in rows:
        seen.setdefault(mbid, name)
    return list(seen.items())


def _artist_item(mbid: str, name: str, known: set[str], reasons: list[str] | None = None) -> dict[str, Any]:
    return {
        "mbid": mbid,
        "name": name,
        "image": catalog.artist_image_path(mbid, name),
        "in_library": mbid in known,
        "reasons": reasons or [],
    }


def build_mix(
    similar: dict[str, list[dict[str, Any]]], personal: set[str], known: set[str], names: dict[str, str]
) -> list[dict[str, Any]]:
    scores: dict[str, float] = defaultdict(float)
    reasons: dict[str, list[str]] = defaultdict(list)
    labels: dict[str, str] = {}
    for seed, items in similar.items():
        top = items[:40]
        if not top:
            continue
        best = max(item["score"] for item in top) or 1.0
        weight = PERSONAL_WEIGHT if seed in personal else 1.0
        for item in top:
            mbid = item["mbid"]
            if mbid in known or mbid in similar:
                continue
            scores[mbid] += weight * item["score"] / best
            labels.setdefault(mbid, item["name"])
            if seed not in reasons[mbid]:
                reasons[mbid].append(seed)
    ranked = sorted(scores, key=lambda mbid: (-scores[mbid], labels[mbid].casefold()))[:ROW_SIZE]
    return [
        _artist_item(mbid, labels[mbid], known, [names.get(seed, "") for seed in reasons[mbid][:2] if names.get(seed)])
        for mbid in ranked
    ]


async def trending(db: Session, settings: AppSettings) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    token = settings.text("listenbrainz_token")

    async def albums_source() -> list[dict[str, Any]]:
        return await listenbrainz.sitewide_release_groups(40, token=token)

    async def artists_source() -> list[dict[str, Any]]:
        return await listenbrainz.sitewide_artists(40, token=token)

    albums = await catalog.optional(
        cache.cached(db, TRENDING_ALBUMS_KEY, TTL_TRENDING, albums_source), "listenbrainz"
    )
    artists = await catalog.optional(
        cache.cached(db, TRENDING_ARTISTS_KEY, TTL_TRENDING, artists_source), "listenbrainz"
    )
    return albums or [], artists or []


async def home(db: Session, settings: AppSettings, user: User) -> dict[str, Any]:
    library_rows = list(db.scalars(select(LibraryArtist)))
    known = {row.mbid for row in library_rows}
    names = {row.mbid: row.name for row in library_rows}
    requested = _requested_artists(db, user)
    for mbid, name in requested:
        names.setdefault(mbid, name)

    personal = [mbid for mbid, _name in requested][:PERSONAL_SEEDS]
    candidates = [row.mbid for row in library_rows if row.track_file_count > 0]
    daily = daily_sample(candidates, LIBRARY_SEEDS, f"{user.id}:{utcnow().date().isoformat()}")
    rows: list[dict[str, Any]] = []

    if settings.flag("source_listenbrainz"):
        seeds = list(dict.fromkeys(personal + daily))
        similar = await catalog.optional(catalog.similar_for(db, seeds), "listenbrainz") or {}
        mix = build_mix(similar, set(personal), known, names)
        if mix:
            rows.append({"id": "for_you", "kind": "artists", "title_key": "discover.forYou", "items": mix})

        seed_rows = 0
        for seed in list(dict.fromkeys(personal + daily)):
            if seed_rows >= MAX_SEED_ROWS:
                break
            items = [
                _artist_item(item["mbid"], item["name"], known)
                for item in similar.get(seed, [])
                if item["mbid"] not in known
            ][:ROW_SIZE]
            if len(items) < MIN_ROW_ITEMS or not names.get(seed):
                continue
            rows.append(
                {
                    "id": f"because:{seed}",
                    "kind": "artists",
                    "title_key": "discover.becauseYouListen",
                    "params": {"name": names[seed], "mbid": seed},
                    "items": items,
                }
            )
            seed_rows += 1

        albums, artists = await trending(db, settings)
        if albums:
            states = catalog.request_states(db, user, [item["mbid"] for item in albums])
            rows.append(
                {
                    "id": "trending_albums",
                    "kind": "albums",
                    "title_key": "discover.trendingAlbums",
                    "items": [
                        {
                            **item,
                            "cover": item["cover"] or coverart.release_group_front(item["mbid"], 250),
                            "request": states.get(item["mbid"]),
                        }
                        for item in albums[:ROW_SIZE]
                    ],
                }
            )
        if artists:
            rows.append(
                {
                    "id": "trending_artists",
                    "kind": "artists",
                    "title_key": "discover.trendingArtists",
                    "items": [_artist_item(item["mbid"], item["name"], known) for item in artists[:ROW_SIZE]],
                }
            )

    return {
        "rows": rows,
        "library_size": len(known),
        "has_seeds": bool(personal or candidates),
        "requests_enabled": settings.requests_ready,
    }


async def warm(db: Session, settings: AppSettings, pause: float = WARM_PAUSE) -> int:
    """Im Hintergrund vorladen, damit die Startseite aus dem Speicher kommt.

    Ein Kuenstler nach dem anderen, mit Pause dazwischen. ListenBrainz taugt nur
    fuer einzelne Abfragen, siehe ``listenbrainz``.
    """
    if not settings.flag("source_listenbrainz"):
        return 0
    seeds = list(db.scalars(select(LibraryArtist.mbid).where(LibraryArtist.track_file_count > 0)))
    missing = [seed for seed in seeds if cache.read(db, catalog.similar_key(seed)) is None]
    loaded = 0
    failed_in_a_row = 0
    for seed in missing:
        try:
            await catalog.similar_for(db, [seed])
        except ListenBrainzError:
            failed_in_a_row += 1
            if failed_in_a_row >= WARM_GIVE_UP_AFTER:
                logger.info("Recommendation warm-up stopped, ListenBrainz does not answer")
                break
        else:
            loaded += 1
            failed_in_a_row = 0
        await asyncio.sleep(pause)
    await trending(db, settings)
    logger.info("Recommendation warm-up loaded %d of %d seeds", loaded, len(seeds))
    return loaded
