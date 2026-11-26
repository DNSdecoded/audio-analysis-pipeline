import { useMemo } from 'react';
import { Music2, Timer } from 'lucide-react';
import { useFileSelection } from '../state/useFileSelection';
import { Badge, Card, ConfidenceBar, InfoNote, SectionHeader, Stat, TableWrap } from '../components/UI';
import { AnalysisLoadState, NoAnalysedFiles } from '../components/AnalysisState';
import { PlotDownloadButton } from '../components/PlotDownloadButton';
import Plot from '../components/Plot';
import { COLORS, VIRIDIS, beatShapes } from '../lib/plotTheme';
import { fmt } from '../lib/format';

export default function MusicalSection() {
  const { files, primary: file, analysis } = useFileSelection({ multiple: false, defaultCount: 1 });

  const chromaData = useMemo(() => {
    if (!analysis) return [];
    return [
      {
        x: analysis.spectral.chroma.pitch_classes,
        y: analysis.spectral.chroma.mean_energy,
        type: 'bar',
        marker: { color: analysis.spectral.chroma.mean_energy.map((value, index) => value === Math.max(...analysis.spectral.chroma.mean_energy) ? COLORS.accent : COLORS.palette[index % COLORS.palette.length]) },
        hovertemplate: '%{x}: %{y:.3f}<extra>mean chroma</extra>',
      },
    ];
  }, [analysis]);

  const chromagramData = useMemo(() => {
    if (!analysis) return [];
    return [
      {
        x: analysis.spectral.chroma.times,
        y: analysis.spectral.chroma.pitch_classes,
        z: analysis.spectral.chroma.energy,
        type: 'heatmap',
        colorscale: VIRIDIS,
        zmin: 0,
        zmax: 1,
        colorbar: { thickness: 10, title: { text: 'Energy' } },
        hovertemplate: '%{x:.1f}s · %{y} · %{z:.3f}<extra></extra>',
      },
    ];
  }, [analysis]);

  const beatData = useMemo(() => {
    if (!analysis) return [];
    const env = analysis.musical.rhythm.onset_envelope;
    return [
      {
        x: env.times,
        y: env.values,
        type: 'scatter',
        mode: 'lines',
        name: 'Onset strength',
        line: { color: COLORS.accent2, width: 0.9 },
        hovertemplate: '%{x:.2f}s · %{y:.3f}<extra></extra>',
      },
    ];
  }, [analysis]);

  const tempoData = useMemo(() => {
    if (!analysis) return [];
    const local = analysis.musical.tempo.local_tempo ?? [];
    const traces: any[] = [
      {
        x: local.map((point) => point.time),
        y: local.map((point) => point.bpm),
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Local tempo',
        line: { color: COLORS.accent3, width: 1.3 },
        marker: { size: 4 },
        hovertemplate: '%{x:.1f}s · %{y:.1f} BPM<extra></extra>',
      },
    ];
    if (analysis.musical.tempo.bpm) {
      traces.push({
        x: [0, Number(analysis.metadata.duration ?? 0)],
        y: [analysis.musical.tempo.bpm, analysis.musical.tempo.bpm],
        type: 'scatter',
        mode: 'lines',
        name: 'Global tempo',
        line: { color: COLORS.success, width: 1, dash: 'dash' },
        hoverinfo: 'skip',
      });
    }
    return traces;
  }, [analysis]);

  const pitchData = useMemo(() => {
    if (!analysis?.musical.pitch.supported || !analysis.musical.pitch.contour) return [];
    const contour = analysis.musical.pitch.contour;
    return [
      {
        x: contour.times,
        y: contour.f0_hz,
        type: 'scatter',
        mode: 'lines+markers',
        name: 'F0',
        line: { color: COLORS.accent, width: 1 },
        marker: { size: 2.5, color: COLORS.accent },
        connectgaps: false,
        hovertemplate: '%{x:.2f}s · %{y:.1f} Hz<extra>F0</extra>',
      },
    ];
  }, [analysis]);

  const pitchDistribution = useMemo(() => {
    if (!analysis?.musical.pitch.pitch_distribution) return [];
    const dist = analysis.musical.pitch.pitch_distribution;
    return [
      {
        x: dist.midi_centers,
        y: dist.normalized,
        type: 'bar',
        marker: { color: COLORS.accent3 },
        hovertemplate: 'MIDI %{x}: %{y:.3f}<extra></extra>',
      },
    ];
  }, [analysis]);

  if (!files.length) {
    return (
      <div className="section-stack">
        <SectionHeader title="Musical analysis" subtitle="Key, tempo, beats, onsets and pitch." />
        <NoAnalysedFiles icon={<Music2 size={28} aria-hidden="true" />} description="Run analysis to inspect musical properties." />
      </div>
    );
  }

  return (
    <div className="section-stack">
      <SectionHeader
        title="Musical analysis"
        subtitle="Estimated key, tempo and pitch, with confidence and explicit limitations. Direct spectral evidence is shown alongside every estimate."
        actions={
          <>
            <PlotDownloadButton fileId={file?.id} fileName={file?.original_name} kind="chroma" plotName="chromagram" text="Chromagram PNG" />
            <PlotDownloadButton fileId={file?.id} fileName={file?.original_name} kind="tempo" plotName="tempo" text="Tempo PNG" />
            <PlotDownloadButton fileId={file?.id} fileName={file?.original_name} kind="pitch" plotName="pitch" text="Pitch PNG" />
          </>
        }
      />

      <AnalysisLoadState fileId={file?.id} label="musical analysis" />

      {analysis && (
        <>
          <div className="two-col">
            <Card
              title="Estimated musical key"
              subtitle={analysis.musical.key.method}
              actions={<Badge variant={analysis.musical.key.confidence_label === 'high' ? 'success' : analysis.musical.key.confidence_label === 'medium' ? 'warning' : 'error'}>{analysis.musical.key.confidence_label} confidence</Badge>}
            >
              <div className="key-hero">
                <div>
                  <span className="eyebrow">Estimated key</span>
                  <div className="key-name">{analysis.musical.key.key ?? '—'}</div>
                  <p className="muted small">{analysis.musical.key.mode ? `${analysis.musical.key.mode} mode` : 'No stable tonal centre'}</p>
                </div>
                <div className="key-confidence">
                  <ConfidenceBar value={analysis.musical.key.confidence} label="Key confidence" />
                  <span className="muted small">Profile correlation {fmt(analysis.musical.key.correlation, 3)}</span>
                </div>
              </div>
              {analysis.musical.key.alternatives?.length ? (
                <TableWrap label="Alternative key estimates">
                  <table className="data-table compact">
                    <thead><tr><th scope="col">Alternative</th><th scope="col">Correlation</th><th scope="col">Probability</th></tr></thead>
                    <tbody>
                      {analysis.musical.key.alternatives.map((alt) => (
                        <tr key={alt.key}><td>{alt.key}</td><td>{fmt(alt.correlation, 3)}</td><td>{fmt(alt.probability * 100, 1)}%</td></tr>
                      ))}
                    </tbody>
                  </table>
                </TableWrap>
              ) : null}
              <p className="muted small">{analysis.musical.key.note}</p>
            </Card>

            <Card title="Chroma distribution" subtitle="Mean chroma energy across the full file. The twelve pitch classes are direct spectral evidence.">
              <Plot title="Chroma distribution" summary={`Mean energy of the twelve pitch classes; strongest ${analysis.spectral.chroma.pitch_classes[analysis.spectral.chroma.mean_energy.indexOf(Math.max(...analysis.spectral.chroma.mean_energy))] ?? '—'}.`} data={chromaData} layout={{ height: 260, margin: { l: 44, r: 10, t: 12, b: 36 }, xaxis: { title: { text: 'Pitch class' } }, yaxis: { title: { text: 'Mean energy' } }, showlegend: false }} height={260} />
            </Card>
          </div>

          <Card title="Chromagram" subtitle="Chroma energy over time (L2-normalised per frame).">
            <Plot title="Chromagram" summary="Pitch-class energy over time (heatmap, 0 to 1)." data={chromagramData} layout={{ height: 280, margin: { l: 60, r: 12, t: 12, b: 40 }, xaxis: { title: { text: 'Time (s)' } }, yaxis: { title: { text: 'Pitch class' } }, showlegend: false }} height={280} />
          </Card>

          <div className="stat-grid">
            <Stat label="Tempo" value={fmt(analysis.musical.tempo.bpm, 1)} unit="BPM" tone="accent" hint={`${analysis.musical.tempo.confidence_label} confidence${(analysis.musical.tempo as any).periodicity !== undefined ? ` · periodicity ${fmt((analysis.musical.tempo as any).periodicity, 2)}` : ''}`} />
            <Stat label="Beat count" value={analysis.musical.tempo.beat_count ?? 0} hint={`${fmt(analysis.musical.tempo.beat_consistency ? analysis.musical.tempo.beat_consistency * 100 : null, 0)}% on grid`} />
            <Stat label="Tempo stability" value={fmt(analysis.musical.tempo.tempo_stability ? analysis.musical.tempo.tempo_stability * 100 : null, 0)} unit="%" hint={analysis.musical.tempo.stability_label} />
            <Stat label="Half-time" value={fmt(analysis.musical.tempo.half_time_bpm, 1)} unit="BPM" />
            <Stat label="Double-time" value={fmt(analysis.musical.tempo.double_time_bpm, 1)} unit="BPM" />
            <Stat label="Onsets" value={analysis.musical.rhythm.onset_count} hint={`${fmt(analysis.musical.rhythm.onset_density_per_second, 2)}/s`} />
          </div>

          <div className="two-col">
            <Card title="Tempo candidates" subtitle="Tempogram peaks; half/double interpretations are explicit.">
              <TableWrap label="Tempo candidates">
                <table className="data-table compact">
                  <thead><tr><th scope="col">BPM</th><th scope="col">Strength</th><th scope="col">Interpretation</th></tr></thead>
                  <tbody>
                    {(analysis.musical.tempo.candidates ?? []).map((candidate) => (
                      <tr key={`${candidate.bpm}-${candidate.interpretation}`}>
                        <td className="mono">{fmt(candidate.bpm, 1)}</td>
                        <td>{fmt(candidate.strength * 100, 0)}%</td>
                        <td>{candidate.interpretation}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
              <InfoNote>
                Tempo tracking can lock to half-time or double-time, especially with sparse or syncopated material. Compare the
                candidates and the local tempo trace before relying on the BPM.
              </InfoNote>
            </Card>

            <Card title="Rhythm statistics" subtitle="Detected onsets and beat-grid alignment.">
              <div className="kv-grid">
                <span>Onset interval CV</span><b>{fmt(analysis.musical.rhythm.onset_interval_cv, 3)}</b>
                <span>Rhythm consistency</span><b>{fmt(analysis.musical.rhythm.rhythm_consistency * 100, 0)}%</b>
                <span>Off-grid onsets</span><b>{fmt(analysis.musical.rhythm.off_grid_onset_fraction * 100, 1)}%</b>
                <span>Beat interval mean</span><b>{fmt(analysis.musical.tempo.beat_interval_mean_seconds, 3)} s</b>
                <span>Beat interval CV</span><b>{fmt(analysis.musical.tempo.beat_interval_cv, 3)}</b>
                <span>Method</span><b>{analysis.musical.rhythm.method}</b>
              </div>
            </Card>
          </div>

          <Card title="Tempo and beat grid" subtitle="Onset-strength envelope with detected beats, plus local tempo over time.">
            <Plot
              title="Onset strength and beat grid"
              summary={`Onset-strength envelope with ${analysis.musical.tempo.beat_count ?? 0} detected beats marked.`}
              data={beatData}
              layout={{
                height: 300,
                margin: { l: 48, r: 14, t: 18, b: 40 },
                xaxis: { title: { text: 'Time (s)' } },
                yaxis: { title: { text: 'Onset strength' } },
                shapes: beatShapes(analysis.musical.tempo.beats ?? []),
                showlegend: false,
              }}
              height={300}
            />
            <Plot
              title="Local tempo"
              summary={`Local tempo over time; global estimate ${fmt(analysis.musical.tempo.bpm, 1)} BPM.`}
              data={tempoData}
              layout={{
                height: 240,
                margin: { l: 48, r: 14, t: 18, b: 40 },
                xaxis: { title: { text: 'Time (s)' } },
                yaxis: { title: { text: 'Tempo (BPM)' } },
                showlegend: true,
              }}
              height={240}
            />
            {analysis.musical.tempo.tempo_changes?.length ? (
              <div className="finding-list">
                {analysis.musical.tempo.tempo_changes.map((change) => (
                  <div className="finding finding-warning" key={`${change.start}-${change.end}`}>
                    <Timer size={16} aria-hidden="true" />
                    <div><strong>{fmt(change.start, 1)}–{fmt(change.end, 1)} s</strong><p>{change.note} Local BPM {change.bpm_min}–{change.bpm_max}.</p></div>
                  </div>
                ))}
              </div>
            ) : <p className="muted small">No local tempo deviations above 5% were detected.</p>}
          </Card>

          <Card
            title="Pitch contour and distribution"
            subtitle={analysis.musical.pitch.method ?? 'Fundamental frequency estimate'}
            actions={<Badge variant={analysis.musical.pitch.confidence_label === 'high' ? 'success' : analysis.musical.pitch.confidence_label === 'medium' ? 'warning' : 'error'}>{analysis.musical.pitch.confidence_label ?? 'unsupported'}</Badge>}
          >
            {analysis.musical.pitch.supported ? (
              <>
                <div className="stat-grid">
                  <Stat label="Median F0" value={fmt(analysis.musical.pitch.f0_median_hz, 1)} unit="Hz" />
                  <Stat label="Pitch range" value={fmt(analysis.musical.pitch.pitch_range_semitones, 1)} unit="semitone" />
                  <Stat label="Stability" value={fmt(analysis.musical.pitch.pitch_stability_semitones_std, 2)} unit="st" hint={analysis.musical.pitch.pitch_stability_label} />
                  <Stat label="Voiced fraction" value={fmt((analysis.musical.pitch.voiced_fraction ?? 0) * 100, 0)} unit="%" />
                  <Stat label="Note transitions" value={analysis.musical.pitch.note_transitions ?? 0} />
                  <Stat label="Analysis window" value={`${fmt(analysis.musical.pitch.analyzed_start, 1)}–${fmt(analysis.musical.pitch.analyzed_end, 1)} s`} />
                </div>
                <Plot title="Pitch contour" summary={`Fundamental-frequency estimate over time; median ${fmt(analysis.musical.pitch.f0_median_hz, 1)} Hz.`} data={pitchData} layout={{ height: 280, margin: { l: 54, r: 14, t: 14, b: 40 }, xaxis: { title: { text: 'Time (s)' } }, yaxis: { title: { text: 'F0 (Hz)' }, type: 'log' }, showlegend: false }} height={280} />
                <Plot title="Pitch distribution" summary="Proportion of voiced frames per MIDI note." data={pitchDistribution} layout={{ height: 220, margin: { l: 48, r: 14, t: 14, b: 40 }, xaxis: { title: { text: 'MIDI note' } }, yaxis: { title: { text: 'Proportion' } }, showlegend: false }} height={220} />
                {((analysis.musical.pitch as any).reliability_notes ?? []).map((note: string) => (
                  <InfoNote key={note} tone="warning">{note} The contour is shown as evidence only; no reliable single-note pitch is reported.</InfoNote>
                ))}
                <p className="muted small">{analysis.musical.pitch.limitations}</p>
              </>
            ) : (
              <InfoNote tone="warning">{analysis.musical.pitch.reason ?? 'Pitch tracking was not supported for this file.'}</InfoNote>
            )}
          </Card>

          <Card title="Estimation limitations" subtitle="What this section can and cannot tell you.">
            <ul className="clean-list">
              {analysis.musical.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}
