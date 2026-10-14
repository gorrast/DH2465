import type { Metadata } from 'next';
import { CalendarView } from '@/components/views/Calendar';

export const metadata: Metadata = { title: 'Calendar' };

export default function Page() {
  return <CalendarView />;
}
