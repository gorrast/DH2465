-- Update poster metadata by catalogue lookup key, without replacing titles, dates or viewing history.
create or replace function public.stressless_update_netflix_artwork(p_updates jsonb)
returns void
language plpgsql
set search_path = ''
as $$
begin
  if auth.uid() is null or jsonb_typeof(p_updates) is distinct from 'array'
     or jsonb_array_length(p_updates) > 20 then
    raise exception 'invalid Netflix artwork update';
  end if;

  if exists (
    select 1 from jsonb_to_recordset(p_updates) as item("query" text, source jsonb)
    where item."query" is null or length(item."query") > 1000
       or jsonb_typeof(item.source) is distinct from 'object'
       or coalesce(item.source->>'artwork_status', '') not in ('matched', 'unmatched')
  ) then
    raise exception 'invalid Netflix artwork metadata';
  end if;

  update public.media_events as target
  set source = target.source || jsonb_strip_nulls(jsonb_build_object(
    'artwork_status', item.source->'artwork_status',
    'artwork_source', item.source->'artwork_source',
    'artwork_url', item.source->'artwork_url',
    'artwork_page', item.source->'artwork_page',
    'tmdb_id', item.source->'tmdb_id',
    'tmdb_media_type', item.source->'tmdb_media_type'
  ))
  from jsonb_to_recordset(p_updates) as item("query" text, source jsonb)
  where target.user_id = (select auth.uid()) and target.provider = 'netflix'
    and target.source->>'artwork_query' = item."query";
end;
$$;

create index if not exists media_events_netflix_artwork_lookup
  on public.media_events (user_id, (source->>'artwork_query')) where provider = 'netflix';

revoke all on function public.stressless_update_netflix_artwork(jsonb) from public, anon;
grant execute on function public.stressless_update_netflix_artwork(jsonb) to authenticated;
