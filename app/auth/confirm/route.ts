import type { EmailOtpType } from '@supabase/supabase-js';
import { NextResponse, type NextRequest } from 'next/server';
import { createClient } from '@/lib/supabase/server';

/** Landing page for the confirmation email: PKCE ``code`` (default template) or ``token_hash`` (custom template). */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = request.nextUrl;
  const nextParam = searchParams.get('next');
  const next = nextParam && nextParam.startsWith('/') && !nextParam.startsWith('//') ? nextParam : '/';
  const code = searchParams.get('code');
  const tokenHash = searchParams.get('token_hash');
  const type = searchParams.get('type') as EmailOtpType | null;
  const supabase = await createClient();

  let error: string | null = searchParams.get('error_description');
  if (!error && code) {
    const res = await supabase.auth.exchangeCodeForSession(code);
    error = res.error?.message ?? null;
  } else if (!error && tokenHash && type) {
    const res = await supabase.auth.verifyOtp({ type, token_hash: tokenHash });
    error = res.error?.message ?? null;
  } else if (!error) {
    error = 'The confirmation link is incomplete.';
  }

  if (!error) return NextResponse.redirect(origin + next);
  // A link opened in another browser cannot finish the PKCE exchange, but the email is confirmed: ask to sign in.
  const url = new URL('/login', origin);
  if (code) url.searchParams.set('confirmed', '1');
  else url.searchParams.set('error', error);
  return NextResponse.redirect(url);
}
