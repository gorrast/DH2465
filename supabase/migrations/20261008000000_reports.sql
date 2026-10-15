-- Generated daily and weekly reports. The primary key is the usage limit: one row per user, kind and period, so at
-- most one model call can ever be made for it. A row is claimed as 'pending' BEFORE the model is called and filled
-- in afterwards; users cannot delete rows or change a finished one.

create table if not exists public.reports (
  user_id      uuid not null default auth.uid() references auth.users (id) on delete cascade,
  kind         text not null check (kind in ('daily', 'weekly')),
  period_start date not null,                          -- daily: the morning; weekly: the Monday
  status       text not null default 'pending' check (status in ('pending', 'ready')),
  mode         text check (mode in ('claude', 'rules')),
  model        text,
  report       jsonb,                                  -- stressless.reports.Report; null while pending
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  primary key (user_id, kind, period_start)
);

alter table public.reports enable row level security;
drop policy if exists "read own" on public.reports;
drop policy if exists "claim own" on public.reports;
drop policy if exists "finish own pending" on public.reports;
create policy "read own" on public.reports for select to authenticated
  using (user_id = (select auth.uid()));
create policy "claim own" on public.reports for insert to authenticated
  with check (user_id = (select auth.uid()) and status = 'pending' and report is null);
create policy "finish own pending" on public.reports for update to authenticated
  using (user_id = (select auth.uid()) and status = 'pending') with check (user_id = (select auth.uid()));
revoke all on public.reports from anon, authenticated;
grant select, insert, update on public.reports to authenticated;

-- Reports claimed by ALL users in the last 24 hours: the global cap on model calls. Returns only a count.
create or replace function public.stressless_reports_last_day()
returns integer
language sql
stable
security definer
set search_path = ''
as $$
  select count(*)::integer from public.reports where created_at > now() - interval '24 hours';
$$;

revoke execute on function public.stressless_reports_last_day() from public, anon;
grant execute on function public.stressless_reports_last_day() to authenticated;
