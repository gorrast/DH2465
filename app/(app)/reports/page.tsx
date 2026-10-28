import type { Metadata } from 'next';
import { HomeView } from '@/components/views/Home';

export const metadata: Metadata = { title: 'Reports' };

// The Claude-written daily and weekly reports (with "Regenerate" on dev servers). Not in the tabs: open /reports.
export default function Page() {
  return <HomeView />;
}
