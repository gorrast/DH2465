'use client';
/* Choose a new password. The reset email's link signs the user in through /auth/confirm and lands here. */
import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';
import { getSupabase } from '@/lib/supabase/client';

export function ResetPasswordForm() {
  const router = useRouter();
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError('The passwords do not match.');
      return;
    }
    setPending(true);
    const { error: err } = await getSupabase().auth.updateUser({ password });
    if (err) {
      setError(err.message);
      setPending(false);
      return;
    }
    setDone(true);
    setTimeout(() => { router.replace('/'); router.refresh(); }, 1500);
  }

  return (
    <div className="login-page">
      <div className="card raised login-card">
        <div>
          <h3 className="login-title">Choose a new password</h3>
          <p className="small secondary login-intro">You are signed in from the reset link. Pick a new password for your account.</p>
        </div>
        <form className="stack login-form" onSubmit={submit}>
          <label className="login-field">
            <span className="small secondary">New password</span>
            <input className="input" type="password" autoComplete="new-password" required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} disabled={done} />
          </label>
          <label className="login-field">
            <span className="small secondary">Confirm new password</span>
            <input className="input" type="password" autoComplete="new-password" required minLength={6} value={confirm} onChange={(e) => setConfirm(e.target.value)} disabled={done} />
          </label>
          {error ? <p className="login-msg login-error small" role="alert">{error}</p> : null}
          {done ? <p className="login-msg login-notice small" role="status">Password updated. Taking you to the app…</p> : null}
          <button className="btn btn-primary login-submit" type="submit" disabled={pending || done}>
            {pending ? <span className="spinner" /> : null}
            Save new password
          </button>
        </form>
      </div>
    </div>
  );
}
