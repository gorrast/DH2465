'use client';
/* Email + password sign-in and sign-up (Supabase Auth). New accounts confirm their email before the first sign-in. */
import { useRouter, useSearchParams } from 'next/navigation';
import { useState, type FormEvent } from 'react';
import { getSupabase } from '@/lib/supabase/client';

type Mode = 'signin' | 'signup';

/** Only allow same-site relative redirects after sign-in. */
function safeNext(next: string | null): string {
  return next && next.startsWith('/') && !next.startsWith('//') ? next : '/';
}

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [mode, setMode] = useState<Mode>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(params.get('error'));
  const [notice, setNotice] = useState<string | null>(params.get('confirmed') ? 'Email confirmed — sign in to continue.' : null);
  const next = safeNext(params.get('next'));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    setNotice(null);
    const supabase = getSupabase();
    try {
      if (mode === 'signin') {
        const { error: err } = await supabase.auth.signInWithPassword({ email, password });
        if (err) throw err;
        router.replace(next);
        router.refresh();
        return;
      }
      const { data, error: err } = await supabase.auth.signUp({
        email, password,
        options: { emailRedirectTo: location.origin + '/auth/confirm?next=' + encodeURIComponent(next) },
      });
      if (err) throw err;
      if (data.session) {
        router.replace(next);
        router.refresh();
        return;
      }
      setNotice('Check your inbox: we sent a confirmation link to ' + email + '. Open it to finish creating your account.');
      setMode('signin');
      setPassword('');
    } catch (err: any) {
      setError(err?.message || String(err));
    }
    setPending(false);
  }

  return (
    <div className="login-page">
      <div className="card raised login-card">
        <div className="brand login-brand">
          <span className="pulse-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12h4l2-5 4 10 2-5h6" /></svg>
          </span>
          <span className="brand-text">StressLess<small>the watch measures, the calendar explains</small></span>
        </div>
        <div className="segmented login-tabs" role="tablist">
          <button type="button" role="tab" aria-selected={mode === 'signin'} className={mode === 'signin' ? 'active' : ''} onClick={() => { setMode('signin'); setError(null); }}>Sign in</button>
          <button type="button" role="tab" aria-selected={mode === 'signup'} className={mode === 'signup' ? 'active' : ''} onClick={() => { setMode('signup'); setError(null); }}>Create account</button>
        </div>
        <form className="stack login-form" onSubmit={submit}>
          <label className="login-field">
            <span className="small secondary">Email</span>
            <input className="input" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label className="login-field">
            <span className="small secondary">Password</span>
            <input className="input" type="password" autoComplete={mode === 'signin' ? 'current-password' : 'new-password'} required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          {error ? <p className="login-msg login-error small" role="alert">{error}</p> : null}
          {notice ? <p className="login-msg login-notice small" role="status">{notice}</p> : null}
          <button className="btn btn-primary login-submit" type="submit" disabled={pending}>
            {pending ? <span className="spinner" /> : null}
            {mode === 'signin' ? 'Sign in' : 'Create account'}
          </button>
        </form>
        <p className="tiny muted login-foot">
          {mode === 'signin' ? 'Each account gets its own demo: a simulated person, their calendar and their watch.' : 'You will get an email to confirm your address before your first sign-in.'}
        </p>
      </div>
    </div>
  );
}
