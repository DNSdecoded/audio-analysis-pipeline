import type { Analysis, FileRecord, QCCheck } from '../types';

const LABELS: Record<string, string> = {
  low_band_share_pct: 'Low-band share',
  high_band_share_pct: 'High-band share',
  centroid_hz: 'Centroid',
  short_term_std_lu: 'Short-term σ',
  lra_lu: 'LRA',
  plr_db: 'PLR',
  crest_factor_db: 'Crest factor',
  correlation: 'Correlation',
  mono_loss_db: 'Mono loss',
  balance_db: 'Balance',
  left_rms_dbfs: 'Left RMS',
  right_rms_dbfs: 'Right RMS',
  side_to_mid_ratio: 'Side/mid',
  width_percent: 'Width',
};

const UNITS: Record<string, string> = {
  _pct: '%', _percent: '%', _hz: 'Hz', _db: 'dB', _dbfs: 'dBFS', _lu: 'LU', _lufs: 'LUFS',
};

function unitFor(key: string): string {
  const suffix = Object.keys(UNITS).find((s) => key.endsWith(s));
  return suffix ? ` ${UNITS[suffix]}` : '';
}

function num(value: number): string {
  if (!Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  const digits = abs !== 0 && abs < 0.01 ? 5 : abs < 1 ? 3 : abs >= 1000 ? 0 : 2;
  return value.toLocaleString('en-US', { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

/**
 * Human-readable text for a QC measured value.  The backend sends numbers,
 * strings, arrays and structured objects (bands, peaks, key/value maps); raw
 * JSON is never shown to the user.
 */
export function formatMeasurement(value: unknown, unit?: string | null): string {
  if (value === null || value === undefined) return 'Not available';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') return `${num(value)}${unit && unit !== 'confidence' ? ` ${unit}` : ''}`;
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) {
    const shown = value.slice(0, 4).map((item) => formatMeasurement(item));
    return shown.join(', ') + (value.length > 4 ? ` … (+${value.length - 4})` : '');
  }
  if (typeof value === 'object') {
    const obj = value as Record<string, any>;
    if (Array.isArray(obj.peaks)) {
      const top = obj.peaks.slice(0, 3).map((p: any) => `${num(p.frequency_hz)} Hz (${num(p.prominence_db)} dB prominence)`);
      return top.length ? `Peaks: ${top.join('; ')}` : 'No peaks';
    }
    if (Array.isArray(obj.bands)) {
      const top = obj.bands.slice(0, 4).map((b: any) => `${b.band}: ${num(b.variation_db)} dB`);
      return `Band variation — ${top.join('; ')}`;
    }
    if (Array.isArray(obj.regions)) {
      return `${obj.regions.length} region(s)`;
    }
    const parts = Object.entries(obj)
      .filter(([, v]) => typeof v === 'number' || typeof v === 'string' || typeof v === 'boolean')
      .map(([k, v]) => `${LABELS[k] ?? k.replace(/_/g, ' ')}: ${typeof v === 'number' ? num(v) + unitFor(k) : String(v)}`);
    return parts.length ? parts.join(' · ') : '—';
  }
  return String(value);
}

/**
 * The backend reports the *warning* threshold on each check.  For a check
 * classified as an error, the limit that actually caused it is the matching
 * error threshold, so both are shown (UI-19).
 */
const ERROR_THRESHOLD: Record<string, { key: string; unit: string; below?: boolean }> = {
  clipping: { key: 'clipping_percent_error', unit: '%' },
  true_peak: { key: 'true_peak_error_dbtp', unit: 'dBTP' },
  correlation: { key: 'correlation_error', unit: 'r', below: true },
  channel_imbalance: { key: 'channel_imbalance_error_db', unit: 'dB' },
  noise: { key: 'noise_floor_error_dbfs', unit: 'dBFS' },
  silence: { key: 'silence_percent_error', unit: '%' },
};

export function formatLimit(
  check: Pick<QCCheck, 'id' | 'severity' | 'threshold_value' | 'threshold_unit'>,
  thresholds?: Record<string, unknown> | null,
): string {
  const error = ERROR_THRESHOLD[check.id];
  const errorValue = error && thresholds ? thresholds[error.key] : undefined;
  if (check.severity === 'error' && typeof errorValue === 'number') {
    const op = error.below ? '≤' : '≥';
    const warn = typeof check.threshold_value === 'number' ? ` · warning ${op} ${num(check.threshold_value)} ${error.unit}` : '';
    return `critical ${op} ${num(errorValue)} ${error.unit}${warn}`;
  }
  const value = check.threshold_value;
  if (value === null || value === undefined) return '—';
  const unit = check.threshold_unit ?? '';
  if (Array.isArray(value)) {
    if (value.length === 2 && value.every((v) => typeof v === 'number')) {
      return `${num(value[0])} to ${num(value[1])} ${unit.replace(/ range$/, '')}`.trim();
    }
    return `${value.slice(0, 6).join(', ')}${value.length > 6 ? '…' : ''} ${unit}`.trim();
  }
  return typeof value === 'number' ? `${num(value)} ${unit}`.trim() : `${String(value)} ${unit}`.trim();
}

export interface Finding {
  fileId: string;
  fileName: string;
  check: QCCheck;
}

const ORDER: Record<string, number> = { error: 0, warning: 1, information: 2, normal: 3 };

export function collectFindings(
  files: Pick<FileRecord, 'id' | 'original_name'>[],
  analyses: Record<string, Pick<Analysis, 'qc'> | undefined>,
  severities: string[],
  query = '',
): Finding[] {
  const q = query.trim().toLowerCase();
  const out: Finding[] = [];
  for (const file of files) {
    const checks = analyses[file.id]?.qc?.checks ?? [];
    for (const check of checks) {
      if (!severities.includes(check.severity)) continue;
      if (q && !`${check.title} ${check.category} ${check.message} ${file.original_name}`.toLowerCase().includes(q)) continue;
      out.push({ fileId: file.id, fileName: file.original_name, check });
    }
  }
  return out.sort(
    (a, b) =>
      (ORDER[a.check.severity] ?? 9) - (ORDER[b.check.severity] ?? 9) ||
      a.fileName.localeCompare(b.fileName) ||
      a.check.title.localeCompare(b.check.title),
  );
}
