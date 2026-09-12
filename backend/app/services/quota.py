"""Kontingent nach Stueckzahl: Jede Anfrage zaehlt eins, egal wie gross.

Der Zeitraum ist ein Kalenderfenster in UTC (Tag, Woche ab Montag, Monat ab dem
Ersten), wie in Nexview. Gezaehlt wird, was in ``COUNTED_STATUSES`` steht.
Abgelehnte, gescheiterte und zurueckgezogene Anfragen fallen heraus, das
Zurueckbuchen passiert also von selbst.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import COUNTED_STATUSES, MusicRequest, User, utcnow
from .settings_service import AppSettings


@dataclass(frozen=True)
class QuotaState:
    #: None heisst unbegrenzt.
    limit: int | None
    used: int
    period: str
    period_start: datetime
    resets_at: datetime

    @property
    def remaining(self) -> int | None:
        return None if self.limit is None else max(0, self.limit - self.used)

    @property
    def exhausted(self) -> bool:
        return self.limit is not None and self.used >= self.limit


def period_bounds(period: str, now: datetime) -> tuple[datetime, datetime]:
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "day":
        return day, day + timedelta(days=1)
    if period == "month":
        start = day.replace(day=1)
        if start.month == 12:
            return start, start.replace(year=start.year + 1, month=1)
        return start, start.replace(month=start.month + 1)
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=7)


def effective_limit(user: User, settings: AppSettings) -> int | None:
    if user.is_admin:
        return None
    if user.quota_limit is None:
        return settings.quota_default_limit
    if user.quota_limit < 0:
        return None
    return user.quota_limit


def state(db: Session, user: User, settings: AppSettings, now: datetime | None = None) -> QuotaState:
    now = now or utcnow()
    period = settings.text("quota_period")
    start, end = period_bounds(period, now)
    counted_from = max(start, user.quota_reset_at) if user.quota_reset_at else start
    used = db.scalar(
        select(func.count(MusicRequest.id)).where(
            MusicRequest.user_id == user.id,
            MusicRequest.status.in_(COUNTED_STATUSES),
            MusicRequest.requested_at >= counted_from,
        )
    )
    return QuotaState(
        limit=effective_limit(user, settings),
        used=int(used or 0),
        period=period,
        period_start=start,
        resets_at=end,
    )


def as_dict(quota: QuotaState) -> dict[str, object]:
    return {
        "limit": quota.limit,
        "used": quota.used,
        "remaining": quota.remaining,
        "period": quota.period,
        "resets_at": quota.resets_at,
    }
