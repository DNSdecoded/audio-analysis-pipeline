import { ChevronLeft, ChevronRight, FileAudio } from 'lucide-react';
import { useApp } from '../state/AppContext';
import { useWorkspace } from '../state/Workspace';
import { fmtDuration } from '../lib/format';
import { SeverityBadge } from './UI';

function channelLabel(channels: number | undefined): string {
  if (!channels) return '—';
  return channels === 1 ? 'Mono' : channels === 2 ? 'Stereo' : `${channels} ch`;
}

/**
 * Persistent "which file am I looking at" bar for analysis sections.  The
 * selection is the workspace's active file, shared by every section.
 */
export function ActiveFileBar() {
  const { session } = useApp();
  const { activeFileId, setActiveFileId, navigate } = useWorkspace();
  const files = (session?.files ?? []).filter((file) => file.has_analysis);
  if (!files.length) return null;
  const index = Math.max(0, files.findIndex((file) => file.id === activeFileId));
  const file = files[index];
  const meta = file.metadata ?? {};
  const qc = file.analysis_summary?.qc_overall;
  const step = (delta: number) => setActiveFileId(files[(index + delta + files.length) % files.length].id);

  return (
    <div className="active-file-bar" role="region" aria-label="Current file context">
      <FileAudio size={16} aria-hidden="true" className="active-file-icon" />
      <label className="active-file-select">
        <span className="sr-only">Active file</span>
        <select value={file.id} onChange={(event) => setActiveFileId(event.target.value)}>
          {files.map((item) => (
            <option key={item.id} value={item.id}>
              {item.original_name}
            </option>
          ))}
        </select>
      </label>
      <div className="active-file-meta" aria-label="File properties">
        <span>{meta.format ?? '—'}</span>
        <span>{meta.sample_rate ? `${Number(meta.sample_rate).toLocaleString()} Hz` : '—'}</span>
        {meta.bit_depth ? <span>{meta.bit_depth}-bit</span> : null}
        <span>{channelLabel(meta.channels)}</span>
        <span>{fmtDuration(meta.duration)}</span>
      </div>
      {qc && (
        <button className="active-file-qc" onClick={() => navigate('qc', { file: file.id })} title="Open quality-control findings">
          <span className="sr-only">QC result:</span>
          <SeverityBadge severity={qc} />
        </button>
      )}
      {files.length > 1 && (
        <div className="active-file-steps">
          <button className="icon-button" onClick={() => step(-1)} aria-label="Previous file" title="Previous file">
            <ChevronLeft size={16} aria-hidden="true" />
          </button>
          <span className="muted small" aria-hidden="true">
            {index + 1}/{files.length}
          </span>
          <button className="icon-button" onClick={() => step(1)} aria-label="Next file" title="Next file">
            <ChevronRight size={16} aria-hidden="true" />
          </button>
        </div>
      )}
    </div>
  );
}
