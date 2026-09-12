"""Einstieg: FastAPI-Anwendung, Router, Hintergrundaufgaben, gebautes Frontend."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import get_settings
from .db import SessionLocal, init_db
from .meldungen import meldung
from .middleware import RequestIdMiddleware, configure_logging
from .routers import auth, catalog, discover, health, onboarding, requests, setup, users, webhooks
from .routers import settings as settings_router
from .services import http
from .services.settings_service import ensure_webhook_secret

logger = logging.getLogger("nexbeat")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    init_db()
    with SessionLocal() as db:
        ensure_webhook_secret(db)
    stop = asyncio.Event()
    tasks: list[asyncio.Task[None]] = []
    if not get_settings().disable_background:
        from .services import poller

        tasks.append(asyncio.create_task(poller.run(stop)))
    logger.info("nexbeat %s started", __version__)
    try:
        yield
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await http.close_all()


app = FastAPI(
    title="nexbeat",
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)
app.add_middleware(RequestIdMiddleware)


@app.exception_handler(RequestValidationError)
async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    fields = [".".join(str(part) for part in error.get("loc", ()) if part != "body") for error in exc.errors()]
    return JSONResponse(
        status_code=422,
        content={"detail": meldung("invalid_input", "The input is not valid.", fields=fields)},
    )


@app.exception_handler(Exception)
async def _unexpected_error(request: Request, _exc: Exception) -> JSONResponse:
    request_id = request.scope.get("state", {}).get("request_id", "-")
    logger.exception("Unhandled error in request %s", request_id)
    return JSONResponse(
        status_code=500,
        content={"detail": meldung("internal_error", "Something went wrong on the server.", request_id=request_id)},
    )


for module in (health, setup, auth, onboarding, users, settings_router, catalog, discover, requests, webhooks):
    app.include_router(module.router)


def _mount_frontend(target: FastAPI, dist: Path) -> None:
    """Das gebaute Frontend ausliefern, jede unbekannte Seite bekommt index.html."""
    index = dist / "index.html"
    if not index.exists():
        return
    if (dist / "assets").is_dir():
        target.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    root = dist.resolve()

    # response_model=None: Aus zwei Antwortklassen baut FastAPI kein Modell und
    # bricht sonst schon beim Import ab.
    @target.get("/{path:path}", include_in_schema=False, response_model=None)
    def spa(path: str) -> FileResponse | JSONResponse:
        if path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": meldung("not_found", "Not found.")})
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and root in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)


_mount_frontend(app, get_settings().frontend_dist)
