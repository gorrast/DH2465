import type { Metadata } from 'next';
import { HomeView } from '@/components/views/Home';

export const metadata: Metadata = { title: 'Home' };

export default function Page() {
  return <HomeView />;
}
