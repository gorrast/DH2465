import { Suspense, type ReactNode } from 'react';
import { Shell } from '@/components/shell/Shell';

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <Suspense>
      <Shell>{children}</Shell>
    </Suspense>
  );
}
