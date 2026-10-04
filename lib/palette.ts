/** Chart colours come from the CSS tokens of the active theme (styles/base.css). */
export function cssVar(name: string): string {
  if (typeof document === 'undefined') return '';
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export const palette = {
  event: (type?: string) => cssVar('--evt-' + (type || 'meeting')) || cssVar('--evt-meeting'),
  series: (i: number) => cssVar('--series-' + i),
  status: (kind: string) => cssVar('--status-' + kind),
  accent: () => cssVar('--accent'),
  ink: (level?: string) => cssVar('--ink-' + (level || 'primary')),
  hairline: () => cssVar('--hairline'),
  var: cssVar,
};

export const EVENT_TYPES = ['meeting', 'focus', 'workout', 'social', 'travel', 'personal', 'protected'];
export const EVENT_LABELS: Record<string, string> = {
  meeting: 'Meeting', focus: 'Focus', workout: 'Workout', social: 'Social', travel: 'Travel', personal: 'Personal', protected: 'Protected',
};
