import { dates } from "./format";

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
  {
    name: "daily",
    label: "Daily Report",
    icon: "sun",
    key: "1",
    withDate: true,
    title: "Daily",
  },
  {
    name: "weekly",
    label: "Weekly Report",
    icon: "week",
    key: "2",
    title: "Weekly",
  },
  {
    name: "connect",
    label: "Connect Your Data",
    icon: "upload",
    key: "3",
    title: "Connect Your Data",
  },
  {
    name: "account",
    label: "My Account",
    icon: "users",
    key: "4",
    title: "My Account",
  },
  {
    name: "data",
    label: "Data and Privacy",
    icon: "lock",
    key: "5",
    title: "Data and Privacy",
  },
];

export function defaultHref(item: NavItem, today: string): string {
  if (item.name === "home") return "/";
  if (!item.withDate) return "/" + item.name;
  return (
    "/" +
    item.name +
    "/" +
    (item.dateOffset ? dates.addDays(today, item.dateOffset) : today)
  );
}

export function hrefFor(name: string, today: string): string {
  const item = NAV.find((n) => n.name === name);
  return item ? defaultHref(item, today) : "/" + name;
}

/** Split a pathname like /morning/2026-09-27 into the view name and its params. */
export function parsePath(pathname: string): {
  name: string;
  params: string[];
} {
  const segs = pathname.split("/").filter(Boolean);
  return { name: segs[0] || "home", params: segs.slice(1) };
}
