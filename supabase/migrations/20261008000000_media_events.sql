-- User-owned media history imported from external exports. Raw files are never retained.
create table if not exists public.media_events (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  provider text not null check (provider in ('spotify', 'netflix')),
  occurred_at timestamptz not null,
  title text not null,
  creator text,
  minutes numeric not null default 0 check (minutes >= 0),
  source jsonb not null default '{}'::jsonb,
  imported_at timestamptz not null default now(),
  primary key (user_id, id)
);

alter table public.media_events enable row level security;
drop policy if exists "own media events" on public.media_events;
create policy "own media events" on public.media_events for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
revoke all on public.media_events from anon;
grant select, insert, update, delete on public.media_events to authenticated;
