import { createClient } from "npm:@supabase/supabase-js@2";

const GOOGLE_SCOPE = "https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/calendar.events.readonly";
const GOOGLE_PROVIDER_VALUES = ["google_calendar", "google", "google-calendar"];
const WINDOW_PAST_DAYS = 70;
const WINDOW_FUTURE_DAYS = 90;
const STATE_TTL_MS = 15 * 60 * 1000;
const BATCH_SIZE = 500;

type ActionBody = { action?: "authorize" | "status" | "sync" | "disconnect" };
type ProviderConnection = { id: string; user_id: string; status: string };
type GoogleAttendee = {
  email?: string;
  displayName?: string;
  responseStatus?: string;
  self?: boolean;
};

type GoogleEvent = {
  id?: string;
  status?: string;
  summary?: string;
  description?: string;
  location?: string;
  eventType?: string;
  attendees?: GoogleAttendee[];
  start?: { dateTime?: string; date?: string };
  end?: { dateTime?: string; date?: string };
};

type GoogleCalendarEvent = {
  calendarId: string;
  event: GoogleEvent;
};

function json(body: unknown, status = 200, headers: HeadersInit = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders(), ...headers },
  });
}

function corsHeaders() {
  const origin = Deno.env.get("APP_ORIGIN") ?? "*";
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Vary": "Origin",
  };
}

function redirectToApp(status: "connected" | "error") {
  const base = Deno.env.get("APP_URL");
  if (!base) throw new Error("Missing APP_URL");
  const target = new URL("/dashboard/connections", base);
  target.searchParams.set("calendar", status);
  return Response.redirect(target, 302);
}

function getAdminClient() {
  const url = Deno.env.get("SUPABASE_URL");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !key) throw new Error("Supabase server configuration is missing");
  return createClient(url, key, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

async function getUserId(request: Request): Promise<string> {
  const authorization = request.headers.get("Authorization");
  if (!authorization?.startsWith("Bearer ")) throw new Error("Sign in to continue");
  const supabase = getAdminClient();
  const { data, error } = await supabase.auth.getUser(authorization.slice(7));
  if (error || !data.user) throw new Error("Your session is invalid or expired");
  return data.user.id;
}

function requiredEnv(name: string): string {
  const value = Deno.env.get(name);
  if (!value) throw new Error(`Missing server setting: ${name}`);
  return value;
}

function toBase64Url(value: Uint8Array): string {
  let binary = "";
  for (const byte of value) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

function fromBase64(value: string): Uint8Array {
  const binary = atob(value);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return toBase64Url(new Uint8Array(digest));
}

async function getEncryptionKey(): Promise<CryptoKey> {
  const bytes = fromBase64(requiredEnv("GOOGLE_TOKEN_ENCRYPTION_KEY"));
  if (bytes.length !== 32) throw new Error("Token encryption key must decode to 32 bytes");
  return crypto.subtle.importKey("raw", bytes, "AES-GCM", false, ["encrypt", "decrypt"]);
}

async function encryptSecret(value: string): Promise<string> {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const encrypted = new Uint8Array(await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    await getEncryptionKey(),
    new TextEncoder().encode(value),
  ));
  return toBase64Url(new Uint8Array([...iv, ...encrypted]));
}

async function decryptSecret(value: string): Promise<string> {
  const data = fromBase64(value.replaceAll("-", "+").replaceAll("_", "/") + "===".slice((value.length + 3) % 4));
  const iv = data.slice(0, 12);
  const encrypted = data.slice(12);
  const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv }, await getEncryptionKey(), encrypted);
  return new TextDecoder().decode(plain);
}

function googleRedirectUri(): string {
  return requiredEnv("GOOGLE_REDIRECT_URI");
}

function googleAuthUrl(state: string): string {
  const url = new URL("https://accounts.google.com/o/oauth2/v2/auth");
  url.searchParams.set("client_id", requiredEnv("GOOGLE_CLIENT_ID"));
  url.searchParams.set("redirect_uri", googleRedirectUri());
  url.searchParams.set("response_type", "code");
  url.searchParams.set("access_type", "offline");
  url.searchParams.set("prompt", "consent");
  url.searchParams.set("scope", GOOGLE_SCOPE);
  url.searchParams.set("state", state);
  return url.toString();
}

async function authorize(request: Request) {
  const userId = await getUserId(request);
  const supabase = getAdminClient();
  const stateBytes = crypto.getRandomValues(new Uint8Array(32));
  const state = toBase64Url(stateBytes);
  const { data: connection, error: connectionError } = await supabase
    .from("provider_connections")
    .insert({ user_id: userId, provider: "google_calendar", status: "pending", scopes: [GOOGLE_SCOPE] })
    .select("id")
    .single();
  if (connectionError || !connection) throw new Error("Could not start calendar connection");

  const { error: credentialError } = await supabase.from("provider_connection_credentials").insert({
    provider_connection_id: connection.id,
    oauth_state_hash: await sha256(state),
    oauth_state_created_at: new Date().toISOString(),
  });
  if (credentialError) {
    await supabase.from("provider_connections").delete().eq("id", connection.id).eq("user_id", userId);
    throw new Error("Could not securely start calendar connection");
  }
  return json({ authorizationUrl: googleAuthUrl(state) });
}

async function exchangeCode(code: string) {
  const body = new URLSearchParams({
    code,
    client_id: requiredEnv("GOOGLE_CLIENT_ID"),
    client_secret: requiredEnv("GOOGLE_CLIENT_SECRET"),
    redirect_uri: googleRedirectUri(),
    grant_type: "authorization_code",
  });
  const response = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  const result = await response.json();
  if (!response.ok) throw new Error("Google could not complete the authorization");
  return result as { access_token?: string; refresh_token?: string };
}

async function oauthCallback(request: Request) {
  const url = new URL(request.url);
  const state = url.searchParams.get("state");
  const code = url.searchParams.get("code");
  if (!state) return redirectToApp("error");

  const supabase = getAdminClient();
  const stateHash = await sha256(state);
  const { data: credential } = await supabase
    .from("provider_connection_credentials")
    .select("provider_connection_id, oauth_state_created_at")
    .eq("oauth_state_hash", stateHash)
    .maybeSingle();
  if (!credential?.oauth_state_created_at || !credential.provider_connection_id) return redirectToApp("error");

  const createdAt = new Date(credential.oauth_state_created_at).getTime();
  if (!Number.isFinite(createdAt) || Date.now() - createdAt > STATE_TTL_MS || createdAt > Date.now() + 60_000 || url.searchParams.has("error")) {
    await supabase.from("provider_connection_credentials")
      .update({ oauth_state_hash: null, oauth_state_created_at: null })
      .eq("provider_connection_id", credential.provider_connection_id);
    await supabase.from("provider_connections")
      .update({ status: "error" })
      .eq("id", credential.provider_connection_id);
    return redirectToApp("error");
  }
  if (!code) return redirectToApp("error");

  const { data: connection } = await supabase.from("provider_connections")
    .select("id, user_id")
    .eq("id", credential.provider_connection_id)
    .maybeSingle();
  if (!connection) return redirectToApp("error");

  try {
    const tokens = await exchangeCode(code);
    if (!tokens.refresh_token) throw new Error("Google did not return a refresh token");
    const ciphertext = await encryptSecret(tokens.refresh_token);
    const { error: credentialError } = await supabase.from("provider_connection_credentials")
      .update({
        oauth_state_hash: null,
        oauth_state_created_at: null,
        refresh_token_ciphertext: ciphertext,
        updated_at: new Date().toISOString(),
      })
      .eq("provider_connection_id", connection.id);
    if (credentialError) throw new Error("Could not store the encrypted calendar credential");

    const { error: connectionError } = await supabase.from("provider_connections")
      .update({ status: "connected", connected_at: new Date().toISOString() })
      .eq("id", connection.id)
      .eq("user_id", connection.user_id);
    if (connectionError) throw new Error("Could not finish the calendar connection");
    return redirectToApp("connected");
  } catch (error) {
    console.error("Google Calendar OAuth callback failed", error);
    await supabase.from("provider_connection_credentials")
      .update({ oauth_state_hash: null, oauth_state_created_at: null })
      .eq("provider_connection_id", connection.id);
    await supabase.from("provider_connections")
      .update({ status: "error" })
      .eq("id", connection.id)
      .eq("user_id", connection.user_id);
    return redirectToApp("error");
  }
}

function isoDate(date: Date): string {
  return date.toISOString();
}

function eventDate(value: { dateTime?: string; date?: string } | undefined): string | null {
  if (value?.dateTime) return new Date(value.dateTime).toISOString();
  if (value?.date) return new Date(`${value.date}T00:00:00.000Z`).toISOString();
  return null;
}

async function refreshGoogleToken(refreshToken: string): Promise<string> {
  const body = new URLSearchParams({
    client_id: requiredEnv("GOOGLE_CLIENT_ID"),
    client_secret: requiredEnv("GOOGLE_CLIENT_SECRET"),
    refresh_token: refreshToken,
    grant_type: "refresh_token",
  });
  const response = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  const result = await response.json();
  if (!response.ok || typeof result.access_token !== "string") {
    throw new Error("Google calendar authorization expired; reconnect your calendar");
  }
  return result.access_token;
}

function shouldImportCalendar(_calendarId: string, _summary?: string): boolean {
  return true;
}

async function listGoogleCalendars(accessToken: string): Promise<Array<{ id: string; summary?: string }>> {
  const calendars: Array<{ id: string; summary?: string }> = [];
  let pageToken: string | undefined;

  do {
    const url = new URL("https://www.googleapis.com/calendar/v3/users/me/calendarList");
    url.searchParams.set("showHidden", "false");
    url.searchParams.set("minAccessRole", "reader");
    url.searchParams.set("maxResults", "250");
    if (pageToken) url.searchParams.set("pageToken", pageToken);

    const response = await fetch(url, { headers: { Authorization: `Bearer ${accessToken}` } });
    const result = await response.json();
    if (!response.ok) {
      if (response.status === 403) {
        throw new Error("Google Calendar access is missing for your account. Please reconnect your calendar to allow reading all available calendars.");
      }
      throw new Error("Google could not list available calendars");
    }

    if (Array.isArray(result.items)) {
      for (const calendar of result.items as Array<{ id?: string; summary?: string }>) {
        if (!calendar.id) continue;
        if (shouldImportCalendar(calendar.id, calendar.summary)) {
          calendars.push({ id: calendar.id, summary: calendar.summary });
        }
      }
    }
    pageToken = typeof result.nextPageToken === "string" ? result.nextPageToken : undefined;
  } while (pageToken);

  return calendars;
}

function shouldImportGoogleEvent(event: GoogleEvent): boolean {
  return !!event.id && event.status !== "cancelled";
}

async function readGoogleEvents(accessToken: string): Promise<GoogleCalendarEvent[]> {
  const now = new Date();
  const timeMin = new Date(now.getTime() - WINDOW_PAST_DAYS * 86_400_000);
  const timeMax = new Date(now.getTime() + WINDOW_FUTURE_DAYS * 86_400_000);
  const calendars = await listGoogleCalendars(accessToken);
  const events: GoogleCalendarEvent[] = [];

  for (const { id: calendarId } of calendars) {
    let pageToken: string | undefined;
    do {
      const url = new URL(`https://www.googleapis.com/calendar/v3/calendars/${encodeURIComponent(calendarId)}/events`);
      url.searchParams.set("timeMin", isoDate(timeMin));
      url.searchParams.set("timeMax", isoDate(timeMax));
      url.searchParams.set("singleEvents", "true");
      url.searchParams.set("orderBy", "startTime");
      url.searchParams.set("maxResults", "2500");
      if (pageToken) url.searchParams.set("pageToken", pageToken);

      const response = await fetch(url, { headers: { Authorization: `Bearer ${accessToken}` } });
      const result = await response.json();
      if (!response.ok) throw new Error("Google could not read calendar events");

      if (Array.isArray(result.items)) {
        for (const item of result.items as GoogleEvent[]) {
          if (!shouldImportGoogleEvent(item)) continue;
          events.push({ calendarId, event: item });
        }
      }
      pageToken = typeof result.nextPageToken === "string" ? result.nextPageToken : undefined;
    } while (pageToken);
  }

  return events;
}

async function syncConnection(supabase: ReturnType<typeof getAdminClient>, userId: string, connection: ProviderConnection) {
  const { data: credential, error } = await supabase.from("provider_connection_credentials")
    .select("refresh_token_ciphertext")
    .eq("provider_connection_id", connection.id)
    .maybeSingle();
  if (error || !credential?.refresh_token_ciphertext) throw new Error("Calendar credential is missing; reconnect the calendar");

  try {
    const refreshToken = await decryptSecret(credential.refresh_token_ciphertext);
    const accessToken = await refreshGoogleToken(refreshToken);
    const googleEvents = await readGoogleEvents(accessToken);
    const rows = googleEvents.flatMap(({ calendarId, event }) => {
      const startsAt = eventDate(event.start);
      const endsAt = eventDate(event.end);
      if (!event.id || event.status === "cancelled" || !startsAt || !endsAt) return [];
      const guests = (event.attendees ?? [])
  .filter((attendee) => !attendee.self)
  .map((attendee) => ({
    email: attendee.email ?? null,
    name: attendee.displayName ?? null,
    response_status: attendee.responseStatus ?? null,
  }));

return [{
  user_id: userId,
  provider: "google_calendar",
  provider_event_id: `${calendarId}:${event.id}`,
  title: event.summary ?? "Untitled event",
  category: "uncategorized",
  starts_at: startsAt,
  ends_at: endsAt,
  location: event.location ?? null,
  description: event.description ?? null,
  guests,
}];
    });

    const { error: clearError } = await supabase.from("calendar_events")
      .delete()
      .eq("user_id", userId)
      .in("provider", GOOGLE_PROVIDER_VALUES);
    if (clearError) throw new Error("Could not refresh calendar events");

    for (let i = 0; i < rows.length; i += BATCH_SIZE) {
      const { error: upsertError } = await supabase.from("calendar_events")
        .upsert(rows.slice(i, i + BATCH_SIZE), { onConflict: "user_id,provider,provider_event_id" });
      if (upsertError) throw new Error("Could not save calendar events");
    }

    const syncedAt = new Date().toISOString();
    const { error: updateError } = await supabase.from("provider_connections")
      .update({ last_synced_at: syncedAt, status: "connected" })
      .eq("id", connection.id)
      .eq("user_id", userId);
    if (updateError) throw new Error("Events synced but the sync status could not be saved");
    return rows.length;
  } catch (error) {
    if (error instanceof Error && error.message.includes("reconnect")) {
      await supabase.from("provider_connections")
        .update({ status: "error" })
        .eq("id", connection.id)
        .eq("user_id", userId);
    }
    throw error;
  }
}

async function status(request: Request) {
  const userId = await getUserId(request);
  const supabase = getAdminClient();
  const { data, error } = await supabase.from("provider_connections")
    .select("id, status, connected_at, last_synced_at, provider_account_id")
    .eq("user_id", userId)
    .eq("provider", "google_calendar")
    .order("created_at", { ascending: false });
  if (error) throw new Error("Could not load calendar connections");
  return json({ connections: data ?? [] });
}
async function sync(request: Request) {
  const userId = await getUserId(request);
  const supabase = getAdminClient();
  const { data: connections, error } = await supabase.from("provider_connections")
    .select("id, user_id, status")
    .eq("user_id", userId)
    .eq("provider", "google_calendar")
    .eq("status", "connected");
  if (error) throw new Error("Could not load calendar connections");
  if (!connections?.length) throw new Error("Connect a Google Calendar first");

  let imported = 0;
  for (const connection of connections) imported += await syncConnection(supabase, userId, connection);
  return json({ imported });
}

async function disconnect(request: Request) {
  const userId = await getUserId(request);
  const supabase = getAdminClient();
  const { data: connections, error } = await supabase.from("provider_connections")
    .select("id")
    .eq("user_id", userId)
    .eq("provider", "google_calendar")
    .eq("status", "connected");
  if (error) throw new Error("Could not load calendar connections");

  for (const connection of connections ?? []) {
    const { data: credential } = await supabase.from("provider_connection_credentials")
      .select("refresh_token_ciphertext")
      .eq("provider_connection_id", connection.id)
      .maybeSingle();
    if (credential?.refresh_token_ciphertext) {
      try {
        const token = await decryptSecret(credential.refresh_token_ciphertext);
        await fetch("https://oauth2.googleapis.com/revoke", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({ token }),
        });
      } catch (error) {
        console.warn("Could not revoke Google token", error);
      }
    }
    await supabase.from("provider_connection_credentials")
      .update({ refresh_token_ciphertext: null, updated_at: new Date().toISOString() })
      .eq("provider_connection_id", connection.id);
    await supabase.from("provider_connections")
      .update({ status: "revoked" })
      .eq("id", connection.id)
      .eq("user_id", userId);
  }
  return json({ disconnected: true });
}

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") return new Response("ok", { headers: corsHeaders() });

  try {
    if (request.method === "GET") {
      const url = new URL(request.url);
      if (url.searchParams.get("mode") === "callback") return await oauthCallback(request);
      return json({ error: "Not found" }, 404);
    }
    if (request.method !== "POST") return json({ error: "Method not allowed" }, 405);

    const body = await request.json() as ActionBody;
    if (body.action === "authorize") return await authorize(request);
    if (body.action === "status") return await status(request);
    if (body.action === "sync") return await sync(request);
    if (body.action === "disconnect") return await disconnect(request);
    return json({ error: "Unsupported action" }, 400);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Calendar request failed";
    const status = message.startsWith("Sign in") || message.startsWith("Your session") ? 401 : 400;
    return json({ error: message }, status);
  }
});
