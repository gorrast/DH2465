// native.js
// Bridges the dashboard to native plugins (calendar, Health Connect / HealthKit,
// background location) and renders everything as cards. Every native call is
// also written to the on-screen debug log at the bottom of the page.

const BACKEND_URL = "https://your-backend.example.com"; // point at your server/index.js deployment

// All fetched data lives here so renderers (and you, via the console) can reach it.
const S = (window.__app = {
  events: [],
  pings: [],
  steps: [], // [{ ms, value }] one per day
  workouts: [],
  sleep: [],
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
  try {
    const res = await fetch(`${BACKEND_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    log(`Backend ${path} → ${res.status}`, undefined, res.ok ? "ok" : "error");
  } catch (err) {
    log(`Backend ${path} unreachable (fine while testing without a server)`, String(err), "error");
  }
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

// --- Renderers ---------------------------------------------------------------
function renderTiles() {
  const stepsTotal = S.steps.reduce((a, s) => a + s.value, 0);
  const sleepHours = S.sleep.map((n) => n.hours).filter((h) => h > 0);
  const tile = (cls, num, cap) => `<div class="tile ${cls}"><div class="num">${num}</div><div class="cap">${cap}</div></div>`;
  $("tiles").innerHTML =
    tile("blue", S.events.length ? fmtNum(S.events.length) : "—", "calendar events") +
    tile("green", S.steps.length ? fmtNum(stepsTotal) : "—", "steps this year") +
    tile("violet", sleepHours.length ? (sleepHours.reduce((a, b) => a + b, 0) / sleepHours.length).toFixed(1) + " h" : "—", "avg sleep") +
    tile("amber", S.pings.length ? fmtNum(S.pings.length) : "—", "location pings");
}

function renderToday() {
  const today = startOfDay(Date.now());
  $("today-date").textContent = new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
  const evs = S.events.filter((e) => e.endDate > today && e.startDate < today + DAY);
  const pings = S.pings.filter((p) => p.time >= today);

  let html = "";
  if (!S.events.length && !S.pings.length) {
    $("today-body").innerHTML = `<div class="empty">Connect calendar and location to see today's plan next to where you've actually been.</div>`;
    return;
  }
  if (S.events.length) {
    html += evs.length
      ? evs.map(evRowHtml).join("")
      : `<div class="empty">No events on your calendar today.</div>`;
  }
  if (S.pings.length) {
    html += `<div class="day-head">Where you've been today</div>`;
    if (pings.length) {
      html += statHtml([
        ["pings today", fmtNum(pings.length)],
        ["first seen", fmtTime(pings[0].time)],
        ["last seen", fmtTime(pings[pings.length - 1].time)],
      ]);
      html += `<div class="sub">Comparing positions to event locations needs geocoding, which is the next step.</div>`;
    } else {
      html += `<div class="empty">No location pings yet today.</div>`;
    }
  }
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

function renderLocation() {
  const pings = S.pings;
  $("loc-sub").textContent = pings.length ? `${fmtNum(pings.length)} pings` : "";
  if (!pings.length) {
    $("loc-body").innerHTML = `<div class="empty">Connect background location to see your movement here. Pings arrive as you move.</div>`;
    return;
  }
  const pts = pings.slice(-300);
  const lat0 = pts.reduce((a, p) => a + p.lat, 0) / pts.length;
  const kx = Math.cos((lat0 * Math.PI) / 180);
  const xs = pts.map((p) => p.lon * kx), ys = pts.map((p) => p.lat);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const W = 300, H = 180, pad = 14;
  const spanX = maxX - minX || 1e-5, spanY = maxY - minY || 1e-5;
  const scale = Math.min((W - 2 * pad) / spanX, (H - 2 * pad) / spanY);
  const ox = (W - spanX * scale) / 2, oy = (H - spanY * scale) / 2;
  const px = (x) => (ox + (x - minX) * scale).toFixed(1);
  const py = (y) => (H - (oy + (y - minY) * scale)).toFixed(1);
  const line = pts.map((_, i) => `${px(xs[i])},${py(ys[i])}`).join(" ");
  const lastIdx = pts.length - 1;
  const svg =
    `<svg class="path" viewBox="0 0 ${W} ${H}"><polyline points="${line}"/>` +
    `<circle cx="${px(xs[0])}" cy="${py(ys[0])}" r="3"/>` +
    `<circle class="latest" cx="${px(xs[lastIdx])}" cy="${py(ys[lastIdx])}" r="5"/></svg>`;

  const last = pings[pings.length - 1];
  const recent = pings.slice(-5).reverse();
  $("loc-body").innerHTML =
    svg +
    `<div class="sub" style="margin:6px 0 10px">Your path (green = latest). Oldest of the last ${pts.length} pings to newest.</div>` +
    statHtml([
      ["latest", `${last.lat.toFixed(5)}, ${last.lon.toFixed(5)}`],
      ["accuracy", last.accuracy != null ? `±${Math.round(last.accuracy)} m` : "—"],
      ["at", fmtTime(last.time)],
    ]) +
    `<div class="day-head">Recent pings</div>` +
    recent
      .map(
        (p) =>
          `<div class="ev"><div class="t">${esc(fmtTime(p.time))}</div><div class="b"><div class="title">${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}</div>` +
          `<div class="meta">${p.accuracy != null ? "±" + Math.round(p.accuracy) + " m" : ""}</div></div></div>`
      )
      .join("");
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

function renderSleep() {
  if (!S.sleep.length) {
    $("sleep-body").innerHTML = `<div class="empty">No sleep sessions found in the last 30 days (or none loaded yet).</div>`;
    return;
  }
  const nights = S.sleep;
  const hours = nights.map((n) => n.hours);
  const avg = hours.reduce((a, b) => a + b, 0) / hours.length;
  const best = nights.reduce((b, n) => (n.hours > b.hours ? n : b), nights[0]);
  $("sleep-body").innerHTML =
    statHtml([
      ["avg / night", `${avg.toFixed(1)} h`],
      ["longest", `${best.hours.toFixed(1)} h`],
      ["nights", String(nights.length)],
    ]) +
    barsSvg(hours, nights.map((n) => `${fmtDay(n.startMs)}: ${n.hours.toFixed(1)} h`), "violet") +
    `<div class="axis"><span>${esc(fmtDay(nights[0].startMs))}</span><span>hours slept</span><span>${esc(fmtDay(nights[nights.length - 1].startMs))}</span></div>` +
    `<div class="day-head" style="margin-top:16px">Latest nights</div>` +
    nights
      .slice(-7)
      .reverse()
      .map(
        (n) =>
          `<div class="ev"><div class="t">${esc(fmtDay(n.startMs))}</div><div class="b"><div class="title">${esc(fmtTime(n.startMs))} → ${esc(fmtTime(n.endMs))}</div>` +
          `<div class="meta">${esc(fmtDur(n.endMs - n.startMs))}</div></div></div>`
      )
      .join("");
}

function renderAll() {
  renderTiles();
  renderToday();
  renderCalendar();
  renderLocation();
  renderSteps();
  renderWorkouts();
  renderSleep();
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
    // heart rate only comes inside workout records. Sleep is read in connectSleep().
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
    await postToBackend("/health/sync", { steps: S.steps, workouts: S.workouts });
  } catch (err) {
    log("Health call threw an error", String(err), "error");
    dot("dot-health", "err");
  }
}

// --- Background location -------------------------------------------------------
let pingCount = 0;
let renderQueued = false;
function queueRender() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => {
    renderQueued = false;
    renderTiles();
    renderToday();
    renderLocation();
  });
}

async function connectLocation() {
  if (!window.Capacitor?.isNativePlatform()) {
    log("Location: not running as a native app (browser tab)", undefined, "error");
    return;
  }
  const BackgroundGeolocation = window.Capacitor.Plugins?.BackgroundGeolocation;
  if (!BackgroundGeolocation) {
    log("Background location plugin not found on window.Capacitor.Plugins", "Registered plugin names: " + registeredNames().join(", "), "error");
    dot("dot-location", "err");
    return;
  }

  try {
    const watcherId = await BackgroundGeolocation.addWatcher(
      {
        backgroundMessage: "Correlate is checking your location against your calendar.",
        backgroundTitle: "Correlate running",
        requestPermissions: true,
        distanceFilter: 10, // metres; lowered for testing so pings arrive faster
      },
      (location, error) => {
        if (error) {
          log("Location watcher error", String(error), "error");
          return;
        }
        pingCount += 1;
        S.pings.push({
          lat: location.latitude,
          lon: location.longitude,
          accuracy: location.accuracy,
          time: location.time || Date.now(),
        });
        if (S.pings.length > 2000) S.pings.splice(0, S.pings.length - 2000);
        log(`Location ping #${pingCount}`, {
          lat: location.latitude,
          lon: location.longitude,
          accuracy: location.accuracy,
          time: new Date(location.time).toLocaleTimeString(),
        });
        queueRender();
        postToBackend("/location/ping", { lat: location.latitude, lon: location.longitude, timestamp: location.time });
      }
    );

    log("Location watcher started", { watcherId });
    dot("dot-location", "on");
    window.__watcherId = watcherId;
  } catch (err) {
    log("Location setup threw an error", String(err), "error");
    dot("dot-location", "err");
  }
}

// --- Sleep (separate plugin per platform) --------------------------------------
// Android -> capacitor-health-connect (raw SleepSessionRecord)
// iOS     -> @perfood/capacitor-healthkit (SleepData sample type)
function parseSleep(res) {
  const arr = res?.records || res?.result || res?.data || (Array.isArray(res) ? res : []);
  return arr
    .map((r) => {
      const startMs = toMs(r.startTime ?? r.startDate ?? r.start);
      const endMs = toMs(r.endTime ?? r.endDate ?? r.end);
      return { startMs, endMs, hours: (endMs - startMs) / 3600000 };
    })
    .filter((n) => Number.isFinite(n.startMs) && Number.isFinite(n.endMs) && n.hours > 0)
    .sort((a, b) => a.startMs - b.startMs);
}

async function connectSleep() {
  if (!window.Capacitor?.isNativePlatform()) {
    log("Sleep: not running as a native app (browser tab)", undefined, "error");
    return;
  }

  const platform = window.Capacitor.getPlatform(); // 'android' | 'ios'
  const end = new Date();
  const start = new Date(end.getTime() - 30 * DAY);

  if (platform === "android") {
    const HealthConnect = findPlugin(["HealthConnect", "CapacitorHealthConnect", "HealthConnectPlugin"]);
    if (!HealthConnect) {
      log("capacitor-health-connect plugin not found", "Registered plugin names: " + registeredNames().join(", "), "error");
      dot("dot-sleep", "err");
      return;
    }
    try {
      const availability = await HealthConnect.checkAvailability();
      log("Health Connect availability", availability);

      await HealthConnect.requestHealthPermissions({
        read: ["SleepSession"], // confirm this literal against the plugin's typings
        write: [],
      });

      const res = await HealthConnect.readRecords({
        type: "SleepSession", // confirm this literal against the plugin's typings
        timeRangeFilter: { type: "between", startTime: start, endTime: end },
      });
      log("Sleep records (raw response)", res);
      S.sleep = parseSleep(res);
      log(`Sleep: ${S.sleep.length} sessions parsed`);
      dot("dot-sleep", "on");
      renderAll();
    } catch (err) {
      log("Sleep (Android) call threw an error", String(err), "error");
      dot("dot-sleep", "err");
    }
  } else if (platform === "ios") {
    const HealthKit = findPlugin(["CapacitorHealthkit", "CapacitorHealthKit", "HealthKit"]);
    if (!HealthKit) {
      log("@perfood/capacitor-healthkit plugin not found", "Registered plugin names: " + registeredNames().join(", "), "error");
      dot("dot-sleep", "err");
      return;
    }
    try {
      await HealthKit.requestAuthorization({ all: [""], read: ["sleep"], write: [""] });
      const res = await HealthKit.queryHKitSampleType({
        sampleName: "sleep",
        startDate: start.toISOString(),
        endDate: end.toISOString(),
        limit: 0,
      });
      log("Sleep records (raw response)", res);
      S.sleep = parseSleep(res);
      dot("dot-sleep", "on");
      renderAll();
    } catch (err) {
      log("Sleep (iOS) call threw an error", String(err), "error");
      dot("dot-sleep", "err");
    }
  } else {
    log("Sleep: unsupported platform", platform, "error");
  }
}

$("btn-calendar").addEventListener("click", connectCalendar);
$("btn-health").addEventListener("click", connectHealth);
$("btn-sleep").addEventListener("click", connectSleep);
$("btn-location").addEventListener("click", connectLocation);

renderAll();

if (!window.Capacitor?.isNativePlatform()) {
  log("Running in a plain browser tab: native plugins are unavailable here.", undefined, "error");
} else {
  log("Native platform detected", { platform: window.Capacitor.getPlatform() });
  log("Plugins registered on window.Capacitor.Plugins", Object.keys(window.Capacitor.Plugins || {}));
}