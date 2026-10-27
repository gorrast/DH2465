import type { Metadata } from 'next';
import { AccountView } from '@/components/views/Account';

export const metadata: Metadata = { title: 'My Account' };

export default function Page() { return <AccountView />; }
