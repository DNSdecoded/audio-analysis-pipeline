import { useEffect, useMemo, useState } from 'react';
import { Gauge } from 'lucide-react';
import { useApp } from '../state/AppContext';
import { useFileSelection } from '../state/useFileSelection';
import { Badge, Card, InfoNote, SectionHeader, Stat, TableWrap } from '../components/UI';
import { AnalysisLoadState, NoAnalysedFiles } from '../components/AnalysisState';
import { PlotDownloadButton } from '../components/PlotDownloadButton';
import { FileSelect } from '../components/FileSelect';
import { parseNumberInput, validateLoudnessTargets } from '../lib/inputValidation';
import Plot from '../components/Plot';
import { COLORS, minSpanRange, regionShapes, rgba } from '../lib/plotTheme';
import { fmt, fmtSigned, fmtUnit } from '../lib/format';
import { gainRow } from '../lib/analysisLogic';

export default function LoudnessSection() {
  const { session, analyses } = useApp();
  const { files, selected, setSelected } = useFileSelection({ multiple: true, defaultCount: 1 });
  // Inputs keep the typed text; the preview uses the last *valid* values so an
  // empty or out-of-range field never silently becomes 0 LUFS.
  const [targetText, setTargetText] = useState(String(session?.settings.target_lufs ?? -14));
  const [limitText, setLimitText] = useState(String(session?.settings.true_peak_limit ?? -1));
  const targetErrors = validateLoudnessTargets(parseNumberInput(targetText), parseNumberInput(limitText));
  const target = targetErrors.target ? Number(session?.settings.target_lufs ?? -14) : parseNumberInput(targetText);
  const limit = targetErrors.limit ? Number(session?.settings.true_peak_limit ?? -1) : parseNumberInput(limitText);
  const [showMomentary, setShowMomentary] = useState(true);

  useEffect(() => {
    if (session) {
      setTargetText(String(session.settings.target_lufs));
      setLimitText(String(session.settings.true_peak_limit));
    }
  }, [session?.settings.target_lufs, session?.settings.true_peak_limit]);

  const primary = files.find((file) => file.id === selected[0]);
  const analysis = primary ? analyses[primary.id] : undefined;

  const traces = useMemo(() => {
    const result: any[] = [];
    selected.forEach((id, index) => {
      const file = files.find((candidate) => candidate.id === id);
      const item = analyses[id];
      if (!file || !item) return;
      const color = COLORS.palette[index % COLORS.palette.length];
      result.push({
        x: item.loudness.short_term.times,
        y: item.loudness.short_term.lufs,
        type: 'scatter',
        mode: 'lines',
        name: `${file.original_name} short-term`,
        line: { color, width: index === 0 ? 1.8 : 1.1 },
        hovertemplate: '%{x:.2f}s · %{y:.2f} LUFS<extra>' + file.original_name + '</extra>',
      });
      if (index === 0 && showMomentary) {
        result.push({
          x: item.loudness.momentary.times,
          y: item.loudness.momentary.lufs,
          type: 'scatter',
          mode: 'lines',
          name: 'Momentary (400 ms)',
          line: { color: rgba(COLORS.reference, 0.65), width: 0.7 },
          hovertemplate: '%{x:.2f}s · %{y:.2f} LUFS<extra>momentary</extra>',
        });
      }
      if (index === 0 && item.loudness.integrated_lufs !== null && item.loudness.integrated_lufs !== undefined) {
        result.push({
          x: [0, Number(item.metadata.duration ?? 0)],
          y: [item.loudness.integrated_lufs, item.loudness.integrated_lufs],
          type: 'scatter',
          mode: 'lines',
          name: `Integrated ${fmt(item.loudness.integrated_lufs)} LUFS`,
          line: { color: COLORS.success, width: 1.1, dash: 'dash' },
          hoverinfo: 'skip',
        });
      }
    });
    result.push({
      x: [0, Number(primary?.metadata.duration ?? 0)],
      y: [target, target],
      type: 'scatter',
      mode: 'lines',
      name: `Target ${fmt(target)} LUFS`,
      line: { color: COLORS.warning, width: 1, dash: 'dot' },
      hoverinfo: 'skip',
    });
    return result;
  }, [selected, files, analyses, showMomentary, target, primary]);

  const maxLoudness = Number(analysis?.qc.thresholds?.loudness_max_lufs ?? -6);
  const shapes = useMemo(() => {
    if (!analysis) return [];
    const st = analysis.loudness.short_term;
    const regions: { start: number; end: number }[] = [];
    let open: number | null = null;
    st.times.forEach((time, index) => {
      const above = st.lufs[index] > maxLoudness;
      if (above && open === null) open = time;
      if (!above && open !== null) {
        regions.push({ start: open, end: time });
        open = null;
      }
    });
    if (open !== null) regions.push({ start: open, end: st.times.at(-1) ?? open });
    return regionShapes(regions, rgba(COLORS.error, 0.14));
  }, [analysis, maxLoudness]);

  const gainRows = useMemo(() => {
    return selected.map((id) => {
      const file = files.find((candidate) => candidate.id === id);
      const item = analyses[id];
      if (!file || !item) return null;
      const integrated = item.loudness.integrated_lufs;
      return {
        file,
        integrated,
        ...gainRow(integrated, item.loudness.true_peak_dbtp, item.loudness.sample_peak_dbfs, target, limit),
      };
    }).filter(Boolean) as any[];
  }, [selected, files, analyses, target, limit]);

  const yRange = useMemo(() => {
    const values: (number | null)[] = [target];
    selected.forEach((id) => {
      const item = analyses[id];
      if (!item) return;
      values.push(...item.loudness.short_term.lufs);
      if (showMomentary) values.push(...item.loudness.momentary.lufs);
    });
    return minSpanRange(values, 12, 1);
  }, [selected, analyses, showMomentary, target]);

  const layout = useMemo(
    () => ({
      height: 420,
      margin: { l: 54, r: 18, t: 22, b: 44 },
      xaxis: { title: { text: 'Time (s)' } },
      // At least a 12 LU window so small variations are not exaggerated.
      yaxis: { title: { text: 'Loudness (LUFS)' }, range: yRange },
      shapes,
      showlegend: true,
    }),
    [shapes, yRange],
  );

  if (!files.length) {
    return (
      <div className="section-stack">
        <SectionHeader title="Loudness and gain" subtitle="ITU-R BS.1770 / EBU R128 measurements and gain preview." />
        <NoAnalysedFiles icon={<Gauge size={28} aria-hidden="true" />} description="Run analysis to measure loudness." />
      </div>
    );
  }

  return (
    <div className="section-stack">
      <SectionHeader
        title="Loudness and gain"
        subtitle="Integrated, short-term and momentary loudness; true-peak status and a non-destructive gain preview."
        actions={<PlotDownloadButton fileId={primary?.id} fileName={primary?.original_name} kind="loudness" plotName="loudness plot" />}
      />

      <Card>
        <FileSelect files={files} selected={selected} onChange={setSelected} multiple label="Overlay files (the active file is always first)" max={4} />
        <div className="toolbar-grid">
          <div className="inline-inputs">
            <label>
              Target loudness (LUFS)
              <input type="number" min={-60} max={0} step={0.1} value={targetText} aria-invalid={!!targetErrors.target} aria-describedby="loud-target-msg" onChange={(event) => setTargetText(event.target.value)} />
              {targetErrors.target && <span id="loud-target-msg" className="error-text small">{targetErrors.target} Using {fmt(target)} LUFS.</span>}
            </label>
            <label>
              True-peak limit (dBTP)
              <input type="number" min={-20} max={0} step={0.1} value={limitText} aria-invalid={!!targetErrors.limit} aria-describedby="loud-limit-msg" onChange={(event) => setLimitText(event.target.value)} />
              {targetErrors.limit && <span id="loud-limit-msg" className="error-text small">{targetErrors.limit} Using {fmt(limit)} dBTP.</span>}
            </label>
            <label className="check-label"><input type="checkbox" checked={showMomentary} onChange={(event) => setShowMomentary(event.target.checked)} /> Show momentary (primary)</label>
          </div>
          <span className="muted small">Preview only · no gain is applied · original files preserved</span>
        </div>
        <AnalysisLoadState fileId={primary?.id} label="loudness measurements" />
        {analysis && (
          <Plot
            title="Loudness over time"
            summary={`Short-term${showMomentary ? ' and momentary' : ''} loudness; integrated ${fmt(analysis.loudness.integrated_lufs)} LUFS, target ${fmt(target)} LUFS.`}
            data={traces}
            layout={layout}
            height={420}
          />
        )}
        <div className="legend-note">
          <span><i className="swatch swatch-critical" aria-hidden="true" /> Above configured loudness maximum ({fmt(maxLoudness)} LUFS)</span>
          <span>Short-term = 3 s · Momentary = 400 ms</span>
        </div>
      </Card>

      {analysis && (
        <div className="stat-grid">
          <Stat label="Integrated" value={fmt(analysis.loudness.integrated_lufs)} unit="LUFS" tone="accent" hint={analysis.loudness.confidence} />
          <Stat label="Short-term max" value={fmt(analysis.loudness.short_term_max_lufs)} unit="LUFS" />
          <Stat label="Loudness range" value={fmt(analysis.loudness.loudness_range_lu)} unit="LU" />
          <Stat label="True peak" value={fmt(analysis.loudness.true_peak_dbtp)} unit="dBTP" tone={Number(analysis.loudness.true_peak_dbtp) > limit ? 'warning' : 'default'} />
          <Stat label="Peak-to-loudness" value={fmt(analysis.loudness.peak_to_loudness_ratio_db)} unit="dB" />
          <Stat label="Crest factor" value={fmt(analysis.loudness.crest_factor_db)} unit="dB" />
        </div>
      )}

      <Card
        title="Track gain preview"
        subtitle={`Target ${fmt(target)} LUFS · true-peak limit ${fmt(limit)} dBTP. Gain is calculated from measured integrated loudness.`}
        actions={<Badge variant="warning">Not applied</Badge>}
      >
        <TableWrap label="Track gain preview">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">File</th>
                <th scope="col">Current</th>
                <th scope="col">Gain to target</th>
                <th scope="col">Gain within TP limit</th>
                <th scope="col">Expected sample peak</th>
                <th scope="col">Expected true peak</th>
                <th scope="col">Peak control</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {gainRows.map((row) => (
                <tr key={row.file.id}>
                  <td>{row.file.original_name}</td>
                  <td>{row.integrated === null || row.integrated === undefined ? 'not measurable' : `${fmt(row.integrated)} LUFS`}</td>
                  <td className={row.gain !== null && row.gain > 0 ? 'warning-text' : ''}>{fmtSigned(row.gain, 2, 'dB')}</td>
                  <td>{fmtSigned(row.safeGain, 2, 'dB')}</td>
                  <td className="num">{fmtUnit(row.expectedSample, 'dBFS')}</td>
                  <td className="num">{fmtUnit(row.expectedTrue, 'dBTP')}</td>
                  <td>{row.peakControl ? `−${fmt(row.peakControl, 2)} dB` : 'none'}</td>
                  <td><Badge variant={row.status === 'within limit' ? 'success' : 'warning'}>{row.status}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
        <InfoNote>
          A positive gain increases level. If the expected true peak exceeds the limit, peak control is required (for example a
          lower limiter ceiling). The platform does not apply gain or limiting; use a copy in your DAW.
        </InfoNote>
      </Card>

      {analysis && (
        <div className="two-col">
          <Card title="Loudness measurements" subtitle="BS.1770-4 / EBU R128.">
            <div className="kv-grid">
              <span>Integrated</span><b>{fmt(analysis.loudness.integrated_lufs)} LUFS</b>
              <span>Short-term max / min</span><b>{fmt(analysis.loudness.short_term_max_lufs)} / {fmt(analysis.loudness.short_term_min_lufs)} LUFS</b>
              <span>Momentary max / min</span><b>{fmt(analysis.loudness.momentary_max_lufs)} / {fmt(analysis.loudness.momentary_min_lufs)} LUFS</b>
              <span>Loudness range</span><b>{fmt(analysis.loudness.loudness_range_lu)} LU</b>
              <span>Sample peak</span><b>{fmt(analysis.loudness.sample_peak_dbfs)} dBFS</b>
              <span>True peak</span><b>{fmt(analysis.loudness.true_peak_dbtp)} dBTP</b>
              <span>RMS</span><b>{fmt(analysis.loudness.rms_dbfs)} dBFS</b>
              <span>PLR</span><b>{fmt(analysis.loudness.peak_to_loudness_ratio_db)} dB</b>
              <span>Relative gate</span><b>{fmt(analysis.loudness.relative_gate_lufs)} LUFS</b>
              <span>Gated blocks</span><b>{fmt(analysis.loudness.gated_blocks, 0)} / {fmt(analysis.loudness.block_count, 0)}</b>
            </div>
            <p className="muted small">{String(analysis.loudness.channel_weighting_note ?? '')}</p>
          </Card>
          <Card title="Gain control notes" subtitle="Why the preview can differ from a limiter.">
            <ul className="clean-list">
              <li>Gain is a linear change; it does not compress or limit the signal.</li>
              <li>Expected true peak is current true peak plus gain; intersample peaks remain relevant.</li>
              <li>Integrated loudness changes with the programme material, not exactly by the gain amount after processing.</li>
              <li>Always verify the processed copy with a fresh analysis; the original is never modified.</li>
            </ul>
          </Card>
        </div>
      )}
    </div>
  );
}
