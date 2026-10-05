# Correlate — MVP native shell

A thin Capacitor wrapper around a web dashboard (`www/`), used only for the
three things a website can't do on its own: reading the device calendar,
reading Apple HealthKit / Android Health Connect, and background
geofencing/location. Everything else (the actual correlation logic, the UI)
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
npm install @capacitor-community/background-geolocation  # background location

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

## Running the backend stub

```bash
node server/index.js
```

Then update `BACKEND_URL` at the top of `www/native.js` to point at it
(use your machine's LAN IP, not `localhost`, when testing on a real phone).

## What's stubbed vs. real

- **Calendar sync, health sync, location pings** — wired up and functional
  once you add the plugins above and grant permissions on-device.
- **Correlation logic** (`/correlate/schedule-adherence` in the backend) —
  intentionally minimal right now: it just counts location pings inside an
  event's time window. The real version needs: geocoding each event's
  location text into coordinates, registering an actual geofence per event
  (not just raw pings), and computing arrival/departure deltas against the
  planned start/end times — worth building once you've confirmed the data
  pipeline itself works end-to-end.
- **Design** — the dashboard is intentionally plain right now (dark,
  functional, no branding decisions made yet) since the point of this pass
  is proving the native data pipeline works, not visual polish.
