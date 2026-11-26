import { Suspense, lazy, useEffect, useMemo, useState, type ComponentType } from 'react';
import {
  AudioLines,
  AudioWaveform,
  ChartColumnBig,
  ChevronRight,
  CircleDot,
  FileText,
  Files,
  Gauge,
  GitCompareArrows,
  LayoutDashboard,
  ListChecks,
  Menu,
  Moon,
  Music2,
  PanelLeftClose,
  PanelLeftOpen,
  Grid3X3,
  Settings,
  ShieldCheck,
  Sun,
  UploadCloud,
  X,
} from 'lucide-react';
import { useApp } from './state/AppContext';
import { useWorkspace } from './state/Workspace';
import { FILE_SECTIONS, type SectionKey } from './lib/routes';
import type { ThemePreference } from './lib/theme';
import { Spinner } from './components/UI';
import { ActiveFileBar } from './components/ActiveFileBar';
import { fmt } from './lib/format';

// Sections are split into their own chunks; Plotly is loaded on first chart.
const SECTIONS: Record<SectionKey, ComponentType<{ navigate: (section: string) => void }>> = {
  dashboard: lazy(() => import('./sections/DashboardSection')),
  upload: lazy(() => import('./sections/UploadSection')),
  files: lazy(() => import('./sections/FilesSection')),
  overview: lazy(() => import('./sections/OverviewSection')),
  waveform: lazy(() => import('./sections/WaveformSection')),
  spectrum: lazy(() => import('./sections/SpectrumSection')),
  spectrogram: lazy(() => import('./sections/SpectrogramSection')),
  musical: lazy(() => import('./sections/MusicalSection')),
  loudness: lazy(() => import('./sections/LoudnessSection')),
  dynamics: lazy(() => import('./sections/DynamicsSection')),
  stereo: lazy(() => import('./sections/StereoSection')),
  comparison: lazy(() => import('./sections/ComparisonSection')),
  qc: lazy(() => import('./sections/QualityControlSection')),
  reports: lazy(() => import('./sections/ReportsSection')),
  settings: lazy(() => import('./sections/SettingsSection')),
};

interface NavItem {
  key: SectionKey;
  label: string;
  icon: ComponentType<{ size?: number; 'aria-hidden'?: boolean }>;
  description: string;
}

const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  { label: 'Project', items: [
    { key: 'dashboard', label: 'Dashboard', icon: LayoutDashboard, description: 'Project overview, recent sessions and quick actions' },
    { key: 'upload', label: 'Upload', icon: UploadCloud, description: 'Add and validate audio' },
    { key: 'files', label: 'Files', icon: Files, description: 'Metadata and validation' },
  ] },
  { label: 'Analysis', items: [
    { key: 'overview', label: 'File overview', icon: ListChecks, description: 'All measurements for one file' },
    { key: 'waveform', label: 'Waveform', icon: AudioWaveform, description: 'Time domain, peaks and regions' },
    { key: 'spectrum', label: 'Spectrum', icon: AudioLines, description: 'FFT, bands and spectral features' },
    { key: 'spectrogram', label: 'Spectrogram', icon: Grid3X3, description: 'STFT and mel time-frequency maps' },
    { key: 'musical', label: 'Musical', icon: Music2, description: 'Key, chroma, tempo and pitch' },
    { key: 'loudness', label: 'Loudness & gain', icon: Gauge, description: 'BS.1770 and gain preview' },
    { key: 'dynamics', label: 'Dynamics', icon: ChartColumnBig, description: 'Crest, LRA and compression' },
    { key: 'stereo', label: 'Stereo & phase', icon: CircleDot, description: 'Correlation, width and mono' },
  ] },
  { label: 'Evaluate', items: [
    { key: 'comparison', label: 'Comparison', icon: GitCompareArrows, description: 'Multi-file and alignment' },
    { key: 'qc', label: 'Quality control', icon: ShieldCheck, description: 'Findings and thresholds' },
  ] },
  { label: 'Deliver', items: [
    { key: 'reports', label: 'Reports', icon: FileText, description: 'PDF, CSV, JSON and PNG' },
    { key: 'settings', label: 'Settings', icon: Settings, description: 'Analysis, QC, theme and charts' },
  ] },
];

const TITLES = Object.fromEntries(
  NAV_GROUPS.flatMap((group) => group.items.map((item) => [item.key, item.label])),
) as Record<SectionKey, string>;

function SectionFallback() {
  return (
    <div className="loading-row section-loading">
      <Spinner label="Loading section" /> Loading…
    </div>
  );
}

export default function App() {
  const { session, overview, loadingIds, busy, uploadProgress } = useApp();
  const { route, navigate, theme, themePreference, setThemePreference } = useWorkspace();
  const section = route.section;
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('aap_sidebar_collapsed') === 'true');

  useEffect(() => {
    localStorage.setItem('aap_sidebar_collapsed', String(collapsed));
  }, [collapsed]);

  useEffect(() => {
    document.title = `${TITLES[section]} · Audio Analysis Pipeline`;
    setMobileOpen(false);
  }, [section]);

  // Escape closes the mobile navigation drawer.
  useEffect(() => {
    if (!mobileOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMobileOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [mobileOpen]);

  const activeJobs = (session?.jobs ?? []).filter((job) => job.status === 'queued' || job.status === 'running');
  const analysed = session?.files.filter((file) => file.has_analysis).length ?? 0;
  const totalFiles = session?.files.length ?? 0;
  const loadingCount = useMemo(() => Object.keys(loadingIds).length, [loadingIds]);
  const qcIssues = Number(overview?.totals.warnings ?? 0) + Number(overview?.totals.errors ?? 0);
  const Section = SECTIONS[section];

  return (
    <div className={`app-shell ${collapsed ? 'sidebar-collapsed' : ''} ${mobileOpen ? 'mobile-nav-open' : ''}`}>
      <a className="skip-link" href="#main-content">Skip to content</a>

      <div className="mobile-scrim" onClick={() => setMobileOpen(false)} aria-hidden="true" />

      <aside className="sidebar" aria-label="Primary navigation">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            <span /><span /><span /><span />
          </div>
          <div className="brand-copy">
            <strong>Audio Analysis</strong>
            <span>Measurement &amp; QC</span>
          </div>
          <button className="icon-button sidebar-close" onClick={() => setMobileOpen(false)} aria-label="Close navigation">
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        <nav className="sidebar-nav" aria-label="Sections">
          {NAV_GROUPS.map((group) => (
            <div className="nav-group" key={group.label} role="group" aria-label={group.label}>
              <div className="nav-group-label" aria-hidden="true">{group.label}</div>
              {group.items.map((item) => {
                const Icon = item.icon;
                const active = section === item.key;
                return (
                  <a
                    key={item.key}
                    href={`#/${item.key}`}
                    className={`nav-item ${active ? 'active' : ''}`}
                    onClick={(event) => {
                      event.preventDefault();
                      navigate(item.key);
                    }}
                    title={collapsed ? item.label : item.description}
                    aria-current={active ? 'page' : undefined}
                  >
                    <Icon size={17} aria-hidden={true} />
                    <span className="nav-label">{item.label}</span>
                    {item.key === 'files' && totalFiles > 0 && (
                      <>
                        <span className="nav-count" aria-hidden="true">{totalFiles}</span>
                        <span className="sr-only">, {totalFiles} files</span>
                      </>
                    )}
                    {item.key === 'qc' && qcIssues > 0 && (
                      <>
                        <span className="nav-alert" aria-hidden="true">{qcIssues}</span>
                        <span className="sr-only">, {qcIssues} warning or critical findings</span>
                      </>
                    )}
                  </a>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="privacy-note">
            <ShieldCheck size={14} aria-hidden="true" />
            <span>Originals preserved. No audio is modified.</span>
          </div>
          <button
            className="collapse-button"
            onClick={() => setCollapsed((value) => !value)}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-expanded={!collapsed}
          >
            {collapsed ? <PanelLeftOpen size={16} aria-hidden="true" /> : <PanelLeftClose size={16} aria-hidden="true" />}
            <span>{collapsed ? 'Expand' : 'Collapse'}</span>
          </button>
        </div>
      </aside>

      <div className="app-main">
        <header className="topbar">
          <button className="icon-button mobile-menu" onClick={() => setMobileOpen(true)} aria-label="Open navigation" aria-expanded={mobileOpen}>
            <Menu size={20} aria-hidden="true" />
          </button>
          <nav className="breadcrumb" aria-label="Location">
            <button className="breadcrumb-project" onClick={() => navigate('dashboard')} title={session ? `Session ${session.id}` : undefined}>
              {session?.name ?? 'Connecting…'}
            </button>
            <ChevronRight size={14} aria-hidden="true" className="breadcrumb-sep" />
            <span aria-current="page">{TITLES[section]}</span>
          </nav>
          <div className="topbar-status" role="status" aria-live="polite">
            <span className={`server-pill ${session ? 'online' : 'offline'}`}>
              <span className="status-dot" aria-hidden="true" />
              {session ? 'Connected' : 'Connecting…'}
            </span>
            <span className="topbar-metric" title="Files with a completed analysis">
              {analysed}/{totalFiles} analysed
            </span>
            {(activeJobs.length > 0 || busy || uploadProgress !== null) && (
              <span className="topbar-metric running">
                <Spinner size={13} label="Working" />
                {uploadProgress !== null
                  ? `Uploading ${uploadProgress}%`
                  : activeJobs.length
                    ? `${activeJobs.length} analysing`
                    : 'Working…'}
              </span>
            )}
            {loadingCount > 0 && (
              <span className="topbar-metric">
                <Spinner size={13} label="Loading results" /> Loading {loadingCount}
              </span>
            )}
          </div>
          <div className="topbar-actions">
            <label className="theme-select" title={`Theme: ${themePreference}${themePreference === 'system' ? ` (now ${theme})` : ''}`}>
              {theme === 'dark' ? <Moon size={15} aria-hidden="true" /> : <Sun size={15} aria-hidden="true" />}
              <span className="sr-only">Theme</span>
              <select value={themePreference} onChange={(event) => setThemePreference(event.target.value as ThemePreference)}>
                <option value="light">Light</option>
                <option value="dark">Dark</option>
                <option value="system">System</option>
              </select>
            </label>
            <button className="icon-button" onClick={() => navigate('settings')} aria-label="Settings" title="Settings">
              <Settings size={17} aria-hidden="true" />
            </button>
          </div>
        </header>

        {FILE_SECTIONS.has(section) && <ActiveFileBar />}

        <main id="main-content" className="content" tabIndex={-1}>
          <Suspense fallback={<SectionFallback />}>
            <Section navigate={navigate} />
          </Suspense>
        </main>

        <footer className="app-footer">
          <span>Measured values are labelled “Measured”; algorithmic estimates show their confidence.</span>
          <span className="muted">
            {session ? `${fmt(overview?.totals.duration_seconds ?? 0, 1)} s of audio · session ${session.id.slice(4, 12)}` : 'No active session'}
          </span>
        </footer>
      </div>
    </div>
  );
}
