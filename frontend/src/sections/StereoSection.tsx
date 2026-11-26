import { useMemo } from 'react';
import { CircleDot, Info } from 'lucide-react';
import { useFileSelection } from '../state/useFileSelection';
import { Card, InfoNote, SectionHeader, SeverityBadge, Stat } from '../components/UI';
import { AnalysisLoadState, NoAnalysedFiles } from '../components/AnalysisState';
import { PlotDownloadButton } from '../components/PlotDownloadButton';
import Plot from '../components/Plot';
import { COLORS, rgba } from '../lib/plotTheme';
import { correlationLabel, fmt } from '../lib/format';
import { formatMeasurement } from '../lib/qcFindings';

export default function StereoSection() {
  const { files, primary: file, analysis } = useFileSelection({ multiple: false, defaultCount: 1 });
  const stereo = analysis?.stereo;

  const vectorscopeData = useMemo(() => {
    if (!stereo?.supported || !stereo.vectorscope) return [];
    return [
      {
        x: stereo.vectorscope.left,
        y: stereo.vectorscope.right,
        type: 'scattergl',
        mode: 'markers',
        name: 'L/R samples',
        marker: { size: 2, color: rgba(COLORS.accent, 0.45) },
        hoverinfo: 'skip',
      },
    ];
  }, [stereo]);

  const channelData = useMemo(() => {
    if (!stereo?.supported || !stereo.channel_envelope) return [];
    return [
      { x: stereo.channel_envelope.times, y: stereo.channel_envelope.left_db, type: 'scatter', mode: 'lines', name: 'Left', line: { color: COLORS.accent2, width: 0.7 } },
      { x: stereo.channel_envelope.times, y: stereo.channel_envelope.right_db, type: 'scatter', mode: 'lines', name: 'Right', line: { color: COLORS.warning, width: 0.7 } },
    ];
  }, [stereo]);

  const correlationData = useMemo(() => {
    if (!stereo?.timeline) return [];
    return [
      { x: stereo.timeline.times, y: stereo.timeline.correlation, type: 'scatter', mode: 'lines', name: 'Correlation', line: { color: COLORS.success, width: 1.1 }, fill: 'tozeroy', fillcolor: rgba(COLORS.success, 0.08) },
    ];
  }, [stereo]);

  const widthData = useMemo(() => {
    if (!stereo?.timeline) return [];
    return [
      { x: stereo.timeline.times, y: stereo.timeline.width, type: 'scatter', mode: 'lines', name: 'Side/mid ratio', line: { color: COLORS.accent3, width: 1.3 }, hovertemplate: '%{x:.1f} s · side/mid %{y:.3f}<extra></extra>' },
      { x: stereo.timeline.times, y: stereo.timeline.mid_db, type: 'scatter', mode: 'lines', name: 'Mid level (dBFS)', yaxis: 'y2', line: { color: COLORS.accent2, width: 0.8, dash: 'dot' }, hovertemplate: '%{x:.1f} s · mid %{y:.1f} dBFS<extra></extra>' },
      { x: stereo.timeline.times, y: stereo.timeline.side_db, type: 'scatter', mode: 'lines', name: 'Side level (dBFS)', yaxis: 'y2', line: { color: COLORS.warning, width: 0.8, dash: 'dash' }, hovertemplate: '%{x:.1f} s · side %{y:.1f} dBFS<extra></extra>' },
    ];
  }, [stereo]);

  if (!files.length) {
    return (
      <div className="section-stack">
        <SectionHeader title="Stereo and phase" subtitle="Vectorscope, correlation, width and mono compatibility." />
        <NoAnalysedFiles icon={<CircleDot size={28} aria-hidden="true" />} description="Run analysis to inspect stereo properties." />
      </div>
    );
  }

  return (
    <div className="section-stack">
      <SectionHeader
        title="Stereo and phase"
        subtitle="Pearson correlation, mid/side energy and mono fold-down. Mono files are reported as mono without fabricated stereo values."
        actions={<PlotDownloadButton fileId={file?.id} fileName={file?.original_name} kind="vectorscope" plotName="vectorscope" text="Vectorscope PNG" />}
      />

      <AnalysisLoadState fileId={file?.id} label="stereo analysis" />

      {analysis && stereo && (
        !stereo.supported ? (
          <Card title="Mono file" subtitle="Stereo metrics are not applicable.">
            <InfoNote tone="info">
              {stereo.reason} The file was measured as mono: RMS {fmt(stereo.mono_rms_dbfs)} dBFS, peak {fmt(stereo.mono_peak_dbfs)} dBFS.
            </InfoNote>
            <div className="stat-grid">
              <Stat label="Mono RMS" value={fmt(stereo.mono_rms_dbfs)} unit="dBFS" />
              <Stat label="Mono peak" value={fmt(stereo.mono_peak_dbfs)} unit="dBFS" />
              <Stat label="Channels" value={stereo.channel_count} />
            </div>
          </Card>
        ) : (
          <>
            <div className="stat-grid">
              <Stat label="Correlation" value={fmt(stereo.correlation?.value, 3)} tone={Number(stereo.correlation?.value) < 0 ? 'warning' : 'default'} hint={stereo.correlation?.value === null || stereo.correlation?.value === undefined ? 'undefined — a channel has no signal' : correlationLabel(Number(stereo.correlation.value))} />
              <Stat label="Stereo width" value={fmt(stereo.mid_side?.stereo_width_percent)} unit="%" hint={`Side/mid ${fmt(stereo.mid_side?.side_to_mid_ratio, 2)}`} />
              <Stat label="Balance" value={fmt(stereo.balance?.balance_db)} unit="dB" hint={stereo.balance?.label} />
              <Stat label="Mono fold-down loss" value={fmt(stereo.mono_compatibility?.mono_loss_db)} unit="dB" tone={Number(stereo.mono_compatibility?.mono_loss_db) < -6 ? 'warning' : 'default'} />
              <Stat label="Left RMS" value={fmt(stereo.left?.rms_dbfs)} unit="dBFS" />
              <Stat label="Right RMS" value={fmt(stereo.right?.rms_dbfs)} unit="dBFS" />
            </div>

            <div className="two-col">
              <Card title="Stereo vectorscope" subtitle="L/R sample pairs; the diagonal is mono, the anti-diagonal is out of phase.">
                <Plot
                  title="Stereo vectorscope"
                  summary={`Left/right sample scatter; correlation ${fmt(stereo.correlation?.value, 3)}. Points on the rising diagonal are mono, on the falling diagonal out of phase.`}
                  data={vectorscopeData}
                  layout={{
                    height: 420,
                    margin: { l: 50, r: 16, t: 16, b: 42 },
                    xaxis: { title: { text: 'Left' }, range: [-1.05, 1.05], zeroline: true },
                    yaxis: { title: { text: 'Right' }, range: [-1.05, 1.05], scaleanchor: 'x', scaleratio: 1, zeroline: true },
                    showlegend: false,
                    shapes: [
                      { type: 'line', x0: -1, x1: 1, y0: -1, y1: 1, line: { color: rgba(COLORS.reference, 0.45), width: 0.8, dash: 'dot' } },
                      { type: 'line', x0: -1, x1: 1, y0: 1, y1: -1, line: { color: rgba(COLORS.reference, 0.25), width: 0.8, dash: 'dot' } },
                    ],
                  }}
                  height={420}
                />
                <p className="muted small">Correlation {fmt(stereo.correlation?.value, 3)} · channel similarity {fmt(stereo.correlation?.channel_similarity, 3)}</p>
              </Card>
              <Card title="Left / right channels" subtitle="Instantaneous sampled channel levels (not RMS).">
                <Plot summary="Left and right channel sample levels over time in dBFS." data={channelData} layout={{ height: 280, margin: { l: 50, r: 16, t: 16, b: 42 }, xaxis: { title: { text: 'Time (s)' } }, yaxis: { title: { text: 'Level (dBFS)' }, range: [-90, 3] }, showlegend: true }} height={280} title="Left and right channel sample levels" />
                <div className="kv-grid">
                  <span>Mid RMS</span><b>{fmt(stereo.mid_side?.mid_rms_dbfs)} dBFS</b>
                  <span>Side RMS</span><b>{fmt(stereo.mid_side?.side_rms_dbfs)} dBFS</b>
                  <span>Mono fold RMS</span><b>{fmt(stereo.mono_compatibility?.mono_fold_rms_dbfs)} dBFS</b>
                  <span>Mono peak</span><b>{fmt(stereo.mono_compatibility?.mono_peak_dbfs)} dBFS</b>
                  <span>Compatible</span><b>{stereo.mono_compatibility?.compatible ? 'Yes' : 'Review'}</b>
                  <span>Confidence</span><b>{stereo.confidence}</b>
                </div>
              </Card>
            </div>

            <Card title="Correlation timeline" subtitle="1 s windows, 0.5 s hop. Negative values indicate phase cancellation in that section.">
              <Plot title="Correlation timeline" summary={`Windowed L/R correlation over time; overall ${fmt(stereo.correlation?.value, 3)}.`} data={correlationData} layout={{ height: 250, margin: { l: 50, r: 16, t: 16, b: 42 }, xaxis: { title: { text: 'Time (s)' } }, yaxis: { title: { text: 'Correlation' }, range: [-1.05, 1.05] }, showlegend: false }} height={250} />
            </Card>

            <Card title="Stereo width and mid/side levels" subtitle="Side/mid ratio and mid/side levels over time.">
              <Plot
                title="Stereo width and mid/side levels"
                summary={`Side/mid ratio (left axis) and mid and side RMS levels in dBFS (right axis); overall width ${fmt(stereo.mid_side?.stereo_width_percent)} %.`}
                data={widthData}
                layout={{
                  height: 280,
                  margin: { l: 54, r: 58, t: 16, b: 42 },
                  xaxis: { title: { text: 'Time (s)' } },
                  yaxis: { title: { text: 'Side/mid ratio' }, rangemode: 'tozero' },
                  yaxis2: { title: { text: 'Level (dBFS)' }, overlaying: 'y', side: 'right', showgrid: false },
                  legend: { orientation: 'h', y: 1.12, x: 0 },
                  showlegend: true,
                }}
                height={280}
              />
            </Card>

            <Card title="Stereo observations" subtitle="Measured issues and informational notes.">
              {stereo.issues?.length ? (
                <div className="finding-list">
                  {stereo.issues.map((issue) => (
                    <div className={`finding finding-${issue.severity === 'error' ? 'error' : issue.severity === 'warning' ? 'warning' : 'info'}`} key={issue.type}>
                      <Info size={16} aria-hidden="true" />
                      <div>
                        <SeverityBadge severity={issue.severity} />
                        <p><strong>{issue.type.replaceAll('_', ' ')}</strong> — {issue.message}</p>
                        <p className="muted small">{issue.recommendation}</p>
                        {issue.measurement && <p className="finding-measure small"><span className="field-label">Measured</span> {formatMeasurement(issue.measurement)}</p>}
                      </div>
                    </div>
                  ))}
                </div>
              ) : <p className="muted">No stereo issues flagged.</p>}
              <p className="muted small">{stereo.method}</p>
            </Card>
          </>
        )
      )}
    </div>
  );
}
