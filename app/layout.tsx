import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';
import { Analytics } from "@vercel/analytics/next"
import '@/styles/base.css';
import '@/styles/charts.css';
import '@/styles/views/morning.css';
import '@/styles/views/week.css';
import '@/styles/views/habits.css';
import '@/styles/views/replay.css';
import '@/styles/views/reality.css';
import '@/styles/views/planner.css';
import '@/styles/views/data.css';
import '@/styles/views/lab.css';
import '@/styles/views/tour.css';
import '@/styles/views/login.css';

const ICON = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%23FF6F5B'/%3E%3Cpath d='M5 17h6l3-7 5 13 3-6h5' fill='none' stroke='%231B1F3B' stroke-width='2.6' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E";

export const metadata: Metadata = {
  title: { default: 'StressLess', template: '%s · StressLess' },
  description: 'StressLess — let your calendar explain your body.',
  icons: { icon: ICON },
};

export const viewport: Viewport = { width: 'device-width', initialScale: 1 };

// Apply the saved theme before first paint (localStorage, then ?theme=, then dark).
const THEME_SCRIPT = `(function(){var t='dark';try{t=localStorage.getItem('sl-theme')||new URLSearchParams(location.search).get('theme')||'dark';}catch(e){}document.documentElement.setAttribute('data-theme',t);})();`;

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
