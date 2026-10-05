// Minimal backend stub — receives what the app syncs from HealthKit/Health
// Connect, the device calendar, and background location pings, and stores it
// in memory (swap for a real database before this goes anywhere near
// production; this is here so you have something to point the app at while
// testing).

const express = require("express");
const cors = require("cors");

const app = express();
app.use(cors());
app.use(express.json());

const db = {
  calendarEvents: [],
  healthSamples: [],
  locationPings: [],
};

app.post("/calendar/sync", (req, res) => {
  db.calendarEvents.push(...(req.body.events || []));
  res.json({ ok: true, stored: req.body.events?.length ?? 0 });
});

app.post("/health/sync", (req, res) => {
  db.healthSamples.push({
    receivedAt: new Date().toISOString(),
    heartRate: req.body.heartRate,
    sleep: req.body.sleep,
  });
  res.json({ ok: true });
});

app.post("/location/ping", (req, res) => {
  db.locationPings.push({
    lat: req.body.lat,
    lon: req.body.lon,
    timestamp: req.body.timestamp,
  });
  res.json({ ok: true });
});

// Very first cut of the actual feature: compare a calendar event's window
// against location pings to flag "left later than planned" / "never left".
app.get("/correlate/schedule-adherence", (req, res) => {
  const results = db.calendarEvents.map((event) => {
    const pings = db.locationPings.filter(
      (p) => p.timestamp >= event.startDate && p.timestamp <= event.endDate + 60 * 60 * 1000
    );
    return {
      event: event.title,
      plannedStart: event.startDate,
      plannedEnd: event.endDate,
      pingCount: pings.length,
      // TODO: real geocoding + distance-to-event-location comparison,
      // arrival/departure detection, etc.
    };
  });
  res.json(results);
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Backend stub listening on :${PORT}`));
