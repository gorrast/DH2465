# Project Course DH2465

# StressLess — demo

> Wearables give you a score. They don't tell you why.
> StressLess connects your calendar and your location history to the biometrics your watch already
> collects, and explains what in your day shaped your body and your sleep.

This repository is a **web demo** of the StressLess product: a Next.js frontend and a FastAPI backend,
deployed together on Vercel, with Supabase for sign-in and per-user storage. Because there is no Apple
Watch in the loop yet, the demo uses a **digital twin**: a simulated person whose calendar, Google Maps
history and watch data are generated from a known causal model. Everything downstream — the explanation
engine, the morning report, reality checks, habits, the planner — is the real product logic, and it runs
unchanged on imported real data (Apple Health export, Google Calendar `.ics`, Google Takeout).

Every account gets its own demo. The dataset itself is never stored: the API regenerates it from the
account's persona, seed and date (about 0.15 s, cached on warm instances) and replays the user's own
answers, added events and accepted suggestions on top. Only those few rows live in Supabase, protected by
row-level security.

## Architecture

```
browser ──► Next.js (app/, components/)          React views, charts, tour; Supabase Auth session in cookies
   │            proxy.ts                         refreshes the session, sends signed-out visitors to /login
   └─ /api/* ─► FastAPI (api/index.py → backend/stressless)
                    verifies the Supabase JWT, regenerates the user's dataset, runs the engine
                    └─► Supabase Postgres (PostgREST, as the user)   profiles, answers, user_events,
                                                                      accepted, narratives — RLS per user
```

## Setup

Requirements: Node.js 20+, [uv](https://docs.astral.sh/uv/) (Python 3.12) and a Supabase project.

1. **Supabase.** Create a project, then run `supabase/migrations/20261004000000_stressless_user_state.sql`
   in the SQL editor (or `supabase db push` with the Supabase CLI). Under Authentication → URL
   Configuration, set the Site URL to your deployed URL and add `http://localhost:3000/**` and
   `https://<your-app>.vercel.app/**` to the redirect URLs. Email confirmation stays on: new accounts
   confirm their address through the link in the email, which lands on `/auth/confirm`.
2. **Environment.** `cp .env.example .env.local` and fill in `NEXT_PUBLIC_SUPABASE_URL` and
   `SUPABASE_ANON_KEY` (Project Settings → API). Projects that still use the legacy
   JWT secret also need `SUPABASE_JWT_SECRET`; projects on asymmetric signing keys (the default) do not.
3. **Install and run.**

   ```bash
   npm install
   uv sync
   npm run dev          # Next.js on http://localhost:3000 and FastAPI on :8000 (proxied under /api)
   ```

4. **Tests.** `npm run test:api` runs the Python suite (engine, simulator, connectors, API with an
   in-memory store); `npm run typecheck` checks the frontend.

## Deploy to Vercel

Import the repository in Vercel (framework: Next.js). `api/index.py` becomes a Python function serving
`/api/*` with the packages from `requirements.txt`; `vercel.json` keeps the frontend out of its bundle.
Set the same environment variables as in `.env.local` for Production and Preview, then deploy. To freeze
"today" for a presentation, set `STRESSLESS_ANCHOR=2026-09-27` — every account then sees the same
dates, and the screenshots and numbers below stay reproducible.

## The demo in eight beats

Press `t` (or click **Tour**) to walk these steps with the arrow keys.

1. **Problem.** The Morning view opens like a wearable app: *Score 68 · 6 h 12 min · that's all your
   watch tells you.*
2. **Why?** One click reveals three likely causes with evidence — "Meeting until 20:15: heart rate
   11 bpm above your evening norm until 22:00" — and a suggestion you can put straight into the
   calendar. Click **Add to calendar**.
3. **Replay** (`2`). The day plays back from the evening: heart rate riding above the dotted
   "your usual" line after the late meeting, then bedtime.
4. **Reality check** (`5`). The watch saw a workout the calendar did not know about. Answer **Yes**
   and see the pattern update: *Late workout: −4.1 → −4.6 pts (11 → 10 nights)*.
5. **Week** (`3`). Average sleep score by meeting load over six weeks, and the strongest pattern.
6. **Planner** (`6`). End tonight's 19:30 meeting at 18:00 and watch the predicted score rise, with
   a likely range. The protected block you accepted is already there.
7. **Same engine, different person.** Switch persona in the top bar (Alex → Sam → Robin, under a
   second). Different life, different #1 cause.
8. **Under the hood** (`8`). The engine compared against the planted truth, a planted null factor,
   out-of-sample skill, and everything the calendar cannot see. Drag the cold-start slider to seven
   nights and watch the confidence intervals widen.

Keyboard: `1`–`8` switch views, `←`/`→` change day, `t` tour, `d` light/dark theme (use light on a
bright projector), `?` help.

## Screenshots

| Morning report | Replay |
|---|---|
| ![Morning](docs/screenshots/morning.png) | ![Replay](docs/screenshots/replay.png) |

| Week | Habits |
|---|---|
| ![Week](docs/screenshots/week.png) | ![Habits](docs/screenshots/habits.png) |

| Reality check | Planner |
|---|---|
| ![Reality](docs/screenshots/reality.png) | ![Planner](docs/screenshots/planner.png) |

| Under the hood | Presenter tour |
|---|---|
| ![Lab](docs/screenshots/lab.png) | ![Tour](docs/screenshots/tour.png) |

Regenerate them against a running instance with `STRESSLESS_EMAIL=… STRESSLESS_PASSWORD=… npm run screenshots`
(add `-- --url https://<your-app>.vercel.app` for a deployment; needs `npx playwright install chromium` once).

## What you are looking at

| View | What it shows |
|---|---|
| Morning | Sleep score, three likely causes with evidence, a calendar-ready suggestion, recovery markers (HRV, resting HR, wrist temperature), the night in numbers, and how confident the engine is |
| Replay | A 24-hour timeline: calendar events, where you were (Maps), minute heart rate against your personal norm, sleep; a live watch face while it plays |
| Week | Ten-week score calendar, sleep score by meeting load, strongest pattern, top habits |
| Habits | Every recurring pattern ranked by effect, with intervals, sample sizes and the adjusted (model) effect next to the simple comparison |
| Reality check | Questions asked only when calendar, location and body disagree — booked but not seen, seen but not booked |
| Planner | What-if for today or the coming week; accepted suggestions land in the calendar and as `.ics` |
| Data & privacy | What is connected, which data classes are read and why, persona and seed, importing your own data (coming soon), delete everything |
| Under the hood | Pipeline, model card (in-sample vs out-of-sample fit), validation against planted truth, hidden factors, why this is not circular, cold-start slider, open challenges |

## How the engine works (and what it does not claim)

1. **Features.** Each day's calendar becomes a handful of numbers: meetings beyond three, longest
   back-to-back chain, hours a meeting ran past 18:00, evening social, morning or late workout,
   travel, early start, protected evening. Events you said you did not attend are excluded.
2. **Personal baselines.** Every biometric is compared with your own recent nights (robust median and
   spread), never with population norms.
3. **Within-person model.** A ridge regression across your nights, with the penalty chosen by
   leave-one-out cross-validation. The footer reports the *out-of-sample* share of night-to-night
   variation the calendar explains, not the flattering in-sample number.
4. **Attribution.** Only factors present on that day are listed; each contribution is the model's
   effect for that factor, with a block-bootstrap interval and a confidence badge that depends on how
   many similar nights exist.
5. **Evidence.** Each cause is backed by what the watch measured: heart rate above your evening norm
   after a late meeting, HRV below baseline after a heavy day, bedtime later than usual after dinner.
6. **Honesty.** When a night is worse than the calendar predicts, the report says so and names the
   things a calendar cannot see: alcohol, caffeine, screens, sleep debt, illness. The Lab shows how
   often those hidden factors occurred in the simulation and how often the engine flagged them.

This is correlation from one person's data. The product says "was followed by" and "is associated
with", never "caused".

## Personas

| | Alex | Sam | Robin |
|---|---|---|---|
| | Product lead who lives by the calendar | Consultant: eight meetings and a flight | Founder: late nights and late workouts |
| Signature bad day | Six meetings, four back-to-back, a call until 20:15 | Flight home plus a client dinner | Investor update at 19:00, gym at 20:45 |

Same seed, same anchor date, same data — every time. Change persona and seed under Data & privacy; freeze
the date with `STRESSLESS_ANCHOR`.

## Bring your own data

Uploading your own exports to the web app is coming soon. The importers already exist and are tested
(`backend/stressless/connectors/`): Apple Health (Settings → Health → Export All Health Data), Google
Calendar (Settings → Import & export → Export) and Google Maps (Google Takeout → Location History, both the
monthly Semantic Location History files and the newer `Timeline.json`). Note that Vercel limits request
bodies to 4.5 MB, so large Apple Health exports will need direct-to-storage uploads.

## Optional: Claude writes the narrative

The narrative on the Morning view is written by a rule-based reasoner by default. To let Claude write it,
set `STRESSLESS_REASONER=claude` and `ANTHROPIC_API_KEY` (in `.env.local`, or in the Vercel project).

Only a de-identified summary is sent (score, causes, evidence text, sample size — never event ids,
times, locations or attendees). The model defaults to `claude-opus-5`; override with
`STRESSLESS_CLAUDE_MODEL`. Server-side refusal fallbacks are enabled by default. On any error the app
falls back to the rule-based reasoner, and the reasoner badge in the top bar always tells you which one
wrote the text. Claude-written narratives are cached per user in Supabase.

## Scripts

```bash
npm run dev            # Next.js + FastAPI with reload
npm run dev:next       # only Next.js (expects the API on :8000)
npm run dev:api        # only FastAPI (uv run uvicorn api.index:app --port 8000)
npm run build          # production build of the frontend
npm run typecheck      # TypeScript
npm run test:api       # Python test suite
npm run screenshots    # render every view with headless Chromium into docs/screenshots
```

## Project layout

```
app/                   Next.js App Router: login, /auth/confirm, and one route per view
components/            React views, SVG charts, app shell, presenter tour, overlays
lib/                   API client, Supabase clients, formatting, icons, navigation
styles/                the design system and per-view CSS
proxy.ts               session refresh and sign-in gate (Next.js 16 proxy)
api/index.py           Vercel entrypoint for the FastAPI app
backend/stressless/
  models.py            shared data model (dataclasses, JSON round-trip)
  timeutil.py          time conventions (nights, day-relative hours)
  sim/                 the digital twin: personas, calendar, location, physiology, sleep score, showcase
  connectors/          Apple Health, .ics and Google Takeout importers; demo sources
  store/               per-user state: Supabase (PostgREST) and in-memory stores
  engine/              features, baselines, matching, reality checks, attribution, habits, what-if,
                       suggestions, reasoning, pipeline
  server/              FastAPI app, Supabase JWT auth, per-request engine sessions
backend/tests/         unittest suite
supabase/migrations/   tables, row-level security and RPCs for per-user state
tools/                 screenshots (Playwright) and palette validation
```

## Known limitations

* One person's data: correlation, not proof — and the app says so on every report.
* The simulator is a caricature of a life. It is honest about its causal model (see Under the hood),
  but it is not a physiological model.
* The DST change night is off by one hour in durations.
* The demo dataset follows the calendar: when the day changes, each account gets a fresh dataset for
  the new date and its reality-check answers and accepted suggestions are cleared (set
  `STRESSLESS_ANCHOR` to keep one date).
* The calendar misses coffee, alcohol, screens and unbooked stress; the demo shows how the product
  copes with that rather than pretending otherwise.
