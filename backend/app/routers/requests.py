"""Anfragen: eigene und, fuer Admins, alle."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..deps import AdminUser, CurrentUser, DbSession
from ..meldungen import fehler
from ..models import MusicRequest, RequestStatus
from ..services import quota, requests_service
from ..services.catalog import MBID_PATTERN
from ..services.requests_service import RequestProblem, serialize
from ..services.settings_service import load_settings

router = APIRouter(tags=["requests"])


class RequestIn(BaseModel):
    release_group_mbid: str = Field(pattern=MBID_PATTERN.pattern)


class ArtistRequestIn(BaseModel):
    artist_mbid: str = Field(pattern=MBID_PATTERN.pattern)


class RejectIn(BaseModel):
    reason: str = Field(default="", max_length=500)


def _problem(error: RequestProblem) -> HTTPException:
    return fehler(error.code, error.message, error.status_code, **error.values)


def _get(db: Session, request_id: int) -> MusicRequest:
    request = db.get(MusicRequest, request_id)
    if request is None:
        raise fehler("request_not_found", "This request does not exist.", 404)
    return request


@router.get("/api/requests/mine", summary="The signed-in account's requests, newest first")
def my_requests(user: CurrentUser, db: DbSession) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(MusicRequest)
        .where(MusicRequest.user_id == user.id)
        .order_by(MusicRequest.requested_at.desc())
        .limit(200)
    )
    return [serialize(row) for row in rows]


@router.post("/api/requests", status_code=201, summary="Request an album, EP or single")
async def create_request(payload: RequestIn, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    settings = load_settings(db)
    try:
        request = await requests_service.create(db, settings, user, payload.release_group_mbid)
    except RequestProblem as error:
        raise _problem(error) from error
    return {"request": serialize(request), "quota": quota.as_dict(quota.state(db, user, settings))}


@router.post(
    "/api/requests/artist",
    status_code=201,
    summary="Request every studio album of an artist, future releases included",
)
async def create_artist_request(payload: ArtistRequestIn, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    settings = load_settings(db)
    try:
        request = await requests_service.create_artist(db, settings, user, payload.artist_mbid)
    except RequestProblem as error:
        raise _problem(error) from error
    return {"request": serialize(request), "quota": quota.as_dict(quota.state(db, user, settings))}


@router.post("/api/requests/{request_id}/cancel", summary="Withdraw a request that has not been sent yet")
def cancel_request(request_id: int, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    request = _get(db, request_id)
    if request.user_id != user.id and not user.is_admin:
        raise fehler("request_not_found", "This request does not exist.", 404)
    try:
        requests_service.cancel(db, user, request)
    except RequestProblem as error:
        raise _problem(error) from error
    return serialize(request)


@router.get("/api/admin/requests", summary="All requests, optionally by status")
def all_requests(_admin: AdminUser, db: DbSession, status: str | None = None) -> list[dict[str, Any]]:
    query = (
        select(MusicRequest)
        .options(selectinload(MusicRequest.user))
        .order_by(MusicRequest.requested_at.desc())
        .limit(300)
    )
    if status:
        if status not in {item.value for item in RequestStatus}:
            raise fehler("invalid_status", "This status does not exist.", 422)
        query = query.where(MusicRequest.status == RequestStatus(status))
    return [serialize(row, with_user=True) for row in db.scalars(query)]


@router.post("/api/admin/requests/{request_id}/approve", summary="Approve a waiting request and send it to Lidarr")
async def approve_request(request_id: int, admin: AdminUser, db: DbSession) -> dict[str, Any]:
    request = _get(db, request_id)
    try:
        await requests_service.approve(db, load_settings(db), admin, request)
    except RequestProblem as error:
        raise _problem(error) from error
    return serialize(request, with_user=True)


@router.post("/api/admin/requests/{request_id}/reject", summary="Reject a waiting request")
def reject_request(request_id: int, payload: RejectIn, admin: AdminUser, db: DbSession) -> dict[str, Any]:
    request = _get(db, request_id)
    try:
        requests_service.reject(db, admin, request, payload.reason)
    except RequestProblem as error:
        raise _problem(error) from error
    return serialize(request, with_user=True)


@router.post("/api/admin/requests/{request_id}/retry", summary="Send a failed or unsent request to Lidarr again")
async def retry_request(request_id: int, _admin: AdminUser, db: DbSession) -> dict[str, Any]:
    request = _get(db, request_id)
    try:
        await requests_service.retry(db, load_settings(db), request)
    except RequestProblem as error:
        raise _problem(error) from error
    return serialize(request, with_user=True)
