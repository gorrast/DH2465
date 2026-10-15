import type { Metadata } from 'next';
import { DataView } from '@/components/views/Data';

export const metadata: Metadata = { title: 'Data & privacy' };

export default function Page() {
  return <DataView />;
}
