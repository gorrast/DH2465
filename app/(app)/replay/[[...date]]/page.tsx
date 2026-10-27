import { redirect } from 'next/navigation';
import { dates } from '@/lib/format';

export default async function Page({ params }: { params: Promise<{ date?: string[] }> }) {
  const { date } = await params;
  redirect('/daily' + (date?.[0] ? '/' + dates.addDays(date[0], 1) : ''));
}
