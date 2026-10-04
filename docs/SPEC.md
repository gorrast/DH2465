# StressLess — Demo Specification (v2, post-critique)

> "Wearables give you a score. They don't tell you why."
> StressLess connects Google Calendar and Google Maps to the biometric data an Apple Watch
> already collects and explains what in your day shaped your body and your sleep.


> **Implementation notes (2026-09-27).** The build follows this spec with these deliberate deviations:
> the sleep-score consistency penalty is asymmetric (an earlier bedtime costs less than a later one, §5.4);
> the hero night uses fixed modest noise draws so the story lands on any seed (§5.6); the frontend mock
> fixtures (§9.1) were not shipped — views are verified against the live server by `tools/screenshot.py`
> (Python, replacing `tools/screenshot.sh`); the persona menu and history pill live in `core.js`.
> The test suite is `tests/test_*.py` (59 tests, ~12 s).

This document is the single source of truth for the demo build. Every module, API route, view and
test is defined here. Implementers: build exactly what is specified; where the spec is silent,
choose the simplest thing that keeps the demo honest and robust. v2 incorporates a three-lens
review (presenter, data science, engineering); the review's reasoning is folded into the rules
below, so follow them even where they look fussy.

---

## 0. Purpose and hard constraints

**Purpose.** A self-contained demo of the StressLess product that runs on the presenter's Mac with
one command and shows *exactly how the product works*, end to end, without an Apple Watch. A
**digital twin** (simulated person with calendar, location history and watch biometrics driven by a
known causal model) replaces the real sensors. Everything downstream — the explanation engine, the
morning report, reality checks, habits, planner — is the real product logic and works unchanged on
imported real data.

**Hard constraints**
1. **Python 3.9 standard library only** (`/usr/bin/python3` on macOS). No pip installs. `zoneinfo`,
   `sqlite3`, `http.server`, `json`, `statistics`, `random`, `xml.etree`, `dataclasses`, `typing`
   are available. **No** `match`, **no** `X | Y` unions at runtime, **no** `list[int]` at runtime
   (use `typing.List` / `from __future__ import annotations`), no `datetime.UTC`.
2. **Frontend: vanilla HTML/CSS/JS, no build step, no CDN, fully offline.** Hand-drawn SVG charts.
3. **One command**: `python3 run.py` generates data (first run), starts a server on `127.0.0.1`,
   opens the browser. Works with no network.
4. **Deterministic**: same persona + seed + anchor date -> identical dataset and explanations. All
   randomness via seeded `random.Random`. **No engine code calls `today_local()`** — use `ds.today`.
5. **Honest**: every number the UI shows is computed by the engine from the data. Simulator ground
   truth appears only in the Lab view, clearly labelled. Confidence, sample size, out-of-sample fit
   and "correlation, not proof" are part of the product.
6. **Optional AI narrative**: with `STRESSLESS_REASONER=claude`, an importable `anthropic` package
   and resolvable credentials, Claude writes the narrative; otherwise a rule-based reasoner does.
   The demo must be complete without it.
7. **Privacy by default**: localhost only; data in `./data/`; "Delete all data"; the Data view lists
   exactly which data classes are used.
8. **JSON safety**: the server serializes with `json.dumps(to_jsonable(obj), ensure_ascii=False,
   allow_nan=False)`. Every float producer must emit `None` instead of NaN/±inf (use a local
   `_finite(x)` helper). Views render `null` as "–".
9. **No module-level caches** anywhere in `stressless/engine` (no `lru_cache` on functions taking a
   Dataset). Caches live on the `Engine` instance and are passed down explicitly.

---

## 1. Product overview

### 1.1 The pitch in one screen
Morning report: what the watch says (a number, nothing else) -> **Why?** -> three likely causes
with evidence -> one suggestion you can put straight into the calendar. Weekly insight: average
sleep score by meeting load, strongest pattern. Reality checks: "Did you make it to the gym?" when
calendar, location and body disagree. No logging. The watch measures, the calendar explains.

### 1.2 What makes this demo 10/10 (all in scope)
| # | Feature | Why |
|---|---------|-----|
| 1 | **Digital twin with planted causes** — 10 weeks of calendar + Maps + watch data from a known causal model, per persona; **showcase guarantees** make the opening night always tell the story | The Lab checks the engine against planted truth; the presenter never opens on a boring night |
| 2 | **Watch card + Reveal** — Morning opens like a wearable app ("Score 68 · 6 h 12 min · that's all you get"), then `Why?` staggers in the causes | Lands the pitch in five seconds |
| 3 | **Day replay** — 24 h timeline with events, location band, heart rate vs *your evening norm*, sleep; Play from the evening at 16x/64x with a live watch face | The body riding the meetings, visibly above the norm line |
| 4 | **Reality-check inbox** — booked-but-not-seen and seen-but-not-booked detections with evidence chips; answers show a before/after effect and add blocks to Replay | "No logging, only confirmations" made concrete |
| 5 | **What-if planner** — end a meeting at 18:00, watch the predicted delta with a likely range; **Add to calendar** writes the protected block; explicit .ics download | The suggestion loop closes on screen |
| 6 | **Presenter tour** — 10 keyboard-driven steps in pitch order, ending on the product promise | No hunting for the next click |
| 7 | **Three personas in the top bar** — Alex, Sam, Robin, pre-generated in the background so switching takes < 1 s; each has a visibly different #1 cause | "Same engine, different person" |
| 8 | **Honesty layer** — n nights, LOO out-of-sample fit, block-bootstrap intervals, confidence badges, adaptive "unexplained" notes, hidden factors the calendar cannot see (alcohol, caffeine, screens, illness, sleep debt), missing nights that are *not* random | The deck's Open Challenges, answered |
| 9 | **Cold-start slider** — 7/14/28/all nights; intervals widen, badges drop, and a visible top-bar pill says so until reset | Cold start, shown not told |
| 10 | **Bring-your-own-data importers** — Apple Health `export.xml`, Google Calendar `.ics`, Google Takeout Semantic Location History | The path to the real product is code |
| 11 | **Optional Claude narrative** — opt-in, de-identified payload, reasoner badge | The "Reasoning AI" chip, done responsibly |
| 12 | **Terminal report, Markdown export, `--demo-check`** — pre-flight checklist before going on stage | Robustness |
| 13 | **Recovery markers** — HRV, resting HR, wrist temperature prominent; respiratory rate and SpO2 under "more" | The deck's "then recovery markers" |
| 14 | **Under the hood** — pipeline, model card with in-sample vs out-of-sample fit, planted-truth scatter (direct vs total), planted null factor, hold-out skill, reality-check accuracy, "why this is not circular" | Credibility for a sharp audience |

---

## 2. Runtime, repository layout, file ownership

```
run.py                                                            [server]
SPEC.md  README.md                                                [lead]
stressless/
  __init__.py timeutil.py models.py engine/features.py            [lead — DONE; read-only for others]
  sim/ personas.py calendar_gen.py location_gen.py physiology.py sleep_score.py generate.py   [sim]
  connectors/ base.py demo.py ics_calendar.py apple_health.py google_takeout.py build.py      [connectors]
  store/db.py                                                     [connectors]
  engine/ baselines.py matching.py reality.py                     [engine-core]
  engine/ attribution.py habits.py whatif.py                      [engine-model]
  engine/ suggestions.py reasoning.py pipeline.py                 [engine-app]
  server/ app.py api.py                                           [server]
web/
  index.html css/base.css js/core.js                              [lead — DONE]
  js/charts.js css/charts.css js/views/{morning,week,habits}.js css/views/{morning,week,habits}.css fixtures/fixtures-a.js   [frontend-a]
  js/views/{replay,reality,planner,data,lab}.js js/tour.js css/views/{replay,reality,planner,data,lab,tour}.css fixtures/fixtures-b.js   [frontend-b]
tests/
  helpers.py test_timeutil_models.py                              [lead — DONE]
  test_features.py                                                [engine-core]
  test_sim.py                                                     [sim]
  test_connectors.py test_store.py                                [connectors]
  test_baselines.py test_matching.py test_reality.py              [engine-core]
  test_attribution.py test_habits.py test_whatif.py               [engine-model]
  test_suggestions.py test_reasoning.py test_pipeline.py          [engine-app]
  test_api.py test_cli.py                                         [server]
  test_e2e.py test_fixtures_contract.py                           [integration]
tools/ screenshot.sh [server]   validate_palette.sh validate_palette.js [lead — DONE]
docs/screenshots/  data/  (generated)
```

**Ownership rule:** edit only files you own. Needed changes elsewhere go in your final report under
"Requested changes" with exact diffs. `models.py`, `timeutil.py`, `engine/features.py` are frozen; if
a field is missing, use a module-local dict and report it. **Every file listed in `index.html` must
exist** (create a stub with a header comment if a view has no CSS).

**Imports:** absolute (`from stressless.models import ...`). `stressless.sim` MAY import
`stressless.engine.features` (single feature vocabulary). `stressless.engine` must never import
`stressless.sim` (except `stressless.sim.sleep_score`) and must never read `Dataset.truth` — only
`attribution.validation()` does, and it is labelled as Lab-only.

---

## 3. Time model

* Persona zone `Europe/Stockholm`; all datetimes aware via `timeutil.tz()`. Durations are wall-clock
  differences between such datetimes (never fixed-offset tzinfo). The one-hour error on the DST
  night (25 Oct 2026) is accepted and listed in the Lab's known limitations.
* **Night N belongs to day D** when sleep starts on D's evening (or D+1 before 12:00):
  `timeutil.night_date(dt)`. `SleepNight.date` is D.
* **Morning report on date M explains night M-1**, using day M-1's calendar and biometrics.
* **Hour-of-day features are relative to the event's day**: `timeutil.day_hour(dt, day)` gives 24.5
  for 00:30 the next morning. `features.py` already does this. UI formats hours >= 24 mod 24
  (`SL.fmt.hourFloat`).
* **`is_weekend` for night D = `timeutil.is_weekend_night(D)`** (Fri and Sat nights). The simulator
  uses the same predicate for its weekend bedtime/wake shift.
* Dataset: nights `start..end`, `end = today - 1`, 70 nights by default (`--days`). **`hr_days`
  span `start..today` inclusive**; today's HeartRateDay is filled until `max(wake_time of night
  today-1, 09:00)` and `None` afterwards. Calendar events span `start .. today + 7`.
* `today = anchor or timeutil.today_local()`. The UI always uses `/api/meta.today`. On startup, if
  no `--anchor` and the stored dataset's `today != today_local()`, run.py regenerates with the stored
  persona/seed (clearing answers/accepted/narratives) and prints why. With `--anchor` the stored
  dataset wins and the persona chip shows "Demo date 27 Sep".
* Minute index: `HeartRateDay.bpm[i]` is minute `i` of the local day (always 1440 slots).

---

## 4. Data model and ids

`stressless/models.py` is final. Key types: `Persona`, `CalendarEvent`, `LocationVisit`,
`WatchWorkout`, `DailyActivity`, `HeartRateDay`, `SleepStage`, `SleepNight`, `SimTruthNight`,
`SimTruthEvent`, `SimTruth`, `DayFeatures` (+ `regressors()`), `Coefficient`, `ModelSummary`,
`Evidence`, `Cause`, `Suggestion`, `RecoveryMetric`, `MorningReport`, `RealityCheck`,
`HabitBucket`, `Habit`, `WhatIfResult`, `Dataset` (indexes: `events_on(d, include_unattended)`,
`event(id)`, `visits_on`, `visit(id)`, `hr`, `night`, `activity_on`, `night_dates`, `add_event`,
`set_attended`). Read the file.

Serialization: `models.to_jsonable(obj)` / `models.dumps(obj)`; decoding `models.from_dict(cls,
d)`, `models.dataset_from_dict(d)`. **All API responses are `to_jsonable` output**: JSON field names
= dataclass field names; datetimes `2026-09-26T20:30+02:00`; dates `YYYY-MM-DD`.

**Id schemes (mandatory, `models.new_id`)**: events `new_id("ev", persona_key, date, seq)` (seq =
0-based index within the day at generation, e.g. `ev-alex-2026-09-26-3`); visits `new_id("vis",
persona_key, date, seq)`; watch workouts `new_id("wk", date, seq)`; reality checks `rc-{event_id}`
/ `rc-{visit_id}`; detected events `new_id("ev", "detected", visit_id)`; suggestion events
`new_id("ev", "sg", morning, kind)`; what-if added events `new_id("ev", "whatif", date, i)`;
suggestions `sg-{morning}-{kind}`. Ids contain only `[A-Za-z0-9_:-]`. test_sim asserts uniqueness.

---

## 5. Simulator (`stressless/sim`) — the digital twin

### 5.1 Personas (`personas.py`)
`PERSONAS: Dict[str, Persona]` keys `alex` (default), `sam`, `robin`; `get_persona(key)`;
`PERSONA_ORDER = ["alex", "sam", "robin"]`.

| | alex | sam | robin |
|---|---|---|---|
| tagline | Product lead who lives by the calendar | Consultant: eight meetings and a flight | Founder: late nights and late workouts |
| office days | Mon–Thu, WFH Fri | client site Mon–Thu (travel Mon/Thu every 2nd week) | irregular, mostly office |
| meetings/day (weekday) | 3–7 | 5–9 | 1–5 |
| late meetings (end >= 19:00) | ~1.5/week | ~2/week | ~2/week (investor calls) |
| workouts | run Tue/Thu 07:00, gym Sat 10:00, occasional gym 20:00 | gym Mon/Wed/Fri 06:30 | gym Mon/Wed/Fri **20:45–21:45**, run Sun 10:00 |
| evening social | Thu after-work 50 %, Sat dinner 60 % | client dinner ~1/week + Fri 50 % | Fri/Sat 70 %, weekday 15 % |
| travel | Berlin day-trip every ~3 weeks (>= 5 in 70 days) | weekly (Mon out / Thu back), one London trip tz_shift=-1 | rare (>= 5 in 70 days incl. one Helsinki tz_shift=+1) |
| protected evenings in history | 6–8 "Wind down" blocks | 6–8 | 6–8 |
| resting HR / HRV / resp | 56 / 48 / 14.6 | 60 / 38 / 15.2 | 52 / 62 / 14.0 |
| sleep need (min) | 480 | 450 | 480 |
| usual bed / wake (weekday) | 23:05 / 06:45 | 23:15 / 06:15 | 00:15 / 07:45 |

**Design sensitivities** (nominal points per unit; `Persona.sensitivities`, keys = REGRESSOR_KEYS
minus is_weekend, plus hidden keys). Every key present for every persona (0 allowed = no mechanism):
```
REF   (alex) : meetings_over_3 -2.2 | b2b_over_2 0 (planted null) | late_meeting_hours -4 | evening_social -8 | workout_morning +5 | workout_late -3 | travel -9 | early_start -3 | protected_evening +4
sam          : -1.2 | -1.5 (only persona with a real b2b effect) | -3 | -5 | +3 | -2 | -12 | -5 | +3
robin        : -0.8 | 0 (planted null) | -2 | -6 | +2 | -9 | -6 | -2 | +6
hidden (all) : alcohol -4/unit-ish via mechanisms, caffeine_late -3, screens_late -2, illness -12, sleep_debt (state)
```
`ratio_k = persona.sensitivities[k] / REF_TABLE[k]` where `REF_TABLE = {meetings_over_3: -2.2,
b2b_over_2: -1.5, late_meeting_hours: -4, evening_social: -8, workout_morning: 5, workout_late: -3,
travel: -9, early_start: -3, protected_evening: 4}` (never zero). Ratio 0 removes the mechanism.

**`Persona.behaviour` schema** (read by the three generators, tests, and the Data view):
`office_days: List[int]`, `meetings_per_day: [lo, hi]`, `late_meetings_per_week: float`,
`b2b_prob: float`, `workouts: [{dow, hour, minutes, kind, place}]`, `late_gym_prob: float`,
`social: {dows: [..], prob: float, weekday_prob: float}`, `travel_every_days: int`,
`wfh_every_days: int`, `skip_prob: {workout: .12, social: .08, meeting: .03}`,
`showcase: {...}` (see 5.6).

### 5.2 Calendar generator (`calendar_gen.py`)
`generate_events(persona, start, end_cal, rng) -> Tuple[List[CalendarEvent], List[SimTruthEvent]]`
(`end_cal = today + 7`).
* Recurring events with `recurring_key` (`mon-standup` Mon 09:00–09:30, `weekly-1on1`, `thu-gym`,
  `sun-family-dinner`, …) plus one-off meetings with titles from a **fictional** title bank
  ("Roadmap review", "Board prep", "Customer call: Northwind", "Design crit", "Interview",
  "1:1 with Maria"), attendees 2–12, `location_hint` in `Office`, `Google Meet`, `Zoom`, `Room Björk`.
* Meeting intensity is implied by title keywords (`board|review|interview|pitch|customer|investor`).
* Back-to-back afternoons (persona `b2b_prob`): chains of 4–6 meetings 13:00–17:00, gaps <= 10 min.
* Late meetings end 19:00–20:45 ("Customer call: Pacific team", "Investor update").
* Workouts (`type="workout"`, hint gym name / "Djurgården loop"), social (`type="social"`: after-work,
  dinner, concert; end 20:30–00:30, hint restaurant/bar), travel (`type="travel"`: "Flight ARN->BER
  07:10", "Train to Göteborg"; `notes="tz_shift=+1"` when applicable), focus blocks, personal
  (dentist, school pickup), 6–8 `protected` "Wind down" blocks 21:00–22:00 spread over history.
* **Attendance truth**: `SimTruthEvent(attended, reason)` for every past event. Skip probabilities
  from `behaviour.skip_prob`; travel never skipped. One WFH day every `wfh_every_days`: Office
  meetings attended remotely (`attended=True`, `reason="wfh"`).
* `CalendarEvent.attended` stays `None` for all generated events. Never copy truth into it.

### 5.3 Location generator (`location_gen.py`)
`generate_visits(persona, events, truth_events, start, end, rng) -> Tuple[List[LocationVisit], List[str]]`
returns visits and the ids of *unbooked* visits.
* Home by default; office on office days 08:30–17:30 (±20 min) with `transit` 30–40 min each way;
  attended physical events move the person (gym; restaurant/bar; airport -> transit -> `away`
  (city name) -> hotel when overnight). Skipped events: the person stays home/office.
* WFH days: at home all day.
* **Unbooked activities**: 3–5 gym visits (>= 40 min) and 2–3 restaurant/bar visits (start >= 17:00)
  with no calendar event; return their ids. They get workout HR / social HR in physiology.
* Location gaps: 2–3 days with no visits at all (phone off).
* Coordinates: defaults are fine (no map is drawn); `place_name` realistic (fictional venues).

### 5.4 Physiology (`physiology.py`) — the causal model
`simulate_day(persona, d, features: DayFeatures, attended_events, visits, hidden, noise, state) ->
Tuple[HeartRateDay, DailyActivity, SleepNight, SimTruthNight]`

* `features = stressless.engine.features.day_features(None_or_partial_ds, d, events=attended)`
  computed by `generate.py` with a lightweight `Dataset` holding only the persona (so the bedtime-
  relative workout rule works). `reg = features.regressors()`; `SimTruthNight.regressors = reg`.
* `hidden` per day (drawn in generate.py): `alcohol_units` (social nights: 70 % have 2–4; other nights
  5 % have 1–2), `caffeine_late` (25 % of days with n_meetings >= 5), `screens_late` (30 %),
  `illness` (one 2–3 day episode, pinned per 5.6), plus `state["debt"]` (sleep debt, below).
* **`noise`** is a dict of pre-drawn draws for the day, one per noise site: `bed, onset, wake, awake,
  interrupt_u (U(0,1)), hrv_ln, rhr, resp, temp, spo2, life, jitter` — drawn once so counterfactual
  nights reuse identical draws (common random numbers). Poisson via inverse CDF on `interrupt_u`.

**Heart rate (1440 minutes):**
* Night: sleeping HR baseline = `night_rhr - 6` with a cosine U-shape (amplitude 3, nadir mid-sleep),
  sd 2 — the same `night_rhr` that goes on the RHR tile. Awake resting `resting_hr + 12`; 30-min
  morning rise.
* Walking bumps (+20–30, 10–20 min) at commute and 2–4 random daytime walks; lunch walk.
* Workouts (attended events and unbooked gym visits): ramp to 140–168 (run) / 115–145 (strength) /
  95–110 (yoga), recovery tau 20 min. Emit `WatchWorkout` for any HR > 120 sustained >= 20 min (the
  watch's own detection; it never reads the calendar).
* Meetings: arousal +4..+14 scaled by intensity (title keywords, attendees), decay tau 40 min; chains
  accumulate (cap +18). Late meetings: evening arousal **+5..+10** above the evening norm until
  `end + 60..120 min`.
* Social: +8..+12 during; alcohol adds `min(1.2*units, 5)` to night HR for the first half of the night.
* Illness days: +7 to all daytime and night minutes.
* AR(1) noise sd 2.5; int; clamp 38..195.
* Every minute has a sample except charging gaps and unworn nights (`None`). Matching must tolerate
  `None` everywhere (real imports are sparse).
* **Not worn**: charging gap 35–60 min on ~60 % of days (morning or evening). Fully unworn night
  probability 0.03, **0.15 on evening_social nights** (informative missingness) -> `SleepNight(worn=
  False, score=None)` and `None` HR 22:00–08:00. Never within the last 7 nights (5.6).

**Sleep — mechanistic, then scored.** With `late_h = reg[late_meeting_hours]`, `m3 =
reg[meetings_over_3]`, `b2b = reg[b2b_over_2]`, `soc`, `wl = workout_late`, `wm = workout_morning`,
`trv`, `es = early_start`, `prot`, each multiplied by its `ratio_k`; `alc = alcohol_units`;
`debt = state["debt"]` (minutes, 0..180):
```
usual_bed  = persona.usual_bedtime (+ 0.6*weekend_shift on weekend nights) + jitter N(0,20)
bed_delay  = 20*late_h + 50*soc + 30*wl + 20*trv - 15*prot + 25*screens - 0.10*debt + N(0,25)
bedtime    = max(usual_bed + bed_delay, last_attended_event_end + 30 min)
onset_lat  = 12 + 6*late_h + 10*wl + 3*m3 + 4*b2b + 5*caffeine - 3*wm - 4*prot - 0.02*debt + N(0,4)   (>= 3)
lambda     = 1.2 + 0.3*alc + 0.3*m3 + 0.5*trv + 0.8*illness - 0.3*wm - 0.3*prot                       (>= 0.2)
interrupt  = Poisson_invcdf(lambda, interrupt_u)
awake_min  = 8 + 10*interrupt - 4*wm - 0.03*debt + N(0,5)                                             (>= 0)
wake       = usual_wake (+ weekend_shift + 0.5*bed_delay capped +120 on weekend nights) - 45*es + N(0,10)
duration   = wake - (bedtime + onset_lat) - awake_min  (>= 180) ; life term: duration += N(0,12) ("life")
hrv        = hrv_base * (1 - 0.03*m3 - 0.05*late_h - min(0.30, 0.06*alc) - 0.07*wl + 0.05*wm - 0.10*trv - 0.20*illness) * LN(0, 0.18)
rhr        = rhr_base + 1.2*m3 + 1.8*late_h + min(1.2*alc, 5) + 2.5*wl - 1.5*wm + 3*trv + 7*illness + N(0,1.5)
resp       = resp_base + 0.7*(alc>0) + 1.5*illness + N(0,0.3)
temp_dev   = 0.25*(alc>0) + 0.5*illness + 0.15*trv + N(0,0.12)
spo2       = 97.5 - 0.4*(alc>0) - 0.3*illness + N(0,0.4)  (92..100)   # tile only, never evidence
deep share = 0.20*(1 - 0.05*(alc>0) - 0.15*wl); rem share = 0.22*(1 - min(0.35, 0.10*alc)); rest core
```
Stages: 4–5 cycles of 90 ± 15 min; deep fraction per cycle 0.35/0.25/0.12/0.05/0, REM 0.05/0.15/
0.25/0.35/0.40 (renormalised to the night's totals); interruptions inserted as `awake` segments at
cycle boundaries. **Sleep debt**: `state["debt"] = clip(sum over last 3 nights of (need - duration),
0, 180)` carried forward.

**Score** via `sleep_score.compute_score(params, recent_bedtimes) -> Tuple[int, Dict[str, int]]`.
`params` keys (all required): `duration_min`, `bedtime_min` (minutes after 12:00 of the night date;
23:15 -> 675, 00:20 -> 740), `interruptions`, `awake_min`, `sleep_need_min`. `recent_bedtimes` =
same unit for the previous <= 14 worn nights (empty -> consistency 30).
* duration (50): `50 * clamp(duration/need, 0, 1) ** 1.3`, minus 5 if duration > need + 120.
* consistency (30): `30 - 0.25 * max(0, |bedtime - median(recent)| - 20)` (floor 0).
* interruptions (20): `20 - 3*interruptions - awake_min/8` (floor 0).
Round, clamp 0..100; parts dict `{"duration", "consistency", "interruptions"}`.
`sleep_score.rating(score) -> str`: `Very low` 0–40, `Low` 41–60, `OK` 61–80, `High` 81–95,
`Very high` 96–100 (Apple-style bands; never call it Apple's score; `score_source="stressless"`).
Target distribution (asserted in test_sim for all personas, seed 7): median 76–86, sd 7–11; in-
sample R² of the engine's ridge on the truth regressors 0.35–0.75.

**Ground truth** (`SimTruthNight`): for each active calendar factor k (`reg[k] != 0`), recompute the
night with `reg[k] = 0` and the **same `noise` dict** -> `contributions[k] = score - score_without_k`.
Hidden factors likewise under `contributions["hidden:alcohol"]`, `hidden:caffeine`, `hidden:screens`,
`hidden:illness`, `hidden:sleep_debt`. `counterfactual_score` = all calendar factors removed.
`noise_points = score - counterfactual - sum(calendar contributions)` (interactions + noise; label it
so). Test: a night with exactly one active factor has `contributions[k] == score -
counterfactual_score`.

### 5.5 Orchestration (`generate.py`)
`generate_dataset(persona_key="alex", seed=7, days=70, anchor: Optional[date]=None, showcase=True)
-> Dataset`. `today = anchor or today_local()`, `end = today-1`, `start = end-(days-1)`. Order:
events -> showcase overrides (5.6) -> visits -> per-day physiology in date order (carrying `state`)
-> truth tables. **Realised truth**: `effect_table_direct[k] = sum contributions[k] / sum reg[k]`
over nights where reg[k] != 0; `effect_table[k] = direct[k] + sum_h (P(h | k active) - P(h | k
inactive)) * mean_effect(h)` (total, including correlated hidden factors, computed empirically from
the generated nights); `effect_table_design = persona.sensitivities`. `hidden_summary = {nights_with_
hidden, alcohol_nights, caffeine_days, illness_nights: [dates], unworn_nights: [dates],
unworn_social_nights: int, debt_mean}`. Must run < 5 s. `sim/__init__.py` exports
`generate_dataset`, `PERSONAS`, `PERSONA_ORDER`.

### 5.6 Showcase guarantees (`showcase=True`, all personas, any seed)
Applied as event/attendance overrides *before* physiology, using the same rng (determinism holds):
* (a) night `end` (last night) is worn with no charging gap 22:00–08:00; the last 7 nights are worn.
* (b) day `end` has the persona's **signature bad day**: alex — 6 meetings incl. a 4-chain 13:00–17:00
  and "Customer call: Pacific team" ending 20:15, no social; sam — flight home ("Flight LHR->ARN",
  tz_shift=-1) + client dinner ending 22:30; robin — "Investor update" 19:00–20:00 + gym 20:45–21:45.
  No illness, no unworn.
* (c) day `today` has a meeting ending >= 19:30 and no protected event; `today+1` has an event
  starting <= 07:30 (so `later_start` can fire).
* (d) within `end-6..end-1`: exactly one skipped booked gym (contradicted: at home, HR flat) and one
  unbooked gym visit >= 40 min with HR > 120 (and, for robin, one unbooked bar visit).
* (e) the illness episode is pinned to `end-12..end-10`; the fully-unworn nights never fall in the
  last 7; one unworn night is pinned at `end-10` (a social night).
* (f) every regressor has `n_active >= 5` in history (protected 6–8, travel >= 5, late workouts >= 5
  for alex via occasional 20:00 gym).
test_sim asserts (a)–(f) for all three personas at seeds 1..5. `run.py --demo-check` asserts the
*engine's* view of them (7.10).

---

## 6. Connectors and store

### 6.1 Connectors (`stressless/connectors`)
* `base.py`: ABCs `CalendarSource.events(start, end)`, `LocationSource.visits(start, end)`,
  `BiometricSource.hr_days/nights/activity(start, end)`; `classify_event(title, location_hint) ->
  type` (gym/run/yoga/pt/workout -> workout; dinner/drinks/afterwork/after-work/concert/party/bar/
  pub -> social; flight/train/airport/trip -> travel; focus/deep work/writing -> focus; wind down/no
  meetings/recovery/protected -> protected; dentist/doctor/pickup/pick-up -> personal; else meeting);
  `classify_place(name) -> place_type`; **`parse_ts(s, tzname) -> datetime`** tolerant of ISO with/
  without seconds, `Z`, `+01:00`, `+0100` (`strptime("%Y-%m-%d %H:%M:%S %z")`), epoch-ms strings,
  fractional seconds (trim to 6 digits). All importers use it.
* `demo.py`: `DemoSources(dataset)` implementing the three ABCs.
* `ics_calendar.py`: `parse_ics(text, tzname, start, end) -> List[CalendarEvent]`. Folded lines;
  `DTSTART;TZID=`, `...Z`; all-day (`VALUE=DATE`) skipped; `STATUS:CANCELLED` skipped; `DURATION`
  when DTEND missing; `SUMMARY`, `LOCATION`, `ATTENDEE` count; `RRULE` `FREQ=DAILY|WEEKLY` with
  `BYDAY` (ordinal prefixes like `1MO` -> plain weekday), `INTERVAL`, `COUNT`, `UNTIL` (UTC compared
  after converting the instance to UTC); comma-separated `EXDATE` with optional TZID; `RECURRENCE-ID`
  overrides replace the master instance for the same UID; unknown/Windows TZIDs -> `tzname` with a
  logged warning; unknown FREQ -> first instance; cap 400 instances/RRULE; within `[start, end]`;
  robust to junk. Ids `new_id("ev", "ics", uid_hash8, date)`.
* `apple_health.py`: `parse_export(path, tzname, start, end) -> Tuple[List[HeartRateDay],
  List[SleepNight], List[DailyActivity]]` via `iterparse(events=("start", "end"))`: keep the root from
  the first start event; on end of `Record`/`Workout` process then `el.clear()`; every 10 000 elements
  `root.clear()`. Skip records whose `startDate[:10]` (string compare) is outside `[start-1, end+1]`
  before parsing. Types: `HKQuantityTypeIdentifierHeartRate` (minute means),
  `HeartRateVariabilitySDNN` (median per night), `RestingHeartRate`, `RespiratoryRate`,
  `OxygenSaturation` (×100 if <= 1.0), `AppleSleepingWristTemperature` (deviation vs median of first
  14 nights), `StepCount` (daily; `hourly_steps` may be empty), `HKCategoryTypeIdentifierSleepAnalysis`
  values `…Asleep`, `…AsleepCore/Deep/REM/Unspecified`, `…Awake`, `…InBed` -> stages/night (when two
  sources overlap on a night keep the one whose `sourceName` contains "Watch"), `<Workout>` ->
  `WatchWorkout`. Score nights with `compute_score` when absent.
* `google_takeout.py`: `parse_timeline(path, tzname, start, end) -> List[LocationVisit]` for
  Semantic Location History monthly JSON (`timelineObjects[].placeVisit` -> visit;
  `activitySegment` -> `transit`; `latitudeE7/1e7`; `startTimestamp` or `startTimestampMs`) **and**
  the newer `Timeline.json` (`semanticSegments[].visit` with `topCandidate.placeLocation` /
  `semanticType`, `startTime`/`endTime`; `activity` segments -> `transit`). `path` may be a file or a
  directory (all `*.json` inside).
* `build.py`: `build_dataset(persona, events, visits, hr_days, nights, activity, today) -> Dataset
  (source="imported", truth=None, showcase=False)`; fills missing nights as `worn=False`.

### 6.2 Store (`stressless/store/db.py`)
`class Store(path)` over sqlite3 (`check_same_thread=False`, one connection, an `RLock` around every
call, commit after every write). Tables: `meta(key PK, value)`, `dataset(id=1, json)`,
`answers(check_id PK, answer, event_id, visit_id, ts)`, `user_events(id PK, json)`,
`accepted(suggestion_id PK, event_id, ts)`, `narratives(key PK, mode, text, ts)`.
Methods: `save_dataset(ds)` (stores `persona/seed/days/anchor/source` in meta; **if persona, seed or
anchor differ from the stored meta, first truncate answers/user_events/accepted/narratives**),
`load_dataset() -> Optional[Dataset]` (pristine), `apply_to(ds)` (mechanical: add each user_event
if its id is absent; for each answer with an `event_id`, `ds.set_attended(event_id, answer ==
"yes")`), `meta()/set_meta`, `save_answer(check_id, answer, event_id, visit_id)`, `answers() ->
Dict[str, Dict]` (`{check_id: {"answer", "ts", "event_id", "visit_id"}}`), `add_user_event(ev)`,
`user_events() -> List[CalendarEvent]`, `save_accepted(sid, event_id)`, `accepted() -> Dict[str,
str]`, `get_narrative(key)`, `set_narrative(key, mode, text)`, `clear_user_state()`, `clear()`,
`state_version() -> str` (sha1 of sorted answers, accepted, user_event ids; first 10 hex chars),
`path`. Dataset JSON blob < 10 MB is fine.

---

## 7. Engine (`stressless/engine`)

Preamble: the engine sees `Dataset` minus `truth`. Errors: `pipeline.py` defines
`class EngineError(Exception): status = 400` and `class NotFound(EngineError): status = 404`
(engine-core/model modules may raise `ValueError`; the Engine wraps them). No module-level caches;
functions that cache take `cache: Optional[dict] = None`. `history_days=N` means the N calendar
nights `upto-N .. upto-1`; `n_nights` counts worn ones among them; the same definition is used by
fit, habits, week and baselines so the cold-start control moves everything consistently.

### 7.1 `features.py` (lead — DONE)
Read it. `day_features(ds, d, events=None)`, `features_range`, `describe_features`,
`workout_slot_for`. Tests (engine-core, `test_features.py`): 07:00 run -> `early_start 0`; social
19:00–00:30 -> `evening_social 1`, `social_end_hour 24.5`; Friday -> `is_weekend 1`, Sunday -> 0;
robin gym 20:45–21:45 -> `late`; chain of 4 with 10-min gaps -> `max_b2b_run 4`; `tz_shift=+1` parsed;
protected by title.

### 7.2 `baselines.py` (engine-core)
* `robust_baseline(values) -> Tuple[Optional[float], Optional[float]]` = (median, max(1.4826*MAD,
  1e-6)); `(None, None)` if < 3 values. All `statistics` calls guarded for empty input.
* `night_metric(night, key) -> Optional[float]` for `score, hrv_ms, resting_hr, resp_rate,
  wrist_temp_dev, spo2, duration_min, interruptions, awake_min, bedtime_min (minutes after 12:00 of
  night.date for in_bed_start — identical to compute_score's unit), onset_min, wake_min`.
* `history(ds, upto, key, history_days=None) -> List[float]` over worn nights `< upto` within the
  window. `baseline_for(ds, upto, key, window=28, history_days=None) -> Dict{median, scale, n}`;
  `z(value, baseline) -> Optional[float]` (finite or None).
* `recovery_metrics(ds, night_date, window=28) -> List[RecoveryMetric]` in this order: `hrv_ms` (up
  good), `resting_hr` (down good), `wrist_temp_dev` (zero), `resp_rate` (zero), `spo2` (up). `status`:
  `good` if z in the good direction >= 0.8; `watch` if z in the bad direction <= -1.0 (|z| >= 1.5 for
  zero-direction); else `typical`; `unknown` when no value. `series` = last 14 nights.
* `hour_label` from timeutil for text.

### 7.3 `matching.py` (engine-core)
All rolling statistics ignore `None`.
* `hr_slice(ds, start, end) -> List[Optional[int]]` across day boundaries.
* `hr_norm_curve(ds, upto, window_days=21, cache=None) -> List[Optional[float]]`: per clock minute,
  the median over prior days that are **calm evenings** (`late_meeting_hours == 0 and evening_social
  == 0` by `day_features`) when >= 10 such days exist (else all days), excluding minutes inside
  watch workouts, using a ±10-minute window. Cache key `("norm", upto, window_days)`.
* `event_response(ds, ev, norm) -> Dict`: `during_mean, during_max, norm_during, delta_during,
  post60_mean, post60_norm, delta_post60, elevated_until (datetime|None: first minute after end where
  the 15-min rolling mean <= norm + 3 for 15 consecutive minutes, searching up to 3 h), series
  (5-min means from start-30 to end+180), series_norm, series_start`.
* `evening_summary(ds, d, norm) -> Dict`: HR 20:00–23:00 mean vs norm, `elevated_until`, `series`.
* `workout_signature(ds, start, end) -> Dict{minutes_over_120, mean, max, n_samples}`.
* `visits_during(ds, start, end) -> List[Tuple[LocationVisit, int]]` with overlap minutes.
* `night_hr_series(ds, night) -> List[Optional[float]]` (10-min means for the night; Replay/Morning).

### 7.4 `reality.py` (engine-core)
`reality_checks(ds, start, end, answers: Dict[str, Dict[str, Any]], cache=None) -> List[RealityCheck]`
where `answers` is exactly `Store.answers()` output. Iterate `ds.events_on(d, include_unattended=True)`
so answered events still produce their check; ids `rc-{event_id}` / `rc-{visit_id}`.
* **booked_not_seen**: past events of type `workout|social|travel`. Expected places: workout ->
  gym/outdoors; social -> restaurant/bar; travel -> airport/transit/away/hotel. `confirmed` (no check)
  if visits of an expected type cover >= 50 % of the window, OR (workout) `minutes_over_120 >= 0.4 *
  duration`. `contradicted` -> check if visits of a non-expected type cover >= 50 % AND (workout)
  `minutes_over_120 < 5`. `uncertain` -> check only for workout/social with *no* location data that
  day and no HR confirmation. **Meetings never generate checks.**
* **seen_not_booked**: gym visit >= 40 min with `minutes_over_120 >= 15` and no workout event
  overlapping >= 30 %; restaurant/bar visit >= 40 min **starting >= 17:00** with no social event
  overlapping >= 30 %. `suggested_event = CalendarEvent(id=new_id("ev","detected",visit_id),
  source="user", type=workout|social, title="Gym (detected)"/"Dinner out (detected)", location_hint=
  place_name)` over the visit window.
* Evidence chips (kind `calendar` / `location` / `hr`): "Booked: Gym 18:00–19:00", "At home 17:40–
  21:10 (Maps)", "Heart rate stayed at 62–71 bpm", "Heart rate 138 bpm on average for 48 min".
* Questions: "Did you make it to the gym on Tue 22 Sep, 18:00?" / "Looks like a workout at SATS
  Odenplan on Wed 16 Sep, 18:05–19:10 — add it to your calendar?" / travel: "Did the trip to Berlin
  on Mon 15 Sep happen?" `consequence`: "If no, this workout leaves your patterns." / "If yes, a
  workout is added to your calendar and patterns."
* Apply answers: `status = answer`, `answered_at = parse_ts(ts)`. Order: open first (newest first),
  then resolved. Return all checks in `[start, end]`; the Engine splits `open` into *recent* (last 14
  days) and *older* for the UI.

### 7.5 `attribution.py` (engine-model)
Pure-Python ridge with LOO-CV lambda, moving-block bootstrap, active-only contributions.
* `@dataclass FitResult`: `keys, coef: Dict[str,float], intercept, x_mean, x_sd, y_mean, r2, rmse,
  r2_loo, rmse_loo, ridge_lambda, n, n_total, n_unworn, ci: Dict[str, Optional[Tuple[float,float]]],
  n_active: Dict[str,int], boot: List[Dict[str,float]] (B draws, original units), loo_residuals:
  Dict[date, float], hat: Dict[date, float], dates: List[date], insufficient: bool, calm_day_pred:
  float, target, history_days, exclude`.
* `design(ds, upto, history_days=None, exclude=None, include_unattended=False, target="score") ->
  Tuple[List[Dict[str,float]], List[float], List[date], int, int]` (worn nights with a score whose
  `day_features` exist; also returns total and unworn counts in the window).
* `fit(ds, upto, exclude=None, history_days=None, target="score", bootstrap=500, seed=0, cache=None,
  include_unattended=False) -> FitResult`:
  - `n < 10` -> `insufficient=True`, all coef 0, ci None, r2 0, rmse = sd(y) or 10.0.
  - Standardise X (sd floor 1e-9; constant column -> coef 0, excluded from lambda search); any k with
    `n_active < 3` -> coef 0, ci None.
  - Lambda by LOO-CV over `{0.5, 1, 2, 5, 10, 20, 40}`: `A = inv(X'X + lambda I)` (Gauss–Jordan on the
    <= 10x10 matrix), `beta = A X'y`, `h_ii = x_i' A x_i`, `e_loo,i = e_i / (1 - h_ii)`; pick argmin
    sum e_loo². `r2_loo = 1 - sum(e_loo²)/sum((y - ybar)²)` clamped to [0, 1]; `rmse_loo`. In-sample
    r2 (clamped) and rmse also stored. Intercept = y_mean; `calm_day_pred = intercept - sum coef[k]
    * x_mean[k]`.
  - Bootstrap: moving-block, block length 5 (draw ceil(n/5) random starts, concatenate, truncate to
    n), B=500, standardisation fixed from the full sample, precomputed per-night outer products so
    each resample is a weighted sum; CI = 2.5/97.5 percentiles in points per unit. Must run < 1.5 s
    for n=70.
* `predict(fit, reg) -> float` (clamped 0..100); `predict_interval(fit, reg_before, reg_after) ->
  Tuple[float, float]` = 2.5/97.5 percentiles of `sum_k b[k]*(after[k]-before[k])` over `boot`.
* `summary(fit) -> ModelSummary` (fill every field incl. `ridge_lambda, r2_loo, rmse_loo,
  insufficient, calm_day_pred, n_total_nights, n_unworn`).
* `explain_night(ds, morning, fit, norm, cache=None) -> Tuple[List[Cause], List[Cause],
  List[Evidence], Dict]`:
  - `night_date = morning - 1`; `f = day_features(ds, night_date)`; `reg = f.regressors()`.
  - **Only active factors** (`reg[k] != 0`) are reported. `contribution_k = coef[k] * reg[k]`
    (reference = a calm day). Causes: contribution < -0.75 sorted ascending (max 3, rank 1..3);
    helpers: > +0.75 (max 2). `is_weekend` never listed. `points_low/high` from `boot`.
  - `confidence`: `low` if `n_active[k] < 4` or `fit.n < 20`; `high` if CI excludes 0 and `n_active
    >= 8` and `|coef * mean active x| >= 1.0`; `medium` if (CI excludes 0 and `n_active >= 4`) or
    `n_active >= 8`; else `low`. With `10 <= n < 20` cap at `medium`. `n_similar = n_active[k]`.
  - Titles / details (hour text via `timeutil.hour_label`):
    - late_meeting_hours: "Meeting until {HH:MM}" (latest meeting); detail from `event_response`:
      "Heart rate {delta_post60:+.0f} bpm above your evening norm until {elevated_until}" (or "…for
      the rest of the evening"); evidence `hr` with series + series_norm.
    - meetings_over_3: "{n} meetings, {max_b2b_run} back-to-back"; detail "Overnight HRV {pct:+.0f} %
      vs your baseline"; evidence `hrv`.
    - evening_social: "{title} until {HH:MM}"; detail "Bedtime {shift} later than usual; resting heart
      rate {delta:+.0f} bpm"; evidence `bedtime`, `rhr`. **Body-signal rule**: if rhr z >= 1.0 or
      wrist_temp z >= 1.0 or hrv z <= -1.0, append Evidence(kind="rhr"|"temp", text="Body signals (RHR
      {d:+.0f} bpm, wrist temp {t:+.1f} °C) suggest more than the late evening itself — e.g. alcohol,
      which the calendar cannot see").
    - workout_late: "Workout at {HH:MM}"; detail "Watch logged {avg_hr} bpm for {min} min; you fell
      asleep {onset} after going to bed".
    - workout_morning (helper): "Morning workout"; detail "on the {n} mornings you trained, scores
      averaged {adj:+.0f} points (adjusted)".
    - travel: "{title}"; detail "on your {n} travel days, scores averaged {adj:+.0f} points (adjusted)".
    - early_start: "First event {HH:MM}"; detail "Slept {duration} vs your usual {usual}".
    - protected_evening (helper): "Protected evening"; detail "Bedtime {shift} earlier than usual".
    - b2b_over_2: "{run} meetings back-to-back"; detail "HRV {pct:+.0f} %".
  - `proximal` (worn nights): bedtime vs 28-night median ("Bedtime 55 min later than usual"), duration
    vs need and usual, interruptions vs median, HRV %, RHR delta.
  - meta: `predicted` (full centred prediction), `calm_day_pred`, `residual_loo` (= `loo_residuals
    [night_date]` when the night is in the fit, else actual - predicted), `unexplained_note`: if
    `residual_loo <= -1.5*rmse_loo` -> "About {|r|:.0f} points are not explained by your calendar.
    Hidden factors like alcohol, caffeine, screens, a short night before, or illness may matter." plus
    "Wrist temperature is {dev:+.1f} °C above baseline — a sign of illness or alcohol." when temp z >=
    1.5; if `residual_loo >= 1.5*rmse_loo` -> "You slept better than your calendar predicts."
    Wording rule everywhere: "was followed by", "is associated with", never "caused".
* `validation(ds, fit, engine_fit_before_answers, checks, cache=None) -> Dict` (Lab only; reads
  `ds.truth`): `coefficients: [{key, label, estimated, ci, planted_total, planted_direct, design,
  n_active, null_planted: bool, ci_covers_zero}]`, `spearman_total` and `spearman_direct` (over the 9
  planted keys), `pooled_spearman` over (night, factor) pairs where the factor is active (true
  contribution vs engine contribution), `pearson_totals` across nights (sum of true calendar
  contributions vs `predicted - calm_day_pred`), `holdout: {rmse_holdout, rmse_naive, skill}` (fit on
  nights <= end-14, predict the last 14 worn nights; naive = median of training scores; `skill = 1 -
  rmse/rmse_naive`), `spearman_before_answers` (fit with `include_unattended=True`) vs
  `spearman_after_answers`, `reality: {booked_not_seen: {tp, fp, fn, precision, recall},
  seen_not_booked: {tp, fn, recall}}` (positives = truth.attended False with type workout/social/travel;
  exclude `reason == "wfh"` from negatives), `hidden: {nights_with_hidden, flagged, precision, recall,
  illness_nights, unworn_nights, unworn_social_nights, sleep_debt_mean}`, `stressors: {pct_booked_not
  _attended, pct_nights_hidden, pct_unworn, r2_gap: r2 - r2_loo}`, `limitations: [str]` (DST hour,
  one person's data, hinge features). Spearman/Pearson in pure Python; all values finite or None.

### 7.6 `habits.py` (engine-model)
* `HABIT_DEFS` (key, title, description, group, predicate(DayFeatures), regressor_key|None):
  `late_meeting` (late_meeting_hours > 0; `late_meeting_hours`), `heavy_meetings` (n_meetings >= 5;
  `meetings_over_3`), `back_to_back` (max_b2b_run >= 3; `b2b_over_2`), `evening_social`,
  `morning_workout` (`workout_morning`), `late_workout` (`workout_late`), `travel`, `early_start`,
  `protected_evening`, `calm_weekday` (n_meetings <= 2 and not is_weekend; None), `weekend_night`
  (is_weekend; `is_weekend`). No `any_workout`, no unstratified `calm_day`.
* `rank_habits(ds, upto, history_days=None, fit=None, bootstrap=1000, seed=0, cache=None) ->
  List[Habit]`: worn nights in the window split into strata by `is_weekend`; `effect = sum_s w_s
  (mean_with,s - mean_without,s)`, `w_s = n_with,s / n_with`, over strata where both groups are non-
  empty (weekend_night itself uses the raw difference); `raw_effect` = unstratified difference;
  bootstrap CI within strata (percentile); `adjusted_effect = fit.coef[k] * mean(reg[k] | active)`
  when a regressor maps; `metric_effects = {"hrv_ms_pct": stratified % diff, "resting_hr": bpm diff}`.
  `confidence`: `high` if CI excludes 0 and min(n_with, n_without) >= 10; `medium` if min(n) >= 6 and
  (CI excludes 0 or min(n) >= 12); else `low`; `direction = neutral` if |effect| < 1.5. `rank_score =
  conservative * weight` where conservative = `min(|lo|, |hi|)` if CI excludes 0 else `0.25*|effect|`,
  weight high 1 / medium 0.7 / low 0.4. Sort by rank_score desc; drop habits with `n_with == 0`.
* `meeting_load_buckets(ds, upto, weeks=6, cache=None) -> List[HabitBucket]` weekday nights only,
  labels "0 to 2 meetings", "3 to 4 meetings", "5+ meetings", bootstrap lo/hi.
* `weekly_insight(ds, upto, weeks=6, habits=None, cache=None) -> Dict`: `buckets`, `headline` — "Days
  with five or more meetings were followed by scores {d:.0f} points lower than calm days (n = {a} vs
  {b})." only if the bucket-difference CI excludes 0, else "Meeting load made little difference
  in the last 6 weeks (difference {d:.0f} points, n = {a} vs {b}).", `strongest_pattern` (top habit with
  confidence != low as text, or None), `last7: [{date, score, worn, chips: describe_features}]`,
  `heat: [{date, score, worn, is_weekend}]` for the full history, `n_nights`, `top_habits` (5).

### 7.7 `suggestions.py` (engine-app)
`suggest(ds, morning, causes, habits, fit, accepted: Dict[str,str], cache=None) -> List[Suggestion]`
(max 3; ids `sg-{morning}-{kind}`; gains via `whatif.predict_day` on **today's** (`morning`) calendar
with `gain_low/high` from `predict_interval`; `body` ends with "likely {lo:+.0f} to {hi:+.0f} points"):
* late-meeting cause/habit -> `protect_evening`: "Protect 21:00 to 22:00 tonight", `proposed_event`
  (type protected, "Wind down (StressLess)" 21:00–22:00 on `morning`). If today has a meeting ending
  >= 19:30 also `move_meeting`: "End {title} by 18:00".
* heavy/back-to-back -> `buffer`: "Add a 20-minute buffer after {chain end}" (focus event).
* late-workout habit (medium+) and a late workout today/tomorrow -> `move_workout`: "Move {workout} to
  07:00".
* evening social today and an early start tomorrow -> `later_start`: "Start tomorrow at 08:30".
* travel today/tomorrow -> `recovery_day`: "Block a recovery evening after {trip}".
Mark `accepted=True` if id in `accepted`. Skip suggestions whose factor has `n_active < 3`.
`to_ics(ev) -> str`: `VERSION:2.0`, `PRODID:-//StressLess//Demo//EN`, `X-WR-TIMEZONE:Europe/Stockholm`,
UTC `DTSTART/DTEND` (`20260927T190000Z`), `DTSTAMP`, `UID`, `SUMMARY`, `DESCRIPTION:Suggested by
StressLess`, CRLF, lines folded at 75 octets.

### 7.8 `whatif.py` (engine-model)
* `apply_modifications(events, mods) -> List[CalendarEvent]` (copies): `{"op":"remove","event_id"}`,
  `{"op":"shift","event_id","hours"}`, `{"op":"end_at","event_id","hour"}`, `{"op":"to_protected",
  "event_id"}`, `{"op":"add","event":{title,start,end,type}}` (ids `new_id("ev","whatif",date,i)`).
  Raise `ValueError` for unknown ops/ids.
* `predict_day(ds, d, mods, fit) -> WhatIfResult` with `delta_low/high` from `predict_interval`,
  `rmse = fit.rmse_loo`, `changed_factors`, predictions clamped 0..100.

### 7.9 `reasoning.py` (engine-app)
* `class Reasoner: mode: str; def narrate(self, payload: Dict) -> str`.
* `RuleReasoner` (mode `rules`): 2–4 sentences — score vs usual; #1 cause + its evidence; #2 cause with
  "on days like that…" pattern; helpers; unexplained note; closing "Based on {n} nights of your data ·
  correlation, not proof." Handles missing night ("Your watch has no data for last night…") and
  insufficient history ("Building your baseline: {n} of 10 nights").
* `ClaudeReasoner` (mode `claude`): lazy `import anthropic`; `client = anthropic.Anthropic()`; model
  `os.environ.get("STRESSLESS_CLAUDE_MODEL", "claude-opus-5")`; `client.beta.messages.create(model,
  max_tokens=4000, system=SYSTEM, messages=[{"role":"user","content": json.dumps(payload)}],
  betas=["server-side-fallback-2026-07-01"], fallbacks="default")`; on `anthropic.BadRequestError`
  retry once with `client.messages.create` without betas/fallbacks; if `stop_reason == "refusal"` ->
  rules; join text blocks; any exception -> log + rules. SYSTEM: "You write the morning explanation
  for StressLess… <= 90 words, plain language, use only numbers present in the JSON, say 'likely',
  never medical advice, end with a one-line suggestion." Payload = `build_payload(report)`: score,
  baseline, rating, causes (title/detail/points/confidence), helpers, proximal texts,
  unexplained_note, n_nights, suggestion title — **never** ids, start/end, location_hint, attendees,
  lat/lon (test_reasoning asserts no such keys and no `\d{4}-\d{2}-\d{2}T` strings).
* `get_reasoner() -> Reasoner`; `reasoning_mode() -> str`.

### 7.10 `pipeline.py` (engine-app)
```python
class Engine:
    def __init__(self, ds: Dataset, store: Optional[Store] = None)   # calls store.apply_to(ds); self._cache = {}
    def invalidate(self) -> None
    def fit_for(self, upto: date, history_days=None) -> FitResult          # cached by (upto, history_days)
    def norm_for(self, upto: date) -> List[Optional[float]]                # cached
    def morning_report(self, morning: date, history_days=None) -> MorningReport
    def week(self, end: date, history_days=None) -> Dict
    def habits(self, upto: date, history_days=None) -> List[Habit]
    def reality(self) -> Dict            # {"open": [recent], "older": [older open], "resolved": [...]}
    def answer(self, check_id: str, answer: str) -> Dict   # see below
    def whatif(self, d: date, mods: List[Dict]) -> WhatIfResult
    def accept_suggestion(self, morning: date, suggestion_id: str) -> Tuple[Suggestion, CalendarEvent, str]
    def suggestion_ics(self, morning: date, suggestion_id: str) -> str
    def day_bundle(self, d: date) -> Dict
    def validation(self) -> Dict
    def model_summary(self, upto: date, history_days=None) -> ModelSummary
    def report_markdown(self, report: MorningReport) -> str
    def demo_check(self) -> Dict         # {"ok": bool, "checks": [{"name", "ok", "detail"}]}
    def sources_for(self, d: date) -> Dict   # {"calendar_events", "maps_places", "watch_minutes"}
```
* Date validation: report dates outside `[ds.start + 1, ds.today]` -> `NotFound("No report yet" /
  "Before your data starts")`; day/planner dates outside `[ds.start, ds.today + 7]` -> `NotFound`;
  unknown check/suggestion ids -> `NotFound`; bad mods/answers -> `EngineError`.
* `morning_report`: night None or `worn=False` -> `score=None`, `missing_data="No watch data for the
  night of {date} — was the watch charging?"`, still `sources`, features context, suggestions.
  `rating = sleep_score.rating(score)`; `baseline_score` = 28-night median; `sources = sources_for
  (night_date)`; `confidence_note` = "Based on {n} nights · explains about {r2_loo:.0%} of night-to-
  night variation out of sample · correlation, not proof" (or the insufficient text).
* **Narratives**: rules recomputed every request; only `claude` narratives cached in the store with
  key `f"{morning}:{history_days}:claude:{store.state_version()}"`.
* `answer(check_id, answer)`: find the check (404); booked_not_seen -> `ds.set_attended(event_id,
  answer == "yes")`; seen_not_booked + yes -> `ds.add_event(check.suggested_event)` +
  `store.add_user_event`; compute the related habit (`late_workout`/`morning_workout` by slot, or
  `evening_social`, or `travel`) **before** and **after** `invalidate()`; `store.save_answer`; return
  `{"check": RealityCheck, "report_dates_affected": [check.date + 1], "habit_before": {key, title,
  effect, n_with} | None, "habit_after": {...} | None, "replay_date": check.date}`.
* `accept_suggestion` is idempotent (existing event returned if already accepted); adds the
  `proposed_event` (`source="user"`) to ds + store; `suggestion_ics` works whether or not accepted.
* `day_bundle(d)` exact shape: `{date, events: [CalendarEvent incl. attended], visits, hr: [1440],
  norm: [1440], night: SleepNight|None (night starting evening d), night_prev: SleepNight|None,
  activity: DailyActivity|None, workouts: [WatchWorkout], features: DayFeatures, chips:
  describe_features, checks: [RealityCheck for d], responses: {event_id: event_response for
  meetings/social/workouts}, evening: evening_summary, is_today: bool}`.
* `demo_check()`: last night worn; report has >= 3 causes with #1 not `low`; a `protect_evening`
  suggestion exists; today has a meeting ending >= 19:30; >= 2 open recent reality checks (one of
  each kind); validation `spearman_total >= 0.6`; no `insufficient`.

---

## 8. Server (`stressless/server`) and CLI (`run.py`)

### 8.1 HTTP
`ThreadingHTTPServer` on `127.0.0.1:{port}` (default 8765; on `OSError` try +1..+20; `--port 0`
lets the OS pick). `server/app.py` holds `class AppState: store, engine, lock = threading.RLock(),
pregen: Dict[str, str]` reachable via `self.server.state`. **Every `/api/*` handler body runs inside
`with state.lock:`**; static files are served without the lock. `POST /api/persona` and `/api/reset`
build the new Store/Engine outside the lock and swap inside it. Static: web root = `ROOT/web`;
`full = os.path.realpath(os.path.join(web_root, unquote(path).lstrip("/")))`, reject unless
`full.startswith(web_root + os.sep)`; MIME by extension; `Cache-Control: no-store`. JSON bodies UTF-8
with correct `Content-Length`; `Content-Type: application/json; charset=utf-8`; `protocol_version =
"HTTP/1.0"`. Error mapping: `EngineError` -> its status `{"error": msg}`; `ValueError` from date
parsing -> 400; anything else -> 500 with message + stderr traceback. Empty/`null` query values mean
None. One stderr log line per request (method, path, status, ms).

**Background pre-generation**: after binding, spawn a daemon thread that generates the other two
personas (same seed/days/anchor) and writes `data/pregen-{persona}-{seed}-{anchor}.json`; `state.pregen
[persona] = "pending"|"ready"|"error"`. `POST /api/persona` loads from the cache when ready, else
generates synchronously.

### 8.2 Routes
| Method | Path | Response |
|---|---|---|
| GET | `/api/meta` | `{persona:{key,name,tagline,description,tz}, personas:[{key,name,tagline,ready}], seed, days, source, start, end, today, anchor_mode, n_nights, reasoning_mode, version, history_days_options:[7,14,28,null], generated_at, showcase}` |
| GET | `/api/health` | `{ok, python, version, persona, n_nights, today, checks:{report,week,habits,reality,day,model}}` (each computed once at startup) |
| GET | `/api/report/{date}?history_days=` | `MorningReport` (404 -> "No report yet") |
| GET | `/api/report/{date}.md` | `text/markdown` |
| GET | `/api/day/{date}` | `day_bundle` |
| GET | `/api/week?end={date}&history_days=` | `weekly_insight` |
| GET | `/api/habits?upto={date}&history_days=` | `{habits:[Habit], model: ModelSummary}` |
| GET | `/api/model?upto=&history_days=` | `ModelSummary` |
| GET | `/api/reality` | `{open, older, resolved}` |
| POST | `/api/reality/{id}/answer` `{answer}` | answer dict (7.10) |
| POST | `/api/whatif` `{date, mods}` | `WhatIfResult` |
| POST | `/api/suggestions/{morning}/{id}/accept` | `{suggestion, event, ics}` (never triggers a download) |
| GET | `/api/suggestions/{morning}/{id}.ics` | `text/calendar`, `Content-Disposition: attachment; filename="stressless-{id}.ics"` |
| GET | `/api/validation` | validation dict |
| POST | `/api/persona` `{persona, seed?}` | swaps dataset; returns meta payload |
| POST | `/api/reset` | deletes all data, regenerates default persona; returns meta |
| POST | `/api/log` `{level, message, stack}` | `{ok:true}` |

### 8.3 `run.py`
```
python3 run.py [--port 8765] [--no-browser] [--persona alex|sam|robin] [--seed 7] [--days 70]
               [--anchor YYYY-MM-DD] [--regenerate] [--data-dir DIR] [--no-showcase]
python3 run.py --report today|YYYY-MM-DD [--json]
python3 run.py --demo-check            # pre-flight checklist; exit 1 on failure
python3 run.py --import-health export.xml --import-ics cal.ics --import-timeline PATH [--persona-name "Nima"]
python3 run.py --test                  # unittest discover -s tests -t ROOT
python3 run.py --screenshots [--out docs/screenshots]
```
First line: `if sys.version_info < (3, 9): sys.exit("Python 3.9+ required …")`. `ROOT =
Path(__file__).resolve().parent; sys.path.insert(0, str(ROOT))`; defaults `--data-dir ROOT/data`;
`os.makedirs(exist_ok=True)`, on `PermissionError` fall back to `tempfile.gettempdir()/stressless`
with a warning. Startup: load store; regenerate if missing, `--regenerate`, or stale today (§3);
build Engine; run health checks and print "All 6 checks passed" (or the failure); bind; print
persona, range, URL, reasoning mode, "Press Ctrl+C to stop"; `threading.Timer(0.5, webbrowser.open,
[url]).start()` unless `--no-browser`; `serve_forever()`; `KeyboardInterrupt` -> shutdown, exit 0.
`--test` runs `unittest.main(module=None, argv=["", "discover", "-s", "tests", "-t", str(ROOT), "-v"])`.
`tools/screenshot.sh`: renders every view at 1440×900 via headless Chrome (path
`/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`), both against the live server and with
`?mock=1`, `--dump-dom` per view; **fails if the DOM contains `sl-error-entry` or `error-card`** or
stderr has `Uncaught`.

---

## 9. Frontend (`web/`)

### 9.1 Shell — `index.html`, `css/base.css`, `js/core.js` (lead, done; read core.js)
Exact `window.SL` surface:
```js
SL.el(tag, attrs, ...children)     // attrs: class, style{}, dataset{}, on<Event>: fn, any attribute; children: Node|string|array|null (strings -> text nodes)
SL.svg(tag, attrs, ...children)    // SVG namespace — charts.js MUST use this
SL.clear(node)
SL.icon(name, {size, class}) -> <span class="icon">   // names: see ICON_PATHS in core.js
SL.eventIcon(type) -> icon name
SL.api.get(path) / SL.api.post(path, body)             // Promise<json|text>; throws Error(message) on !ok (message = server error text)
SL.state.get(k) / set(k, v) / on(k, fn) -> unsubscribe  // keys: 'meta', 'historyDays' (null = all), 'theme', 'route'
SL.meta()                                               // current meta object
SL.fmt.score|num|signed|pct|hm(iso)|day(isoDate)|dayLong|minutes|bpm|hourFloat
SL.date.parse|toISO|addDays|today() (= meta.today)|isFuture|weekday|diffDays
SL.palette.event(type)|series(i)|status(kind)|accent()|ink(level)|hairline()|var(name)
SL.EVENT_TYPES, SL.EVENT_LABELS
SL.toast(msg, {kind: 'info'|'success'|'error', duration})
SL.theme.get/set/toggle
SL.log(level, msg, err)
SL.router.register(name, {title, render(container, {params, query}) -> cleanup | Promise<cleanup>}) / go(hash) / current() / hashFor(name)
SL.refreshMeta() -> Promise<meta>                       // call after POST /api/persona or /api/reset
SL.ready                                                // Promise resolved after first render
SL.modal.confirm({title, body, confirmLabel, danger}) -> Promise<boolean>   // in-app dialog; never window.confirm
SL.busy(label|null)                                     // full-screen stepper while a persona regenerates
SL.mock                                                 // true when ?mock=1
```
Contracts other files must honour:
* **tour.js must set `SL.tour = { start(), stop(), toggle(), active() -> bool, next(), prev() }`**
  at load time. core.js suppresses global shortcuts while `active()` is true.
* **replay.js sets `SL.replay = { play(speed), pause(), seek(minute), playRange(fromMin, toMin,
  speed) }`** while mounted and `null` on cleanup.
* core.js re-renders the current view on theme toggle and when `historyDays` changes — views must
  be re-render-safe and read `SL.state.get('historyDays')` to build `?history_days=`.
* core.js renders a top-bar pill "Using {n} nights · Reset" whenever `historyDays != null`, and the
  persona chip is a menu (Alex / Sam / Robin, seed shown) that POSTs `/api/persona`, shows `SL.busy`
  with a four-step stepper, refreshes meta, resets `historyDays`, and navigates to
  `#/morning/{today}`.
Routes: `#/morning/{date}?reveal=1`, `#/replay/{date}?t={minute}`, `#/week/{end?}`, `#/habits`,
`#/reality`, `#/planner/{date?}`, `#/data`, `#/lab`; `?tour=1` starts the tour. Keys (suppressed in
inputs): `1` Morning, `2` Replay, `3` Week, `4` Habits, `5` Reality, `6` Planner, `7` Data, `8` Under
the hood, `←/→` day on Morning/Replay, `t` tour, `d` theme, `?` help.

**Mock mode (`?mock=1`)**: keys `"GET /api/report/2026-09-27"`, `"POST /api/whatif"`; a value may be a
function `(method, path, body) => payload`. Resolution: exact `METHOD path` -> exact without query ->
longest key that is a prefix of the path. **Key ownership**: fixtures-a.js owns `GET /api/meta`,
`/api/report/*`, `/api/week`, `/api/habits`, `/api/model`, `POST /api/suggestions/*`; fixtures-b.js
owns `/api/day/*`, `/api/reality`, `POST /api/reality/*`, `POST /api/whatif`, `/api/validation`,
`POST /api/persona`, `POST /api/reset`, `POST /api/log`. Bodies: `window.__FIXTURES__ =
Object.assign(window.__FIXTURES__ || {}, /*JSON-START*/ {...} /*JSON-END*/);` with **strict JSON**
between the markers; function fixtures in a second `Object.assign` after the markers. Fixture dates
use anchor 2026-09-27 (today) / night 2026-09-26. `tests/test_fixtures_contract.py` extracts the JSON
and asserts, for payloads that map to dataclasses (MorningReport, RealityCheck, Habit, WhatIfResult,
ModelSummary, DayFeatures inside day), that `set(payload) == {f.name for f in fields(cls)}` and
`from_dict` succeeds.

### 9.2 Design tokens and chart palette (in `base.css`)
Dark default; light theme available. See `base.css` for every variable (`--page --card --card-2
--card-3 --hairline --ink-primary/secondary/muted --accent --series-1..6 --evt-* --seq-1..6
--div-better/worse/mid --status-* --grid --axis --sleep-deep/core/rem/awake`).
**Chart palette (validated with `tools/validate_palette.sh` against each surface; do not change):**
| slot | event type | dark | light |
|---|---|---|---|
| 1 | meeting | `#E85A45` | `#E0553F` |
| 2 | travel | `#3987e5` | `#2a78d6` |
| 3 | workout | `#199e70` | `#1baf7a` |
| 4 | focus | `#c98500` | `#eda100` |
| 5 | social | `#9085e9` | `#4a3aa7` |
| 6 | personal | `#d55181` | `#e87ba4` |
| — | protected | `#8A8FB0` at 35 % + shield icon | `#7A7F9E` |
Adjacent pairs pass; all-pairs does not -> **every event block/legend swatch always carries a text
label and an icon**. Light-mode aqua/yellow/magenta are < 3:1 on white -> direct labels mandatory.
Single-series magnitude (meeting-load bars, sparklines): slot 1. Effects: diverging blue (better)
/ coral (worse) around 0. Ring colour follows the **rating band** via status tokens (Very low/Low ->
critical/serious, OK -> warning, High/Very high -> good) with the band text next to it; coral stays
a UI accent. Marks: bars <= 24 px, 4 px rounded data-end, 2 px lines, markers r >= 4 with 2 px
surface ring, hairline solid grid, area fills 10 %. Text never wears series colour.
**CSS namespaces**: base.css owns unprefixed primitives; charts.css uses `.c-*` only; each view uses
`.v-<view>-*`; tour.css `.tour-*`.

### 9.3 `charts.js` (frontend-a) — SVG primitives with hover layer and table twin
```js
Charts.minuteOf(iso, dayIso) -> int            // HH*60+MM, +1440 if iso's date is dayIso+1 (0..2880)
Charts.ring(el, {value, max:100, label, sublabel, band, size})        // hero meter; colour from band via status tokens; same-ramp track
Charts.sparkline(el, {values, baseline?, norm?, start?, stepMin?, width, height, unit, label})  // crosshair tooltip; norm drawn dotted, exceedance shaded 10 %
Charts.bars(el, {items:[{label, value, n, lo, hi}], unit, max, vertical, formatValue}) // one hue, CI whiskers, n under labels, direct labels
Charts.line(el, {series:[{name, values:[{x, y}], color}], xLabels, yDomain, unit, baseline?})  // crosshair + all-series tooltip; legend when >= 2 series
Charts.effectBars(el, {items:[{label, effect, lo, hi, confidence, direction, adjusted?}], onSelect}) // diverging around 0, CI whiskers, adjusted marker
Charts.dayTimeline(el, {date, events, visits, hr, norm, night, nightPrev, workouts, checks, cursorMinute, compact, onSeek, onHover})
   // 24 h (0..1440): event lane (typed blocks: icon + label, protected = outlined + shield, unattended = hatched), location lane, HR line with norm dotted + exceedance fill, sleep shading (nightPrev morning end + night evening start), watch workouts as brackets, check markers; crosshair; returns {update, destroy, setCursor(min)}
Charts.heatStrip(el, {days:[{date, score, worn, is_weekend}], onSelect})   // weeks x 7, sequential coral, unworn hatched, tooltip, click
Charts.scatter(el, {points:[{x, y, label, hollow}], xLabel, yLabel, identity:true, errorBars:[{lo,hi}]})
Charts.stages(el, {night})                                                // stacked stage bar with 2 px gaps + legend, sleep-* tokens
Charts.table(el, columns, rows)                                           // table twin helper
```
Each returns `{update(data), destroy()}`. Tooltips via `textContent`. No dual axes. Reduced motion
respected.

### 9.4 Views
**Morning** (`morning.js`, default). Sources strip at top (`data-tour="sources"`: "Calendar 6
events · Maps 4 places · Watch 1,392 min" from `report.sources`). Hero row (`data-tour="hero"`):
**watch card** (`data-tour="watch-card"`: score, time asleep, rating word, "That's all your watch
tells you."), ring, and the **causes column** (`data-tour="causes"`) which — when `query.reveal ===
'1'` — starts veiled with a big `Why?` button (`data-tour="reveal"`); clicking staggers in *Three
likely causes* (numbered; title, detail, `−6 pts` chip with "likely −9 to −3" on hover, confidence
badge, #1's evidence sparkline expanded by default, others expandable) and the **suggestion card**
(`data-tour="suggestion"`: "Suggestion: protect 21:00 to 22:00 tonight · likely +2 to +6" · **Add to
calendar** -> POST accept -> "Added ✓" + separate "Download .ics" link; never auto-download). Then
*What helped*; narrative card with reasoner badge (`data-tour="narrative"`); compact day strip
(`Charts.dayTimeline compact`) — click -> `#/replay/{night_date}?t={minute}`; *Last night in
numbers* (`data-tour="recovery"`): tiles HRV, resting HR, wrist temp (value, delta, 14-night
sparkline, status icon+label) with resp rate and SpO2 under "more"; night details (bedtime, asleep,
awake, `Charts.stages`); proximal chips; footer (`data-tour="confidence"`) with `confidence_note` and
the cold-start select (7 / 14 / 28 / all -> `SL.state.set('historyDays', …)`). Missing-night state;
404 -> "No report yet" (not the error card); insufficient-history state.

**Week** (`week.js`): `#/week/{end}`; `heatStrip` of the whole history at top (`data-tour="heat"`,
click -> Morning of date+1); headline; *Average sleep score by meeting load, last 6 weeks*
(`data-tour="buckets"`, 3 bars, n, CI); *Strongest pattern* callout (`data-tour="strongest"`); last-7
strip with chips; top 5 habits as `effectBars` linking to Habits.

**Habits** (`habits.js`): filter chips (all/good/bad/group); `effectBars` (`data-tour="effects"`) with
CI, confidence, adjusted marker; per-habit card: title, description, "n = 14 vs 49 nights",
adjusted effect first ("−4.1 pts, adjusted"), stratified effect with CI ("simple comparison: −5.0"),
HRV/RHR effects, example dates -> Morning. Table twin toggle.

**Replay** (`replay.js`): `#/replay/{date}?t=`; `dayTimeline` (`data-tour="timeline"`); transport
(`data-tour="transport"`): Play/Pause, speeds 4x/16x/64x (minutes per second; default 16x), scrub,
chapter buttons *Next event* / *Evening* (17:00) / *Bedtime* (in_bed − 20 min); initial cursor = `t`
or first event − 30 min (or 06:00). **Watch face** (`data-tour="watchface"`): time, HR, "+11 vs
norm", current event icon+title, current place. Side panel: events with reality-check chips and
`responses` deltas ("+11 bpm during", "elevated until 22:00"); night summary; "Explain this night →"
-> `#/morning/{date+1}`. Exposes `SL.replay`.

**Reality** (`reality.js`): header line ("We never ask you to log. We only ask when your calendar,
your location and your body disagree."); inbox (`data-tour="inbox"`) of `open` (last 14 days): card
with question, evidence chips (calendar / Maps / watch icons), **Yes / No**; on answer -> toast +
Resolved card shows consequence and **before → after** ("Late workout: −4.1 → −4.6 pts (11 → 10
nights)") + "See that day →" (`#/replay/{replay_date}`); `older` collapsed under "Older (assumed as
booked)"; resolved list; empty state "All clear — calendar, Maps and watch agree".

**Planner** (`planner.js`): `#/planner/{date}` (default today, allowed to today+7); hero delta
(`data-tour="prediction"`: "+4 · likely +1 to +7" with predicted score under it); events list
(`data-tour="events"`) with **type-relevant controls** (meeting: end at 18:00 / −2 h / remove / →
protected; focus: → protected / remove; workout: move to 07:00 / remove; social/travel/personal:
remove); POST `/api/whatif` debounced 250 ms; changed-factor chips; today's suggestions with Add to
calendar; **Undo changes**. Accepted blocks appear in the list (source `user`).

**Data & privacy** (`data.js`): connection cards (Calendar · Watch · Maps · Reasoning) with status;
data-class table (what we read, why, retention "local only"); *Demo dataset* card (`data-tour=
"personas"`): persona radio cards (name, tagline, ready badge), seed input, **Regenerate**; *Import
your own data* (CLI flags, formats); dataset facts (nights, worn %, unworn
nights and how many were social nights, events, visits); **Delete all data** via `SL.modal.confirm`.
After persona/reset: `await SL.refreshMeta()`, `SL.state.set('historyDays', null)`, go to Morning.

**Under the hood** (`lab.js`, route `#/lab`): pipeline strip with live counts (`data-tour=
"pipeline"`); model card (`data-tour="model"`: n, λ, in-sample R² vs **out-of-sample R²**, RMSE,
coefficients via `effectBars`, caption "95 % intervals per factor; with 10 factors expect roughly one
false alarm in a null world"); **Validation vs planted truth** (`data-tour="validation"`): scatter
estimated vs planted *total* (filled) and *direct* (hollow) with identity line and CI error bars,
caption "the calendar sees the dinner, not the wine"; planted-null row ("Back-to-back meetings:
planted as no effect for Alex — engine {coef:+.1f} (CI {lo}..{hi})"); rank agreement ("0.82 — the
engine ordered the real causes correctly on most nights"); hold-out skill ("predicts the last 14
nights {skill:.0%} better than assuming your median"); before/after answers; reality checks "right /
wrong / missed"; hidden-factor nights and flag precision/recall; missing nights "4 unworn, 3 after
social nights — missing data is not random"; **Why this is not circular** panel (four stressors with
live numbers); cold-start slider (`data-tour="coldstart"`, sets `historyDays`, animates CI widths);
*Open challenges* (`data-tour="challenges"`): each deck challenge -> what the demo does, with "Show
me a night the calendar can't explain →" (`#/morning/{illness_night+1}`); known limitations. Every
truth number labelled "Simulator ground truth — demo only".

**Tour** (`tour.js`): overlay; 10 steps `{title, text, hash, anchor, onEnter}`; navigation via
`SL.router.go(hash)` then poll `[data-tour="anchor"]` every 100 ms up to 3 s; spotlight the anchor;
keys `→`/`space` next, `←` back, `esc` exit; progress dots; resets `historyDays` on step change.
Steps: 1 **Problem** — `#/morning/{today}?reveal=1`, anchor `watch-card`: "A score. No why." ·
2 **Why?** — same page, anchor `reveal`; onEnter clicks the Why button, then anchor `causes` ·
3 **The body rode the meetings** — `#/replay/{today-1}?t=1020`, anchor `timeline`; onEnter
`SL.replay.playRange(17*60, 23.5*60, 64)` · 4 **Reality check** — `#/reality`, anchor `inbox` ·
5 **Patterns over weeks** — `#/week`, anchor `buckets` · 6 **Change tomorrow** — `#/planner/{today}`,
anchor `prediction` · 7 **Same engine, different person** — anchor `persona` (top-bar chip); text
tells the presenter to switch to Robin · 8 **Under the hood** — `#/lab`, anchor `validation` ·
9 **What the calendar can't see** — `#/lab`, anchor `challenges` · 10 **The watch measures. The
calendar explains.** — `#/morning/{today}`, anchor `suggestion`.

### 9.5 Accessibility & polish
Landmarks, focus-visible, `aria-live` toasts, reduced motion respected (replay still functional),
colour never the sole carrier, table twins, min width 1024 px (rail collapse already in base.css).

---

## 10. Tests and quality bar
* `python3 -m unittest discover -s tests -t . -v` passes in < 90 s. Use `tests/helpers.py`
  (`ANCHOR`, cached `dataset()`, `fresh_dataset()`); no test calls `today_local()`.
* Sim: determinism (same seed -> identical `dumps` after `generated_at=None`); ranges; showcase
  guarantees (a)–(f) for all personas at seeds 1..5; score distribution targets; single-factor
  contribution equality; realised effect signs match design signs where `n_active >= 5`;
  Spearman(realised direct, design) >= 0.8 for alex; unique ids; every regressor `n_active >= 5`.
* Engine: features (7.1 list); ridge recovers known coefficients on synthetic data (|err| < 0.6,
  n=200, sd 3); LOO lambda picks a larger lambda on noisier data; `insufficient` at n < 10; active-only
  contributions (a night with no travel never lists travel); reality fixture scenarios (skipped gym
  -> contradicted check; WFH meeting -> none; unbooked gym -> suggestion; lunch restaurant -> none);
  habits: stratified effect removes a planted weekend confound; whatif delta sign matches coef sign
  and interval contains delta; suggestions produce ICS that `parse_ics` round-trips (start/end equal
  after `astimezone`); reasoner payload de-identified.
* **Acceptance** (test_pipeline): Spearman(planted total, estimated) >= 0.6 over the 9 planted keys
  for each persona at seed 7 **and** median over seeds 1..10 >= 0.6 for alex. If a seed fails, the
  sim owner adjusts magnitudes/noise; the engine is never tuned to a seed. `demo_check()` ok for all
  personas at seed 7.
* Connectors: fixture `.ics` (RRULE/EXDATE/TZID/DURATION/RECURRENCE-ID), Apple Health XML with a
  `+0100` date and an overlapping-source night, Takeout SLH JSON.
* Store: round-trip, `apply_to`, truncation on persona change, `state_version` changes on answer.
* API: server thread on port 0; every route 200 and `json.loads(body, parse_constant=fail)`; `..`
  rejected; 404 for future report; POST answer changes the report; `.md`/`.ics` content types; 20
  concurrent GETs during a POST all 200.
* CLI smoke (`test_cli.py`): `run.py --no-browser --port 0 --data-dir tmp --anchor 2026-09-27`,
  read the URL from stdout, GET `/api/health` and `/api/report/2026-09-27`, SIGINT, exit 0 in < 5 s.
* Frontend: `tools/screenshot.sh` — zero `sl-error-entry`/`error-card` in any view, live and mock.

## 11. Coding conventions
Type hints; module docstrings; small pure functions; `logging.getLogger("stressless.x")`; no
prints outside `run.py`. JS: `'use strict'`, IIFE per file, globals only `SL`, `Charts`,
`window.__FIXTURES__`. Never build HTML from strings containing data — `SL.el` only.

## 12. Demo script (README)
1. `python3 run.py --demo-check` the morning of the pitch, then `python3 run.py`.
2. Browser opens on today's Morning with `?reveal=1` via the tour (`t`): "Score 68. That's all your
   watch tells you." Press → : **Why?** reveals three causes and the suggestion. Click **Add to
   calendar**.
3. → Replay auto-plays the evening at 64x: heart rate rides above the norm line after the late
   meeting.
4. → Reality: answer **Yes** to the detected gym; see "−4.1 → −4.6 pts" and "See that day →".
5. → Week: meeting load vs sleep score; strongest pattern. → Planner: end the 19:30 meeting at 18:00;
   the delta rises; the accepted Wind-down block is already there.
6. → Switch persona to Robin in the top bar (< 1 s): different #1 cause, same engine.
7. → Under the hood: engine vs planted truth, the planted null, hold-out skill; drag the cold-start
   slider to 7 nights; → Open challenges. → Close on Morning: "The watch measures. The calendar
   explains."
