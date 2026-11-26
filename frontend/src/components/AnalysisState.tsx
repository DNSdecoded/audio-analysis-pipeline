import type { ReactNode } from 'react';
import { Activity, RotateCcw, UploadCloud } from 'lucide-react';
import { useApp } from '../state/AppContext';
import { useWorkspace } from '../state/Workspace';
import { Card, EmptyState, InfoNote, Spinner } from './UI';

/**
 * Loading / error state for one file's analysis payload.  Renders nothing once
 * the analysis is available.  A failed request is shown with the server's
 * message and a Retry action instead of an endless "Loading…" or a blank page.
 */
export function AnalysisLoadState({ fileId, label = 'analysis' }: { fileId: string | null | undefined; label?: string }) {
  const { analyses, loadingIds, analysisErrors, retryAnalysis } = useApp();
  if (!fileId || analyses[fileId]) return null;
  const error = analysisErrors[fileId];
  if (error) {
    return (
      <Card>
        <InfoNote tone="error">
          <strong>Could not load the {label}.</strong> {error}
          <div className="inline-actions">
            <button type="button" className="btn btn-sm" onClick={() => void retryAnalysis(fileId)}>
              <RotateCcw size={14} aria-hidden="true" /> Retry
            </button>
          </div>
        </InfoNote>
      </Card>
    );
  }
  if (loadingIds[fileId]) {
    return (
      <Card>
        <div className="loading-row">
          <Spinner label={`Loading ${label}`} /> Loading {label}…
        </div>
      </Card>
    );
  }
  return null;
}

/**
 * Empty state for analysis sections: explains what is missing and offers the
 * next step (upload when the session is empty, analyse when files are waiting).
 */
export function NoAnalysedFiles({ icon, description }: { icon: ReactNode; description: string }) {
  const { session, analyze, busy } = useApp();
  const { navigate } = useWorkspace();
  const files = session?.files ?? [];
  const running = files.some((file) => file.status === 'queued' || file.status === 'analyzing');
  const pending = files.filter((file) => !file.has_analysis && file.status !== 'queued' && file.status !== 'analyzing');
  let action: ReactNode;
  if (!files.length) {
    action = (
      <button type="button" className="btn btn-primary" onClick={() => navigate('upload')}>
        <UploadCloud size={15} aria-hidden="true" /> Upload audio
      </button>
    );
  } else if (pending.length && !running) {
    action = (
      <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void analyze(pending.map((file) => file.id), false)}>
        <Activity size={15} aria-hidden="true" /> Analyze {pending.length} file(s)
      </button>
    );
  } else if (running) {
    action = (
      <span className="loading-row">
        <Spinner size={14} label="Analysis running" /> Analysis is running — results appear automatically.
      </span>
    );
  }
  return (
    <Card>
      <EmptyState icon={icon} title="No analysed files yet" description={description} action={action} />
    </Card>
  );
}
