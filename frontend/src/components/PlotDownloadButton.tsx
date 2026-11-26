import { useState } from 'react';
import { Download, Loader2 } from 'lucide-react';
import { useApp } from '../state/AppContext';
import { api, formatError } from '../lib/api';

/**
 * Server-rendered PNG export for one file's plot.  Disabled while running (no
 * duplicate downloads from a double click), reports success with the real
 * filename and failures with the server's message.  The accessible name says
 * which plot and file it exports — several "PNG" buttons on one page, plus
 * Plotly's own toolbar button, were otherwise indistinguishable.
 */
export function PlotDownloadButton({
  fileId,
  fileName,
  kind,
  text = 'PNG',
  plotName,
  log,
  start,
  end,
}: {
  fileId: string | null | undefined;
  fileName?: string;
  kind: string;
  /** Visible text; the accessible name always contains it (WCAG 2.5.3). */
  text?: string;
  plotName: string;
  log?: boolean;
  start?: number;
  end?: number;
}) {
  const { session, notify } = useApp();
  const [busy, setBusy] = useState(false);
  const run = async () => {
    if (!session || !fileId || busy) return;
    setBusy(true);
    try {
      const filename = await api.downloadPlot(session.id, fileId, kind, { log, start, end });
      notify('success', 'Plot exported', filename);
    } catch (error) {
      notify('error', 'Plot export failed', formatError(error));
    } finally {
      setBusy(false);
    }
  };
  return (
    <button
      type="button"
      className="btn btn-sm"
      onClick={() => void run()}
      disabled={!fileId || busy}
      aria-busy={busy}
      aria-label={`Download ${plotName} PNG${fileName ? ` for ${fileName}` : ''}`}
      title={`Download the server-rendered ${plotName} as PNG`}
    >
      {busy ? <Loader2 size={14} className="spin" aria-hidden="true" /> : <Download size={14} aria-hidden="true" />} {text}
    </button>
  );
}
