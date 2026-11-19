"""Ein Geraet per Code verbinden (``services/pairing.py`` erzaehlt den Ablauf).

Drei Wege fuer das Geraet ohne Anmeldung (anfragen, nachfragen, loslassen), einer fuer den Browser (bestaetigen).
Der Weg des Browsers verlangt eine Browsersitzung: Ein Token soll sich keine weiteren Token ausstellen.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, NoReturn

from fastapi import APIRouter, Header, Path, Response
from pydantic import BaseModel, Field

from ..deps import DbSession, SessionUser
from ..meldungen import fehler
from ..services import pairing
from ..services.pairing import PairingProblem

router = APIRouter(tags=["pairing"])


class RequestIn(BaseModel):
    device_name: str | None = Field(default=None, max_length=80)


class RequestOut(BaseModel):
    id: str
    secret: str
    #: Wie Menschen ihn lesen: ``ABCD-2345``.
    code: str
    expires_at: datetime
    poll_seconds: int


class Account(BaseModel):
    name: str


class StateOut(BaseModel):
    #: ``waiting`` oder ``confirmed``; abgelaufen und abgeholt kommen als 410.
    state: str
    #: Nur einmal, in der ersten Antwort nach der Bestaetigung.
    token: str | None = None
    account: Account | None = None


class ConfirmIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)


class ConfirmOut(BaseModel):
    device_name: str


def _raise(problem: PairingProblem) -> NoReturn:
    error = fehler(problem.code, problem.message, problem.status_code, **problem.values)
    if "retry_after" in problem.values:
        error.headers = {"Retry-After": str(problem.values["retry_after"])}
    raise error


Secret = Annotated[str, Header(alias="X-Pairing-Secret", max_length=200)]
RequestId = Annotated[str, Path(min_length=1, max_length=40)]


@router.post("/api/pairing/request", response_model=RequestOut, status_code=201,
             summary="A device without a browser asks for a code to show (no sign-in)")
def ask(body: RequestIn, db: DbSession) -> RequestOut:
    try:
        made = pairing.create(db, body.device_name)
    except PairingProblem as problem:
        _raise(problem)
    return RequestOut(id=made.request.id, secret=made.secret, code=pairing.formatted(made.request.code),
                      expires_at=made.request.expires_at.replace(tzinfo=UTC), poll_seconds=pairing.POLL_SECONDS)


@router.get("/api/pairing/request/{request_id}", response_model=StateOut, response_model_exclude_none=True,
            summary="The device asks whether its code was confirmed; then it gets its API token, once")
def poll(request_id: RequestId, secret: Secret, db: DbSession) -> StateOut:
    try:
        state = pairing.state(db, request_id, secret)
    except PairingProblem as problem:
        _raise(problem)
    return StateOut(state=state.state, token=state.token,
                    account=Account(name=state.account) if state.account is not None else None)


@router.delete("/api/pairing/request/{request_id}", status_code=204,
               summary="The device lets its code go (a new code, or the screen closed)")
def let_go(request_id: RequestId, secret: Secret, db: DbSession) -> Response:
    try:
        pairing.release(db, request_id, secret)
    except PairingProblem as problem:
        _raise(problem)
    return Response(status_code=204)


@router.post("/api/pairing/confirm", response_model=ConfirmOut,
             summary="In the browser: confirm the code a device shows; it then fetches a token of this account")
def confirm(body: ConfirmIn, user: SessionUser, db: DbSession) -> ConfirmOut:
    try:
        request = pairing.confirm(db, user, body.code)
    except PairingProblem as problem:
        _raise(problem)
    return ConfirmOut(device_name=request.device_name)
