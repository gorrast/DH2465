/** The shared demo account every visitor is signed in to (app/auth/demo/route.ts signs in on the server; no password). */
export const DEMO_EMAIL = "hwigh@kth.se";

export function isDemoEmail(email: string | null | undefined): boolean {
  return (email || "").trim().toLowerCase() === DEMO_EMAIL;
}
