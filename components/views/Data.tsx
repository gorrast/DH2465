'use client';
/* Data & privacy: what is connected, what is read, persona/seed, import, delete (SPEC §9.4). */
import Link from 'next/link';
import { api } from '@/lib/api';
import { fmt } from '@/lib/format';
import { Icon } from '../ui/Icon';
import { busy, confirmModal, toast } from '../ui/overlays';
import { useApp } from '../shell/AppContext';
import { ViewHead, useLoad } from './common';

const CLASSES = [
  ['Calendar events', 'title, start, end, attendees count, location hint', 'to know what your day looked like', 'demo: regenerated, never stored'],
  ['Location visits', 'place type and name, start, end', 'to check whether booked events happened', 'demo: regenerated, never stored'],
  ['Heart rate', 'one sample per minute', 'to see how your body responded during and after events', 'demo: regenerated, never stored'],
  ['Sleep', 'bedtime, stages, interruptions, wake time', 'to compute and explain the sleep score', 'demo: regenerated, never stored'],
  ['Recovery markers', 'overnight HRV, resting heart rate, respiratory rate, wrist temperature, blood oxygen', 'to compare each night with your own baseline', 'demo: regenerated, never stored'],
  ['Your answers', 'yes/no to reality checks, accepted suggestions', 'to correct the calendar and improve your patterns', 'your account, until you delete it'],
];

function Conn({ icon, title, status, note }: { icon: string; title: string; status: string; note: string }) {
  return (
    <div className="card v-data-conn">
      <div className="row between">
        <span className="row"><span className="v-data-icon"><Icon name={icon} size={18} /></span><strong>{title}</strong></span>
        <span className={'badge ' + (status.startsWith('Demo') ? 'badge-accent' : 'badge-good')}>{status}</span>
      </div>
      <p className="small secondary">{note}</p>
    </div>
  );
}

export function DataView() {
  const { meta, refreshMeta, setHistoryDays, go } = useApp();
  const facts = useLoad(() => api.get('/api/validation').catch(() => null), []);
  const isDemo = meta.source === 'demo';
  const hidden = facts.data && facts.data.available ? facts.data.hidden : null;

  const deleteAll = async () => {
    const ok = await confirmModal({ title: 'Delete all data?', body: 'This removes your reality-check answers, accepted suggestions and added events from your account. The default demo is regenerated.', confirmLabel: 'Delete and regenerate', danger: true });
    if (!ok) return;
    busy({ title: 'Deleting and regenerating', steps: ['Removing your data', 'Booking a fresh calendar', 'Simulating heart rate and sleep', 'Fitting the model'] });
    try {
      await api.post('/api/reset');
      const m = await refreshMeta();
      setHistoryDays(null);
      busy(null);
      toast('All data deleted. Fresh demo ready.', { kind: 'success' });
      go('/daily/' + m.today);
    } catch (e: any) {
      busy(null);
      toast(e.message, { kind: 'error' });
    }
  };

  return (
    <>
      <ViewHead eyebrow="Data and Privacy" title="What StressLess reads, and why" />
      <div className="v-data stack" data-tour="privacy">
        <div className="grid grid-4">
          <Conn icon="calendar" title="Calendar" status={isDemo ? 'Demo data' : 'Imported'} note={isDemo ? 'Ten weeks of a simulated calendar. In the product: Google Calendar or EventKit, read-only, plus one write per accepted suggestion.' : 'Imported from your .ics export.'} />
          <Conn icon="watch" title="Watch" status={isDemo ? 'Demo data' : 'Imported'} note={isDemo ? 'Simulated Apple Watch: heart rate, sleep stages, HRV, resting heart rate, wrist temperature. In the product: HealthKit on the phone.' : 'Imported from Apple Health.'} />
          <Conn icon="map" title="Maps" status={isDemo ? 'Demo data' : 'Imported'} note={isDemo ? 'Simulated Google Maps timeline. In the product: Google Takeout or the Timeline API, used only to confirm booked events.' : 'Imported from Google Takeout.'} />
          <Conn icon="brain" title="Reasoning" status={meta.reasoning_mode === 'claude' ? 'Claude (opt-in)' : 'Rule-based'}
            note={meta.reasoning_mode === 'claude' ? 'Claude writes the daily and weekly reports from a de-identified summary: numbers and short labels only, never names, calendar titles or places.' : 'The reports are written by rules on the StressLess server. Set STRESSLESS_REASONER=claude to let Claude write them (opt-in).'} />
        </div>
        <div className="card">
          <div className="card-title"><h3>Data classes</h3></div>
          <table className="data">
            <thead><tr>{['What', 'Fields', 'Why', 'Retention'].map((h) => <th key={h}>{h}</th>)}</tr></thead>
            <tbody>{CLASSES.map((r) => <tr key={r[0]}>{r.map((c, i) => <td key={i}>{c}</td>)}</tr>)}</tbody>
          </table>
        </div>
        <div className="grid grid-2">
          <div className="card">
            <div className="card-title"><h3>Bring your own data</h3></div>
            <p className="small secondary">Connect Your Data is the home for imports and optional sync. Import Spotify listening history, Netflix viewing CSVs, YouTube watch history, or a Steam library JSON. Steam and Last.fm sync are available when configured.</p>
            <p className="small secondary">Health, calendar and location exports cannot currently be uploaded through the web app. Each supported source includes its own setup instructions and file requirements.</p>
            <Link className="btn btn-primary" href="/connect"><Icon name="upload" size={16} />Connect Your Data</Link>
          </div>
          <div className="stack">
            <div className="card">
              <div className="card-title"><h3>This dataset</h3></div>
              <div className="row">
                <span className="chip">{(meta.n_nights || 0) + ' nights with watch data'}</span>
                {hidden ? <span className="chip">{(hidden.unworn_nights || []).length + ' unworn nights, ' + (hidden.unworn_social_nights || 0) + ' after social evenings'}</span> : null}
                <span className="chip">{'generated ' + (meta.generated_at ? fmt.hm(meta.generated_at) : '–')}</span>
              </div>
              {hidden ? <p className="tiny muted" style={{ marginTop: '8px' }}>Missing nights are not random: forgetting to charge happens more after late evenings, which is exactly what real data does.</p> : null}
            </div>
            <div className="card">
              <div className="card-title"><h3>Delete everything</h3></div>
              <p className="small secondary">Removes your answers and accepted suggestions from your account, then regenerates the default demo.</p>
              <button className="btn btn-danger" type="button" onClick={deleteAll}><Icon name="trash" size={16} />Delete all data</button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
