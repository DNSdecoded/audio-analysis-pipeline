import { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  ArrowRight,
  FileText,
  FolderOpen,
  GitCompareArrows,
  Layers,
  Plus,
  RotateCcw,
  Settings,
  UploadCloud,
  X,
} from 'lucide-react';
import { useApp } from '../state/AppContext';
import { useWorkspace } from '../state/Workspace';
import { api } from '../lib/api';
import { Badge, Card, EmptyState, InfoNote, ProgressBar, SectionHeader, SeverityBadge, Spinner, TableWrap } from '../components/UI';
import Plot from '../components/Plot';
import { COLORS, DASHES } from '../lib/plotTheme';
import { fmt, fmtDate, fmtDuration, fmtUnit } from '../lib/format';
import type { Session } from '../types';

function Kpi({ label, value, hint, tone = 'default' }: { label: string; value: string | number; hint?: string; tone?: 'default' | 'warning' | 'error' | 'success' | 'accent' }) {
  return (
    <div className={`kpi kpi-${tone}`}>
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">{value}</span>
      {hint && <span className="kpi-hint">{hint}</span>}
    </div>
  );
}

function worstQc(session: Session): string | null {
  const order = ['error', 'warning', 'information', 'normal'];
  const values = session.files.map((file) => file.analysis_summary?.qc_overall).filter(Boolean) as string[];
  return order.find((level) => values.includes(level)) ?? null;
}

function RecentSessions({ currentId }: { currentId: string | undefined }) {
  const { recentSessions, openSession, forgetRecentSession } = useApp();
  const [details, setDetails] = useState<Record<string, Session | 'missing'>>({});
  const ids = recentSessions.map((item) => item.id).join(',');

  useEffect(() => {
    let cancelled = false;
    Promise.all(
      recentSessions.map((item) =>
        api.getSession(item.id).then(
          (session) => [item.id, session] as const,
          () => [item.id, 'missing' as const] as const,
        ),
      ),
    ).then((entries) => {
      if (!cancelled) setDetails(Object.fromEntries(entries));
    });
    return () => {
      cancelled = true;
    };
    // Re-fetch only when the list of remembered sessions changes.
  }, [ids]);

  const rows = recentSessions.filter((item) => details[item.id] !== 'missing');
  return (
    <Card title="Recent analysis sessions" subtitle="Sessions opened in this browser. Server sessions expire after the configured retention period.">
      {!rows.length ? (
        <p className="muted">No other sessions yet.</p>
      ) : (
        <TableWrap label="Recent analysis sessions">
          <table className="data-table stack-mobile">
            <thead>
              <tr>
                <th scope="col">Project</th>
                <th scope="col">Files</th>
                <th scope="col">Created</th>
                <th scope="col">Processing</th>
                <th scope="col">QC</th>
                <th scope="col"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((item) => {
                const session = details[item.id] as Session | undefined;
                const analysed = session?.files.filter((file) => file.has_analysis).length ?? 0;
                const running = session?.files.filter((file) => file.status === 'queued' || file.status === 'analyzing').length ?? 0;
                const failed = session?.files.filter((file) => file.status === 'error').length ?? 0;
                const qc = session ? worstQc(session) : null;
                const current = item.id === currentId;
                return (
                  <tr key={item.id} className={current ? 'is-current' : ''}>
                    <th scope="row">
                      {session?.name ?? <Spinner size={12} label="Loading session" />}
                      {current && <Badge variant="accent" className="ml">Current</Badge>}
                    </th>
                    <td data-label="Files" className="num">{session ? session.files.length : '—'}</td>
                    <td data-label="Created">{session ? fmtDate(session.created_at) : '—'}</td>
                    <td data-label="Processing">
                      {!session ? '—' : running ? `${running} analysing` : failed ? `${analysed} done · ${failed} failed` : `${analysed}/${session.files.length} analysed`}
                    </td>
                    <td data-label="QC">{qc ? <SeverityBadge severity={qc} /> : <span className="muted">—</span>}</td>
                    <td data-label="Actions" className="row-actions">
                      {!current && (
                        <button className="btn btn-sm" onClick={() => void openSession(item.id)} aria-label={`Open session ${session?.name ?? item.id}`}>
                          <FolderOpen size={13} aria-hidden="true" /> Open
                        </button>
                      )}
                      {!current && (
                        <button className="icon-button" onClick={() => forgetRecentSession(item.id)} aria-label={`Remove ${session?.name ?? 'session'} from recent sessions`}>
                          <X size={14} aria-hidden="true" />
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableWrap>
      )}
    </Card>
  );
}

export default function DashboardSection() {
  const { session, overview, busy, analyze, newSession } = useApp();
  const { navigate } = useWorkspace();
  const files = session?.files ?? [];
  const overviewFiles = overview?.files ?? [];
  const analysed = files.filter((file) => file.has_analysis);
  const processing = files.filter((file) => file.status === 'queued' || file.status === 'analyzing');
  const failed = files.filter((file) => file.status === 'error');
  const pending = files.filter((file) => !file.has_analysis && file.status !== 'queued' && file.status !== 'analyzing');
  const totalDuration = files.reduce((sum, file) => sum + Number(file.metadata?.duration ?? 0), 0);
  const errors = files.reduce((sum, file) => sum + Number(file.analysis_summary?.qc_errors ?? 0), 0);
  const warnings = files.reduce((sum, file) => sum + Number(file.analysis_summary?.qc_warnings ?? 0), 0);
  const recommendations = (overview?.recommendations ?? []).slice(0, 6);

  const series = (pick: (file: (typeof overviewFiles)[number]) => { x?: number[]; y?: (number | null)[] }, unit: string) =>
    overviewFiles
      .filter((file) => (pick(file).x ?? []).length)
      .slice(0, 8)
      .map((file, index) => ({
        x: pick(file).x,
        y: pick(file).y,
        type: 'scatter',
        mode: 'lines',
        name: file.name,
        line: { color: COLORS.palette[index % COLORS.palette.length], width: 1.4, dash: DASHES[index % DASHES.length] },
        hovertemplate: `%{x:.1f} s · %{y:.1f} ${unit}<extra>${file.name}</extra>`,
      }));

  const rmsData = useMemo(() => series((f) => ({ x: f.quick?.rms_times, y: f.quick?.rms_db }), 'dBFS'), [overviewFiles]);
  const loudnessData = useMemo(() => series((f) => ({ x: f.quick?.short_term_times, y: f.quick?.short_term_lufs }), 'LUFS'), [overviewFiles]);
  const bandData = useMemo(() => {
    const candidates = overviewFiles.filter((file) => file.quick?.bands?.length).slice(0, 6);
    if (!candidates.length) return [];
    const labels = candidates[0].quick!.bands.map((band) => band.label);
    return candidates.map((file, index) => ({
      x: labels,
      y: labels.map((_, bandIndex) => file.quick!.bands[bandIndex]?.share ?? null),
      type: 'bar',
      name: file.name,
      marker: { color: COLORS.palette[index % COLORS.palette.length], pattern: { shape: ['', '/', '.', 'x', '-', '+'][index % 6] } },
      hovertemplate: '%{x}: %{y:.1f}%<extra>' + file.name + '</extra>',
    }));
  }, [overviewFiles]);

  const lineLayout = (yTitle: string) => ({
    height: 240,
    margin: { l: 52, r: 12, t: 28, b: 40 },
    xaxis: { title: { text: 'Time (s)' } },
    yaxis: { title: { text: yTitle } },
  });

  return (
    <div className="section-stack">
      <SectionHeader
        title="Project dashboard"
        subtitle={session ? `${session.name} · created ${fmtDate(session.created_at)}` : 'Connecting to the analysis server…'}
        actions={
          <>
            <button className="btn" onClick={() => void newSession()} disabled={busy}>
              <Plus size={15} aria-hidden="true" /> New analysis
            </button>
            <button className="btn btn-primary" onClick={() => navigate('upload')}>
              <UploadCloud size={15} aria-hidden="true" /> Upload audio
            </button>
          </>
        }
      />

      <div className="kpi-grid" role="group" aria-label="Project overview">
        <Kpi label="Uploaded files" value={files.length} hint={`${fmtDuration(totalDuration)} total`} />
        <Kpi label="Completed analyses" value={analysed.length} tone={analysed.length && analysed.length === files.length ? 'success' : 'default'} hint={pending.length ? `${pending.length} not analysed` : files.length ? 'all analysed' : undefined} />
        <Kpi label="Processing" value={processing.length} tone={processing.length ? 'accent' : 'default'} hint={processing.length ? 'live from server' : 'idle'} />
        <Kpi label="Failed" value={failed.length} tone={failed.length ? 'error' : 'default'} hint={failed.length ? 'see file status' : undefined} />
        <Kpi label="Total duration" value={fmtDuration(totalDuration)} hint="original media" />
        <Kpi label="QC issues" value={errors + warnings} tone={errors ? 'error' : warnings ? 'warning' : 'default'} hint={`${errors} critical · ${warnings} warning`} />
      </div>

      <div className="quick-actions" role="group" aria-label="Quick actions">
        <button onClick={() => void newSession()} disabled={busy}><Plus size={18} aria-hidden="true" /><span><b>New analysis</b><small>Start an empty session (this one is kept)</small></span></button>
        <button onClick={() => navigate('upload')}><UploadCloud size={18} aria-hidden="true" /><span><b>Upload audio</b><small>WAV, FLAC, MP3, AAC, OGG, AIFF</small></span></button>
        <button onClick={() => navigate('comparison')} disabled={analysed.length < 2}><GitCompareArrows size={18} aria-hidden="true" /><span><b>Compare audio</b><small>{analysed.length < 2 ? 'Needs two analysed files' : `${analysed.length} files ready`}</small></span></button>
        <button onClick={() => navigate('reports')} disabled={!analysed.length}><FileText size={18} aria-hidden="true" /><span><b>Open reports</b><small>PDF, CSV, JSON, PNG</small></span></button>
        <button onClick={() => navigate('settings')}><Settings size={18} aria-hidden="true" /><span><b>Analysis settings</b><small>Target, FFT, QC limits</small></span></button>
      </div>

      {files.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Layers size={30} aria-hidden="true" />}
            title="No audio in this session yet"
            description="Upload one or more files. Each file is validated from its content (not its extension) before analysis."
            action={
              <button className="btn btn-primary" onClick={() => navigate('upload')}>
                <UploadCloud size={16} aria-hidden="true" /> Upload audio files
              </button>
            }
          />
        </Card>
      ) : (
        <Card
          title="File status"
          subtitle="Processing state comes from the server. Key and tempo are estimates and show their confidence."
          actions={
            <>
              {pending.length > 0 && (
                <button className="btn btn-sm btn-primary" onClick={() => void analyze(pending.map((file) => file.id), false)} disabled={busy}>
                  <Activity size={14} aria-hidden="true" /> Analyze {pending.length} file(s)
                </button>
              )}
              <button className="link-button" onClick={() => navigate('files')}>All files <ArrowRight size={14} aria-hidden="true" /></button>
            </>
          }
        >
          <TableWrap label="File status">
            <table className="data-table stack-mobile">
              <thead>
                <tr>
                  <th scope="col">File</th>
                  <th scope="col">Properties</th>
                  <th scope="col">Loudness</th>
                  <th scope="col">True peak</th>
                  <th scope="col">Key (estimate)</th>
                  <th scope="col">Tempo (estimate)</th>
                  <th scope="col">Status</th>
                  <th scope="col">QC</th>
                  <th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {files.map((file) => {
                  const summary = file.analysis_summary ?? {};
                  const running = file.status === 'queued' || file.status === 'analyzing';
                  return (
                    <tr key={file.id}>
                      <th scope="row" className="file-cell" title={file.original_name}>{file.original_name}</th>
                      <td data-label="Properties" className="muted">{file.metadata?.format ?? '—'} · {file.metadata?.sample_rate ? `${(file.metadata.sample_rate / 1000).toLocaleString()} kHz` : '—'} · {fmtDuration(file.metadata?.duration)}</td>
                      <td data-label="Loudness" className="num">{file.has_analysis ? (summary.integrated_lufs === null || summary.integrated_lufs === undefined ? 'not measurable' : `${fmt(summary.integrated_lufs)} LUFS`) : '—'}</td>
                      <td data-label="True peak" className="num">{file.has_analysis ? fmtUnit(summary.true_peak_dbtp, 'dBTP') : '—'}</td>
                      <td data-label="Key (estimate)">{summary.key ?? '—'}</td>
                      <td data-label="Tempo (estimate)" className="num">{summary.tempo_bpm ? `${fmt(summary.tempo_bpm, 1)} BPM` : '—'}</td>
                      <td data-label="Status">
                        {running ? (
                          <div className="status-progress">
                            <span className="small">{file.stage}</span>
                            <ProgressBar value={file.progress} label={`${file.original_name} analysis progress`} />
                          </div>
                        ) : file.status === 'error' ? (
                          <Badge variant="error">Failed</Badge>
                        ) : file.has_analysis ? (
                          <Badge variant="success">Complete</Badge>
                        ) : (
                          <Badge variant="neutral">Not analysed</Badge>
                        )}
                        {file.error && <div className="small error-text">{file.error}</div>}
                      </td>
                      <td data-label="QC">{summary.qc_overall ? <SeverityBadge severity={summary.qc_overall} /> : <span className="muted">—</span>}</td>
                      <td data-label="Actions" className="row-actions">
                        {file.has_analysis && (
                          <button className="btn btn-sm" onClick={() => navigate('overview', { file: file.id })} aria-label={`Open analysis of ${file.original_name}`}>
                            Open
                          </button>
                        )}
                        {(file.status === 'error' || (!file.has_analysis && !running)) && (
                          <button className="btn btn-sm" onClick={() => void analyze([file.id], true)} disabled={busy} aria-label={`${file.status === 'error' ? 'Retry' : 'Analyze'} ${file.original_name}`}>
                            {file.status === 'error' ? <RotateCcw size={13} aria-hidden="true" /> : <Activity size={13} aria-hidden="true" />} {file.status === 'error' ? 'Retry' : 'Analyze'}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TableWrap>
          <p className="muted small">Key and tempo estimates: open a file for confidence values and alternatives.</p>
        </Card>
      )}

      <RecentSessions currentId={session?.id} />

      {recommendations.length > 0 && (
        <Card
          title="Recommendations"
          subtitle="Each item is tied to a measured value; nothing is applied automatically."
          actions={<button className="link-button" onClick={() => navigate('qc')}>Quality control <ArrowRight size={14} aria-hidden="true" /></button>}
        >
          <ul className="recommendation-list">
            {recommendations.map((rec, index) => (
              <li className="recommendation" key={`${rec.file_id}-${rec.id}-${index}`}>
                <SeverityBadge severity={rec.priority === 'info' ? 'information' : rec.priority} />
                <div className="recommendation-body">
                  <strong>{rec.title}</strong>
                  <button type="button" className="link-button recommendation-file" onClick={() => navigate('qc', { file: rec.file_id })} aria-label={`Open quality-control findings for ${rec.file_name}`}>
                    {rec.file_name}
                  </button>
                  <p>{rec.supporting_measurement}</p>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {analysed.length > 0 && (
        <div className="two-col">
          <Card title="Loudness overview" subtitle="Short-term loudness (3 s, EBU R128). Files are not time-aligned.">
            <Plot title="Short-term loudness of all files" summary={`Short-term loudness over time for ${loudnessData.length} file(s).`} data={loudnessData} layout={lineLayout('LUFS')} height={240} emptyMessage="Analyse files to populate this chart." />
          </Card>
          <Card title="RMS overview" subtitle="50 ms RMS envelopes (all channels).">
            <Plot title="RMS envelopes of all files" summary={`RMS envelopes over time for ${rmsData.length} file(s).`} data={rmsData} layout={lineLayout('RMS (dBFS)')} height={240} emptyMessage="Analyse files to populate this chart." />
          </Card>
          <Card title="Frequency-band balance" subtitle="Share of measured energy per band." className="span-2">
            <Plot
              title="Frequency-band balance of all files"
              data={bandData}
              layout={{ height: 260, barmode: 'group', margin: { l: 52, r: 12, t: 28, b: 60 }, yaxis: { title: { text: 'Share of energy (%)' } } }}
              height={260}
              emptyMessage="Analyse files to compare spectral balance."
            />
          </Card>
        </div>
      )}

      {failed.length > 0 && (
        <InfoNote tone="warning">
          {failed.length} file(s) could not be analysed. The originals are preserved; use Retry in the table above or open Files for the
          full error message.
        </InfoNote>
      )}
    </div>
  );
}
