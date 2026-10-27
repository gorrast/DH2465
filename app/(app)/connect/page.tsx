import type { Metadata } from 'next';
import { MediaView } from '@/components/views/Media';

export const metadata: Metadata = { title: 'Connect Your Data' };

export default function Page() {
  return <MediaView />;
}