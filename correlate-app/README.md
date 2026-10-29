# Correlate — MVP native shell

A thin Capacitor wrapper around a web dashboard (`www/`), used only for the
things a website can't do on its own: reading the device calendar,
reading Apple HealthKit / Android Health Connect, and Android app usage.
Everything else (the actual correlation logic, the UI)
lives in normal web code and can keep evolving like a website.

## What's here

```
correlate-app/
├── www/                 the web dashboard (plain HTML/JS for now — swap in
│                         your real frontend framework freely)
│   ├── index.html
│   └── native.js         bridges the dashboard to native plugins
├── server/
│   └── index.js          minimal Express backend stub to sync data to
├── capacitor.config.json
└── package.json
```

## One-time setup

```bash
cd correlate-app
npm install

# Add the native plugins used in native.js
npm install capacitor-health                     # HealthKit + Health Connect, one API
npm install @ebarooni/capacitor-calendar          # device calendar (EventKit / CalendarContract)

npx cap init   # if capacitor.config.json wasn't already picked up
npx cap add ios
npx cap add android
npx cap sync
```

## iOS — install on your own phone, free, no App Store

Requires a Mac with Xcode.

```bash
npx cap open ios
```

In Xcode:
1. Select your Apple ID under Signing & Capabilities (a free account works for
   local installs — no paid developer account needed yet).
2. Add the **HealthKit** capability (Signing & Capabilities → + Capability).
3. In `Info.plist`, add `NSHealthShareUsageDescription` and
   `NSHealthUpdateUsageDescription` with a plain-language reason.
4. Plug in your iPhone via USB, select it as the run target, hit Run (▶).

The app installs directly on your phone. No review, no store. Free builds
expire after ~7 days — just re-run to renew while you're testing.

To share test builds with others without an App Store listing, use
**TestFlight** (needs the $99/year Apple Developer Program): internal
testers get builds instantly with zero review.

## Android — install on your own phone, completely free

Requires Android Studio.

```bash
npx cap open android
```

1. Add Health Connect permissions to `AndroidManifest.xml` (the
   `capacitor-health` plugin's README lists the exact `<uses-permission>`
   entries you need — they vary by which data types you request).
2. Plug in your Android phone via USB with USB debugging enabled, select it
   as the run target, hit Run.

That's it — fully free, no account, no review, works immediately.

To distribute to other testers before a public launch, Play Console's
**internal testing track** needs only a one-time $25 developer account fee,
no review.

## Sign in & Sync (sleep, heart rate, vitals, steps, screen time → Supabase)

The **Account & sync** card signs in with the same Supabase email/password account as the web app
(`www/auth.js`, plain Supabase Auth REST calls). **Sync** re-reads the phone's data and POSTs it to the
StressLess API (`POST /api/sync`) with the user's access token. The app sends everything it can read
and the API decides what to keep:

- **Sleep & vitals** (Health Connect, last 30 days): sleep sessions with their stages; heart rate, averaged on
  the phone to one sample per minute; resting heart rate, breathing rate and blood oxygen readings. Each type is
  asked for separately, and the Sleep & vitals card lists how many records of each came back (or "not allowed").
- **Steps:** daily totals since 1 January.
- **Screen time:** every foreground app session and screen/lock event of the last 7 days
  (`UsageStats.getUsageSessions`). Android only keeps about a week of these, so sync at least weekly.

The API (`backend/stressless/server/phone_sync.py`) follows the ingest flow in `docs/SCHEMA.md`:
- It checks consent; the first sync asks for it.
- It records this install as its own connection (`health_connect` and `screen_time`).
- It upserts the raw `source_records`.
- It recomputes `sleep_nights` (scored, with the resting heart rate, breathing rate and blood oxygen measured while
  asleep), `heart_rate_days` (1440 minutes, merged with what is already stored for that day), `daily_activity` and
  the `screen.*` rows in `daily_metrics`.

Syncing the same days again overwrites instead of duplicating.

1. Apply `supabase/migrations/20261016000000_screen_time.sql` (registers the screen-time source and metrics).
2. Set `SUPABASE_SERVICE_ROLE_KEY` for the API (`.env.local` / Vercel); without it `/api/sync` answers 503.
3. `cp www/config.example.js www/config.js` and fill in the Supabase URL, the publishable key and `API_URL`.
4. `npx cap sync`, then run the app.

Pointing `API_URL` at a local `npm run dev:api` (`http://10.0.2.2:8000` from the emulator) is plain HTTP
from an `https://localhost` WebView. Android blocks that as mixed content unless you add
`"android": { "allowMixedContent": true }` to `capacitor.config.json` (dev only). The deployed HTTPS URL
doesn't need it. Extra allowed origins for the API's CORS go in `STRESSLESS_CORS_ORIGINS`.

## Running the backend stub

```bash
node server/index.js
```

Then update `BACKEND_URL` at the top of `www/native.js` to point at it
(use your machine's LAN IP, not `localhost`, when testing on a real phone).

## What's stubbed vs. real

- **Calendar sync, health sync** — wired up and functional once you add the
  plugins above and grant permissions on-device.
- **Design** — the dashboard is intentionally plain right now (dark,
  functional, no branding decisions made yet) since the point of this pass
  is proving the native data pipeline works, not visual polish.
