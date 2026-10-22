import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';
import { Analytics } from "@vercel/analytics/next"
import '@/styles/base.css';
import '@/styles/charts.css';
import '@/styles/views/home.css';
import '@/styles/views/morning.css';
import '@/styles/views/week.css';
import '@/styles/views/habits.css';
import '@/styles/views/replay.css';
import '@/styles/views/reality.css';
import '@/styles/views/planner.css';
import '@/styles/views/data.css';
import '@/styles/views/media.css';
import '@/styles/views/lab.css';
import '@/styles/views/calendar.css';
import '@/styles/views/tour.css';
import '@/styles/views/login.css';

const ICON = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%23FF6F5B'/%3E%3Cpath d='M5 17h6l3-7 5 13 3-6h5' fill='none' stroke='%231B1F3B' stroke-width='2.6' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E";

export const metadata: Metadata = {
  title: { default: 'StressLess', template: '%s · StressLess' },
  description: 'StressLess — let your calendar explain your body.',
  icons: { icon: ICON },
};

export const viewport: Viewport = { width: 'device-width', initialScale: 1 };

// Apply an explicit theme, saved preference, or default dark theme before first paint.
const THEME_SCRIPT = `(function(){var t='dark';try{var q=new URLSearchParams(location.search).get('theme');var s=localStorage.getItem('sl-theme');t=q||s||'dark';if(t!=='dark'&&t!=='light')t='dark';}catch(e){}document.documentElement.setAttribute('data-theme',t);})();`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" data-theme="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>
        {children}
        <Analytics />
      </body>
    </html>
  );
}
