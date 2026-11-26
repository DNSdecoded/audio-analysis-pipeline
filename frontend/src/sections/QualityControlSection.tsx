import { Fragment, useEffect, useMemo, useState } from 'react';
import { AudioWaveform, ChevronDown, ChevronRight, Download, Loader2, RotateCcw, Save, Search, ShieldCheck, SlidersHorizontal } from 'lucide-react';
import { useApp } from '../state/AppContext';
import { useWorkspace } from '../state/Workspace';
import { api, formatError } from '../lib/api';
import { Card, EmptyState, InfoNote, SEVERITY_DISPLAY, SectionHeader, SeverityBadge, Spinner, TableWrap, ToggleGroup } from '../components/UI';
import { NoAnalysedFiles } from '../components/AnalysisState';
import { collectFindings, formatLimit, formatMeasurement, type Finding } from '../lib/qcFindings';
import { fmt, titleCase } from '../lib/format';
import { parseNumberInput } from '../lib/inputValidation';

const SEVERITIES = ['error', 'warning', 'information', 'normal'] as const;

function FindingRow({ finding, thresholds, onJump }: { finding: Finding; thresholds?: Record<string, unknown>; onJump: (start: number, end: number) => void }) {
  const [open, setOpen] = useState(false);
  const { check } = finding;
  const positions = check.time_positions ?? [];
  const detailsId = `qc-${finding.fileId}-${check.id}`;
  return (
    <Fragment>
      <tr className={`qc-tr qc-tr-${check.severity}`}>
        <td>
          <SeverityBadge severity={check.severity} />
        </td>
        <td>
          <button
            type="button"
            className="qc-expand"
            aria-expanded={open}
            aria-controls={detailsId}
            onClick={() => setOpen((value) => !value)}
          >
            {open ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />}
            <span>
              <strong>{check.title}</strong>
              <span className="muted small"> · {titleCase(check.category)}</span>
            </span>
          </button>
          <div className="small qc-message">{check.message}</div>
        </td>
        <td className="qc-file">{finding.fileName}</td>
        <td className="num">{formatMeasurement(check.measured_value, check.measured_unit)}</td>
        <td className="num muted">{formatLimit(check, thresholds)}</td>
        <td>
          {positions.length ? (
            <div className="time-chip-row">
              {positions.slice(0, 3).map((region, index) => (
                <button
                  type="button"
                  key={`${region.start}-${index}`}
                  className="time-chip"
                  onClick={() => onJump(region.start, region.end)}
                >
                  <AudioWaveform size={12} aria-hidden="true" />
                  <span className="sr-only">Open {finding.fileName} waveform at </span>
                  {fmt(region.start, 2)}–{fmt(region.end, 2)} s
                </button>
              ))}
              {positions.length > 3 && <span className="muted small">+{positions.length - 3}</span>}
            </div>
          ) : (
            <span className="muted small">Whole file</span>
          )}
        </td>
      </tr>
      {open && (
        <tr className="qc-details-row" id={detailsId}>
          <td />
          <td colSpan={5}>
            <div className="qc-row-details">
              <div>
                <span className="field-label">Why this matters</span>
                <p>{check.explanation}</p>
              </div>
              <div>
                <span className="field-label">Recommended action</span>
                <p>{check.recommendation}</p>
              </div>
              <div className="qc-row-meta">
                <span>Rule: <code>{check.id}</code></span>
                {check.standard && <span>Standard: {check.standard}</span>}
                <span>Confidence: {check.confidence}</span>
              </div>
              {positions.length > 3 && (
                <div>
                  <span className="field-label">All {positions.length} time positions</span>
                  <div className="time-chip-row wrap">
                    {positions.map((region, index) => (
                      <button type="button" key={`all-${region.start}-${index}`} className="time-chip" onClick={() => onJump(region.start, region.end)}>
                        <AudioWaveform size={12} aria-hidden="true" />
                        <span className="sr-only">Open {finding.fileName} waveform at </span>
                        {fmt(region.start, 2)}–{fmt(region.end, 2)} s
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </Fragment>
  );
}

export default function QualityControlSection() {
  const { session, analyses, ensureAnalysis, loadingIds, analysisErrors, retryAnalysis, notify, recomputeQc, busy, appSettings } = useApp();
  const { navigate, activeFileId, route } = useWorkspace();
  const files = useMemo(() => (session?.files ?? []).filter((file) => file.has_analysis), [session?.files]);
  // Opened for one file (active-file bar, Files → "QC findings"): start scoped to it.
  const [scope, setScope] = useState<'all' | 'active'>(() => (route.file ? 'active' : 'all'));
  const [exporting, setExporting] = useState(false);
  const [activeSeverities, setActiveSeverities] = useState<string[]>(['error', 'warning', 'information']);
  const [query, setQuery] = useState('');
  const [thresholds, setThresholds] = useState<Record<string, number | number[]>>({});
  const [editorOpen, setEditorOpen] = useState(false);

  const activeFile = files.find((file) => file.id === activeFileId) ?? files[0];
  const scopedFiles = useMemo(() => (scope === 'all' ? files : activeFile ? [activeFile] : []), [scope, files, activeFile]);

  useEffect(() => {
    scopedFiles.forEach((file) => {
      if (!analyses[file.id]) void ensureAnalysis(file.id);
    });
  }, [scopedFiles, analyses, ensureAnalysis]);

  // Session polling replaces the settings object every 1.4 s while jobs run;
  // depend on the *values* so an edit in progress is not overwritten.
  const savedThresholds = JSON.stringify(session?.settings?.qc_thresholds ?? appSettings?.qc_thresholds ?? {});
  useEffect(() => {
    setThresholds(JSON.parse(savedThresholds));
  }, [savedThresholds]);

  const findings = useMemo(
    () => collectFindings(scopedFiles, analyses, activeSeverities, query),
    [scopedFiles, analyses, activeSeverities, query],
  );
  const counts = useMemo(() => {
    const all = collectFindings(scopedFiles, analyses, [...SEVERITIES]);
    return Object.fromEntries(SEVERITIES.map((s) => [s, all.filter((f) => f.check.severity === s).length])) as Record<string, number>;
  }, [scopedFiles, analyses]);
  const loading = scopedFiles.some((file) => !analyses[file.id] && loadingIds[file.id]);
  // Files in scope whose QC is not available yet: never drop them silently.
  const missing = scopedFiles.filter((file) => !analyses[file.id]);
  const included = scopedFiles.length - missing.length;
  const anyQc = analyses[activeFile?.id ?? '']?.qc ?? Object.values(analyses).find((a) => a?.qc)?.qc;
  const schema: any[] = anyQc?.threshold_schema ?? appSettings?.qc_threshold_schema ?? [];

  const toggleSeverity = (severity: string) =>
    setActiveSeverities((current) => (current.includes(severity) ? current.filter((v) => v !== severity) : [...current, severity]));

  const updateThreshold = (key: string, value: string) => {
    // An empty field is invalid (NaN), not a silent 0 that would be saved.
    setThresholds((current) => ({ ...current, [key]: parseNumberInput(value) }));
  };

  const invalidThresholds = schema.filter((field) => {
    const value = thresholds[field.key];
    return typeof value !== 'number' || !Number.isFinite(value) || value < field.min || value > field.max;
  });

  const saveAndRecompute = async () => {
    if (invalidThresholds.length) {
      notify('warning', 'Fix the highlighted thresholds', invalidThresholds.map((f) => f.label).join(', '));
      return;
    }
    const cleaned: Record<string, unknown> = {};
    schema.forEach((field) => {
      const value = thresholds[field.key];
      if (typeof value === 'number' && Number.isFinite(value)) cleaned[field.key] = value;
    });
    await recomputeQc(cleaned);
  };

  const resetDefaults = () => {
    if (appSettings?.qc_thresholds) {
      setThresholds({ ...appSettings.qc_thresholds });
      notify('info', 'Defaults loaded', 'Save and recompute to apply the default thresholds.');
    }
  };

  const exportQc = async () => {
    if (!session || exporting) return;
    setExporting(true);
    try {
      const filename = await api.downloadReport(session.id, { format: 'qc-csv', file_ids: scopedFiles.map((f) => f.id), include_comparison: false });
      notify('success', 'QC findings exported', filename);
    } catch (error) {
      notify('error', 'Export failed', formatError(error));
    } finally {
      setExporting(false);
    }
  };

  if (!files.length) {
    return (
      <div className="section-stack">
        <SectionHeader title="Quality control" subtitle="Measured checks with explicit limits, time positions and recommendations." />
        <NoAnalysedFiles icon={<ShieldCheck size={28} aria-hidden="true" />} description="Run analysis to generate quality-control findings." />
      </div>
    );
  }

  return (
    <div className="section-stack">
      <SectionHeader
        title="Quality control"
        subtitle="Every finding comes from a measured value compared with an explicit, configurable limit. Select a time position to open it in the waveform."
        actions={
          <>
            <button className="btn btn-sm" onClick={() => setEditorOpen((value) => !value)} aria-expanded={editorOpen}>
              <SlidersHorizontal size={14} aria-hidden="true" /> Thresholds
            </button>
            <button className="btn btn-sm" onClick={() => void exportQc()} disabled={exporting} aria-busy={exporting} title={`Export every QC check for ${scope === 'all' ? 'all files' : 'the active file'} (all statuses)`}>
              {exporting ? <Loader2 size={14} className="spin" aria-hidden="true" /> : <Download size={14} aria-hidden="true" />} Export QC CSV
            </button>
          </>
        }
      />

      <div className="qc-summary" role="group" aria-label="Findings by status">
        {SEVERITIES.map((severity) => (
          <button
            key={severity}
            type="button"
            className={`qc-summary-tile qc-summary-${severity} ${activeSeverities.includes(severity) ? 'active' : ''}`}
            aria-pressed={activeSeverities.includes(severity)}
            onClick={() => toggleSeverity(severity)}
          >
            <span className="qc-summary-count">{counts[severity] ?? 0}</span>
            <span className="qc-summary-label">
              <SeverityBadge severity={severity} />
            </span>
          </button>
        ))}
      </div>

      <Card>
        <div className="toolbar-grid">
          <ToggleGroup
            label="Files in scope"
            value={scope}
            onChange={setScope}
            options={[
              { value: 'all', label: `All files (${files.length})` },
              { value: 'active', label: `Active file${activeFile ? `: ${activeFile.original_name}` : ''}` },
            ]}
          />
          <label className="search-field">
            <Search size={14} aria-hidden="true" />
            <span className="sr-only">Filter findings</span>
            <input type="search" placeholder="Filter by issue or file" value={query} onChange={(event) => setQuery(event.target.value)} />
          </label>
        </div>
        {missing.length > 0 && (
          <InfoNote tone={missing.some((file) => analysisErrors[file.id]) ? 'error' : 'info'}>
            <strong>
              Findings from {included} of {scopedFiles.length} file(s).
            </strong>{' '}
            {missing.map((file, index) => (
              <span key={file.id}>
                {index > 0 && ' · '}
                {file.original_name}:{' '}
                {analysisErrors[file.id] ? (
                  <>
                    could not be loaded ({analysisErrors[file.id]}){' '}
                    <button type="button" className="btn btn-sm" onClick={() => void retryAnalysis(file.id)}>
                      <RotateCcw size={13} aria-hidden="true" /> Retry
                    </button>
                  </>
                ) : (
                  'loading…'
                )}
              </span>
            ))}
          </InfoNote>
        )}
        <p className="muted small">
          Showing {findings.length} finding(s) from {included} file(s). Toggle the status tiles above to include or hide Pass, Info, Warning and Critical
          results. Critical = a configured error limit was crossed.
        </p>
      </Card>

      {editorOpen && (
        <Card
          title="QC thresholds"
          subtitle="Stored with the session and applied when QC is recomputed. Recomputing reclassifies existing measurements; it does not re-run the audio analysis."
          actions={
            <>
              <button className="btn btn-sm" onClick={resetDefaults}>
                <RotateCcw size={14} aria-hidden="true" /> Defaults
              </button>
              <button className="btn btn-sm btn-primary" onClick={() => void saveAndRecompute()} disabled={busy || invalidThresholds.length > 0}>
                <Save size={14} aria-hidden="true" /> Save and recompute
              </button>
            </>
          }
        >
          <div className="threshold-grid">
            {schema.map((field) => {
              const current = thresholds[field.key];
              const invalid = invalidThresholds.includes(field);
              const errorId = `thr-${field.key}-err`;
              return (
                <label key={field.key} className={`threshold-field ${invalid ? 'invalid' : ''}`}>
                  <span>{field.label}</span>
                  <div className="threshold-input">
                    <input
                      type="number"
                      min={field.min}
                      max={field.max}
                      step={field.step}
                      value={typeof current === 'number' && Number.isFinite(current) ? current : ''}
                      aria-invalid={invalid}
                      aria-describedby={errorId}
                      onChange={(event) => updateThreshold(field.key, event.target.value)}
                    />
                    {field.unit && <span className="threshold-unit">{field.unit}</span>}
                  </div>
                  <span id={errorId} className={invalid ? 'error-text small' : 'muted small'}>
                    {invalid ? `Enter a value from ${field.min} to ${field.max}` : `Allowed ${field.min}–${field.max}`}
                  </span>
                </label>
              );
            })}
          </div>
        </Card>
      )}

      <Card title="Findings" subtitle="Select an issue name to see why it matters, the recommended action and the rule that produced it.">
        {loading && (
          <div className="loading-row">
            <Spinner label="Loading QC results" /> Loading QC results…
          </div>
        )}
        {findings.length ? (
          <TableWrap label="Quality-control findings">
            <table className="data-table qc-table">
              <thead>
                <tr>
                  <th scope="col">Status</th>
                  <th scope="col">Issue</th>
                  <th scope="col">File</th>
                  <th scope="col">Measured</th>
                  <th scope="col">Limit</th>
                  <th scope="col">Time position</th>
                </tr>
              </thead>
              <tbody>
                {findings.map((finding) => (
                  <FindingRow
                    key={`${finding.fileId}-${finding.check.id}`}
                    finding={finding}
                    thresholds={analyses[finding.fileId]?.qc?.thresholds as Record<string, unknown> | undefined}
                    onJump={(start, end) => navigate('waveform', { file: finding.fileId, start, end, label: finding.check.title })}
                  />
                ))}
              </tbody>
            </table>
          </TableWrap>
        ) : (
          !loading && <EmptyState title="No findings match" description="Change the status tiles, scope or filter text to see more results." />
        )}
      </Card>

      {anyQc && (
        <Card title="Thresholds in effect" subtitle="Values used for the current QC pass.">
          <TableWrap label="Thresholds in effect">
            <table className="data-table compact">
              <thead>
                <tr>
                  <th scope="col">Threshold</th>
                  <th scope="col">Value</th>
                  <th scope="col">Unit</th>
                </tr>
              </thead>
              <tbody>
                {schema.map((field) => (
                  <tr key={field.key}>
                    <td>{field.label}</td>
                    <td className="num">{fmt(anyQc.thresholds?.[field.key], String(anyQc.thresholds?.[field.key] ?? '').includes('.') ? 3 : 0)}</td>
                    <td className="muted">{field.unit}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
          <div className="legend-note">
            {SEVERITIES.map((severity) => (
              <span key={severity}>
                <SeverityBadge severity={severity} />{' '}
                {severity === 'normal'
                  ? 'Within configured limits'
                  : severity === 'information'
                    ? 'Observation, not a defect'
                    : severity === 'warning'
                      ? 'Warning limit crossed — review'
                      : `Error limit crossed (${SEVERITY_DISPLAY.error.label})`}
              </span>
            ))}
          </div>
        </Card>
      )}
      <InfoNote tone="info">
        QC never modifies audio. Information findings are context, not defects; whether a warning matters depends on your delivery
        target.
      </InfoNote>
    </div>
  );
}
