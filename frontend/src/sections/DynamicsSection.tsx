import { useMemo } from 'react';
import { ChartColumnBig, Gauge } from 'lucide-react';
import { useFileSelection } from '../state/useFileSelection';
import { Card, InfoNote, SectionHeader, Stat, TableWrap } from '../components/UI';
import { AnalysisLoadState, NoAnalysedFiles } from '../components/AnalysisState';
import { PlotDownloadButton } from '../components/PlotDownloadButton';
import Plot from '../components/Plot';
import { COLORS, regionShapes, rgba } from '../lib/plotTheme';
import { fmt } from '../lib/format';
import { formatMeasurement } from '../lib/qcFindings';

export default function DynamicsSection() {
  const { files, primary: file, analysis } = useFileSelection({ multiple: false, defaultCount: 1 });

  const levelData = useMemo(() => {
    if (!analysis) return [];
    const tl = analysis.dynamics.timeline;
    return [
      { x: tl.times, y: tl.rms_db, type: 'scatter', mode: 'lines', name: 'RMS', line: { color: COLORS.accent2, width: 0.9 } },
      { x: tl.times, y: tl.peak_db, type: 'scatter', mode: 'lines', name: 'Peak', line: { color: COLORS.error, width: 0.7 } },
    ];
  }, [analysis]);

  const crestData = useMemo(() => {
    if (!analysis) return [];
    const tl = analysis.dynamics.timeline;
    return [{ x: tl.times, y: tl.crest_db, type: 'scatter', mode: 'lines', name: 'Crest factor', line: { color: COLORS.accent3, width: 0.9 }, fill: 'tozeroy', fillcolor: rgba(COLORS.accent3, 0.1) }];
  }, [analysis]);

  const loudnessData = useMemo(() => {
    if (!analysis) return [];
    return [
      { x: analysis.dynamics.timeline.short_term_lufs.times, y: analysis.dynamics.timeline.short_term_lufs.values, type: 'scatter', mode: 'lines', name: 'Short-term loudness', line: { color: COLORS.success, width: 1.2 } },
    ];
  }, [analysis]);

  const shapes = useMemo(() => (analysis ? regionShapes(analysis.dynamics.reduced_dynamic_sections, rgba(COLORS.warning, 0.13)) : []), [analysis]);

  if (!files.length) {
    return (
      <div className="section-stack">
        <SectionHeader title="Dynamic range" subtitle="Crest factor, loudness range and compression indicators." />
        <NoAnalysedFiles icon={<ChartColumnBig size={28} aria-hidden="true" />} description="Run analysis to inspect dynamics." />
      </div>
    );
  }

  return (
    <div className="section-stack">
      <SectionHeader
        title="Dynamic range"
        subtitle="Measured crest factor, loudness range and short-term variation. Reduced-dynamic sections are highlighted as observations, not defects."
        actions={<PlotDownloadButton fileId={file?.id} fileName={file?.original_name} kind="dynamics" plotName="dynamics plot" />}
      />

      <AnalysisLoadState fileId={file?.id} label="dynamics" />

      {analysis && (
        <>
          <div className="stat-grid">
            <Stat label="Crest factor" value={fmt(analysis.dynamics.crest_factor_db)} unit="dB" tone="accent" />
            <Stat label="Loudness range" value={fmt(analysis.dynamics.loudness_range_lu)} unit="LU" />
            <Stat label="PLR" value={fmt(analysis.dynamics.peak_to_loudness_ratio_db)} unit="dB" />
            <Stat label="RMS variation" value={fmt(analysis.dynamics.rms_variation_db)} unit="dB" />
            <Stat label="Short-term variation" value={fmt(analysis.dynamics.short_term_dynamic_variation_lu)} unit="LU" />
            <Stat label="Transient density" value={fmt(analysis.dynamics.transient_strength?.transient_density_per_second, 2)} unit="/s" hint={analysis.dynamics.transient_strength?.supported ? 'onsets' : 'unavailable'} />
          </div>

          <Card title="Level and crest factor" subtitle="RMS, sample peak and crest factor over time.">
            <Plot title="RMS and peak level" summary={`Frame RMS and sample peak over time; crest factor ${fmt(analysis.dynamics.crest_factor_db)} dB.`} data={levelData} layout={{ height: 300, margin: { l: 50, r: 16, t: 18, b: 40 }, xaxis: { title: { text: 'Time (s)' } }, yaxis: { title: { text: 'Level (dBFS)' } }, showlegend: true }} height={300} />
            <Plot title="Crest factor over time" summary="Crest factor (peak minus RMS) per frame; shaded regions are reduced-dynamics observations." data={crestData} layout={{ height: 230, margin: { l: 50, r: 16, t: 18, b: 40 }, xaxis: { title: { text: 'Time (s)' } }, yaxis: { title: { text: 'Crest factor (dB)' } }, shapes, showlegend: false }} height={230} />
            <div className="legend-note"><span><i className="swatch swatch-reduced" aria-hidden="true" /> Reduced-dynamics observation</span></div>
          </Card>

          <div className="two-col">
            <Card title="Short-term loudness" subtitle="3 s K-weighted loudness, used for LRA.">
              <Plot title="Short-term loudness" summary={`Short-term loudness over time; loudness range ${fmt(analysis.dynamics.loudness_range_lu)} LU.`} data={loudnessData} layout={{ height: 280, margin: { l: 50, r: 16, t: 18, b: 40 }, xaxis: { title: { text: 'Time (s)' } }, yaxis: { title: { text: 'LUFS' } }, showlegend: false }} height={280} />
            </Card>
            <Card title="Transient strength" subtitle="Onset-strength envelope at detected onsets.">
              {analysis.dynamics.transient_strength?.supported ? (
                <div className="kv-grid">
                  <span>Onsets</span><b>{analysis.dynamics.transient_strength.onset_count}</b>
                  <span>Mean strength</span><b>{fmt(analysis.dynamics.transient_strength.strength_mean, 3)}</b>
                  <span>P95 strength</span><b>{fmt(analysis.dynamics.transient_strength.strength_p95, 3)}</b>
                  <span>P95 / median</span><b>{fmt(analysis.dynamics.transient_strength.peak_to_median_ratio, 2)}×</b>
                  <span>Density</span><b>{fmt(analysis.dynamics.transient_strength.transient_density_per_second, 2)}/s</b>
                  <span>Method</span><b>{analysis.dynamics.transient_strength.method}</b>
                </div>
              ) : <p className="muted">{analysis.dynamics.transient_strength?.reason ?? 'Not available.'}</p>}
            </Card>
          </div>

          <Card title="Compression indicators" subtitle="Contextual observations based on measured dynamics.">
            {analysis.dynamics.compression_indicators.length ? (
              <div className="finding-list">
                {analysis.dynamics.compression_indicators.map((indicator: any) => (
                  <div className="finding finding-warning" key={indicator.type}>
                    <Gauge size={16} aria-hidden="true" />
                    <div>
                      <strong>{indicator.type.replaceAll('_', ' ')}</strong>
                      <p>{indicator.message} {indicator.recommendation}</p>
                      {indicator.measurement && <p className="finding-measure small"><span className="field-label">Measured</span> {formatMeasurement(indicator.measurement)}</p>}
                    </div>
                  </div>
                ))}
              </div>
            ) : <p className="muted">No compression indicators were flagged.</p>}
          </Card>

          {analysis.dynamics.reduced_dynamic_sections.length > 0 && (
            <Card title="Sections with reduced dynamics" subtitle="Local loudness range below 2.5 LU or local crest range below 5 dB.">
              <TableWrap label="Sections with reduced dynamics">
                <table className="data-table compact">
                  <thead><tr><th scope="col">Start</th><th scope="col">End</th><th scope="col">Local LRA</th><th scope="col">Local crest</th><th scope="col">Note</th></tr></thead>
                  <tbody>
                    {analysis.dynamics.reduced_dynamic_sections.map((section: any, index: number) => (
                      <tr key={`${section.start}-${index}`}>
                        <td>{fmt(section.start, 1)} s</td>
                        <td>{fmt(section.end, 1)} s</td>
                        <td>{fmt(section.local_lra_lu)} LU</td>
                        <td>{fmt(section.local_crest_db)} dB</td>
                        <td className="muted small">{section.note}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
              <InfoNote tone="warning">
                These sections are observations, not errors. Low local dynamics can be an intentional production choice. Compare
                against the arrangement and a reference track before changing compression.
              </InfoNote>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
