"""Fill a demo account with 90 days of believable data, with links planted on purpose.

    uv run --env-file .env.local python tools/seed_demo.py --user <demo uuid> --calibrate <your uuid>           # dry run
    uv run --env-file .env.local python tools/seed_demo.py --user <demo uuid> --calibrate <your uuid> --write   # replace
    uv run --env-file .env.local python tools/seed_demo.py --user <demo uuid> --remove                          # empty it

Everything is generated: sleep, minute heart rate, steps, calendar, Spotify, Netflix, screen time (daily totals and
the time of every unlock) and check-ins. The
simulator (stressless.sim) makes the body and the calendar; ``--calibrate`` only *reads* a real account to copy its
shape (usual bedtime and wake, sleep need, resting heart rate, HRV, steps, screen time), never its rows.

The links in PLANTED are the answer key: the dry run builds the dataset from the planned rows, runs the links engine
on it and prints which planted links it found, which it missed and which it found that we did not plant. Write the
key with ``--key FILE`` to check a report against it later.

Generate once and keep it current: write with ``--date D`` and run the server with ``STRESSLESS_ANCHOR=D``, so every
report sees the same "today", the same last night and the same links (the anchor applies to every user on that server).

``--write`` and ``--remove`` replace or delete *all* of the demo user's data rows, so they refuse to run on an account
that has data from anywhere but this script (a real phone sync or Google Calendar). Uses SUPABASE_SERVICE_ROLE_KEY.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from stressless.connectors.real_data import load_dataset  # noqa: E402
from stressless.engine.lifestyle import lifestyle_patterns  # noqa: E402
from stressless.models import CalendarEvent, Dataset, DayFeatures, Persona  # noqa: E402
from stressless.sim import generate_dataset, get_persona  # noqa: E402
from stressless.store.base import UserStore  # noqa: E402
from stressless.store.memory import MemoryStore  # noqa: E402
from stressless.timeutil import at, tz  # noqa: E402

# --------------------------------------------------------------------------- #
# Config: the story. Change these, run the dry run, see what the engine finds.
# --------------------------------------------------------------------------- #
CONFIG: Dict[str, Any] = {
    "days": 90,
    "seed": 12,                             # the dry run with --sweep 40 ranks seeds; the best depends on the date
    "name": "Demo",
    "time_zone": "Europe/Stockholm",
    "behaviour": "alex",                    # simulator persona whose weekend rhythm and sensitivities are the base
    # calendar -> sleep effects, in sleep-score points per unit (sim/personas.py REF_TABLE); 0 = no effect
    "sensitivities": {"meetings_over_3": -2.0, "b2b_over_2": -1.5, "late_meeting_hours": -4.0, "evening_social": -16.0,
                      "workout_morning": 15.0, "workout_late": -3.0, "travel": -9.0, "early_start": -3.0,
                      "protected_evening": 4.0},
    # The week of a student with a part-time café job: (title, [(weekday, from, to)], category, place, guests, effect).
    # Each title is a recurring series; "effect" names an entry in class_effects.
    "week": [("Statistics lecture", [(1, 8.25, 12.0), (3, 8.25, 12.0)], "meeting", "Lecture hall F1", 30, "stress"),
             ("Interaction Design studio", [(0, 13.0, 15.0), (4, 9.0, 11.0)], "meeting", "Design studio", 12, "enjoy"),
             ("Café shift", [(5, 7.0, 13.0), (6, 16.0, 21.0)], "meeting", "Café", 3, None)],
    # stored with another category than the simulator uses: the shift is a meeting to the simulator (so the late
    # shift delays bedtime), but the app would call it a meeting ("late meetings", "time in meetings")
    "stored_as": {"Café shift": "personal"},
    # per class day: daytime heart rate from the class to 22:00, minutes to fall asleep, overnight HRV and resting HR
    "class_effects": {"stress": {"day_hr": 6, "onset_min": 30, "hrv": -0.20, "resting_hr": 3},
                      "enjoy": {"day_hr": -3, "onset_min": -8, "hrv": 0.06, "resting_hr": -1}},
    "study": {"title": "Study session", "place": "KTH Library", "share": {"weekday": 0.55, "sat": 0.15, "sun": 0.6},
              "slots": {"weekday": [(14.0, 16.0), (16.0, 18.0), (18.5, 20.5)], "weekend": [(13.0, 16.0)]}},
    # focus music: on this share of study blocks the artist plays through it; those blocks keep only this share of
    # their pickups (unlocks) and have a calmer heart rate, and those days have less screen time
    "focus_artist": ("Ludovico Einaudi", "modern classical", 0.55),
    "focus_effects": {"pickups": 0.35, "screen_minutes": -40, "hr": -4},
    "waking": {"weekday": (7.5, 23.5), "weekend": (9.5, 24.0)},   # hours the day's unlocks fall in
    # on days without a class effect, so the class links and the workout links stay apart
    "workouts": [("Morning run", "Djurgården", [(2, 7.0, 7.75, 0.95)]),
                 ("Gym", "SATS KTH", [(2, 18.0, 19.0, 0.6), (5, 15.0, 16.0, 0.6)])],
    "late_gym": 0.3,                        # share of gym sessions moved to 20:00-21:00
    "socials": [("Pub night", 3, 19.0, 23.0, 0.45), ("Dinner with friends", 4, 19.5, 23.5, 0.5),
                ("Party", 5, 20.0, 23.75, 0.45)],
    "one_offs": [("Group project meeting", 2, 10.0, 11.0, 0.6, "meeting", "Group room", 4)],
    # music: the artists the engine tests, as (artist, share of days, minutes per day), and a long tail of others
    # (one on most days, too rare for the engine to test: each tested artist is another chance of a false link)
    "artists": [("Metallica", 0.30, (20, 60)), ("Bon Iver", 0.40, (15, 45))],
    "tail": ["Robyn", "Fleetwood Mac", "Daft Punk", "First Aid Kit", "Kent", "Lykke Li", "The National", "Phoebe Bridgers",
             "Tame Impala", "Radiohead", "Little Dragon", "José González", "Beyoncé", "Arctic Monkeys", "Taylor Swift",
             "Kendrick Lamar", "The xx", "Fever Ray", "Avicii", "Veronica Maggio", "Håkan Hellström", "ABBA",
             "Miriam Bryant", "Zara Larsson", "The Cure", "Massive Attack", "Portishead", "Nick Drake", "Bonobo",
             "Khruangbin", "Haim", "Lorde", "Frank Ocean", "SZA", "Joni Mitchell", "Fleet Foxes", "Sufjan Stevens",
             "The Knife", "Jungle", "Caribou"],
    "tail_minutes": (10, 30),
    "hr_artist": "Metallica",               # its days: daytime heart rate up by hr_artist_bpm
    "hr_artist_bpm": 5,
    "podcast": ("Sommar i P1", 0.25, (25, 55)),
    "shows": ["Stranger Things", "Bron", "The Crown", "Dark"],
    "netflix_days": 0.40,                   # share of evenings with Netflix
    "netflix_late": 0.45,                   # share of those running past 22:00 (pushes bedtime later)
    "late_screen": 0.18,                    # share of other evenings with long late phone use
    "late_screen_delay": (30, 50),          # minutes late Netflix or late phone use push bedtime, on top of the simulator's 20
    "run_steps": 5000,                      # extra steps on a run day
    "coffee_heavy": 0.22,                   # share of days with 4-5 cups (slower to fall asleep)
    "checkin_logged": 0.85,                 # share of days with a coffee/alcohol check-in
}

# The answer key: cause key in engine/lifestyle.py -> what we planted. "strength": strong = should be found with
# confidence; weak = may be found, but never the other way round; none = planted *without* an effect (a control: an
# early hint is fine, the engine gives one to about half of all causes without an effect; a strong link is not).
# Links from sleep to sleep (off_rhythm, sleep_debt, short_night) follow from the night itself and are not planted.
PLANTED: Dict[str, Dict[str, str]] = {
    "series_statistics_lecture": {"direction": "hurt", "strength": "strong",
                                  "how": "stressful class: daytime HR +6, 30 min slower to sleep, HRV -20 %"},
    "series_interaction_design_studio": {"direction": "helped", "strength": "strong",
                                         "how": "enjoyed class: daytime HR -3, 8 min faster to sleep, HRV +6 %"},
    "series_café_shift":  {"direction": "hurt", "strength": "strong",
                           "how": "early Saturday and late Sunday shifts: later bedtime, earlier wake (simulator)"},
    "busy_days":          {"direction": "hurt", "strength": "weak", "how": "the long Statistics days"},
    "pair_ludovico_einaudi_during_study_session": {"direction": "helped", "strength": "strong",
                                     "how": "study blocks with it: 65 % fewer pickups and HR -4 while studying, "
                                            "40 min less screen time that day"},
    "artist_ludovico_einaudi": {"direction": "helped", "strength": "weak", "how": "follows from the calmer study blocks"},
    "social_evenings":    {"direction": "hurt", "strength": "strong", "how": "~90 min later bedtime, often drinks (simulator)"},
    "cardio_days":        {"direction": "helped", "strength": "strong", "how": "morning runs: faster onset, less waking, higher HRV (simulator)"},
    "early_starts":       {"direction": "hurt", "strength": "weak", "how": "Saturday opening shifts: wake earlier (simulator)"},
    "late_workouts":      {"direction": "hurt", "strength": "weak", "how": "late gym: later bedtime, less deep sleep (simulator)"},
    "active_days":        {"direction": "helped", "strength": "weak", "how": "follows from the runs (5 000 extra steps)"},
    "workout_days":       {"direction": "helped", "strength": "weak", "how": "follows from the runs"},
    "late_streaming":     {"direction": "hurt", "strength": "strong", "how": "Netflix past 22:00 pushes bedtime ~20 min"},
    "late_screen":        {"direction": "hurt", "strength": "strong", "how": "late phone use pushes bedtime ~20 min"},
    "alcohol":            {"direction": "hurt", "strength": "strong", "how": "lower HRV, higher resting HR (simulator)"},
    "artist_metallica":   {"direction": "hurt", "strength": "strong", "how": "daytime heart rate +5 bpm"},
    "more_coffee":        {"direction": "hurt", "strength": "weak", "how": "5 min slower to fall asleep"},
    "artist_bon_iver":    {"direction": "none", "strength": "none", "how": "control: played often, no effect"},
    "podcast_days":       {"direction": "none", "strength": "none", "how": "control: no effect"},
    "artist_sommar_i_p1": {"direction": "none", "strength": "none", "how": "control: the podcast as its own cause"},
}

SEED = "seed-demo"                          # data_origin / provider_account_id / id prefix of every seeded row
HEALTH, SCREEN = "health_connect", "screen_time"


# --------------------------------------------------------------------------- #
# Database (service role; every query is filtered on one user id)
# --------------------------------------------------------------------------- #
def db(method: str, table: str, *, params: Optional[Dict[str, str]] = None, json_body: Any = None,
       prefer: Optional[str] = None, api: str = "rest/v1") -> Any:
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    url = (os.environ.get("SUPABASE_URL") or os.environ["NEXT_PUBLIC_SUPABASE_URL"]).rstrip("/")
    headers = {"apikey": key, "Content-Type": "application/json"}
    if not key.startswith("sb_"):  # legacy service_role JWT; the newer sb_secret_ keys go in apikey only
        headers["Authorization"] = "Bearer " + key
    if prefer:
        headers["Prefer"] = prefer
    r = httpx.request(method, "%s/%s/%s" % (url, api, table), params=params, json=json_body, headers=headers, timeout=60.0)
    if r.status_code >= 400:
        raise SystemExit("Supabase %s %s -> %d %s" % (method, table, r.status_code, r.text[:300]))
    return r.json() if r.content else None


class AdminStore(UserStore):
    """Read-only view of one user's real-data tables, for calibration."""

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id

    def time_zone(self) -> str:
        rows = db("GET", "profiles", params={"user_id": "eq." + self.user_id, "select": "time_zone"}) or []
        return (rows[0].get("time_zone") if rows else None) or CONFIG["time_zone"]

    def rows(self, table, column=None, lo=None, hi=None, where=None):
        params = dict({"select": "*", "user_id": "eq." + self.user_id}, **{k: "eq." + v for k, v in (where or {}).items()})
        conds = ["%s.gte.%s" % (column, lo)] * (lo is not None) + ["%s.lte.%s" % (column, hi)] * (hi is not None)
        if column:
            params["order"] = column
        if conds:
            params["and"] = "(%s)" % ",".join(conds)
        out: List[Dict[str, Any]] = []
        while True:
            page = db("GET", table, params=dict(params, limit="1000", offset=str(len(out)))) or []
            out.extend(page)
            if len(page) < 1000:
                return out


# --------------------------------------------------------------------------- #
# Calibration
# --------------------------------------------------------------------------- #
def _med(vals: List[float], default: float) -> float:
    vals = [v for v in vals if v is not None]
    return float(statistics.median(vals)) if len(vals) >= 5 else default


def calibrate(user_id: Optional[str], today: date) -> Dict[str, Any]:
    """The shape of a real account: persona baselines (as the reports compute them) and step and screen levels."""
    base = get_persona(CONFIG["behaviour"])
    cal: Dict[str, Any] = {"persona": base, "hrv_key": "hrv_rmssd_ms", "steps": None, "screen": {}, "nights": 0}
    if not user_id:
        return cal
    store = AdminStore(user_id)
    real = load_dataset(store, today, days=CONFIG["days"])
    p = real.persona
    cal["nights"] = sum(1 for n in real.nights if n.worn)
    rows = store.rows("sleep_nights", "night_date", (today - timedelta(days=CONFIG["days"])).isoformat(), today.isoformat())
    if sum(r.get("hrv_sdnn_ms") is not None for r in rows) > sum(r.get("hrv_rmssd_ms") is not None for r in rows):
        cal["hrv_key"] = "hrv_sdnn_ms"
    cal["persona"] = p
    cal["steps"] = _med([a.steps for a in real.activity if a.steps >= 100], None)
    for k in ("minutes", "late_minutes", "pickups"):
        for weekend in (False, True):
            vals = [m.get("screen." + k) for d, m in real.day_metrics.items() if (d.weekday() >= 5) == weekend]
            cal["screen"][(k, weekend)] = _med(vals, None)
    return cal


def persona_for(cal: Dict[str, Any]) -> Persona:
    """The calibrated baselines with the week and sensitivities of the simulator persona in CONFIG["behaviour"]."""
    p, base = cal["persona"], get_persona(CONFIG["behaviour"])
    return Persona(key="demo", name=CONFIG["name"], tagline="Demo account", description="Generated demo data.",
                   tz=CONFIG["time_zone"], resting_hr=p.resting_hr, hrv_ms=p.hrv_ms, resp_rate=p.resp_rate,
                   sleep_need_min=p.sleep_need_min, usual_bedtime=p.usual_bedtime, usual_wake=p.usual_wake,
                   weekend_shift_min=base.weekend_shift_min, behaviour=base.behaviour,
                   sensitivities=dict(base.sensitivities, **CONFIG["sensitivities"]))


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
def _slug(text: str) -> str:
    return "-".join("".join(ch if ch.isalnum() else " " for ch in text.lower()).split())


def student_week(start: date, end: date, rng: random.Random) -> List[CalendarEvent]:
    """CONFIG's week, study blocks, workouts, socials and one-offs for every day of ``start..end``."""
    zone = CONFIG["time_zone"]
    events: List[CalendarEvent] = []

    def add(d: date, title: str, s: float, e: float, kind: str, place: Optional[str], guests: int = 0,
            series: bool = False) -> None:
        events.append(CalendarEvent(id="%s-%s-%d" % (_slug(title), d.isoformat(), len(events)), title=title,
                                    start=at(d, s, tzname=zone), end=at(d, e, tzname=zone), type=kind,
                                    location_hint=place, attendees=guests,
                                    recurring_key=("series-" + _slug(title)) if series else None))

    def free(d: date, s: float, e: float) -> bool:
        a, b = at(d, s, tzname=zone), at(d, e, tzname=zone)
        return not any(ev.start < b and ev.end > a for ev in events if ev.start.date() == d)

    d = start
    while d <= end:
        dow = d.weekday()
        for title, slots, kind, place, guests, _ in CONFIG["week"]:
            for wd, s, e in slots:
                if wd == dow:
                    add(d, title, s, e, kind, place, guests, series=True)
        for title, place, slots in CONFIG["workouts"]:
            for wd, s, e, share in slots:
                if wd == dow and rng.random() < share:
                    late = title == "Gym" and rng.random() < CONFIG["late_gym"]
                    if free(d, 20.0 if late else s, 21.0 if late else e):
                        add(d, title, 20.0 if late else s, 21.0 if late else e, "workout", place)
        for title, wd, s, e, share in CONFIG["socials"]:
            if wd == dow and rng.random() < share and free(d, s, e):
                add(d, title, s, e, "social", None, rng.randint(2, 6))
        for title, wd, s, e, share, kind, place, guests in CONFIG["one_offs"]:
            if wd == dow and rng.random() < share and free(d, s, e):
                add(d, title, s, e, kind, place, guests)
        st = CONFIG["study"]
        if rng.random() < st["share"]["weekday" if dow < 5 else ("sat" if dow == 5 else "sun")]:
            for s, e in st["slots"]["weekday" if dow < 5 else "weekend"]:
                if free(d, s, e):
                    add(d, st["title"], s, e, "focus", st["place"])
                    break
        d += timedelta(days=1)
    return sorted(events, key=lambda ev: ev.start)


def class_effect(events: List[CalendarEvent], d: date) -> Optional[Tuple[Dict[str, float], datetime]]:
    """The class effect of day ``d`` and when the class started, if a class with an effect was that day."""
    by_title = {w[0]: w[5] for w in CONFIG["week"]}
    for ev in events:
        if ev.start.date() == d and by_title.get(ev.title):
            return CONFIG["class_effects"][by_title[ev.title]], ev.start
    return None


def plan_days(start: date, end: date, rng: random.Random) -> Dict[date, Dict[str, Any]]:
    """What happens each day besides the calendar, decided before the body is simulated."""
    plan = {}
    d = start
    while d <= end:
        weekend = d.weekday() >= 4                       # Fri and Sat evenings
        netflix = rng.random() < CONFIG["netflix_days"] * (1.3 if weekend else 1.0)
        late_tv = netflix and rng.random() < CONFIG["netflix_late"]
        plan[d] = {"netflix": netflix, "late_tv": late_tv,
                   "late_phone": not late_tv and rng.random() < CONFIG["late_screen"],
                   "coffee_heavy": d.weekday() < 5 and rng.random() < CONFIG["coffee_heavy"],
                   "artists": [a for a, share, _ in CONFIG["artists"] if rng.random() < share],
                   "tail": [rng.choice(CONFIG["tail"])] if rng.random() < 0.6 else [],
                   "podcast": rng.random() < CONFIG["podcast"][1],
                   "logged": rng.random() < CONFIG["checkin_logged"]}
        d += timedelta(days=1)
    return plan


def generate(cal: Dict[str, Any], today: date) -> Dict[str, Any]:
    rng = random.Random("seed-demo-%d" % CONFIG["seed"])
    days = CONFIG["days"]
    start = today - timedelta(days=days)
    plan = plan_days(start, today + timedelta(days=7), rng)

    events = student_week(start, today + timedelta(days=7), random.Random("seed-demo-week-%d" % CONFIG["seed"]))

    def calendar(persona, cal_start, cal_end, cal_today, cal_rng):
        day_kind = {ev.start.date(): "office" for ev in events if ev.recurring_key}
        return [ev for ev in events if cal_start <= ev.start.date() <= cal_end], [], day_kind

    def hook(d: date, f: DayFeatures, hidden: Dict[str, Any]) -> None:
        p = plan[d]
        eff = class_effect(events, d)
        if eff:
            hidden["extra_onset_min"] = eff[0]["onset_min"]
        hidden["screens_late"] = p["late_tv"] or p["late_phone"]
        if hidden["screens_late"]:
            hidden["extra_bed_delay_min"] = rng.uniform(*CONFIG["late_screen_delay"])
        hidden["caffeine_late"] = p["coffee_heavy"]

    ds = generate_dataset("demo", seed=CONFIG["seed"], days=days, anchor=today, showcase=False,
                          persona=persona_for(cal), hidden_hook=hook, calendar=calendar)
    z = tz(CONFIG["time_zone"])
    media: List[Dict[str, Any]] = []
    metrics: List[Dict[str, Any]] = []
    unlocks: List[Dict[str, Any]] = []
    urng = random.Random("seed-demo-unlocks-%d" % CONFIG["seed"])
    alcohol = {tn.date: int(tn.hidden.get("alcohol_units") or 0) for tn in ds.truth.nights}

    def play(provider: str, end_at: datetime, title: str, creator: Optional[str], minutes: float, kind: str) -> None:
        media.append({"id": "%s-%s-%d" % (SEED, provider, len(media)), "provider": provider,
                      "occurred_at": end_at.astimezone(timezone.utc).isoformat(), "title": title, "creator": creator,
                      "minutes": round(minutes, 2), "source": {"media_kind": kind, "seed": True}})

    # steps around the calibrated level, more on run days (the simulator ties steps to office days, and so to stress)
    for a in ds.activity:
        runs = sum(1 for w in a.workouts if w.kind == "run")
        a.steps = int((cal["steps"] or 7000) * rng.lognormvariate(0, 0.3) * (0.85 if a.date.weekday() >= 5 else 1.0)
                      + runs * CONFIG["run_steps"])
    focus_name, genre, focus_share = CONFIG["focus_artist"]
    for d in sorted(p for p in plan if start <= p < today):
        p = plan[d]
        weekend = d.weekday() >= 5
        h = ds.hr(d)
        study = [ev for ev in events if ev.start.date() == d and ev.type == "focus"]
        focus_day = bool(study) and rng.random() < focus_share
        # music: blocks through the day, a track every ~3.5 minutes, never during study blocks
        clock = datetime.combine(d, time(10 if weekend else 7, 40), z)
        blocks = [a for a in CONFIG["artists"] if a[0] in p["artists"]] + [(a, 0, CONFIG["tail_minutes"]) for a in p["tail"]]
        for artist, _, (lo, hi) in blocks:
            left = rng.uniform(lo, hi)
            for ev in study:
                if ev.start - timedelta(minutes=hi) < clock < ev.end:
                    clock = ev.end
            while left > 0:
                m = min(left, rng.uniform(2.8, 4.5))
                clock += timedelta(minutes=m)
                play("spotify", clock, "%s track %d" % (artist, rng.randint(1, 12)), artist, m, "music")
                left -= m
            clock += timedelta(minutes=rng.uniform(60, 240))
        # study music: the focus artist through the study block, a calmer heart rate while studying
        if focus_day:
            ev = study[0]
            t, until = ev.start + timedelta(minutes=rng.uniform(0, 10)), ev.end - timedelta(minutes=rng.uniform(0, 15))
            while t < until:
                m = rng.uniform(3.0, 6.5)
                t += timedelta(minutes=m)
                play("spotify", t, "%s track %d" % (focus_name, rng.randint(1, 15)), focus_name, m, "music")
                media[-1]["source"]["genre"] = genre
            if h is not None:
                s0 = ev.start.hour * 60 + ev.start.minute
                for m in range(s0, min(1440, s0 + ev.duration_min)):
                    if h.bpm[m] is not None:
                        h.bpm[m] += CONFIG["focus_effects"]["hr"]
        # class days: daytime heart rate from the class to 22:00, and that night's HRV and resting heart rate
        eff = class_effect(events, d)
        if eff and h is not None:
            s0 = eff[1].hour * 60 + eff[1].minute
            h.bpm = [b if b is None or not (s0 <= m < 22 * 60) else b + eff[0]["day_hr"] for m, b in enumerate(h.bpm)]
        n = ds.night(d)
        if eff and n is not None and n.worn and n.hrv_ms is not None:
            n.hrv_ms = round(n.hrv_ms * (1 + eff[0]["hrv"]), 1)
            n.resting_hr = n.resting_hr + eff[0]["resting_hr"] if n.resting_hr is not None else None
        if p["podcast"]:
            name, _, (lo, hi) = CONFIG["podcast"]
            play("spotify", datetime.combine(d, time(17, 30), z) + timedelta(minutes=rng.uniform(0, 40)),
                 "%s, episode %d" % (name, rng.randint(1, 60)), name, rng.uniform(lo, hi), "podcast")
        if p["netflix"]:
            show = rng.choice(CONFIG["shows"])
            t = datetime.combine(d, time(21, 50) if p["late_tv"] else time(19, 30), z) + timedelta(minutes=rng.uniform(0, 30))
            for ep in range(rng.randint(2, 3) if p["late_tv"] else rng.randint(1, 2)):
                t += timedelta(minutes=48)
                play("netflix", t, "%s: Episode %d" % (show, rng.randint(1, 9)), None, 48, "video")
        # Metallica days: daytime heart rate up (minutes 08-22, worn minutes only)
        if h is not None and CONFIG["hr_artist"] in p["artists"]:
            h.bpm = [b if b is None or not (8 * 60 <= m < 22 * 60) else b + CONFIG["hr_artist_bpm"]
                     for m, b in enumerate(h.bpm)]
        # screen time around the calibrated levels; late minutes high on late-phone evenings
        sc = lambda k, default: cal["screen"].get((k, weekend)) or default  # noqa: E731
        late = sc("late_minutes", 25.0) * (rng.uniform(2.5, 4.0) if p["late_phone"] else rng.uniform(0.3, 1.1))
        fe = CONFIG["focus_effects"]
        minutes = sc("minutes", 210.0) * rng.lognormvariate(0, 0.25) + late * 0.5 + (fe["screen_minutes"] if focus_day else 0)
        # unlocks spread over the waking day; a focus block keeps only fe["pickups"] of those inside it, and the
        # day's total is what is left, as the phone sync counts it (their own rng, so the other draws stay as they were)
        lo, hi = CONFIG["waking"]["weekend" if weekend else "weekday"]
        times = sorted(datetime.combine(d, time(0, 0), z) + timedelta(hours=urng.uniform(lo, hi))
                       for _ in range(int(round(sc("pickups", 70.0) * rng.lognormvariate(0, 0.2)))))
        if focus_day:
            times = [t for t in times if not (study[0].start <= t < study[0].end) or urng.random() < fe["pickups"]]
        for t in times:
            unlocks.append(screen_event(d, t, len(unlocks)))
        for k, v in (("minutes", minutes), ("late_minutes", late), ("pickups", len(times))):
            metrics.append({"day": d.isoformat(), "metric_key": "screen." + k, "value": round(v, 1), "source": SCREEN})
        if p["logged"]:
            cups = rng.choice([4, 5]) if p["coffee_heavy"] else rng.choice([1, 2, 2, 3])
            metrics.append({"day": d.isoformat(), "metric_key": "intake.coffee_cups", "value": cups, "source": "manual"})
            metrics.append({"day": d.isoformat(), "metric_key": "intake.alcohol_units", "value": alcohol.get(d, 0),
                            "source": "manual"})
    ds.reindex()
    return {"ds": ds, "media": media, "metrics": metrics, "unlocks": unlocks}


def screen_event(d: date, t: datetime, i: int) -> Dict[str, Any]:
    """One unlock as the phone sync stores it (source_records, every row with the same keys)."""
    return {"source": SCREEN, "data_type": "screen_event", "source_record_id": "%s-unlock-%s-%d" % (SEED, d.isoformat(), i),
            "data_origin": None, "start_at": _iso(t), "end_at": None, "start_offset_min": _offset(d), "end_offset_min": None,
            "value": None, "unit": None, "payload": {"type": "unlock"}, "source_modified_at": None}


# --------------------------------------------------------------------------- #
# Rows
# --------------------------------------------------------------------------- #
def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def _offset(d: date) -> int:
    return int(at(d, 12.0, tzname=CONFIG["time_zone"]).utcoffset().total_seconds() // 60)


def to_rows(gen: Dict[str, Any], hrv_key: str) -> Dict[str, List[Dict[str, Any]]]:
    ds: Dataset = gen["ds"]
    nights = []
    for n in ds.nights:
        if not (n.worn and n.score is not None):
            continue
        nights.append({"night_date": n.date.isoformat(), "source": HEALTH, "data_origin": SEED, "utc_offset_min": _offset(n.date),
                       "in_bed_at": _iso(n.in_bed_start), "onset_at": _iso(n.sleep_onset), "wake_at": _iso(n.wake_time),
                       "out_of_bed_at": _iso(n.out_of_bed), "asleep_min": n.duration_min, "deep_min": n.deep_min,
                       "rem_min": n.rem_min, "core_min": n.core_min, "awake_min": n.awake_min,
                       "interruptions": n.interruptions, "has_stages": bool(n.stages),
                       "stages": [{"kind": s.kind, "start": _iso(s.start), "end": _iso(s.end)} for s in n.stages],
                       hrv_key: n.hrv_ms, "resting_hr": n.resting_hr, "resp_rate": n.resp_rate, "spo2": n.spo2,
                       "skin_temp_dev": n.wrist_temp_dev, "score": n.score, "score_parts": n.score_parts,
                       "score_source": "stressless"})
    hr = [{"day": h.date.isoformat(), "source": HEALTH, "data_origin": SEED, "utc_offset_min": _offset(h.date),
           "bpm": (h.bpm + [None] * 1440)[:1440], "worn_minutes": sum(b is not None for b in h.bpm)}
          for h in ds.hr_days if h.date < ds.today and any(b is not None for b in h.bpm)]
    activity = [{"day": a.date.isoformat(), "source": HEALTH, "utc_offset_min": _offset(a.date), "steps": a.steps,
                 "active_min": a.active_minutes, "hourly_steps": a.hourly_steps if len(a.hourly_steps) == 24 else [],
                 "workouts": [{"kind": w.kind, "start": _iso(w.start), "end": _iso(w.end), "avg_hr": w.avg_hr,
                               "max_hr": w.max_hr, "calories": w.calories, "data_origin": SEED} for w in a.workouts]}
                for a in ds.activity]
    events = [{"provider": "manual", "provider_event_id": "%s-%s" % (SEED, e.id), "title": e.title,
               "category": CONFIG["stored_as"].get(e.title, e.type),
               "starts_at": _iso(e.start), "ends_at": _iso(e.end), "location": e.location_hint,
               "guests": [{"response_status": "accepted"}] * max(0, e.attendees - 1), "recurring_key": e.recurring_key}
              for e in ds.events]
    return {"sleep_nights": nights, "heart_rate_days": hr, "daily_activity": activity, "daily_metrics": gen["metrics"],
            "calendar_events": events, "media_events": gen["media"], "source_records": gen["unlocks"]}


# --------------------------------------------------------------------------- #
# Check against the answer key
# --------------------------------------------------------------------------- #
def check(rows: Dict[str, List[Dict[str, Any]]], today: date) -> Dict[str, Any]:
    """Load the rows the way the app does and run the links engine on them."""
    store = MemoryStore()
    store.tz = CONFIG["time_zone"]
    store.tables = {k: [dict(r, id=r.get("provider_event_id") or r.get("source_record_id") or r.get("id") or str(i))
                        for i, r in enumerate(v)]
                    for k, v in rows.items()}
    ds = load_dataset(store, today)
    found = {p.key: p for p in lifestyle_patterns(ds, today) if p.reportable}
    result = {"planted": {}, "unplanted": {}, "derived": {}}
    for key, want in PLANTED.items():
        p = found.get(key)
        got = {"direction": p.direction, "tier": p.primary.tier, "outcomes": [o.key for o in p.reportable]} if p else None
        if want["strength"] == "none":
            ok = p is None or p.primary.tier != "strong"
        elif want["strength"] == "weak":
            ok = p is None or p.direction == want["direction"]
        else:
            ok = p is not None and p.direction == want["direction"] and p.primary.tier == "strong"
        result["planted"][key] = dict(want, found=got, ok=ok)
    for key, p in found.items():
        if key not in PLANTED:
            result["derived" if p.cause_def.source == "sleep" else "unplanted"][key] = {"direction": p.direction, "tier": p.primary.tier,
                                        "outcomes": [o.key for o in p.reportable]}
    return result


def print_summary(cal: Dict[str, Any], rows: Dict[str, List[Dict[str, Any]]], result: Dict[str, Any]) -> None:
    p = cal["persona"]
    print("Calibrated from %d real nights: bedtime %.2f h, wake %.2f h, need %d min, resting HR %d, HRV %.0f ms (%s), "
          "steps %s" % (cal["nights"], p.usual_bedtime, p.usual_wake, p.sleep_need_min, p.resting_hr, p.hrv_ms,
                        cal["hrv_key"], "%.0f" % cal["steps"] if cal["steps"] else "simulator default"))
    print("\nRows: " + ", ".join("%s %d" % (k, len(v)) for k, v in rows.items()))
    print("\nPlanted links (engine looks at the last 56 days):")
    for key, r in result["planted"].items():
        got = r["found"]
        seen = "%s, %s via %s" % (got["direction"], got["tier"], "/".join(got["outcomes"])) if got else "not reported"
        print("  %s %-18s want %-6s %-6s | %s" % ("OK  " if r["ok"] else "MISS", key, r["direction"], r["strength"], seen))
    for title, part in (("Found but not planted (false links):", "unplanted"), ("Sleep to sleep (not planted):", "derived")):
        print("\n" + title)
        for key, got in result[part].items() or [("(none)", None)]:
            print("  %-22s %s" % (key, "%s, %s via %s" % (got["direction"], got["tier"], "/".join(got["outcomes"])) if got else ""))


def sweep(cal: Dict[str, Any], today: date, n: int) -> None:
    """The seeds where most planted links are found and fewest false ones, best first."""
    ranked = []
    for seed in range(1, n + 1):
        CONFIG["seed"] = seed
        result = check(to_rows(generate(cal, today), cal["hrv_key"]), today)
        misses = [k for k, r in result["planted"].items() if not r["ok"]]
        ranked.append((len(misses), len(result["unplanted"]), seed, misses, sorted(result["unplanted"])))
    print("seed  missed  false links")
    for n_miss, n_false, seed, misses, false in sorted(ranked)[:8]:
        print("%4d  %-40s %d: %s" % (seed, ", ".join(misses) or "-", n_false, ", ".join(false)))


# --------------------------------------------------------------------------- #
# Write / remove
# --------------------------------------------------------------------------- #
TABLES = ("sleep_nights", "heart_rate_days", "daily_activity", "daily_metrics", "calendar_events", "media_events",
          "source_records")
CONFLICT = {"sleep_nights": "user_id,night_date", "heart_rate_days": "user_id,day", "daily_activity": "user_id,day",
            "daily_metrics": "user_id,day,metric_key", "calendar_events": "user_id,provider,provider_event_id",
            "media_events": "user_id,id", "source_records": "user_id,source,source_record_id"}


def guard(user_id: str) -> None:
    """Refuse to touch an account that has data this script did not write."""
    uid = {"user_id": "eq." + user_id}
    db("GET", "admin/users/" + user_id, api="auth/v1")   # exits on 404: sign the demo account up in the app first
    checks = [("provider_connections", "provider_account_id", "not.like.%s*" % SEED),
              ("sleep_nights", "data_origin", "not.eq." + SEED),
              ("calendar_events", "provider_event_id", "not.like.%s*" % SEED),
              ("media_events", "id", "not.like.%s*" % SEED),
              ("source_records", "source_record_id", "not.like.%s*" % SEED)]
    for table, col, cond in checks:
        rows = db("GET", table, params=dict(uid, select=col, limit="1", **{col: cond})) or []
        if rows:
            raise SystemExit("Refusing: %s has %s rows not written by this script. Is this a real account?" % (user_id, table))


def remove(user_id: str) -> None:
    for table in TABLES + ("connection_streams", "provider_connections"):
        db("DELETE", table, params={"user_id": "eq." + user_id})
    print("Removed the demo data of %s." % user_id)


def write(user_id: str, rows: Dict[str, List[Dict[str, Any]]], today: date) -> None:
    remove(user_id)
    now = datetime.now(timezone.utc).isoformat()
    # the app creates the profile at the consent step, so a fresh account has none yet
    db("POST", "profiles", params={"on_conflict": "user_id"},
       json_body={"user_id": user_id, "time_zone": CONFIG["time_zone"], "consented_at": now},
       prefer="resolution=merge-duplicates,return=minimal")
    for table in TABLES:
        batch = [dict(r, user_id=user_id) for r in rows[table]]
        for i in range(0, len(batch), 200):
            db("POST", table, params={"on_conflict": CONFLICT[table]}, json_body=batch[i:i + 200],
               prefer="resolution=merge-duplicates,return=minimal")
    # the phone connections the readiness dialog reads (no Google Calendar: it would need real tokens)
    last = max(r["wake_at"] for r in rows["sleep_nights"])
    first = min(r["in_bed_at"] for r in rows["sleep_nights"])
    for source, types in ((HEALTH, ("sleep_session", "heart_rate", "steps", "exercise")), (SCREEN, ("app_usage",))):
        conn = db("POST", "provider_connections", params={"on_conflict": "user_id,provider,provider_account_id"},
                  json_body={"user_id": user_id, "provider": source, "provider_account_id": SEED, "status": "connected",
                             "platform": "android", "device_label": "Demo phone", "time_zone": CONFIG["time_zone"],
                             "connected_at": first, "last_synced_at": now},
                  prefer="resolution=merge-duplicates,return=representation")[0]
        db("POST", "connection_streams", params={"on_conflict": "connection_id,data_type"},
           json_body=[{"connection_id": conn["id"], "user_id": user_id, "data_type": t, "data_from": first,
                       "data_until": last, "last_synced_at": now, "updated_at": now} for t in types],
           prefer="resolution=merge-duplicates,return=minimal")
    print("Wrote the demo data for %s. Stored reports are kept: regenerate them on a dev server." % user_id)
    print("To keep this data current, run the server with STRESSLESS_ANCHOR=%s (freezes today for every user)."
          % today.isoformat())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user", help="the demo account's user id (required for --write and --remove)")
    ap.add_argument("--calibrate", help="a real account's user id to copy the shape from (read only)")
    ap.add_argument("--date", help="today (default: today)")
    ap.add_argument("--key", help="write the answer key and what the engine found to this JSON file")
    ap.add_argument("--seed", type=int, help="override CONFIG['seed']")
    ap.add_argument("--sweep", type=int, metavar="N", help="try seeds 1..N and rank them (nothing is written)")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--write", action="store_true", help="replace the demo account's data")
    group.add_argument("--remove", action="store_true", help="delete the demo account's data")
    args = ap.parse_args()
    if (args.write or args.remove) and not args.user:
        ap.error("--write and --remove need --user")
    if args.user and args.user == args.calibrate:
        ap.error("--user and --calibrate must be different accounts")

    if args.remove:
        guard(args.user)
        remove(args.user)
        return
    today = date.fromisoformat(args.date) if args.date else date.today()
    cal = calibrate(args.calibrate, today)
    if args.sweep:
        sweep(cal, today, args.sweep)
        return
    if args.seed is not None:
        CONFIG["seed"] = args.seed
    rows = to_rows(generate(cal, today), cal["hrv_key"])
    result = check(rows, today)
    print_summary(cal, rows, result)
    if args.key:
        with open(args.key, "w", encoding="utf-8") as fh:
            json.dump(dict(result, config={k: v for k, v in CONFIG.items()}, date=today.isoformat()), fh, indent=2, default=str)
    if args.write:
        guard(args.user)
        write(args.user, rows, today)
    else:
        print("\nDry run: nothing written (add --write).")


if __name__ == "__main__":
    main()
