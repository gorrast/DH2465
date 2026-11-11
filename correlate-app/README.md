# StressLess Android app

A Capacitor app around a plain web dashboard (`www/`). It reads what the watch writes to Health Connect and how the
phone is used, and syncs both to the StressLess API. The analysis and the reports live in the web app and the
backend. An iOS app is planned; until then iPhone data comes in through the Apple data importer
(`tools/apple-data`).

## One-time setup

```bash
cd correlate-app
npm install
npx cap sync
```

## Android — install on your own phone, completely free

Requires Android Studio.

```bash
npx cap open android
```

Plug in your Android phone via USB with USB debugging enabled, select it as the run target and hit Run. The
Health Connect and usage-access permissions are declared in `AndroidManifest.xml`; the app asks for them on first
use.

To distribute to other testers before a public launch, Play Console's
**internal testing track** needs only a one-time $25 developer account fee,
no review.

## Sign in & Sync (sleep, heart rate, HRV, steps, screen time → Supabase)

The **Account & sync** card signs in with the same Supabase email/password account as the web app
(`www/auth.js`, plain Supabase Auth REST calls). **Sync** re-reads the phone's data and POSTs it to the
StressLess API (`POST /api/sync`) with the user's access token. The app sends everything it can read
and the API decides what to keep:

- **Sleep:** Health Connect sessions with their stages (last 30 days).
- **Heart rate:** all-day Health Connect heart rate (last 30 days), averaged on the phone to one sample per minute.
- **HRV:** the watch's own RMSSD readings (`HeartRateVariabilityRmssdRecord`, last 30 days). HRV needs
  beat-to-beat intervals, so it cannot be computed from per-minute heart rate, and only some watch apps write it
  to Health Connect. capacitor-health-connect 0.7 cannot return this record type on its own:
  `scripts/patch-health-connect.cjs` adds it and runs on `npm install` (postinstall). Run
  `node scripts/patch-health-connect.cjs` once by hand if `node_modules` is already installed.
- **Resting heart rate:** the watch's own readings (`RestingHeartRateRecord`, last 30 days). Without one for a
  night, the API computes it from the per-minute heart rate: the lowest 30-minute average while asleep.
- **Steps:** daily totals since 1 January.
- **Workouts:** Health Connect exercise sessions of the last 30 days (type, start, end, calories, distance, heart
  rate during them), including the walks the phone detects on its own. Every session adds to the day's active
  minutes; a walk only counts as a workout (morning/late workout patterns) when its average heart rate is at least
  30 bpm above that day's usual waking heart rate (`WALK_MIN_HR_RISE` in `connectors/device_sync.py`).
- **Screen time:** every foreground app session and screen/lock event of the last 7 days
  (`UsageStats.getUsageSessions`). Android only keeps about a week of these, so sync at least weekly.

The API (`backend/stressless/server/phone_sync.py`) follows the ingest flow in `docs/SCHEMA.md`:
- It checks consent; the first sync asks for it.
- It records this install as its own connection (`health_connect` and `screen_time`).
- It upserts the raw `source_records`.
- It recomputes `sleep_nights` (scored, with the night's mean HRV in `hrv_rmssd_ms`: readings from bedtime to two
  hours after waking, and `resting_hr`: the watch's reading, else computed from the night's heart rate), `heart_rate_days` (1440 minutes, merged with what is already stored for that day),
  `daily_activity` and the `screen.*` rows in `daily_metrics`.

Syncing the same days again overwrites instead of duplicating.

1. Apply `supabase/migrations/20261016000000_screen_time.sql` (registers the screen-time source and metrics).
2. Set `SUPABASE_SERVICE_ROLE_KEY` for the API (`.env.local` / Vercel); without it `/api/sync` answers 503.
3. `cp www/config.example.js www/config.js` and fill in the Supabase URL, the publishable key and `API_URL`.
4. `npx cap sync`, then run the app.

Pointing `API_URL` at a local `npm run dev:api` (`http://10.0.2.2:8000` from the emulator) is plain HTTP
from an `https://localhost` WebView. Android blocks that as mixed content unless you add
`"android": { "allowMixedContent": true }` to `capacitor.config.json` (dev only). The deployed HTTPS URL
doesn't need it. Extra allowed origins for the API's CORS go in `STRESSLESS_CORS_ORIGINS`.
