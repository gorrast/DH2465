"""What-if: modify a day's events and predict the night's sleep score (SPEC §7.8)."""
from __future__ import annotations

import copy
from datetime import date, timedelta
from typing import Any, Dict, List, Sequence

from ..models import CalendarEvent, Dataset, WhatIfResult, new_id
from ..timeutil import at, parse_dt
from .attribution import FitResult, predict, predict_interval
from .features import day_features


def apply_modifications(events: Sequence[CalendarEvent], mods: Sequence[Dict[str, Any]], d: date, tzname: str) -> List[CalendarEvent]:
    out = [copy.copy(e) for e in events]
    by_id = {e.id: e for e in out}
    for i, m in enumerate(mods or []):
        op = m.get("op")
        if op == "add":
            spec = m.get("event") or {}
            try:
                start = parse_dt(spec["start"], tzname)
                end = parse_dt(spec["end"], tzname)
            except (KeyError, ValueError, TypeError):
                raise ValueError("add needs event.start and event.end as ISO datetimes")
            out.append(CalendarEvent(id=new_id("ev", "whatif", d, i), title=str(spec.get("title") or "New event"), start=start, end=end,
                                     type=str(spec.get("type") or "meeting"), location_hint=spec.get("location_hint"), source="user"))
            continue
        ev = by_id.get(str(m.get("event_id")))
        if ev is None:
            raise ValueError("unknown event_id %r" % m.get("event_id"))
        if op == "remove":
            out = [e for e in out if e.id != ev.id]
            by_id.pop(ev.id, None)
        elif op == "shift":
            delta = timedelta(hours=float(m.get("hours", 0)))
            ev.start, ev.end = ev.start + delta, ev.end + delta
        elif op == "end_at":
            hour = float(m.get("hour", 18.0))
            new_end = at(ev.start.date(), hour, tzname=tzname)
            if new_end <= ev.start:
                new_end = ev.start + timedelta(minutes=15)
            ev.end = new_end
        elif op == "to_protected":
            ev.type = "protected"
            ev.title = "Wind down (StressLess)"
        else:
            raise ValueError("unknown op %r" % op)
    return out


def predict_day(ds: Dataset, d: date, mods: Sequence[Dict[str, Any]], fit_: FitResult) -> WhatIfResult:
    tzname = ds.persona.tz
    before_events = ds.events_on(d)
    after_events = apply_modifications(before_events, mods, d, tzname)
    fb = day_features(ds, d, events=before_events)
    fa = day_features(ds, d, events=after_events)
    rb, ra = fb.regressors(), fa.regressors()
    pb, pa = predict(fit_, rb), predict(fit_, ra)
    lo, hi = predict_interval(fit_, rb, ra)
    changed = [k for k in rb if rb[k] != ra[k]]
    return WhatIfResult(date=d, baseline_pred=round(pb, 1), modified_pred=round(pa, 1), delta=round(pa - pb, 1),
                        rmse=round(fit_.rmse_loo, 1), features_before=fb, features_after=fa, changed_factors=changed,
                        events_after=after_events, delta_low=round(lo, 1), delta_high=round(hi, 1))
