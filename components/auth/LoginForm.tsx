'use client';
/* Email + password sign-in, sign-up and password reset (Supabase Auth). New accounts confirm their email before the
 * first sign-in; a reset link signs the user in through /auth/confirm and lands on /reset-password. */
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { motion, useMotionValue, useSpring } from 'motion/react';
import { ActionButton, RevealHeading } from '../ui/Motion';
import { getSupabase } from '@/lib/supabase/client';

type Mode = 'signin' | 'signup' | 'forgot';

/** Only allow same-site relative redirects after sign-in. */
function safeNext(next: string | null): string {
  return next && next.startsWith('/') && !next.startsWith('//') ? next : '/';
}

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [mode, setMode] = useState<Mode>(params.get('reset') ? 'forgot' : 'signin');
  const [motionPaused, setMotionPaused] = useState(false);
  const pageRef = useRef<HTMLDivElement>(null);
  const targetX = useMotionValue(0);
  const targetY = useMotionValue(0);
  const glowX = useSpring(targetX, { stiffness: 450, damping: 42, mass: 0.5 });
  const glowY = useSpring(targetY, { stiffness: 450, damping: 42, mass: 0.5 });
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(params.get('error'));
  const [notice, setNotice] = useState<string | null>(params.get('confirmed') ? 'Email confirmed — sign in to continue.' : null);
  const next = safeNext(params.get('next'));

  function switchMode(m: Mode) {
    setMode(m);
    setError(null);
    setNotice(null);
    setPassword('');
    setConfirm('');
  }

  useEffect(() => {
    const page = pageRef.current;
    if (!page || motionPaused) return;
    const motion = matchMedia('(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)');
    const reset = () => {
      targetX.set(0); targetY.set(0);
      glowX.jump(0); glowY.jump(0);
    };
    const follow = (event: PointerEvent) => {
      if (!motion.matches || event.pointerType !== 'mouse') return;
      const bounds = page.getBoundingClientRect();
      targetX.set(event.clientX - bounds.left - bounds.width * .15);
      targetY.set(event.clientY - bounds.top - bounds.height * .4);
    };
    page.addEventListener('pointermove', follow);
    page.addEventListener('pointerleave', reset);
    motion.addEventListener('change', reset);
    return () => {
      page.removeEventListener('pointermove', follow);
      page.removeEventListener('pointerleave', reset);
      motion.removeEventListener('change', reset);
      reset();
    };
  }, [motionPaused, targetX, targetY, glowX, glowY]);


  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    if (mode === 'signup' && password !== confirm) {
      setError('The passwords do not match.');
      return;
    }
    setPending(true);
    const supabase = getSupabase();
    try {
      if (mode === 'forgot') {
        const { error: err } = await supabase.auth.resetPasswordForEmail(email, {
          redirectTo: location.origin + '/auth/confirm?next=' + encodeURIComponent('/reset-password'),
        });
        if (err) throw err;
        // Same message whether or not the address has an account, so the form does not reveal who is registered.
        setNotice('If ' + email + ' has an account, we sent it a link to choose a new password.');
        setPending(false);
        return;
      }
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
      setConfirm('');
    } catch (err: any) {
      setError(err?.message || String(err));
    }
    setPending(false);
  }

  return (
    <div className="login-page" ref={pageRef}>
      <motion.div className="login-glow" aria-hidden="true" style={{ x: glowX, y: glowY }} />
      <section className="login-story" aria-label="About StressLess">
        <span className="eyebrow">A little clarity. A calmer tomorrow.</span>
        <RevealHeading as="h1" paused={motionPaused} aria-label="Your day has a story. Understand yours." lines={['Your day has a story.', 'Understand yours.']} />
        <p>Connect the dots between your calendar, your body, and your sleep. Find one small change for tonight.</p>
        <div className="login-visual">
          <svg viewBox="0 0 440 140" role="img" aria-label="Illustrative calendar events and flowing waveform">
            <path d="M0 110H440" stroke="var(--hairline-strong)" />
            {[40, 115, 190, 265].map((x, i) => <rect key={x} x={x} y={16} width={i === 3 ? 92 : 56} height={32} rx={8} fill={i === 3 ? 'var(--accent)' : 'var(--card-3)'} />)}
            <g className="login-wave" style={{ animationPlayState: motionPaused ? 'paused' : 'running' }}>
              {[0, 440].map(x => <path key={x} transform={`translate(${x} 0)`} d="M0 100C20 100 30 85 50 100S80 110 100 90S130 80 150 96S180 100 200 75S230 75 250 90S280 90 300 63S330 75 350 85S400 100 440 100" fill="none" stroke="var(--accent)" strokeWidth="3" strokeLinecap="round" />)}
            </g>
            <path d="M0 100H440" stroke="var(--ink-muted)" strokeDasharray="4 6" />
          </svg>
          <button className="login-motion-toggle" type="button" aria-pressed={motionPaused} onClick={() => setMotionPaused(paused => !paused)}>Pause animation</button>
        </div>
      </section>
      <div className="card raised login-card">
        <div className="brand login-brand">
          <span className="pulse-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12h4l2-5 4 10 2-5h6" /></svg>
          </span>
          <span className="brand-text">StressLess<small>the watch measures, the calendar explains</small></span>
        </div>
        {mode === 'forgot' ? (
          <div>
            <h3 className="login-title">Reset your password</h3>
            <p className="small secondary login-intro">Enter your email and we will send you a link to choose a new password.</p>
          </div>
        ) : (
          <div className="segmented login-tabs" role="tablist">
            <button type="button" role="tab" aria-selected={mode === 'signin'} className={mode === 'signin' ? 'active' : ''} onClick={() => switchMode('signin')}>Sign in</button>
            <button type="button" role="tab" aria-selected={mode === 'signup'} className={mode === 'signup' ? 'active' : ''} onClick={() => switchMode('signup')}>Create account</button>
          </div>
        )}
        <form className="stack login-form" onSubmit={submit}>
          <label className="login-field">
            <span className="small secondary">Email</span>
            <input className="input" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          {mode !== 'forgot' ? (
            <div className="login-field">
              <div className="row between">
                <label className="small secondary" htmlFor="login-password">Password</label>
                {mode === 'signin' ? <button type="button" className="login-link small" onClick={() => switchMode('forgot')}>Forgot password?</button> : null}
              </div>
              <input id="login-password" className="input" type="password" autoComplete={mode === 'signin' ? 'current-password' : 'new-password'} required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
          ) : null}
          {mode === 'signup' ? (
            <label className="login-field">
              <span className="small secondary">Confirm password</span>
              <input className="input" type="password" autoComplete="new-password" required minLength={6} value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            </label>
          ) : null}
          {error ? <p className="login-msg login-error small" role="alert">{error}</p> : null}
          {notice ? <p className="login-msg login-notice small" role="status">{notice}</p> : null}
          <ActionButton className="btn btn-primary login-submit" type="submit" disabled={pending}>
            {pending ? <span className="spinner" /> : null}
            {mode === 'signin' ? 'Sign in' : mode === 'signup' ? 'Create account' : 'Send reset link'}
          </ActionButton>
        </form>
        {mode === 'forgot' ? (
          <button type="button" className="login-link small login-back" onClick={() => switchMode('signin')}>Back to sign in</button>
        ) : (
          <p className="tiny muted login-foot">
            {mode === 'signin' ? 'Sign in to see your reports.' : 'You will get an email to confirm your address before your first sign-in.'}
          </p>
        )}
      </div>
    </div>
  );
}
