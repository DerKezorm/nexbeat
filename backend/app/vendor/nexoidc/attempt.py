"""The attempt cookie and the single use of a ``state`` (Bauplan 02, "Ablauf" 1 and 2).

The three random values of an attempt travel with the browser in a signed cookie instead of a table: nothing to
clean up, and an unredeemed attempt is worthless after ten minutes. Nobody can forge it without the key; the browser's
owner could read it, so only what belongs to that browser anyway is inside: the provider, the purpose, an invitation
key that came from this browser's own address bar, the account that links itself.

The key is derived from the app's server secret with a prefix of its own (``<app>-oidc-attempt:``), so an attempt
never passes as a session and a session never as an attempt. HS256 signs the app's own cookie here; tokens of a
provider are never accepted with it (``protocol.ALGORITHMS``).

On top of the cookie every ``state`` is remembered on the server until it expires, so a replayed callback is refused
even with the original cookie.
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Any

import jwt

from . import config
from .protocol import Attempt

#: How long a started attempt is valid. Longer than anybody needs at a provider, short enough that a forgotten
#: cookie is worthless.
ATTEMPT_MINUTES = 10
#: What an attempt is for.
SIGN_IN = "sign_in"
LINK = "link"
INVITE = "invite"
PURPOSES = (SIGN_IN, LINK, INVITE)


@dataclass(frozen=True)
class Started:
    """What a returning browser carries, read back from its cookie."""

    provider_id: int
    purpose: str
    state: str
    nonce: str
    verifier: str
    redirect_uri: str
    link_account_id: int | None = None
    invite: str | None = None


def _key() -> bytes:
    cfg = config.current()
    secret = cfg.server_secret()
    raw = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    if len(raw) < 16:
        raise RuntimeError("the app's server secret is too short to derive the attempt key from")
    return hashlib.sha256(f"{cfg.app_name}-oidc-attempt:".encode("ascii") + raw).digest()


def pack(
    attempt: Attempt,
    *,
    provider_id: int,
    purpose: str,
    redirect_uri: str,
    link_account_id: int | None = None,
    invite: str | None = None,
) -> str:
    """The attempt as a signed, short-lived cookie value."""
    if purpose not in PURPOSES:
        raise ValueError(f"unknown purpose {purpose!r}")
    now = int(time.time())
    payload: dict[str, Any] = {
        "pid": provider_id,
        "for": purpose,
        "state": attempt.state,
        "nonce": attempt.nonce,
        "verifier": attempt.verifier,
        "redirect": redirect_uri,
        "iat": now,
        "exp": now + ATTEMPT_MINUTES * 60,
    }
    if link_account_id is not None:
        payload["link"] = link_account_id
    if invite is not None:
        payload["invite"] = invite
    return jwt.encode(payload, _key(), algorithm="HS256")


def read(value: str | None) -> Started | None:
    """The attempt from the cookie; None when it is missing, expired, not ours or not whole."""
    if not value:
        return None
    try:
        data = jwt.decode(value, _key(), algorithms=["HS256"], options={"require": ["exp", "iat"]})
    except jwt.PyJWTError:
        return None
    try:
        started = Started(
            provider_id=int(data["pid"]),
            purpose=str(data["for"]),
            state=str(data["state"]),
            nonce=str(data["nonce"]),
            verifier=str(data["verifier"]),
            redirect_uri=str(data["redirect"]),
            link_account_id=int(data["link"]) if data.get("link") is not None else None,
            invite=str(data["invite"]) if data.get("invite") is not None else None,
        )
    except (KeyError, TypeError, ValueError):
        return None
    if started.purpose not in PURPOSES or not started.state or not started.nonce or not started.verifier:
        return None
    if started.purpose == LINK and started.link_account_id is None:
        return None
    if started.purpose == INVITE and not started.invite:
        return None
    return started


#: Hashes of the states already redeemed, with the moment they may be forgotten.
_used: dict[str, float] = {}
_used_lock = threading.Lock()


def consume_state(state: str) -> bool:
    """Marks the state as used; False when it was used before."""
    now = time.monotonic()
    digest = hashlib.sha256(state.encode("utf-8")).hexdigest()
    with _used_lock:
        for key in [key for key, until in _used.items() if until <= now]:
            del _used[key]
        if digest in _used:
            return False
        _used[digest] = now + ATTEMPT_MINUTES * 60
        return True


def forget_used_states() -> None:
    """For the tests."""
    with _used_lock:
        _used.clear()
