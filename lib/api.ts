/** API client for the FastAPI backend: same-origin /api/*, authenticated with the Supabase access token. */
import { getSupabase } from './supabase/client';

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

async function authHeaders(): Promise<Record<string, string>> {
  const { data } = await getSupabase().auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: 'Bearer ' + token } : {};
}

async function send(method: string, path: string, body?: unknown): Promise<Response> {
  const headers = await authHeaders();
  const init: RequestInit = { method, headers };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  if (!res.ok) {
    let msg = res.status + ' ' + res.statusText;
    try {
      const j = await res.json();
      if (j && j.error) msg = j.error;
    } catch {
      /* not JSON */
    }
    if (res.status === 401 && typeof window !== 'undefined') {
      window.location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search);
    }
    throw new ApiError(msg, res.status);
  }
  return res;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await send(method, path, body);
  const ct = res.headers.get('content-type') || '';
  return (ct.includes('application/json') ? res.json() : res.text()) as Promise<T>;
}

export const api = {
  get: <T = any>(path: string) => request<T>('GET', path),
  post: <T = any>(path: string, body?: unknown) => request<T>('POST', path, body === undefined ? {} : body),
  /** Fetch an authenticated file and hand it to the browser as a download. */
  download: async (path: string, filename: string) => {
    const blob = await (await send('GET', path)).blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
};

/** Report a client-side error to the server log (best effort). */
export function logClient(level: string, message: string, err?: unknown) {
  const stack = err && (err as Error).stack ? String((err as Error).stack) : err ? String(err) : '';
  (level === 'error' ? console.error : console.warn)('[StressLess]', message, err || '');
  try {
    fetch('/api/log', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ level, message, stack }) }).catch(() => {});
  } catch {
    /* ignore */
  }
}
