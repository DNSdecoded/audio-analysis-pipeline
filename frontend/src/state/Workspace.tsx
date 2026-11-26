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
import { parseRoute, routeHref, SECTION_KEYS, type Route, type SectionKey } from '../lib/routes';
import {
  applyTheme,
  DARK_QUERY,
  readThemePreference,
  resolveTheme,
  THEME_KEY,
  type ResolvedTheme,
  type ThemePreference,
} from '../lib/theme';

export type Theme = ResolvedTheme;

export interface ChartPrefs {
  /** Default to a logarithmic frequency axis for spectra and spectrograms. */
  logFrequency: boolean;
  /** Show the Plotly toolbar permanently instead of on hover. */
  alwaysShowToolbar: boolean;
}

export interface FocusRange {
  fileId: string;
  start: number;
  end: number;
  label?: string;
}

interface WorkspaceValue {
  route: Route;
  navigate: (section: SectionKey | string, params?: { file?: string; start?: number; end?: number; label?: string }) => void;
  /** Resolved theme currently applied ('light' | 'dark'). */
  theme: Theme;
  /** Stored preference ('light' | 'dark' | 'system'). */
  themePreference: ThemePreference;
  setThemePreference: (preference: ThemePreference) => void;
  /** Explicitly choose light or dark (same as setThemePreference). */
  setTheme: (theme: Theme) => void;
  activeFileId: string | null;
  setActiveFileId: (fileId: string | null) => void;
  focus: FocusRange | null;
  clearFocus: () => void;
  chartPrefs: ChartPrefs;
  setChartPrefs: (prefs: Partial<ChartPrefs>) => void;
}

const WorkspaceContext = createContext<WorkspaceValue | null>(null);
const PREFS_KEY = 'aap_chart_prefs';

function systemPrefersDark(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia?.(DARK_QUERY).matches;
}

function initialPrefs(): ChartPrefs {
  const defaults: ChartPrefs = { logFrequency: true, alwaysShowToolbar: false };
  try {
    return { ...defaults, ...JSON.parse(localStorage.getItem(PREFS_KEY) ?? '{}') };
  } catch {
    return defaults;
  }
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash));
  const [themePreference, setPreferenceState] = useState<ThemePreference>(() => readThemePreference(localStorage));
  const [systemDark, setSystemDark] = useState<boolean>(systemPrefersDark);
  const theme = resolveTheme(themePreference, systemDark);
  const [activeFileId, setActiveFileId] = useState<string | null>(() => parseRoute(window.location.hash).file ?? null);
  const [focus, setFocus] = useState<FocusRange | null>(() => {
    const r = parseRoute(window.location.hash);
    return r.file && r.start !== undefined && r.end !== undefined ? { fileId: r.file, start: r.start, end: r.end } : null;
  });
  const [chartPrefs, setPrefsState] = useState<ChartPrefs>(initialPrefs);

  // Display preferences saved on the Settings page must apply on every load,
  // not only after the Settings page has been opened.
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.density = localStorage.getItem('aap_density') ?? 'comfortable';
    root.dataset.reduceMotion = String(localStorage.getItem('aap_reduce_motion') === 'true');
  }, []);

  // Apply the resolved theme to <html>; every token-based component and the
  // Plot component (which subscribes to `theme`) update without a reload.
  useEffect(() => {
    applyTheme(document.documentElement, theme);
  }, [theme]);

  // While "System" is selected, follow operating-system changes live.
  useEffect(() => {
    const media = window.matchMedia?.(DARK_QUERY);
    if (!media) return;
    const onChange = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }, []);

  // Keep several open tabs on one preference.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === THEME_KEY) setPreferenceState(readThemePreference(localStorage));
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  const setThemePreference = useCallback((preference: ThemePreference) => {
    localStorage.setItem(THEME_KEY, preference);
    setPreferenceState(preference);
  }, []);

  // Hash is the single source of truth for the section: Back/Forward and deep
  // links work, and a file/time-range in the hash selects that context.
  // Hash changes the app itself made (navigate) already set focus with its
  // label; re-setting it here would replay a consumed focus without the label.
  const ownHash = useRef<string | null>(null);
  useEffect(() => {
    const onHash = () => {
      const next = parseRoute(window.location.hash);
      setRoute(next);
      if (ownHash.current === window.location.hash) {
        ownHash.current = null;
        return;
      }
      if (next.file) setActiveFileId(next.file);
      if (next.file && next.start !== undefined && next.end !== undefined) {
        setFocus({ fileId: next.file, start: next.start, end: next.end });
      }
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const navigate = useCallback<WorkspaceValue['navigate']>((section, params) => {
    const key = (SECTION_KEYS.has(section) ? section : 'dashboard') as SectionKey;
    if (params?.file) setActiveFileId(params.file);
    if (params?.file && params.start !== undefined && params.end !== undefined) {
      setFocus({ fileId: params.file, start: params.start, end: params.end, label: params.label });
    }
    const href = routeHref(key, params);
    if (window.location.hash !== href) {
      ownHash.current = href;
      window.location.hash = href;
    }
    else setRoute(parseRoute(href));
    document.getElementById('main-content')?.focus({ preventScroll: true });
    window.scrollTo({ top: 0 });
  }, []);

  const setChartPrefs = useCallback((prefs: Partial<ChartPrefs>) => {
    setPrefsState((current) => {
      const next = { ...current, ...prefs };
      localStorage.setItem(PREFS_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const value = useMemo<WorkspaceValue>(
    () => ({
      route,
      navigate,
      theme,
      themePreference,
      setThemePreference,
      setTheme: setThemePreference,
      activeFileId,
      setActiveFileId,
      focus,
      clearFocus: () => setFocus(null),
      chartPrefs,
      setChartPrefs,
    }),
    [route, navigate, theme, themePreference, setThemePreference, activeFileId, focus, chartPrefs, setChartPrefs],
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceValue {
  const context = useContext(WorkspaceContext);
  if (!context) throw new Error('useWorkspace must be used inside WorkspaceProvider');
  return context;
}
