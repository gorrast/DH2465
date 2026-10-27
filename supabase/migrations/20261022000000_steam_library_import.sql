-- Steam libraries are snapshots stored as documents, separate from dated events.
create or replace function public.stressless_replace_media(
  p_provider text,
  p_events jsonb,
  p_documents jsonb default '[]'::jsonb
) returns void
language plpgsql
set search_path = ''
as $$
declare
  v_user_id uuid := auth.uid();
begin
  if v_user_id is null or p_provider not in ('spotify', 'netflix', 'steam') then
    raise exception 'invalid media replacement request';
  end if;

  if p_provider = 'steam' and jsonb_array_length(coalesce(p_events, '[]'::jsonb)) > 0 then
    raise exception 'Steam imports must be library documents';
  end if;

  if exists (
    select 1
    from jsonb_to_recordset(coalesce(p_events, '[]'::jsonb)) as item(provider text)
    where item.provider is distinct from p_provider
  ) then
    raise exception 'media event provider does not match replacement provider';
  end if;

  if jsonb_array_length(coalesce(p_events, '[]'::jsonb)) > 0 then
    delete from public.media_events
    where user_id = v_user_id and provider = p_provider;

    insert into public.media_events (user_id, id, provider, occurred_at, title, creator, minutes, source)
    select v_user_id, item.id, item.provider, item.occurred_at, item.title, item.creator, item.minutes,
           coalesce(item.source, '{}'::jsonb)
    from jsonb_to_recordset(p_events) as item(
      id text, provider text, occurred_at timestamptz, title text, creator text, minutes numeric, source jsonb
    );
  end if;

  if p_provider in ('spotify', 'steam') then
    insert into public.media_documents (user_id, id, filename, kind, payload)
    select v_user_id, item.id, item.filename, item.kind, coalesce(item.payload, '{}'::jsonb)
    from jsonb_to_recordset(coalesce(p_documents, '[]'::jsonb)) as item(
      id text, filename text, kind text, payload jsonb
    )
    on conflict (user_id, id) do update
    set filename = excluded.filename, kind = excluded.kind, payload = excluded.payload, imported_at = now();
  end if;
end;
$$;

revoke all on function public.stressless_replace_media(text, jsonb, jsonb) from public, anon;
grant execute on function public.stressless_replace_media(text, jsonb, jsonb) to authenticated;
