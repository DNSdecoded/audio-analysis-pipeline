import { useEffect, useMemo, useState } from 'react';
import {
  Download,
  FileArchive,
  FileJson,
  FileSpreadsheet,
  FileText,
  Image,
  Loader2,
  ShieldCheck,
} from 'lucide-react';
import { useApp } from '../state/AppContext';
import { api, formatError } from '../lib/api';
import { Badge, Card, InfoNote, SectionHeader, Spinner } from '../components/UI';
import { NoAnalysedFiles } from '../components/AnalysisState';
import { FileSelect } from '../components/FileSelect';
import { fmt } from '../lib/format';
import { parseNumberInput, validateLoudnessTargets } from '../lib/inputValidation';

const REPORT_FORMATS: {
  format: 'pdf' | 'json' | 'csv' | 'qc-csv' | 'comparison-csv';
  title: string;
  description: string;
  icon: any;
  needsComparison?: boolean;
}[] = [
  {
    format: 'pdf',
    title: 'PDF report',
    description: 'Combined measurement report with embedded plots, loudness summary, QC findings and comparison tables.',
    icon: FileText,
  },
  {
    format: 'json',
    title: 'JSON export',
    description: 'Complete machine-readable analyses, settings, methods, QC results and optional comparison.',
    icon: FileJson,
  },
  {
    format: 'csv',
    title: 'Measurements CSV',
    description: 'One row per file with the key measured values for spreadsheets and further processing.',
    icon: FileSpreadsheet,
  },
  {
    format: 'qc-csv',
    title: 'QC findings CSV',
    description: 'One row per QC check with severity, measured value, threshold, time positions and recommendation.',
    icon: ShieldCheck,
  },
  {
    format: 'comparison-csv',
    title: 'Comparison CSV',
    description: 'Parameter-by-parameter comparison with tolerance, spread, status and per-file values.',
    icon: FileArchive,
    needsComparison: true,
  },
];

const PLOTS: { kind: string; label: string; description: string; log?: boolean; wide?: boolean }[] = [
  { kind: 'waveform', label: 'Waveform', description: 'Time-domain waveform with peak and RMS envelope.', wide: true },
  { kind: 'spectrum', label: 'Spectrum', description: 'Average FFT magnitude spectrum (log frequency).', log: true, wide: true },
  { kind: 'spectrogram', label: 'Spectrogram', description: 'STFT magnitude over time.', log: true, wide: true },
  { kind: 'loudness', label: 'Loudness', description: 'Momentary, short-term and integrated loudness.', wide: true },
  { kind: 'dynamics', label: 'Dynamics', description: 'Crest factor, RMS and short-term loudness.', wide: true },
  { kind: 'bands', label: 'Frequency bands', description: 'Seven-band energy distribution.' },
  { kind: 'chroma', label: 'Chroma', description: 'Pitch-class energy over time.' },
  { kind: 'tempo', label: 'Tempo', description: 'Onset envelope, beats and local tempo.' },
  { kind: 'pitch', label: 'Pitch', description: 'F0 contour and pitch distribution.' },
  { kind: 'stereo', label: 'Stereo', description: 'Correlation and mid/side timeline.' },
  { kind: 'vectorscope', label: 'Vectorscope', description: 'L/R sample scatter.' },
  { kind: 'mel', label: 'Mel spectrogram', description: 'Perceptual mel-band energy.' },
  { kind: 'rms_peak', label: 'RMS and peak', description: 'Frame RMS and peak over time.', wide: true },
  { kind: 'spectral_features', label: 'Spectral features', description: 'Centroid, bandwidth, rolloff, flatness, flux.' },
];

export default function ReportsSection() {
  const { session, notify } = useApp();
  const files = (session?.files ?? []).filter((file) => file.has_analysis);
  const [selected, setSelected] = useState<string[]>(files.map((file) => file.id));
  const [includeComparison, setIncludeComparison] = useState(true);
  const [targetText, setTargetText] = useState(String(session?.settings.target_lufs ?? -14));
  const [limitText, setLimitText] = useState(String(session?.settings.true_peak_limit ?? -1));
  const target = parseNumberInput(targetText);
  const limit = parseNumberInput(limitText);
  const targetErrors = validateLoudnessTargets(target, limit);
  const targetsInvalid = Boolean(targetErrors.target || targetErrors.limit);
  const [busyFormat, setBusyFormat] = useState<string | null>(null);
  const [plotFile, setPlotFile] = useState<string>('');
  const [plotBusy, setPlotBusy] = useState<string | null>(null);

  useEffect(() => {
    if (files.length && (!selected.length || !selected.every((id) => files.some((file) => file.id === id)))) {
      setSelected(files.map((file) => file.id));
    }
  }, [files, selected]);

  useEffect(() => {
    if (files.length && (!plotFile || !files.some((file) => file.id === plotFile))) {
      setPlotFile(files[0].id);
    }
  }, [files, plotFile]);

  useEffect(() => {
    if (session) {
      setTargetText(String(session.settings.target_lufs));
      setLimitText(String(session.settings.true_peak_limit));
    }
  }, [session?.settings.target_lufs, session?.settings.true_peak_limit]);

  const totalDuration = useMemo(
    () =>
      files
        .filter((file) => selected.includes(file.id))
        .reduce((sum, file) => sum + Number(file.metadata?.duration ?? 0), 0),
    [files, selected],
  );

  const download = async (format: (typeof REPORT_FORMATS)[number]['format']) => {
    if (!session || targetsInvalid) return;
    setBusyFormat(format);
    try {
      const filename = await api.downloadReport(session.id, {
        format,
        file_ids: selected,
        include_comparison: includeComparison,
        target_lufs: target,
        true_peak_limit: limit,
      });
      notify('success', 'Report downloaded', filename);
    } catch (error) {
      notify('error', 'Report generation failed', formatError(error));
    } finally {
      setBusyFormat(null);
    }
  };

  const downloadPlot = async (kind: string, log?: boolean) => {
    if (!session || !plotFile) return;
    setPlotBusy(kind);
    try {
      const filename = await api.downloadPlot(session.id, plotFile, kind, { log });
      notify('success', 'Plot exported', filename);
    } catch (error) {
      notify('error', 'Plot export failed', formatError(error));
    } finally {
      setPlotBusy(null);
    }
  };

  if (!files.length) {
    return (
      <div className="section-stack">
        <SectionHeader title="Reports and exports" subtitle="PDF, JSON, CSV and per-plot PNG exports." />
        <NoAnalysedFiles icon={<Download size={28} aria-hidden="true" />} description="Analyse at least one file to generate reports." />
      </div>
    );
  }

  return (
    <div className="section-stack">
      <SectionHeader
        title="Reports and exports"
        subtitle="Individual or combined reports. Exports contain measured values, methods and confidence labels — never simulated data."
      />

      <Card title="Report selection" subtitle="Choose which analysed files are included.">
        <FileSelect files={files} selected={selected} onChange={setSelected} multiple label="Files in report" />
        <div className="toolbar-grid">
          <div className="inline-inputs">
            <label>
              Comparison gain target (LUFS)
              <input type="number" min={-60} max={0} step={0.1} value={targetText} aria-invalid={!!targetErrors.target} aria-describedby="rep-target-msg" onChange={(event) => setTargetText(event.target.value)} />
              <span id="rep-target-msg" className={targetErrors.target ? 'error-text small' : 'muted small'}>{targetErrors.target ?? 'Used for the gain preview in the comparison table'}</span>
            </label>
            <label>
              Comparison true-peak limit (dBTP)
              <input type="number" min={-20} max={0} step={0.1} value={limitText} aria-invalid={!!targetErrors.limit} aria-describedby="rep-limit-msg" onChange={(event) => setLimitText(event.target.value)} />
              <span id="rep-limit-msg" className={targetErrors.limit ? 'error-text small' : 'muted small'}>{targetErrors.limit ?? 'Per-file QC uses the session settings'}</span>
            </label>
            <label className="check-label">
              <input
                type="checkbox"
                checked={includeComparison}
                onChange={(event) => setIncludeComparison(event.target.checked)}
              />
              Include comparison (2+ files)
            </label>
          </div>
          <span className="muted small">
            {selected.length} file(s) · {fmt(totalDuration, 1)} s of audio · {session?.settings.fft_size ?? '—'} FFT /{' '}
            {session?.settings.hop_length ?? '—'} hop
          </span>
        </div>
        <InfoNote>
          PDF reports embed the same plot renderers used by the API. JSON includes the full analysis payload and can be large for
          long files. CSV exports use UTF-8 with a byte-order mark for Excel compatibility.
        </InfoNote>
      </Card>

      <div className="report-grid">
        {REPORT_FORMATS.map((item) => {
          const Icon = item.icon;
          const disabled =
            busyFormat !== null ||
            targetsInvalid ||
            (item.needsComparison && (!includeComparison || selected.length < 2));
          return (
            <div className="report-card" key={item.format}>
              <div className="report-icon"><Icon size={22} aria-hidden="true" /></div>
              <div className="report-copy">
                <h3>{item.title}</h3>
                <p>{item.description}</p>
                {item.needsComparison && (
                  <Badge variant={selected.length >= 2 ? 'success' : 'neutral'}>
                    {selected.length >= 2 ? `${selected.length} files` : 'needs 2+ files'}
                  </Badge>
                )}
              </div>
              <button className="btn btn-primary" disabled={disabled} onClick={() => void download(item.format)} aria-label={`Download ${item.title}`}>
                {busyFormat === item.format ? <Loader2 size={15} className="spin" aria-hidden="true" /> : <Download size={15} aria-hidden="true" />} Download
              </button>
            </div>
          );
        })}
      </div>

      <Card
        title="Plot exports"
        subtitle="Server-rendered PNG files at print resolution. The same builders are used inside the PDF report."
      >
        <FileSelect files={files} selected={plotFile ? [plotFile] : []} onChange={(ids) => setPlotFile(ids[0])} label="Plot file" />
        <div className="plot-export-grid">
          {PLOTS.map((plot) => (
            <div className="plot-export-card" key={plot.kind}>
              <div className="plot-export-head">
                <Image size={16} aria-hidden="true" />
                <strong>{plot.label}</strong>
              </div>
              <p className="muted small">{plot.description}</p>
              <button
                className="btn btn-sm"
                disabled={!plotFile || plotBusy !== null}
                aria-label={`Download ${plot.label} PNG`}
                onClick={() => void downloadPlot(plot.kind, plot.log)}
              >
                {plotBusy === plot.kind ? <Loader2 size={13} className="spin" aria-hidden="true" /> : <Download size={13} aria-hidden="true" />} PNG
              </button>
            </div>
          ))}
        </div>
        {!plotFile && (
          <div className="loading-row">
            <Spinner /> Waiting for an analysed file…
          </div>
        )}
      </Card>

      <Card title="What is included" subtitle="Report contents and provenance.">
        <div className="three-col">
          <div>
            <h4>Measurements</h4>
            <ul className="clean-list">
              <li>File metadata and validation warnings</li>
              <li>Loudness (BS.1770-4 / EBU R128), true peak, PLR</li>
              <li>Time-domain level, DC, clipping, silence, dropouts</li>
              <li>Spectral features, bands, chroma, tempo, pitch</li>
              <li>Stereo correlation, width and mono compatibility</li>
            </ul>
          </div>
          <div>
            <h4>Quality control</h4>
            <ul className="clean-list">
              <li>Every check with severity and explanation</li>
              <li>Measured value and threshold side by side</li>
              <li>Time positions for localised findings</li>
              <li>Recommended action and confidence</li>
              <li>Thresholds stored with the session</li>
            </ul>
          </div>
          <div>
            <h4>Provenance</h4>
            <ul className="clean-list">
              <li>SHA-256 of the original file</li>
              <li>Analysis settings and library versions</li>
              <li>Methods and limitations per measurement</li>
              <li>Estimated values labelled with confidence</li>
              <li>Original audio is never modified</li>
            </ul>
          </div>
        </div>
      </Card>
    </div>
  );
}
