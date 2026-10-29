// Minimal backend stub — receives what the app syncs from HealthKit/Health
// Connect and the device calendar, and stores it in memory (swap for a real
// database before this goes anywhere near production; this is here so you have something to point the app at while
// testing).

const express = require("express");
const cors = require("cors");

const app = express();
app.use(cors());
app.use(express.json());

const db = {
  calendarEvents: [],
  healthSamples: [],
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

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Backend stub listening on :${PORT}`));
