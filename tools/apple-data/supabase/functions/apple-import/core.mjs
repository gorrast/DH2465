// Standalone, append-only importer. No arbitrary table names, SQL, updates,
// deletes, connection changes, or shared-health-summary writes are exposed.
export const TABLES = ["source_records", "daily_metrics"];
const SOURCES = new Set(["apple_health", "apple_screen_time"]);
const METRICS = new Set(["apple_screen.total_seconds", "apple_screen.first_active_unix_s", "apple_screen.last_active_unix_s"]);
const HEALTH_TYPES = new Set(["heart_rate", "resting_heart_rate", "hrv_sdnn", "steps"]);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const LIMIT = 500, MAX_BYTES = 1024 * 1024;
const RECORD_KEYS = new Set(["source", "data_type", "source_record_id", "data_origin", "start_at", "end_at",
  "start_offset_min", "end_offset_min", "value", "unit", "payload", "source_modified_at", "user_id", "connection_id"]);
const METRIC_KEYS = new Set(["source", "day", "metric_key", "value", "user_id"]);
class Failure extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
const fail = (status, message) => { throw new Failure(status, message); };
const object = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
const finite = (v) => (typeof v === "number" || (typeof v === "string" && /^-?\d+(\.\d+)?([eE][+-]?\d+)?$/.test(v))) && Number.isFinite(Number(v));
const stamp = (v) => typeof v === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
const date = (v) => typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) && !Number.isNaN(Date.parse(v)) && new Date(v).toISOString().slice(0, 10) === v;
const text = (v, n) => typeof v === "string" && v.length >= 1 && v.length <= n;
const offset = (v) => v === null || Number.isInteger(v) && Math.abs(v) <= 840;

export function validateRows(table, input, userId) {
  if (!TABLES.includes(table) || !Array.isArray(input) || !input.length || input.length > LIMIT) fail(400, "Invalid table or batch size.");
  const seen = new Set();
  return input.map((r) => {
    if (!object(r) || Object.keys(r).some((k) => !(table === "source_records" ? RECORD_KEYS : METRIC_KEYS).has(k))) fail(400, "Unexpected row fields.");
    if (!SOURCES.has(r.source) || r.user_id != null && r.user_id !== userId || r.connection_id != null) fail(403, "Row ownership/source is not permitted.");
    if (table === "daily_metrics") {
      if (r.source !== "apple_screen_time" || !date(r.day) || !METRICS.has(r.metric_key) || !finite(r.value) || Number(r.value) < 0) fail(400, "Invalid Apple daily metric.");
      if (r.metric_key === "apple_screen.total_seconds" && Number(r.value) > 26 * 3600) fail(400, "Invalid daily duration.");
    } else {
      if (!text(r.source_record_id, 200) || !/^[a-zA-Z0-9_.:-]+$/.test(r.source_record_id) || !stamp(r.start_at) ||
          r.end_at !== null && (!stamp(r.end_at) || Date.parse(r.end_at) < Date.parse(r.start_at)) ||
          !offset(r.start_offset_min) || !offset(r.end_offset_min) || !object(r.payload) ||
          new TextEncoder().encode(JSON.stringify(r.payload)).length > 65536 ||
          r.data_origin !== null && !text(r.data_origin, 200) || r.unit !== null && !text(r.unit, 32) ||
          r.value !== null && !finite(r.value) || r.source_modified_at !== null && !stamp(r.source_modified_at)) fail(400, "Invalid source record.");
      if (r.source === "apple_health") {
        if (!HEALTH_TYPES.has(r.data_type) && !(typeof r.data_type === "string" && /^ah_[a-z0-9_]{1,37}$/.test(r.data_type))) fail(400, "Invalid Apple Health data type.");
        const units = {heart_rate: "count/min", resting_heart_rate: "count/min", hrv_sdnn: "ms", steps: "count"};
        if (HEALTH_TYPES.has(r.data_type) && (r.unit !== units[r.data_type] || r.value === null || Number(r.value) < 0)) fail(400, "Invalid canonical Health value/unit.");
      } else {
        if (!["app_usage", "apple_screen_session"].includes(r.data_type) || r.unit !== "min" || !text(r.payload.bundle_id, 200) || !text(r.payload.device_id, 200)) fail(400, "Invalid Screen Time record.");
        if (r.data_type === "app_usage" && (r.end_at === null || r.value === null || Number(r.value) < 0 || r.payload.usable_duration !== true ||
            Math.abs((Date.parse(r.end_at) - Date.parse(r.start_at)) / 60000 - Number(r.value)) > 0.001)) fail(400, "App usage must have a valid measured interval.");
        if (r.data_type === "apple_screen_session" && r.value !== null) fail(400, "Incomplete focus records cannot carry a duration.");
      }
    }
    const id = table === "source_records" ? `${r.source}/${r.source_record_id}` : `${r.day}/${r.metric_key}`;
    if (seen.has(id)) fail(400, "Duplicate key inside batch.");
    seen.add(id);
    const row = {...r, user_id: userId};
    delete row.connection_id; // no privilege to attach an existing connection
    return row;
  });
}

async function readJSON(req) {
  if (!(req.headers.get("content-type") || "").toLowerCase().startsWith("application/json")) fail(415, "Expected JSON.");
  if (Number(req.headers.get("content-length")) > MAX_BYTES) fail(413, "Batch exceeds 1 MiB.");
  const reader = req.body?.getReader();
  if (!reader) fail(400, "Missing JSON body.");
  let size = 0; const chunks = [];
  while (true) {
    const {done, value} = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_BYTES) { await reader.cancel(); fail(413, "Batch exceeds 1 MiB."); }
    chunks.push(value);
  }
  const data = new Uint8Array(size); let at = 0;
  for (const chunk of chunks) { data.set(chunk, at); at += chunk.length; }
  try { return JSON.parse(new TextDecoder("utf-8", {fatal: true}).decode(data)); }
  catch { fail(400, "Invalid JSON."); }
}

export function createHandler(env, fetcher = fetch) {
  return async (req) => {
    const answer = (body, status = 200) => new Response(JSON.stringify(body), {status, headers: {"Content-Type": "application/json", "Cache-Control": "no-store"}});
    try {
      if (!["GET", "POST"].includes(req.method)) fail(405, "Only GET/POST are supported.");
      const base = env.SUPABASE_URL?.replace(/\/$/, "");
      const serviceKey = (env.SUPABASE_SECRET_KEYS && JSON.parse(env.SUPABASE_SECRET_KEYS).default) || env.SUPABASE_SERVICE_ROLE_KEY;
      const publicKey = (env.SUPABASE_PUBLISHABLE_KEYS && JSON.parse(env.SUPABASE_PUBLISHABLE_KEYS).default) || env.SUPABASE_ANON_KEY || env.SUPABASE_PUBLISHABLE_KEY;
      // The plural setting is authoritative when present, even if invalid.
      // Keep old single-user deployments working without widening access.
      const allowedIds = (env.APPLE_IMPORT_USER_IDS?.split(",") ?? [env.APPLE_IMPORT_USER_ID ?? ""])
        .map((id) => id.trim().toLowerCase());
      if (!base || !serviceKey || !publicKey || !allowedIds.every((id) => UUID.test(id))) {
        fail(503, "Importer requires a nonempty list of allowed user UUIDs.");
      }
      const project = new URL(base).hostname.split(".")[0];
      const auth = req.headers.get("Authorization") || "";
      if (!/^Bearer [^\s]+$/.test(auth)) fail(401, "A signed-in user session is required.");
      const userResponse = await fetcher(base + "/auth/v1/user", {headers: {apikey: publicKey, Authorization: auth}, redirect: "error"});
      if (!userResponse.ok) fail(401, "Session could not be verified.");
      const user = await userResponse.json();
      if (typeof user?.id !== "string" || !UUID.test(user.id) || user.is_anonymous ||
          !allowedIds.includes(user.id.toLowerCase())) fail(403, "This user is not allowed to import.");
      const uid = user.id;
      // No browser-supplied filters, table names, keys or tokens reach the DB.
      async function db(table, params, rows) {
        if (![...TABLES, "profiles", "sources", "data_types", "metric_definitions"].includes(table)) fail(400, "Table not allowed.");
        if (rows && !TABLES.includes(table)) fail(400, "Registry/profile writes are forbidden.");
        const headers = {apikey: serviceKey, "Content-Type": "application/json"};
        if (!serviceKey.startsWith("sb_")) headers.Authorization = "Bearer " + serviceKey;
        if (rows) headers.Prefer = "resolution=ignore-duplicates,return=representation";
        const response = await fetcher(base + "/rest/v1/" + table + "?" + new URLSearchParams(params), {
          method: rows ? "POST" : "GET", headers, redirect: "error", ...(rows ? {body: JSON.stringify(rows)} : {}),
        });
        if (!response.ok) fail(502, "Database request failed. No diagnostic data was returned.");
        return response.json();
      }
      const profile = await db("profiles", {select: "consented_at", user_id: "eq." + uid, limit: "1"});
      if (!profile[0]?.consented_at) fail(403, "Consent is required in your app before preview or upload.");
      const enabled = env.APPLE_IMPORT_ENABLED === "true";
      if (req.method === "GET") return answer({version: 1, contract_version: 3, user_id: uid, project_ref: project,
        mode: "append-only", tables: TABLES, enabled, writes_existing_rows: false, changes_schema: false});
      const body = await readJSON(req);
      if (!object(body) || Object.keys(body).some((k) => !["action", "table", "rows", "expected_user_id", "expected_project_ref"].includes(k)) ||
          !["preview", "insert"].includes(body.action)) fail(400, "Invalid import action.");
      if (body.expected_user_id !== uid || body.expected_project_ref !== project) fail(403, "Project/user approval does not match.");
      if (body.action === "insert" && !enabled) fail(403, "Uploads are disabled. Preview is still available.");
      const rows = validateRows(body.table, body.rows, uid);
      // Global registry definitions are read-only, even for this endpoint.
      const sourceKeys = [...new Set(rows.map((r) => r.source))];
      const sources = await db("sources", {select: "key,category,active", key: "in.(" + sourceKeys.join(",") + ")"});
      for (const key of sourceKeys) {
        const s = sources.find((s) => s.key === key);
        if (!s || !s.active || s.category !== (key === "apple_health" ? "health" : "screen")) fail(409, "Missing or incompatible source registration.");
      }
      const types = [...new Set(rows.map((r) => r.data_type || r.metric_key))];
      const registry = await db(body.table === "source_records" ? "data_types" : "metric_definitions", {
        select: body.table === "source_records" ? "key,category" : "key,unit", key: "in.(" + types.join(",") + ")"});
      for (const r of rows) {
        const definition = registry.find((d) => d.key === (r.data_type || r.metric_key));
        if (!definition || body.table === "daily_metrics" && definition.unit !== (r.metric_key.endsWith("total_seconds") ? "s" : "unix_s") ||
            body.table === "source_records" && r.source === "apple_screen_time" && definition.category !== "screen" ||
            body.table === "source_records" && HEALTH_TYPES.has(r.data_type) && definition.category !== (r.data_type === "steps" ? "activity" : "heart")) fail(409, "Missing or incompatible type/metric registration.");
      }
      if (body.action === "preview") {
        // Individual key lookups, grouped by source/date, return only identity
        // fields. No measurement values are included in preview responses.
        let existing = 0;
        const groups = new Map();
        for (const r of rows) {
          const group = body.table === "source_records" ? r.source : r.day;
          if (!groups.has(group)) groups.set(group, []);
          groups.get(group).push(body.table === "source_records" ? r.source_record_id : r.metric_key);
        }
        for (const [group, ids] of groups) {
          for (let i = 0; i < ids.length; i += 50) {
            const field = body.table === "source_records" ? "source_record_id" : "metric_key";
            const params = {user_id: "eq." + uid, select: field, [field]: "in.(" + ids.slice(i, i + 50).join(",") + ")", limit: "500"};
            params[body.table === "source_records" ? "source" : "day"] = "eq." + group;
            existing += (await db(body.table, params)).length;
          }
        }
        return answer({submitted: rows.length, would_insert: rows.length - existing, would_skip: existing, writes: 0});
      }
      const conflict = body.table === "source_records" ? "user_id,source,source_record_id" : "user_id,day,metric_key";
      const select = body.table === "source_records" ? "source_record_id" : "day,metric_key";
      const inserted = await db(body.table, {on_conflict: conflict, select}, rows);
      return answer({submitted: rows.length, inserted: inserted.length, skipped: rows.length - inserted.length});
    } catch (exc) {
      // Never log tokens, raw records or upstream error bodies.
      return answer({error: exc instanceof Failure ? exc.message : "Importer request failed safely."}, exc instanceof Failure ? exc.status : 502);
    }
  };
}
