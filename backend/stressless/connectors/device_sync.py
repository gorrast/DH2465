"""Phone sync (correlate-app → POST /api/sync): validate the upload and turn it into rows for the real-data schema.

Pure functions only; server/phone_sync.py does the storage. Payload, every list optional:

    {"device":     {"installId": "<uuid the app generated>", "platform": "android", "label": "Pixel 8",
                    "timeZone": "Europe/Stockholm", "tzOffsetMin": 120},
     "permissions": {"sleep_session": true, "steps": true, "app_usage": false},
     "sleep":      [{"id", "start", "end", "tzOffsetMin", "source", "modifiedAt", "stages": [{"start", "end", "stage"}]}],
     "steps":      [{"date": "YYYY-MM-DD", "steps": int}],
     "screenTime": {"from": ms, "to": ms, "launcherPackage", "selfPackage",
                    "sessions": [{"pkg", "start": ms, "end": ms}],
                    "screenEvents": [{"type": "unlock" | "lock" | "screen_on" | "screen_off" | ..., "ts": ms}]}}

Timestamps are ISO-8601 strings or epoch ms. ``stage`` is a Health Connect STAGE_TYPE int (0-6) or a name. The app
sends everything it can read (Android keeps about a week of usage events, Health Connect 30 days of history); the raw
records go to source_records, and the derived rows (sleep_nights, daily_activity, daily_metrics) are computed here.
Each night is scored with the same ``compute_score`` the Apple Health importer uses (sim/sleep_score.py).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..sim.sleep_score import compute_score, rating
from ..timeutil import parse_date

HEALTH = "health_connect"
SCREEN = "screen_time"
ALGORITHM_VERSION = "v1"

MAX_SLEEP = 400
MAX_DAYS = 400
MAX_SESSIONS = 20000       # about a week of heavy use
MAX_SCREEN_EVENTS = 20000
MIN_NIGHT_MIN = 60         # shorter sessions (naps, glitches) are not scored as a night
SLEEP_NEED_MIN = 450
LATE_FROM_H, LATE_TO_H = 22, 3                  # "late" screen time: 22:00-03:00, on the evening's day like a night
NOT_SCREEN_TIME = ("com.android.systemui",)    # plus the launcher the app reports; Digital Wellbeing skips these too
SCREEN_EVENTS = ("screen_on", "screen_off", "unlock", "lock", "shutdown", "startup")

# Health Connect SleepSessionRecord.STAGE_TYPE_*
_HC_STAGES = {0: "unknown", 1: "awake", 2: "asleep", 3: "out_of_bed", 4: "light", 5: "deep", 6: "rem"}
_STAGE_ALIASES = {"sleeping": "asleep", "asleepunspecified": "asleep", "core": "light", "asleepcore": "light",
                  "asleepdeep": "deep", "asleeprem": "rem", "outofbed": "out_of_bed", "in_bed": "inbed"}
ASLEEP = ("asleep", "light", "deep", "rem")
AWAKE = ("awake", "out_of_bed")
_ENGINE_KIND = {"awake": "awake", "out_of_bed": "awake", "light": "core", "deep": "deep", "rem": "rem"}  # models.STAGE_KINDS


# ------------------------------------------------------------------ parsing --
def _ts(v: Any, what: str) -> datetime:
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
        return datetime.fromtimestamp(v / 1000.0, tz=timezone.utc)
    if isinstance(v, str) and v:
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("%s: bad timestamp %r" % (what, v))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    raise ValueError("%s: missing timestamp" % what)


def _day(v: Any, what: str) -> date:
    try:
        return parse_date(str(v))
    except ValueError:
        raise ValueError("%s: bad date %r (expected YYYY-MM-DD)" % (what, v))


def _count(v: Any, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v < 0:
        raise ValueError("%s: expected a non-negative number, got %r" % (what, v))
    return int(round(v))


def _offset(v: Any, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or abs(v) > 14 * 60:
        raise ValueError("%s: bad UTC offset %r" % (what, v))
    return int(v)


def _text(v: Any, limit: int) -> Optional[str]:
    return str(v)[:limit] if v not in (None, "") else None


def _list(obj: Dict[str, Any], key: str, limit: int, where: str) -> List[Any]:
    items = obj.get(key) or []
    if not isinstance(items, list):
        raise ValueError("%s%s must be a list" % (where, key))
    if len(items) > limit:
        raise ValueError("%s%s: at most %d items per sync (got %d)" % (where, key, limit, len(items)))
    return items


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def local(dt: datetime, offset_min: int) -> datetime:
    """Naive local wall-clock time of an aware instant."""
    return dt.astimezone(timezone.utc).replace(tzinfo=None) + timedelta(minutes=offset_min)


def _minutes(a: datetime, b: datetime) -> float:
    return max(0.0, (b - a).total_seconds() / 60.0)


def stage_name(v: Any) -> str:
    if isinstance(v, int) and not isinstance(v, bool):
        return _HC_STAGES.get(v, "unknown")
    s = str(v or "").strip().lower().replace(" ", "").replace("-", "")
    s = _STAGE_ALIASES.get(s, s)
    return s if s in ASLEEP + AWAKE + ("inbed",) else "unknown"


def _sleep_session(raw: Any, i: int) -> Dict[str, Any]:
    w = "sleep[%d]" % i
    if not isinstance(raw, dict):
        raise ValueError(w + " must be an object")
    start, end = _ts(raw.get("start"), w + ".start"), _ts(raw.get("end"), w + ".end")
    if end <= start:
        raise ValueError(w + ": end is not after start")
    stages = []
    for j, st in enumerate(raw.get("stages") or []):
        if not isinstance(st, dict):
            raise ValueError("%s.stages[%d] must be an object" % (w, j))
        s, e = _ts(st.get("start"), "%s.stages[%d].start" % (w, j)), _ts(st.get("end"), "%s.stages[%d].end" % (w, j))
        s, e = max(s, start), min(e, end)
        if e > s:
            stages.append({"start": s, "end": e, "raw": st.get("stage"), "kind": stage_name(st.get("stage"))})
    stages.sort(key=lambda x: x["start"])
    return {"id": _text(raw.get("id"), 200) or "sleep:%d" % int(start.timestamp() * 1000), "start": start, "end": end,
            "offset": _offset(raw.get("tzOffsetMin", 0), w + ".tzOffsetMin"), "origin": _text(raw.get("source"), 200),
            "modified": _ts(raw["modifiedAt"], w + ".modifiedAt") if raw.get("modifiedAt") else None, "stages": stages}


def _screen(raw: Any, offset: int) -> Optional[Dict[str, Any]]:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("screenTime must be an object")
    w = "screenTime."
    frm, to = _ts(raw.get("from"), w + "from"), _ts(raw.get("to"), w + "to")
    if to <= frm:
        raise ValueError("screenTime: to is not after from")
    hidden = set(NOT_SCREEN_TIME) | ({str(raw["launcherPackage"])} if raw.get("launcherPackage") else set())
    sessions: Dict[str, Dict[str, Any]] = {}
    for i, x in enumerate(_list(raw, "sessions", MAX_SESSIONS, w)):
        if not isinstance(x, dict) or not x.get("pkg"):
            raise ValueError("screenTime.sessions[%d] needs a pkg" % i)
        s, e = _ts(x.get("start"), "%ssessions[%d].start" % (w, i)), _ts(x.get("end"), "%ssessions[%d].end" % (w, i))
        if e <= s:
            continue
        pkg = str(x["pkg"])[:200]
        sid = "%s:%d" % (pkg, int(s.timestamp() * 1000))
        if sid not in sessions or e > sessions[sid]["end"]:   # a session still open at the last sync has grown
            sessions[sid] = {"id": sid, "pkg": pkg, "start": s, "end": e, "counted": pkg not in hidden}
    events: Dict[str, Dict[str, Any]] = {}
    for i, x in enumerate(_list(raw, "screenEvents", MAX_SCREEN_EVENTS, w)):
        if not isinstance(x, dict) or x.get("type") not in SCREEN_EVENTS:
            raise ValueError("screenTime.screenEvents[%d]: type must be one of %s" % (i, ", ".join(SCREEN_EVENTS)))
        ts = _ts(x.get("ts"), "%sscreenEvents[%d].ts" % (w, i))
        eid = "%s:%d" % (x["type"], int(ts.timestamp() * 1000))
        events[eid] = {"id": eid, "type": x["type"], "ts": ts}
    return {"from": frm, "to": to, "offset": offset, "sessions": sorted(sessions.values(), key=lambda x: x["start"]),
            "events": sorted(events.values(), key=lambda x: x["ts"])}


def parse(payload: Any) -> Dict[str, Any]:
    """Validate an upload; raises ValueError (-> HTTP 400) on anything malformed."""
    if not isinstance(payload, dict):
        raise ValueError("expected a JSON object")
    device = payload.get("device")
    if not isinstance(device, dict) or not isinstance(device.get("installId"), str) or not 8 <= len(device["installId"]) <= 100:
        raise ValueError("device.installId is required (the id the app generated for this install)")
    platform = device.get("platform") or "android"
    if platform not in ("android", "ios", "web"):
        raise ValueError("device.platform must be android, ios or web")
    offset = _offset(device.get("tzOffsetMin", 0), "device.tzOffsetMin")
    perms = payload.get("permissions") or {}
    if not isinstance(perms, dict):
        raise ValueError("permissions must be an object")
    steps: Dict[date, int] = {}
    for i, it in enumerate(_list(payload, "steps", MAX_DAYS, "")):
        if not isinstance(it, dict):
            raise ValueError("steps[%d] must be an object" % i)
        steps[_day(it.get("date"), "steps[%d].date" % i)] = _count(it.get("steps"), "steps[%d].steps" % i)
    return {
        "device": {"install_id": device["installId"], "platform": platform, "label": _text(device.get("label"), 80),
                   "time_zone": _text(device.get("timeZone"), 64), "offset": offset},
        "permissions": {str(k): bool(v) for k, v in perms.items()},
        "sleep": [_sleep_session(raw, i) for i, raw in enumerate(_list(payload, "sleep", MAX_SLEEP, ""))],
        "steps": sorted(steps.items()),
        "screen": _screen(payload.get("screenTime"), offset),
    }


# -------------------------------------------------------------- raw records --
def _record(source: str, data_type: str, rid: str, start: datetime, end: Optional[datetime], offset: int,
            origin: Optional[str] = None, value: Optional[float] = None, unit: Optional[str] = None,
            payload: Optional[Dict[str, Any]] = None, modified: Optional[datetime] = None) -> Dict[str, Any]:
    # every row has the same keys: PostgREST bulk upserts require it
    return {"source": source, "data_type": data_type, "source_record_id": rid, "data_origin": origin,
            "start_at": iso(start), "end_at": iso(end) if end else None, "start_offset_min": offset,
            "end_offset_min": offset if end else None, "value": value, "unit": unit, "payload": payload or {},
            "source_modified_at": iso(modified) if modified else None}


def source_records(batch: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = [_record(HEALTH, "sleep_session", s["id"], s["start"], s["end"], s["offset"], s["origin"],
                   payload={"stages": [{"start": iso(st["start"]), "end": iso(st["end"]), "stage": st["raw"]} for st in s["stages"]]},
                   modified=s["modified"]) for s in batch["sleep"]]
    off = batch["device"]["offset"]
    for d, n in batch["steps"]:   # the app reads daily totals; one record per local day, overwritten as the day fills
        midnight = datetime.combine(d, time(0, 0), tzinfo=timezone.utc) - timedelta(minutes=off)
        out.append(_record(HEALTH, "steps", "steps:" + d.isoformat(), midnight, midnight + timedelta(days=1), off, value=n, unit="count"))
    sc = batch["screen"]
    if sc:
        out += [_record(SCREEN, "app_usage", x["id"], x["start"], x["end"], sc["offset"], x["pkg"],
                        value=round(_minutes(x["start"], x["end"]), 2), unit="min",
                        payload={} if x["counted"] else {"not_screen_time": True}) for x in sc["sessions"]]
        out += [_record(SCREEN, "screen_event", e["id"], e["ts"], None, sc["offset"], payload={"type": e["type"]})
                for e in sc["events"]]
    return out


def streams(batch: Dict[str, Any]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """{(source, data_type): {permitted, data_from, data_until}} for every stream this upload says something about."""
    spans: Dict[Tuple[str, str], List[datetime]] = {}
    for r in source_records(batch):
        spans.setdefault((r["source"], r["data_type"]), []).extend(
            _ts(v, "") for v in (r["start_at"], r["end_at"]) if v)
    out = {}
    for key in set(spans) | {(HEALTH, "sleep_session"), (HEALTH, "steps"), (SCREEN, "app_usage")}:
        if key not in spans and key[1] not in batch["permissions"]:
            continue
        ts = spans.get(key) or []
        out[key] = {"permitted": batch["permissions"].get(key[1], True),
                    "data_from": iso(min(ts)) if ts else None, "data_until": iso(max(ts)) if ts else None}
    return out


# ------------------------------------------------------------------ derived --
def night_of(start: datetime, offset: int) -> Tuple[date, float]:
    """(night date, bedtime in minutes after 12:00 that date): sleep from 23:10 or 00:40 both belong to the evening."""
    loc = local(start, offset)
    night = (loc - timedelta(hours=12)).date()
    return night, _minutes(datetime.combine(night, time(12, 0)), loc)


def _measure(s: Dict[str, Any]) -> Dict[str, Any]:
    stages = s["stages"]
    asleep = [x for x in stages if x["kind"] in ASLEEP]
    if not asleep:   # no stage data: the whole session counts as asleep
        return {"asleep_min": int(_minutes(s["start"], s["end"])), "awake_min": 0, "interruptions": 0, "deep_min": 0,
                "rem_min": 0, "core_min": 0, "onset": s["start"], "wake": s["end"], "has_stages": False}
    mins = lambda *kinds: int(round(sum(_minutes(x["start"], x["end"]) for x in stages if x["kind"] in kinds)))
    first, last = asleep[0]["start"], asleep[-1]["end"]
    # an interruption is a wake-up between two stretches of sleep, not lying awake before falling asleep or after waking
    interruptions = sum(1 for x in stages if x["kind"] in AWAKE and x["start"] >= first and x["end"] <= last)
    return {"asleep_min": mins(*ASLEEP), "awake_min": mins(*AWAKE), "interruptions": interruptions, "deep_min": mins("deep"),
            "rem_min": mins("rem"), "core_min": mins("light"), "onset": first, "wake": last,
            "has_stages": any(x["kind"] in ("light", "deep", "rem") for x in stages)}


def sleep_night_rows(batch: Dict[str, Any], earlier_bedtimes: Optional[List[float]] = None) -> List[Dict[str, Any]]:
    """One scored sleep_nights row per night: its longest session. ``earlier_bedtimes`` are the stored nights just
    before the first one in this upload (oldest first), so bedtime consistency does not restart at every sync."""
    best: Dict[date, Tuple[Dict[str, Any], Dict[str, Any], float]] = {}
    for s in batch["sleep"]:
        m = _measure(s)
        if m["asleep_min"] < MIN_NIGHT_MIN:
            continue
        night, bed = night_of(s["start"], s["offset"])
        if night not in best or m["asleep_min"] > best[night][1]["asleep_min"]:
            best[night] = (s, m, bed)
    rows, recent = [], list(earlier_bedtimes or [])[-14:]
    for night in sorted(best):
        s, m, bed = best[night]
        score, parts = compute_score({"duration_min": m["asleep_min"], "bedtime_min": bed, "interruptions": m["interruptions"],
                                      "awake_min": m["awake_min"], "sleep_need_min": SLEEP_NEED_MIN}, recent)
        recent = (recent + [bed])[-14:]
        rows.append({
            "night_date": night.isoformat(), "source": HEALTH, "data_origin": s["origin"], "utc_offset_min": s["offset"],
            "in_bed_at": iso(s["start"]), "onset_at": iso(m["onset"]), "wake_at": iso(m["wake"]), "out_of_bed_at": iso(s["end"]),
            "asleep_min": m["asleep_min"], "deep_min": m["deep_min"], "rem_min": m["rem_min"], "core_min": m["core_min"],
            "awake_min": m["awake_min"], "interruptions": m["interruptions"], "has_stages": m["has_stages"],
            "stages": [{"kind": _ENGINE_KIND[x["kind"]], "start": iso(x["start"]), "end": iso(x["end"])}
                       for x in s["stages"] if x["kind"] in _ENGINE_KIND],
            "score": score, "score_parts": parts, "score_source": "stressless", "algorithm_version": ALGORITHM_VERSION,
        })
    return rows


def bedtime_min(in_bed_at: str, offset: int) -> float:
    return night_of(_ts(in_bed_at, "in_bed_at"), offset)[1]


def activity_rows(batch: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{"day": d.isoformat(), "source": HEALTH, "utc_offset_min": batch["device"]["offset"], "steps": n}
            for d, n in batch["steps"]]


def _overlap(a: datetime, b: datetime, lo: datetime, hi: datetime) -> float:
    return _minutes(max(a, lo), min(b, hi)) if min(b, hi) > max(a, lo) else 0.0


def screen_days(batch: Dict[str, Any]) -> Dict[date, Dict[str, float]]:
    """Per local day: minutes, late minutes and unlocks. Only days the upload covers completely from midnight (plus
    today so far) are returned, so a partial first day never overwrites a stored full one. Days are cut with the
    phone's current offset; a DST change inside the synced week shifts that week's boundaries by an hour."""
    sc = batch["screen"]
    if not sc:
        return {}
    off = sc["offset"]
    first, last = local(sc["from"], off), local(sc["to"], off)
    first_day = first.date() if first.time() == time(0, 0) else first.date() + timedelta(days=1)
    days: Dict[date, Dict[str, float]] = {}
    for d in range((last.date() - first_day).days + 1):
        days[first_day + timedelta(days=d)] = {"minutes": 0.0, "late_minutes": 0.0, "pickups": 0}
    for x in sc["sessions"]:
        if not x["counted"]:
            continue
        a, b = local(x["start"], off), local(x["end"], off)
        d = a.date() - timedelta(days=1)
        while d <= b.date():
            if d in days:
                midnight = datetime.combine(d, time(0, 0))
                days[d]["minutes"] += _overlap(a, b, midnight, midnight + timedelta(days=1))
                days[d]["late_minutes"] += _overlap(a, b, midnight + timedelta(hours=LATE_FROM_H), midnight + timedelta(days=1, hours=LATE_TO_H))
            d += timedelta(days=1)
    for e in sc["events"]:
        d = local(e["ts"], off).date()
        if e["type"] == "unlock" and d in days:
            days[d]["pickups"] += 1
    return days


def metric_rows(batch: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{"day": d.isoformat(), "metric_key": "screen." + k, "value": round(v, 1), "source": SCREEN}
            for d, vals in sorted(screen_days(batch).items()) for k, v in vals.items()]


def summary(batch: Dict[str, Any], nights: List[Dict[str, Any]], metrics: List[Dict[str, Any]], records: int) -> Dict[str, Any]:
    """What the app shows after a sync."""
    sc = batch["screen"]
    return {"stored": {"records": records, "nights": len(nights), "step_days": len(batch["steps"]),
                       "screen_sessions": len(sc["sessions"]) if sc else 0, "screen_days": len({m["day"] for m in metrics})},
            "nights": [{"night": r["night_date"], "score": r["score"], "rating": rating(r["score"]), "asleep_min": r["asleep_min"],
                        "parts": r["score_parts"]} for r in nights]}
