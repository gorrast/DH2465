import type { Metadata } from 'next';
import { MorningView } from '@/components/views/Morning';

export const metadata: Metadata = { title: 'Morning' };

export default async function Page({ params, searchParams }: { params: Promise<{ date?: string[] }>; searchParams: Promise<{ reveal?: string }> }) {
  const [{ date }, { reveal }] = await Promise.all([params, searchParams]);
  return <MorningView key={date?.[0] ?? ''} date={date?.[0]} reveal={reveal === '1'} />;
}
