import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  AudioLines,
  AudioWaveform,
  CheckCircle2,
  CircleDot,
  FileAudio,
  Gauge,
  Info,
  ListChecks,
  Music2,
  RefreshCw,
  Replace,
  ShieldCheck,
  Trash2,
  UploadCloud,
} from 'lucide-react';
import { useApp } from '../state/AppContext';
import { useWorkspace } from '../state/Workspace';
import { useConfirm } from '../components/ConfirmDialog';
import { AnalysisLoadState } from '../components/AnalysisState';
import { api } from '../lib/api';
import { Badge, Card, EmptyState, InfoNote, KeyValue, ProgressBar, SectionHeader, SeverityBadge } from '../components/UI';
import { fmt, fmtBytes, fmtDate, fmtDuration, fmtHz, statusClass, titleCase } from '../lib/format';
import type { FileRecord } from '../types';
import type { SectionKey } from '../lib/routes';

const ACCEPT = '.wav,.wave,.mp3,.flac,.aac,.ogg,.oga,.aiff,.aif,.aifc,.m4a,.mp4';

const QUICK_LINKS: { section: SectionKey; label: string; Icon: typeof Activity }[] = [
  { section: 'overview', label: 'Overview', Icon: ListChecks },
  { section: 'waveform', label: 'Waveform', Icon: AudioWaveform },
  { section: 'spectrum', label: 'Spectrum', Icon: AudioLines },
  { section: 'musical', label: 'Musical', Icon: Music2 },
  { section: 'loudness', label: 'Loudness', Icon: Gauge },
  { section: 'stereo', label: 'Stereo', Icon: CircleDot },
  { section: 'qc', label: 'QC findings', Icon: ShieldCheck },
];

export default function FilesSection() {
  const { session, analyses, ensureAnalysis, analyze, removeFile, replaceFile, busy, uploadProgress, notify } = useApp();
  // The selected file *is* the workspace's active file, so the section links
  // below (and every analysis page) open this file, not the first one.
  const { navigate, activeFileId, setActiveFileId } = useWorkspace();
  const confirm = useConfirm();
  const files = session?.files ?? [];
  const [replaceTarget, setReplaceTarget] = useState<string | null>(null);
  const replaceRef = useRef<HTMLInputElement | null>(null);

  const selectedId = files.some((file) => file.id === activeFileId) ? activeFileId : files[0]?.id ?? null;
  useEffect(() => {
    if (selectedId && selectedId !== activeFileId) setActiveFileId(selectedId);
  }, [selectedId, activeFileId, setActiveFileId]);

  const selected = files.find((file) => file.id === selectedId) ?? null;
  const analysis = selected ? analyses[selected.id] : undefined;

  useEffect(() => {
    if (selected?.has_analysis && !analyses[selected.id]) {
      void ensureAnalysis(selected.id);
    }
  }, [selected?.id, selected?.has_analysis, analyses, ensureAnalysis]);

  const replace = (file: FileRecord) => {
    setReplaceTarget(file.id);
    replaceRef.current?.click();
  };

  const confirmRemove = async (file: FileRecord) => {
    const ok = await confirm({
      title: `Remove ${file.original_name}?`,
      message: 'The uploaded copy and its analysis results are deleted from this session. Other files are not affected. This cannot be undone.',
      confirmLabel: 'Remove file',
      destructive: true,
    });
    if (ok) await removeFile(file.id);
  };

  const analyzed = useMemo(() => files.filter((file) => file.has_analysis), [files]);

  return (
    <div className="section-stack">
      <SectionHeader
        title="Files & validation"
        subtitle="Technical metadata, validation results and per-file processing state. Each file is analysed independently."
        actions={
          <>
            <button className="btn" onClick={() => navigate('upload')}>
              <UploadCloud size={15} aria-hidden="true" /> Add files
            </button>
            <button className="btn btn-primary" onClick={() => void analyze(undefined, false)} disabled={busy || !files.some((file) => !file.has_analysis && file.status !== 'queued' && file.status !== 'analyzing')} title={files.some((file) => !file.has_analysis && file.status !== 'queued' && file.status !== 'analyzing') ? 'Analyse files that have not been analysed yet' : 'All files are already analysed — use Re-analyse on a file to run it again'}>
              <Activity size={15} aria-hidden="true" /> Analyze all
            </button>
          </>
        }
      />
      <input
        ref={replaceRef}
        type="file"
        accept={ACCEPT}
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file && replaceTarget) {
            void replaceFile(replaceTarget, file).then((replaced) => {
              if (replaced) notify('success', 'Replacement complete', 'The new file was validated, then the previous file was removed.');
            });
          }
          setReplaceTarget(null);
          event.target.value = '';
        }}
      />

      {files.length === 0 ? (
        <Card>
          <EmptyState
            icon={<FileAudio size={28} aria-hidden="true" />}
            title="No files in this session"
            description="Upload WAV, MP3, FLAC, AAC, OGG or AIFF files to validate and analyse them."
            action={
              <button className="btn btn-primary" onClick={() => navigate('upload')}>
                <UploadCloud size={15} aria-hidden="true" /> Upload audio
              </button>
            }
          />
        </Card>
      ) : (
        <div className="files-layout">
          <div className="file-list-panel">
            {files.map((file) => {
              const active = file.id === selectedId;
              return (
                <button
                  key={file.id}
                  className={`file-list-item ${active ? 'active' : ''}`}
                  onClick={() => setActiveFileId(file.id)}
                  aria-pressed={active}
                >
                  <div className="file-list-top">
                    <span className={`status-dot ${statusClass(file.status)}`} aria-hidden="true" />
                    <strong>{file.original_name}</strong>
                    {file.has_analysis && <Badge variant="success">Analysed</Badge>}
                  </div>
                  <div className="file-list-meta">
                    {file.metadata?.format ?? '—'} · {fmtDuration(file.metadata?.duration)} ·{' '}
                    {fmtHz(file.metadata?.sample_rate)} · {file.metadata?.channels ?? '—'} ch
                  </div>
                  {(file.status === 'analyzing' || file.status === 'queued') && (
                    <ProgressBar value={file.progress} label={`${file.original_name} progress`} />
                  )}
                  {file.status === 'error' && <div className="small error-text">{file.error}</div>}
                </button>
              );
            })}
          </div>

          {selected && (
            <div className="file-detail">
              <Card
                title={selected.original_name}
                subtitle={`${selected.metadata?.format ?? 'Audio'} · ${selected.metadata?.codec ?? 'unknown codec'} · unique ID ${selected.id}`}
                actions={
                  <div className="row-actions">
                    {!selected.has_analysis && selected.status !== 'analyzing' && selected.status !== 'queued' && (
                      <button className="btn btn-primary btn-sm" onClick={() => void analyze([selected.id], true)} disabled={busy}>
                        <Activity size={14} aria-hidden="true" /> Analyze
                      </button>
                    )}
                    {selected.has_analysis && (
                      <button className="btn btn-sm" onClick={() => void analyze([selected.id], true)} disabled={busy}>
                        <RefreshCw size={14} aria-hidden="true" /> Re-analyse
                      </button>
                    )}
                    <button className="btn btn-sm" onClick={() => replace(selected)} disabled={uploadProgress !== null}>
                      <Replace size={14} aria-hidden="true" /> Replace
                    </button>
                    <button className="btn btn-sm btn-danger" onClick={() => void confirmRemove(selected)}>
                      <Trash2 size={14} aria-hidden="true" /> Remove
                    </button>
                  </div>
                }
              >
                <audio className="audio-player" controls preload="metadata" src={api.audioUrl(session!.id, selected.id)}>
                  Your browser cannot play this format. The original file is still available for analysis.
                </audio>
                <div className="meta-cards">
                  <div className="meta-card"><span>Duration</span><b>{fmtDuration(selected.metadata?.duration)}</b></div>
                  <div className="meta-card"><span>Sample rate</span><b>{fmtHz(selected.metadata?.sample_rate)}</b></div>
                  <div className="meta-card"><span>Bit depth</span><b>{selected.metadata?.bit_depth ?? (selected.metadata?.is_lossy ? 'lossy' : 'n/a')}</b></div>
                  <div className="meta-card"><span>Channels</span><b>{selected.metadata?.channels_label ?? selected.metadata?.channels ?? '—'}</b></div>
                  <div className="meta-card"><span>Encoded bitrate</span><b>{selected.metadata?.bitrate_kbps ? `${selected.metadata.bitrate_kbps} kbps` : '—'}</b></div>
                  <div className="meta-card"><span>File size</span><b>{fmtBytes(selected.size_bytes)}</b></div>
                  <div className="meta-card"><span>Frames</span><b>{selected.metadata?.frames?.toLocaleString() ?? '—'}</b></div>
                  <div className="meta-card"><span>Uploaded</span><b>{fmtDate(selected.uploaded_at)}</b></div>
                </div>
                {selected.metadata?.bit_depth_note && (
                  <p className="muted small">{selected.metadata.bit_depth_note}</p>
                )}
                <div className="tag-row">
                  <Badge variant={selected.status === 'complete' ? 'success' : selected.status === 'error' ? 'error' : 'info'}>
                    {selected.status === 'analyzing' ? `${selected.stage} · ${fmt(selected.progress, 0)}%` : titleCase(selected.status)}
                  </Badge>
                  <Badge variant={selected.validation?.ok ? 'success' : 'error'}>
                    {selected.validation?.ok ? 'Validation passed' : 'Validation failed'}
                  </Badge>
                  {selected.validation?.warnings?.length ? <Badge variant="warning">{selected.validation.warnings.length} warning(s)</Badge> : null}
                  {selected.metadata?.is_lossy ? <Badge variant="purple">Lossy codec</Badge> : <Badge variant="neutral">Lossless / PCM</Badge>}
                </div>
                {selected.status === 'analyzing' && <ProgressBar value={selected.progress} label="Analysis progress" />}
                {selected.error && <InfoNote tone="error">{selected.error}</InfoNote>}
              </Card>

              <div className="two-col">
                <Card title="Validation report" subtitle="Container signature, structural checks and decoder probe.">
                  {selected.validation ? (
                    <div className="finding-list">
                      {(selected.validation.errors ?? []).map((error) => (
                        <div className="finding finding-error" key={error}>
                          <AlertTriangle size={16} aria-hidden="true" />
                          <div><strong>Error</strong><p>{error}</p></div>
                        </div>
                      ))}
                      {(selected.validation.warnings ?? []).map((warning) => (
                        <div className="finding finding-warning" key={warning}>
                          <Info size={16} aria-hidden="true" />
                          <div><strong>Warning</strong><p>{warning}</p></div>
                        </div>
                      ))}
                      {(selected.validation.errors?.length ?? 0) === 0 && (selected.validation.warnings?.length ?? 0) === 0 && (
                        <div className="finding finding-ok">
                          <CheckCircle2 size={16} aria-hidden="true" />
                          <div><strong>Valid audio file</strong><p>Signature, structure and decoder probe passed.</p></div>
                        </div>
                      )}
                    </div>
                  ) : (
                    <p className="muted">No validation payload is available.</p>
                  )}
                </Card>

                <Card title="Technical properties" subtitle="Measured from the original file; no resampling was applied.">
                  <KeyValue
                    rows={[
                      { label: 'Format / container', value: `${selected.metadata?.format ?? '—'} / ${selected.metadata?.container ?? '—'}` },
                      { label: 'Codec', value: selected.metadata?.codec ?? '—', mono: true },
                      { label: 'Sample rate', value: fmtHz(selected.metadata?.sample_rate) },
                      { label: 'Bit depth', value: selected.metadata?.bit_depth ? `${selected.metadata.bit_depth} bits (${selected.metadata.bit_depth_source})` : 'Not applicable (lossy)' },
                      { label: 'Encoded bitrate', value: selected.metadata?.bitrate_kbps ? `${selected.metadata.bitrate_kbps} kbps · ${selected.metadata.bitrate_source}` : '—' },
                      { label: 'Channels', value: selected.metadata?.channels_label ?? selected.metadata?.channels ?? '—' },
                      { label: 'Sample frames', value: selected.metadata?.frames?.toLocaleString() ?? '—', mono: true },
                      { label: 'SHA-256', value: analysis?.sha256 ? `${analysis.sha256.slice(0, 32)}…` : 'Available after analysis', mono: true },
                    ]}
                  />
                </Card>
              </div>

              {selected.has_analysis && <AnalysisLoadState fileId={selected.id} label="analysis summary" />}

              {analysis && (
                <Card
                  title="Analysis summary"
                  subtitle="Direct measurements and estimates are kept separate. Open a section for the full evidence."
                  actions={
                    <Badge variant={analysis.qc.overall === 'error' ? 'error' : analysis.qc.overall === 'warning' ? 'warning' : 'success'}>
                      QC {analysis.qc.overall_label}
                    </Badge>
                  }
                >
                  <div className="stat-grid">
                    <div className="stat"><span className="stat-label">Integrated loudness</span><span className="stat-value">{fmt(analysis.loudness.integrated_lufs)}<small>LUFS</small></span></div>
                    <div className="stat"><span className="stat-label">True peak</span><span className="stat-value">{fmt(analysis.loudness.true_peak_dbtp)}<small>dBTP</small></span></div>
                    <div className="stat"><span className="stat-label">Loudness range</span><span className="stat-value">{fmt(analysis.loudness.loudness_range_lu)}<small>LU</small></span></div>
                    <div className="stat"><span className="stat-label">Key (estimate)</span><span className="stat-value">{analysis.musical.key.key ?? '—'}</span></div>
                    <div className="stat"><span className="stat-label">Tempo (estimate)</span><span className="stat-value">{fmt(analysis.musical.tempo.bpm, 0)}<small>BPM</small></span></div>
                    <div className="stat"><span className="stat-label">Stereo correlation</span><span className="stat-value">{analysis.stereo.supported ? fmt(analysis.stereo.correlation?.value, 2) : 'mono'}</span></div>
                  </div>
                  <div className="quick-nav" role="group" aria-label={`Open ${selected.original_name} in`}>
                    {QUICK_LINKS.map(({ section, label, Icon }) => (
                      <button key={section} className="quick-link" onClick={() => navigate(section, { file: selected.id })}>
                        <Icon size={16} aria-hidden="true" /> {label}
                      </button>
                    ))}
                  </div>
                  <div className="qc-mini">
                    {analysis.qc.findings.slice(0, 5).map((finding) => (
                      <div className="qc-mini-row" key={finding.id}>
                        <SeverityBadge severity={finding.severity} />
                        <span>{finding.title}</span>
                        <span className="muted small">{finding.message}</span>
                      </div>
                    ))}
                    {analysis.qc.findings.length === 0 && <p className="muted">No findings outside the configured thresholds.</p>}
                  </div>
                </Card>
              )}
            </div>
          )}
        </div>
      )}

      <InfoNote>
        {analyzed.length} of {files.length} file(s) analysed. Each analysis stores metadata separately from the original audio.
        Removing a file deletes only this session&apos;s copy.
      </InfoNote>
    </div>
  );
}
