import { dates } from './format';

export interface NavItem {
  name: string;
  label: string;
  icon: string;
  key: string;
  withDate?: boolean;
  dateOffset?: number;
  title: string;
}

export const NAV: NavItem[] = [
  { name: 'morning', label: 'Morning', icon: 'moon', key: '1', withDate: true, title: 'Morning' },
  { name: 'replay', label: 'Replay', icon: 'pulse', key: '2', withDate: true, dateOffset: -1, title: 'Replay' },
  { name: 'week', label: 'Week', icon: 'week', key: '3', title: 'Week' },
  { name: 'habits', label: 'Habits', icon: 'habits', key: '4', title: 'Habits' },
  { name: 'reality', label: 'Reality check', icon: 'inbox', key: '5', title: 'Reality check' },
  { name: 'planner', label: 'Planner', icon: 'planner', key: '6', title: 'Planner' },
  { name: 'data', label: 'Data & privacy', icon: 'lock', key: '7', title: 'Data & privacy' },
  { name: 'lab', label: 'Under the hood', icon: 'lab', key: '8', title: 'Under the hood' },
];

export function defaultHref(item: NavItem, today: string): string {
  if (!item.withDate) return '/' + item.name;
  return '/' + item.name + '/' + (item.dateOffset ? dates.addDays(today, item.dateOffset) : today);
}

export function hrefFor(name: string, today: string): string {
  const item = NAV.find((n) => n.name === name);
  return item ? defaultHref(item, today) : '/' + name;
}

/** Split a pathname like /morning/2026-09-27 into the view name and its params. */
export function parsePath(pathname: string): { name: string; params: string[] } {
  const segs = pathname.split('/').filter(Boolean);
  return { name: segs[0] || 'morning', params: segs.slice(1) };
}
