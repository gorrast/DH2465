'use client';
/* Check-in: cups of coffee and units of alcohol per day (backend: server/checkins.py). The reports look for patterns
   between these and the night after; a day that is not logged counts as unknown, not as zero. */
import { useEffect, useState, useImperativeHandle, type Ref } from 'react';
import { api } from '@/lib/api';
import { dates, fmt } from '@/lib/format';
import { Icon } from '../ui/Icon';
import { toast } from '../ui/overlays';
import { useLoad } from './common';

interface CheckinDay { day: string; coffee_cups: number | null; alcohol_units: number | null }
interface Checkins { today: string; days: CheckinDay[] }
type Field = 'coffee_cups' | 'alcohol_units';

const FIELDS: { key: Field; label: string; icon: string; unit: string; max: number; hint: string }[] = [
  { key: 'coffee_cups', label: 'Coffee', icon: 'coffee', unit: 'cups', max: 20, hint: 'Cups of coffee, or other caffeinated drinks' },
  { key: 'alcohol_units', label: 'Alcohol', icon: 'drop', unit: 'units', max: 30, hint: '1 unit ≈ a beer, glass of wine or a shot' },
];
const SHOWN_DAYS = 3;                          // today, yesterday and the day before

function dayLabel(day: string, today: string): string {
  const back = dates.diffDays(day, today);
  return back === 0 ? 'Today' : back === 1 ? 'Yesterday' : fmt.day(day);
}

export interface CheckinHandle { save: () => Promise<boolean> }

export function CheckinCard({ ref, locked = false }: { ref?: Ref<CheckinHandle>; locked?: boolean }) {
  const load = useLoad(() => api.get<Checkins>('/api/checkins'), []);
  const [day, setDay] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<Field, number | null>>({ coffee_cups: null, alcohol_units: null });
  const [saving, setSaving] = useState(false);

  const data = load.data;
  const today = data?.today;
  const selected = day ?? (today ? dates.addDays(today, -1) : null);   // yesterday: the evening before last night
  const stored = data?.days.find((d) => d.day === selected);

  useEffect(() => {
    if (stored) setDraft({ coffee_cups: stored.coffee_cups, alcohol_units: stored.alcohol_units });
    else setDraft({ coffee_cups: null, alcohol_units: null });
  }, [stored, selected]);

  useImperativeHandle(ref, () => ({ save }));

  if (load.error) return <div role="alert">Could not load your check-in. <button className="btn" onClick={load.reload}>Try again</button></div>;
  if (!data || !today || !selected) return <p role="status">Loading your check-in…</p>;
  const changed = FIELDS.some((f) => draft[f.key] !== (stored ? stored[f.key] : null));
  const recent = data.days.slice(0, 7);
  const loggedDays = recent.filter((d) => d.coffee_cups !== null || d.alcohol_units !== null).length;

  function step(f: (typeof FIELDS)[number], by: number) {
    setDraft((d) => ({ ...d, [f.key]: Math.min(f.max, Math.max(0, (d[f.key] ?? 0) + by)) }));
  }

  async function save() {
    if (!data || !today || !selected || saving) return false;
    if (!FIELDS.some(f => draft[f.key] !== (stored?.[f.key] ?? null))) return true;
    setSaving(true);
    try {
      // Only send what changed; a value cleared back to "not logged" is sent as null.
      const body: Partial<Record<Field, number | null>> = {};
      FIELDS.forEach((f) => { if (draft[f.key] !== (stored ? stored[f.key] : null)) body[f.key] = draft[f.key]; });
      const r = await api.post<Checkins>('/api/checkins/' + selected, body);
      load.setData(r);
      toast('Saved for ' + dayLabel(selected!, today!).toLowerCase(), { kind: 'success' });
      return true;
    } catch (e: any) {
      toast('Could not save: ' + e.message, { kind: 'error' });
      return false;
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="card v-home-checkin" aria-label="Coffee and alcohol check-in">
      <div className="row between">
        <div>
          <div className="eyebrow">Check-in</div>
          <h3>What did you have?</h3>
        </div>
        <div className="segmented" role="tablist" aria-label="Day">
          {Array.from({ length: SHOWN_DAYS }, (_, k) => dates.addDays(today, -k)).reverse().map((d) => (
            <button key={d} type="button" role="tab" aria-selected={d === selected} className={d === selected ? 'active' : ''}
                    disabled={locked || saving} onClick={() => setDay(d)}>{dayLabel(d, today)}</button>
          ))}
        </div>
      </div>

      <ul className="v-home-intake">
        {FIELDS.map((f) => (
          <li key={f.key}>
            <Icon name={f.icon} size={18} />
            <div className="v-home-intake-label">
              <div className="title">{f.label}</div>
              <div className="tiny muted">{f.hint}</div>
            </div>
            <div className="v-home-stepper">
              <button className="btn btn-sm btn-icon" type="button" aria-label={'Less ' + f.label.toLowerCase()}
                      disabled={locked || saving || !draft[f.key]} onClick={() => step(f, -1)}>−</button>
              <output aria-live="polite">{draft[f.key] === null ? '–' : draft[f.key]}<span className="tiny muted"> {f.unit}</span></output>
              <button className="btn btn-sm btn-icon" type="button" aria-label={'More ' + f.label.toLowerCase()}
                      disabled={locked || saving || draft[f.key] === f.max} onClick={() => step(f, 1)}>+</button>
            </div>
          </li>
        ))}
      </ul>

      <div className="row between">
        <span className="tiny muted">
          {loggedDays ? 'Logged ' + loggedDays + ' of the last 7 days. ' : ''}Log zero too: a day you skip counts as unknown.
        </span>
        <div className="row">
          {changed && stored && (stored.coffee_cups !== null || stored.alcohol_units !== null) ? (
            <button className="btn btn-ghost btn-sm" type="button" disabled={locked || saving}
                    onClick={() => setDraft({ coffee_cups: stored.coffee_cups, alcohol_units: stored.alcohol_units })}>Undo</button>
          ) : null}
          <button className="btn btn-primary btn-sm" type="button" disabled={locked || saving || !changed} onClick={save}>
            {saving ? <span className="spinner" /> : <Icon name="check" size={14} />}Save
          </button>
        </div>
      </div>
    </section>
  );
}
