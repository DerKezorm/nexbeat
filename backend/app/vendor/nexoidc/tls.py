"""One TLS context for every call the module makes (provider, authentik), read once and never in the event loop.

httpx builds a new context for each client unless it is given one (``verify=``), and reading the trusted certificates
takes 0.5 to 0.8 s on a small machine (measured in nextasks), several times per sign-in, inside the event loop where
it stops everybody. So the module reads the context once, in a worker thread, with httpx's own defaults (certifi, and
``SSL_CERT_FILE``/``SSL_CERT_DIR`` from the environment), and hands it to every client it makes.

``warm()`` reads it ahead at the app's start; without that, the first call reads it, also in a thread. An app with a
context of its own gives it as ``AppConfig.ssl_context``; the module then uses that one and reads nothing.
"""

from __future__ import annotations

import asyncio
import ssl
import threading

import httpx

from . import config

_lock = threading.Lock()
_context: ssl.SSLContext | None = None


def _build() -> ssl.SSLContext:
    """httpx's default context: its CA bundle, and the environment's certificate settings (``trust_env``)."""
    return httpx.create_ssl_context(trust_env=True)


def _read() -> ssl.SSLContext:
    """Blocking: the context, built on first use. Called in a worker thread only."""
    global _context
    with _lock:
        if _context is None:
            _context = _build()
        return _context


async def context() -> ssl.SSLContext:
    """The context for a client: the app's own when it gave one, else the module's, read in a thread the first time."""
    own = config.current().ssl_context
    if own is not None:
        return own
    if _context is not None:
        return _context
    return await asyncio.to_thread(_read)


async def warm() -> None:
    """Read the context ahead, at the app's start, so that the first sign-in does not wait for it."""
    await context()


def forget() -> None:
    """For the tests: the next call reads the context anew."""
    global _context
    with _lock:
        _context = None
