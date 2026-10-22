import type { ReactNode } from 'react';
import { fmt, pointClass } from '@/lib/format';

/** Signed sleep-score changes; intervals colour each endpoint independently. */
export function ScoreChange({ value, digits = 1, children }: { value: number | null | undefined; digits?: number; children?: ReactNode }) {
  return <span className={pointClass(value, digits)}>{children ?? fmt.signed(value, digits)}</span>;
}

/** Highlight explicit point changes in engine prose, without interpreting physiological values. */
export function ScoreText({ text }: { text: string }) {
  const parts: ReactNode[] = [];
  const pattern = /([+−-]\d+(?:\.\d+)?)(?=(?:\s+to\s+[+−-]?\d+(?:\.\d+)?)?\s*(?:points?|pts)\b)|(\d+(?:\.\d+)?)(?=\s+points?\s+(?:higher|lower)\b)/g;
  let end = 0;
  for (const match of text.matchAll(pattern)) {
    const start = match.index!;
    const lower = match[2] && /^\s+points?\s+lower\b/.test(text.slice(start + match[0].length));
    const value = Number(match[0].replace('−', '-')) * (lower ? -1 : 1);
    parts.push(text.slice(end, start), <ScoreChange key={start} value={value} digits={Math.min(100, match[0].split('.')[1]?.length || 0)}>{match[0]}</ScoreChange>);
    end = start + match[0].length;
  }
  return <>{parts}{text.slice(end)}</>;
}
