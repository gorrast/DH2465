# StressLess — DH2465

StressLess brings sleep, heart rate, calendar events, phone use and media history together to show
patterns in one person's recorded days. The app calculates the measurements and associations; an
optional Claude writer turns those results into daily and weekly reports.

The backend uses the signed-in user's synced/imported data by default. Health Connect data comes
through the Android app in `correlate-app/`; Google Calendar and supported media sources are connected
through **Connect Your Data**. `STRESSLESS_DATA=demo` enables the legacy simulated dataset for development
and tests. Missing measurements are unavailable, not zero, and connecting a source does not recover
history that the source never recorded.

## Current pages

| Page | What is displayed |
|---|---|
| Daily Report | Sleep score and rating, time asleep and wake time, a generated report, similar day patterns, sleep stages, HRV and resting heart rate, a BPM/calendar timeline, reality checks and a suggested change for tonight. |
| Weekly Report | Seven expandable statistics cards, a generated weekly report, a 1–4 week sleep calendar, meeting-load comparison, strongest pattern, the last seven nights and the recurring-pattern graph/table. |
| Connect Your Data | Health/phone connection instructions, Google Calendar connection, media imports and supported provider sync. |
| My Account | Account details, password changes and sign-out. |
| Data and Privacy | Data sources/classes, retention and import information, dataset information and deletion controls. Deletion requires typing `DELETE` and explicitly confirming; Cancel or Escape aborts it. |

Use the section arrows to move through long reports. The daily date arrows select another morning;
the sleep shown belongs to the preceding night. System reduced-motion preferences are respected.
Wrist temperature, respiratory rate, blood oxygen and a Maps connection are not displayed as measures
or connections in the current daily/privacy layout.

## Understanding the measures

### Units and terminology

| Label | Meaning and interpretation |
|---|---|
| bpm | Beats per minute: heart rate. An average summarizes recorded samples; a peak is the highest recorded sample, not a continuously observed maximum. |
| HRV, ms | Heart-rate variability, in milliseconds: variation in the time between heartbeats. It is different from heart rate. SDNN summarizes the spread of normal beat intervals; RMSSD summarizes successive interval differences. The real-data loader chooses SDNN or RMSSD according to which has more recorded nights (ties choose SDNN); these methods are not interchangeable. The displayed value comes from the stored measurement, rather than being inferred from the timeline's minute averages. |
| min; h | Minutes; hours. Sleep time counts time asleep, not simply time between going to bed and getting up. |
| pts | Sleep-score points on a 0–100 scale. A change of +5 points is not a 5% change. |
| % vs your usual | `100 × (value − baseline) / baseline`; unavailable when the baseline is missing or zero. |
| n; samples; sessions; plays | Counts of eligible nights, heart-rate readings, app sessions or media plays. They refer to the particular calculation, not necessarily all records in the account. |
| 95% interval | A bootstrap uncertainty interval from resampling the observed data. An interval spanning zero means that these data do not clearly separate a positive from a negative association. It does not cover every source of measurement error or confounding. |

### Sleep score and rating

This is **StressLess's own score**, not an Apple, Garmin or other watch manufacturer's score. The
Health Connect sync and Apple Health importer use the same scoring function. The weights are product
heuristics intended to summarize duration, regularity and continuity; they have not been clinically
validated. HRV, heart rate and calendar events are not direct inputs to this score.

The score is the rounded sum of three components, clipped to 0–100:

| Component | Calculation | Why it is included |
|---|---|---|
| Duration: up to 50 points | Let `r = clamp(asleep minutes / sleep need, 0, 1)`. Points are `50 × r^1.3`. Subtract 5 if sleep exceeds the need by more than 120 minutes; floor at zero. Device sync currently uses a fixed need of **450 minutes (7 h 30 min)**; simulated personas can have a different need. | Gives the largest weight to sufficient recorded sleep. Longer sleep stops accumulating points once the target is met. |
| Bedtime consistency: up to 30 points | Compare bedtime with the median of up to 14 earlier recorded bedtimes. For a later bedtime, subtract 0.25 points per minute beyond 20 minutes late. For an earlier bedtime, subtract 0.10 per minute beyond 30 minutes early. Floor at zero. With no earlier bedtimes, award 30. | Represents regularity while penalizing an earlier bedtime less heavily than a later one. |
| Continuity: up to 20 points | `max(0, 20 − 3 × interruptions − awake minutes / 8)`. | Represents wake-ups and time awake during the recorded sleep session. |

For example, 450 minutes asleep, a usual bedtime, two interruptions and 16 awake minutes gives
`50 + 30 + (20 − 6 − 2) = 92`, rated **High**. Parts are summed before rounding, so individually rounded
component values can differ slightly from the rounded total.

| Score | Rating |
|---|---|
| 0–40 | Very low |
| 41–60 | Low |
| 61–80 | OK |
| 81–95 | High |
| 96–100 | Very high |

For device sync, the longest eligible sleep session per night is used; sessions shorter than 60 minutes
are not scored. Time asleep is summed from asleep stages; interruptions are awake segments between the
first and last asleep segments. If only a session interval exists, its duration is treated as asleep and
awake minutes/interruptions are zero. This can make a score look better than incomplete stage data
justify. The stage visual shows source-provided stages, not stages predicted by StressLess.

Implementation: [sleep scoring](backend/stressless/sim/sleep_score.py),
[device session processing](backend/stressless/connectors/device_sync.py).

### Your usual, recovery markers and sleep stages

The sleep-score comparison and recovery cards use the median of up to **28 earlier eligible nights**
with that measurement. At least three values are needed. The current night is excluded from its own
baseline. A median reduces the influence of an unusually high or low night.

The sleep-score difference is `score − baseline score`. HRV normally shows a percentage difference;
resting heart rate shows an absolute difference in bpm. Neither comparison is a population benchmark.
The stage timeline, sleep onset, wake time and interruption count describe the source's recorded night.

Recovery status uses `z = (value − median) / max(1.4826 × MAD, 0.000001)`, where MAD is the median absolute
deviation from the median. This scales a change by the person's usual variability:

| Marker | `good` | `watch` | Otherwise |
|---|---|---|---|
| HRV | z ≥ 0.8 | z ≤ −1.0 | `typical` |
| Resting heart rate | z ≤ −0.8 | z ≥ 1.0 | `typical` |

Missing values/baselines produce `unknown`/building-baseline states. These are application labels based
on personal variation, not diagnoses or a rule that higher HRV/lower heart rate is always healthier.

Implementation: [baselines and recovery](backend/stressless/engine/baselines.py),
[real-data HRV selection](backend/stressless/connectors/real_data.py).

### BPM and Calendar events: Overview

The daily timeline aligns recorded heart rate and calendar events by time. The dotted **Your usual**
line is a separate time-of-day baseline, not the resting-heart-rate value on the recovery card:

1. Look back over 21 calendar days with heart-rate data.
2. Prefer days without late meetings or evening social events if at least ten such days exist;
   otherwise use all available days.
3. Mask workout periods and smooth each day's readings with a 21-minute rolling mean.
4. At each clock minute, take the median across days; require at least three contributing values.

This compares an evening reading with the person's usual reading at that time rather than with their
sleeping heart rate. Shading above the baseline highlights a measured difference; it does not establish
that a nearby calendar event caused it. Move the time slider or select an event to inspect readings.

Implementation: [heart-rate matching](backend/stressless/engine/matching.py).

### Similar day patterns in the daily report

The heading refers to recurring **calendar factors**, not a nearest-neighbour search for whole days
that look alike. The app pairs recorded sleep scores with features from the preceding day, such as
meeting load, back-to-back meetings, late meetings, workout timing, social events, travel, early starts
and protected evenings. Events marked not attended are excluded.

A ridge regression estimates each factor's association with sleep while accounting for the other
included calendar features. Ridge shrinks unstable estimates when features overlap; its penalty is
selected by leave-one-out prediction error. The model needs at least **10 scored nights**, and a factor
must occur on at least **three nights** to enter the fit.

For the selected day, a contribution is `factor coefficient × that day's feature value`. The displayed
list selects up to three negative contributions below −0.75 points; up to two positive contributions
over +0.75 appear as helpers. These contributions describe the fitted model, not measured causal losses
or a breakdown that must sum to the score difference from usual.

- **Similar nights** is the count of training nights where that factor was nonzero. They need not share
  the other features of the selected day.
- **Estimated range** comes from 500 moving-block bootstrap fits using blocks of five consecutive
  recorded nights. Blocks preserve some dependence between nearby nights.
- **Confidence** is low below 20 training nights or four occurrences. High requires at least eight
  occurrences, a coefficient interval excluding zero and an average active contribution of at least
  one point in magnitude. Otherwise, an interval excluding zero with at least four occurrences, or at
  least eight occurrences regardless of that interval, gives medium; the remainder is low.
- **Evidence** can show heart rate around an event, sleep duration or recovery measurements alongside
  the model estimate. These are supporting observations, not additional independent causal tests.

The generated written report can also discuss cross-source lifestyle links computed separately from
these calendar factors. Its narrative is not the source of the graph's numerical estimates.

#### Cross-source links in generated findings

The lifestyle engine normally examines the preceding **56 days**, splitting days with/without a habit
or above/below a personal threshold. Numeric thresholds often use the person's upper or lower third of
days; categorical activities use occurrence rules. It normally needs 14 measured days for a cause
(10 for manually logged check-ins) and at least four observations on each side for an outcome.

It compares eligible sleep, recovery, activity, phone-use or daytime-heart-rate outcomes, stratified by
work/weekend day or night as appropriate. There are 400 bootstrap resamples. A reportable **strong**
link must meet its outcome-specific minimum effect, have a 95% interval excluding zero and medium/high
confidence. An **early hint** can instead have an 80% interval excluding zero and is always labelled
low confidence; some activity comparisons disallow hints. The thresholds are filters for what to tell,
not a correction for testing many possible links.

Steps are daily recorded totals; days below 100 recorded steps are omitted from these lifestyle tests
as a phone-not-carried proxy. Daytime heart rate is averaged over 08:00–22:00, excluding workouts and
30 minutes afterward, and needs at least 240 measured minutes. Phone pickups/unlocks are recorded
counts, with per-hour rates where a finding compares activities of different lengths. Media minutes
come from records with usable duration; missing duration is not inferred for an arbitrary provider.
Coffee/alcohol values come from user check-ins. These rules reduce misleading comparisons, but remain
observational; the writer may omit weak, redundant or implausible links.

Implementation: [daily attribution](backend/stressless/engine/attribution.py),
[calendar features](backend/stressless/engine/features.py),
[report inputs](backend/stressless/engine/report_input.py).

### Tonight's suggestion and reality check

Suggested calendar changes are evaluated with the fitted model before and after the proposed change.
The estimated point change and bootstrap range describe a model prediction, not a promised benefit.
An accepted suggestion can be saved/downloaded as a calendar event.

Reality checks let a user confirm whether an activity happened when available evidence disagrees with
its booking. Answers update which events enter the analysis and refresh the daily report's underlying
data. They do not automatically rewrite an already saved generated narrative.

Implementation: [suggestions](backend/stressless/engine/suggestions.py),
[reality checks](backend/stressless/engine/reality.py).

## Understanding the weekly page

### Calendar, averages and meeting load

The sleep calendar shows **1, 2, 3 or 4 weeks**. Its average is the arithmetic mean of available scored
nights in the selected range; missing nights are excluded, rather than treated as zero. Selecting a
night opens its daily report. The last-seven-nights cards show each night's score and recorded factors.

The meeting-load chart uses the **last four weeks**, restricted to work nights, grouped into **0–2,
3–4 and 5+ meetings**. Each bar is the mean sleep score after days in that group. Whiskers are 95%
bootstrap intervals for that mean (600 resamples; at least three nights are needed for an interval).
They express uncertainty in the mean, not a range containing 95% of individual scores. The accompanying
headline compares the heavy-meeting group with the calm group.

The calendar range buttons change the calendar and its displayed average; they do not change the
meeting-load window or restrict the recurring-pattern model to that range.

### Your recurring patterns: Effect on sleep score

This graph uses eligible recorded history before the selected end date, not just the seven days of the
weekly narrative. For each habit it compares sleep after days **with that habit** against sleep after
all other days **without that habit**. It is not a direct comparison between the named bars.

Except for the weekend-night habit itself, calculate the difference separately for work nights and
weekend nights (Friday/Saturday), then combine usable groups weighted by their numbers of nights with
the habit. A group contributes only when both with-habit and without-habit nights exist. This reduces
weekend scheduling bias but does not remove other confounding.

| Graph element | Calculation and meaning |
|---|---|
| Colored bar and pts | Weighted mean score difference, with minus without. Positive means higher observed sleep scores; negative means lower. Bars are ordered most negative to most positive. |
| Whisker | 2.5th–97.5th percentiles from 800 bootstrap resamples within those groups. |
| Diamond: adjusted (model) | Ridge coefficient × average nonzero feature value, where a corresponding regression factor exists and the model has enough history. It accounts for other included model features. Evening workouts and calm workdays have no corresponding model factor, so no diamond. |
| Confidence | High: interval excludes zero and both groups have ≥10 nights. Medium: both have ≥6 and the interval excludes zero, or both have ≥12 regardless of the interval. Otherwise low. These rules differ from daily attribution confidence. |
| Table view | Shows counts with/without, the bar estimate, interval, adjusted estimate and confidence. |
| Model nights; out-of-sample R² | Number of scored nights in the regression and its leave-one-out `1 − prediction error / variation around the mean`, clipped to 0–1 and shown as a percentage. This assesses prediction against a mean-only reference; it is not a percentage of sleep caused by the calendar. |

The **Strongest pattern** summary uses a separate conservative ranking: the interval endpoint nearest
zero when it excludes zero, otherwise one quarter of the absolute estimate, multiplied by confidence
weights (high 1, medium 0.7, low 0.4). It selects the first non-low-confidence, non-neutral pattern;
absolute effects below 1.5 points are treated as neutral.

A large bar with few nights can be unstable. Opposite signs for evening and late workouts can reflect
different comparison groups and co-occurring activities. They do not prove that later exercise is
better for sleep.

Implementation: [recurring patterns and meeting buckets](backend/stressless/engine/habits.py),
[effect graph](components/charts/analysis.tsx).

### Calendar habit definitions

| Habit | Rule |
|---|---|
| Late meetings | A meeting ends after 18:00; the model feature is hours beyond 18:00. |
| Heavy meeting days | At least five meetings; the regression uses the number beyond three. |
| Back-to-back blocks | At least three consecutive meetings, with gaps of at most ten minutes; the model uses the chain length beyond two. |
| Evening social | Social event ends at or after 20:30. |
| Morning workouts | Starts before 10:00 and does not satisfy the late rule. |
| Evening workouts | Starts at or after 17:00 but before 19:30, and ends more than two hours before usual bedtime. |
| Late workouts | Starts at or after 19:30 **or** ends at/after usual bedtime minus two hours. The late rule takes precedence. |
| Travel | A recorded travel event. |
| Early starts | A meeting, travel or personal event starts before 07:30; an early run alone does not count. |
| Protected evenings | A protected block overlapping 20:00–23:00, or an event title matching wind-down/no-meetings/recovery/screen-free. |
| Calm workdays | At most two meetings on a work night. |
| Weekend nights | Friday and Saturday nights, before the weekend's non-workdays. |

The last-starting workout determines that day's workout category if there is more than one. “Usual
bedtime” for this classification is the dataset/persona value; it is distinct from the rolling median
used to score bedtime consistency. Different cross-source report analyses may have their own definitions;
for example, the lifestyle engine's late-workout link uses workouts ending at or after 20:00.

### Your week in numbers: the seven statistics cards

These cards query the signed-in user's stored records through Supabase functions. Their windows differ
and are printed on the cards; **not every card is limited to the last week**. A missing overlap with
heart-rate samples produces no measured response, not a score of zero.

| Card | Calculation and purpose |
|---|---|
| Your most-used apps | Sum positive recorded app-use minutes per package over the last seven days; show the top five. Describes recorded use, not estimated attention. |
| Apps that get you going | Score each app session with at least two overlapping HR samples using the response formula below, then average session scores per app. Also show peak session score, mean of session-average bpm, maximum bpm, measured-session minutes and count. Uses all recorded sessions. |
| Your liveliest events | Apply the same response formula to each recorded calendar event with at least two overlapping HR samples; rank events by score. Shows average/minimum/maximum bpm and sample count. Uses all recorded events. |
| Songs that move you | Use Spotify playback intervals ending at the recorded play timestamp, with at least 30 seconds of recorded duration and one overlapping HR sample. Average response scores by title/artist; show average bpm, peak, difference from resting baseline and eligible play count. Uses all recorded plays. |
| Find your flow | Consider completed calendar events in the last 30 days with at least two HR samples. Rank first by lowest mean bpm, then lowest population standard deviation in bpm, then least overlapping app-use minutes, then fewest unlocks, then newest start. Show five candidates. Screen minutes are summed overlap durations; app sessions/unlocks are counts. This is an ordered observational ranking, not a validated flow-state detector. |
| Your Cardiac Wrapped | Last seven days: the highest response-scored Spotify track, plus “Cardiac Anthem” (largest first-to-peak playback HR rise on a day with ≤2,000 recorded steps), “True Calmer” (artist-play average below non-Spotify HR), and “Focus Cadence” (lowest population HR standard deviation during Spotify/focus-event overlaps). Sample/play counts and comparison bpm accompany these values. Low daily steps are only a stationary proxy; non-Spotify time is not verified silence. |
| Meeting Hangover Index | Completed meetings in the last 30 days, ending at least three hours ago. Drift = mean bpm in the three hours after the meeting − mean bpm in the hour before it; require ≥2 post-meeting samples and ≥1 pre-meeting sample. Rank by largest drift. That night's resting-HR and deep-sleep changes are differences from the means of the preceding 30 calendar days. Other activities during the comparison windows can explain the difference. |

For app/event/song response scores, let `R` be mean recorded resting HR over the last 14 days (fallback
65 bpm), `A` mean HR during the session/event/play, `P` its maximum, and `S` its first recorded HR.
With `clip(x) = min(100, max(0, x))`:

```text
response = 0.50 × clip(100 × (A − R) / 30)
         + 0.30 × clip(100 × (P − (R + 10)) / 35)
         + 0.20 × clip(100 × (P − S) / 20)
```

The result is clipped to 0–100. The formula weights sustained elevation, a high peak, and a rise during
the recorded interval. It is a heuristic response/arousal index: higher is not better health, enjoyment
or proof of stress. Its mean-RHR baseline is different from the recovery cards' 28-night median. The
“bpm variation” shown in flow/music cards is standard deviation of bpm samples, **not beat-to-beat HRV
in milliseconds**.

Implementation: [app aggregation](components/views/useAppStatistics.ts),
[statistics card presentation](components/views/FunStatistics.tsx), and the versioned
[Supabase SQL functions](supabase/migrations/) (`20261027000002`–`20261027000008`; apply in order so the
latest function definitions are used).

## Written reports and Claude

Daily reports describe the preceding night/day. The weekly written report covers the **last complete
Monday–Sunday week**, with baseline metrics from the preceding history. This is separate from the
rolling statistics-card windows and sleep-calendar range.

The engine computes scores, baselines, calendar contributions and cross-source lifestyle associations
before the writer runs. Claude receives a structured report input and writes the headline, summary,
findings and suggestion; it does not calculate or replace the underlying chart values.

By default reports use the rule writer. To enable Claude, set these server-side variables in
`.env.local` locally and in the deployment environment:

```env
STRESSLESS_REASONER=claude
ANTHROPIC_API_KEY=your_api_key
# Optional: override the configured model for either report kind.
# STRESSLESS_DAILY_MODEL=your_model_id
# STRESSLESS_WEEKLY_MODEL=your_model_id
# STRESSLESS_REPORT_EFFORT=medium
```

Restart the backend after changing environment variables. The Anthropic Python package must be installed.
Real-data reports require consent to send the report input. The app uses rules if Claude is disabled,
consent is missing, the rolling 24-hour report limit is reached (default 50), a pending generation becomes
stale, or the model request fails/returns unusable content. API failures are logged by the backend.

**Written by …** and **Written without AI** reflect the saved report's actual writer. Reports are saved
per period and reused; enabling Claude does not rewrite an existing rule-generated report. Development
servers expose regeneration; production does not. The older internal morning narrative remains
rule-based and is separate from the generated report card.

Implementation: [generation and storage](backend/stressless/server/reports.py),
[writers](backend/stressless/engine/report_writer.py),
[lifestyle links](backend/stressless/engine/lifestyle.py).

## Architecture

```text
Browser → Next.js pages/components → /api/* → FastAPI
   └──────── Supabase Auth + user-scoped statistics RPCs
FastAPI → authenticated user store → synced/imported records → analysis → optional report writer
Android Health Connect sync → FastAPI → stored sleep/heart-rate/activity records
```

Supabase Auth identifies each user. Database row-level security isolates their records. Server-only
provider keys and the Anthropic key are not sent to the browser. Imported media are stored as normalized
records rather than keeping uploaded files. The optional simulated dataset supports testing; it is not
a substitute for missing real measurements.

## Setup

Requirements: Node.js 20+, [uv](https://docs.astral.sh/uv/) (Python 3.12) and a Supabase project.

1. **Supabase.** Create a project and apply the migrations in `supabase/migrations/` in timestamp order
   (or use `supabase db push` with the Supabase CLI), including the phone-sync and statistics functions. Under Authentication → URL
   Configuration, set the Site URL to your deployed URL and add `http://localhost:3000/**` and
   `https://<your-app>.vercel.app/**` to the redirect URLs. Email confirmation stays on: new accounts
   confirm their address through the link in the email, which lands on `/auth/confirm`.
2. **Environment.** `cp .env.example .env.local` and fill in `NEXT_PUBLIC_SUPABASE_URL` and
   `NEXT_PUBLIC_SUPABASE_ANON_KEY` (Project Settings → API). Projects that still use the legacy
   JWT secret also need `SUPABASE_JWT_SECRET`; projects on asymmetric signing keys (the default) do not.
   The Google Calendar connection needs five more server-side variables (`APP_URL`,
   `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_TOKEN_ENCRYPTION_KEY`, `SUPABASE_SERVICE_ROLE_KEY`; see
   `.env.example`) and `<APP_URL>/api/calendar/google/callback` registered as a redirect URI on the Google
   OAuth client. Without them the rest of the app works and the connection reports it is not configured.
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
"today" for a presentation, set `STRESSLESS_ANCHOR` to the desired `YYYY-MM-DD` — the backend uses a fixed
analysis date. Statistics RPCs using database `now()` retain their real-time windows; the anchor does not freeze those cards.

## Bring your own data

Use **Connect Your Data** for media histories, library browsing, imports and optional sync.
Import/sync stores provider records; viewing those histories does not itself generate a Claude report.
The weekly statistics and generated reports analyze eligible stored data separately.

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
4 MB combined, except the larger YouTube allowance below). Overlapping records in the same import are deduplicated. A Steam import replaces its previous
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

   Each user then connects their own account under Connect Your Data → Last.fm: they create a Last.fm account, enable
   [Spotify scrobbling](https://www.last.fm/about/trackmymusic), keep their recent listening public and enter
   their username. The API checks the username with Last.fm and keeps it in the user's `lastfm_sync` document.
   **Disconnect** deletes that document and the user's saved scrobbles, so two Last.fm accounts never mix.
3. Apply `supabase/migrations/20261022133929_lastfm_media_sync.sql` in Supabase's SQL editor (or your normal
   migration workflow). It extends the `media_events` provider constraint and the existing atomic import RPC.
   Last.fm events merge by a stable ID; file histories keep their replacement behavior. Sync progress is a
   `lastfm_sync` document in `media_documents`. Existing media remains intact.
4. Restart `npm run dev`, reload Connect Your Data and click **Sync now** in Last.fm under Listening. Each request reads
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
does not recover listening Last.fm never recorded. Sync runs on button presses, without generating a report or scheduled polling.
Stored listening records can subsequently contribute to analysis.

### Steam Sync now (your own account)

1. Sign in locally and open **Connect Your Data → Steam → Set up Steam sync**. Copy **Your app user ID**.
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
6. Reload Connect Your Data, go to Steam, and click **Sync now**. The games, playtime and
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
combined limit will need a future chunked-upload flow. Importing does not itself generate a report; stored history is available to the analysis pipeline.

## Scripts

```bash
npm run dev            # Next.js + FastAPI with reload
npm run dev:next       # frontend; expects the API on :8000
npm run dev:api        # backend; loads .env.local
npm run build          # production frontend build
npm run typecheck      # frontend TypeScript checks
npm run test:api       # backend unit/integration tests
npm run screenshots    # authenticated browser screenshots; needs Playwright Chromium
```

## Project layout

| Path | Purpose |
|---|---|
| `app/`, `components/`, `styles/`, `lib/` | Next.js routes, UI, charts and browser helpers. |
| `backend/stressless/connectors/` | Device sync, stored real-data loading and source importers. |
| `backend/stressless/engine/` | Scoring inputs, baselines, matching, attribution, recurring/lifestyle patterns and report writers. |
| `backend/stressless/server/`, `api/index.py` | Authenticated FastAPI routes and deployment entrypoint. |
| `backend/stressless/store/`, `supabase/migrations/` | User storage, RLS and database statistics functions. |
| `correlate-app/` | Companion Android app for health/phone sync. |
| `backend/tests/` | Backend tests. |
| `backend/stressless/sim/` | Optional legacy demo/test data and shared sleep-score function. |

## Limits when interpreting the page

- These are within-person associations from recorded history. Scheduling, exercise, missing records and
  other unmeasured factors can explain a link. An adjusted model does not establish causation.
- Sleep scores and response/arousal indices are application heuristics, not clinically validated measures.
  Source devices can misclassify stages or miss readings; the app cannot repair missing measurements.
- Different cards intentionally use different windows, baselines and confidence rules. A weekly narrative,
  a rolling 30-day card and an all-history recurring pattern need not agree numerically.
- The calendar cannot observe everything affecting sleep. Check-ins and supported cross-source records
  add context but do not measure every possible influence.
- Some legacy backend/importer capabilities remain outside the current navigation. They are not presented
  here as current pages or connection options. Detailed historical design notes in `docs/SPEC.md` can lag
  the shipped UI; the linked implementation files are the reference for calculation details.
