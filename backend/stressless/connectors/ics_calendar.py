"""Google Calendar / iCalendar (.ics) importer with recurrence expansion (SPEC §6.1)."""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from ..models import CalendarEvent, new_id
from ..timeutil import tz
from .base import classify_event, parse_ts

log = logging.getLogger("stressless.connectors.ics")
WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
MAX_INSTANCES = 400
WINDOWS_TZ = {"W. Europe Standard Time": "Europe/Stockholm", "Central European Standard Time": "Europe/Stockholm",
              "GMT Standard Time": "Europe/London", "Eastern Standard Time": "America/New_York", "Pacific Standard Time": "America/Los_Angeles"}


def _unfold(text: str) -> List[str]:
    lines: List[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        elif raw.strip():
            lines.append(raw)
    return lines


def _split_prop(line: str) -> Tuple[str, Dict[str, str], str]:
    if ":" not in line:
        return line.upper(), {}, ""
    head, value = line.split(":", 1)
    parts = head.split(";")
    name = parts[0].upper()
    params = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.upper()] = v.strip('"')
    return name, params, value


def _zone(params: Dict[str, str], default: str) -> str:
    tzid = params.get("TZID")
    if not tzid:
        return default
    name = WINDOWS_TZ.get(tzid, tzid)
    try:
        tz(name)
        return name
    except Exception:
        log.warning("unknown TZID %r; using %s", tzid, default)
        return default


def _parse_dt(value: str, params: Dict[str, str], default_tz: str) -> Optional[datetime]:
    v = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", v):
        return None  # all-day: skipped
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})?(Z?)", v)
    if not m:
        try:
            return parse_ts(v, default_tz)
        except ValueError:
            return None
    y, mo, d, hh, mm, ss, z = m.groups()
    naive = datetime(int(y), int(mo), int(d), int(hh), int(mm), int(ss or 0))
    if z:
        from datetime import timezone
        return naive.replace(tzinfo=timezone.utc).astimezone(tz(default_tz))
    return naive.replace(tzinfo=tz(_zone(params, default_tz))).astimezone(tz(default_tz))


def _parse_duration(value: str) -> timedelta:
    m = re.fullmatch(r"(-)?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", value.strip())
    if not m:
        return timedelta(hours=1)
    neg, w, d, h, mi, s = m.groups()
    td = timedelta(weeks=int(w or 0), days=int(d or 0), hours=int(h or 0), minutes=int(mi or 0), seconds=int(s or 0))
    return -td if neg else td


def _expand(start: datetime, rrule: str, exdates: set, lo: datetime, hi: datetime) -> List[datetime]:
    rule = {}
    for part in rrule.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            rule[k.upper()] = v
    freq = rule.get("FREQ", "").upper()
    interval = max(1, int(rule.get("INTERVAL", "1") or 1))
    count = int(rule["COUNT"]) if rule.get("COUNT") else None
    until = None
    if rule.get("UNTIL"):
        until = _parse_dt(rule["UNTIL"], {}, str(start.tzinfo))
        if until is None:  # DATE form
            u = rule["UNTIL"]
            until = datetime(int(u[:4]), int(u[4:6]), int(u[6:8]), 23, 59, tzinfo=start.tzinfo)
    out: List[datetime] = []
    if freq not in ("DAILY", "WEEKLY"):
        return [start] if lo <= start <= hi else []
    if freq == "DAILY":
        cur = start
        n = 0
        while len(out) < MAX_INSTANCES and (count is None or n < count) and (until is None or cur <= until) and cur <= hi:
            if cur >= lo and cur not in exdates:
                out.append(cur)
            n += 1
            cur = cur + timedelta(days=interval)
        return out
    bydays = [WEEKDAYS[d[-2:]] for d in rule.get("BYDAY", "").split(",") if d and d[-2:] in WEEKDAYS] or [start.weekday()]
    week_start = start - timedelta(days=start.weekday())
    n = 0
    week = 0
    while len(out) < MAX_INSTANCES:
        base = week_start + timedelta(weeks=week * interval)
        if base > hi + timedelta(days=7) or (until is not None and base > until + timedelta(days=7)):
            break
        for wd in sorted(bydays):
            cur = base + timedelta(days=wd)
            if cur < start:
                continue
            if until is not None and cur > until:
                return out
            if count is not None and n >= count:
                return out
            n += 1
            if lo <= cur <= hi and cur not in exdates:
                out.append(cur)
        week += 1
    return out


def parse_ics(text: str, tzname: str, start: date, end: date) -> List[CalendarEvent]:
    """Expand a .ics export into events within [start, end] (all-day and cancelled events skipped)."""
    lines = _unfold(text)
    vevents: List[Dict[str, object]] = []
    cur: Optional[Dict[str, object]] = None
    for line in lines:
        name, params, value = _split_prop(line)
        if name == "BEGIN" and value.upper() == "VEVENT":
            cur = {"exdates": set(), "attendees": 0}
        elif name == "END" and value.upper() == "VEVENT" and cur is not None:
            vevents.append(cur)
            cur = None
        elif cur is not None:
            if name == "EXDATE":
                for v in value.split(","):
                    dt = _parse_dt(v, params, tzname)
                    if dt is not None:
                        cur["exdates"].add(dt)
            elif name == "ATTENDEE":
                cur["attendees"] = int(cur.get("attendees", 0)) + 1
            elif name in ("DTSTART", "DTEND", "RECURRENCE-ID"):
                cur[name] = (value, params)
            else:
                cur[name] = value
    lo = datetime.combine(start, datetime.min.time(), tzinfo=tz(tzname))
    hi = datetime.combine(end, datetime.max.time().replace(microsecond=0), tzinfo=tz(tzname))
    overrides: Dict[Tuple[str, datetime], Dict[str, object]] = {}
    for ve in vevents:
        if "RECURRENCE-ID" in ve and ve.get("UID"):
            rid = _parse_dt(*ve["RECURRENCE-ID"], default_tz=tzname) if isinstance(ve["RECURRENCE-ID"], tuple) else None
            if rid is not None:
                overrides[(str(ve["UID"]), rid)] = ve
    out: List[CalendarEvent] = []
    for ve in vevents:
        if str(ve.get("STATUS", "")).upper() == "CANCELLED" or "DTSTART" not in ve:
            continue
        if "RECURRENCE-ID" in ve:
            continue  # handled through the master below
        dtstart = _parse_dt(*ve["DTSTART"], default_tz=tzname)
        if dtstart is None:
            continue
        if "DTEND" in ve:
            dtend = _parse_dt(*ve["DTEND"], default_tz=tzname) or (dtstart + timedelta(hours=1))
        elif ve.get("DURATION"):
            dtend = dtstart + _parse_duration(str(ve["DURATION"]))
        else:
            dtend = dtstart + timedelta(hours=1)
        duration = dtend - dtstart
        uid = str(ve.get("UID") or hashlib.sha1(("%s%s" % (ve.get("SUMMARY"), dtstart)).encode()).hexdigest())
        starts = _expand(dtstart, str(ve["RRULE"]), set(ve["exdates"]), lo, hi) if ve.get("RRULE") else ([dtstart] if lo <= dtstart <= hi else [])
        for s in starts:
            ov = overrides.get((uid, s))
            title = str(ve.get("SUMMARY") or "Untitled")
            loc = ve.get("LOCATION")
            e_start, e_end = s, s + duration
            attendees = int(ve.get("attendees", 0))
            if ov is not None:
                if str(ov.get("STATUS", "")).upper() == "CANCELLED":
                    continue
                o_start = _parse_dt(*ov["DTSTART"], default_tz=tzname) if "DTSTART" in ov else None
                if o_start is not None:
                    o_end = _parse_dt(*ov["DTEND"], default_tz=tzname) if "DTEND" in ov else None
                    if o_end is None and ov.get("DURATION"):
                        o_end = o_start + _parse_duration(str(ov["DURATION"]))
                    e_start, e_end = o_start, (o_end or (o_start + duration))
                title = str(ov.get("SUMMARY") or title)
                loc = ov.get("LOCATION", loc)
            out.append(CalendarEvent(id=new_id("ev", "ics", hashlib.sha1(uid.encode()).hexdigest()[:8], e_start.date(), e_start.strftime("%H%M")),
                                     title=title, start=e_start, end=e_end, type=classify_event(title, str(loc) if loc else None),
                                     location_hint=str(loc) if loc else None, attendees=attendees,
                                     recurring_key=("ics-%s" % hashlib.sha1(uid.encode()).hexdigest()[:8]) if ve.get("RRULE") else None, source="ics"))
    out.sort(key=lambda e: e.start)
    return out
