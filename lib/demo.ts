/** The shared demo account behind "Try the demo". Its credentials are public on purpose: anyone can sign in with one click. */
export const DEMO_EMAIL = 'hwigh@kth.se';
export const DEMO_PASSWORD = 'demo11';

export function isDemoEmail(email: string | null | undefined): boolean {
  return (email || '').trim().toLowerCase() === DEMO_EMAIL;
}
