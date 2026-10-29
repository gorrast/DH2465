-- "Delete all data" removes everything the signed-in user has stored, not only their answers.
--
-- The synced tables (sleep_nights, source_records, ...) are read-only for users under RLS, so the function runs as
-- its owner (security definer) and every statement is pinned to the caller's own rows. Only the profile stays: the
-- API resets it to the default demo right after. Connections go too, which drops the stored Google refresh token
-- (provider_connection_credentials cascades) and the phone install's sync streams.
create or replace function public.stressless_clear_state()
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  uid uuid := (select auth.uid());
begin
  if uid is null then
    raise exception 'not signed in';
  end if;
  -- your answers and what the app made for you
  delete from public.answers              where user_id = uid;
  delete from public.user_events          where user_id = uid;
  delete from public.accepted             where user_id = uid;
  delete from public.narratives           where user_id = uid;
  delete from public.reports              where user_id = uid;
  -- synced and imported data
  delete from public.source_records       where user_id = uid;
  delete from public.sleep_nights         where user_id = uid;
  delete from public.heart_rate_days      where user_id = uid;
  delete from public.daily_activity       where user_id = uid;
  delete from public.daily_metrics        where user_id = uid;
  delete from public.event_analytics      where user_id = uid;
  delete from public.calendar_events      where user_id = uid;
  delete from public.biometric_samples    where user_id = uid;
  delete from public.media_events         where user_id = uid;
  delete from public.media_documents      where user_id = uid;
  -- connections last: their streams and stored credentials cascade
  delete from public.connection_streams   where user_id = uid;
  delete from public.provider_connections where user_id = uid;
end;
$$;

revoke execute on function public.stressless_clear_state() from public, anon;
grant execute on function public.stressless_clear_state() to authenticated;
