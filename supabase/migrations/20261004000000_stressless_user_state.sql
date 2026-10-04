-- StressLess per-user state. The demo dataset itself is never stored: the API regenerates it from the profile
-- (persona, seed, anchor date) and replays these rows onto it. Every row belongs to one auth user; row-level
-- security restricts each signed-in user to their own rows.

create table if not exists public.profiles (
  user_id    uuid primary key default auth.uid() references auth.users (id) on delete cascade,
  persona    text not null default 'alex' check (persona in ('alex', 'sam', 'robin')),
  seed       integer not null default 7 check (seed between 0 and 9999),
  anchor     date,                                   -- the "today" the user's dataset was generated for
  updated_at timestamptz not null default now()
);

create table if not exists public.answers (           -- reality-check answers
  user_id  uuid not null default auth.uid() references auth.users (id) on delete cascade,
  check_id text not null,
  answer   text not null check (answer in ('yes', 'no')),
  event_id text,
  visit_id text,
  ts       timestamptz not null default now(),
  primary key (user_id, check_id)
);

create table if not exists public.user_events (       -- events the user added (accepted suggestions, confirmed activities)
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id      text not null,
  event   jsonb not null,
  ts      timestamptz not null default now(),
  primary key (user_id, id)
);

create table if not exists public.accepted (          -- accepted suggestions -> the event they created
  user_id       uuid not null default auth.uid() references auth.users (id) on delete cascade,
  suggestion_id text not null,
  event_id      text not null,
  ts            timestamptz not null default now(),
  primary key (user_id, suggestion_id)
);

create table if not exists public.narratives (        -- cached Claude-written narratives
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  key     text not null,
  mode    text not null,
  text    text not null,
  ts      timestamptz not null default now(),
  primary key (user_id, key)
);

-- Row-level security: each user sees and changes only their own rows.
do $$
declare t text;
begin
  foreach t in array array['profiles', 'answers', 'user_events', 'accepted', 'narratives'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists "own rows" on public.%I', t);
    execute format('create policy "own rows" on public.%I for all to authenticated '
                   'using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()))', t);
    execute format('revoke all on public.%I from anon', t);
    execute format('grant select, insert, update, delete on public.%I to authenticated', t);
  end loop;
end $$;

-- The whole user state in one round trip (runs as the caller, so RLS applies).
create or replace function public.stressless_state()
returns json
language sql
stable
security invoker
set search_path = ''
as $$
  select json_build_object(
    'profile',     (select row_to_json(p) from public.profiles p where p.user_id = (select auth.uid())),
    'answers',     coalesce((select json_agg(a) from public.answers a where a.user_id = (select auth.uid())), '[]'::json),
    'user_events', coalesce((select json_agg(json_build_object('id', e.id, 'event', e.event)) from public.user_events e
                             where e.user_id = (select auth.uid())), '[]'::json),
    'accepted',    coalesce((select json_agg(s) from public.accepted s where s.user_id = (select auth.uid())), '[]'::json)
  );
$$;

-- Forget answers, added events, accepted suggestions and narratives (the profile stays).
create or replace function public.stressless_clear_state()
returns void
language plpgsql
security invoker
set search_path = ''
as $$
begin
  delete from public.answers     where user_id = (select auth.uid());
  delete from public.user_events where user_id = (select auth.uid());
  delete from public.accepted    where user_id = (select auth.uid());
  delete from public.narratives  where user_id = (select auth.uid());
end;
$$;

revoke execute on function public.stressless_state() from public, anon;
revoke execute on function public.stressless_clear_state() from public, anon;
grant execute on function public.stressless_state() to authenticated;
grant execute on function public.stressless_clear_state() to authenticated;
