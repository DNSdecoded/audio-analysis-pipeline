import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { shouldApplyAlignment } from '../lib/analysisLogic';
import {
  ArrowDown,
  ArrowLeftRight,
  ArrowUp,
  Download,
  Crosshair,
  ExternalLink,
  GitCompareArrows,
  Loader2,
  Search,
} from 'lucide-react';
import { useApp } from '../state/AppContext';
import { useWorkspace } from '../state/Workspace';
import { describeFindingMeasurement, filterRows, sortBy, sortRows, type RowSort, type SortDir } from '../lib/comparisonView';
import { api, formatError } from '../lib/api';
import { Badge, Card, EmptyState, InfoNote, SectionHeader, SeverityBadge, Spinner, TableWrap, ToggleGroup } from '../components/UI';
import { hasErrors, parseNumberInput, validateTimeRange } from '../lib/inputValidation';
import { FileSelect } from '../components/FileSelect';
import Plot from '../components/Plot';
import { COLORS } from '../lib/plotTheme';
import { fmt, fmtSigned, fmtUnit } from '../lib/format';
import type { AlignmentResult, Analysis, Comparison, FileRecord } from '../types';

const PARAMETER_GROUPS: { group: string; keys: string[] }[] = [
  { group: 'File', keys: ['format', 'codec', 'duration', 'sample_rate', 'bit_depth', 'bitrate', 'channels', 'file_size', 'is_lossy'] },
  { group: 'Loudness', keys: ['integrated_lufs', 'loudness_range', 'true_peak', 'sample_peak', 'rms'] },
  { group: 'Dynamics', keys: ['crest_factor', 'plr'] },
  { group: 'Signal quality', keys: ['dc_offset', 'clipping', 'silence', 'snr', 'noise_floor'] },
  { group: 'Stereo', keys: ['correlation', 'stereo_width', 'channel_balance', 'mono_loss'] },
  { group: 'Musical', keys: ['key', 'tempo', 'tempo_stability', 'pitch_median'] },
  { group: 'Spectral', keys: ['spectral_centroid', 'spectral_bandwidth', 'spectral_rolloff', 'spectral_flatness', 'zcr', 'hnr'] },
  { group: 'Frequency bands', keys: ['band_sub_bass', 'band_bass', 'band_low_midrange', 'band_midrange', 'band_upper_midrange', 'band_presence', 'band_brilliance'] },
];

const STATUS_LABEL: Record<string, string> = {
  match: 'Match',
  different: 'Different',
  large_deviation: 'Large deviation',
  low_confidence: 'Low confidence',
  unsupported: 'Unsupported',
};

/** Last result per session + configuration, so revisiting the page does not re-run it. */
const comparisonCache = new Map<string, Comparison>();

const STATUSES = ['large_deviation', 'different', 'low_confidence', 'unsupported', 'match'];

type SummaryKey = 'name' | 'key' | 'bpm' | 'sr' | 'lufs' | 'tp' | 'dr' | 'lra' | 'width' | 'gain' | 'qc';

export default function ComparisonSection() {
  const { session, analyses, ensureAnalysis, notify } = useApp();
  const { navigate } = useWorkspace();
  const [statusFilter, setStatusFilter] = useState<string[]>(STATUSES);
  const [rowQuery, setRowQuery] = useState('');
  const [rowSort, setRowSort] = useState<RowSort>('group');
  const [summarySort, setSummarySort] = useState<{ key: SummaryKey; dir: SortDir }>({ key: 'name', dir: 'asc' });
  const files = (session?.files ?? []).filter((file) => file.has_analysis);
  const [selected, setSelected] = useState<string[]>(files.slice(0, 2).map((file) => file.id));
  const [groups, setGroups] = useState<string[]>(PARAMETER_GROUPS.map((group) => group.group));
  const [reference, setReference] = useState<string>('');
  const [mode, setMode] = useState<'full' | 'segment'>('full');
  const [ranges, setRanges] = useState<Record<string, { start: string; end: string }>>({});
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [loading, setLoading] = useState(false);
  const [alignA, setAlignA] = useState<string>('');
  const [alignB, setAlignB] = useState<string>('');
  const [alignment, setAlignment] = useState<AlignmentResult | null>(null);
  const [alignLoading, setAlignLoading] = useState(false);
  const [offsets, setOffsets] = useState<Record<string, number>>({});
  const [manualOffset, setManualOffset] = useState('0');
  const [csvBusy, setCsvBusy] = useState(false);
  const autoRan = useRef(false);

  useEffect(() => {
    if (files.length < 2) return;
    const remaining = selected.filter((id) => files.some((file) => file.id === id));
    if (remaining.length === selected.length && selected.length >= 2) return;
    // A selected file was removed or replaced: drop only that file and keep the
    // user's other choices (top up to two files if needed).  The previous
    // comparison and alignment refer to data that no longer exists.
    const topUp = files.map((file) => file.id).filter((id) => !remaining.includes(id));
    setSelected([...remaining, ...topUp].slice(0, Math.max(2, remaining.length)));
    setComparison(null);
    setAlignment(null);
    setOffsets((current) => Object.fromEntries(Object.entries(current).filter(([id]) => remaining.includes(id))));
    autoRan.current = false;
  }, [files, selected]);

  useEffect(() => {
    if (reference && !selected.includes(reference)) setReference('');
    if (alignA && !selected.includes(alignA)) setAlignA('');
    if (alignB && !selected.includes(alignB)) setAlignB('');
  }, [selected, reference, alignA, alignB]);

  useEffect(() => {
    selected.forEach((id) => {
      if (!analyses[id]) void ensureAnalysis(id);
    });
  }, [selected, analyses, ensureAnalysis]);

  useEffect(() => {
    if (!alignA && selected[0]) setAlignA(selected[0]);
    if (!alignB && selected[1]) setAlignB(selected[1]);
  }, [selected, alignA, alignB]);

  const cacheKey = `${session?.id}|${selected.join(',')}|${mode}|${reference}|${groups.join(',')}|${mode === 'segment' ? JSON.stringify(ranges) : ''}`;

  useEffect(() => {
    if (comparison || selected.length < 2 || !selected.every((id) => analyses[id]) || autoRan.current) return;
    autoRan.current = true;
    const cached = comparisonCache.get(cacheKey);
    if (cached) setComparison(cached);
    else void runComparison(true);
  }, [selected, analyses, comparison, cacheKey]);

  const selectedFiles = selected
    .map((id) => files.find((file) => file.id === id))
    .filter((file): file is FileRecord => Boolean(file));
  const selectedAnalyses = useMemo(
    () => selected.map((id) => analyses[id]).filter((analysis): analysis is Analysis => Boolean(analysis)),
    [selected, analyses],
  );
  const allKeys = PARAMETER_GROUPS.filter((group) => groups.includes(group.group)).flatMap((group) => group.keys);
  const rangeErrors: Record<string, { start?: string; end?: string }> = Object.fromEntries(
    selectedFiles.map((file) => {
      const current = ranges[file.id] ?? { start: '0', end: String(file.metadata?.duration ?? '') };
      return [file.id, validateTimeRange(current.start, current.end, Number(file.metadata?.duration ?? 0))];
    }),
  );
  const segmentInvalid = mode === 'segment' && Object.values(rangeErrors).some(hasErrors);
  const configInvalid = segmentInvalid || !groups.length;

  const runComparison = async (quiet = false) => {
    if (!session || selected.length < 2 || configInvalid) return;
    if (!selected.every((id) => analyses[id])) {
      notify('warning', 'Analysis not ready', 'Wait for all selected files to finish analysis.');
      return;
    }
    setLoading(true);
    try {
      const segmentRanges = Object.fromEntries(
        selected.map((id) => {
          const file = files.find((candidate) => candidate.id === id);
          const duration = Number(file?.metadata?.duration ?? 0);
          const current = ranges[id];
          return [id, {
            start: current?.start === '' || current?.start === undefined ? 0 : Number(current.start),
            end: current?.end === '' || current?.end === undefined ? duration : Number(current.end),
          }];
        }),
      );
      const result = await api.compare(session.id, {
        file_ids: selected,
        parameters: allKeys.length ? allKeys : undefined,
        target_lufs: session.settings.target_lufs,
        true_peak_limit: session.settings.true_peak_limit,
        reference_file_id: reference || undefined,
        mode,
        ranges: mode === 'segment' ? segmentRanges : undefined,
      });
      setComparison(result);
      comparisonCache.set(cacheKey, result);
      if (!quiet) notify('success', 'Comparison complete', `${result.rows.length} parameters compared across ${selected.length} files.`);
    } catch (error) {
      notify('error', 'Comparison failed', formatError(error));
    } finally {
      setLoading(false);
    }
  };

  const runAlignment = async (manual?: number) => {
    if (!session || !alignA || !alignB || alignA === alignB) {
      notify('warning', 'Choose two different files', 'Alignment needs a source and a target.');
      return;
    }
    setAlignLoading(true);
    try {
      const result = await api.align(session.id, {
        file_a: alignA,
        file_b: alignB,
        method: 'auto',
        manual_offset_seconds: manual,
        max_offset_seconds: 15,
      });
      setAlignment(result);
      const usable = result.offset_seconds !== null && result.offset_seconds !== undefined;
      // A weak correlation is not a reliable alignment: show it, but do not
      // silently shift the overlay plots by it.
      if (shouldApplyAlignment(result)) {
        setOffsets((current) => ({ ...current, [alignB]: Number(result.offset_seconds) }));
        notify('success', 'Alignment computed', `${fmt(result.offset_seconds, 3)} s offset · ${result.confidence_label} confidence`);
      } else if (usable) {
        setOffsets((current) => {
          const next = { ...current };
          delete next[alignB];
          return next;
        });
        notify('warning', 'Alignment not applied', `Correlation is weak (${fmt(result.confidence, 2)}); the ${fmt(result.offset_seconds, 3)} s estimate is unreliable and was not applied to the plots.`);
      } else {
        notify('warning', 'Alignment unavailable', String((result as any).reason ?? 'No offset could be estimated.'));
      }
    } catch (error) {
      notify('error', 'Alignment failed', formatError(error));
    } finally {
      setAlignLoading(false);
    }
  };

  const exportCsv = async () => {
    if (!session || csvBusy) return;
    setCsvBusy(true);
    try {
      // Same files and parameter groups as the table on screen.
      const filename = await api.downloadReport(session.id, {
        format: 'comparison-csv',
        file_ids: selected,
        include_comparison: true,
        parameters: allKeys.length ? allKeys : undefined,
        target_lufs: session.settings.target_lufs,
        true_peak_limit: session.settings.true_peak_limit,
        reference_file_id: reference || undefined,
      });
      notify('success', 'Comparison exported', filename);
    } catch (error) {
      notify('error', 'Export failed', formatError(error));
    } finally {
      setCsvBusy(false);
    }
  };

  const manualValue = parseNumberInput(manualOffset);
  const manualError = !Number.isFinite(manualValue) || manualValue < -600 || manualValue > 600 ? 'Enter an offset from −600 to 600 s.' : undefined;
  const checkManualOffset = () => {
    if (manualError) return;
    setOffsets((current) => ({ ...current, [alignB]: manualValue }));
    void runAlignment(manualValue);
  };

  const fileNames = useMemo(
    () => Object.fromEntries((session?.files ?? []).map((file) => [file.id, file.original_name])),
    [session?.files],
  );

  const visibleRows = useMemo(
    () => (comparison ? sortRows(filterRows(comparison.rows, statusFilter, rowQuery), rowSort) : []),
    [comparison, statusFilter, rowQuery, rowSort],
  );

  const summaryRows = useMemo(() => {
    const rows = selectedAnalyses.map((analysis) => {
      const a: any = analysis;
      const gain = comparison?.gain_preview?.find((row: any) => row.file_id === analysis.file_id);
      return {
        id: analysis.file_id,
        name: analysis.original_name,
        key: a.musical?.key?.key ?? null,
        keyConf: a.musical?.key?.key ? a.musical?.key?.confidence_label ?? null : null,
        bpm: a.musical?.tempo?.bpm ?? null,
        bpmConf: a.musical?.tempo?.bpm ? a.musical?.tempo?.confidence_label ?? null : null,
        sr: a.metadata?.sample_rate ?? null,
        lufs: a.loudness?.integrated_lufs ?? null,
        tp: a.loudness?.true_peak_dbtp ?? null,
        dr: a.dynamics?.dynamic_range_db ?? null,
        plr: a.loudness?.peak_to_loudness_ratio_db ?? null,
        lra: a.loudness?.loudness_range_lu ?? null,
        width: a.stereo?.supported ? a.stereo?.mid_side?.stereo_width_percent ?? null : null,
        gain: gain?.recommended_gain_db ?? null,
        qc: a.qc?.overall ?? null,
      };
    });
    const qcRank: Record<string, number> = { error: 0, warning: 1, information: 2, normal: 3 };
    return sortBy(rows, (row) => (summarySort.key === 'qc' ? qcRank[row.qc ?? ''] : (row as any)[summarySort.key]), summarySort.dir);
  }, [selectedAnalyses, comparison, summarySort]);

  const bandData = useMemo(() => {
    const withBands = selectedAnalyses.filter((analysis) => analysis.spectral?.bands?.bands?.length);
    if (!withBands.length) return [];
    const labels = withBands[0].spectral.bands.bands.map((band: any) => band.label);
    return withBands.map((analysis, index) => ({
      x: labels,
      y: labels.map((_: string, bandIndex: number) => analysis.spectral.bands.bands[bandIndex]?.relative_energy_pct ?? 0),
      type: 'bar',
      name: analysis.original_name,
      marker: { color: COLORS.palette[index % COLORS.palette.length] },
      hovertemplate: '%{x}: %{y:.1f}%<extra>' + analysis.original_name + '</extra>',
    }));
  }, [selectedAnalyses]);

  const spectrumData = useMemo(() => {
    return selectedAnalyses
      .filter((analysis) => analysis.spectral?.fft?.frequencies_hz?.length)
      .map((analysis, index) => ({
        x: analysis.spectral.fft.frequencies_hz,
        y: analysis.spectral.fft.average_dbfs,
        type: 'scatter',
        mode: 'lines',
        name: analysis.original_name,
        line: { color: COLORS.palette[index % COLORS.palette.length], width: 0.9 },
      }));
  }, [selectedAnalyses]);

  const loudnessData = useMemo(() => {
    return selectedAnalyses
      .filter((analysis) => analysis.loudness?.short_term?.times?.length)
      .map((analysis, index) => {
        const offset = Number(offsets[analysis.file_id] ?? 0);
        return {
          x: analysis.loudness.short_term.times.map((time: number) => time - offset),
          y: analysis.loudness.short_term.lufs,
          type: 'scatter',
          mode: 'lines',
          name: `${analysis.original_name}${offset ? ` (shift ${fmtSigned(-offset, 2)} s)` : ''}`,
          line: { color: COLORS.palette[index % COLORS.palette.length], width: 1.2 },
        };
      });
  }, [selectedAnalyses, offsets]);

  const waveformData = useMemo(() => {
    return selectedAnalyses
      .filter((analysis) => analysis.time_domain?.envelopes?.times?.length)
      .map((analysis, index) => {
        const offset = Number(offsets[analysis.file_id] ?? 0);
        return {
          x: analysis.time_domain.envelopes.times.map((time: number) => time - offset),
          y: analysis.time_domain.envelopes.rms_db,
          type: 'scatter',
          mode: 'lines',
          name: `${analysis.original_name} RMS`,
          line: { color: COLORS.palette[index % COLORS.palette.length], width: 1.1 },
        };
      });
  }, [selectedAnalyses, offsets]);

  if (files.length < 2) {
    return (
      <div className="section-stack">
        <SectionHeader title="Multi-file comparison" subtitle="Compare measurements, spectra, loudness and dynamics across files." />
        <Card>
          <EmptyState
            icon={<GitCompareArrows size={28} aria-hidden="true" />}
            title="At least two analysed files are required"
            description={`Upload and analyse two or more files to unlock the comparison engine (${files.length} analysed so far).`}
            action={
              <button className="btn btn-primary" onClick={() => navigate((session?.files.length ?? 0) >= 2 ? 'files' : 'upload')}>
                {(session?.files.length ?? 0) >= 2 ? 'Open files' : 'Upload audio'}
              </button>
            }
          />
        </Card>
      </div>
    );
  }

  return (
    <div className="section-stack">
      <SectionHeader
        title="Multi-file comparison"
        subtitle="A tolerance-based comparison engine. Level-match before perceptual judgments; unsupported and low-confidence values are labelled."
        actions={
          <>
            <button className="btn btn-sm btn-primary" onClick={() => void runComparison()} disabled={loading || selected.length < 2 || configInvalid}>
              {loading ? <Loader2 size={14} className="spin" aria-hidden="true" /> : <GitCompareArrows size={14} aria-hidden="true" />} Run comparison
            </button>
            <button
              className="btn btn-sm"
              disabled={!comparison || csvBusy}
              aria-busy={csvBusy}
              aria-label="Download comparison CSV"
              title={mode === 'segment' ? 'Exports the full-file comparison of these files (segment ranges are not part of the CSV export)' : 'Exports the parameter comparison shown below'}
              onClick={() => void exportCsv()}
            >
              {csvBusy ? <Loader2 size={14} className="spin" aria-hidden="true" /> : <Download size={14} aria-hidden="true" />} CSV{mode === 'segment' ? ' (full files)' : ''}
            </button>
          </>
        }
      />

      <Card>
        <FileSelect files={files} selected={selected} onChange={(ids) => { setSelected(ids); setComparison(null); autoRan.current = false; }} multiple label="Files to compare (2+)" />
        <div className="toolbar-grid">
          <div className="control-group">
            <div className="field-label">Parameters</div>
            <div className="checkbox-row" role="group" aria-label="Parameter groups">
              {PARAMETER_GROUPS.map((group) => (
                <label key={group.group} className="check-label">
                  <input
                    type="checkbox"
                    checked={groups.includes(group.group)}
                    onChange={(event) => {
                      setGroups((current) => event.target.checked ? [...current, group.group] : current.filter((g) => g !== group.group));
                      setComparison(null);
                    }}
                  />
                  {group.group}
                </label>
              ))}
            </div>
            {!groups.length && <span className="error-text small">Select at least one parameter group.</span>}
          </div>
          <div className="control-group">
            <div className="field-label">Mode</div>
            <ToggleGroup
              label="Comparison mode"
              value={mode}
              onChange={(value) => { setMode(value); setComparison(null); }}
              options={[
                { value: 'full', label: 'Full files' },
                { value: 'segment', label: 'Selected segments' },
              ]}
            />
            <label className="inline-label">Reference file
              <select value={reference} onChange={(event) => { setReference(event.target.value); setComparison(null); }}>
                <option value="">Compare as peers</option>
                {selectedFiles.map((file) => <option key={file.id} value={file.id}>{file.original_name}</option>)}
              </select>
            </label>
          </div>
        </div>
        {mode === 'segment' && (
          <div className="segment-ranges">
            {selectedFiles.map((file) => {
              const duration = Number(file.metadata?.duration ?? 0);
              const current = ranges[file.id] ?? { start: '0', end: String(duration) };
              const errs = rangeErrors[file.id] ?? {};
              const errId = `seg-${file.id}-err`;
              return (
                <div className="segment-range" key={file.id}>
                  <strong>{file.original_name}</strong>
                  <label>Start (s)<input type="number" min={0} max={duration} step={0.1} value={current.start} aria-invalid={!!errs.start} aria-describedby={errId} onChange={(event) => { setRanges({ ...ranges, [file.id]: { ...current, start: event.target.value } }); setComparison(null); }} /></label>
                  <label>End (s)<input type="number" min={0} max={duration} step={0.1} value={current.end} aria-invalid={!!errs.end} aria-describedby={errId} onChange={(event) => { setRanges({ ...ranges, [file.id]: { ...current, end: event.target.value } }); setComparison(null); }} /></label>
                  <span id={errId} className={errs.start || errs.end ? 'error-text small' : 'muted small'}>{errs.start ?? errs.end ?? `duration ${fmt(duration, 2)} s`}</span>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      <Card
        title="Alignment and synchronization"
        subtitle="Optional. Align corresponding sections before generating synchronized overlays; originals are untouched."
        actions={<Badge variant={alignment ? (alignment.confidence_label === 'high' ? 'success' : alignment.confidence_label === 'medium' ? 'warning' : 'error') : 'neutral'}>{alignment ? `${alignment.confidence_label} confidence` : 'not aligned'}</Badge>}
      >
        <div className="alignment-grid">
          <label>File A<select value={alignA} onChange={(event) => setAlignA(event.target.value)}>{selectedFiles.map((file) => <option key={file.id} value={file.id}>{file.original_name}</option>)}</select></label>
          <label>File B<select value={alignB} onChange={(event) => setAlignB(event.target.value)}>{selectedFiles.map((file) => <option key={file.id} value={file.id}>{file.original_name}</option>)}</select></label>
          <button className="btn btn-sm btn-primary" onClick={() => void runAlignment()} disabled={alignLoading || alignA === alignB}>
            {alignLoading ? <Loader2 size={14} className="spin" aria-hidden="true" /> : <ArrowLeftRight size={14} aria-hidden="true" />} Auto align
          </button>
          <label>
            Manual offset B (s)
            <input
              type="number"
              step={0.01}
              min={-600}
              max={600}
              value={manualOffset}
              aria-invalid={!!manualError}
              aria-describedby="manual-offset-msg"
              onChange={(event) => setManualOffset(event.target.value)}
              onKeyDown={(event) => { if (event.key === 'Enter') checkManualOffset(); }}
            />
            <span id="manual-offset-msg" className={manualError ? 'error-text small' : 'muted small'}>{manualError ?? 'Measures the match at this offset and applies it to B'}</span>
          </label>
          <button className="btn btn-sm" onClick={checkManualOffset} disabled={alignLoading || alignA === alignB || !!manualError}>
            <Crosshair size={14} aria-hidden="true" /> Check offset
          </button>
        </div>
        {alignment && (
          <div className="alignment-result">
            <div><span>Offset</span><b>{fmtSigned(alignment.offset_seconds, 3, 's')}</b></div>
            <div><span>Confidence</span><b>{fmt(alignment.confidence, 3)} ({alignment.confidence_label})</b></div>
            <div><span>Overlap</span><b>{fmt(alignment.overlap_seconds, 2)} s ({fmt((alignment.overlap_fraction ?? 0) * 100, 1)}%)</b></div>
            <div><span>Method</span><b>{alignment.method}</b></div>
            <div><span>Durations</span><b>{fmt(alignment.file_a_duration, 2)} / {fmt(alignment.file_b_duration, 2)} s</b></div>
            <div><span>Shift applied to B</span><b>{fmtSigned(alignment.apply_shift_to_b_seconds, 3, 's')}</b></div>
          </div>
        )}
        <p className="muted small">{alignment?.offset_description ?? 'Positive offset means file B starts later than file A. Overlay charts shift B left by the measured offset.'}</p>
        <div className="inline-inputs">
          {selectedFiles.slice(1).map((file) => (
            <label key={file.id}>Offset for {file.original_name} (s)<input type="number" step={0.01} value={offsets[file.id] ?? 0} onChange={(event) => setOffsets((current) => ({ ...current, [file.id]: Number(event.target.value) }))} /></label>
          ))}
        </div>
      </Card>

      {loading && <Card><div className="loading-row"><Spinner /> Comparing measurements…</div></Card>}

      {!loading && !comparison && selected.length >= 2 && (
        <InfoNote tone="info">
          {selected.every((id) => analyses[id])
            ? configInvalid
              ? 'Fix the highlighted settings, then run the comparison.'
              : 'The comparison settings changed. Select “Run comparison” to update the results.'
            : 'Loading the selected analyses…'}
        </InfoNote>
      )}

      {comparison && (
        <>
          <div className="comparison-summary">
            {Object.entries(comparison.summary).map(([status, count]) => (
              <div key={status} className={`comparison-summary-item status-${status}${count === 0 ? ' is-zero' : ''}`}>
                <b>{count}</b><span>{STATUS_LABEL[status] ?? status}</span>
              </div>
            ))}
          </div>

          <Card title="File summary" subtitle="Key measurements side by side. Select a column header to sort; values are not ranked as better or worse.">
            <TableWrap label="File summary">
              <table className="data-table summary-table">
                <thead>
                  <tr>
                    {([
                      ['name', 'File'], ['key', 'Key'], ['bpm', 'BPM'], ['sr', 'Sample rate'], ['lufs', 'Loudness'],
                      ['tp', 'True peak'], ['dr', 'Dynamic range'], ['lra', 'LRA'], ['width', 'Stereo width'],
                      ['gain', 'Gain within TP limit'], ['qc', 'QC'],
                    ] as [SummaryKey, string][]).map(([key, label]) => {
                      const active = summarySort.key === key;
                      return (
                        <th key={key} scope="col" aria-sort={active ? (summarySort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                          <button
                            type="button"
                            className="th-sort"
                            onClick={() => setSummarySort({ key, dir: active && summarySort.dir === 'asc' ? 'desc' : 'asc' })}
                          >
                            {label}
                            {active && (summarySort.dir === 'asc' ? <ArrowUp size={12} aria-hidden="true" /> : <ArrowDown size={12} aria-hidden="true" />)}
                          </button>
                        </th>
                      );
                    })}
                    <th scope="col"><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {summaryRows.map((row) => (
                    <tr key={row.id}>
                      <th scope="row">{row.name}</th>
                      <td>{row.key ?? '—'}{row.keyConf && <span className={`confidence-tag conf-${row.keyConf}`}>{row.keyConf}</span>}</td>
                      <td className="num">{fmt(row.bpm, 1)}{row.bpmConf && <span className={`confidence-tag conf-${row.bpmConf}`}>{row.bpmConf}</span>}</td>
                      <td className="num">{row.sr ? `${row.sr.toLocaleString()} Hz` : '—'}</td>
                      <td className="num">{row.lufs === null ? 'not measurable' : `${fmt(row.lufs)} LUFS`}</td>
                      <td className="num">{fmtUnit(row.tp, 'dBTP')}</td>
                      <td className="num">{fmtUnit(row.dr, 'dB')}</td>
                      <td className="num">{fmtUnit(row.lra, 'LU')}</td>
                      <td className="num">{row.width === null ? 'mono' : `${fmt(row.width)} %`}</td>
                      <td className="num">{fmtSigned(row.gain, 2, 'dB')}</td>
                      <td>{row.qc ? <SeverityBadge severity={row.qc} /> : '—'}</td>
                      <td>
                        <button className="btn btn-sm" onClick={() => navigate('overview', { file: row.id })} aria-label={`Open ${row.name} file overview`}>
                          <ExternalLink size={13} aria-hidden="true" /> Open
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          </Card>

          <Card
            title="Parameter comparison"
            subtitle={`${comparison.mode === 'segment' ? 'Selected time segments' : 'Full files'} · ${visibleRows.length} of ${comparison.rows.length} parameters shown. Status compares the spread with each parameter's tolerance.`}
          >
            <div className="table-controls">
              <div className="chip-filter" role="group" aria-label="Show statuses">
                {STATUSES.map((status) => (
                  <button
                    key={status}
                    type="button"
                    className={`chip status-${status} ${statusFilter.includes(status) ? 'active' : ''}`}
                    aria-pressed={statusFilter.includes(status)}
                    onClick={() => setStatusFilter((current) => current.includes(status) ? current.filter((v) => v !== status) : [...current, status])}
                  >
                    {STATUS_LABEL[status]} <b>{comparison.summary[status] ?? 0}</b>
                  </button>
                ))}
              </div>
              <label className="search-field">
                <Search size={14} aria-hidden="true" />
                <span className="sr-only">Filter parameters</span>
                <input type="search" placeholder="Filter parameters" value={rowQuery} onChange={(event) => setRowQuery(event.target.value)} />
              </label>
              <label className="inline-label">Sort
                <select value={rowSort} onChange={(event) => setRowSort(event.target.value as RowSort)}>
                  <option value="group">By group</option>
                  <option value="status">Largest differences first</option>
                  <option value="spread">Spread (high to low)</option>
                  <option value="name">Parameter A–Z</option>
                </select>
              </label>
            </div>
            <TableWrap label="Parameter comparison">
              <table className="data-table comparison-table">
                <thead>
                  <tr>
                    <th scope="col">Parameter</th>
                    {comparison.files.map((file) => <th scope="col" key={file.id}>{file.name}</th>)}
                    <th scope="col">Spread</th>
                    <th scope="col">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {(rowSort === 'group'
                    ? comparison.groups
                        .map((group) => ({ name: group.name, rows: visibleRows.filter((row) => row.group === group.name) }))
                        .filter((group) => group.rows.length)
                    : [{ name: '', rows: visibleRows }]
                  ).map((group) => (
                    <Fragment key={group.name || 'all'}>
                      {group.name && <tr className="group-row"><th colSpan={comparison.files.length + 3} scope="colgroup">{group.name}</th></tr>}
                      {group.rows.map((row) => (
                        <tr key={row.key} className={`comparison-row row-${row.status}`}>
                          <th scope="row">
                            <strong>{row.label}</strong>
                            {row.unit && <span className="muted small"> · {row.unit}</span>}
                            {row.note && <div className="muted small">{row.note}</div>}
                          </th>
                          {comparison.files.map((file) => (
                            <td key={file.id} className={`num ${reference && reference === file.id ? 'reference-cell' : ''}`}>
                              {row.display[file.id] ?? '—'}
                              {row.confidence?.[file.id] && <span className={`confidence-tag conf-${row.confidence[file.id]}`}>{row.confidence[file.id]}</span>}
                              {row.deviations?.[file.id] !== null && row.deviations?.[file.id] !== undefined && (
                                <span className="deviation">{fmtSigned(row.deviations[file.id], 2)}</span>
                              )}
                            </td>
                          ))}
                          <td className="num">{row.spread !== null ? fmt(row.spread, 3) : '—'}</td>
                          <td><span className={`status-pill status-${row.status}`}>{STATUS_LABEL[row.status] ?? row.status}</span></td>
                        </tr>
                      ))}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </TableWrap>
            {!visibleRows.length && <p className="muted">No parameters match the filters.</p>}
            <p className="muted small">{comparison.method}</p>
          </Card>

          <div className="two-col">
            <Card title="Tempo comparison" subtitle="Estimated BPM per file; hatched bars are low-confidence estimates.">
              <Plot
                title="Tempo comparison"
                summary={summaryRows.map((row) => `${row.name}: ${row.bpm === null ? 'no tempo' : `${fmt(row.bpm, 1)} BPM`}`).join('; ')}
                data={[{
                  x: summaryRows.map((row) => row.name),
                  y: summaryRows.map((row) => row.bpm),
                  type: 'bar',
                  marker: {
                    color: summaryRows.map((_row, index) => COLORS.palette[index % COLORS.palette.length]),
                    pattern: { shape: summaryRows.map((row) => (row.bpmConf === 'low' ? '/' : '')) },
                  },
                  hovertemplate: '%{x}: %{y:.1f} BPM<extra></extra>',
                }]}
                layout={{ height: 280, margin: { l: 50, r: 16, t: 16, b: 70 }, yaxis: { title: { text: 'BPM' } }, showlegend: false }}
                height={280}
                emptyMessage="No tempo estimates for these files."
              />
            </Card>
            <Card title="Dynamic range comparison" subtitle="Crest factor (dB), PLR (dB) and loudness range (LU).">
              <Plot
                title="Dynamic range comparison"
                summary={summaryRows.map((row) => `${row.name}: crest ${fmt(row.dr)} dB, PLR ${fmt(row.plr)} dB, LRA ${fmt(row.lra)} LU`).join('; ')}
                data={[
                  { key: 'dr', label: 'Crest factor (dB)' },
                  { key: 'plr', label: 'PLR (dB)' },
                  { key: 'lra', label: 'LRA (LU)' },
                ].map((metric, index) => ({
                  x: summaryRows.map((row) => row.name),
                  y: summaryRows.map((row) => (row as any)[metric.key]),
                  type: 'bar',
                  name: metric.label,
                  marker: { color: COLORS.palette[index], pattern: { shape: ['', '/', '.'][index] } },
                }))}
                layout={{ height: 280, barmode: 'group', margin: { l: 50, r: 16, t: 16, b: 70 }, yaxis: { title: { text: 'dB / LU' } } }}
                height={280}
              />
            </Card>
          </div>
          <div className="inline-actions">
            <span className="muted small">More overlays for these files:</span>
            <button className="btn btn-sm" onClick={() => navigate('waveform', { file: selected[0] })}>Waveform overlay</button>
            <button className="btn btn-sm" onClick={() => navigate('spectrogram', { file: selected[0] })}>Spectrograms side by side</button>
          </div>

          <div className="two-col">
            <Card title="Frequency-band comparison" subtitle="Relative share of measured energy.">
              <Plot title="Frequency-band comparison" summary="Share of measured energy per production band for each compared file." data={bandData} layout={{ height: 340, barmode: 'group', margin: { l: 48, r: 16, t: 16, b: 80 }, xaxis: { tickangle: -22 }, yaxis: { title: { text: 'Share (%)' } } }} height={340} />
            </Card>
            <Card title="Spectrum overlay" subtitle="Average FFT magnitude. Level-match before judging tonal differences.">
              <Plot title="Spectrum overlay" summary="Average FFT magnitude of each compared file on a logarithmic frequency axis." data={spectrumData} layout={{ height: 340, margin: { l: 50, r: 16, t: 16, b: 42 }, xaxis: { title: { text: 'Frequency (Hz)' }, type: 'log', range: [Math.log10(20), Math.log10(20000)] }, yaxis: { title: { text: 'dBFS' }, range: [-120, 6] } }} height={340} />
            </Card>
          </div>

          <Card title="Synchronized loudness overlay" subtitle="Short-term loudness, shifted by the selected offsets. Only overlapping content should be compared.">
            <Plot title="Synchronized loudness overlay" summary="Short-term loudness of each file, shifted by the alignment offsets." data={loudnessData} layout={{ height: 320, margin: { l: 50, r: 16, t: 16, b: 42 }, xaxis: { title: { text: 'Aligned time (s)' } }, yaxis: { title: { text: 'LUFS' } } }} height={320} />
          </Card>

          <Card title="RMS overlay" subtitle="Measured RMS envelopes. Alignment offsets are applied for display only.">
            <Plot title="RMS overlay" summary="RMS envelopes of each file, shifted by the alignment offsets." data={waveformData} layout={{ height: 300, margin: { l: 50, r: 16, t: 16, b: 42 }, xaxis: { title: { text: 'Aligned time (s)' } }, yaxis: { title: { text: 'RMS (dBFS)' } } }} height={300} />
          </Card>

          <Card title="Track gain comparison" subtitle={`Target ${fmt(comparison.target_lufs)} LUFS · limit ${fmt(comparison.true_peak_limit)} dBTP · preview only`}>
            <TableWrap label="Track gain comparison">
              <table className="data-table compact">
                <thead><tr><th scope="col">File</th><th scope="col">Integrated</th><th scope="col">Gain to target</th><th scope="col">Gain within TP limit</th><th scope="col">Expected sample peak</th><th scope="col">Expected true peak</th><th scope="col">Peak control</th><th scope="col">Status</th></tr></thead>
                <tbody>
                  {comparison.gain_preview.map((row: any) => (
                    <tr key={row.file_id}>
                      <td>{row.file_name}</td><td>{row.integrated_lufs === null || row.integrated_lufs === undefined ? 'not measurable' : `${fmt(row.integrated_lufs)} LUFS`}</td><td>{fmtSigned(row.gain_db, 2, 'dB')}</td>
                      <td>{fmtSigned(row.recommended_gain_db, 2, 'dB')}</td>
                      <td className="num">{fmtUnit(row.expected_sample_peak_dbfs, 'dBFS')}</td><td className="num">{fmtUnit(row.expected_true_peak_dbtp, 'dBTP')}</td>
                      <td>{row.peak_control_required_db ? `−${fmt(row.peak_control_required_db, 2)} dB` : 'none'}</td>
                      <td><Badge variant={row.status === 'ok' ? 'success' : row.status === 'unsupported' ? 'neutral' : 'warning'}>{row.status === 'true_peak_limit_exceeded' ? 'not reachable by gain alone' : String(row.status ?? '').replaceAll('_', ' ')}</Badge></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          </Card>

          <Card title="Cross-file findings" subtitle="Contextual differences; none of these are automatically classified as defects.">
            {comparison.findings.length ? (
              <div className="finding-list">
                {comparison.findings.map((finding) => (
                  <div className="finding finding-info" key={finding.id}>
                    <SeverityBadge severity={finding.severity} />
                    <div>
                      <strong>{finding.title}</strong>
                      <p>{finding.message}</p>
                      <p className="muted small">{finding.recommendation}</p>
                      <dl className="finding-values">
                        {describeFindingMeasurement(finding.measurement as Record<string, unknown>, fileNames).map((line) => (
                          <div key={line.label}>
                            <dt>{line.label}</dt>
                            <dd>{line.values.map((item) => (item.name ? `${item.name}: ${item.value}` : item.value)).join(' · ')}</dd>
                          </div>
                        ))}
                      </dl>
                    </div>
                  </div>
                ))}
              </div>
            ) : <p className="muted">No cross-file findings.</p>}
            <ul className="clean-list">{comparison.notes.map((note) => <li key={note}>{note}</li>)}</ul>
          </Card>
        </>
      )}
    </div>
  );
}
