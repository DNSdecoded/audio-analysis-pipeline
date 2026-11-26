import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { api, formatError, UploadCancelledError } from '../lib/api';
import type { Analysis, AppSettings, Overview, Session } from '../types';
import { ToastStack, type ToastMessage } from '../components/Toast';
import { staleAnalysisIds } from '../lib/analysisLogic';
import { forgetSession, readRecentSessions, rememberSession, type RecentSessionRef } from '../lib/recentSessions';

interface AppContextValue {
  session: Session | null;
  overview: Overview | null;
  analyses: Record<string, Analysis>;
  loadingIds: Record<string, boolean>;
  /** Files whose analysis payload could not be loaded (message per file id). */
  analysisErrors: Record<string, string>;
  /** Retry loading an analysis payload after a failure. */
  retryAnalysis: (fileId: string) => Promise<Analysis | null>;
  appSettings: AppSettings | null;
  uploadProgress: number | null;
  busy: boolean;
  notify: (type: ToastMessage['type'], title: string, message?: string) => void;
  refreshSession: () => Promise<Session | null>;
  refreshOverview: () => Promise<void>;
  ensureAnalysis: (fileId: string) => Promise<Analysis | null>;
  analyze: (fileIds?: string[], force?: boolean) => Promise<void>;
  upload: (files: File[]) => Promise<{ files: any[]; errors: any[] } | null>;
  /** Abort the upload in progress (no-op when idle). */
  cancelUpload: () => void;
  removeFile: (fileId: string) => Promise<void>;
  replaceFile: (fileId: string, file: File) => Promise<boolean>;
  /** Resolves true when the settings were stored on the server. */
  saveSettings: (settings: Record<string, unknown>, recompute?: boolean) => Promise<boolean>;
  recomputeQc: (thresholds?: Record<string, unknown>) => Promise<void>;
  resetSession: () => Promise<void>;
  /** Start a new empty session; the current one is kept and stays in the recent list. */
  newSession: () => Promise<void>;
  /** Reopen a session this browser opened before. */
  openSession: (sessionId: string) => Promise<boolean>;
  recentSessions: RecentSessionRef[];
  forgetRecentSession: (sessionId: string) => void;
}

const AppContext = createContext<AppContextValue | null>(null);
const SESSION_KEY = 'aap_session_id';

export function AppProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [analyses, setAnalyses] = useState<Record<string, Analysis>>({});
  const [loadingIds, setLoadingIds] = useState<Record<string, boolean>>({});
  const [analysisErrors, setAnalysisErrors] = useState<Record<string, string>>({});
  const analysisErrorsRef = useRef<Record<string, string>>({});
  analysisErrorsRef.current = analysisErrors;
  const [appSettings, setAppSettings] = useState<AppSettings | null>(null);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const [recentSessions, setRecentSessions] = useState<RecentSessionRef[]>(() => readRecentSessions());
  const sessionIdRef = useRef<string | null>(null);
  const sessionRef = useRef<Session | null>(null);
  sessionRef.current = session;
  const pendingAnalysis = useRef<Record<string, Promise<Analysis | null>>>({});
  const initializing = useRef(false);

  const notify = useCallback((type: ToastMessage['type'], title: string, message?: string) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    setToasts((current) => [...current.slice(-4), { id, type, title, message }]);
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const refreshOverview = useCallback(async () => {
    const id = sessionIdRef.current;
    if (!id) return;
    try {
      const data = await api.getOverview(id);
      setOverview(data);
    } catch (error) {
      if (import.meta.env.DEV) console.warn('Overview refresh failed', error);
    }
  }, []);

  const refreshSession = useCallback(async () => {
    const id = sessionIdRef.current;
    if (!id) return null;
    try {
      const data = await api.getSession(id);
      setSession(data);
      return data;
    } catch (error) {
      notify('error', 'Session unavailable', formatError(error));
      return null;
    }
  }, [notify]);

  const ensureAnalysis = useCallback(async (fileId: string): Promise<Analysis | null> => {
    const id = sessionIdRef.current;
    if (!id) return null;
    if (analyses[fileId]) return analyses[fileId];
    // A failed load is shown with a Retry action; effects that call this on
    // every render must not hammer the server (or stack error toasts).
    if (analysisErrorsRef.current[fileId]) return null;
    const pending = pendingAnalysis.current[fileId];
    if (pending) return pending;
    setLoadingIds((current) => ({ ...current, [fileId]: true }));
    const promise = api
      .getAnalysis(id, fileId)
      .then((analysis) => {
        // Do not cache a result that is already superseded (a re-analysis
        // finished while this request was in flight).
        const record = sessionRef.current?.files.find((file) => file.id === fileId);
        if (!record?.analyzed_at || record.analyzed_at === analysis.analyzed_at) {
          setAnalyses((current) => ({ ...current, [fileId]: analysis }));
        }
        return analysis;
      })
      .catch((error) => {
        const message = formatError(error);
        analysisErrorsRef.current = { ...analysisErrorsRef.current, [fileId]: message };
        setAnalysisErrors((current) => ({ ...current, [fileId]: message }));
        notify('error', 'Could not load analysis', message);
        return null;
      })
      .finally(() => {
        setLoadingIds((current) => {
          const next = { ...current };
          delete next[fileId];
          return next;
        });
        delete pendingAnalysis.current[fileId];
      });
    pendingAnalysis.current[fileId] = promise;
    return promise;
  }, [analyses, notify]);

  const retryAnalysis = useCallback(
    (fileId: string) => {
      const next = { ...analysisErrorsRef.current };
      delete next[fileId];
      analysisErrorsRef.current = next;
      setAnalysisErrors(next);
      return ensureAnalysis(fileId);
    },
    [ensureAnalysis],
  );

  const initialize = useCallback(async () => {
    if (initializing.current) return;
    initializing.current = true;
    try {
      const stored = localStorage.getItem(SESSION_KEY);
      let active: Session | null = null;
      if (stored) {
        try {
          active = await api.getSession(stored);
        } catch {
          active = null;
        }
      }
      if (!active) {
        active = await api.createSession('Audio analysis session');
        localStorage.setItem(SESSION_KEY, active.id);
      }
      sessionIdRef.current = active.id;
      setSession(active);
      setRecentSessions(rememberSession(active.id));
      void refreshOverview();
    } catch (error) {
      notify('error', 'Cannot reach the analysis server', formatError(error));
    } finally {
      initializing.current = false;
    }
  }, [notify, refreshOverview]);

  useEffect(() => {
    void initialize();
    api
      .getAppSettings()
      .then(setAppSettings)
      .catch(() => undefined);
  }, [initialize]);

  // Invalidate cached analyses whose file was removed, lost its analysis, or
  // was re-analysed (the session record carries the current analyzed_at).
  useEffect(() => {
    if (!session) return;
    // A load error belongs to one analysis run; forget it once the file is
    // removed or re-analysed so the new result is fetched.
    setAnalysisErrors((current) => {
      const keep = Object.fromEntries(
        Object.entries(current).filter(([fileId]) =>
          session.files.some((file) => file.id === fileId && file.has_analysis && file.status !== 'analyzing' && file.status !== 'queued'),
        ),
      );
      if (Object.keys(keep).length === Object.keys(current).length) return current;
      analysisErrorsRef.current = keep;
      return keep;
    });
    setAnalyses((current) => {
      const stale = staleAnalysisIds(session.files, current);
      if (!stale.length) return current;
      const next = { ...current };
      for (const id of stale) delete next[id];
      return next;
    });
  }, [session]);

  const invalidate = useCallback((fileIds: string[]) => {
    if (!fileIds.length) return;
    setAnalyses((current) => {
      const next = { ...current };
      for (const id of fileIds) delete next[id];
      return next;
    });
  }, []);

  const hasActiveJobs = useMemo(() => {
    if (!session) return false;
    return (
      session.jobs.some((job) => job.status === 'queued' || job.status === 'running') ||
      session.files.some((file) => file.status === 'queued' || file.status === 'analyzing')
    );
  }, [session]);

  useEffect(() => {
    if (!session || !hasActiveJobs) return;
    let cancelled = false;
    const poll = async () => {
      const id = sessionIdRef.current;
      if (!id) return;
      try {
        const data = await api.getSession(id);
        if (cancelled) return;
        setSession(data);
        const complete = data.files.filter((file) => file.has_analysis);
        for (const file of complete.slice(-2)) {
          if (!analyses[file.id] && !pendingAnalysis.current[file.id]) {
            void ensureAnalysis(file.id);
          }
        }
        void refreshOverview();
      } catch {
        /* transient polling error */
      }
    };
    const timer = window.setInterval(poll, 1400);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [session?.id, hasActiveJobs, ensureAnalysis, refreshOverview, analyses]);

  const uploadingRef = useRef(false);
  const uploadAbort = useRef<AbortController | null>(null);
  const cancelUpload = useCallback(() => {
    uploadAbort.current?.abort();
  }, []);
  const upload = useCallback(
    async (files: File[]) => {
      const id = sessionIdRef.current;
      if (!id) return null;
      if (uploadingRef.current) {
        notify('warning', 'Upload already in progress', 'Wait for the current upload to finish before adding more files.');
        return null;
      }
      uploadingRef.current = true;
      const controller = new AbortController();
      uploadAbort.current = controller;
      setUploadProgress(0);
      setBusy(true);
      try {
        const result = await api.uploadFiles(id, files, setUploadProgress, controller.signal);
        setSession(result.session);
        sessionIdRef.current = result.session.id;
        void refreshOverview();
        if (result.errors?.length) {
          notify(
            'warning',
            `${result.errors.length} file(s) rejected`,
            result.errors.map((item: any) => `${item.file_name}: ${item.errors?.[0] ?? 'invalid'}`).join(' · '),
          );
        }
        if (result.files?.length) {
          notify('success', `${result.files.length} file(s) validated`, 'Ready for analysis.');
        }
        return result;
      } catch (error) {
        if (error instanceof UploadCancelledError) {
          notify('info', 'Upload cancelled', 'The transfer was stopped. Files already in the session are unchanged.');
          // If the request body had already been sent the server may still
          // have stored it; show the server's actual state.
          void refreshSession();
          return null;
        }
        notify('error', 'Upload failed', formatError(error));
        return null;
      } finally {
        uploadAbort.current = null;
        uploadingRef.current = false;
        setUploadProgress(null);
        setBusy(false);
      }
    },
    [notify, refreshOverview, refreshSession],
  );

  const analyze = useCallback(
    async (fileIds?: string[], force = false) => {
      const id = sessionIdRef.current;
      if (!id) return;
      setBusy(true);
      try {
        const result = await api.analyze(id, {
          file_ids: fileIds,
          force,
          target_lufs: session?.settings.target_lufs,
          true_peak_limit: session?.settings.true_peak_limit,
        });
        setSession(result.session);
        invalidate((result.jobs ?? []).map((job) => job.file_id));
        if (result.errors?.length) {
          notify('warning', 'Some files could not be queued', result.errors.map((e: any) => e.error).join(' · '));
        }
        if (result.jobs?.length) {
          notify('info', `${result.jobs.length} analysis job(s) started`, 'Progress updates automatically.');
        } else if (result.skipped?.length) {
          notify('info', 'Files already analysed', 'Use Re-analyse to run the pipeline again.');
        }
      } catch (error) {
        notify('error', 'Could not start analysis', formatError(error));
      } finally {
        setBusy(false);
      }
    },
    [notify, invalidate, session?.settings.target_lufs, session?.settings.true_peak_limit],
  );

  const removeFile = useCallback(
    async (fileId: string) => {
      const id = sessionIdRef.current;
      if (!id) return;
      try {
        const result = await api.removeFile(id, fileId);
        setSession(result.session);
        setAnalyses((current) => {
          const next = { ...current };
          delete next[fileId];
          return next;
        });
        void refreshOverview();
        notify('success', 'File removed', 'The original file was deleted from this session.');
      } catch (error) {
        notify('error', 'Could not remove file', formatError(error));
      }
    },
    [notify, refreshOverview],
  );

  // Upload and validate the replacement first; only remove the original once
  // the new file has been accepted, so a rejected replacement loses nothing.
  const replaceFile = useCallback(
    async (fileId: string, file: File) => {
      const id = sessionIdRef.current;
      if (!id) return false;
      const result = await upload([file]);
      if (!result?.files?.length) {
        notify('warning', 'Replacement not applied', 'The new file was not accepted, so the original was kept.');
        return false;
      }
      try {
        const removed = await api.removeFile(id, fileId);
        setSession(removed.session);
        invalidate([fileId]);
        void refreshOverview();
        return true;
      } catch (error) {
        notify('error', 'New file added but the original could not be removed', formatError(error));
        return false;
      }
    },
    [upload, notify, invalidate, refreshOverview],
  );

  const saveSettings = useCallback(
    async (values: Record<string, unknown>, recompute = true) => {
      const id = sessionIdRef.current;
      if (!id) return false;
      setBusy(true);
      let updated: Session;
      try {
        updated = await api.patchSession(id, values as any);
        setSession(updated);
      } catch (error) {
        notify('error', 'Could not save settings', formatError(error));
        setBusy(false);
        return false;
      }
      try {
        if (recompute) {
          const qc = await api.recomputeQc(id, updated.settings.qc_thresholds);
          setSession(qc.session);
          invalidate((qc.updated ?? []).map((item: any) => item.file_id));
          notify('success', 'Settings saved', 'QC results were recomputed with the current thresholds.');
          void refreshOverview();
        } else {
          notify('success', 'Settings saved');
        }
      } catch (error) {
        // The PATCH succeeded, so do not report the save as failed.
        notify('warning', 'Settings saved, QC not recomputed', `${formatError(error)}. Use "Save and recompute" on Quality control to retry.`);
      } finally {
        setBusy(false);
      }
      return true;
    },
    [notify, refreshOverview, invalidate],
  );

  const recomputeQc = useCallback(
    async (thresholds?: Record<string, unknown>) => {
      const id = sessionIdRef.current;
      if (!id) return;
      setBusy(true);
      try {
        const result = await api.recomputeQc(id, thresholds);
        setSession(result.session);
        setAnalyses((current) => {
          const next = { ...current };
          for (const item of result.updated ?? []) {
            if (next[item.file_id]) {
              // QC values changed server-side; force a refresh next time the file is opened.
              delete next[item.file_id];
            }
          }
          return next;
        });
        void refreshOverview();
        notify('success', 'Quality control recomputed', `${result.updated?.length ?? 0} analysed file(s) updated.`);
      } catch (error) {
        notify('error', 'QC recompute failed', formatError(error));
      } finally {
        setBusy(false);
      }
    },
    [notify, refreshOverview],
  );

  const resetSession = useCallback(async () => {
    const id = sessionIdRef.current;
    if (!id) return;
    setBusy(true);
    try {
      try {
        await api.deleteSession(id);
      } catch {
        /* ignore if already gone */
      }
      const created = await api.createSession('Audio analysis session');
      sessionIdRef.current = created.id;
      localStorage.setItem(SESSION_KEY, created.id);
      setSession(created);
      setOverview(null);
      setAnalyses({});
      setAnalysisErrors({});
      analysisErrorsRef.current = {};
      forgetSession(id);
      setRecentSessions(rememberSession(created.id));
      notify('success', 'New session started', 'Previous temporary files were removed.');
    } catch (error) {
      notify('error', 'Could not start a new session', formatError(error));
    } finally {
      setBusy(false);
    }
  }, [notify]);

  const activate = useCallback((next: Session) => {
    sessionIdRef.current = next.id;
    pendingAnalysis.current = {};
    localStorage.setItem(SESSION_KEY, next.id);
    setSession(next);
    setOverview(null);
    setAnalyses({});
    setLoadingIds({});
    setAnalysisErrors({});
    analysisErrorsRef.current = {};
    setRecentSessions(rememberSession(next.id));
  }, []);

  const newSession = useCallback(async () => {
    setBusy(true);
    try {
      const created = await api.createSession('Audio analysis session');
      activate(created);
      void refreshOverview();
      notify('success', 'New analysis session', 'The previous session is kept under Recent sessions until it expires.');
    } catch (error) {
      notify('error', 'Could not start a new session', formatError(error));
    } finally {
      setBusy(false);
    }
  }, [activate, notify, refreshOverview]);

  const openSession = useCallback(async (sessionId: string) => {
    if (sessionId === sessionIdRef.current) return true;
    try {
      const loaded = await api.getSession(sessionId);
      activate(loaded);
      void refreshOverview();
      notify('success', 'Session opened', loaded.name);
      return true;
    } catch (error) {
      setRecentSessions(forgetSession(sessionId));
      notify('warning', 'Session no longer available', `${formatError(error)}. It may have expired and was removed from Recent sessions.`);
      return false;
    }
  }, [activate, notify, refreshOverview]);

  const forgetRecentSession = useCallback((sessionId: string) => {
    setRecentSessions(forgetSession(sessionId));
  }, []);

  const value: AppContextValue = {
    session,
    overview,
    analyses,
    loadingIds,
    analysisErrors,
    retryAnalysis,
    appSettings,
    uploadProgress,
    busy,
    notify,
    refreshSession,
    refreshOverview,
    ensureAnalysis,
    analyze,
    upload,
    cancelUpload,
    removeFile,
    replaceFile,
    saveSettings,
    recomputeQc,
    resetSession,
    newSession,
    openSession,
    recentSessions,
    forgetRecentSession,
  };

  return (
    <AppContext.Provider value={value}>
      {children}
      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </AppContext.Provider>
  );
}

export function useApp(): AppContextValue {
  const context = useContext(AppContext);
  if (!context) throw new Error('useApp must be used inside AppProvider');
  return context;
}
