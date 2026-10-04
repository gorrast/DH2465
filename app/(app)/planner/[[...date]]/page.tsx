import type { Metadata } from 'next';
import { PlannerView } from '@/components/views/Planner';

export const metadata: Metadata = { title: 'Planner' };

export default async function Page({ params }: { params: Promise<{ date?: string[] }> }) {
  const { date } = await params;
  return <PlannerView key={date?.[0] ?? ''} date={date?.[0]} />;
}
