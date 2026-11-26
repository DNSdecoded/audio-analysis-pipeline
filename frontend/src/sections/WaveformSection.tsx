import { useEffect, useMemo, useRef, useState } from 'react';
import {
  AudioWaveform,
  Loader2,
  Maximize2,
  Play,
  ScanSearch,
  Scissors,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import { useApp } from '../state/AppContext';
import { useFileSelection } from '../state/useFileSelection';
import { useWorkspace } from '../state/Workspace';
import { api, formatError } from '../lib/api';
import { Badge, Card, InfoNote, SectionHeader, Stat } from '../components/UI';
import { AnalysisLoadState, NoAnalysedFiles } from '../components/AnalysisState';
import { PlotDownloadButton } from '../components/PlotDownloadButton';
import { FileSelect } from '../components/FileSelect';
import Plot from '../components/Plot';
import { COLORS, beatShapes, regionShapes, rgba } from '../lib/plotTheme';
import { fmt, fmtDuration } from '../lib/format';
import { clampSelection, validateTimeRange } from '../lib/inputValidation';
import type { Analysis, WaveformResponse } from '../types';

export default function WaveformSection() {
  const { session, analyses, notify } = useApp();
  const { files, selected, setSelected } = useFileSelection({ multiple: true, defaultCount: 1 });
  const [selection, setSelection] = useState<{ start: number; end: number } | null>(null);
  const [zoomRange, setZoomRange] = useState<[number, number] | null>(null);
  const [detail, setDetail] = useState<WaveformResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [segmentResult, setSegmentResult] = useState<Analysis | null>(null);
  const [segmentLoading, setSegmentLoading] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const primary = files.find((file) => file.id === selected[0]);
  const analysis = primary ? analyses[primary.id] : undefined;
  const stopListenerRef = useRef<(() => void) | null>(null);

  // Detail and segment results belong to one file; clear them when the
  // primary file changes so they are never shown under another file's name.
  useEffect(() => {
    setDetail(null);
    setSegmentResult(null);
    setSelection(null);
    setZoomRange(null);
  }, [primary?.id]);

  // A QC finding (or a deep link) asked to show a specific time range.
  // Declared after the reset effect so it wins when both run in one commit.
  const { focus, clearFocus } = useWorkspace();
  const [focusLabel, setFocusLabel] = useState<string | null>(null);
  useEffect(() => {
    if (!focus || !primary || focus.fileId !== primary.id) return;
    const pad = Math.max(0.25, (focus.end - focus.start) * 0.5);
    setSelection({ start: focus.start, end: focus.end });
    setZoomRange([Math.max(0, focus.start - pad), focus.end + pad]);
    setFocusLabel(focus.label ?? `${fmt(focus.start, 2)}–${fmt(focus.end, 2)} s`);
    clearFocus();
  }, [focus, primary?.id, clearFocus]);
  const duration = Number(primary?.metadata?.duration ?? analysis?.time_domain?.duration_seconds ?? 0);

  // The start/end fields keep what the user typed; only a valid range becomes
  // the selection, so "Analyze selection" can never send a range outside the
  // file (previously start = 999 s on a 10 s file was accepted).
  const [draft, setDraft] = useState({ start: '', end: '' });
  const typedSelection = useRef(false);
  useEffect(() => {
    // Selection changed by zoom, a QC jump or "Full file": show it.  A change
    // the user is typing is left as typed (no reformatting mid-entry).
    if (typedSelection.current) {
      typedSelection.current = false;
      return;
    }
    // Millisecond precision: QC regions can be shorter than 10 ms.
    const ms = (value: number) => String(Math.round(value * 1000) / 1000);
    setDraft(selection ? { start: ms(selection.start), end: ms(selection.end) } : { start: '', end: '' });
  }, [selection]);
  const draftErrors = draft.start === '' && draft.end === '' ? {} : validateTimeRange(draft.start, draft.end === '' ? String(duration) : draft.end, duration);
  const commitDraft = (next: { start: string; end: string }) => {
    setDraft(next);
    if (next.start === '' && next.end === '') {
      typedSelection.current = selection !== null;
      setSelection(null);
      return;
    }
    const startText = next.start === '' ? '0' : next.start;
    const endText = next.end === '' ? String(duration) : next.end;
    const errors = validateTimeRange(startText, endText, duration);
    if (errors.start || errors.end) return;
    const clamped = clampSelection(Number(startText), Number(endText), duration);
    if (clamped && (clamped.start !== selection?.start || clamped.end !== selection?.end)) {
      typedSelection.current = true;
      setSelection(clamped);
    }
  };

  const zoomBy = (factor: number) => {
    if (!(duration > 0)) return;
    const [lo, hi] = zoomRange ?? [0, duration];
    const centre = (lo + hi) / 2;
    const span = Math.min(duration, Math.max(0.05, (hi - lo) * factor));
    let start = Math.max(0, centre - span / 2);
    const end = Math.min(duration, start + span);
    start = Math.max(0, end - span);
    if (start <= 0 && end >= duration) setZoomRange(null);
    else setZoomRange([start, end]);
  };

  const plot = useMemo(() => {
    const traces: any[] = [];
    selected.forEach((id, index) => {
      const item = analyses[id];
      const file = files.find((candidate) => candidate.id === id);
      if (!item || !file) return;
      const wf = item.time_domain.waveform;
      const color = COLORS.palette[index % COLORS.palette.length];
      const isPrimary = index === 0;
      const x = [...wf.times, ...wf.times.slice().reverse()];
      const y = [...wf.mono_max, ...wf.mono_min.slice().reverse()];
      traces.push({
        x,
        y,
        type: 'scatter',
        mode: 'lines',
        name: `${file.original_name} peak`,
        fill: 'toself',
        fillcolor: rgba(color, isPrimary ? 0.28 : 0.12),
        line: { color, width: isPrimary ? 1.1 : 0.7 },
        hoverinfo: 'skip',
        showlegend: isPrimary,
      });
      const env = item.time_domain.envelopes;
      traces.push({
        x: env.times,
        y: env.rms_db.map((value) => Math.pow(10, value / 20)),
        type: 'scatter',
        mode: 'lines',
        name: `${file.original_name} RMS`,
        line: { color, width: 1.1, dash: 'dot' },
        hovertemplate: '%{x:.2f}s · RMS %{customdata:.1f} dBFS<extra>' + file.original_name + '</extra>',
        customdata: env.rms_db,
      });
      traces.push({
        x: env.times,
        y: env.rms_db.map((value) => -Math.pow(10, value / 20)),
        type: 'scatter',
        mode: 'lines',
        line: { color, width: 1.1, dash: 'dot' },
        showlegend: false,
        hoverinfo: 'skip',
      });
    });
    return traces;
  }, [selected, analyses, files]);

  const shapes = useMemo(() => {
    if (!analysis) return [];
    const result: any[] = [
      ...regionShapes(analysis.time_domain.clipping.regions, rgba(COLORS.error, 0.16)),
      ...regionShapes(analysis.time_domain.silence.regions, rgba(COLORS.reference, 0.12)),
      ...beatShapes(analysis.musical.tempo.beats ?? []),
    ];
    if (selection) {
      result.push({
        type: 'rect',
        x0: selection.start,
        x1: selection.end,
        y0: 0,
        y1: 1,
        yref: 'paper',
        fillcolor: rgba(COLORS.accent, 0.12),
        line: { color: COLORS.accent, width: 1, dash: 'dot' },
        layer: 'above',
      });
    }
    return result;
  }, [analysis, selection]);

  const layout = useMemo(
    () => ({
      height: 380,
      margin: { l: 48, r: 16, t: 18, b: 40 },
      xaxis: {
        title: { text: 'Time (s)' },
        rangeslider: { visible: true, thickness: 0.08, bgcolor: rgba(COLORS.reference, 0.08), bordercolor: COLORS.border },
        range: zoomRange ?? undefined,
        autorange: zoomRange ? false : true,
      },
      yaxis: { title: { text: 'Amplitude (linear)' }, range: [-1.02, 1.02], zeroline: true },
      shapes,
      showlegend: true,
      uirevision: 'waveform-section',
    }),
    [shapes, zoomRange],
  );

  const detailPlot = useMemo(() => {
    if (!detail) return null;
    const traces: any[] = [];
    const x = [...detail.times, ...detail.times.slice().reverse()];
    const y = [...detail.mono_max, ...detail.mono_min.slice().reverse()];
    traces.push({
      x,
      y,
      type: 'scatter',
      mode: 'lines',
      name: 'Peak envelope',
      fill: 'toself',
      fillcolor: rgba(COLORS.accent2, 0.28),
      line: { color: COLORS.accent2, width: 0.9 },
    });
    traces.push({
      x: detail.times,
      y: detail.mono_rms_db.map((value) => Math.pow(10, value / 20)),
      type: 'scatter',
      mode: 'lines',
      name: 'RMS envelope',
      line: { color: COLORS.accent, width: 1 },
    });
    traces.push({
      x: detail.times,
      y: detail.mono_rms_db.map((value) => -Math.pow(10, value / 20)),
      type: 'scatter',
      mode: 'lines',
      showlegend: false,
      line: { color: COLORS.accent, width: 1 },
    });
    return { traces, layout: { ...layout, height: 260, xaxis: { ...layout.xaxis, rangeslider: { visible: false }, range: [detail.selection?.start, detail.selection?.end] }, shapes: [] } };
  }, [detail, layout]);

  const loadDetail = async () => {
    if (!session || !primary || !selection) return;
    setDetailLoading(true);
    try {
      const response = await api.getWaveform(session.id, primary.id, {
        start: selection.start,
        end: selection.end,
        buckets: 4000,
      });
      setDetail(response);
      notify('success', 'Detail waveform loaded', `${fmt(selection.start, 2)}–${fmt(selection.end, 2)} s`);
    } catch (error) {
      notify('error', 'Could not load waveform detail', formatError(error));
    } finally {
      setDetailLoading(false);
    }
  };

  const analyzeSelection = async () => {
    if (!session || !primary || !selection) return;
    setSegmentLoading(true);
    try {
      const result = await api.segmentAnalysis(session.id, primary.id, {
        start: selection.start,
        end: selection.end,
        target_lufs: session.settings.target_lufs,
        true_peak_limit: session.settings.true_peak_limit,
      });
      setSegmentResult(result);
      notify('success', 'Selection analysed', 'All values below come from the selected time range only.');
    } catch (error) {
      notify('error', 'Segment analysis failed', formatError(error));
    } finally {
      setSegmentLoading(false);
    }
  };

  const onRelayout = (event: any) => {
    const start = event['xaxis.range[0]'];
    const end = event['xaxis.range[1]'];
    if (typeof start === 'number' && typeof end === 'number' && end > start) {
      setZoomRange([start, end]);
      setSelection({ start: Math.max(0, start), end: Math.min(duration, end) });
    }
    if (event['xaxis.autorange']) {
      setZoomRange(null);
    }
  };

  const playSelection = () => {
    const audio = audioRef.current;
    if (!audio || !selection) return;
    // Remove the stop handler of any previous selection playback first;
    // otherwise handlers accumulate and pause later, unrelated playback.
    stopListenerRef.current?.();
    const stopAt = selection.end;
    const handler = () => {
      if (audio.currentTime >= stopAt) {
        audio.pause();
        cleanup();
      }
    };
    const cleanup = () => {
      audio.removeEventListener('timeupdate', handler);
      audio.removeEventListener('pause', cleanup);
      stopListenerRef.current = null;
    };
    audio.addEventListener('timeupdate', handler);
    audio.addEventListener('pause', cleanup);
    stopListenerRef.current = cleanup;
    audio.currentTime = selection.start;
    audio.play().catch((error) => {
      cleanup();
      notify('error', 'Playback failed', formatError(error));
    });
  };

  if (!files.length) {
    return (
      <div className="section-stack">
        <SectionHeader title="Waveform analysis" subtitle="Amplitude, RMS, clipping, silence and transients." />
        <NoAnalysedFiles icon={<AudioWaveform size={28} aria-hidden="true" />} description="Upload audio and run analysis to inspect waveforms." />
      </div>
    );
  }

  return (
    <div className="section-stack">
      <SectionHeader
        title="Waveform analysis"
        subtitle="Peak envelope, RMS, clipping, silence and detected beats. Drag on the plot to select a time range."
        actions={
          <>
            <button className="btn btn-sm" onClick={loadDetail} disabled={!selection || detailLoading} aria-describedby="selection-hint">
              {detailLoading ? <Loader2 size={14} className="spin" aria-hidden="true" /> : <ScanSearch size={14} aria-hidden="true" />} Load detail
            </button>
            <button className="btn btn-sm" onClick={analyzeSelection} disabled={!selection || segmentLoading} aria-describedby="selection-hint">
              {segmentLoading ? <Loader2 size={14} className="spin" aria-hidden="true" /> : <Scissors size={14} aria-hidden="true" />} Analyze selection
            </button>
            <PlotDownloadButton
              fileId={primary?.id}
              fileName={primary?.original_name}
              kind="waveform"
              plotName={zoomRange ? 'waveform (visible range)' : 'waveform'}
              start={zoomRange ? Math.max(0, zoomRange[0]) : undefined}
              end={zoomRange ? Math.min(duration, zoomRange[1]) : undefined}
            />
          </>
        }
      />

      {focusLabel && selection && (
        <InfoNote tone="warning">
          Showing <strong>{focusLabel}</strong> at {fmt(selection.start, 2)}–{fmt(selection.end, 2)} s (highlighted). Use
          “Reset zoom” to return to the full file.
        </InfoNote>
      )}

      <Card>
        <FileSelect files={files} selected={selected} onChange={setSelected} multiple label="Overlay files (the active file is always first)" max={4} />
        {selected.length > 1 && (
          <InfoNote tone="info">
            Overlaid files share a time axis starting at 0. Use Comparison → alignment before comparing offset recordings.
          </InfoNote>
        )}
        <div className="waveform-toolbar">
          <div className="selection-inputs">
            <label>
              Selection start (s)
              <input
                type="number"
                step="0.01"
                min={0}
                max={duration}
                value={draft.start}
                placeholder="0.00"
                aria-invalid={!!draftErrors.start}
                aria-describedby="sel-start-err"
                onChange={(event) => commitDraft({ ...draft, start: event.target.value })}
              />
              {draftErrors.start && <span id="sel-start-err" className="error-text small">{draftErrors.start}</span>}
            </label>
            <label>
              Selection end (s)
              <input
                type="number"
                step="0.01"
                min={0}
                max={duration}
                value={draft.end}
                placeholder={fmt(duration, 2)}
                aria-invalid={!!draftErrors.end}
                aria-describedby="sel-end-err"
                onChange={(event) => commitDraft({ ...draft, end: event.target.value })}
              />
              {draftErrors.end && <span id="sel-end-err" className="error-text small">{draftErrors.end}</span>}
            </label>
            <button className="btn btn-sm" onClick={() => setSelection({ start: 0, end: duration })} disabled={!(duration > 0)}>
              Full file
            </button>
            <div className="btn-group" role="group" aria-label="Waveform zoom">
              <button className="btn btn-sm" onClick={() => zoomBy(0.5)} aria-label="Zoom in on time axis" title="Zoom in (halve the visible range)" disabled={!(duration > 0)}>
                <ZoomIn size={14} aria-hidden="true" />
              </button>
              <button className="btn btn-sm" onClick={() => zoomBy(2)} aria-label="Zoom out on time axis" title="Zoom out (double the visible range)" disabled={!zoomRange}>
                <ZoomOut size={14} aria-hidden="true" />
              </button>
              <button className="btn btn-sm" onClick={() => setZoomRange(null)} disabled={!zoomRange} title="Show the full file">
                <Maximize2 size={14} aria-hidden="true" /> Reset zoom
              </button>
            </div>
          </div>
          <div className="muted small">
            Visible range: {zoomRange ? `${fmt(zoomRange[0], 2)}–${fmt(zoomRange[1], 2)} s` : 'full file'} · playhead {fmt(currentTime, 2)} s
          </div>
          <p id="selection-hint" className="muted small">
            {selection
              ? `Selection ${fmt(selection.start, 2)}–${fmt(selection.end, 2)} s: load a full-resolution detail view or analyse just this range.`
              : 'Zoom the plot (drag across it) or enter start/end times to select a range; “Load detail” and “Analyze selection” then become available.'}
          </p>
        </div>
        {primary && (
          <div className="audio-row">
            <audio
              ref={audioRef}
              className="audio-player"
              controls
              preload="metadata"
              src={api.audioUrl(session!.id, primary.id)}
              onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
            />
            <button className="btn btn-sm" onClick={playSelection} disabled={!selection} aria-describedby="selection-hint">
              <Play size={14} aria-hidden="true" /> Play selection
            </button>
          </div>
        )}
        <AnalysisLoadState fileId={primary?.id} label="waveform" />
        {analysis && (
          <Plot
            title={`Waveform of ${primary?.original_name ?? 'the active file'}`}
            summary={`Peak and RMS envelope over ${fmt(duration, 2)} s; ${analysis.time_domain.clipping.regions.length} clipping and ${analysis.time_domain.silence.regions.length} silence regions marked.`}
            data={plot}
            layout={layout}
            height={380}
            onRelayout={onRelayout}
          />
        )}
        <div className="legend-note">
          <span><i className="swatch swatch-critical" aria-hidden="true" /> Clipping regions</span>
          <span><i className="swatch swatch-silence" aria-hidden="true" /> Silence</span>
          <span><i className="swatch swatch-beats" aria-hidden="true" /> Detected beats</span>
          <span><i className="swatch swatch-selection" aria-hidden="true" /> Time selection</span>
        </div>
      </Card>

      {analysis && (
        <div className="stat-grid">
          <Stat label="Sample peak" value={fmt(analysis.time_domain.sample_peak.dbfs)} unit="dBFS" tone="accent" />
          <Stat label="True peak" value={fmt(analysis.time_domain.true_peak_dbtp)} unit="dBTP" />
          <Stat label="RMS" value={fmt(analysis.time_domain.rms.dbfs)} unit="dBFS" />
          <Stat label="Crest factor" value={fmt(analysis.loudness.crest_factor_db)} unit="dB" />
          <Stat label="Clipped samples" value={analysis.time_domain.clipping.clipped_samples.toLocaleString()} hint={`${fmt(analysis.time_domain.clipping.clipped_percent, 4)}%`} tone={analysis.time_domain.clipping.clipped_samples ? 'warning' : 'success'} />
          <Stat label="Silence" value={fmt(analysis.time_domain.silence.percent, 2)} unit="%" hint={fmtDuration(analysis.time_domain.silence.duration_seconds)} />
        </div>
      )}

      {detailPlot && (
        <Card
          title="Detailed waveform selection"
          subtitle={`${fmt(detail?.selection?.start, 2)}–${fmt(detail?.selection?.end, 2)} s · ${detail?.bucket_count} buckets decoded from the original file`}
        >
          <Plot title="Detailed waveform selection" data={detailPlot.traces} layout={detailPlot.layout} height={260} />
        </Card>
      )}

      {segmentResult && (
        <Card
          title="Selected time range analysis"
          subtitle={`${fmt(segmentResult.segment?.start, 2)}–${fmt(segmentResult.segment?.end, 2)} s · computed independently from the original file`}
          actions={<Badge variant="accent">Segment</Badge>}
        >
          <div className="stat-grid">
            <Stat label="Integrated loudness" value={fmt(segmentResult.loudness.integrated_lufs)} unit="LUFS" />
            <Stat label="True peak" value={fmt(segmentResult.loudness.true_peak_dbtp)} unit="dBTP" />
            <Stat label="RMS" value={fmt(segmentResult.time_domain.rms.dbfs)} unit="dBFS" />
            <Stat label="Crest factor" value={fmt(segmentResult.loudness.crest_factor_db)} unit="dB" />
            <Stat label="Spectral centroid" value={fmt(segmentResult.spectral.spectral_features.centroid_hz?.mean, 0)} unit="Hz" />
            <Stat label="Estimated key" value={segmentResult.musical.key.key ?? '—'} />
          </div>
          <InfoNote>
            Segment measurements can differ from the full-file values because loudness gating, LRA and estimates use only the
            selected range. This does not modify the original file.
          </InfoNote>
        </Card>
      )}

      {analysis && (
        <div className="two-col">
          <Card title="Signal integrity regions" subtitle="Measured on the decoded copy; positions refer to the original timeline.">
            <div className="region-summary">
              <div><strong>{analysis.time_domain.clipping.regions.length}</strong><span>clipping regions</span></div>
              <div><strong>{analysis.time_domain.silence.regions.length}</strong><span>silence regions</span></div>
              <div><strong>{analysis.time_domain.dropouts.count}</strong><span>possible dropouts</span></div>
              <div><strong>{analysis.time_domain.noise.confidence}</strong><span>noise confidence</span></div>
            </div>
            {analysis.time_domain.noise.noise_floor_dbfs === null && (
              <p className="muted small">{analysis.time_domain.noise.method}</p>
            )}
          </Card>
          <Card title="Envelope statistics" subtitle="50 ms frames, 25 ms hop.">
            <div className="kv-grid">
              <span>RMS variation</span><b>{fmt(analysis.time_domain.signal_variation.rms_std_db)} dB</b>
              <span>RMS range (p5–p95)</span><b>{fmt(analysis.time_domain.signal_variation.rms_range_db)} dB</b>
              <span>Frame RMS p5</span><b>{fmt(analysis.time_domain.signal_variation.rms_p5_dbfs)} dBFS</b>
              <span>Frame RMS p95</span><b>{fmt(analysis.time_domain.signal_variation.rms_p95_dbfs)} dBFS</b>
              <span>DC offset</span><b>{fmt(analysis.time_domain.dc_offset.max_abs, 6)}</b>
              <span>Noise floor</span><b>{analysis.time_domain.noise.noise_floor_dbfs === null ? 'not separable' : `${fmt(analysis.time_domain.noise.noise_floor_dbfs)} dBFS`}</b>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
