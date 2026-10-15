// auth.js
// Email + password sign-in against Supabase Auth's REST API (same accounts as the web app). No supabase-js here
// because www/ has no build step; this is the small part of it we need: sign in, keep the session, refresh it.

const Auth = (() => {
  const KEY = "sb_session";
  const cfg = window.APP_CONFIG || {};
  let session = null;
  let refreshing = null;

  try {
    session = JSON.parse(localStorage.getItem(KEY));
  } catch {
    session = null;
  }

  function save(s) {
    session = s;
    try {
      if (s) localStorage.setItem(KEY, JSON.stringify(s));
      else localStorage.removeItem(KEY);
    } catch {
      // storage unavailable: the session just lasts until the app closes
    }
  }

  const configured = () => Boolean(cfg.SUPABASE_URL && cfg.SUPABASE_ANON_KEY && !cfg.SUPABASE_URL.includes("your-project-ref"));

  async function tokenRequest(grantType, body) {
    if (!configured()) throw new Error("Supabase is not configured: copy www/config.example.js to www/config.js");
    const res = await fetch(`${cfg.SUPABASE_URL}/auth/v1/token?grant_type=${grantType}`, {
      method: "POST",
      headers: { apikey: cfg.SUPABASE_ANON_KEY, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(data.error_description || data.msg || data.message || `Supabase Auth error ${res.status}`);
      err.status = res.status;
      throw err;
    }
    save({
      access_token: data.access_token,
      refresh_token: data.refresh_token,
      expires_at: data.expires_at || Math.floor(Date.now() / 1000) + (data.expires_in || 3600),
      user: { id: data.user?.id, email: data.user?.email },
    });
    return session;
  }

  return {
    configured,
    user: () => session?.user || null,

    signIn: (email, password) => tokenRequest("password", { email, password }),

    // A valid access token, refreshed when it expires within a minute; null when signed out.
    async accessToken() {
      if (!session) return null;
      if (session.expires_at * 1000 - Date.now() > 60000) return session.access_token;
      refreshing ||= tokenRequest("refresh_token", { refresh_token: session.refresh_token })
        .catch((err) => {
          if (err.status === 400 || err.status === 401) save(null); // refresh token revoked or used up: sign in again
          throw err;
        })
        .finally(() => (refreshing = null));
      return (await refreshing).access_token;
    },

    async signOut() {
      const token = session?.access_token;
      save(null);
      if (token && configured()) {
        fetch(`${cfg.SUPABASE_URL}/auth/v1/logout`, {
          method: "POST",
          headers: { apikey: cfg.SUPABASE_ANON_KEY, Authorization: `Bearer ${token}` },
        }).catch(() => {});
      }
    },

    // Sign-up consent (profiles.consented_at): the user's own row, which they may write themselves under RLS.
    async giveConsent() {
      const token = await this.accessToken();
      if (!token) throw new Error("Signed out: please sign in again.");
      const res = await fetch(`${cfg.SUPABASE_URL}/rest/v1/profiles?on_conflict=user_id`, {
        method: "POST",
        headers: {
          apikey: cfg.SUPABASE_ANON_KEY,
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
          Prefer: "resolution=merge-duplicates,return=minimal",
        },
        body: JSON.stringify({ user_id: session.user.id, consented_at: new Date().toISOString() }),
      });
      if (!res.ok) throw new Error(`Saving consent failed (${res.status}): ${(await res.text()).slice(0, 200)}`);
    },

    // The backend rejected the token (expired, or revoked server-side): forget it.
    invalidate: () => save(null),
  };
})();
