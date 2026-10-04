'use client';
/* Data & privacy: what is connected, what is read, persona/seed, import, delete (SPEC §9.4). */
import { useState } from 'react';
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
  const { meta, switchPersona, refreshMeta, setHistoryDays, go } = useApp();
  const [chosen, setChosen] = useState(meta.persona.key);
  const [seed, setSeed] = useState(String(meta.seed));
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
      go('/morning/' + m.today);
    } catch (e: any) {
      busy(null);
      toast(e.message, { kind: 'error' });
    }
  };

  return (
    <>
      <ViewHead eyebrow="Data & privacy" title="What StressLess reads, and why" />
      <div className="v-data stack">
        <div className="grid grid-4">
          <Conn icon="calendar" title="Calendar" status={isDemo ? 'Demo data' : 'Imported'} note={isDemo ? 'Ten weeks of a simulated calendar. In the product: Google Calendar or EventKit, read-only, plus one write per accepted suggestion.' : 'Imported from your .ics export.'} />
          <Conn icon="watch" title="Watch" status={isDemo ? 'Demo data' : 'Imported'} note={isDemo ? 'Simulated Apple Watch: heart rate, sleep stages, HRV, resting heart rate, wrist temperature. In the product: HealthKit on the phone.' : 'Imported from Apple Health.'} />
          <Conn icon="map" title="Maps" status={isDemo ? 'Demo data' : 'Imported'} note={isDemo ? 'Simulated Google Maps timeline. In the product: Google Takeout or the Timeline API, used only to confirm booked events.' : 'Imported from Google Takeout.'} />
          <Conn icon="brain" title="Reasoning" status={meta.reasoning_mode === 'claude' ? 'Claude (opt-in)' : 'Rule-based'}
            note={meta.reasoning_mode === 'claude' ? 'Claude writes the narrative from a de-identified summary: numbers and titles only, never ids, times, places or people.' : 'The explanation text is written by rules on the StressLess server. Set STRESSLESS_REASONER=claude to let Claude write it (opt-in).'} />
        </div>
        <div className="card">
          <div className="card-title"><h3>Data classes</h3></div>
          <table className="data">
            <thead><tr>{['What', 'Fields', 'Why', 'Retention'].map((h) => <th key={h}>{h}</th>)}</tr></thead>
            <tbody>{CLASSES.map((r) => <tr key={r[0]}>{r.map((c, i) => <td key={i}>{c}</td>)}</tr>)}</tbody>
          </table>
        </div>
        <div className="card" data-tour="personas">
          <div className="card-title"><h3>Demo dataset</h3><span className="tiny muted">{(meta.days || 70) + ' nights · today ' + fmt.day(meta.today) + (meta.anchor_mode ? ' (fixed)' : '')}</span></div>
          <p className="small secondary">Three simulated people with different lives and different true sensitivities. Same seed, same story, every time.</p>
          <div className="grid grid-3">
            {(meta.personas || []).map((p) => (
              <button key={p.key} type="button" className={'card soft v-data-persona' + (chosen === p.key ? ' chosen' : '')} onClick={() => setChosen(p.key)}>
                <div className="row between">
                  <span className="avatar">{p.name.slice(0, 1)}</span>
                  {p.key === meta.persona.key ? <span className="badge badge-accent">current</span> : p.ready ? <span className="badge badge-good">ready</span> : <span className="badge badge-low">preparing</span>}
                </div>
                <strong>{p.name}</strong>
                <div className="small secondary">{p.tagline}</div>
              </button>
            ))}
          </div>
          <div className="row" style={{ marginTop: '12px' }}>
            <label className="row small">Seed
              <input className="input" type="number" value={seed} min={0} max={9999} style={{ width: '90px' }} aria-label="Seed" onChange={(e) => setSeed(e.target.value)} />
            </label>
            <button className="btn btn-primary" type="button" onClick={() => switchPersona(chosen, Math.min(9999, Math.max(0, +seed || 0)))}><Icon name="refresh" size={16} />Regenerate</button>
          </div>
        </div>
        <div className="grid grid-2">
          <div className="card">
            <div className="card-title"><h3>Bring your own data</h3><span className="badge badge-low">coming soon</span></div>
            <p className="small secondary">The same engine runs on real exports. Uploading your own files to the web app is coming soon; these are the exports it will read:</p>
            <ul className="small secondary v-data-list">
              <li>Apple Health: Settings → Health → Export All Health Data (export.xml)</li>
              <li>Google Calendar: Settings → Import &amp; export → Export (.ics)</li>
              <li>Google Maps: Google Takeout → Location History (Semantic Location History or Timeline.json)</li>
            </ul>
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
