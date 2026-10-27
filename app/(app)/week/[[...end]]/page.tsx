import { redirect } from 'next/navigation';

export default async function Page({ params }: { params: Promise<{ end?: string[] }> }) {
  const { end } = await params;
  redirect('/weekly' + (end?.[0] ? '/' + end[0] : ''));
}
