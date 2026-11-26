/**
 * Chart design tokens and theme mapping.
 *
 * Sections build Plotly traces with *identity* colours — the Light-mode
 * ("Clean Analytical") values below.  `themeFigure()` (applied by the Plot
 * component on every render) swaps each identity colour for its Dark-mode
 * ("Studio Matte") pair, including rgba() tints made with `rgba()`.
 * Track N therefore keeps the same identity in both themes, and every chart
 * re-themes immediately without each section re-computing.
 *
 * The light series are the refined indigo/teal/violet/amber/crimson palette;
 * each is ≥3:1 on #FFFFFF.  The dark pairs keep the same hue but are
 * lightened just enough to clear 3:1 on #1A1A1D.  Magnitude maps are
 * unchanged and theme-neutral.
 *
 * Axis, grid, text and surface colours are read from CSS tokens at render
 * time (`--chart-*`), so they always match the active theme.
 */
export type ResolvedTheme = 'light' | 'dark';

/** Light identity → Dark pair (same hue, tuned for each chart surface). */
const PAIRS: [string, string][] = [
  ['#4F46E5', '#665EE8'], // Track 1 — indigo (primary waveform)
  ['#0D9488', '#0D9488'], // Track 2 — teal (overlay data)
  ['#7C3AED', '#884CEF'], // Track 3 — violet (stereo / phase)
  ['#D97706', '#D97706'], // Track 4 — amber (spectral peaks)
  ['#BE123C', '#C93A5D'], // Track 5 — crimson (loudness ranges)
  ['#15803D', '#4ADE80'], // Track 6 — green (extension)
  ['#0369A1', '#7DD3FC'], // Track 7 — sky (extension)
  ['#9F1239', '#F9A8D4'], // Track 8 — rose (extension)
  // Reference / muted doubles as the control border in both themes, so it is
  // listed once: a duplicated key would silently override an earlier mapping.
  ['#71717A', '#71717A'], // Reference, muted and control border
  ['#6366F1', '#7A7DF3'], // Secondary accent (graphics)
  ['#11813A', '#51CF66'], // Success
  ['#A75C05', '#FFD43B'], // Warning
  ['#D82525', '#FF6B6B'], // Critical
  ['#0275B1', '#74C0FC'], // Information
];

export const SERIES = PAIRS.slice(0, 8).map(([light]) => light);

export const COLORS = {
  accent: '#4F46E5',
  accent2: '#6366F1',
  accent3: '#7C3AED',
  success: '#11813A',
  warning: '#A75C05',
  error: '#D82525',
  info: '#0275B1',
  muted: '#71717A',
  reference: '#71717A',
  border: '#71717A',
  palette: SERIES,
};

/** Dash patterns paired with palette colours so overlaid series differ by more than colour. */
export const DASHES = ['solid', 'dash', 'dot', 'dashdot', 'longdash', 'longdashdot', 'solid', 'dash'];

/** Perceptually uniform scientific colour maps (identical in both themes). */
export const MAGMA: [number, string][] = [
  [0, '#000004'], [0.13, '#1c1044'], [0.25, '#4f127b'], [0.38, '#812581'], [0.5, '#b5367a'],
  [0.63, '#e55064'], [0.75, '#fb8761'], [0.88, '#fec287'], [1, '#fcfdbf'],
];
export const VIRIDIS = 'Viridis';

const HEX_MAP = new Map(PAIRS.map(([l, d]) => [l.toLowerCase(), d]));
const hexToRgb = (hex: string) => {
  const v = hex.replace('#', '');
  return [0, 2, 4].map((i) => parseInt(v.slice(i, i + 2), 16)).join(',');
};
const RGB_MAP = new Map(PAIRS.map(([l, d]) => [hexToRgb(l), hexToRgb(d)]));
const RGBA_RE = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([0-9.]+)\s*)?\)$/i;

/** Map one colour string to the active theme (identity in light). */
export function themeColor(value: string, theme: ResolvedTheme): string {
  if (theme === 'light') return value;
  const direct = HEX_MAP.get(value.toLowerCase());
  if (direct) return direct;
  const m = RGBA_RE.exec(value);
  if (m) {
    const mapped = RGB_MAP.get(`${m[1]},${m[2]},${m[3]}`);
    if (mapped) return m[4] !== undefined ? `rgba(${mapped},${m[4]})` : `rgb(${mapped})`;
  }
  return value;
}

/**
 * Deep-map every colour string in a Plotly figure (traces or layout).
 * Numeric arrays are returned untouched (no copying of large data arrays).
 */
export function themeFigure<T>(value: T, theme: ResolvedTheme): T {
  if (theme === 'light') return value;
  const walk = (v: any): any => {
    if (typeof v === 'string') return themeColor(v, theme);
    if (Array.isArray(v)) {
      if (v.length && typeof v[0] === 'number') return v;
      if (v.length && Array.isArray(v[0]) && typeof v[0][0] === 'number') return v; // z matrices
      return v.map(walk);
    }
    if (v && typeof v === 'object') {
      const out: Record<string, any> = {};
      for (const key of Object.keys(v)) out[key] = walk(v[key]);
      return out;
    }
    return v;
  };
  return walk(value);
}

export const PLOT_CONFIG = {
  responsive: true,
  displaylogo: false,
  scrollZoom: false,
  // "sendChartToCloud" (Share chart…) uploads the chart data to Plotly Cloud;
  // measurement data must never leave the application.
  modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d', 'sendChartToCloud', 'editInChartStudio'],
  showSendToCloud: false,
  showEditInChartStudio: false,
  plotlyServerURL: '',
  toImageButtonOptions: { format: 'png', filename: 'audio-analysis-plot', scale: 2 },
};

function token(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/** Chart tokens read from CSS; fallbacks mirror the light theme exactly. */
export function chartTokens() {
  return {
    text: token('--chart-text', '#18181B'),
    muted: token('--chart-muted', '#52525B'),
    grid: token('--chart-grid', '#E4E4E7'),
    zero: token('--chart-zero', '#A1A1AA'),
    plotBg: token('--chart-bg', '#FFFFFF'),
    hoverBg: token('--chart-hover-bg', '#18181B'),
    hoverText: token('--chart-hover-text', '#FAFAFA'),
    border: token('--border', '#E4E4E7'),
    modebarBg: token('--panel', '#FFFFFF'),
    modebarColor: token('--text-soft', '#52525B'),
    modebarActive: token('--accent', '#4F46E5'),
    font: token('--font-sans', 'system-ui, sans-serif'),
  };
}

function axisDefaults(t: ReturnType<typeof chartTokens>) {
  return {
    gridcolor: t.grid,
    zerolinecolor: t.zero,
    linecolor: t.border,
    tickfont: { size: 11, color: t.muted },
    title: { font: { size: 12, color: t.muted } },
    automargin: true,
  };
}

function mergeAxis(base: Record<string, any>, override: Record<string, any> | undefined) {
  if (!override) return base;
  const title =
    typeof override.title === 'string'
      ? { ...base.title, text: override.title }
      : override.title
        ? { ...base.title, ...override.title }
        : base.title;
  return { ...base, ...override, title };
}

export function baseLayout(overrides: Record<string, any> = {}) {
  const t = chartTokens();
  const axis = axisDefaults(t);
  const layout: Record<string, any> = {
    paper_bgcolor: t.plotBg,
    plot_bgcolor: t.plotBg,
    font: { color: t.text, family: t.font, size: 12 },
    margin: { l: 56, r: 16, t: 36, b: 44 },
    hoverlabel: { bgcolor: t.hoverBg, bordercolor: t.hoverBg, font: { color: t.hoverText, size: 12 } },
    modebar: { bgcolor: t.modebarBg, color: t.modebarColor, activecolor: t.modebarActive },
    legend: {
      orientation: 'h',
      y: 1.02,
      yanchor: 'bottom',
      x: 0,
      font: { size: 11, color: t.muted },
      bgcolor: 'rgba(0,0,0,0)',
    },
    hovermode: 'closest',
    ...overrides,
  };
  for (const key of Object.keys(layout)) {
    if (/^[xy]axis\d*$/.test(key)) layout[key] = mergeAxis(axis, layout[key]);
  }
  if (!layout.xaxis) layout.xaxis = axis;
  if (!layout.yaxis) layout.yaxis = axis;
  return layout;
}

export function rgba(hex: string, alpha: number): string {
  const clean = hex.replace('#', '');
  const value = clean.length === 3 ? clean.split('').map((c) => c + c).join('') : clean;
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

export function bandShapes(): any[] {
  const bounds = [60, 250, 500, 2000, 4000, 6000];
  return bounds.map((x) => ({
    type: 'line',
    x0: x,
    x1: x,
    y0: 0,
    y1: 1,
    yref: 'paper',
    line: { color: rgba(COLORS.muted, 0.55), width: 1, dash: 'dot' },
  }));
}

export function regionShapes(regions: { start: number; end: number }[], color: string, max = 80): any[] {
  return regions.slice(0, max).map((region) => ({
    type: 'rect',
    x0: region.start,
    x1: region.end,
    y0: 0,
    y1: 1,
    yref: 'paper',
    fillcolor: color,
    line: { width: 0 },
    layer: 'below',
  }));
}

export function lineShapes(values: number[], color: string, dash: string = 'dash'): any[] {
  return values.map((value) => ({
    type: 'line',
    x0: 0,
    x1: 1,
    xref: 'paper',
    y0: value,
    y1: value,
    line: { color, width: 1.2, dash },
  }));
}

export function beatShapes(beats: number[], color = rgba(COLORS.accent2, 0.35), max = 500): any[] {
  return beats.slice(0, max).map((beat) => ({
    type: 'line',
    x0: beat,
    x1: beat,
    y0: 0,
    y1: 1,
    yref: 'paper',
    line: { color, width: 0.7 },
  }));
}

/**
 * y-range for loudness/level plots that never stretches a tiny variation over
 * the full height (a 0.4 LU wobble must not look like a 20 LU swing).
 */
export function minSpanRange(values: (number | null | undefined)[], minSpan: number, pad = 1): [number, number] | undefined {
  const finite = values.filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
  if (!finite.length) return undefined;
  let lo = Math.min(...finite);
  let hi = Math.max(...finite);
  if (hi - lo < minSpan) {
    const mid = (hi + lo) / 2;
    lo = mid - minSpan / 2;
    hi = mid + minSpan / 2;
  }
  return [lo - pad, hi + pad];
}
