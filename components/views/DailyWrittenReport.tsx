'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { api } from '@/lib/api';
import { useLoad } from './common';
import { ReportCard, sourceLine, type Overview, type Report } from './Home';
import { ReportInsights } from './ReportInsights';
import { CheckinCard, type CheckinHandle } from './Checkin';
import { Icon } from '../ui/Icon';

export function useDailyWrittenReport(morning: string, paused: boolean, sleepSummary: ReactNode) {
  const overview = useLoad(() => api.get<Overview>('/api/reports'), [morning]);
  const stored = useLoad(() => api.get<{ report: Report | null; status: string }>('/api/reports/daily/' + morning), [morning]);
  const [generated, setGenerated] = useState<Report | null>(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');
  const [scrollVersion, setScrollVersion] = useState(0);
  const section = useRef<HTMLElement>(null);
  const busy = useRef(false);
  const report = generated || stored.data?.report;
  useEffect(() => {
    if (!scrollVersion || !report) return;
    const frame = requestAnimationFrame(() => {
      section.current?.scrollIntoView({ behavior: paused || window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' });
      section.current?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [scrollVersion, report, paused]);
  async function generate(agree: boolean, checkin: CheckinHandle | null, regenerate = false) {
    const o = overview.data;
    if (busy.current || !o || !o.ready || morning !== o.daily.period || (o.ai && !o.consented && !agree)) return;
    busy.current = true; setWorking(true); setError('');
    try {
      if (checkin && !await checkin.save()) throw new Error('Save your check-in before generating the report.');
      if (!o.consented) await api.post('/api/reports/consent');
      const result = await api.post<{ report: Report }>('/api/reports/daily/' + morning + (regenerate ? '?regenerate=true' : ''));
      setGenerated(result.report);
      overview.setData({ ...o, consented: true, daily: { ...o.daily, status: 'ready' } });
      setScrollVersion(version => version + 1);
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not generate your report. Please try again.'); }
    finally { busy.current = false; setWorking(false); }
  }
  const output = <>
    {stored.error ? <div className="card" role="alert">Could not load the saved daily report. <button className="btn" onClick={stored.reload}>Try again</button></div> : null}
    {report ? <section ref={section} id="night-explanation" className="ah-section daily-written-report written-report" tabIndex={-1} aria-label="Your generated daily report">
      <ReportCard report={report} summaryAside={sleepSummary} insights={<ReportInsights report={report} paused={paused} />} />
      {overview.data?.dev && morning === overview.data.daily.period ? <button className="btn btn-sm" disabled={working} onClick={() => generate(true, null, true)}>{working ? 'Writing your report…' : 'Regenerate (dev)'}</button> : null}
      {error ? <p role="alert">{error}</p> : null}
    </section> : null}
  </>;
  return { morning, overview, stored, report, working, error, generate, output, view: () => setScrollVersion(v => v + 1) };
}

export function DailyGenerationForm({ controller, checkinOpen, tooltip, tooltipId }: { controller: ReturnType<typeof useDailyWrittenReport>; checkinOpen: boolean; tooltip: ReactNode; tooltipId: string }) {
  const checkin = useRef<CheckinHandle>(null);
  const [agree, setAgree] = useState(false);
  const { overview, stored, report, working, error } = controller;
  const o = overview.data;
  const pending = !report && (o?.daily.status === 'pending' || stored.data?.status === 'pending');
  const historical = o && o.daily.period !== controller.morning;
  return <>
    {checkinOpen && !report && !historical ? <div className="ah-report-checkin">
      <CheckinCard ref={checkin} locked={working} />
      {o ? <>
        <ul className="v-home-sources">{o.sources.map(source => <li key={source.key}><Icon name={source.ready ? 'check' : 'alert'} size={16} /><span>{source.label}{source.required ? ' · required' : ''}<small>{sourceLine(source)}</small></span></li>)}</ul>
        {o.ai && !o.consented ? <label className="v-home-consent small"><input type="checkbox" checked={agree} disabled={working} onChange={event => setAgree(event.target.checked)} /><span>I agree that a summary of my data (numbers, short labels and the artists and shows you play; no people’s names, calendar titles or places) is sent to Anthropic’s Claude to write my reports.</span></label> : null}
      </> : null}
    </div> : null}
    {(checkinOpen || report) && (!historical || report) ? <div className="ah-generate-action"><button className="btn btn-primary" type="button" aria-describedby={tooltipId} disabled={working || (!report && (!o || !o.ready || pending || (o.ai && !o.consented && !agree)))} onClick={() => report ? controller.view() : controller.generate(agree, checkin.current)}>
      <Icon name={working ? 'refresh' : 'brain'} size={16} />{report ? 'View daily report' : working ? 'Writing your report…' : 'Generate today’s report'}
    </button>{tooltip}</div> : null}
    {working ? <p role="status">Writing your report. This can take up to a minute.</p> : null}
    {pending ? <p role="status">Your report is being written. <button className="btn btn-sm" onClick={() => { overview.reload(); stored.reload(); }}>Check again</button></p> : null}
    {o && !o.ready && !report ? <p className="small secondary">Last night’s watch data has not arrived yet. Sync your data before generating.</p> : null}
    {historical && !report ? <p className="small secondary">No saved report for this date. New reports can only be generated for today.</p> : null}
    {overview.error ? <p role="alert">Could not check report availability. <button className="btn" onClick={overview.reload}>Try again</button></p> : null}
    {error ? <p role="alert">{error}</p> : null}
  </>;
}
