import type { Metadata } from 'next';
import { WeekView } from '@/components/views/Week';

export const metadata: Metadata = { title: 'Week' };

export default async function Page({ params }: { params: Promise<{ end?: string[] }> }) {
  const { end } = await params;
  return <WeekView key={end?.[0] ?? ''} end={end?.[0]} />;
}
