import { useState } from 'react';
import { Grid3X3, Loader2, RefreshCw } from 'lucide-react';
import { useApp } from '../state/AppContext';
import { useFileSelection } from '../state/useFileSelection';
import { api, formatError } from '../lib/api';
import { Badge, Card, InfoNote, SectionHeader, ToggleGroup } from '../components/UI';
import { AnalysisLoadState, NoAnalysedFiles } from '../components/AnalysisState';
import { PlotDownloadButton } from '../components/PlotDownloadButton';
import { FileSelect } from '../components/FileSelect';
import Plot from '../components/Plot';
import { MAGMA } from '../lib/plotTheme';
import { useWorkspace } from '../state/Workspace';
import { fmt } from '../lib/format';
import { FFT_SIZES, HOP_SIZES, hasErrors, parseNumberInput, validateColorRange, validateFftHop, validateTimeRange } from '../lib/inputValidation';

type Mode = 'stft' | 'mel';

export default function SpectrogramSection() {
  const { session, analyses, notify } = useApp();
  const { files, selected, setSelected } = useFileSelection({ multiple: true, defaultCount: 2 });
  const [mode, setMode] = useState<Mode>('stft');
  const { chartPrefs } = useWorkspace();
  // Log frequency by default (Settings → chart preferences): on a linear 0–20 kHz
  // axis most musical energy is squeezed into the bottom few pixels.
  const [logFrequency, setLogFrequency] = useState(chartPrefs.logFrequency);
  const [nFft, setNFft] = useState<number>(session?.settings.fft_size ?? 4096);
  const [hop, setHop] = useState<number>(session?.settings.hop_length ?? 1024);
  const [maxFrames, setMaxFrames] = useState(400);
  const [zText, setZText] = useState({ min: '-100', max: '0' });
  const [range, setRange] = useState({ start: '', end: '' });
  const [custom, setCustom] = useState<Record<string, any>>({});
  const [computing, setComputing] = useState(false);

  const primary = files.find((file) => file.id === selected[0]);
  const duration = Number(primary?.metadata?.duration ?? 0);
  const fftErrors = validateFftHop(nFft, hop);
  const rangeErrors = validateTimeRange(range.start, range.end, duration);
  const colorErrors = validateColorRange(parseNumberInput(zText.min), parseNumberInput(zText.max));
  // An invalid colour range (e.g. floor ≥ ceiling) would draw a blank map;
  // keep drawing with the last valid default until it is corrected.
  const zMin = hasErrors(colorErrors) ? -100 : parseNumberInput(zText.min);
  const zMax = hasErrors(colorErrors) ? 0 : parseNumberInput(zText.max);
  const framesError = !Number.isInteger(maxFrames) || maxFrames < 50 || maxFrames > 1200 ? 'Time bins must be a whole number from 50 to 1200.' : undefined;
  const invalid = hasErrors(fftErrors) || hasErrors(rangeErrors) || !!framesError;

  const compute = async () => {
    if (!session || invalid) return;
    const start = range.start === '' ? undefined : Number(range.start);
    const end = range.end === '' ? (start !== undefined ? duration : undefined) : Number(range.end);
    setComputing(true);
    try {
      const entries = await Promise.all(
        selected.map(async (id) => {
          const result = await api.getSpectrogram(session.id, id, {
            start,
            end,
            n_fft: nFft,
            hop_length: hop,
            max_frames: maxFrames,
          });
          return [id, result] as const;
        }),
      );
      setCustom(Object.fromEntries(entries));
      notify('success', 'Spectrogram recomputed', `${nFft}-point FFT · hop ${hop}`);
    } catch (error) {
      notify('error', 'Spectrogram computation failed', formatError(error));
    } finally {
      setComputing(false);
    }
  };

  if (!files.length) {
    return (
      <div className="section-stack">
        <SectionHeader title="Spectrogram analysis" subtitle="STFT and Mel time-frequency views." />
        <NoAnalysedFiles icon={<Grid3X3 size={28} aria-hidden="true" />} description="Run analysis to compute spectrograms." />
      </div>
    );
  }

  return (
    <div className="section-stack">
      <SectionHeader
        title="Spectrogram analysis"
        subtitle="Time-frequency energy from the measured STFT. Compare up to four files side by side."
        actions={
          <PlotDownloadButton
            fileId={primary?.id}
            fileName={primary?.original_name}
            kind={mode === 'stft' ? 'spectrogram' : 'mel'}
            plotName={mode === 'stft' ? 'spectrogram' : 'mel spectrogram'}
            log={mode === 'stft' ? logFrequency : undefined}
          />
        }
      />

      <Card>
        <ToggleGroup
          label="Spectrogram type"
          value={mode}
          onChange={setMode}
          options={[
            { value: 'stft', label: 'STFT spectrogram' },
            { value: 'mel', label: 'Mel spectrogram' },
          ]}
        />
        <FileSelect files={files} selected={selected} onChange={setSelected} multiple label="Overlay files (the active file is always first)" max={4} />
        <div className="toolbar-grid">
          <fieldset className="inline-inputs fieldset-plain" disabled={mode === 'mel'}>
            <legend className="sr-only">STFT computation</legend>
              <label>
                FFT size
                <select value={nFft} aria-invalid={!!fftErrors.nFft} aria-describedby="sg-fft-err" onChange={(event) => setNFft(Number(event.target.value))}>
                  {FFT_SIZES.map((size) => <option key={size} value={size}>{size}</option>)}
                </select>
                {fftErrors.nFft && <span id="sg-fft-err" className="error-text small">{fftErrors.nFft}</span>}
              </label>
              <label>
                Hop
                <select value={hop} aria-invalid={!!fftErrors.hop} aria-describedby="sg-hop-err" onChange={(event) => setHop(Number(event.target.value))}>
                  {HOP_SIZES.map((size) => <option key={size} value={size} disabled={size > nFft}>{size}{size > nFft ? ' (exceeds window)' : ''}</option>)}
                </select>
                {fftErrors.hop && <span id="sg-hop-err" className="error-text small">{fftErrors.hop}</span>}
              </label>
            <label>
              Max time bins
              <input type="number" min={50} max={1200} step={50} value={Number.isFinite(maxFrames) ? maxFrames : ''} aria-invalid={!!framesError} aria-describedby="sg-frames-err" onChange={(event) => setMaxFrames(parseNumberInput(event.target.value))} />
              {framesError && <span id="sg-frames-err" className="error-text small">{framesError}</span>}
            </label>
              <label>
                Start (s)
                <input type="number" min={0} max={duration} step={0.1} placeholder="0" value={range.start} aria-invalid={!!rangeErrors.start} aria-describedby="sg-start-err" onChange={(event) => setRange({ ...range, start: event.target.value })} />
                {rangeErrors.start && <span id="sg-start-err" className="error-text small">{rangeErrors.start}</span>}
              </label>
              <label>
                End (s)
                <input type="number" min={0} max={duration} step={0.1} placeholder={fmt(duration, 1)} value={range.end} aria-invalid={!!rangeErrors.end} aria-describedby="sg-end-err" onChange={(event) => setRange({ ...range, end: event.target.value })} />
                {rangeErrors.end && <span id="sg-end-err" className="error-text small">{rangeErrors.end}</span>}
              </label>
            <button className="btn btn-sm btn-primary" onClick={compute} disabled={computing || invalid}>
              {computing ? <Loader2 size={14} className="spin" aria-hidden="true" /> : <RefreshCw size={14} aria-hidden="true" />} Recompute
            </button>
          </fieldset>
          <div className="inline-inputs">
            <label className="check-label"><input type="checkbox" checked={logFrequency} onChange={(event) => setLogFrequency(event.target.checked)} disabled={mode === 'mel'} /> Log frequency (STFT)</label>
            <label>
              Floor (dB)
              <input type="number" min={-160} max={20} step={5} value={zText.min} aria-invalid={!!colorErrors.floor} aria-describedby="sg-floor-err" onChange={(event) => setZText({ ...zText, min: event.target.value })} />
              {colorErrors.floor && <span id="sg-floor-err" className="error-text small">{colorErrors.floor}</span>}
            </label>
            <label>
              Ceiling (dB)
              <input type="number" min={-150} max={20} step={5} value={zText.max} aria-invalid={!!colorErrors.ceiling} aria-describedby="sg-ceiling-err" onChange={(event) => setZText({ ...zText, max: event.target.value })} />
              {colorErrors.ceiling && <span id="sg-ceiling-err" className="error-text small">{colorErrors.ceiling}</span>}
            </label>
          </div>
        </div>
        {mode === 'mel' && <InfoNote tone="info">Mel views use the stored analysis at the default STFT settings. The Mel filterbank is Slaney-normalised.</InfoNote>}
        {Object.keys(custom).length > 0 && mode === 'stft' && <Badge variant="accent">Custom STFT computation</Badge>}
      </Card>

      <div className="spectrogram-grid">
        {selected.map((id) => {
          const file = files.find((candidate) => candidate.id === id);
          const analysis = analyses[id];
          if (!file) return null;
          if (!analysis) return <AnalysisLoadState key={id} fileId={id} label={`spectrogram of ${file.original_name}`} />;
          const stft = custom[id] ?? analysis.spectral.spectrogram;
          const mel = analysis.spectral.mel;
          const data = mode === 'stft'
            ? {
                x: stft.times,
                y: logFrequency ? stft.log_frequencies_hz : stft.frequencies_hz,
                z: logFrequency ? stft.log_magnitude_db : stft.magnitude_db,
              }
            : { x: mel.times, y: mel.frequencies_hz, z: mel.power_db };
          return (
            <Card
              key={id}
              title={file.original_name}
              subtitle={`${mode === 'stft' ? `${stft.n_fft ?? nFft}-point FFT · hop ${stft.hop_length ?? hop}` : `${mel.n_mels} Mel bands`} · ${fmt(analysis.metadata.duration)} s`}
              className="spectrogram-card"
            >
              <Plot
                title={`${mode === 'stft' ? 'STFT' : 'Mel'} spectrogram of ${file.original_name}`}
                summary={`Time-frequency energy heatmap; colour range ${zMin} to ${zMax} dB.`}
                data={[
                  {
                    x: data.x,
                    y: data.y,
                    z: data.z,
                    type: 'heatmap',
                    colorscale: mode === 'stft' ? MAGMA : 'Viridis',
                    zmin: zMin,
                    zmax: zMax,
                    colorbar: { title: { text: mode === 'stft' ? 'dBFS' : 'dB' }, thickness: 10, len: 0.85, tickfont: { size: 9 } },
                    hovertemplate: '%{x:.2f} s · %{y:.0f} Hz · %{z:.1f} dB<extra></extra>',
                  },
                ]}
                layout={{
                  height: 330,
                  margin: { l: 58, r: 12, t: 12, b: 42 },
                  xaxis: { title: { text: 'Time (s)' } },
                  yaxis: {
                    title: { text: 'Frequency (Hz)' },
                    type: logFrequency && mode === 'stft' ? 'log' : 'linear',
                    range: logFrequency && mode === 'stft' ? [Math.log10(20), Math.log10(20000)] : [0, Math.min(20000, Number(data.y.at(-1) ?? 20000))],
                  },
                  showlegend: false,
                }}
                height={330}
              />
              <p className="muted small">
                {mode === 'stft'
                  ? `Time bins ${stft.times?.length ?? 0} · frequency bins ${stft.frequencies_hz?.length ?? 0}. Color range ${zMin} to ${zMax} dB.`
                  : `Mel bands ${mel.n_mels} · ${mel.fmin_hz}–${mel.fmax_hz} Hz.`}
              </p>
            </Card>
          );
        })}
      </div>

      <InfoNote>
        The spectrogram is an STFT magnitude display. Dark areas indicate low energy at that time and frequency; they are not
        necessarily silence. Use the color range controls and the FFT/hop settings to inspect detail. Original audio is not
        resampled or modified.
      </InfoNote>
    </div>
  );
}
