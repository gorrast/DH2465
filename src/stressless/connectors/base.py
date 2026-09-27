"""Connector base classes and shared parsing/classification helpers (SPEC §6.1)."""
from __future__ import annotations

import abc
import re
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from ..models import CalendarEvent, DailyActivity, HeartRateDay, LocationVisit, SleepNight
from ..timeutil import tz

_TS_APPLE = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) ([+-]\d{4})$")
_TS_EPOCH_MS = re.compile(r"^\d{12,13}$")
_TS_EPOCH_S = re.compile(r"^\d{9,10}$")


def parse_ts(value, tzname: Optional[str] = None) -> datetime:
    """Tolerant timestamp parser: ISO (with/without seconds, Z, ±HH:MM, ±HHMM), Apple Health, epoch ms/s."""
    zone = tz(tzname)
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        m = _TS_APPLE.match(s)
        if m:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S %z")
        elif _TS_EPOCH_MS.match(s):
            dt = datetime.fromtimestamp(int(s) / 1000.0, tz=timezone.utc)
        elif _TS_EPOCH_S.match(s):
            dt = datetime.fromtimestamp(int(s), tz=timezone.utc)
        else:
            if s.endswith("Z") or s.endswith("z"):
                s = s[:-1] + "+00:00"
            # trim fractional seconds to 6 digits
            s = re.sub(r"(\.\d{6})\d+", r"\1", s)
            # +0100 -> +01:00
            s = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s)
            if "T" not in s and " " in s:
                s = s.replace(" ", "T", 1)
            dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=zone)
    return dt.astimezone(zone)


def classify_event(title: str, location_hint: Optional[str] = None) -> str:
    t = ("%s %s" % (title or "", location_hint or "")).lower()
    if re.search(r"\b(gym|run|running|yoga|\bpt\b|workout|training|swim|cycling|climb|crossfit|pilates)\b", t):
        return "workout"
    if re.search(r"\b(dinner|drinks|after-?work|afterwork|concert|party|bar|pub|brunch|birthday)\b", t):
        return "social"
    if re.search(r"\b(flight|train to|airport|trip|travel|arn->|->arn)\b", t):
        return "travel"
    if re.search(r"\b(focus|deep work|writing|no meetings|heads.?down)\b", t):
        return "focus"
    if re.search(r"\b(wind.?down|recovery|protected|screen.?free|bedtime)\b", t):
        return "protected"
    if re.search(r"\b(dentist|doctor|pickup|pick-up|physio|vet|haircut)\b", t):
        return "personal"
    return "meeting"


def classify_place(name: str, semantic: Optional[str] = None) -> str:
    n = (name or "").lower()
    sem = (semantic or "").lower()
    if "home" in sem or n in ("home", "hem"):
        return "home"
    if "work" in sem or re.search(r"\b(office|kontor|hq|headquarters)\b", n):
        return "office"
    if re.search(r"\b(gym|sats|friskis|nordic wellness|fitness|crossfit|yoga)\b", n):
        return "gym"
    if re.search(r"\b(bar|pub|brewery|tap ?room|club)\b", n):
        return "bar"
    if re.search(r"\b(restaurant|restaurang|bistro|kitchen|pizzeria|sushi|trattoria|café|cafe|brasserie|krog)\b", n):
        return "restaurant"
    if re.search(r"\b(airport|arlanda|terminal|flygplats)\b", n):
        return "airport"
    if re.search(r"\b(hotel|hostel|inn)\b", n):
        return "hotel"
    if re.search(r"\b(park|trail|loop|forest|beach|lake)\b", n):
        return "outdoors"
    if re.search(r"\b(station|central|centralen|metro|t-bana|bus)\b", n):
        return "transit"
    return "other"


class CalendarSource(abc.ABC):
    @abc.abstractmethod
    def events(self, start: date, end: date) -> List[CalendarEvent]: ...


class LocationSource(abc.ABC):
    @abc.abstractmethod
    def visits(self, start: date, end: date) -> List[LocationVisit]: ...


class BiometricSource(abc.ABC):
    @abc.abstractmethod
    def hr_days(self, start: date, end: date) -> List[HeartRateDay]: ...

    @abc.abstractmethod
    def nights(self, start: date, end: date) -> List[SleepNight]: ...

    @abc.abstractmethod
    def activity(self, start: date, end: date) -> List[DailyActivity]: ...
