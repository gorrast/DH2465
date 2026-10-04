import type { Metadata } from 'next';
import { RealityView } from '@/components/views/Reality';

export const metadata: Metadata = { title: 'Reality check' };

export default function Page() {
  return <RealityView />;
}
