/** Formatting and date helpers (ported 1:1 from the original SL.fmt / SL.date). */
type N = number | null | undefined;

const pad2 = (n: number) => (n < 10 ? '0' : '') + n;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const DAYS_LONG = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

function parseISODate(iso: string): Date {
  const [y, m, d] = String(iso).slice(0, 10).split('-').map(Number);
  return new Date(y, m - 1, d);
}
function toISODate(dt: Date): string {
  return dt.getFullYear() + '-' + pad2(dt.getMonth() + 1) + '-' + pad2(dt.getDate());
}
const isNum = (n: N): n is number => !(n === null || n === undefined || Number.isNaN(n));

export const fmt = {
  score: (n: N) => (n === null || n === undefined ? '–' : String(Math.round(n))),
  num: (n: N, digits?: number) => (isNum(n) ? Number(n).toFixed(digits === undefined ? 0 : digits) : '–'),
  signed: (n: N, digits?: number) => {
    if (!isNum(n)) return '–';
    const d = digits === undefined ? 0 : digits;
    const v = Math.abs(Number(n)).toFixed(d);
    const zero = Number(v) === 0;
    return (zero ? '' : n > 0 ? '+' : '−') + v;
  },
  pct: (n: N, digits?: number) => (n === null || n === undefined ? '–' : fmt.signed(n, digits === undefined ? 0 : digits) + ' %'),
  hm: (iso: string | null | undefined) => {
    if (!iso) return '–';
    const m = String(iso).match(/T(\d{2}):(\d{2})/);
    return m ? m[1] + ':' + m[2] : String(iso);
  },
  day: (iso: string | null | undefined) => {
    if (!iso) return '–';
    const d = parseISODate(iso);
    return DAYS[d.getDay()] + ' ' + d.getDate() + ' ' + MONTHS[d.getMonth()];
  },
  dayLong: (iso: string | null | undefined) => {
    if (!iso) return '–';
    const d = parseISODate(iso);
    return DAYS_LONG[d.getDay()] + ' ' + d.getDate() + ' ' + MONTHS[d.getMonth()] + ' ' + d.getFullYear();
  },
  minutes: (n: N) => {
    if (n === null || n === undefined) return '–';
    const m = Math.round(Math.abs(n));
    const h = Math.floor(m / 60), r = m % 60;
    const s = n < 0 ? '−' : '';
    if (h && r) return s + h + ' h ' + r + ' min';
    if (h) return s + h + ' h';
    return s + r + ' min';
  },
  bpm: (n: N) => (n === null || n === undefined ? '–' : Math.round(n) + ' bpm'),
  hourFloat: (h: N) => {
    if (h === null || h === undefined) return '–';
    const hh = Math.floor(h), mm = Math.round((h - hh) * 60);
    return pad2(hh % 24) + ':' + pad2(mm);
  },
};

export const dates = {
  parse: parseISODate,
  toISO: toISODate,
  addDays: (iso: string, n: number) => {
    const d = parseISODate(iso);
    d.setDate(d.getDate() + n);
    return toISODate(d);
  },
  localToday: () => toISODate(new Date()),
  weekday: (iso: string) => DAYS[parseISODate(iso).getDay()],
  diffDays: (a: string, b: string) => Math.round((parseISODate(b).getTime() - parseISODate(a).getTime()) / 86400000),
};

export const minuteLabel = (m: number) => {
  const mm = ((m % 1440) + 1440) % 1440;
  return String((mm / 60) | 0).padStart(2, '0') + ':' + String(mm % 60).padStart(2, '0');
};

/** Minutes since midnight of ``dayIso`` for an ISO timestamp (negative/over 1440 when on another day). */
export function minuteOf(iso: string | null | undefined, dayIso?: string): number | null {
  if (!iso) return null;
  const m = String(iso).match(/(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})/);
  if (!m) return null;
  let v = +m[2] * 60 + +m[3];
  if (dayIso && m[1] > dayIso) v += 1440;
  if (dayIso && m[1] < dayIso) v -= 1440;
  return v;
}

export type Band = 'good' | 'warning' | 'serious' | 'critical' | 'unknown';
export function bandFor(score: N): Band {
  if (score === null || score === undefined) return 'unknown';
  if (score <= 40) return 'critical';
  if (score <= 60) return 'serious';
  if (score <= 80) return 'warning';
  return 'good';
}
export function ratingFor(score: N): string {
  if (score === null || score === undefined) return 'No data';
  if (score <= 40) return 'Very low';
  if (score <= 60) return 'Low';
  if (score <= 80) return 'OK';
  if (score <= 95) return 'High';
  return 'Very high';
}
