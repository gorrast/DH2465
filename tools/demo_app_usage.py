"""Per-app phone sessions for the demo account, for the Weekly tab's app cards ("Your most-used apps", "Apps that get
you going", the app logos in its header, and the screen minutes in "Find your flow").

    uv run --env-file .env.local python tools/demo_app_usage.py --user <demo uuid>            # dry run: summary only
    uv run --env-file .env.local python tools/demo_app_usage.py --user <demo uuid> --write    # replace the sessions

The sessions follow the data seed_demo.py wrote, so the numbers agree with the rest of the app:

* one session starts at each of the seed's unlocks (source_records, data_type screen_event), and none runs into the
  next unlock, so pickups and sessions line up;
* each day's sessions add up to that day's screen time (daily_metrics screen.minutes), and the ones after 22:00 to
  its late-evening minutes (screen.late_minutes) as far as that evening's unlocks leave room;
* the app depends on the time of day: work apps in working hours, social and video apps in the evening.

Nothing else in the app reads app sessions: the backend counts unlocks and the daily screen totals, which this script
does not touch. It only replaces rows with source 'manual' and data_type 'app_usage' (the hand-added set, which
seed_demo.py keeps on a re-seed), and --write saves the rows it replaces to a JSON file first. Re-run it after a
re-seed that changes the unlocks. Uses SUPABASE_SERVICE_ROLE_KEY.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

SEED = 20261103
LABEL = "SYNTHETIC FUN STATS DEMO ONLY - NOT REAL HEALTH DATA"   # the label of the hand-added rows it replaces
LATE_FROM = 22 * 60                                               # screen.late_minutes counts from 22:00
MIN_SESSION, MAX_LAST = 0.25, 40.0                                # a glance; the day's last session at most
GAP = 0.2                                                         # minutes left free before the next unlock

# package -> how long a session in it tends to be (relative). Display names come from lib/app-brands.ts.
APPS = {
    "com.Slack": 0.7, "com.microsoft.office.outlook": 0.8, "com.microsoft.teams": 1.0, "com.android.chrome": 1.2,
    "com.linkedin.android": 1.0, "com.whatsapp": 0.6, "com.instagram.android": 1.5, "com.google.android.youtube": 2.2,
    "com.reddit.frontpage": 1.6, "com.spotify.music": 0.5, "com.google.android.apps.maps": 0.8,
    "com.netflix.mediaclient": 2.5,
}
# which app a session opens, by part of the day (weights)
MIX = {
    "morning": {"com.spotify.music": 18, "com.whatsapp": 18, "com.instagram.android": 14, "com.microsoft.office.outlook": 16,
                "com.Slack": 12, "com.android.chrome": 10, "com.google.android.apps.maps": 6, "com.linkedin.android": 6},
    "work": {"com.Slack": 30, "com.microsoft.office.outlook": 22, "com.microsoft.teams": 12, "com.android.chrome": 10,
             "com.whatsapp": 8, "com.instagram.android": 7, "com.linkedin.android": 6, "com.spotify.music": 3,
             "com.google.android.apps.maps": 2},
    "evening": {"com.instagram.android": 22, "com.whatsapp": 19, "com.google.android.youtube": 15, "com.android.chrome": 9,
                "com.reddit.frontpage": 9, "com.spotify.music": 7, "com.Slack": 6, "com.netflix.mediaclient": 5,
                "com.google.android.apps.maps": 4, "com.linkedin.android": 4},
    "late": {"com.instagram.android": 30, "com.google.android.youtube": 25, "com.reddit.frontpage": 15,
             "com.whatsapp": 14, "com.android.chrome": 9, "com.netflix.mediaclient": 7},
    "weekend": {"com.instagram.android": 22, "com.whatsapp": 20, "com.google.android.youtube": 15, "com.spotify.music": 10,
                "com.android.chrome": 9, "com.reddit.frontpage": 9, "com.google.android.apps.maps": 9,
                "com.netflix.mediaclient": 4, "com.Slack": 2},
}


def db(method: str, table: str, params: Optional[Dict[str, str]] = None, body: Any = None,
       prefer: Optional[str] = None) -> Any:
    url = (os.environ.get("SUPABASE_URL") or os.environ["NEXT_PUBLIC_SUPABASE_URL"]).rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key, "Authorization": "Bearer " + key, "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    req = urllib.request.Request("%s/rest/v1/%s?%s" % (url, table, urllib.parse.urlencode(params or {})), method=method,
                                 headers=headers, data=None if body is None else json.dumps(body).encode())
    with urllib.request.urlopen(req) as res:
        text = res.read().decode()
    return json.loads(text) if text else None


def all_rows(table: str, params: Dict[str, str], order: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    while True:
        page = db("GET", table, dict(params, order=order, offset=str(len(out)), limit="1000"))
        out += page
        if len(page) < 1000:
            return out


def part_of_day(local: datetime) -> str:
    m = local.hour * 60 + local.minute
    if m >= LATE_FROM:
        return "late"
    if local.weekday() >= 5:
        return "weekend"
    return "morning" if m < 8 * 60 else "work" if m < 17 * 60 else "evening"


def fill(target: float, caps: List[float], weights: List[float]) -> List[float]:
    """Split target over the sessions in proportion to their weights, none above its cap (water-filling)."""
    out = [0.0] * len(caps)
    free = [i for i in range(len(caps)) if caps[i] > 0]
    left = target
    while free and left > 1e-9:
        total = sum(weights[i] for i in free)
        full = [i for i in free if left * weights[i] / total >= caps[i]]
        if not full:
            for i in free:
                out[i] = left * weights[i] / total
            return out
        for i in full:
            out[i] = caps[i]
            left -= caps[i]
        free = [i for i in free if i not in full]
    return out


def sessions_for_day(day: str, unlocks: List[Tuple[datetime, int]], minutes: float, late: float,
                     rng: random.Random) -> List[Dict[str, Any]]:
    """unlocks: (UTC time, offset in minutes), sorted. Returns the day's sessions as source_records rows."""
    local = [t + timedelta(minutes=off) for t, off in unlocks]
    gaps = [(unlocks[i + 1][0] - unlocks[i][0]).total_seconds() / 60 if i + 1 < len(unlocks) else MAX_LAST
            for i in range(len(unlocks))]
    # the app opens a few seconds after the unlock (never past the next one)
    starts = [t + timedelta(minutes=min(rng.uniform(1, 6) / 60, 0.25 * gaps[i])) for i, (t, _) in enumerate(unlocks)]
    apps = [rng.choices(list(MIX[part_of_day(lt)]), list(MIX[part_of_day(lt)].values()))[0] for lt in local]
    caps, weights, is_late = [], [], []
    for i, lt in enumerate(local):
        m = lt.hour * 60 + lt.minute + lt.second / 60
        # room until the next unlock, leaving GAP (or half the gap, when unlocks come seconds apart) free
        nxt = ((starts[i + 1] - starts[i]).total_seconds() / 60 if i + 1 < len(unlocks) else MAX_LAST)
        nxt -= min(GAP, nxt / 2)
        late_i = m >= LATE_FROM
        cap = min(nxt, MAX_LAST) if late_i else min(nxt, LATE_FROM - m, MAX_LAST)   # daytime sessions end by 22:00
        caps.append(max(cap, 0.0))
        weights.append(APPS[apps[i]] * rng.lognormvariate(0, 0.6))
        is_late.append(late_i)
    idx_late = [i for i in range(len(local)) if is_late[i]]
    idx_day = [i for i in range(len(local)) if not is_late[i]]
    dur = [0.0] * len(local)
    got_late = fill(late, [caps[i] for i in idx_late], [weights[i] for i in idx_late])
    for i, d in zip(idx_late, got_late):
        dur[i] = d
    rest = minutes - sum(got_late)      # what the evening could not hold moves to the daytime, so the day's total holds
    for i, d in zip(idx_day, fill(rest, [caps[i] for i in idx_day], [weights[i] for i in idx_day])):
        dur[i] = d
    rows = []
    for i, (t, off) in enumerate(unlocks):
        d = max(dur[i], min(MIN_SESSION, caps[i]))     # at least a glance, where there is room for one
        if d <= 0:
            continue
        parts = [(apps[i], d)]
        if d > 8 and rng.random() < 0.3:                    # a longer session sometimes switches app halfway
            other = rng.choices(list(MIX[part_of_day(local[i])]), list(MIX[part_of_day(local[i])].values()))[0]
            if other != apps[i]:
                cut = d * rng.uniform(0.35, 0.65)
                parts = [(apps[i], cut), (other, d - cut)]
        start = starts[i]
        for pkg, length in parts:
            end = start + timedelta(minutes=length)
            rows.append({"source": "manual", "data_type": "app_usage",
                         "source_record_id": "%s:%d" % (pkg, int(start.timestamp() * 1000)), "data_origin": LABEL,
                         "start_at": start.isoformat(), "end_at": end.isoformat(), "start_offset_min": off,
                         "end_offset_min": off, "value": round(length, 2), "unit": "min", "payload": {},
                         "source_modified_at": None, "_day": day})
            start = end
    return rows


def build(user: str) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, float]]]:
    metrics: Dict[str, Dict[str, float]] = defaultdict(dict)
    for r in all_rows("daily_metrics", {"user_id": "eq." + user, "metric_key": "like.screen.*", "select": "day,metric_key,value"},
                      "day,metric_key"):
        metrics[r["day"]][r["metric_key"]] = r["value"]
    by_day: Dict[str, List[Tuple[datetime, int]]] = defaultdict(list)
    for r in all_rows("source_records", {"user_id": "eq." + user, "data_type": "eq.screen_event", "source": "eq.screen_time",
                                         "payload->>type": "eq.unlock", "select": "start_at,start_offset_min"}, "start_at"):
        t = datetime.fromisoformat(r["start_at"]).astimezone(timezone.utc)
        off = r["start_offset_min"] or 0
        by_day[(t + timedelta(minutes=off)).date().isoformat()].append((t, off))
    rng = random.Random(SEED)
    rows: List[Dict[str, Any]] = []
    for day in sorted(by_day):
        m = metrics.get(day, {})
        if "screen.minutes" not in m:
            continue
        rows += sessions_for_day(day, sorted(by_day[day]), m["screen.minutes"], m.get("screen.late_minutes", 0.0), rng)
    return rows, metrics


def report(rows: List[Dict[str, Any]], metrics: Dict[str, Dict[str, float]]) -> None:
    days = defaultdict(lambda: [0.0, 0.0, 0])
    overlaps = 0
    last_end: Optional[datetime] = None
    for r in sorted(rows, key=lambda r: r["start_at"]):
        s, e = datetime.fromisoformat(r["start_at"]), datetime.fromisoformat(r["end_at"])
        if last_end and s < last_end - timedelta(seconds=1):
            overlaps += 1
        last_end = max(last_end or e, e)
        local = s + timedelta(minutes=r["start_offset_min"])
        days[r["_day"]][0] += r["value"]
        days[r["_day"]][1] += r["value"] if local.hour * 60 + local.minute >= LATE_FROM else 0
        days[r["_day"]][2] += 1
    total_err = [abs(v[0] - metrics[d]["screen.minutes"]) for d, v in days.items()]
    late_err = [v[1] - metrics[d].get("screen.late_minutes", 0) for d, v in days.items()]
    print("%d sessions over %d days (%s to %s), %d overlapping" % (len(rows), len(days), min(days), max(days), overlaps))
    print("day totals vs screen.minutes: largest difference %.2f min" % max(total_err))
    print("after 22:00 vs screen.late_minutes: mean %+.1f min, %d days short by more than 5 min"
          % (sum(late_err) / len(late_err), sum(1 for x in late_err if x < -5)))
    lengths = sorted(r["value"] for r in rows)
    print("session length: median %.1f min, 90th percentile %.1f, longest %.1f"
          % (lengths[len(lengths) // 2], lengths[int(len(lengths) * 0.9)], lengths[-1]))
    for d in sorted(days)[-7:]:
        print("  %s  %3d sessions  %6.1f min (screen.minutes %6.1f)  after 22:00 %5.1f (late_minutes %5.1f)"
              % (d, days[d][2], days[d][0], metrics[d]["screen.minutes"], days[d][1], metrics[d].get("screen.late_minutes", 0)))
    last7 = sorted(days)[-7:]
    top = Counter()
    for r in rows:
        if r["_day"] in last7:
            top[r["source_record_id"].split(":")[0]] += r["value"]
    print("most-used apps, last 7 days:", ", ".join("%s %.0f min" % (p, v) for p, v in top.most_common(6)))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user", required=True, help="the demo account's user id")
    ap.add_argument("--write", action="store_true", help="replace the account's hand-added app sessions")
    ap.add_argument("--backup", default="app_usage_backup.json", help="where --write saves the rows it replaces")
    args = ap.parse_args()
    rows, metrics = build(args.user)
    if not rows:
        sys.exit("No seeded unlocks or screen time for this user: run seed_demo.py first.")
    report(rows, metrics)
    if not args.write:
        print("Dry run: nothing written. Add --write to replace the sessions.")
        return
    old_filter = {"user_id": "eq." + args.user, "source": "eq.manual", "data_type": "eq.app_usage"}
    old = all_rows("source_records", dict(old_filter, select="*"), "id")
    with open(args.backup, "w") as f:
        json.dump(old, f)
    print("Saved the %d rows being replaced to %s" % (len(old), args.backup))
    db("DELETE", "source_records", old_filter, prefer="return=minimal")
    batch = [{k: v for k, v in dict(r, user_id=args.user).items() if not k.startswith("_")} for r in rows]
    for i in range(0, len(batch), 500):
        db("POST", "source_records", {"on_conflict": "user_id,source,source_record_id"}, batch[i:i + 500],
           prefer="resolution=merge-duplicates,return=minimal")
    print("Wrote %d app sessions." % len(batch))


if __name__ == "__main__":
    main()
