import type { Metadata } from 'next';
import { FunStatisticsView } from '@/components/views/FunStatistics';

export const metadata: Metadata = { title: 'Fun statistics' };

export default function Page() {
  return <FunStatisticsView />;
}
