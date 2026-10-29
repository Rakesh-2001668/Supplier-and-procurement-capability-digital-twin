"""Business clock. Seeds and tests pin it so date-driven rules are reproducible."""
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
_pinned: Optional[datetime] = None


def now() -> datetime:
    return _pinned if _pinned is not None else datetime.now(timezone.utc)


def today() -> date:
    return now().astimezone(IST).date()


@contextmanager
def pinned(at: datetime):
    global _pinned
    previous = _pinned
    _pinned = at if at.tzinfo else at.replace(tzinfo=IST)
    try:
        yield
    finally:
        _pinned = previous


def set_pinned(at: Optional[datetime]) -> None:
    global _pinned
    _pinned = at if (at is None or at.tzinfo) else at.replace(tzinfo=IST)


def at_ist(d: date, hour: int = 10, minute: int = 0) -> datetime:
    return datetime.combine(d, time(hour, minute), tzinfo=IST)


def is_working_day(d: date, working_days: Iterable[int], holidays: Iterable[date]) -> bool:
    return d.weekday() in set(working_days) and d not in set(holidays)


def subtract_working_days(d: date, days: int, working_days=(0, 1, 2, 3, 4, 5), holidays=()) -> date:
    """Move back ``days`` working days on a factory calendar."""
    working, off = set(working_days), set(holidays)  # is_working_day's test, with the sets built once per call
    current = d
    remaining = days
    while remaining > 0:
        current -= timedelta(days=1)
        if current.weekday() in working and current not in off:
            remaining -= 1
    return current


def add_business_days(start: datetime, days: int, working_days=(0, 1, 2, 3, 4)) -> datetime:
    current = start
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if current.astimezone(IST).weekday() in working_days:
            remaining -= 1
    return current


def fiscal_year(d: date, start_month: int = 4) -> str:
    """Indian fiscal year label, e.g. 2026-11-14 -> '2026-27'."""
    start = d.year if d.month >= start_month else d.year - 1
    return f"{start}-{str(start + 1)[-2:]}"
