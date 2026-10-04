import type { Metadata } from 'next';
import { HabitsView } from '@/components/views/Habits';

export const metadata: Metadata = { title: 'Habits' };

export default function Page() {
  return <HabitsView />;
}
