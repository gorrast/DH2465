import type { Metadata } from 'next';
import { SocialView } from '@/components/views/Social';

export const metadata: Metadata = { title: 'Social' };

export default function Page() {
  return <SocialView />;
}
