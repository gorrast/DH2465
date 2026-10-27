'use client';

import { getSupabase } from '@/lib/supabase/client';
import { useLoad } from './common';

export type AppUsage = { appName: string; packageName: string; minutes: number };
export type AppHeartRate = { package_name: string; app_name: string; gets_you_going_score: number; peak_session_score: number; avg_bpm: number; peak_bpm: number; total_minutes: number; sessions_measured: number };

async function topApps(): Promise<AppUsage[]> {
  const supabase = getSupabase();
  const { data: auth, error: authError } = await supabase.auth.getUser();
  if (authError) throw new Error(authError.message);
  if (!auth.user) throw new Error('Sign in to view your app usage.');
  const { data, error } = await supabase.from('source_records').select('source_record_id,value').eq('user_id', auth.user.id)
    .eq('data_type', 'app_usage').gte('start_at', new Date(Date.now() - 7 * 86400000).toISOString());
  if (error) throw new Error(error.message);
  const totals = new Map<string, number>();
  for (const row of data || []) {
    const name = typeof row.source_record_id === 'string' ? row.source_record_id.split(':', 1)[0].trim() : '';
    const minutes = Number(row.value ?? 0);
    if (name && Number.isFinite(minutes) && minutes > 0) totals.set(name, (totals.get(name) || 0) + minutes);
  }
  return Array.from(totals, ([packageName, minutes]) => {
    const cleaned = packageName.replace(/^(com|org|net|io|co|ai|app|se|de|uk|fr)\.([^.]+\.)*/i, '').replace(/[._]/g, ' ').trim().toLowerCase();
    return { packageName, minutes, appName: cleaned ? cleaned.replace(/\b[a-z]/g, letter => letter.toUpperCase()) : packageName };
  }).sort((a, b) => b.minutes - a.minutes || a.packageName.localeCompare(b.packageName)).slice(0, 5);
}

/** The header and statistic cards share these requests and their current results. */
export function useAppStatistics() {
  const apps = useLoad(topApps, []);
  const appHR = useLoad(async () => {
    const { data, error } = await getSupabase().rpc('top_apps_by_heart_rate');
    if (error) throw new Error(error.message);
    return (data || []) as AppHeartRate[];
  }, []);
  return { apps, appHR };
}

export type AppStatistics = ReturnType<typeof useAppStatistics>;
