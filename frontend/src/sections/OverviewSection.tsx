import { useMemo } from 'react';
import { ListChecks } from 'lucide-react';
import { useFileSelection } from '../state/useFileSelection';
import { Card, InfoNote, MetricCard, SectionHeader } from '../components/UI';
import { AnalysisLoadState, NoAnalysedFiles } from '../components/AnalysisState';
import { buildMetricGroups, formatMetricValue } from '../lib/metrics';
import { fmtDate } from '../lib/format';

export default function OverviewSection() {
  const { files, primary, analysis } = useFileSelection();
  const groups = useMemo(() => (analysis ? buildMetricGroups(analysis) : []), [analysis]);

  if (!files.length) {
    return (
      <div className="section-stack">
        <SectionHeader title="File overview" subtitle="All measurements for one file, with status and confidence." />
        <NoAnalysedFiles icon={<ListChecks size={28} aria-hidden="true" />} description="Upload audio and run the analysis to see its measurements here." />
      </div>
    );
  }

  return (
    <div className="section-stack">
      <SectionHeader
        title="File overview"
        subtitle={
          analysis
            ? `${primary?.original_name} · analysed ${fmtDate(analysis.analyzed_at)}. “Measured” values are direct measurements; “Estimate” values come from algorithms and show their confidence.`
            : `${primary?.original_name ?? 'File'} · measurements not loaded yet.`
        }
      />
      <AnalysisLoadState fileId={primary?.id} label="measurements" />
      {groups.map((group) => (
        <Card key={group.title} title={group.title} subtitle={group.description}>
          {group.note ? (
            <InfoNote tone="info">{group.note}</InfoNote>
          ) : (
            <div className="metric-grid">
              {group.metrics.map((metric) => (
                <MetricCard
                  key={metric.key}
                  label={metric.label}
                  value={formatMetricValue(metric)}
                  unit={metric.unit}
                  status={metric.status}
                  kind={metric.kind}
                  confidence={metric.confidence}
                  explanation={metric.explanation}
                  hint={metric.hint}
                />
              ))}
            </div>
          )}
        </Card>
      ))}
      {analysis && (
        <p className="muted small">
          Status comes from the configured quality-control rule for each measurement (Pass / Info / Warning / Critical). Measurements
          without a QC rule show no status. Thresholds can be changed in Settings or Quality control.
        </p>
      )}
    </div>
  );
}
