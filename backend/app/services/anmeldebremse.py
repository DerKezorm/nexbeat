"""Bremse gegen Passwort-Raten, im Arbeitsspeicher.

Drei Fehlversuche sind frei. Danach waechst die Wartezeit von 1 Sekunde auf hoechstens
fuenf Minuten. Ein Erfolg setzt den Zaehler zurueck, eine Stunde ohne Fehlversuch ebenso.

Gezaehlt wird je Konto, egal ob mit Benutzername oder E-Mail. Unbekannte Anmeldenamen
zaehlen je Name. Nicht je Adresse: Hinter einem Proxy saehe nexbeat sonst alle Besucher
als eine einzige Adresse.

Ein Browser, der sich schon einmal erfolgreich als dieses Konto angemeldet hat, zaehlt
fuer sich (``sitzung.known_device``). Fremde Fehlversuche bremsen ihn nicht.

12.09.2026: Vorher sperrten zehn Fehlversuche 15 Minuten, und jeder weitere verlaengerte.
Wer nur den Namen kannte, hielt ein Konto so dauerhaft verschlossen. Benutzername und
E-Mail hatten zudem getrennte Zaehler, das verdoppelte die Versuche.

⚠️ Die Zaehler ueberleben keinen Neustart. Fuer eine Bremse reicht das, sie
soll Raten teuer machen, nicht Buch fuehren.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

FREE_ATTEMPTS = 3
MAX_DELAY_SECONDS = 300
FORGET_AFTER_SECONDS = 3600
#: Ab so vielen Zaehlern fallen die vergessenen heraus. Sonst wuechse der Speicher mit jedem erfundenen Namen.
PRUNE_ABOVE = 10_000


@dataclass
class _State:
    failures: int = 0
    blocked_until: float = 0.0
    last_failure: float = 0.0


_lock = threading.Lock()
_states: dict[str, _State] = {}


def account_key(user_id: int) -> str:
    return f"account:{user_id}"


def device_key(user_id: int, device_id: str) -> str:
    return f"device:{user_id}:{device_id}"


def login_key(login: str) -> str:
    return f"login:{login.strip().lower()}"


def password_change_key(user_id: int) -> str:
    return f"password:{user_id}"


def _current(key: str, now: float) -> _State | None:
    state = _states.get(key)
    if state is not None and now - state.last_failure > FORGET_AFTER_SECONDS:
        del _states[key]
        return None
    return state


def wait_seconds(key: str, now: float | None = None) -> int:
    now = time.monotonic() if now is None else now
    with _lock:
        state = _current(key, now)
        return 0 if state is None else max(0, math.ceil(state.blocked_until - now))


def failed(key: str, now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    with _lock:
        if len(_states) > PRUNE_ABOVE:
            for stale in [name for name, state in _states.items() if now - state.last_failure > FORGET_AFTER_SECONDS]:
                del _states[stale]
        state = _current(key, now) or _states.setdefault(key, _State())
        state.failures += 1
        state.last_failure = now
        if state.failures > FREE_ATTEMPTS:
            exponent = min(state.failures - FREE_ATTEMPTS - 1, 16)
            state.blocked_until = now + min(MAX_DELAY_SECONDS, 2**exponent)


def succeeded(key: str) -> None:
    with _lock:
        _states.pop(key, None)


def forget_user(user_id: int) -> None:
    """Alle Zaehler eines Kontos, auch die seiner Browser. Nach einem neuen Passwort."""
    prefix = f"device:{user_id}:"
    with _lock:
        for key in [name for name in _states if name.startswith(prefix)]:
            del _states[key]
        _states.pop(account_key(user_id), None)
        _states.pop(password_change_key(user_id), None)


def reset_all() -> None:
    with _lock:
        _states.clear()
