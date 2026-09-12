"""ListenBrainz: aehnliche Kuenstler, Trends, beliebteste Alben eines Kuenstlers.

Groesstenteils ohne Schluessel nutzbar. Die aehnlichen Kuenstler kommen von
``labs``, einem Versuchsgelaende ohne Stabilitaetszusage. Deshalb liegt jedes
Ergebnis eine Woche im Zwischenspeicher, und ein Ausfall leert nur den Abschnitt.

⚠️ Ein Aufruf je Kuenstler. Gemessen am 11.09.2026: ``artist_mbids`` laesst sich
zwar mehrfach uebergeben (mit Komma kommt ``400``), die Antwort taugt dann aber
nicht. Bei drei Kuenstlern kamen 299 Zeilen: einer bekam 152 Zeilen fuer 100
Kuenstler, die anderen 90 von 99 und 57 von 100.

Auch die Wochenlisten fuehren einen Eintrag manchmal doppelt. Jede Liste wird
deshalb auf eine Zeile je Kennung gekuerzt.

Seit 12.09.2026 gibt die API die Beliebtheit einzelner Kuenstler teils nur noch mit
Token heraus. Der Betreiber kann einen Schluessel hinterlegen. Er geht nur an die
API, nie an ``labs``.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from . import coverart, http

logger = logging.getLogger("nexbeat.listenbrainz")

LABS_URL = "https://labs.api.listenbrainz.org"
API_URL = "https://api.listenbrainz.org/1"
SIMILAR_ALGORITHM = "session_based_days_7500_session_300_contribution_5_threshold_10_limit_100_filter_True_skip_30"


class ListenBrainzError(Exception):
    def __init__(self, code: str = "listenbrainz_unavailable") -> None:
        super().__init__(code)
        self.code = code


async def _get(url: str, params: Any, token: str = "") -> Any:
    headers = {"Authorization": f"Token {token}"} if token else None
    try:
        response = await http.client("listenbrainz", timeout=30.0).get(url, params=params, headers=headers)
    except httpx.HTTPError as error:
        logger.info("ListenBrainz unreachable: %s", error)
        raise ListenBrainzError() from error
    if response.status_code == 204:
        return None
    if response.status_code == 401:
        # 12.09.2026 gemessen: Die Beliebtheit einzelner Kuenstler gibt ListenBrainz
        # teils nur noch mit Token heraus, wegen "bad actors and AI scrapers". Ein
        # falsches Token bekommt dieselbe 401 wie gar keins.
        logger.info("ListenBrainz refused %s, token sent: %s", url, bool(token))
        raise ListenBrainzError("listenbrainz_token_rejected" if token else "listenbrainz_token_required")
    if response.status_code >= 400:
        logger.info("ListenBrainz answered %s for %s", response.status_code, url)
        raise ListenBrainzError()
    try:
        return response.json()
    except ValueError as error:
        raise ListenBrainzError() from error


def _rows_with(data: Any, key: str) -> list[dict[str, Any]]:
    """Alle Eintraege mit diesem Feld, egal wie tief die Antwort verschachtelt ist."""
    found: list[dict[str, Any]] = []
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, list):
            stack.extend(reversed(item))
        elif isinstance(item, dict):
            if key in item:
                found.append(item)
            else:
                stack.extend(item.values())
    return found


def _first_of_each(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Jede Kennung einmal. Die Listen kommen nach Hoerzahl sortiert, die erste Zeile zaehlt."""
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        if item["mbid"] not in seen:
            seen.add(item["mbid"])
            unique.append(item)
    return unique


async def validate_token(token: str) -> dict[str, Any]:
    """Prueft einen Schluessel. Gemessen am 12.09.2026: Ein falscher gibt 200 mit ``valid: false``."""
    data = await _get(f"{API_URL}/validate-token", None, token) or {}
    return {"valid": data.get("valid") is True, "user_name": data.get("user_name") or ""}


async def similar_artists(seed_mbid: str) -> list[dict[str, Any]]:
    """Die aehnlichen Kuenstler zu einem Kuenstler, nach Score absteigend, ohne ihn selbst.

    Steht ein Kuenstler mehrfach in der Antwort, zaehlt sein bester Score.
    """
    params = [("algorithm", SIMILAR_ALGORITHM), ("artist_mbids", seed_mbid)]
    data = await _get(f"{LABS_URL}/similar-artists/json", params)
    best: dict[str, dict[str, Any]] = {}
    for row in _rows_with(data, "artist_mbid"):
        mbid = row.get("artist_mbid")
        if not mbid or mbid == seed_mbid or (row.get("reference_mbid") or seed_mbid) != seed_mbid:
            continue
        score = float(row.get("score") or 0)
        if mbid not in best or score > best[mbid]["score"]:
            best[mbid] = {"mbid": mbid, "name": row.get("name") or "", "score": score}
    return sorted(best.values(), key=lambda item: -item["score"])


async def sitewide_artists(count: int = 40, range_: str = "week", token: str = "") -> list[dict[str, Any]]:
    data = await _get(f"{API_URL}/stats/sitewide/artists", {"count": count, "range": range_}, token) or {}
    payload = data.get("payload") or {}
    return _first_of_each(
        [
            {
                "mbid": item.get("artist_mbid") or "",
                "name": item.get("artist_name") or "",
                "listen_count": int(item.get("listen_count") or 0),
            }
            for item in payload.get("artists") or []
            if item.get("artist_mbid")
        ]
    )


async def sitewide_release_groups(count: int = 40, range_: str = "week", token: str = "") -> list[dict[str, Any]]:
    data = await _get(f"{API_URL}/stats/sitewide/release-groups", {"count": count, "range": range_}, token) or {}
    payload = data.get("payload") or {}
    result = []
    for item in payload.get("release_groups") or []:
        mbid = item.get("release_group_mbid")
        if not mbid:
            continue
        artists = item.get("artist_mbids") or [""]
        result.append(
            {
                "mbid": mbid,
                "title": item.get("release_group_name") or "",
                "artist_mbid": artists[0] if artists else "",
                "artist_name": item.get("artist_name") or "",
                "listen_count": int(item.get("listen_count") or 0),
                "cover": coverart.release_image(item.get("caa_release_mbid"), item.get("caa_id")),
            }
        )
    return _first_of_each(result)


async def top_release_groups(artist_mbid: str, token: str = "") -> list[dict[str, Any]]:
    data = await _get(f"{API_URL}/popularity/top-release-groups-for-artist/{artist_mbid}", None, token) or []
    items = data if isinstance(data, list) else data.get("payload") or []
    result = []
    for item in items:
        mbid = item.get("release_group_mbid")
        if not mbid:
            continue
        group = item.get("release_group") or {}
        result.append(
            {
                "mbid": mbid,
                "title": group.get("name") or "",
                "type": group.get("type") or "",
                "date": group.get("date") or "",
                "listen_count": int(item.get("total_listen_count") or 0),
                "user_count": int(item.get("total_user_count") or 0),
                "cover": coverart.release_image(group.get("caa_release_mbid"), group.get("caa_id")),
                # Wem die Release-Group gehoert. ListenBrainz zaehlt auch fremde Alben mit, auf
                # denen der Kuenstler nur mitsingt (gemessen am 12.09.2026).
                "artist_mbids": [
                    credit.get("artist_mbid")
                    for credit in (item.get("artist") or {}).get("artists") or []
                    if credit.get("artist_mbid")
                ],
            }
        )
    return _first_of_each(result)
