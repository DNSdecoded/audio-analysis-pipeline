import { useCallback, useEffect, useMemo, useState } from 'react';
import { useApp } from './AppContext';
import { useWorkspace } from './Workspace';
import type { FileRecord } from '../types';

/**
 * Shared file selection for analysis sections.
 *
 * The first selected file is the workspace's *active file*, so opening a file
 * from the dashboard, QC or comparison carries into every analysis section
 * (previously each section kept its own state initialised to files[0]).
 * Additional overlay files stay local to the section.  Analyses for every
 * selected file are loaded once, through the shared cache.
 */
export function useFileSelection(options: { multiple?: boolean; defaultCount?: number; analysedOnly?: boolean } = {}) {
  const { multiple = false, defaultCount = 1, analysedOnly = true } = options;
  const { session, analyses, ensureAnalysis } = useApp();
  const { activeFileId, setActiveFileId } = useWorkspace();
  const allFiles = session?.files ?? [];
  const files: FileRecord[] = useMemo(
    () => (analysedOnly ? allFiles.filter((file) => file.has_analysis) : allFiles),
    [allFiles, analysedOnly],
  );
  const [extras, setExtras] = useState<string[]>(() =>
    multiple ? files.filter((file) => file.id !== activeFileId).slice(0, Math.max(0, defaultCount - 1)).map((file) => file.id) : [],
  );

  const primaryId = files.some((file) => file.id === activeFileId) ? activeFileId! : files[0]?.id ?? null;

  // Keep the workspace pointing at a file that exists in this list.
  useEffect(() => {
    if (primaryId && primaryId !== activeFileId) setActiveFileId(primaryId);
  }, [primaryId, activeFileId, setActiveFileId]);

  const selected = useMemo(() => {
    if (!primaryId) return [];
    const valid = extras.filter((id) => id !== primaryId && files.some((file) => file.id === id));
    return multiple ? [primaryId, ...valid] : [primaryId];
  }, [primaryId, extras, files, multiple]);

  const setSelected = useCallback(
    (ids: string[]) => {
      if (!ids.length) return;
      setActiveFileId(ids[0]);
      setExtras(ids.slice(1));
    },
    [setActiveFileId],
  );

  useEffect(() => {
    selected.forEach((id) => {
      if (!analyses[id]) void ensureAnalysis(id);
    });
  }, [selected, analyses, ensureAnalysis]);

  const primary = files.find((file) => file.id === primaryId);
  return { files, selected, setSelected, primary, primaryId, analysis: primary ? analyses[primary.id] : undefined };
}
