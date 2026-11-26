import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
// Tests run in Node, so the real stylesheet can be read from disk and the
// contrast guards below assert on the values that actually ship. (Vitest stubs
// CSS imports to an empty string, so `?raw` cannot be used here.)
// @ts-expect-error -- node:fs is available at test time; @types/node is not a dependency.
import { readFileSync } from 'node:fs';
import { MetricCard, SeverityBadge, TableWrap } from '../components/UI';
import { parseRoute, routeHref } from './routes';
import { forgetSession, readRecentSessions, rememberSession } from './recentSessions';
import { collectFindings, formatLimit, formatMeasurement } from './qcFindings';
import { describeFindingMeasurement, filterRows, sortBy, sortRows } from './comparisonView';
import { validateSettings } from './settingsValidation';
import { buildMetricGroups } from './metrics';
import { minSpanRange, COLORS, PLOT_CONFIG, SERIES, themeColor } from './plotTheme';
import { readThemePreference, resolveTheme } from './theme';

const FILE = 'fil_' + 'a'.repeat(32);

function memoryStorage() {
  const data: Record<string, string> = {};
  return { getItem: (k: string) => data[k] ?? null, setItem: (k: string, v: string) => { data[k] = v; } };
}

describe('routes', () => {
  it('parses section, file and time range', () => {
    expect(parseRoute(`#/waveform?file=${FILE}&start=1.5&end=2.25`)).toEqual({ section: 'waveform', file: FILE, start: 1.5, end: 2.25 });
  });
  it('rejects invalid input from the editable hash', () => {
    expect(parseRoute('#/nope?file=../../etc&start=5&end=1')).toEqual({ section: 'dashboard' });
    expect(parseRoute('#/qc?file=fil_xyz')).toEqual({ section: 'qc' });
  });
  it('round-trips', () => {
    expect(parseRoute(routeHref('overview', { file: FILE, start: 0.1234, end: 3 }))).toEqual({ section: 'overview', file: FILE, start: 0.123, end: 3 });
  });
});

describe('recent sessions', () => {
  it('keeps most-recent-first, unique, valid IDs only', () => {
    const s = memoryStorage();
    const a = 'ses_' + '1'.repeat(32);
    const b = 'ses_' + '2'.repeat(32);
    rememberSession(a, s);
    rememberSession(b, s);
    rememberSession(a, s);
    expect(readRecentSessions(s).map((r) => r.id)).toEqual([a, b]);
    s.setItem('aap_recent_sessions', JSON.stringify([{ id: 'evil' }, { id: a }]));
    expect(readRecentSessions(s).map((r) => r.id)).toEqual([a]);
    expect(forgetSession(a, s)).toEqual([]);
  });
});

describe('QC formatting (UI-03, UI-19)', () => {
  it('never shows raw JSON', () => {
    const bands = { bands: [{ band: 'Sub-bass', variation_db: 28.84 }, { band: 'Presence', variation_db: 10.09 }] };
    const text = formatMeasurement(bands);
    expect(text).toBe('Band variation — Sub-bass: 28.84 dB; Presence: 10.09 dB');
    expect(formatMeasurement({ high_band_share_pct: 0, centroid_hz: 380.05 })).toBe('High-band share: 0 % · Centroid: 380.05 Hz');
    expect(formatMeasurement(null)).toBe('Not available');
    expect(formatMeasurement(0.0017, 'linear')).toBe('0.0017 linear'); // small values keep precision
  });
  it('shows the error limit for critical findings', () => {
    const check = { id: 'clipping', severity: 'error', threshold_value: 0.005, threshold_unit: '% warning' } as any;
    expect(formatLimit(check, { clipping_percent_error: 0.05 })).toBe('critical ≥ 0.05 % · warning ≥ 0.005 %');
    const corr = { id: 'correlation', severity: 'error', threshold_value: -0.1, threshold_unit: 'r warning' } as any;
    expect(formatLimit(corr, { correlation_error: -0.5 })).toBe('critical ≤ -0.5 r · warning ≤ -0.1 r');
    expect(formatLimit({ id: 'x', severity: 'warning', threshold_value: [-30, -6], threshold_unit: 'LUFS range' } as any)).toBe('-30 to -6 LUFS');
  });
  it('collects across files, filters and orders by severity', () => {
    const files = [{ id: 'f1', original_name: 'b.wav' }, { id: 'f2', original_name: 'a.wav' }];
    const mk = (id: string, severity: string, title: string) => ({ id, severity, title, category: 'Signal quality', message: title } as any);
    const analyses = {
      f1: { qc: { checks: [mk('a', 'information', 'Info one'), mk('b', 'error', 'Clip')] } },
      f2: { qc: { checks: [mk('c', 'warning', 'Warn'), mk('d', 'normal', 'Ok')] } },
    } as any;
    const all = collectFindings(files, analyses, ['error', 'warning', 'information']);
    expect(all.map((f) => `${f.check.severity}:${f.fileName}`)).toEqual(['error:b.wav', 'warning:a.wav', 'information:b.wav']);
    expect(collectFindings(files, analyses, ['error', 'warning', 'information', 'normal'], 'a.wav').length).toBe(2);
  });
});

describe('comparison view (UI-04)', () => {
  it('maps file IDs to names', () => {
    const lines = describeFindingMeasurement({ sample_rates_hz: { f1: 44100, f2: 48000 }, ratio: 2 }, { f1: 'a.wav', f2: 'b.wav' });
    expect(lines[0]).toEqual({ label: 'Sample rate (Hz)', values: [{ name: 'a.wav', value: '44,100' }, { name: 'b.wav', value: '48,000' }] });
    expect(JSON.stringify(lines)).not.toContain('f1');
  });
  it('filters and sorts parameter rows', () => {
    const rows = [
      { key: 'a', label: 'True peak', group: 'Loudness', status: 'match', spread: 0.1 },
      { key: 'b', label: 'Crest', group: 'Dynamics', status: 'large_deviation', spread: 9 },
      { key: 'c', label: 'Sample peak', group: 'Loudness', status: 'different', spread: null },
    ];
    expect(filterRows(rows, ['match', 'different'], 'peak').map((r) => r.key)).toEqual(['a', 'c']);
    expect(sortRows(rows, 'status').map((r) => r.key)).toEqual(['b', 'c', 'a']);
    expect(sortRows(rows, 'spread').map((r) => r.key)).toEqual(['b', 'a', 'c']);
    expect(sortBy([{ v: 2 }, { v: null }, { v: 1 }], (x) => x.v, 'desc').map((x) => x.v)).toEqual([2, 1, null]);
  });
});

describe('settings validation', () => {
  const ok = { name: 'S', target: -14, limit: -1, fftSize: 4096, hopLength: 1024 };
  it('accepts valid settings', () => expect(validateSettings(ok)).toEqual({}));
  it('rejects out-of-range values and hop > FFT', () => {
    const errors = validateSettings({ ...ok, target: -80, limit: 2, fftSize: 512, hopLength: 1024, name: ' ' });
    expect(Object.keys(errors).sort()).toEqual(['hopLength', 'limit', 'name', 'target']);
  });
});

describe('metrics dashboard', () => {
  const analysis: any = {
    qc: { checks: [{ id: 'clipping', severity: 'error' }, { id: 'true_peak', severity: 'normal' }] },
    time_domain: { noise: { snr_db: null, noise_floor_dbfs: null, confidence: 'unavailable' }, clipping: { clipped_percent: 50.08, clipped_samples: 10 }, sample_peak: { dbfs: 0 }, rms: { dbfs: -3 }, dc_offset: { max_abs: 0 }, silence: { percent: 0 } },
    loudness: { true_peak_dbtp: 0.02, integrated_lufs: null },
    musical: { key: { key: 'A major', confidence: 0.4, confidence_label: 'low' }, tempo: {}, pitch: { supported: false } },
    metadata: { sample_rate: 48000, channels: 1 },
    dynamics: {},
    stereo: { supported: false, reason: 'Mono file' },
  };
  const groups = buildMetricGroups(analysis);
  const metric = (key: string) => groups.flatMap((g) => g.metrics).find((m) => m.key === key)!;
  it('takes status only from the matching QC rule', () => {
    expect(metric('clipping').status).toBe('critical');
    expect(metric('true_peak').status).toBe('pass');
    expect(metric('rms').status).toBe('none');
  });
  it('labels estimates and keeps missing values unavailable', () => {
    expect(metric('key').kind).toBe('estimate');
    expect(metric('snr').value).toBeNull();
    expect(metric('integrated').value).toBeNull();
    expect(groups.find((g) => g.title === 'Stereo analysis')!.metrics).toEqual([]);
  });
});

describe('components', () => {
  it('MetricCard never shows Pass for a missing value', () => {
    const html = renderToStaticMarkup(<MetricCard label="SNR" value={null} unit="dB" status="pass" kind="estimate" confidence="unavailable" />);
    expect(html).toContain('Not available');
    expect(html).not.toContain('Pass');
    expect(html).not.toContain('unavailable confidence');
  });
  it('MetricCard shows unit, status text and measurement kind', () => {
    const html = renderToStaticMarkup(<MetricCard label="True peak" value="-1.20" unit="dBTP" status="warning" explanation="4x oversampled" />);
    expect(html).toContain('dBTP');
    expect(html).toContain('Warning');
    expect(html).toContain('Measured');
    expect(html).toContain('role="tooltip"');
  });
  it('SeverityBadge uses text + icon, not colour alone', () => {
    expect(renderToStaticMarkup(<SeverityBadge severity="error" />)).toContain('Critical');
    expect(renderToStaticMarkup(<SeverityBadge severity="normal" />)).toContain('Pass');
  });
  it('TableWrap is a focusable labelled region', () => {
    const html = renderToStaticMarkup(<TableWrap label="Findings"><table /></TableWrap>);
    expect(html).toContain('role="region"');
    expect(html).toContain('aria-label="Findings"');
    expect(html).toContain('tabindex="0"');
  });
});

describe('chart design tokens', () => {
  it('never offers Plotly cloud upload (UI-01)', () => {
    expect(PLOT_CONFIG.modeBarButtonsToRemove).toContain('sendChartToCloud');
    expect(PLOT_CONFIG.showSendToCloud).toBe(false);
  });
  it('series palette meets 3:1 on both chart backgrounds', () => {
    const lum = (hex: string) => {
      const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((x) => (x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
      return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
    };
    const ratio = (a: string, b: string) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
    for (const colour of COLORS.palette) {
      expect(ratio(colour, '#ffffff')).toBeGreaterThanOrEqual(3); // light identity on white chart
      expect(ratio(themeColor(colour, 'dark'), '#1a1a1d')).toBeGreaterThanOrEqual(3); // dark pair on #1A1A1D
    }
    expect(themeColor('#4F46E5', 'dark')).toBe('#665EE8');
    expect(themeColor('#7C3AED', 'dark')).toBe('#884CEF');
    expect(themeColor('rgba(79,70,229,0.4)', 'dark')).toBe('rgba(102,94,232,0.4)');
    expect(themeColor('#4F46E5', 'light')).toBe('#4F46E5');
  });
  it('maps each identity colour at most once (a duplicate key would silently win)', () => {
    const identities = SERIES.map((c) => c.toLowerCase());
    expect(new Set(identities).size).toBe(identities.length);
  });
  it('minimum span keeps small variations from filling the axis (UI-06)', () => {
    const [lo, hi] = minSpanRange([-14.4, -14.0, null], 12, 1)!;
    expect(hi - lo).toBeCloseTo(14);
    expect(minSpanRange([null], 12)).toBeUndefined();
  });
});

describe('theme preference', () => {
  it('defaults to system and resolves light without a dark OS preference', () => {
    expect(readThemePreference({ getItem: () => null })).toBe('system');
    expect(resolveTheme('system', false)).toBe('light');
    expect(resolveTheme('system', true)).toBe('dark');
    expect(resolveTheme('light', true)).toBe('light');
    expect(readThemePreference({ getItem: () => 'bogus' })).toBe('system');
  });
});

describe('token contrast', () => {
  const css = readFileSync(new URL('../styles.css', import.meta.url), 'utf8');
  const lum = (hex: string) => {
    const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((x) => (x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  };
  const ratio = (a: string, b: string) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

  /**
   * Read one theme's custom-property block straight from styles.css.
   * Uses a selector-anchored match so it is independent of line endings and
   * of the order the two blocks appear in.
   */
  const tokens = (theme: 'light' | 'dark') => {
    const pattern =
      theme === 'light'
        ? /:root,\s*\[data-theme='light'\]\s*\{([\s\S]*?)\n\}/
        : /\[data-theme='dark'\]\s*\{([\s\S]*?)\n\}/;
    const block = pattern.exec(css)?.[1];
    expect(block, `${theme} token block`).toBeDefined();
    const map: Record<string, string> = {};
    for (const [, name, value] of block!.matchAll(/--([\w-]+):\s*(#[0-9A-Fa-f]{6})/g)) map[name] = value;
    return map;
  };

  it.each(['light', 'dark'] as const)('%s theme text and status pairs meet WCAG AA (4.5:1)', (theme) => {
    const t = tokens(theme);
    // Text on every surface it can land on, including tinted/selected ones.
    for (const [fg, bg] of [
      ['text', 'panel'], ['text', 'bg-0'], ['text', 'panel-2'],
      ['text-soft', 'panel'], ['text-soft', 'bg-0'], ['text-soft', 'panel-2'],
      ['muted', 'panel'], ['muted', 'panel-2'], ['muted', 'bg-0'],
      ['muted', 'selected-bg'],
      ['accent-text', 'panel'], ['accent-text', 'bg-0'], ['accent-text', 'selected-bg'],
      ['pending', 'panel-2'], ['processing', 'processing-soft'],
    ] as const) {
      expect(t[fg], `${theme}:${fg}`).toBeDefined();
      expect(t[bg], `${theme}:${bg}`).toBeDefined();
      expect(ratio(t[fg], t[bg]), `${theme}: ${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
    }
    // Status foreground/background pairs, on the panel and on their own tint.
    for (const status of ['success', 'warning', 'error', 'info'] as const) {
      expect(ratio(t[status], t[`${status}-soft`]), `${theme}: ${status} on soft`).toBeGreaterThanOrEqual(4.5);
      expect(ratio(t[status], t.panel), `${theme}: ${status} on panel`).toBeGreaterThanOrEqual(4.5);
    }
    // Labels on solid fills.
    expect(ratio(t['on-accent'], t.accent), `${theme}: on-accent`).toBeGreaterThanOrEqual(4.5);
    expect(ratio(t['on-error'], t.error), `${theme}: on-error`).toBeGreaterThanOrEqual(4.5);
    // Tooltip and table-header surfaces.
    expect(ratio(t['tooltip-text'], t['tooltip-bg']), `${theme}: tooltip`).toBeGreaterThanOrEqual(4.5);
    expect(ratio(t['table-header-text'], t['table-header-bg']), `${theme}: table header`).toBeGreaterThanOrEqual(4.5);
  });

  it('control boundaries reach 3:1 on their surfaces (WCAG 1.4.11)', () => {
    for (const theme of ['light', 'dark'] as const) {
      const t = tokens(theme);
      for (const bg of ['panel', 'bg-0', 'input-bg', 'panel-2'] as const) {
        expect(ratio(t['control-border'], t[bg]), `${theme}: control-border on ${bg}`).toBeGreaterThanOrEqual(3);
      }
    }
  });

  it('chart series reach 3:1 on their chart surface in both themes', () => {
    for (const theme of ['light', 'dark'] as const) {
      const t = tokens(theme);
      for (const key of ['series-1', 'series-2', 'series-3', 'series-4', 'series-5', 'series-ref'] as const) {
        expect(ratio(t[key], t['chart-bg']), `${theme}: ${key} on chart`).toBeGreaterThanOrEqual(3);
      }
    }
  });

  it('muted text survives the accent-tinted composites (chips, active nav)', () => {
    // Active chip/nav backgrounds are accent tints over a surface, so they
    // composite darker than any flat token. muted must still read on them.
    const hex = (n: number) => n.toString(16).padStart(2, '0');
    const parse = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
    const over = (fg: string, bg: string, a: number) => {
      const f = parse(fg);
      const b = parse(bg);
      return '#' + f.map((v, i) => hex(Math.round(v * a + b[i] * (1 - a)))).join('');
    };
    // `--well-rgb` equals panel-2 in light and bg-0 in dark (the chip well).
    const well: Record<'light' | 'dark', 'panel-2' | 'bg-0'> = { light: 'panel-2', dark: 'bg-0' };
    for (const theme of ['light', 'dark'] as const) {
      const t = tokens(theme);
      const chipBase = over(t[well[theme]], t.panel, 0.42);
      const surfaces = {
        'active chip': over(t.accent, chipBase, 0.08),
        'active nav': over(t.accent, t.panel, 0.16),
        'selected bg': t['selected-bg'],
      };
      for (const [label, bg] of Object.entries(surfaces)) {
        expect(ratio(t.muted, bg), `${theme}: muted on ${label}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it('no pure black or pure white dark surfaces, and no glow shadows', () => {
    const dark = tokens('dark');
    for (const key of ['bg-0', 'panel', 'panel-2'] as const) {
      expect(['#000000', '#FFFFFF']).not.toContain(dark[key].toUpperCase());
    }

    // A glow is a shadow with zero offset AND zero spread but a non-zero blur
    // (`0 0 12px colour`). Spread-only rings (`0 0 0 3px`) are legitimate focus
    // indicators, so parse each layer properly instead of pattern-matching text.
    const glows: string[] = [];
    for (const [, value] of css.matchAll(/box-shadow:\s*([^;]+);/g)) {
      for (const layer of value.split(/,(?![^(]*\))/)) {
        const nums = (layer.match(/-?\d+(?:\.\d+)?(?=px|\s|$)/g) ?? []).map(Number);
        if (nums.length >= 3 && nums[0] === 0 && nums[1] === 0 && nums[2] > 0) {
          glows.push(layer.trim());
        }
      }
    }
    expect(glows, `glow shadows found: ${glows.join(' | ')}`).toEqual([]);
  });
});
