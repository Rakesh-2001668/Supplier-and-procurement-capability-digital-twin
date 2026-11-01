"""Cron expressions for the job scheduler: five fields ``minute hour day-of-month month day-of-week`` evaluated in a time zone.

Supports ``*``, lists (``1,15``), ranges (``1-5``), steps (``*/15``, ``0-30/10``), month and weekday names (``JAN``, ``MON``) and
the aliases ``@hourly``, ``@daily``, ``@weekly``, ``@monthly``. Weekdays follow cron: 0 or 7 = Sunday. As in Vixie cron, when both
day-of-month and day-of-week are restricted a day matches if EITHER does.
"""
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

ALIASES = {"@hourly": "0 * * * *", "@daily": "0 0 * * *", "@midnight": "0 0 * * *", "@weekly": "0 0 * * 0", "@monthly": "0 0 1 * *"}
MONTHS = {n: i for i, n in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), start=1)}
DAYS = {n: i for i, n in enumerate(("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"))}
LIMITS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


class CronError(ValueError):
    pass


def _field(text: str, low: int, high: int, names: Optional[dict] = None) -> set[int]:
    values: set[int] = set()
    for part in text.split(","):
        if not part:
            raise CronError("empty list item")
        step = 1
        if "/" in part:
            part, raw = part.split("/", 1)
            if not raw.isdigit() or int(raw) < 1:
                raise CronError(f"invalid step '{raw}'")
            step = int(raw)
        if part == "*":
            start, end = low, high
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = _number(a, names), _number(b, names)
        else:
            start = _number(part, names)
            end = high if step > 1 else start
        if start < low or end > high or start > end:
            raise CronError(f"'{part}' is outside {low}-{high}")
        values.update(range(start, end + 1, step))
    return values


def _number(text: str, names: Optional[dict]) -> int:
    if names and text.upper() in names:
        return names[text.upper()]
    if not text.isdigit():
        raise CronError(f"invalid value '{text}'")
    return int(text)


class Cron:
    def __init__(self, expression: str):
        expression = ALIASES.get((expression or "").strip().lower(), (expression or "").strip())
        parts = expression.split()
        if len(parts) != 5:
            raise CronError("a schedule has five fields: minute hour day-of-month month day-of-week (or @hourly, @daily, @weekly, @monthly)")
        self.expression = expression
        self.minutes = _field(parts[0], *LIMITS[0])
        self.hours = _field(parts[1], *LIMITS[1])
        self.dom = _field(parts[2], *LIMITS[2])
        self.months = _field(parts[3], *LIMITS[3], names=MONTHS)
        self.dow = {d % 7 for d in _field(parts[4], *LIMITS[4], names=DAYS)}
        self._dom_any, self._dow_any = parts[2] == "*", parts[4] == "*"

    def _day_matches(self, day) -> bool:
        if day.month not in self.months:
            return False
        dom_ok = day.day in self.dom
        dow_ok = (day.weekday() + 1) % 7 in self.dow  # Python Monday=0 -> cron Monday=1, Sunday=0
        if self._dom_any or self._dow_any:
            return dom_ok and dow_ok
        return dom_ok or dow_ok

    def next_after(self, after: datetime, tz: str = "Asia/Kolkata") -> datetime:
        """The first matching minute strictly after ``after`` (an aware datetime), returned in UTC."""
        zone = ZoneInfo(tz)
        local = after.astimezone(zone).replace(second=0, microsecond=0) + timedelta(minutes=1)
        day = local.date()
        for offset in range(0, 366 * 5):
            current = day + timedelta(days=offset)
            if not self._day_matches(current):
                continue
            for hour in sorted(self.hours):
                for minute in sorted(self.minutes):
                    candidate = datetime(current.year, current.month, current.day, hour, minute, tzinfo=zone)
                    if candidate >= local:
                        return candidate.astimezone(ZoneInfo("UTC"))
        raise CronError(f"'{self.expression}' never fires")


def validate(expression: str) -> str:
    return Cron(expression).expression
