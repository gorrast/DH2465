import { redirect } from 'next/navigation';

export default async function Page({ params }: { params: Promise<{ date?: string[] }> }) {
  const { date } = await params;
  redirect('/daily' + (date?.[0] ? '/' + date[0] : ''));
}
