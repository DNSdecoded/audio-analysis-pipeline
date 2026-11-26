import { Fragment, useEffect, useState } from 'react';
import {
  Cpu,
  Database,
  Info,
  Palette,
  RefreshCw,
  Save,
  Settings2,
  ShieldCheck,
  Trash2,
} from 'lucide-react';
import { useApp } from '../state/AppContext';
import { useWorkspace } from '../state/Workspace';
import { useConfirm } from '../components/ConfirmDialog';
import { validateSettings } from '../lib/settingsValidation';
import { Badge, Card, InfoNote, SectionHeader, Stat, ToggleGroup } from '../components/UI';
import { fmt } from '../lib/format';

const DENSITY_KEY = 'aap_density';
const MOTION_KEY = 'aap_reduce_motion';

export default function SettingsSection() {
  const { session, appSettings, saveSettings, resetSession, busy, notify } = useApp();
  const { theme, themePreference, setThemePreference, chartPrefs, setChartPrefs } = useWorkspace();
  const confirm = useConfirm();
  const [name, setName] = useState('');
  const [target, setTarget] = useState(-14);
  const [limit, setLimit] = useState(-1);
  const [fftSize, setFftSize] = useState(2048);
  const [hopLength, setHopLength] = useState(512);
  const [density, setDensity] = useState<'comfortable' | 'compact'>(localStorage.getItem(DENSITY_KEY) === 'compact' ? 'compact' : 'comfortable');
  const [reduceMotion, setReduceMotion] = useState(localStorage.getItem(MOTION_KEY) === 'true');

  useEffect(() => {
    if (!session) return;
    setName(session.name);
    setTarget(session.settings.target_lufs);
    setLimit(session.settings.true_peak_limit);
    setFftSize(session.settings.fft_size);
    setHopLength(session.settings.hop_length);
  }, [session?.id, session?.settings.target_lufs, session?.settings.true_peak_limit, session?.settings.fft_size, session?.settings.hop_length, session?.name]);

  useEffect(() => {
    document.documentElement.dataset.density = density;
    localStorage.setItem(DENSITY_KEY, density);
  }, [density]);

  useEffect(() => {
    document.documentElement.dataset.reduceMotion = String(reduceMotion);
    localStorage.setItem(MOTION_KEY, String(reduceMotion));
  }, [reduceMotion]);

  const analysisSettingsChanged =
    session && (fftSize !== session.settings.fft_size || hopLength !== session.settings.hop_length);
  const errors = validateSettings({ name, target, limit, fftSize, hopLength });
  const dirty =
    !!session &&
    (name !== session.name ||
      target !== session.settings.target_lufs ||
      limit !== session.settings.true_peak_limit ||
      fftSize !== session.settings.fft_size ||
      hopLength !== session.settings.hop_length);

  const cancel = () => {
    if (!session) return;
    setName(session.name);
    setTarget(session.settings.target_lufs);
    setLimit(session.settings.true_peak_limit);
    setFftSize(session.settings.fft_size);
    setHopLength(session.settings.hop_length);
  };

  const save = async () => {
    if (Object.keys(errors).length) {
      notify('warning', 'Settings not saved', Object.values(errors).join(' '));
      return;
    }
    await saveSettings(
      {
        name: name.trim() || 'Audio analysis session',
        target_lufs: target,
        true_peak_limit: limit,
        fft_size: fftSize,
        hop_length: hopLength,
      },
      true,
    );
  };

  const reset = async () => {
    const ok = await confirm({
      title: 'Delete this session permanently?',
      message: `All ${session?.files.length ?? 0} uploaded file(s) and their analysis results are removed from the server, and a new empty session starts. This cannot be undone. To keep this session, use “New analysis” on the dashboard instead.`,
      confirmLabel: 'Delete session',
      destructive: true,
    });
    if (ok) await resetSession();
  };

  // The server always returns a full threshold map (defaults merged in), so
  // "custom" means: differs from the server defaults.
  const customThresholds =
    !!session?.settings.qc_thresholds &&
    !!appSettings?.qc_thresholds &&
    Object.entries(appSettings.qc_thresholds).some(
      ([key, value]) => JSON.stringify((session.settings.qc_thresholds as Record<string, unknown>)[key]) !== JSON.stringify(value),
    );
  const fftOptions = Array.from(new Set([512, 1024, 2048, 4096, 8192, 16384, ...(session ? [session.settings.fft_size] : [])])).sort((a, b) => a - b);
  const hopOptions = Array.from(new Set([128, 256, 512, 1024, 2048, 4096, ...(session ? [session.settings.hop_length] : [])])).sort((a, b) => a - b);

  return (
    <div className="section-stack">
      <SectionHeader
        title="Settings"
        subtitle="Session defaults, analysis parameters, appearance and system information."
        actions={
          <>
            <button className="btn btn-sm" onClick={cancel} disabled={busy || !dirty}>
              Cancel changes
            </button>
            <button className="btn btn-primary btn-sm" onClick={() => void save()} disabled={busy || !session || !dirty || Object.keys(errors).length > 0}>
              <Save size={14} aria-hidden="true" /> Save settings
            </button>
          </>
        }
      />

      <div className="two-col">
        <Card title="Session" subtitle="A session groups the files you compare together.">
          <div className="form-stack">
            <label>
              Session name
              <input type="text" maxLength={80} value={name} aria-invalid={!!errors.name} aria-describedby="err-name" onChange={(event) => setName(event.target.value)} />
              {errors.name && <span id="err-name" className="error-text small">{errors.name}</span>}
            </label>
            <div className="inline-inputs">
              <label>
                Target loudness
                <span className="input-with-unit">
                  <input type="number" min={-60} max={0} step={0.1} value={Number.isFinite(target) ? target : ''} aria-invalid={!!errors.target} aria-describedby="err-target" onChange={(event) => setTarget(event.target.value === '' ? NaN : Number(event.target.value))} />
                  <span className="unit">LUFS</span>
                </span>
                <span id="err-target" className={errors.target ? 'error-text small' : 'muted small'}>{errors.target ?? 'Typical: −14 streaming, −23 broadcast'}</span>
              </label>
              <label>
                True-peak limit
                <span className="input-with-unit">
                  <input type="number" min={-20} max={0} step={0.1} value={Number.isFinite(limit) ? limit : ''} aria-invalid={!!errors.limit} aria-describedby="err-limit" onChange={(event) => setLimit(event.target.value === '' ? NaN : Number(event.target.value))} />
                  <span className="unit">dBTP</span>
                </span>
                <span id="err-limit" className={errors.limit ? 'error-text small' : 'muted small'}>{errors.limit ?? 'Typical: −1 dBTP'}</span>
              </label>
            </div>
            <p className="muted small">
              Target values are used for the non-destructive gain preview, QC loudness limits and report summaries. They never
              change the audio.
            </p>
          </div>
        </Card>

        <Card title="Analysis parameters" subtitle="Applied the next time a file is analysed.">
          <div className="form-stack">
            <label>
              FFT size
              <select value={fftSize} aria-invalid={!!errors.fftSize} aria-describedby="err-fft" onChange={(event) => setFftSize(Number(event.target.value))}>
                {fftOptions.map((size) => (
                  <option key={size} value={size}>{size} samples</option>
                ))}
              </select>
              {errors.fftSize && <span id="err-fft" className="error-text small">{errors.fftSize}</span>}
            </label>
            <label>
              Hop length
              <select value={hopLength} aria-invalid={!!errors.hopLength} aria-describedby="err-hop" onChange={(event) => setHopLength(Number(event.target.value))}>
                {hopOptions.map((size) => (
                  <option key={size} value={size} disabled={size > fftSize}>
                    {size} samples ({Math.round((1 - size / fftSize) * 100)}% overlap){size > fftSize ? ' — larger than FFT size' : ''}
                  </option>
                ))}
              </select>
              {errors.hopLength && <span id="err-hop" className="error-text small">{errors.hopLength}</span>}
            </label>
            <div className="kv-grid">
              <span>Window type</span><b>Hann (periodic) — fixed by the analysis engine</b>
              <span>Frequency resolution</span><b>{`${fmt(44100 / fftSize, 2)} Hz at 44.1 kHz · ${fmt(48000 / fftSize, 2)} Hz at 48 kHz`}</b>
            </div>
            <p className="muted small">
              FFT size controls frequency resolution; hop length controls time resolution. Larger FFT windows give finer
              frequency detail and coarser time detail.
            </p>
            {analysisSettingsChanged && (
              <InfoNote tone="warning">
                FFT size or hop length differs from the analysed files. Re-analyse files on the Files page to apply the new
                values; existing analyses keep the settings they were measured with.
              </InfoNote>
            )}
          </div>
        </Card>
      </div>

      <div className="two-col">
        <Card title="Appearance" subtitle="Display preferences are stored in this browser only.">
          <div className="form-stack">
            <div className="control-group">
              <div className="field-label"><Palette size={14} aria-hidden="true" /> Theme</div>
              <ToggleGroup
                label="Theme"
                value={themePreference}
                onChange={setThemePreference}
                options={[
                  { value: 'light', label: 'Light — Slate & Cobalt' },
                  { value: 'dark', label: 'Dark — Obsidian & Indigo' },
                  { value: 'system', label: `System (now ${theme})` },
                ]}
              />
            </div>
            <div className="control-group">
              <div className="field-label">Chart display</div>
              <label className="check-label">
                <input type="checkbox" checked={chartPrefs.logFrequency} onChange={(event) => setChartPrefs({ logFrequency: event.target.checked })} />
                Logarithmic frequency axis by default (spectrum and spectrogram)
              </label>
              <label className="check-label">
                <input type="checkbox" checked={chartPrefs.alwaysShowToolbar} onChange={(event) => setChartPrefs({ alwaysShowToolbar: event.target.checked })} />
                Always show chart toolbar (zoom, pan, reset, PNG) instead of on hover
              </label>
            </div>
            <div className="control-group">
              <div className="field-label">Interface density</div>
              <ToggleGroup
                label="Interface density"
                value={density}
                onChange={setDensity}
                options={[
                  { value: 'comfortable', label: 'Comfortable' },
                  { value: 'compact', label: 'Compact' },
                ]}
              />
            </div>
            <label className="check-label">
              <input type="checkbox" checked={reduceMotion} onChange={(event) => setReduceMotion(event.target.checked)} />
              Reduce animations and transitions
            </label>
            <p className="muted small">
              Preferences are stored in this browser. Chart series colours are the same in both themes and meet 3:1 contrast on
              either background.
            </p>
          </div>
        </Card>

        <Card title="Session management" subtitle="Temporary server data.">
          <div className="form-stack">
            <div className="kv-grid">
              <span>Session id</span><b className="mono">{session?.id ?? '—'}</b>
              <span>Files</span><b>{session?.files.length ?? 0}</b>
              <span>Analysed</span><b>{session?.files.filter((file) => file.has_analysis).length ?? 0}</b>
              <span>Created</span><b>{session ? new Date(session.created_at).toLocaleString() : '—'}</b>
            </div>
            <InfoNote tone="warning">
              Sessions expire automatically after the configured retention period. “Delete session” permanently removes this
              session's uploaded files and analysis results. To keep it, use “New analysis” on the dashboard instead.
            </InfoNote>
            <button className="btn btn-danger" onClick={() => void reset()} disabled={busy}>
              <Trash2 size={15} aria-hidden="true" /> Delete this session and start a new one
            </button>
          </div>
        </Card>
      </div>

      {appSettings && (
        <>
          <div className="stat-grid">
            <Stat label="Server version" value={appSettings.version} tone="accent" />
            <Stat label="Max file size" value={fmt(appSettings.limits.max_file_size_mb, 0)} unit="MB" />
            <Stat label="Max duration" value={fmt(appSettings.limits.max_duration_seconds, 0)} unit="s" />
            <Stat label="Max files / session" value={appSettings.limits.max_files_per_session} />
            <Stat label="Concurrent jobs" value={appSettings.limits.max_concurrent_jobs} />
            <Stat label="Session TTL" value={fmt(appSettings.limits.session_ttl_hours, 0)} unit="h" />
          </div>

          <div className="two-col">
            <Card title="Supported formats" subtitle="Validated on upload before analysis.">
              <div className="chip-wrap">
                {appSettings.supported_formats.map((format) => (
                  <Badge key={format} variant="accent">{format}</Badge>
                ))}
              </div>
              <p className="muted small">
                Extensions: {appSettings.supported_extensions.join(', ')}. Lossy formats do not expose a meaningful PCM bit
                depth; the platform reports the encoded bitrate instead.
              </p>
              <div className="kv-grid">
                <span>Default target</span><b>{fmt(appSettings.defaults.target_lufs)} LUFS</b>
                <span>Default true-peak limit</span><b>{fmt(appSettings.defaults.true_peak_limit)} dBTP</b>
                <span>Default FFT size</span><b>{appSettings.defaults.fft_size}</b>
                <span>Default hop length</span><b>{appSettings.defaults.hop_length}</b>
              </div>
            </Card>

            <Card title="Measurement methods" subtitle="Every report states the method used.">
              <div className="kv-grid">
                {Object.entries(appSettings.methods).map(([key, value]) => (
                  <Fragment key={key}>
                    <span>{key.replaceAll('_', ' ')}</span>
                    <b>{value}</b>
                  </Fragment>
                ))}
              </div>
              <ul className="clean-list">
                {appSettings.notes.map((note) => <li key={note}>{note}</li>)}
              </ul>
            </Card>
          </div>

          <Card title="Processing model" subtitle="Read-only guarantees.">
            <div className="three-col">
              <div>
                <h4><ShieldCheck size={16} aria-hidden="true" /> Originals preserved</h4>
                <p className="muted small">
                  Uploaded files are stored byte-for-byte and never rewritten. All measurements are computed from decoded
                  copies in memory.
                </p>
              </div>
              <div>
                <h4><Cpu size={16} aria-hidden="true" /> Local analysis</h4>
                <p className="muted small">
                  Analysis runs on the server with NumPy, SciPy, librosa, soundfile and PyAV. No third-party audio service is
                  involved.
                </p>
              </div>
              <div>
                <h4><Database size={16} aria-hidden="true" /> Separate artifacts</h4>
                <p className="muted small">
                  Analysis JSON, plots and reports are stored separately from the original audio and are removed when the
                  session expires.
                </p>
              </div>
            </div>
          </Card>
        </>
      )}

      <Card title="About estimated measurements" subtitle="Measured vs estimated.">
        <div className="three-col">
          <div>
            <Badge variant="success">Measured</Badge>
            <p className="muted small">
              Loudness, peaks, RMS, DC offset, clipping, silence, dropouts, spectrum, spectral features, band energy, stereo
              correlation and width are direct measurements with defined methods.
            </p>
          </div>
          <div>
            <Badge variant="warning">Estimated</Badge>
            <p className="muted small">
              Key, tempo and pitch are algorithmic estimates. They include confidence values, alternatives where available, and
              explicit limitations.
            </p>
          </div>
          <div>
            <Badge variant="info">Context</Badge>
            <p className="muted small">
              Low dynamics, wide stereo or high loudness are not automatically defects. QC separates observations from
              threshold-based warnings and errors.
            </p>
          </div>
        </div>
        <div className="legend-note">
          <span><Info size={13} aria-hidden="true" /> Analysis settings: {session?.settings.fft_size ?? '—'} FFT · {session?.settings.hop_length ?? '—'} hop</span>
          <span><Settings2 size={13} aria-hidden="true" /> {appSettings ? (customThresholds ? 'Custom QC thresholds active' : 'Default QC thresholds') : 'QC thresholds: loading…'}</span>
          <span><RefreshCw size={13} aria-hidden="true" /> QC recomputes automatically after settings changes</span>
        </div>
      </Card>
    </div>
  );
}
