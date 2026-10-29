// native.js
// Bridges the dashboard to native plugins (calendar, Health Connect / HealthKit,
// app usage) and renders everything as cards. Every native call is
// also written to the on-screen debug log at the bottom of the page.

const BACKEND_URL = window.localStorage.getItem("BACKEND_URL") || "http://10.0.2.2:3000"; // 10.0.2.2 for Android Emulator, localhost:3000 for adb reverse

// All fetched data lives here so renderers (and you, via the console) can reach it.
const S = (window.__app = {
  events: [],
  steps: [], // [{ ms, value }] one per day
  workouts: [],
  sleep: [],
  sleepSessions: [], // full sessions with stages, normalised for POST /api/sync
  heartRate: [], // Health Connect heart-rate records, averaged to one sample per minute, for POST /api/sync
  vitals: { resting: [], spo2: [], resp: [] }, // point readings, for POST /api/sync
  hcRead: null, // what the last Health Connect read returned, per record type
  hcPermissions: {}, // API data type -> granted
  appUsage: [],
  usageDays: [],
  usageSelected: null,
  calView: "upcoming",
  stepsMode: "week",
  range: null,
});

// --- Small helpers -----------------------------------------------------------
const DAY = 24 * 60 * 60 * 1000;
const $ = (id) => document.getElementById(id);
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const toMs = (v) => (typeof v === "number" ? v : new Date(v).getTime());
const fmtDay = (ms) => new Date(ms).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
const fmtTime = (ms) => new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const fmtNum = (n) => Math.round(n).toLocaleString();
const fmtDur = (ms) => {
  if (ms > 0 && ms < 60000) {
    const sec = Math.round(ms / 1000);
    return `${sec}s`;
  }
  const m = Math.round(ms / 60000);
  return m >= 60 ? `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m` : `${m}m`;
};
const dayKey = (ms) => {
  const d = new Date(ms);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const startOfDay = (ms) => {
  const d = new Date(ms);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
};
const weekStart = (ms) => {
  const d = new Date(startOfDay(ms));
  const dow = (d.getDay() + 6) % 7; // Monday = 0
  return d.getTime() - dow * DAY;
};

// --- On-screen logging -------------------------------------------------------
const logEl = $("log");

function log(label, data, level = "ok") {
  const entry = document.createElement("div");
  entry.className = `log-entry ${level}`;
  const time = new Date().toLocaleTimeString();
  let body = "";
  if (data !== undefined) {
    let text = JSON.stringify(data, null, 2) ?? String(data);
    if (text.length > 3000) text = text.slice(0, 3000) + `\n… (truncated, ${text.length - 3000} more characters)`;
    body = `\n${text}`;
  }
  entry.textContent = `${time}  ${label}${body}`;
  logEl.prepend(entry);
  while (logEl.children.length > 80) logEl.lastChild.remove();
  console.log(`[${level}] ${label}`, data ?? "");
}

$("btn-clear-log").addEventListener("click", () => {
  logEl.innerHTML = "";
});

const dot = (id, state) => {
  const el = $(id);
  el.classList.remove("on", "off", "err");
  el.classList.add(state); // "on" | "off" | "err"
};

async function postToBackend(path, body) {
  const urls = [BACKEND_URL, "http://localhost:3000", "http://10.0.2.2:3000"];
  const uniqueUrls = [...new Set(urls)];
  let lastErr = null;

  for (const url of uniqueUrls) {
    try {
      const res = await fetch(`${url}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        log(`Backend ${url}${path} → ${res.status}`, undefined, "ok");
        return;
      }
    } catch (err) {
      lastErr = err;
    }
  }
  log(`Backend ${path} unreachable on ${uniqueUrls.join(", ")}`, String(lastErr), "error");
}

// Finds a plugin by trying likely names; the registered name depends on how
// each plugin author declared it.
function findPlugin(candidates) {
  const all = window.Capacitor?.Plugins || {};
  for (const name of candidates) if (all[name]) return all[name];
  return null;
}
const registeredNames = () => Object.keys(window.Capacitor?.Plugins || {});

// --- Chart builders (plain SVG/HTML, no libraries) ---------------------------
function barsSvg(values, titles = [], cls = "") {
  const n = values.length;
  if (!n) return "";
  const W = 300, H = 96;
  const step = W / n;
  const bw = Math.max(0.6, step - (n > 60 ? 0.4 : 1.5));
  const max = Math.max(...values, 1);
  const rects = values
    .map((v, i) => {
      const h = v > 0 ? Math.max(1, Math.round((v / max) * (H - 4))) : 0;
      return `<rect x="${(i * step).toFixed(2)}" y="${H - h}" width="${bw.toFixed(2)}" height="${h}" rx="1"><title>${esc(titles[i] ?? v)}</title></rect>`;
    })
    .join("");
  return `<svg class="bars ${cls}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${rects}</svg>`;
}

function sparkSvg(values) {
  if (values.length < 2) return "";
  const W = 300, H = 34;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const pts = values
    .map((v, i) => `${((i / (values.length - 1)) * W).toFixed(1)},${(H - 3 - ((v - min) / span) * (H - 6)).toFixed(1)}`)
    .join(" ");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><polyline points="${pts}"/></svg>`;
}

function statHtml(pairs) {
  return `<div class="stats">${pairs
    .map(([k, v]) => `<div class="stat"><div class="v">${esc(v)}</div><div class="k">${esc(k)}</div></div>`)
    .join("")}</div>`;
}

function hbarsHtml(entries) {
  const max = Math.max(...entries.map((e) => e[1]), 1);
  return entries
    .map(
      ([name, n]) =>
        `<div class="hbar"><div class="lbl"><span>${esc(name)}</span><span>${n}</span></div>` +
        `<div class="track"><div class="fill" style="width:${((n / max) * 100).toFixed(1)}%"></div></div></div>`
    )
    .join("");
}

// Local-midnight boundaries per day; setDate keeps daylight saving days correct
function dayRange(daysAgo) {
  const end = new Date();
  end.setHours(0, 0, 0, 0);
  end.setDate(end.getDate() - (daysAgo - 1)); // end of that day = start of the next
  const start = new Date(end);
  start.setDate(start.getDate() - 1);
  return { startTime: start.getTime(), endTime: end.getTime(), date: dayKey(start.getTime()) };
}

async function fetchScreenTimeDays(numDays = 7) {
  const UsageStats = window.Capacitor.Plugins?.UsageStats;
  const perm = await UsageStats.checkPermission();
  if (!perm.granted && perm.result !== "granted") {
    await UsageStats.requestPermission();
    return [];
  }

  const days = [];
  for (let i = 1; i <= numDays; i++) { // 1 = yesterday, 2 = day before, ...
    const { startTime, endTime, date } = dayRange(i);
    try {
      const res = await UsageStats.getUsageStats({ startTime, endTime });
      const stats = res.stats || [];
      const totalMs = stats.reduce((a, s) => a + s.totalTimeMillis, 0);
      days.push({ date, totalMs, apps: stats });
      log(`Screen time ${date}: ${fmtDur(totalMs)}`, undefined, totalMs ? "ok" : "error");
    } catch (err) {
      log(`Screen time ${date} failed`, String(err), "error");
    }
  }
  return days.sort((a, b) => a.date.localeCompare(b.date));
}

// --- Renderers ---------------------------------------------------------------
function renderTiles() {
  const stepsTotal = S.steps.reduce((a, s) => a + s.value, 0);
  const sleepHours = S.sleep.map((n) => n.hours).filter((h) => h > 0);
  const tile = (cls, num, cap) => `<div class="tile ${cls}"><div class="num">${num}</div><div class="cap">${cap}</div></div>`;
  $("tiles").innerHTML =
    tile("blue", S.events.length ? fmtNum(S.events.length) : "—", "calendar events") +
    tile("green", S.steps.length ? fmtNum(stepsTotal) : "—", "steps this year") +
    tile("violet", sleepHours.length ? (sleepHours.reduce((a, b) => a + b, 0) / sleepHours.length).toFixed(1) + " h" : "—", "avg sleep") +
    tile("amber", S.workouts.length ? fmtNum(S.workouts.length) : "—", "workouts");
}

function renderToday() {
  const today = startOfDay(Date.now());
  $("today-date").textContent = new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
  const evs = S.events.filter((e) => e.endDate > today && e.startDate < today + DAY);

  if (!S.events.length) {
    $("today-body").innerHTML = `<div class="empty">Connect your calendar to see today's plan.</div>`;
    return;
  }
  const html = evs.length
    ? evs.map(evRowHtml).join("")
    : `<div class="empty">No events on your calendar today.</div>`;
  $("today-body").innerHTML = html;
}

function evRowHtml(e) {
  const time = e.isAllDay ? "All day" : `${fmtTime(e.startDate)}–${fmtTime(e.endDate)}`;
  const meta = [
    e.calendarName ? `<span class="chip">${esc(e.calendarName)}</span>` : "",
    e.location ? esc(e.location) : "",
  ].join("");
  return (
    `<div class="ev"><div class="t">${esc(time)}</div><div class="b">` +
    `<div class="title">${esc(e.title || "(no title)")}</div>` +
    (meta ? `<div class="meta">${meta}</div>` : "") +
    `</div></div>`
  );
}

function renderCalendar() {
  if (!S.events.length) {
    $("cal-body").innerHTML = `<div class="empty">No calendar events loaded yet.</div>`;
    return;
  }
  const now = Date.now();
  const today = startOfDay(now);
  const list =
    S.calView === "upcoming"
      ? S.events.filter((e) => e.endDate >= today).slice(0, 40)
      : S.events.filter((e) => e.startDate < today).slice(-40).reverse();

  // group by day
  let html = "";
  let lastKey = "";
  for (const e of list) {
    const k = dayKey(e.startDate);
    if (k !== lastKey) {
      html += `<div class="day-head">${esc(fmtDay(e.startDate))}</div>`;
      lastKey = k;
    }
    html += evRowHtml(e);
  }
  if (!list.length) html = `<div class="empty">Nothing ${S.calView === "upcoming" ? "upcoming" : "in the past"}.</div>`;

  // events per month across the fetched range
  const byMonth = new Map();
  for (const e of S.events) {
    const d = new Date(e.startDate);
    const k = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    byMonth.set(k, (byMonth.get(k) || 0) + 1);
  }
  const months = [...byMonth.keys()].sort();
  const monthVals = months.map((k) => byMonth.get(k));

  // per calendar
  const per = {};
  S.events.forEach((e) => {
    const n = e.calendarName || "unknown";
    per[n] = (per[n] || 0) + 1;
  });
  const perEntries = Object.entries(per).sort((a, b) => b[1] - a[1]).slice(0, 6);

  const first = S.events[0].startDate;
  const last = S.events[S.events.length - 1].startDate;
  $("cal-body").innerHTML =
    statHtml([
      ["events", fmtNum(S.events.length)],
      ["calendars", String(Object.keys(per).length)],
      ["from", new Date(first).toLocaleDateString(undefined, { month: "short", year: "numeric" })],
    ]) +
    barsSvg(monthVals, months.map((m, i) => `${m}: ${monthVals[i]} events`)) +
    `<div class="axis"><span>${esc(months[0])}</span><span>events per month</span><span>${esc(months[months.length - 1])}</span></div>` +
    `<div class="day-head" style="margin-top:18px">By calendar</div>` +
    hbarsHtml(perEntries) +
    `<div class="day-head" style="margin-top:18px">${S.calView === "upcoming" ? "Upcoming" : "Recent"}</div>` +
    html;
}

function renderSteps() {
  if (!S.steps.length) {
    $("steps-body").innerHTML = `<div class="empty">No step data loaded yet.</div>`;
    return;
  }
  const days = S.steps;
  const total = days.reduce((a, d) => a + d.value, 0);
  const withData = days.filter((d) => d.value > 0);
  const best = withData.reduce((b, d) => (d.value > b.value ? d : b), withData[0] || days[0]);

  let values, titles, axisL, axisR;
  if (S.stepsMode === "day") {
    values = days.map((d) => d.value);
    titles = days.map((d) => `${fmtDay(d.ms)}: ${fmtNum(d.value)} steps`);
  } else {
    const weeks = new Map();
    for (const d of days) {
      const w = weekStart(d.ms);
      const cur = weeks.get(w) || { sum: 0, n: 0 };
      cur.sum += d.value;
      cur.n += d.value > 0 ? 1 : 0;
      weeks.set(w, cur);
    }
    const keys = [...weeks.keys()].sort((a, b) => a - b);
    values = keys.map((k) => (weeks.get(k).n ? weeks.get(k).sum / weeks.get(k).n : 0));
    titles = keys.map((k, i) => `Week of ${fmtDay(k)}: ${fmtNum(values[i])} steps/day`);
  }
  axisL = fmtDay(days[0].ms);
  axisR = fmtDay(days[days.length - 1].ms);

  $("steps-body").innerHTML =
    statHtml([
      ["total", fmtNum(total)],
      ["avg / day", fmtNum(total / Math.max(withData.length, 1))],
      ["best day", `${fmtNum(best.value)}`],
      ["days tracked", String(withData.length)],
    ]) +
    barsSvg(values, titles, "green") +
    `<div class="axis"><span>${esc(axisL)}</span><span>${S.stepsMode === "day" ? "steps per day" : "avg steps per day, by week"}</span><span>${esc(axisR)}</span></div>` +
    (best ? `<div class="sub" style="margin-top:8px">Best day: ${esc(fmtDay(best.ms))}</div>` : "");
}

function renderWorkouts() {
  if (!S.workouts.length) {
    $("workouts-body").innerHTML = `<div class="empty">No workouts in the last 30 days (or none loaded yet).</div>`;
    return;
  }
  $("workouts-body").innerHTML = S.workouts
    .map((w) => {
      const hr = w.hr || [];
      const avg = hr.length ? hr.reduce((a, b) => a + b, 0) / hr.length : null;
      const max = hr.length ? Math.max(...hr) : null;
      const bits = [
        w.durationMs ? fmtDur(w.durationMs) : "",
        w.calories ? `${fmtNum(w.calories)} kcal` : "",
        w.distance ? `${(w.distance / 1000).toFixed(2)} km` : "",
        avg ? `avg ${Math.round(avg)} bpm` : "",
        max ? `max ${Math.round(max)} bpm` : "",
      ].filter(Boolean);
      return (
        `<div class="wk"><div class="top"><span class="type">${esc(w.type)}</span><span class="sub">${esc(fmtDay(w.startMs))}, ${esc(fmtTime(w.startMs))}</span></div>` +
        `<div class="meta">${esc(bits.join(" · ") || "no details")}${w.source ? ` · ${esc(w.source)}` : ""}</div>` +
        sparkSvg(hr) +
        `</div>`
      );
    })
    .join("");
}

function renderVitals() {
  const body = $("vitals-body");
  if (!S.hcRead) {
    body.innerHTML = `<div class="empty">Connect sleep &amp; vitals to see your nights, heart rate and vitals here.</div>`;
    return;
  }
  let html = `<div class="day-head">Read from Health Connect (last 30 days)</div>` + hcReadHtml();

  // sleep
  html += `<div class="day-head" style="margin-top:16px">Sleep</div>`;
  const nights = S.sleep;
  if (!nights.length) {
    html += `<div class="empty">No sleep sessions found.</div>`;
  } else {
    const hours = nights.map((n) => n.hours);
    const avg = hours.reduce((a, b) => a + b, 0) / hours.length;
    const best = nights.reduce((b, n) => (n.hours > b.hours ? n : b), nights[0]);
    html +=
      statHtml([
        ["avg / night", `${avg.toFixed(1)} h`],
        ["longest", `${best.hours.toFixed(1)} h`],
        ["nights", String(nights.length)],
      ]) +
      barsSvg(hours, nights.map((n) => `${fmtDay(n.startMs)}: ${n.hours.toFixed(1)} h`), "violet") +
      `<div class="axis"><span>${esc(fmtDay(nights[0].startMs))}</span><span>hours slept</span><span>${esc(fmtDay(nights[nights.length - 1].startMs))}</span></div>`;
  }

  // heart rate: the latest day with readings, minute by minute
  html += `<div class="day-head" style="margin-top:16px">Heart rate</div>`;
  const samples = S.heartRate.flatMap((r) => r.samples);
  if (!samples.length) {
    html += `<div class="empty">No heart rate found. Your watch app has to share heart rate with Health Connect.</div>`;
  } else {
    const days = new Set(samples.map((x) => dayKey(x.t)));
    const lastDay = [...days].sort().pop();
    const today = samples.filter((x) => dayKey(x.t) === lastDay).sort((a, b) => a.t - b.t);
    const bpm = today.map((x) => x.bpm);
    const latest = today[today.length - 1];
    html +=
      statHtml([
        ["minutes", fmtNum(samples.length)],
        ["days", String(days.size)],
        ["latest", `${latest.bpm} bpm`],
      ]) +
      sparkSvg(bpm) +
      `<div class="axis"><span>${esc(fmtTime(today[0].t))}</span><span>${esc(fmtDay(today[0].t))}: ${Math.min(...bpm)}–${Math.max(...bpm)} bpm</span><span>${esc(fmtTime(latest.t))}</span></div>`;
  }

  // vitals: the latest reading of each, then the most recent readings
  html += `<div class="day-head" style="margin-top:16px">Vitals</div>`;
  const kinds = [
    ["resting", "resting HR", "bpm", (v) => `${Math.round(v.bpm)} bpm`],
    ["resp", "breathing", "rate", (v) => `${v.rate.toFixed(1)} /min`],
    ["spo2", "blood oxygen", "percent", (v) => `${v.percent.toFixed(1)} %`],
  ];
  const latestOf = (k) => S.vitals[k][S.vitals[k].length - 1];
  html += statHtml(kinds.map(([k, label, , show]) => [label, latestOf(k) ? show(latestOf(k)) : "—"]));
  const recent = kinds
    .flatMap(([k, label, , show]) => S.vitals[k].map((v) => ({ ms: toMs(v.time), label, text: show(v) })))
    .sort((a, b) => b.ms - a.ms)
    .slice(0, 8);
  html += recent.length
    ? recent
        .map((r) => `<div class="ev"><div class="t">${esc(fmtDay(r.ms))}</div><div class="b"><div class="title">${esc(r.text)}</div><div class="meta">${esc(r.label)} · ${esc(fmtTime(r.ms))}</div></div></div>`)
        .join("")
    : `<div class="empty">No resting heart rate, breathing rate or blood oxygen found.</div>`;
  body.innerHTML = html;
}

// One line per record type: how many came back, or why none did
function hcReadHtml() {
  return Object.entries(S.hcRead)
    .map(([type, r]) => {
      const state = r.error ? "err" : r.allowed === false ? "off" : "on";
      const text = r.error ? "read failed" : r.allowed === false ? "not allowed" : `${fmtNum(r.count)} ${r.unit}`;
      return `<div class="row"><span><span class="dot ${state}"></span>${esc(HC_LABELS[type])}</span><span class="sub">${esc(text)}</span></div>`;
    })
    .join("");
}

function renderAll() {
  renderTiles();
  renderToday();
  renderCalendar();
  renderSteps();
  renderWorkouts();
  renderVitals();
  renderAppUsage();
}

// Segmented controls (Upcoming/Past, Daily/Weekly)
document.addEventListener("click", (ev) => {
  const btn = ev.target.closest("[data-seg]");
  if (!btn) return;
  const [group, value] = btn.dataset.seg.split(":");
  btn.parentElement.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === btn));
  if (group === "cal") {
    S.calView = value;
    renderCalendar();
  } else if (group === "steps") {
    S.stepsMode = value;
    renderSteps();
  }
});

// --- Calendar ----------------------------------------------------------------
async function connectCalendar() {
  if (!window.Capacitor?.isNativePlatform()) {
    log("Calendar: not running as a native app (browser tab)", undefined, "error");
    return;
  }
  const CapacitorCalendar = findPlugin(["CapacitorCalendar", "Calendar"]);
  if (!CapacitorCalendar) {
    log("Calendar plugin not found on window.Capacitor.Plugins", "Registered plugin names: " + registeredNames().join(", "), "error");
    dot("dot-calendar", "err");
    return;
  }

  try {
    const perm = await CapacitorCalendar.requestReadOnlyCalendarAccess();
    log("Calendar permission result", perm);
    if (perm.result !== "granted") {
      dot("dot-calendar", "err");
      return;
    }

    // Which calendars exist on the device, so each event can show its source
    const calendarNames = {};
    try {
      const cals = await CapacitorCalendar.listCalendars();
      (cals.result || []).forEach((c) => {
        calendarNames[c.id] = c.title || c.name || String(c.id);
      });
      log("Calendars on this device", (cals.result || []).map((c) => ({ id: c.id, title: c.title || c.name })));
    } catch (err) {
      log("listCalendars failed (continuing without calendar names)", String(err), "error");
    }

    // 30-day chunks, sequentially: one giant query can freeze the WebView, and
    // this way a failed chunk doesn't lose the rest.
    const CHUNK_DAYS = 30;
    const LOOKBACK_DAYS = 730; // ~2 years; raise if it stays stable
    const LOOKAHEAD_DAYS = 30;
    const now = Date.now();
    const rangeStart = now - LOOKBACK_DAYS * DAY;
    const rangeEnd = now + LOOKAHEAD_DAYS * DAY;

    const seen = new Set();
    const all = [];
    let failedChunks = 0;
    for (let from = rangeStart; from < rangeEnd; from += CHUNK_DAYS * DAY) {
      const to = Math.min(from + CHUNK_DAYS * DAY, rangeEnd);
      try {
        const res = await CapacitorCalendar.listEventsInRange({ from, to });
        for (const e of res.result || []) {
          const key = `${e.id}-${e.startDate}`;
          if (seen.has(key)) continue;
          seen.add(key);
          all.push({ ...e, calendarName: calendarNames[e.calendarId] });
        }
      } catch (err) {
        failedChunks += 1;
        log(`Calendar chunk failed (${new Date(from).toDateString()})`, String(err), "error");
      }
      await new Promise((r) => setTimeout(r, 0)); // let the UI breathe
    }
    all.sort((a, b) => a.startDate - b.startDate);
    S.events = all;
    S.range = { from: rangeStart, to: rangeEnd };

    const per = {};
    all.forEach((e) => {
      const n = e.calendarName || "unknown";
      per[n] = (per[n] || 0) + 1;
    });
    log(`Calendar: ${all.length} events fetched`, {
      from: new Date(rangeStart).toDateString(),
      to: new Date(rangeEnd).toDateString(),
      failedChunks,
      perCalendar: per,
      firstEvent: all[0],
    });

    dot("dot-calendar", "on");
    renderAll();

    for (let i = 0; i < all.length; i += 200) {
      await postToBackend("/calendar/sync", { events: all.slice(i, i + 200) });
    }
  } catch (err) {
    log("Calendar call threw an error", String(err), "error");
    dot("dot-calendar", "err");
  }
}

// --- Health: steps + workouts (capacitor-health) ---------------------------------
// Tolerant parsers: the plugin's exact field names are logged the first time so
// they can be corrected quickly if a card comes up empty.
function parseSteps(res) {
  const arr = res?.aggregatedData || res?.result || res?.data || (Array.isArray(res) ? res : []);
  return arr
    .map((it) => ({
      ms: toMs(it.startDate ?? it.start ?? it.date ?? it.time),
      value: Number(it.value ?? it.count ?? it.steps ?? 0),
    }))
    .filter((x) => Number.isFinite(x.ms));
}

function parseWorkouts(res) {
  const arr = res?.workouts || res?.result || res?.data || (Array.isArray(res) ? res : []);
  return arr
    .map((w) => {
      const startMs = toMs(w.startDate ?? w.start);
      const endMs = toMs(w.endDate ?? w.end);
      const hrRaw = w.heartRate || w.heartRates || [];
      return {
        type: String(w.workoutType ?? w.type ?? "Workout").replace(/[_-]/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase()),
        startMs,
        durationMs: w.duration ? Number(w.duration) * 1000 : endMs - startMs,
        calories: Number(w.calories ?? w.totalEnergyBurned ?? 0) || 0,
        distance: Number(w.distance ?? w.totalDistance ?? 0) || 0,
        source: w.sourceName ?? w.source ?? "",
        hr: hrRaw.map((h) => Number(h.bpm ?? h.value ?? h.heartRate)).filter((n) => Number.isFinite(n)),
      };
    })
    .filter((w) => Number.isFinite(w.startMs))
    .sort((a, b) => b.startMs - a.startMs);
}

async function connectHealth() {
  if (!window.Capacitor?.isNativePlatform()) {
    log("Health: not running as a native app (browser tab)", undefined, "error");
    return;
  }
  const Health = findPlugin(["Health", "HealthPlugin", "CapacitorHealth"]);
  if (!Health) {
    log("Health plugin not found on window.Capacitor.Plugins", "Registered plugin names: " + registeredNames().join(", "), "error");
    dot("dot-health", "err");
    return;
  }

  try {
    const available = await Health.isHealthAvailable();
    log("Health store availability", available);
    if (!available.available) {
      dot("dot-health", "err");
      return;
    }

    // capacitor-health has no sleep support and no standalone heart rate;
    // heart rate only comes inside workout records. Sleep and all-day heart rate are read in connectVitals().
    const permResult = await Health.requestHealthPermissions({
      permissions: ["READ_STEPS", "READ_HEART_RATE", "READ_WORKOUTS"],
    });
    log("Health permission result", permResult);

    // Steps: from 1 January this year, one query per month so no single call is huge
    const now = new Date();
    const yearStart = new Date(now.getFullYear(), 0, 1);
    const byDay = new Map();
    let sampleLogged = false;
    for (let m = new Date(yearStart); m <= now; m = new Date(m.getFullYear(), m.getMonth() + 1, 1)) {
      const chunkStart = m;
      const chunkEnd = new Date(Math.min(new Date(m.getFullYear(), m.getMonth() + 1, 1).getTime(), now.getTime()));
      try {
        const res = await Health.queryAggregated({
          dataType: "steps",
          startDate: chunkStart.toISOString(),
          endDate: chunkEnd.toISOString(),
          bucket: "day",
        });
        const items = parseSteps(res);
        if (!sampleLogged) {
          log("Steps: raw response shape (first month)", res);
          sampleLogged = true;
        }
        for (const it of items) {
          const k = dayKey(it.ms);
          const cur = byDay.get(k);
          byDay.set(k, { ms: startOfDay(it.ms), value: (cur?.value || 0) + it.value });
        }
      } catch (err) {
        log(`Steps chunk failed (${chunkStart.toLocaleDateString()})`, String(err), "error");
      }
      await new Promise((r) => setTimeout(r, 0));
    }
    S.steps = [...byDay.values()].sort((a, b) => a.ms - b.ms);
    log(`Steps: ${S.steps.length} days loaded since ${yearStart.toDateString()}`, {
      total: S.steps.reduce((a, s) => a + s.value, 0),
    });

    // Workouts with heart rate: last 30 days (heart rate samples make these heavy)
    const wStart = new Date(now.getTime() - 30 * DAY);
    try {
      const wres = await Health.queryWorkouts({
        startDate: wStart.toISOString(),
        endDate: now.toISOString(),
        includeHeartRate: true,
        includeSteps: false,
      });
      S.workouts = parseWorkouts(wres);
      log(`Workouts: ${S.workouts.length} in the last 30 days`, wres?.workouts?.[0] ?? wres);
    } catch (err) {
      log("Workouts query failed", String(err), "error");
    }

    dot("dot-health", "on");
    renderAll();
  } catch (err) {
    log("Health call threw an error", String(err), "error");
    dot("dot-health", "err");
  }
}

// --- Sleep & vitals (Health Connect) ------------------------------------------------
// Android -> capacitor-health-connect: sleep sessions with stages, heart rate, resting heart rate, blood oxygen and
// breathing rate. Each type is asked for and read on its own, so one refused permission does not hide the rest.
// iOS is out of scope for the MVP.
const HC_TYPES = {
  // plugin record type: [Health Connect permission, data type the API stores it under, unit shown in the app]
  SleepSession: ["READ_SLEEP", "sleep_session", "sessions"],
  HeartRateSeries: ["READ_HEART_RATE", "heart_rate", "minutes"],
  RestingHeartRate: ["READ_RESTING_HEART_RATE", "resting_heart_rate", "readings"],
  RespiratoryRate: ["READ_RESPIRATORY_RATE", "respiratory_rate", "readings"],
  OxygenSaturation: ["READ_OXYGEN_SATURATION", "oxygen_saturation", "readings"],
};
const HC_LABELS = {
  SleepSession: "Sleep",
  HeartRateSeries: "Heart rate",
  RestingHeartRate: "Resting heart rate",
  RespiratoryRate: "Breathing rate",
  OxygenSaturation: "Blood oxygen",
};
const HC_MAX_RECORDS = 50000;

const sleepArray = (res) => res?.records || res?.resultData || res?.result || res?.data || (Array.isArray(res) ? res : []);
const isoOrNull = (v) => {
  const ms = toMs(v);
  return Number.isFinite(ms) ? new Date(ms).toISOString() : null;
};
// "+02:00" -> 120; without one, the phone's offset at that moment
function offsetMin(v, ms) {
  const m = /^([+-])(\d{2}):(\d{2})$/.exec(typeof v === "string" ? v : "");
  return m ? (m[1] === "-" ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3])) : -new Date(ms).getTimezoneOffset();
}

// Health Connect: one SleepSessionRecord per night, stages inside (schemas/sleep-schema.json)
function sleepSessionsAndroid(res) {
  return sleepArray(res)
    .map((r) => {
      const startMs = toMs(r.startTime ?? r.start), endMs = toMs(r.endTime ?? r.end);
      if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return null;
      const stages = (r.stages || [])
        .map((st) => ({ start: isoOrNull(st.startTime ?? st.start), end: isoOrNull(st.endTime ?? st.end), stage: st.stage }))
        .filter((st) => st.start && st.end);
      return {
        id: r.metadata?.id || String(startMs),
        start: new Date(startMs).toISOString(),
        end: new Date(endMs).toISOString(),
        tzOffsetMin: offsetMin(r.startZoneOffset, startMs),
        source: r.metadata?.dataOrigin || null,
        modifiedAt: isoOrNull(r.metadata?.lastModifiedTime),
        stages,
      };
    })
    .filter(Boolean);
}

function parseSleep(res) {
  return sleepArray(res)
    .map((r) => {
      const startMs = toMs(r.startTime ?? r.startDate ?? r.start);
      const endMs = toMs(r.endTime ?? r.endDate ?? r.end);
      return { startMs, endMs, hours: (endMs - startMs) / 3600000 };
    })
    .filter((n) => Number.isFinite(n.startMs) && Number.isFinite(n.endMs) && n.hours > 0)
    .sort((a, b) => a.startMs - b.startMs);
}

// Every page of one record type in [start, end]
async function readAllRecords(HealthConnect, type, start, end) {
  const records = [];
  let pageToken;
  do {
    const res = await HealthConnect.readRecords({
      type,
      timeRangeFilter: { type: "between", startTime: start, endTime: end },
      pageSize: 1000,
      ...(pageToken ? { pageToken } : {}),
    });
    records.push(...sleepArray(res));
    pageToken = res?.pageToken || undefined;
  } while (pageToken && records.length < HC_MAX_RECORDS);
  return records;
}

const recordMeta = (r, ms, prefix) => ({
  id: r.metadata?.id || `${prefix}:${ms}`,
  tzOffsetMin: offsetMin(r.startZoneOffset ?? r.zoneOffset, ms),
  source: r.metadata?.dataOrigin || null,
  modifiedAt: isoOrNull(r.metadata?.lastModifiedTime),
});

// HeartRateRecord: a span with samples inside, averaged here to one sample per minute to keep the upload small
function heartRateRecords(records) {
  return records
    .map((r) => {
      const startMs = toMs(r.startTime), endMs = toMs(r.endTime);
      if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return null;
      const perMinute = new Map();
      for (const x of r.samples || []) {
        const t = toMs(x.time), bpm = Number(x.beatsPerMinute);
        if (!Number.isFinite(t) || !Number.isFinite(bpm)) continue;
        const m = Math.floor(t / 60000);
        const acc = perMinute.get(m) || [0, 0];
        acc[0] += bpm;
        acc[1] += 1;
        perMinute.set(m, acc);
      }
      const samples = [...perMinute.entries()]
        .sort((a, b) => a[0] - b[0])
        .map(([m, [sum, n]]) => ({ t: m * 60000, bpm: Math.round(sum / n) }));
      return { ...recordMeta(r, startMs, "hr"), start: new Date(startMs).toISOString(), end: new Date(endMs).toISOString(), samples };
    })
    .filter(Boolean);
}

// Resting heart rate, blood oxygen, breathing rate: one reading at a point in time
function pointRecords(records, prefix, field, valueOf) {
  return records
    .map((r) => {
      const ms = toMs(r.time), value = Number(valueOf(r));
      if (!Number.isFinite(ms) || !Number.isFinite(value)) return null;
      return { ...recordMeta(r, ms, prefix), time: new Date(ms).toISOString(), [field]: value };
    })
    .filter(Boolean)
    .sort((a, b) => toMs(a.time) - toMs(b.time));
}

async function connectVitals() {
  if (!window.Capacitor?.isNativePlatform()) {
    log("Sleep & vitals: not running as a native app (browser tab)", undefined, "error");
    return;
  }
  const platform = window.Capacitor.getPlatform();
  if (platform !== "android") {
    log("Sleep & vitals: unsupported platform", platform, "error");
    return;
  }
  const HealthConnect = findPlugin(["HealthConnect", "CapacitorHealthConnect", "HealthConnectPlugin"]);
  if (!HealthConnect) {
    log("capacitor-health-connect plugin not found", "Registered plugin names: " + registeredNames().join(", "), "error");
    dot("dot-vitals", "err");
    return;
  }
  const end = new Date();
  const start = new Date(end.getTime() - 30 * DAY);
  try {
    const availability = await HealthConnect.checkAvailability();
    log("Health Connect availability", availability);
    const types = Object.keys(HC_TYPES);
    try {
      await HealthConnect.requestHealthPermissions({ read: types, write: [] });
    } catch (err) {
      log("Health Connect permission dialog", String(err), "error");
    }
    // ask again what is granted: a dismissed dialog reports nothing, even for permissions given earlier
    const perm = await HealthConnect.checkHealthPermissions({ read: types, write: [] });
    log("Health Connect permissions", perm);
    const granted = new Set((perm?.grantedPermissions || []).map((p) => String(p).split(".").pop()));

    const read = {};
    const raw = {};
    for (const type of types) {
      const [permission, dataType, unit] = HC_TYPES[type];
      const allowed = granted.has(permission);
      S.hcPermissions[dataType] = allowed;
      if (!allowed) {
        read[type] = { allowed: false, count: 0, unit };
        continue;
      }
      try {
        raw[type] = await readAllRecords(HealthConnect, type, start, end);
        read[type] = { allowed: true, count: raw[type].length, unit };
        log(`${HC_LABELS[type]}: ${raw[type].length} records`, raw[type].slice(0, 3));
      } catch (err) {
        read[type] = { allowed: true, count: 0, unit, error: String(err) };
        log(`${HC_LABELS[type]}: read failed`, String(err), "error");
      }
    }

    const sleep = { records: raw.SleepSession || [] };
    S.sleep = parseSleep(sleep);
    S.sleepSessions = sleepSessionsAndroid(sleep);
    S.heartRate = heartRateRecords(raw.HeartRateSeries || []);
    S.vitals = {
      resting: pointRecords(raw.RestingHeartRate || [], "rhr", "bpm", (r) => r.beatsPerMinute),
      resp: pointRecords(raw.RespiratoryRate || [], "resp", "rate", (r) => r.rate),
      spo2: pointRecords(raw.OxygenSaturation || [], "spo2", "percent", (r) => r.percentage?.value),
    };
    if (read.HeartRateSeries.allowed) read.HeartRateSeries.count = S.heartRate.reduce((n, r) => n + r.samples.length, 0);
    S.hcRead = read;
    const failed = Object.values(read).some((r) => r.error);
    dot("dot-vitals", failed ? "err" : granted.size ? "on" : "off");
    renderAll();
  } catch (err) {
    log("Sleep & vitals call threw an error", String(err), "error");
    dot("dot-vitals", "err");
  }
}

// --- App Usage (UsageStats) --------------------------------------------------
const USAGE_DAYS = 7; // days of history to fetch; older days may be empty on the phone

function renderAppUsage() {
  const body = $("usagestats-body");
  if (!body) return;
  const sub = $("usage-sub");
  const chrono = S.usageDays || []; // oldest -> newest, for the chart
  if (!chrono.length) {
    body.classList.add("empty");
    body.innerHTML = "No app usage stats loaded yet.";
    if (sub) sub.textContent = "";
    return;
  }
  body.classList.remove("empty");
  const days = [...chrono].reverse(); // newest first, for the slides
  if (sub) sub.textContent = `last ${days.length} days`;

  const prevScroll = body.querySelector(".usage-swipe")?.scrollLeft || 0;
  const withData = days.filter((d) => d.totalMs > 0);
  const avgMs = withData.length ? withData.reduce((a, d) => a + d.totalMs, 0) / withData.length : 0;

  const overview =
    statHtml([
      ["avg / day", fmtDur(avgMs)],
      ["days with data", `${withData.length}/${days.length}`],
    ]) +
    barsSvg(chrono.map((d) => d.totalMs / 60000), chrono.map((d) => `${d.date}: ${fmtDur(d.totalMs)}`), "violet") +
    `<div class="axis"><span>${esc(chrono[0].date)}</span><span>minutes per day</span><span>${esc(chrono[chrono.length - 1].date)}</span></div>`;

  const slides = days
    .map((d) => {
      const ms = new Date(`${d.date}T00:00:00`).getTime(); // local midnight
      const top = [...d.apps].sort((a, b) => b.totalTimeMillis - a.totalTimeMillis).slice(0, 10);
      const max = top.length ? top[0].totalTimeMillis : 1;
      const rows = top
        .map(
          (s) =>
            `<div class="hbar"><div class="lbl"><span>${esc(s.packageName)}</span><span>${esc(fmtDur(s.totalTimeMillis))}</span></div>` +
            `<div class="track"><div class="fill" style="width:${((s.totalTimeMillis / max) * 100).toFixed(1)}%"></div></div></div>`
        )
        .join("");
      return (
        `<div class="usage-slide">` +
        `<div class="usage-slide-head"><span class="d">${esc(fmtDay(ms))}</span><span class="tot">${esc(fmtDur(d.totalMs))}</span></div>` +
        `<div class="sub">${d.apps.length} apps</div>` +
        (rows || `<div class="empty" style="margin-top:10px">No data for this day (older than the phone keeps events?)</div>`) +
        `</div>`
      );
    })
    .join("");

  body.innerHTML =
    overview +
    `<div class="usage-swipe">${slides}</div>` +
    `<div class="usage-pos" id="usage-pos">1 / ${days.length} · swipe for older days</div>`;

  const sw = body.querySelector(".usage-swipe");
  sw.scrollLeft = prevScroll; // keep position when other cards trigger a re-render
  const update = () => {
    const i = Math.round(sw.scrollLeft / (sw.clientWidth + 12));
    const pos = $("usage-pos");
    if (pos) pos.textContent = `${Math.min(i + 1, days.length)} / ${days.length} · ${days[Math.min(i, days.length - 1)].date}`;
  };
  sw.addEventListener("scroll", update, { passive: true });
  update();
}

async function connectUsageStats() {
  if (!window.Capacitor?.isNativePlatform()) {
    log("UsageStats: not running as a native app (browser tab)", undefined, "error");
    return;
  }
  const UsageStats = findPlugin(["UsageStats", "UsageStatsPlugin"]);
  if (!UsageStats) {
    log("UsageStats plugin not found on window.Capacitor.Plugins", "Registered plugin names: " + registeredNames().join(", "), "error");
    dot("dot-usagestats", "err");
    return;
  }
  try {
    const perm = await UsageStats.checkPermission();
    log("UsageStats permission result", perm);
    if (!perm.granted && perm.result !== "granted") {
      log("UsageStats permission not granted. Requesting permission...", undefined, "error");
      await UsageStats.requestPermission();
      dot("dot-usagestats", "err");
      alert("Please grant Usage Access permission in Settings, then tap Connect again.");
      return;
    }

    // Completed days only: 1 = yesterday ... USAGE_DAYS days ago (today is excluded)
    const days = await fetchScreenTimeDays(USAGE_DAYS);
    S.usageDays = days;
    S.usageSelected = null;
    S.appUsage = days.length ? days[days.length - 1].apps : []; // yesterday, kept for compatibility

    log(
      `UsageStats: ${days.length} days fetched`,
      days.map((d) => `${d.date}: ${fmtDur(d.totalMs)} (${d.apps.length} apps)`)
    );

    dot("dot-usagestats", days.length ? "on" : "err");
    renderAll();
  } catch (err) {
    log("UsageStats call threw an error", String(err), "error");
    dot("dot-usagestats", "err");
  }
}

// --- Account & sync ------------------------------------------------------------
// Sync re-reads sleep, steps and screen time from the phone, then POSTs them to the StressLess API with the
// signed-in user's Supabase token. The API scores each night and stores everything under that user (RLS).
const API_URL = (() => {
  try {
    return localStorage.getItem("API_URL") || window.APP_CONFIG?.API_URL || "";
  } catch {
    return window.APP_CONFIG?.API_URL || "";
  }
})().replace(/\/+$/, "");

function syncStatus(text, level = "") {
  const el = $("sync-status");
  el.hidden = !text;
  el.className = `sync-status ${level}`;
  el.textContent = text || "";
}

function renderAccount() {
  const user = Auth.user();
  $("signin-form").hidden = Boolean(user);
  $("signed-in").hidden = !user;
  $("account-email").textContent = user?.email || "";
  let last = null;
  try {
    last = localStorage.getItem("LAST_SYNC");
  } catch {}
  $("last-sync").textContent = user && last ? `last sync ${fmtDay(Number(last))} ${fmtTime(Number(last))}` : "";
  if (!Auth.configured()) syncStatus("Supabase is not configured: copy www/config.example.js to www/config.js and rebuild.", "err");
}

async function signIn(e) {
  e.preventDefault();
  const btn = $("btn-signin");
  btn.disabled = true;
  syncStatus("Signing in…");
  try {
    const s = await Auth.signIn($("signin-email").value.trim(), $("signin-password").value);
    $("signin-password").value = "";
    log("Signed in", { email: s.user.email });
    syncStatus("");
  } catch (err) {
    log("Sign-in failed", String(err), "error");
    syncStatus(err.message, "err");
  } finally {
    btn.disabled = false;
    renderAccount();
  }
}

// Every foreground session and screen/lock event of the last USAGE_DAYS days up to now, unfiltered: the backend
// decides what to keep. Re-sending overlapping days is fine, sessions are keyed by package + start.
async function fetchUsageSessions() {
  const UsageStats = findPlugin(["UsageStats", "UsageStatsPlugin"]);
  if (!UsageStats?.getUsageSessions) return null;
  const perm = await UsageStats.checkPermission();
  if (!perm.granted && perm.result !== "granted") return null;
  const startTime = dayRange(USAGE_DAYS).startTime;
  const res = await UsageStats.getUsageSessions({ startTime, endTime: Date.now() });
  log(`Usage sessions: ${res.sessions.length} sessions, ${res.screenEvents.length} screen events`);
  return res;
}

// A random id for this install: each phone becomes its own connection in provider_connections.
function installId() {
  try {
    let id = localStorage.getItem("INSTALL_ID");
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem("INSTALL_ID", id);
    }
    return id;
  } catch {
    return (window.__installId ||= crypto.randomUUID());
  }
}

function syncPayload(usage) {
  return {
    device: {
      installId: installId(),
      platform: window.Capacitor?.getPlatform?.() || "web",
      timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      tzOffsetMin: -new Date().getTimezoneOffset(),
    },
    permissions: { app_usage: Boolean(usage), ...S.hcPermissions },
    sleep: S.sleepSessions,
    heartRate: S.heartRate,
    restingHeartRate: S.vitals.resting,
    oxygenSaturation: S.vitals.spo2,
    respiratoryRate: S.vitals.resp,
    steps: S.steps.map((s) => ({ date: dayKey(s.ms), steps: Math.round(s.value) })),
    screenTime: usage
      ? {
          from: usage.startTime,
          to: usage.endTime,
          sessions: usage.sessions,
          screenEvents: usage.screenEvents,
          launcherPackage: usage.launcherPackage,
          selfPackage: usage.selfPackage,
        }
      : null,
  };
}

async function syncToBackend() {
  const btn = $("btn-sync");
  btn.disabled = true;
  try {
    if (!API_URL || API_URL.includes("your-app")) throw new Error("API_URL is not set in www/config.js");
    if (window.Capacitor?.isNativePlatform()) {
      syncStatus("Reading sleep, heart rate, vitals, steps and screen time from the phone…");
      await connectVitals();
      await connectHealth();
      await connectUsageStats();
    }
    let usage = null;
    try {
      usage = await fetchUsageSessions();
    } catch (err) {
      log("Usage sessions failed", String(err), "error");
    }
    const payload = syncPayload(usage);
    const vitalsCount = payload.restingHeartRate.length + payload.oxygenSaturation.length + payload.respiratoryRate.length;
    if (!payload.sleep.length && !payload.heartRate.length && !vitalsCount && !payload.steps.length && !payload.screenTime?.sessions.length) {
      syncStatus("Nothing to sync yet: no sleep, heart rate, vitals, steps or screen time could be read (check permissions above).", "err");
      return;
    }

    syncStatus("Uploading…");
    const token = await Auth.accessToken();
    if (!token) throw new Error("Signed out: please sign in again.");
    const res = await fetch(`${API_URL}/api/sync`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) {
      Auth.invalidate();
      throw new Error(data.error || "Session expired: please sign in again.");
    }
    if (res.status === 403 && String(data.error).startsWith("consent_required")) {
      $("consent").hidden = false;
      syncStatus("");
      return;
    }
    if (!res.ok) throw new Error(data.error || `Sync failed (${res.status})`);

    log("Sync stored", data);
    try {
      localStorage.setItem("LAST_SYNC", String(Date.now()));
    } catch {}
    const n = data.stored;
    const lastNight = data.nights?.[data.nights.length - 1];
    syncStatus(
      `Synced ${n.nights} nights (${n.nights_with_vitals} with vitals), ${n.heart_rate_days} days of heart rate ` +
        `(${fmtNum(n.heart_rate_samples)} minutes), ${n.resting_hr} resting HR, ${n.resp_rate} breathing rate and ${n.spo2} blood oxygen readings, ` +
        `${n.step_days} days of steps, ${n.screen_sessions} app sessions (${n.screen_days} days).` +
        (lastNight ? ` Sleep score ${lastNight.night}: ${lastNight.score} (${lastNight.rating}).` : ""),
      "ok"
    );
  } catch (err) {
    log("Sync failed", String(err), "error");
    syncStatus(err.message || String(err), "err");
  } finally {
    btn.disabled = false;
    renderAccount();
  }
}

$("signin-form").addEventListener("submit", signIn);
$("btn-signout").addEventListener("click", async () => {
  await Auth.signOut();
  syncStatus("");
  renderAccount();
});
$("btn-sync").addEventListener("click", syncToBackend);
$("btn-consent").addEventListener("click", async () => {
  try {
    await Auth.giveConsent();
    $("consent").hidden = true;
    log("Consent saved");
    await syncToBackend();
  } catch (err) {
    log("Saving consent failed", String(err), "error");
    syncStatus(err.message || String(err), "err");
  }
});
renderAccount();

$("btn-calendar")?.addEventListener("click", connectCalendar);
$("btn-health")?.addEventListener("click", connectHealth);
$("btn-vitals")?.addEventListener("click", connectVitals);
$("btn-usagestats")?.addEventListener("click", connectUsageStats);

renderAll();

if (!window.Capacitor?.isNativePlatform()) {
  log("Running in a plain browser tab: native plugins are unavailable here.", undefined, "error");
} else {
  log("Native platform detected", { platform: window.Capacitor.getPlatform() });
  log("Plugins registered on window.Capacitor.Plugins", Object.keys(window.Capacitor.Plugins || {}));
}