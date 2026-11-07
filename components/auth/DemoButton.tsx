'use client';
/* One-click sign-in to the shared demo account, so visitors can explore the app without credentials. */
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { getSupabase } from '@/lib/supabase/client';
import { DEMO_EMAIL, DEMO_PASSWORD } from '@/lib/demo';

export function DemoButton({ className = 'btn btn-primary', label = 'Try the demo', next = '/daily' }: { className?: string; label?: string; next?: string }) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setPending(true);
    setError(null);
    const { error: err } = await getSupabase().auth.signInWithPassword({ email: DEMO_EMAIL, password: DEMO_PASSWORD });
    if (err) {
      setError('The demo is unavailable right now: ' + err.message);
      setPending(false);
      return;
    }
    router.replace(next);
    router.refresh();
  }

  return (
    <>
      <button type="button" className={className} onClick={start} disabled={pending}>
        {pending ? <span className="spinner" /> : null}
        {label}
      </button>
      {error ? <p className="login-msg login-error small" role="alert">{error}</p> : null}
    </>
  );
}
