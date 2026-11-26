import { useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  FileAudio,
  Loader2,
  Replace,
  Trash2,
  UploadCloud,
  X,
} from 'lucide-react';
import { useApp } from '../state/AppContext';
import { useConfirm } from '../components/ConfirmDialog';
import { Badge, Card, EmptyState, InfoNote, ProgressBar, SectionHeader, TableWrap } from '../components/UI';
import { fmt, fmtBytes, fmtDuration, fmtHz, statusClass, titleCase } from '../lib/format';
import { precheckUploads } from '../lib/inputValidation';

const ACCEPT = '.wav,.wave,.mp3,.flac,.aac,.ogg,.oga,.aiff,.aif,.aifc,.m4a,.mp4';
const DEFAULT_EXTENSIONS = ACCEPT.split(',');

export default function UploadSection({ navigate }: { navigate: (section: string) => void }) {
  const { session, upload, uploadProgress, cancelUpload, removeFile, replaceFile, analyze, busy, notify, appSettings } = useApp();
  const confirm = useConfirm();
  const [dragging, setDragging] = useState(false);
  const [lastResult, setLastResult] = useState<{ files: any[]; errors: any[] } | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const replaceRef = useRef<HTMLInputElement | null>(null);
  const [replaceTarget, setReplaceTarget] = useState<string | null>(null);

  const files = session?.files ?? [];
  const canAnalyze = files.some((file) => !file.has_analysis && file.status !== 'queued' && file.status !== 'analyzing');

  const handleFiles = async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return;
    if (uploadProgress !== null) {
      notify('warning', 'Upload already in progress', 'Wait for the current upload to finish, or cancel it, before adding more files.');
      return;
    }
    // Checks that need no upload: type, size, empty files and duplicates of
    // files already in the session.  The server still validates content.
    const check = precheckUploads(Array.from(fileList), files, {
      extensions: appSettings?.supported_extensions ?? DEFAULT_EXTENSIONS,
      maxBytes: appSettings ? appSettings.limits.max_file_size_mb * 1024 * 1024 : undefined,
    });
    let toSend = check.accepted;
    if (check.duplicates.length) {
      const names = check.duplicates.map((file) => file.name);
      const uploadAnyway = await confirm({
        title: `${names.length} file(s) already in this session`,
        message: (
          <>
            <p>A file with the same name and size is already uploaded:</p>
            <ul className="clean-list">{names.map((name, index) => <li key={`${name}-${index}`}>{name}</li>)}</ul>
            <p className="muted small">Uploading again creates a second, independent copy with its own analysis.</p>
          </>
        ),
        confirmLabel: 'Upload duplicates too',
        cancelLabel: 'Skip duplicates',
      });
      if (uploadAnyway) toSend = [...toSend, ...check.duplicates];
    }
    if (!toSend.length) {
      setLastResult({ files: [], errors: check.rejected });
      if (check.rejected.length) notify('warning', `${check.rejected.length} file(s) rejected`, 'See “Rejected files” for the reason.');
      return;
    }
    const result = await upload(toSend);
    if (result) setLastResult({ files: result.files ?? [], errors: [...check.rejected, ...(result.errors ?? [])] });
    else if (check.rejected.length) setLastResult({ files: [], errors: check.rejected });
  };

  const confirmRemove = async (fileId: string, name: string) => {
    const ok = await confirm({
      title: `Remove ${name}?`,
      message: 'The uploaded copy and its analysis results are deleted from this session. Other files are not affected. This cannot be undone.',
      confirmLabel: 'Remove file',
      destructive: true,
    });
    if (ok) await removeFile(fileId);
  };

  const triggerReplace = (fileId: string) => {
    setReplaceTarget(fileId);
    replaceRef.current?.click();
  };

  return (
    <div className="section-stack">
      <SectionHeader
        title="Multi-file upload"
        subtitle="Add two or more audio files, validate them, then run independent analyses in one session. Originals are preserved."
        actions={
          files.length > 0 ? (
            <button className="btn btn-primary" onClick={() => navigate('files')}>
              Review files
            </button>
          ) : undefined
        }
      />

      <div
        className={`dropzone ${dragging ? 'dragging' : ''}`}
        onDragOver={(event) => {
          event.preventDefault();
          if (!dragging) setDragging(true);
        }}
        onDragLeave={(event) => {
          // dragleave also fires when the pointer moves onto a child element;
          // only clear the highlight when it really leaves the drop zone.
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
        }}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          void handleFiles(event.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        aria-describedby="dropzone-help"
        aria-busy={uploadProgress !== null}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            inputRef.current?.click();
          }
        }}
      >
        <div className="dropzone-icon">
          {uploadProgress === null ? <UploadCloud size={30} aria-hidden="true" /> : <Loader2 size={30} className="spin" aria-hidden="true" />}
        </div>
        <h2>{uploadProgress === null ? 'Drop audio files here' : 'Uploading and validating…'}</h2>
        <p id="dropzone-help">or press Enter to choose files · WAV, MP3, FLAC, AAC, OGG and AIFF · batch upload supported · originals are never modified</p>
        <div className="dropzone-formats">
          {['WAV', 'MP3', 'FLAC', 'AAC', 'OGG', 'AIFF'].map((format) => (
            <span key={format}>{format}</span>
          ))}
        </div>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          onChange={(event) => {
            void handleFiles(event.target.files);
            event.target.value = '';
          }}
        />
        <input
          ref={replaceRef}
          type="file"
          accept={ACCEPT}
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file && replaceTarget) {
              void replaceFile(replaceTarget, file).then((replaced) => {
                if (replaced) notify('success', 'Replacement complete', 'The new file was validated, then the previous file was removed.');
              });
            }
            setReplaceTarget(null);
            event.target.value = '';
          }}
        />
      </div>

      {uploadProgress !== null && (
        <div className="upload-progress-panel" role="group" aria-label="Upload in progress">
          <ProgressBar value={uploadProgress} label="Upload progress" />
          <span className="muted small" aria-live="polite">
            {uploadProgress >= 100 ? 'Transfer complete — the server is validating the files…' : 'Transferring files…'}
          </span>
          <button type="button" className="btn btn-sm" onClick={cancelUpload}>
            <X size={14} aria-hidden="true" /> Cancel upload
          </button>
        </div>
      )}

      {lastResult?.errors?.length ? (
        <Card title="Rejected files" subtitle="These files did not pass validation and were not stored.">
          <div className="finding-list">
            {lastResult.errors.map((error: any, index: number) => (
              <div key={`${error.file_name}-${index}`} className="finding finding-error">
                <AlertTriangle size={17} aria-hidden="true" />
                <div>
                  <strong>{error.file_name}</strong>
                  <ul>
                    {(error.errors ?? []).map((message: string) => (
                      <li key={message}>{message}</li>
                    ))}
                  </ul>
                  {(error.warnings ?? []).length > 0 && (
                    <p className="muted small">Warnings: {error.warnings.join(' · ')}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      {lastResult?.files?.length ? (
        <Card title="Validation passed" subtitle="Technical metadata was read from each file. No audio was modified.">
          <div className="validation-grid">
            {lastResult.files.map((file: any) => (
              <div key={file.id} className="validation-card">
                <div className="validation-card-head">
                  <CheckCircle2 size={18} className="success-text" aria-hidden="true" />
                  <strong>{file.original_name}</strong>
                </div>
                <div className="meta-grid">
                  <span>Format</span><b>{file.metadata?.format ?? '—'}</b>
                  <span>Duration</span><b>{fmtDuration(file.metadata?.duration)}</b>
                  <span>Sample rate</span><b>{fmtHz(file.metadata?.sample_rate)}</b>
                  <span>Bit depth</span><b>{file.metadata?.bit_depth ?? 'n/a (lossy)'}</b>
                  <span>Channels</span><b>{file.metadata?.channels_label ?? file.metadata?.channels}</b>
                  <span>Size</span><b>{fmtBytes(file.size_bytes)}</b>
                </div>
                {(file.validation?.warnings ?? []).length > 0 && (
                  <p className="muted small">Warnings: {file.validation.warnings.join(' · ')}</p>
                )}
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      <Card
        title="Session files"
        subtitle={`${files.length} file(s) in this session. Each file has a unique identifier and independent analysis state.`}
        actions={
          files.length > 0 ? (
            <button className="btn btn-primary" onClick={() => void analyze(undefined, false)} disabled={busy || !canAnalyze} title={canAnalyze ? 'Analyse files that have not been analysed yet' : 'All files are already analysed — use Re-analyse on a file to run it again'}>
              <Activity size={15} aria-hidden="true" /> Analyze all
            </button>
          ) : undefined
        }
      >
        {files.length === 0 ? (
          <EmptyState
            icon={<FileAudio size={26} aria-hidden="true" />}
            title="No files uploaded yet"
            description="Add at least two files to unlock comparison. You can upload more at any time."
          />
        ) : (
          <TableWrap label="Session files">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">File</th>
                  <th scope="col">Format</th>
                  <th scope="col">Duration</th>
                  <th scope="col">Sample rate</th>
                  <th scope="col">Bit depth</th>
                  <th scope="col">Channels</th>
                  <th scope="col">Size</th>
                  <th scope="col">Status</th>
                  <th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {files.map((file) => (
                  <tr key={file.id}>
                    <td>
                      <div className="file-name-cell">
                        <span className={`status-dot ${statusClass(file.status)}`} aria-hidden="true" />
                        <div>
                          <strong>{file.original_name}</strong>
                          <span className="muted small mono">{file.id.slice(0, 16)}…</span>
                        </div>
                      </div>
                    </td>
                    <td>{file.metadata?.format ?? '—'}</td>
                    <td>{fmtDuration(file.metadata?.duration)}</td>
                    <td className="num">{fmtHz(file.metadata?.sample_rate)}</td>
                    <td>{file.metadata?.bit_depth ?? (file.metadata?.is_lossy ? 'lossy' : '—')}</td>
                    <td>{file.metadata?.channels ?? '—'}</td>
                    <td>{fmtBytes(file.size_bytes)}</td>
                    <td>
                      <div className="status-cell">
                        <Badge variant={file.status === 'complete' ? 'success' : file.status === 'error' ? 'error' : file.status === 'analyzing' || file.status === 'queued' ? 'info' : 'neutral'}>
                          {file.status === 'analyzing' ? `${file.stage} ${fmt(file.progress, 0)}%` : titleCase(file.status)}
                        </Badge>
                        {file.error && <span className="small error-text">{file.error}</span>}
                      </div>
                    </td>
                    <td>
                      <div className="row-actions">
                        {!file.has_analysis && file.status !== 'analyzing' && file.status !== 'queued' && (
                          <button
                            className="icon-button"
                            title="Analyze this file"
                            aria-label={`Analyze ${file.original_name}`}
                            onClick={() => void analyze([file.id], true)}
                            disabled={busy}
                          >
                            <Activity size={15} aria-hidden="true" />
                          </button>
                        )}
                        <button
                          className="icon-button"
                          title="Replace file"
                          aria-label={`Replace ${file.original_name}`}
                          onClick={() => triggerReplace(file.id)}
                          disabled={uploadProgress !== null}
                        >
                          <Replace size={15} aria-hidden="true" />
                        </button>
                        <button
                          className="icon-button danger"
                          title="Remove file"
                          aria-label={`Remove ${file.original_name}`}
                          onClick={() => void confirmRemove(file.id, file.original_name)}
                        >
                          <Trash2 size={15} aria-hidden="true" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Card>

      <InfoNote>
        Files are validated against their actual container signature, not just the extension. Damaged or incomplete files are
        rejected before analysis. Original uploads are stored read-only and are never modified by gain, EQ, alignment or any
        other operation.
      </InfoNote>
    </div>
  );
}
