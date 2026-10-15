// Copy to config.js (git-ignored) and fill in. The Supabase values are the same as NEXT_PUBLIC_SUPABASE_URL and
// SUPABASE_ANON_KEY in the web app's .env.local; the publishable key is meant to ship in clients, never put the
// service-role key here.
window.APP_CONFIG = {
  SUPABASE_URL: "https://your-project-ref.supabase.co",
  SUPABASE_ANON_KEY: "sb_publishable_...",
  // The StressLess FastAPI (POST /api/sync): the deployed Vercel URL, or http://10.0.2.2:8000 for `npm run dev:api`
  // from the Android emulator. Can be overridden on the device with localStorage.setItem("API_URL", "...").
  API_URL: "https://your-app.vercel.app",
};
