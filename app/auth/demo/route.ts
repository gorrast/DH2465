import { createClient as createAdminClient } from "@supabase/supabase-js";
import { NextResponse, type NextRequest } from "next/server";
import { DEMO_EMAIL } from "@/lib/demo";
import { createClient } from "@/lib/supabase/server";

/** Signs the visitor in to the shared demo account and sends them on to ``next`` (default /daily).
 *
 * Done on the server without a password: the service-role key makes a one-time sign-in link for the demo user, and
 * its token is redeemed at once into the visitor's session cookies (no email is sent). So nothing a visitor does to
 * the account's password can lock the demo. Needs SUPABASE_SERVICE_ROLE_KEY (server only). */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = request.nextUrl;
  const nextParam = searchParams.get("next");
  const next =
    nextParam && nextParam.startsWith("/") && !nextParam.startsWith("//")
      ? nextParam
      : "/daily";
  const fail = (message: string) => {
    console.error("demo sign-in failed: " + message);
    const url = new URL("/project", origin);
    url.searchParams.set("demo", "unavailable");
    return NextResponse.redirect(url);
  };

  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!key) return fail("SUPABASE_SERVICE_ROLE_KEY is not set");
  const admin = createAdminClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, key, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
  const link = await admin.auth.admin.generateLink({
    type: "magiclink",
    email: DEMO_EMAIL,
  });
  if (link.error || !link.data.properties?.hashed_token)
    return fail(link.error?.message || "no token");

  const supabase = await createClient();
  const { error } = await supabase.auth.verifyOtp({
    type: "magiclink",
    token_hash: link.data.properties.hashed_token,
  });
  if (error) return fail(error.message);
  return NextResponse.redirect(origin + next);
}
