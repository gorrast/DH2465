'use client';
import { createContext, useContext, type MutableRefObject } from 'react';

export interface Persona { key: string; name: string; tagline?: string; description?: string; tz?: string; ready?: boolean }
export interface Meta {
  persona: Persona;
  personas: Persona[];
  seed: number;
  days: number;
  source: string;
  start?: string;
  end?: string;
  today: string;
  anchor_mode?: boolean;
  n_nights?: number;
  reasoning_mode?: string;
  version?: string;
  generated_at?: string;
  showcase?: boolean;
}

export interface ReplayControls {
  play: (speed?: number) => void;
  pause: () => void;
  seek: (minute: number) => void;
  playRange: (from: number, to: number, speed?: number) => void;
}

export interface TourControls { start: () => void; stop: () => void; toggle: () => void; active: () => boolean }

export interface AppState {
  meta: Meta;
  today: string;
  refreshMeta: () => Promise<Meta>;
  historyDays: number | null;
  setHistoryDays: (n: number | null) => void;
  theme: 'dark' | 'light';
  toggleTheme: () => void;
  switchPersona: (key: string, seed?: number) => Promise<void>;
  replay: MutableRefObject<ReplayControls | null>;
  tour: TourControls;
  go: (href: string) => void;
  userEmail: string | null;
  signOut: () => Promise<void>;
}

export const AppCtx = createContext<AppState | null>(null);

export function useApp(): AppState {
  const ctx = useContext(AppCtx);
  if (!ctx) throw new Error('useApp outside <Shell>');
  return ctx;
}
