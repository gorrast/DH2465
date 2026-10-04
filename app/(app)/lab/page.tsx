import type { Metadata } from 'next';
import { LabView } from '@/components/views/Lab';

export const metadata: Metadata = { title: 'Under the hood' };

export default function Page() {
  return <LabView />;
}
