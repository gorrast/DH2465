"""Google Takeout location history importer: Semantic Location History and Timeline.json (SPEC §6.1)."""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Any, Dict, List

from ..models import LocationVisit, new_id
from .base import classify_place, parse_ts

log = logging.getLogger("stressless.connectors.takeout")


def _files(path: str) -> List[str]:
    if os.path.isdir(path):
        out = []
        for root, _, files in os.walk(path):
            out += [os.path.join(root, f) for f in files if f.lower().endswith(".json")]
        return sorted(out)
    return [path]


def _visit(d: date, seq: int, ptype: str, name: str, s, e, lat: float, lon: float) -> LocationVisit:
    return LocationVisit(id=new_id("vis", "takeout", d, seq), place_type=ptype, place_name=name, start=s, end=e, lat=lat, lon=lon, source="takeout")


def parse_timeline(path: str, tzname: str, start: date, end: date) -> List[LocationVisit]:
    out: List[LocationVisit] = []
    seq: Dict[date, int] = {}

    def nxt(d: date) -> int:
        seq[d] = seq.get(d, 0) + 1
        return seq[d] - 1

    for f in _files(path):
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            log.warning("skipping %s: %s", f, exc)
            continue
        for obj in data.get("timelineObjects", []) or []:            # Semantic Location History
            pv = obj.get("placeVisit")
            seg = obj.get("activitySegment")
            item = pv or seg
            if not item:
                continue
            dur = item.get("duration") or {}
            s_raw = dur.get("startTimestamp") or dur.get("startTimestampMs")
            e_raw = dur.get("endTimestamp") or dur.get("endTimestampMs")
            if not s_raw or not e_raw:
                continue
            try:
                s, e = parse_ts(s_raw, tzname), parse_ts(e_raw, tzname)
            except ValueError:
                continue
            if s.date() < start or s.date() > end:
                continue
            if pv:
                loc = pv.get("location") or {}
                name = loc.get("name") or loc.get("address") or "Unknown place"
                lat = float(loc.get("latitudeE7", 0)) / 1e7
                lon = float(loc.get("longitudeE7", 0)) / 1e7
                out.append(_visit(s.date(), nxt(s.date()), classify_place(name, loc.get("semanticType")), name, s, e, lat, lon))
            else:
                out.append(_visit(s.date(), nxt(s.date()), "transit", (seg.get("activityType") or "In transit").replace("_", " ").title(), s, e, 0.0, 0.0))
        for seg in data.get("semanticSegments", []) or []:            # Timeline.json (2024+)
            s_raw, e_raw = seg.get("startTime"), seg.get("endTime")
            if not s_raw or not e_raw:
                continue
            try:
                s, e = parse_ts(s_raw, tzname), parse_ts(e_raw, tzname)
            except ValueError:
                continue
            if s.date() < start or s.date() > end:
                continue
            if "visit" in seg:
                cand = (seg["visit"].get("topCandidate") or {})
                name = cand.get("placeLocation", {}).get("name") if isinstance(cand.get("placeLocation"), dict) else None
                name = name or cand.get("placeId") or "Unknown place"
                sem = cand.get("semanticType")
                latlng = cand.get("placeLocation", {}).get("latLng", "") if isinstance(cand.get("placeLocation"), dict) else ""
                lat = lon = 0.0
                try:
                    lat_s, lon_s = latlng.replace("°", "").split(",")
                    lat, lon = float(lat_s), float(lon_s)
                except (ValueError, AttributeError):
                    pass
                out.append(_visit(s.date(), nxt(s.date()), classify_place(name, sem), name, s, e, lat, lon))
            elif "activity" in seg:
                out.append(_visit(s.date(), nxt(s.date()), "transit", "In transit", s, e, 0.0, 0.0))
    out.sort(key=lambda v: v.start)
    return out
