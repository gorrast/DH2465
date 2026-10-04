import type { Metadata } from 'next';
import { ReplayView } from '@/components/views/Replay';

export const metadata: Metadata = { title: 'Replay' };

export default async function Page({ params, searchParams }: { params: Promise<{ date?: string[] }>; searchParams: Promise<{ t?: string }> }) {
  const [{ date }, { t }] = await Promise.all([params, searchParams]);
  return <ReplayView key={(date?.[0] ?? '') + ':' + (t ?? '')} date={date?.[0]} t={t} />;
}
