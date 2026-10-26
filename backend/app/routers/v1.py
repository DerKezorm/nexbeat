"""Die zugesagte Schnittstelle unter ``/api/v1``, fuer Skripte und Dashboards wie nexdeck.

⚠️ **Was hier steht, ist ein Versprechen.** Solange ``v1`` in der Adresse steht, aendert sich an diesen
Antworten nichts, was Bestehendes bricht. Alles andere unter ``/api/...`` ist Innenteil der Oberflaeche
und darf sich mit ihr aendern. Gebaut wie in Nexview.

Die Flaeche ist bewusst klein: herausfinden, was man darf, etwas zaehlen, suchen, anfragen, und fuer
Admins freigeben oder ablehnen. Einstellungen und Benutzer sind nicht dabei; sie zu versprechen hiesse,
das Konfigurationsmodell einzufrieren.

⚠️ **Die Handler sind dieselben.** Suchen, Anfragen und Freigeben werden nicht nachgebaut, sondern ein
zweites Mal eingehaengt. Damit kann v1 nicht vom Innenteil abweichen. Neu sind nur ``me`` und
``dashboard``, weil es die vorher nicht gab.

Die Rechte kommen aus dem Konto: Ein Token erbt die seines Besitzers, mit "nur lesen" gehen nur GETs.
Englisch, weil es nach aussen geht.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import func, select

from .. import __version__
from ..deps import CurrentUser, DbSession, key_of_request
from ..models import LibraryArtist, MusicRequest, RequestStatus, utcnow
from ..services.settings_service import load_settings
from . import catalog, requests

router = APIRouter(prefix="/api/v1", tags=["v1"])

#: Was ``may`` in ``/api/v1/me`` enthalten kann.
MAY_REQUEST = "request"
MAY_SEE_ALL = "see_all"
MAY_DECIDE = "decide"


class AccountOut(BaseModel):
    id: int
    username: str
    display_name: str
    role: str


class KeyOut(BaseModel):
    name: str
    read_only: bool


class MeV1Out(BaseModel):
    version: str
    account: AccountOut
    #: The API token this request came with, or null for a browser session.
    key: KeyOut | None
    #: What this account together with this token may do: ``request``, ``see_all``, ``decide``.
    may: list[str]


class RequestCountsOut(BaseModel):
    waiting: int
    running: int
    failed: int
    done_last_7_days: int


class LibraryOut(BaseModel):
    artists: int
    artists_with_music: int
    albums: int


class DashboardOut(BaseModel):
    version: str
    #: ``all`` for administrators, ``mine`` for everybody else: whose requests are counted.
    scope: str
    #: Where requests go: ``lidarr``, ``nexcrate`` or null while nothing is set up.
    target: str | None
    requests_enabled: bool
    requests: RequestCountsOut
    library: LibraryOut


@router.get(
    "/me",
    response_model=MeV1Out,
    summary="Who this token is and what it may do",
    description=(
        "The account behind the token and what the token may do with it. `may` folds the account's role and "
        "the token's read-only flag together: `decide` is there only when the account is an administrator "
        "**and** the token may write. Build buttons on `may`, not on the role."
    ),
)
def me(request: Request, user: CurrentUser) -> MeV1Out:
    key = key_of_request(request)
    writes = key is None or not key.read_only
    may: list[str] = []
    if writes:
        may.append(MAY_REQUEST)
    if user.is_admin:
        may.append(MAY_SEE_ALL)
        if writes:
            may.append(MAY_DECIDE)
    return MeV1Out(
        version=__version__,
        account=AccountOut(id=user.id, username=user.username, display_name=user.display_name, role=user.role.value),
        key=KeyOut(name=key.name, read_only=key.read_only) if key else None,
        may=may,
    )


@router.get(
    "/dashboard",
    response_model=DashboardOut,
    summary="Numbers for a dashboard tile",
    description=(
        "Requests by state and the size of the library, in one call. Administrators get the counts of the "
        "whole installation (`scope: all`), everybody else those of their own requests (`scope: mine`). "
        "`running` means approved or searching; `done_last_7_days` counts requests completed in the last "
        "seven days."
    ),
)
def dashboard(user: CurrentUser, db: DbSession) -> DashboardOut:
    settings = load_settings(db)
    query = select(MusicRequest.status, func.count(MusicRequest.id)).group_by(MusicRequest.status)
    done_query = select(func.count(MusicRequest.id)).where(
        MusicRequest.status == RequestStatus.downloaded,
        MusicRequest.completed_at >= utcnow() - timedelta(days=7),
    )
    if not user.is_admin:
        query = query.where(MusicRequest.user_id == user.id)
        done_query = done_query.where(MusicRequest.user_id == user.id)
    by_status: dict[Any, int] = {status: int(count) for status, count in db.execute(query)}
    library = db.execute(
        select(
            func.count(LibraryArtist.mbid),
            func.count(LibraryArtist.mbid).filter(LibraryArtist.track_file_count > 0),
            func.coalesce(func.sum(LibraryArtist.album_count), 0),
        )
    ).one()
    return DashboardOut(
        version=__version__,
        scope="all" if user.is_admin else "mine",
        target=settings.target,
        requests_enabled=settings.requests_ready,
        requests=RequestCountsOut(
            waiting=by_status.get(RequestStatus.pending_approval, 0),
            running=by_status.get(RequestStatus.approved, 0) + by_status.get(RequestStatus.searching, 0),
            failed=by_status.get(RequestStatus.failed, 0),
            done_last_7_days=int(db.scalar(done_query) or 0),
        ),
        library=LibraryOut(artists=int(library[0]), artists_with_music=int(library[1]), albums=int(library[2])),
    )


# --- Dieselben Handler wie im Innenteil ---------------------------------------------------------------

router.add_api_route(
    "/search/artists", catalog.search_artists, methods=["GET"],
    summary="Search artists",
    description="Artists from MusicBrainz by name, marked when they are in the library.",
)
router.add_api_route(
    "/search/albums", catalog.search_albums, methods=["GET"],
    summary="Search albums, EPs and singles",
    description="Release groups from MusicBrainz by name, with their request and library state.",
)
router.add_api_route(
    "/requests/mine", requests.my_requests, methods=["GET"],
    summary="The account's own requests",
    description="Newest first, at most 200.",
)
router.add_api_route(
    "/requests", requests.create_request, methods=["POST"], status_code=201,
    summary="Request an album, EP or single",
    description=(
        "Body: `{\"release_group_mbid\": \"…\"}`. Counts against the account's quota. Needs a token that may "
        "write."
    ),
)
router.add_api_route(
    "/requests/artist", requests.create_artist_request, methods=["POST"], status_code=201,
    summary="Request every album of an artist in the chosen types",
    description=(
        "Body: `{\"artist_mbid\": \"…\", \"types\": [\"studio\", \"live\"]}`. Future releases are included. "
        "`types` may be left out, then the administrator's default applies, studio albums unless changed. "
        "Known types: `studio`, `ep`, `single`, `live`, `compilation`, `soundtrack`, `remix`, `spoken`, "
        "`other`. Only nexcrate takes a choice; with Lidarr it is studio albums. Needs a token that may write."
    ),
)
router.add_api_route(
    "/requests/{request_id}/cancel", requests.cancel_request, methods=["POST"],
    summary="Withdraw a request that has not been sent yet",
    description="Only the account's own requests, or any request for an administrator.",
)
router.add_api_route(
    "/admin/requests", requests.all_requests, methods=["GET"],
    summary="All requests, optionally by status",
    description=(
        "Administrators only. `status` is one of `pending_approval`, `approved`, `searching`, `downloaded`, "
        "`rejected`, `failed`, `cancelled`. `cover_url` is either a whole address or a path on this "
        "installation starting with `/`."
    ),
)
router.add_api_route(
    "/admin/requests/{request_id}/approve", requests.approve_request, methods=["POST"],
    summary="Approve a waiting request",
    description="Administrators only, with a token that may write. The request goes to Lidarr or nexcrate.",
)
router.add_api_route(
    "/admin/requests/{request_id}/reject", requests.reject_request, methods=["POST"],
    summary="Turn down a waiting request",
    description="Administrators only, with a token that may write. Body: `{\"reason\": \"…\"}`, may be empty.",
)
