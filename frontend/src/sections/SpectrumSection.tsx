import { useMemo, useState } from 'react';
import { AudioLines, Loader2, RefreshCw, RotateCcw } from 'lucide-react';
import { useApp } from '../state/AppContext';
import { useFileSelection } from '../state/useFileSelection';
import { useWorkspace } from '../state/Workspace';
import { api, formatError } from '../lib/api';
import { Badge, Card, InfoNote, SectionHeader, TableWrap } from '../components/UI';
import { AnalysisLoadState, NoAnalysedFiles } from '../components/AnalysisState';
import { PlotDownloadButton } from '../components/PlotDownloadButton';
import { FileSelect } from '../components/FileSelect';
import Plot from '../components/Plot';
import { COLORS, bandShapes, rgba } from '../lib/plotTheme';
import { fmt, fmtHz } from '../lib/format';
import { FFT_SIZES, HOP_SIZES, hasErrors, validateFftHop, validateTimeRange } from '../lib/inputValidation';

export default function SpectrumSection() {
  const { session, analyses, notify } = useApp();
  const { chartPrefs } = useWorkspace();
  const { files, selected, setSelected } = useFileSelection({ multiple: true, defaultCount: 2 });
  // Default follows Settings → "Logarithmic frequency axis by default".
  const [logScale, setLogScale] = useState(chartPrefs.logFrequency);
  const [nFft, setNFft] = useState<number>(session?.settings.fft_size ?? 4096);
  const [hop, setHop] = useState<number>(session?.settings.hop_length ?? 1024);
  const [range, setRange] = useState<{ start: string; end: string }>({ start: '', end: '' });
  const [segmentData, setSegmentData] = useState<Record<string, any>>({});
  const [computing, setComputing] = useState(false);

  const primary = files.find((file) => file.id === selected[0]);
  const primaryAnalysis = primary ? analyses[primary.id] : undefined;
  const primaryFft = primary ? segmentData[primary.id] ?? primaryAnalysis?.spectral.fft : undefined;
  const duration = Number(primary?.metadata?.duration ?? 0);
  const fftErrors = validateFftHop(nFft, hop);
  const rangeErrors = validateTimeRange(range.start, range.end, duration);
  const invalid = hasErrors(fftErrors) || hasErrors(rangeErrors);
  // Custom results describe the files they were computed for; keep them only
  // for those files so an added overlay is never mixed with a stale range.
  const customIds = Object.keys(segmentData).filter((id) => selected.includes(id));

  const traces = useMemo(() => {
    return selected.map((id, index) => {
      const file = files.find((candidate) => candidate.id === id);
      const fft = segmentData[id] ?? analyses[id]?.spectral.fft;
      if (!file || !fft) return null;
      return {
        x: fft.frequencies_hz,
        y: fft.average_dbfs,
        type: 'scatter',
        mode: 'lines',
        name: file.original_name,
        line: { color: COLORS.palette[index % COLORS.palette.length], width: 1.1 },
        hovertemplate: '%{x:.1f} Hz · %{y:.1f} dBFS<extra>' + file.original_name + '</extra>',
      };
    }).filter(Boolean);
  }, [selected, files, analyses, segmentData]);

  const peakTraces = useMemo(() => {
    if (!primaryFft?.peaks) return [];
    return [
      {
        x: primaryFft.peaks.map((peak: any) => peak.frequency_hz),
        y: primaryFft.peaks.map((peak: any) => peak.amplitude_dbfs),
        type: 'scatter',
        mode: 'markers+text',
        name: 'Dominant peaks',
        text: primaryFft.peaks.map((peak: any) => `${fmt(peak.frequency_hz, 0)} Hz`),
        textposition: 'top center',
        textfont: { size: 9, color: COLORS.accent },
        marker: { color: COLORS.accent, size: 5, symbol: 'diamond' },
        hovertemplate: '%{x:.2f} Hz · %{y:.2f} dBFS<extra>peak</extra>',
      },
    ];
  }, [primaryFft]);

  const layout = useMemo(
    () => ({
      height: 420,
      margin: { l: 54, r: 18, t: 24, b: 46 },
      xaxis: {
        title: { text: 'Frequency (Hz)' },
        type: logScale ? 'log' : 'linear',
        range: logScale ? [Math.log10(20), Math.log10(20000)] : [0, Math.min(20000, Number(primaryFft?.frequencies_hz?.at(-1) ?? 20000))],
      },
      yaxis: { title: { text: 'Amplitude (dBFS)' }, range: [-120, 6] },
      shapes: bandShapes(),
      hovermode: 'x unified',
      legend: { orientation: 'h', y: 1.08, x: 0 },
    }),
    [logScale, primaryFft],
  );

  const computeSegment = async () => {
    if (!session || !primary) return;
    if (invalid) return;
    const start = range.start === '' ? undefined : Number(range.start);
    const end = range.end === '' ? (start !== undefined ? duration : undefined) : Number(range.end);
    setComputing(true);
    try {
      const entries = await Promise.all(
        selected.map(async (id) => {
          const result = await api.getSpectrum(session.id, id, { start, end, n_fft: nFft, hop_length: hop });
          return [id, result] as const;
        }),
      );
      setSegmentData(Object.fromEntries(entries));
      notify('success', 'Spectrum recomputed', start !== undefined ? `Selected range ${fmt(start, 2)}–${fmt(end, 2)} s` : 'Full file');
    } catch (error) {
      notify('error', 'Spectrum computation failed', formatError(error));
    } finally {
      setComputing(false);
    }
  };

  if (!files.length) {
    return (
      <div className="section-stack">
        <SectionHeader title="Frequency spectrum" subtitle="FFT magnitude, dominant peaks and frequency-band context." />
        <NoAnalysedFiles icon={<AudioLines size={28} aria-hidden="true" />} description="Run analysis to compute the spectrum." />
      </div>
    );
  }

  return (
    <div className="section-stack">
      <SectionHeader
        title="Frequency spectrum"
        subtitle="Average FFT magnitude in dBFS, computed at the native sample rate. Select a time range to inspect a section."
        actions={
          <PlotDownloadButton fileId={primary?.id} fileName={primary?.original_name} kind="spectrum" plotName="spectrum" log={logScale} />
        }
      />

      <Card>
        <div className="toolbar-grid">
          <FileSelect files={files} selected={selected} onChange={setSelected} multiple label="Overlay files (the active file is always first)" max={4} />
          <div className="control-group">
            <label className="check-label"><input type="checkbox" checked={logScale} onChange={(event) => setLogScale(event.target.checked)} /> Logarithmic frequency axis</label>
            <div className="inline-inputs">
              <label>
                FFT size
                <select value={nFft} aria-invalid={!!fftErrors.nFft} aria-describedby="spec-fft-err" onChange={(event) => setNFft(Number(event.target.value))}>
                  {FFT_SIZES.map((size) => <option key={size} value={size}>{size}</option>)}
                </select>
                {fftErrors.nFft && <span id="spec-fft-err" className="error-text small">{fftErrors.nFft}</span>}
              </label>
              <label>
                Hop
                <select value={hop} aria-invalid={!!fftErrors.hop} aria-describedby="spec-hop-err" onChange={(event) => setHop(Number(event.target.value))}>
                  {HOP_SIZES.map((size) => <option key={size} value={size} disabled={size > nFft}>{size}{size > nFft ? ' (exceeds window)' : ''}</option>)}
                </select>
                {fftErrors.hop && <span id="spec-hop-err" className="error-text small">{fftErrors.hop}</span>}
              </label>
            </div>
            <div className="inline-inputs">
              <label>
                Start (s)
                <input type="number" min={0} max={duration} step={0.1} placeholder="0" value={range.start} aria-invalid={!!rangeErrors.start} aria-describedby="spec-start-err" onChange={(event) => setRange({ ...range, start: event.target.value })} />
                {rangeErrors.start && <span id="spec-start-err" className="error-text small">{rangeErrors.start}</span>}
              </label>
              <label>
                End (s)
                <input type="number" min={0} max={duration} step={0.1} placeholder={fmt(duration, 1)} value={range.end} aria-invalid={!!rangeErrors.end} aria-describedby="spec-end-err" onChange={(event) => setRange({ ...range, end: event.target.value })} />
                {rangeErrors.end && <span id="spec-end-err" className="error-text small">{rangeErrors.end}</span>}
              </label>
              <button className="btn btn-sm btn-primary" onClick={computeSegment} disabled={computing || invalid}>
                {computing ? <Loader2 size={14} className="spin" aria-hidden="true" /> : <RefreshCw size={14} aria-hidden="true" />} Compute
              </button>
              <button className="btn btn-sm" onClick={() => { setRange({ start: '', end: '' }); setSegmentData({}); }} disabled={!customIds.length && range.start === '' && range.end === ''}>
                <RotateCcw size={14} aria-hidden="true" /> Reset
              </button>
            </div>
          </div>
        </div>
        <InfoNote>
          A full-scale sine is calibrated to 0 dBFS at its peak bin. Frequency resolution is sample rate / FFT size; for{' '}
          {fmtHz(primary?.metadata?.sample_rate)} and {nFft} points, the bin width is{' '}
          {primary?.metadata?.sample_rate ? `${fmt(Number(primary.metadata.sample_rate) / nFft, 2)} Hz` : '—'}.
        </InfoNote>
        <AnalysisLoadState fileId={primary?.id} label="spectrum" />
        {primaryAnalysis && (
          <Plot
            title="Average frequency spectrum"
            summary={`Average FFT magnitude in dBFS on a ${logScale ? 'logarithmic' : 'linear'} frequency axis; dominant frequency ${fmt(primaryFft?.dominant_frequency_hz, 1)} Hz.`}
            data={[...traces, ...peakTraces]}
            layout={layout}
            height={420}
          />
        )}
        <div className="legend-note">
          <span><i className="swatch swatch-peaks" aria-hidden="true" /> Dominant peaks</span>
          <span>Band boundaries: 60, 250, 500, 2k, 4k, 6k Hz</span>
          {customIds.length > 0 && <Badge variant="accent">Custom computation ({customIds.length} file{customIds.length > 1 ? 's' : ''})</Badge>}
        </div>
      </Card>

      {primaryFft && (
        <div className="two-col">
          <Card title="Dominant frequency peaks" subtitle="Sub-bin interpolated frequency and main-lobe amplitude.">
            <TableWrap label="Dominant frequency peaks">
              <table className="data-table compact">
                <thead><tr><th scope="col">Frequency</th><th scope="col">Amplitude</th><th scope="col">Prominence</th><th scope="col">Harmonic</th></tr></thead>
                <tbody>
                  {primaryFft.peaks.map((peak: any) => (
                    <tr key={`${peak.frequency_hz}-${peak.amplitude_dbfs}`}>
                      <td className="mono">{fmt(peak.frequency_hz, 1)} Hz</td>
                      <td className="num">{fmt(peak.amplitude_dbfs, 2)} dBFS</td>
                      <td className="num">{fmt(peak.prominence_db, 1)} dB</td>
                      <td>{peak.harmonic_of_dominant ? `×${peak.harmonic_of_dominant}` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          </Card>
          <Card title="Measurement settings" subtitle="Direct measurement from the decoded source.">
            <div className="kv-grid">
              <span>FFT size</span><b>{primaryFft.n_fft}</b>
              <span>Window</span><b>{primaryFft.window}</b>
              <span>Bin width</span><b>{fmt(primaryFft.bin_width_hz, 2)} Hz</b>
              <span>Dominant frequency</span><b>{fmt(primaryFft.dominant_frequency_hz, 1)} Hz</b>
              <span>Method</span><b>{primaryFft.method}</b>
            </div>
            <p className="muted small">
              Spectral peaks can be harmonics, resonances, or noise. Harmonic labels are relative to the strongest peak and are
              descriptive, not a musical analysis.
            </p>
          </Card>
        </div>
      )}

      {primaryAnalysis && (
        <Card title="Band context" subtitle="Share of energy in the standard production bands.">
          <div className="band-bar-list">
            {primaryAnalysis.spectral.bands.bands.map((band) => (
              <div className="band-bar-row" key={band.key}>
                <span>{band.label}</span>
                <div className="band-bar-track"><div className="band-bar-fill" style={{ width: `${Math.min(100, band.relative_energy_pct ?? 0)}%`, background: rgba(COLORS.accent2, 0.65) }} /></div>
                <b>{fmt(band.relative_energy_pct, 2)}%</b>
                <span className="muted small">{fmt(band.average_db)} dB</span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
