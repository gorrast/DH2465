import { createServerClient } from '@supabase/ssr';
import { NextResponse, type NextRequest } from 'next/server';

const PUBLIC_PATHS = ['/login', '/auth', '/project'];

/** Refresh the Supabase session on every page request. / is the public project site for everyone; signed-out
 * visitors to app pages are sent to /login. */
export async function proxy(request: NextRequest) {
  let response = NextResponse.next({ request });
  const supabase = createServerClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: (toSet) => {
        toSet.forEach(({ name, value }) => request.cookies.set(name, value));
        response = NextResponse.next({ request });
        toSet.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
      },
    },
  });
  // Do not run code between createServerClient and getClaims: it refreshes the session cookies.
  const { data } = await supabase.auth.getClaims();
  const signedIn = !!data?.claims;
  const path = request.nextUrl.pathname;
  const isPublic = PUBLIC_PATHS.some((p) => path === p || path.startsWith(p + '/'));

  if (path === '/') {
    const url = request.nextUrl.clone();
    url.pathname = '/project';
    url.search = '';
    return NextResponse.redirect(url);
  }
  if (!signedIn && !isPublic) {
    const url = request.nextUrl.clone();
    url.pathname = '/login';
    url.search = '?next=' + encodeURIComponent(path + request.nextUrl.search);
    return NextResponse.redirect(url);
  }
  if (signedIn && path === '/login') {
    const url = request.nextUrl.clone();
    url.pathname = '/daily';
    url.search = '';
    return NextResponse.redirect(url);
  }
  return response;
}

export const config = {
  // Everything except the API (FastAPI checks its own bearer tokens) and static assets.
  matcher: ['/((?!api/|fonts/|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)'],
};
