import { redirect } from 'next/navigation';

/** Where the google-calendar function sends the browser after Google's consent screen (?calendar=connected|error). */
export default async function CalendarConnectionCallback({ searchParams }: { searchParams: Promise<{ calendar?: string | string[] }> }) {
  const failed = (await searchParams).calendar === 'error';
  redirect(failed ? '/calendar?error=google' : '/calendar?sync=google');
}
