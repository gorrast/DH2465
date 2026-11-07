# Project Course DH2465

# StressLess

> Wearables give you a score. They don't tell you why.

Your watch tells you that you slept badly and that your HRV is down. It does not tell you that it happens after
a particular meeting, that the evenings you watch an episode of something light after a long day go with deeper
sleep, or that you reach for your phone more the day after a short night. That knowledge sits spread across
apps that never talk to each other.

**StressLess connects them.** It brings the biometrics your watch already collects (sleep, heart rate, HRV,
steps) together with the rest of your life: your calendar, workouts, the music, podcasts and shows you play,
your phone use, and quick coffee and alcohol check-ins. Then it looks for the links in your own history:

* **which meetings weigh on you**: your heart rate in each recurring meeting against your other meetings that
  day, and whether a meeting stays with you into the evening and the night;
* **what helps you recover**: the activities, evenings and habits that go with deeper sleep and a calmer heart;
* **what happens around your phone**: focus music that cuts pickups during deep work, more screen time after a
  short night;
* **how your week fits together**: your best and hardest days, and what to keep or try next week.

Every morning a **daily report** explains last night through what happened yesterday, and every Monday a
**weekly report** looks back over the week. The statistics are computed by StressLess's own engine; a language
model (Claude) only chooses which links are worth telling and puts them into plain words, citing the numbers
each finding rests on. Everything is a comparison within one person's data: StressLess says "goes with" and
"tends to", never "caused".

### Try it

The running site has a public project page (process, product, team) and a **demo version**: one click on
**Try the demo** opens the app on a shared demo account, read-only, so every visitor sees the same data.

## Architecture

```
browser ──► Next.js (app/, components/)     React views, charts, tour; Supabase Auth session in cookies
   │            proxy.ts                    refreshes the session; / → /project; signed-out → /auth/demo
   │            app/auth/demo/route.ts      server-side sign-in to the demo account (service-role key)
   └─ /api/* ─► FastAPI (api/index.py → backend/stressless)
                    verifies the Supabase JWT, loads the user's data, runs the engine, writes the reports
                    └─► Supabase Postgres (PostgREST)    synced and imported data, calendar, media, check-ins,
                                                         reports, per-user state — row-level security per user
```

With `STRESSLESS_DATA=real` (the default) the API reads each user's own rows: what the phone app synced (sleep,
heart rate, steps, screen time), the calendar, imported media and check-ins
(`backend/stressless/connectors/real_data.py`).

## Setup

Requirements: Node.js 20+, [uv](https://docs.astral.sh/uv/) (Python 3.12) and a Supabase project.

1. **Supabase.** Apply the migrations in `supabase/migrations/` in order (SQL editor, or `supabase db push`).
2. **Environment.** `cp .env.example .env.local` and fill it in (see the table below).
3. **Demo account.** Create the user in Supabase (Authentication → Users) and put its email in `lib/demo.ts`.
4. **Install and run.**

   ```bash
   npm install
   uv sync
   npm run dev          # Next.js on http://localhost:3000 and FastAPI on :8000 (proxied under /api)
   ```

5. **Tests.** `npm run test:api` runs the Python suite (engine, simulator, links, reports, connectors, API with
   an in-memory store); `npm run typecheck` checks the frontend.

### Environment variables

| Variable | Where | What |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` | both | the Supabase project (Project Settings → API) |
| `SUPABASE_SERVICE_ROLE_KEY` | server | the demo sign-in (`/auth/demo`) and server-side writes (phone sync, check-ins, calendar). Never `NEXT_PUBLIC_` |
| `STRESSLESS_READ_ONLY` | server | `true` for the shared demo: the API refuses every change except asking for a report, and the UI hides what would fail |
| `STRESSLESS_ANCHOR` | server | freezes "today" for every account (`YYYY-MM-DD`), for a stable demo or presentation |
| `ENVIRONMENT` | server | `PROD` on Vercel. Anything else is a dev server, where a stored report can be generated again |
| `STRESSLESS_REASONER`, `ANTHROPIC_API_KEY` | server | `claude` and a key let Claude write the reports; otherwise rules do. Models: `STRESSLESS_DAILY_MODEL`, `STRESSLESS_WEEKLY_MODEL`; cap on model calls per 24 h: `STRESSLESS_REPORT_DAILY_CAP` |
| `SUPABASE_JWT_SECRET` | server | only for projects on the legacy JWT secret |
| `LASTFM_API_KEY`, `TMDB_READ_ACCESS_TOKEN`, `STEAM_*`, `GOOGLE_*`, `APP_URL` | server | optional integrations, below |

## Deploy to Vercel

Import the repository in Vercel (framework: Next.js). `api/index.py` becomes a Python function serving `/api/*`
with the packages from `requirements.txt`; `vercel.json` keeps the frontend out of its bundle. Set the variables
above for Production and Preview; `SUPABASE_SERVICE_ROLE_KEY` is used by both the Next.js and the Python side.

## What you are looking at

| Page | What it shows |
|---|---|
| Project (`/project`) | The course project: process, product and team, and the way into the demo |
| Daily Report (`/daily`) | Last night's sleep score, stages and recovery markers (HRV, resting heart rate), similar-day patterns, the day's heart rate against the calendar, a reality check, one change for tonight, and the daily report: the links behind last night |
| Weekly Report (`/weekly`) | The weekly report, your week in numbers (apps, events and songs by heart rate, flow, meeting hangover), the sleep calendar, sleep by meeting load, and your recurring patterns |
| Connect Your Data (`/connect`) | Spotify, Netflix, YouTube and Steam histories, imports and Last.fm/Steam sync |
| Data and Privacy (`/data`) | What is connected, which data is read and why, deleting everything |
| My Account (`/account`) | Who is signed in, theme, leaving the demo |

Press `t` for the presenter tour; `d` switches light/dark theme, `?` lists the keys.

## How the reports work

1. **Links** (`engine/lifestyle.py`). Each cause (a recurring meeting, an artist, a workout, late screen time, a
   short night, a show after a busy day, …) is split into days with and without it, stratified by weekend, and
   compared on what follows: sleep score, time asleep, sleep onset, HRV, resting heart rate, deep sleep, the next
   day's steps and screen time, daytime heart rate, and the heart rate or phone pickups during an activity. A
   bootstrap interval decides whether a link is strong, an early hint, or nothing.
2. **The report input** (`engine/report_input.py`). The links whose cause happened in the period, with their
   numbers, next to the period's metrics against the person's usual. Obvious links (late phone use, alcohol,
   coffee, steps, a late night out, …) are left out, and so is what the Daily page already shows. The daily
   report gets yesterday's links; the weekly report gets the week's, minus those today's daily report told.
3. **The writer** (`engine/report_writer.py`). Claude (with `STRESSLESS_REASONER=claude`) or the rule writer turns
   the input into a headline, a summary and two to four findings. It only words what the engine computed: every
   finding cites the links it rests on, and the page shows their computed values next to it.
4. **Once per period.** A report is claimed in the database before the model is called, stored, and returned as
   is from then on (`server/reports.py`).

The daily causes behind last night (`engine/attribution.py`, a within-person ridge regression over calendar
features with leave-one-out validation) are shown on the Daily page as similar-day patterns.

## Bring your own data

On an account of your own (not on the read-only demo), Connect Your Data imports and syncs media history.

The Media tab has separate Spotify, Netflix and Steam sections, with scrollable histories, library browsing,
and the Morning view's typography and section reveals. It displays imported data without requesting media
insights, statistical correlations, or Claude analysis.

- **Spotify:** import music/podcast history JSON, including Extended Streaming History. Taste Profile,
  Your Library and Wrapped summaries are also supported. Select history files together.
- **Netflix:** download Viewing activity from each Netflix profile and select the CSVs together.
  `Title,Date` exports accept `M/D/YY`, `M/D/YYYY`, and ISO dates. Each filename labels its profile;
  keep filenames stable when reimporting. Missing titles remain visible as “Title unavailable”. Dates
  carry no time of day, and duration is unavailable unless the CSV supplies `Duration` as `HH:MM:SS`.
- **Steam:** import one JSON response from [GetOwnedGames or GetRecentlyPlayedGames](https://partner.steamgames.com/doc/webapi/IPlayerService).
  Request `include_appinfo=true` for GetOwnedGames to include names. Both the full `{ "response": { "games": [...] } }`
  envelope and `{ "games": [...] }` work. Displayed playtime is in-game cumulative minutes, converted to hours;
  snapshots do not supply individual play sessions. Library search and sorting happen locally.
  Steam can also refresh directly using **Sync now** after the setup below. Scheduled sync is not enabled.

History imports replace that provider's history; choose all files to retain in one import (up to 20 files,
4 MB combined). Overlapping records in the same import are deduplicated. A Steam import replaces its previous
library snapshot. The server discards the original uploads and persists normalized history in `media_events`
and summaries/snapshots in `media_documents`, protected by per-user row-level security. Apply migrations,
including `20261022000000_steam_library_import.sql`, before using Steam imports against Supabase.

Last.fm provides ongoing listening history through its official API. Its scrobbles are displayed separately
from Spotify exports to avoid adding overlapping play counts together. No playback duration is inferred.

### Last.fm listening and artwork

1. Create a [Last.fm API account](https://www.last.fm/api/account/create) for the app. One API key serves every
   user; no shared secret, authentication callback or Spotify developer application is needed.
2. Set the server-only variable in `.env.local` (and in the Vercel project's environment variables):

   ```env
   LASTFM_API_KEY=your_lastfm_api_key
   ```

   Each user then connects their own account under Media → Last.fm: they create a Last.fm account, enable
   [Spotify scrobbling](https://www.last.fm/about/trackmymusic), keep their recent listening public and enter
   their username. The API checks the username with Last.fm and keeps it in the user's `lastfm_sync` document.
   **Disconnect** deletes that document and the user's saved scrobbles, so two Last.fm accounts never mix.
3. Apply `supabase/migrations/20261022133929_lastfm_media_sync.sql` in Supabase's SQL editor (or your normal
   migration workflow). It extends the `media_events` provider constraint and the existing atomic import RPC.
   Last.fm events merge by a stable ID; file histories keep their replacement behavior. Sync progress is a
   `lastfm_sync` document in `media_documents`. Existing media remains intact.
4. Restart `npm run dev`, reload Media and click **Sync now** in Last.fm under Listening. Each request reads
   up to 200 completed scrobbles. **Load older listening** pages through older history. **Continue sync** appears
   when a large new-listening backlog needs another batch; fixed time windows keep new tracks from shifting
   those pages. Repeating a sync does not duplicate saved scrobbles. Now-playing tracks are not saved as plays.

Album artwork is displayed in the featured latest listen and history thumbnails. Safe HTTPS image URLs from
Last.fm's image CDNs are used directly. If a track has no artwork, a visible cover triggers a cached
`album.getInfo` lookup through the authenticated backend. Repeated album lookups share requests and are paced;
missing or broken covers fall back to a music icon. Listening data/artwork link back to Last.fm.

Last.fm calls use your server-side key and are limited to the configured app user. API errors preserve saved
history and paging progress; no credentials are returned to the browser. Username changes are rejected while
history for a different username is saved. Scrobbles have no exact listening duration, and enabling scrobbling
does not recover listening Last.fm never recorded. Sync runs on button presses, without Claude, statistical
analysis or scheduled polling.

### Steam Sync now (your own account)

1. Sign in locally and open **Media → Steam → Set up Steam sync**. Copy **Your app user ID**.
   This is your Supabase Auth UUID; it is also listed under Supabase → Authentication → Users.
2. Register a personal [Steam Web API key](https://steamcommunity.com/dev/apikey) and find your **SteamID64**
   (17 digits, not your login name or custom profile URL). Check your Steam account details for the Steam ID.
3. Under Steam → Edit Profile → Privacy Settings, make **My profile** and **Game details** public.
   To expose playtime, also disable “Always keep my total playtime private”.
4. Add these server-only variables to the existing `.env.local`:

   ```env
   STEAM_WEB_API_KEY=your_personal_steam_api_key
   STEAM_ID=your_17_digit_steam_id
   STEAM_SYNC_USER_ID=your_supabase_auth_user_uuid
   ```

5. Apply `supabase/migrations/20261022000000_steam_library_import.sql` if it has not already been applied.
   No additional migration is needed for the button. Restart `npm run dev` so the backend reloads `.env.local`.
6. Reload [Media](http://localhost:3000/media), go to Steam, and click **Sync now**. The games, playtime and
   last-synced timestamp update after the snapshot is saved. Errors leave the previous snapshot intact.

The configured Steam library can only be synced by `STEAM_SYNC_USER_ID`. The API key is sent to Steam in
the `x-webapi-key` header, never returned to the browser or persisted in `media_documents`. No service-role
key, Claude key, statistical-engine connection or scheduler is required. This is a personal server-side
configuration; other users can continue to import their own files. Both `media_events` and `media_documents`
remain in use. Steam sync updates its snapshot in `media_documents` without changing Spotify or Netflix data.

### Automatic Netflix and Steam artwork

Steam imports and Sync now attach official header-image URLs using each game's app ID. Game cards display
these images automatically; missing/removed artwork keeps the existing gamepad placeholder. No new Steam
credential, image upload or database migration is needed for Steam artwork. Sync/import once to populate old
snapshots with the new image URLs.

Netflix's CSV does not include artwork. StressLess can fetch series/movie posters from TMDB automatically
after a successful import:

1. Create a [TMDB API account](https://www.themoviedb.org/settings/api) and copy its **API Read Access Token**
   (the Bearer token, not the shorter v3 API key).
2. Add `TMDB_READ_ACCESS_TOKEN=...` to `.env.local`. Optionally set `TMDB_LANGUAGE=sv-SE` (the default).
3. Apply `supabase/migrations/20261022142351_netflix_artwork.sql`. It adds a user-scoped RPC/index to patch
   poster metadata in `media_events.source` while preserving titles, dates, profiles and all other records.
4. Restart `npm run dev` and import all Netflix CSVs together. Existing uploads need one reimport to attach
   catalogue lookup keys. No individual images need to be supplied.

After the history is saved, the import UI automatically processes small poster batches and displays progress.
Episodes share a show lookup/poster. Exact normalized titles and original titles are matched; ambiguous titles,
remakes without a distinguishing year, missing covers and unknown titles remain placeholders. Only title search
queries are sent to TMDB, without viewing dates or profile filenames. Requests are cached and credentials stay
on the server. **Fetch missing posters** resumes interrupted work; no metadata lookup starts just by opening
the page. Network/API failures do not discard imported history. TMDB attribution is displayed under Netflix.

The original health and calendar importers already exist and are tested
(`backend/stressless/connectors/`): Apple Health (Settings → Health → Export All Health Data), Google
Calendar (Settings → Import & export → Export) and Google Maps (Google Takeout → Location History, both the
monthly Semantic Location History files and the newer `Timeline.json`). Note that Vercel limits request
bodies to 4.5 MB, so large Apple Health exports will need direct-to-storage uploads.

### YouTube watch-history import

YouTube imports default to the last 90 days, with a choice of 30 days or all history. Every choice is capped
at the latest 5,000 unique viewing entries across the selected files, before the Supabase write. The result
shows imported and skipped counts. Empty date selections preserve existing history. This limits bulk-write
cost without changing database execution timeouts; the earlier YouTube provider migration is still required.

Apply `supabase/migrations/20261023000000_youtube_media_import.sql` after the existing media migrations.
This extends the media provider constraint and atomic replacement RPC; it keeps using `media_events`.
No YouTube API key or OAuth setup is needed. In Media, below Netflix, open **Import YouTube JSON** and
upload the extracted Google Takeout `watch-history.json`. Select all parts together for split exports:
each successful import replaces only YouTube history. Invalid or search-only uploads preserve existing data.

Viewing entries include exported timestamps (displayed in the browser's local timezone), channel names
when present, canonical video links, and lazy YouTube thumbnails with icon fallbacks. Actual watch duration
is unknown and is not inferred from video runtime. Search/channel activity is excluded. Exact duplicate
entries are deduplicated, while repeat views at different timestamps are retained.

The backend accepts up to 32 MB total for YouTube JSON (other sources remain 4 MB). Your hosting provider
may enforce a smaller request-body limit; if so, split a large JSON array into valid smaller arrays and
select the parts together within that deployment's limit. Larger histories exceeding the deployment's
combined limit will need a future chunked-upload flow. No AI or statistical analysis is connected.

## Scripts

```bash
npm run dev            # Next.js + FastAPI with reload
npm run dev:next       # only Next.js (expects the API on :8000)
npm run dev:api        # only FastAPI (uv run uvicorn api.index:app --port 8000)
npm run build          # production build of the frontend
npm run typecheck      # TypeScript
npm run test:api       # Python test suite
uv run python tools/report_try.py daily --help    # build a report input and optionally call Claude
```

## Project layout

```
app/                   Next.js App Router: the project site (/project), /auth/demo, and one route per view
components/            React views, SVG charts, app shell, presenter tour, project site, overlays
lib/                   API client, Supabase clients, the demo account, formatting, icons, navigation
styles/                the design system and per-view CSS
proxy.ts               session refresh, / → /project, signed-out visitors → the demo (Next.js 16 proxy)
api/index.py           Vercel entrypoint for the FastAPI app
backend/stressless/
  models.py            shared data model (dataclasses, JSON round-trip)
  reports.py           report input and content schemas
  timeutil.py          time conventions (nights, day-relative hours)
  sim/                 simulated data for the tests: calendar, physiology, sleep score
  connectors/          real data from Supabase, phone sync, Apple Health, .ics, Google Takeout, media importers
  store/               per-user state: Supabase (PostgREST) and in-memory stores
  engine/              features, baselines, attribution, links (lifestyle), report input and writer, habits,
                       reality checks, what-if, suggestions, pipeline
  server/              FastAPI app, Supabase JWT auth, read-only guard, reports, sync and check-in routes
backend/tests/         unittest suite
supabase/migrations/   tables, row-level security and RPCs
tools/                 scripts: report try-out, screenshots, palette validation and more
```

## Known limitations

* One person's data: correlation, not proof, and the reports say so.
* Read-only is enforced by the API; a visitor with browser devtools could still write to the few tables
  row-level security lets a signed-in user write.
* `npm run screenshots` (`tools/screenshots.mjs`) still signs in through `/login`, which the demo-only site no
  longer has.
* Vercel limits request bodies to 4.5 MB, so large Apple Health exports would need direct-to-storage uploads.

