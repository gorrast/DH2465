"""Time helpers shared by the simulator, engine, and server.

Conventions (see SPEC.md § Time model):
- Every datetime is timezone-aware in the persona's zone (default Europe/Stockholm).
- A *night* is keyed by the date of the evening it started: sleep that begins at
  23:10 on 26 Sep or at 00:40 on 27 Sep both belong to night 2026-09-26.
- The morning report shown on date M explains night M-1.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Iterator, List, Optional
from zoneinfo import ZoneInfo

DEFAULT_TZ = "Europe/Stockholm"

_TZ_CACHE = {}


def tz(name: Optional[str] = None) -> ZoneInfo:
    """Return a cached ZoneInfo for ``name`` (default persona zone)."""
    name = name or DEFAULT_TZ
    if name not in _TZ_CACHE:
        _TZ_CACHE[name] = ZoneInfo(name)
    return _TZ_CACHE[name]


def at(d: date, hour: float = 0, minute: int = 0, tzname: Optional[str] = None) -> datetime:
    """Local datetime on day ``d``. ``hour`` may be fractional (20.5 -> 20:30)."""
    whole = int(hour)
    frac_min = int(round((hour - whole) * 60))
    base = datetime.combine(d, time(0, 0), tzinfo=tz(tzname))
    return base + timedelta(hours=whole, minutes=minute + frac_min)


def parse_dt(value, tzname: Optional[str] = None) -> datetime:
    """Parse an ISO-8601 string (or pass through a datetime) into an aware datetime."""
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz(tzname))
    return dt.astimezone(tz(tzname))


def parse_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="minutes")


def minute_of_day(dt: datetime) -> int:
    """0..1439 in the datetime's own zone."""
    return dt.hour * 60 + dt.minute


def hours_float(dt: datetime) -> float:
    """20:30 -> 20.5 (in the datetime's own zone)."""
    return dt.hour + dt.minute / 60.0 + dt.second / 3600.0


def night_date(dt: datetime) -> date:
    """The night a moment belongs to: evenings keep their date, small hours roll back."""
    return dt.date() if dt.hour >= 12 else dt.date() - timedelta(days=1)


def day_range(start: date, end: date) -> List[date]:
    """Inclusive list of dates."""
    if end < start:
        return []
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def iter_days(start: date, end: date) -> Iterator[date]:
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def overlap_minutes(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> int:
    lo = max(a_start, b_start)
    hi = min(a_end, b_end)
    if hi <= lo:
        return 0
    return int((hi - lo).total_seconds() // 60)


def fmt_hm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def fmt_day(d: date) -> str:
    """'Thu 26 Sep'"""
    return d.strftime("%a %-d %b")


def fmt_minutes(minutes: float) -> str:
    """95 -> '1 h 35 min', 40 -> '40 min'."""
    m = int(round(minutes))
    h, r = divmod(abs(m), 60)
    sign = "-" if m < 0 else ""
    if h and r:
        return f"{sign}{h} h {r} min"
    if h:
        return f"{sign}{h} h"
    return f"{sign}{r} min"


def today_local(tzname: Optional[str] = None) -> date:
    return datetime.now(tz(tzname)).date()


def weekday_name(d: date) -> str:
    return d.strftime("%A")


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5


def day_hour(dt: datetime, day: date) -> float:
    """Hour-of-day of ``dt`` relative to midnight of ``day`` (same zone as ``dt``).

    An end at 00:30 the morning after ``day`` is 24.5, never 0.5. All hour-of-day
    features (last meeting end, social end, workout slot) use this so events that
    cross midnight stay on the evening they belong to.
    """
    midnight = datetime.combine(day, time(0, 0), tzinfo=dt.tzinfo)
    return (dt - midnight).total_seconds() / 3600.0


def is_weekend_night(d: date) -> bool:
    """True for nights before a non-workday (Friday and Saturday nights)."""
    return (d + timedelta(days=1)).weekday() >= 5


def hour_label(h: float) -> str:
    """24.5 -> '00:30', 20.25 -> '20:15'."""
    total = int(round(h * 60))
    hh, mm = divmod(total, 60)
    return f"{hh % 24:02d}:{mm:02d}"
