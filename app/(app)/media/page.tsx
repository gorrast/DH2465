import type { Metadata } from 'next';
import { MediaView } from '@/components/views/Media';

export const metadata: Metadata = { title: 'Media lab' };

export default function Page() {
  return <MediaView />;
}