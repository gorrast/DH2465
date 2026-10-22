-- Structured Spotify summaries such as Taste Profile, Your Library and Wrapped.
create table if not exists public.media_documents (
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id text not null,
  filename text not null,
  kind text not null,
  payload jsonb not null default '{}'::jsonb,
  imported_at timestamptz not null default now(),
  primary key (user_id, id)
);

alter table public.media_documents enable row level security;
drop policy if exists "own media documents" on public.media_documents;
create policy "own media documents" on public.media_documents for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
revoke all on public.media_documents from anon;
grant select, insert, update, delete on public.media_documents to authenticated;