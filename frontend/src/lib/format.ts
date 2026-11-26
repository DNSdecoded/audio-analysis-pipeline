export const PITCH_CLASSES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

export function fmt(value: unknown, digits = 1, fallback = '—'): string {
  if (value === null || value === undefined || value === '') return fallback;
  const number = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(number)) return fallback;
  if (Math.abs(number) >= 1000) return number.toLocaleString(undefined, { maximumFractionDigits: digits });
  return number.toFixed(digits);
}

export function fmtSigned(value: unknown, digits = 2, unit = ''): string {
  if (value === null || value === undefined) return '—';
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  return `${number >= 0 ? '+' : ''}${number.toFixed(digits)}${unit ? ` ${unit}` : ''}`;
}

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—';
  const total = Math.max(0, seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${s.toFixed(1).padStart(4, '0')}`;
  return `${m}:${s.toFixed(1).padStart(4, '0')}`;
}

export function fmtBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

export function fmtDate(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export function titleCase(value: string | null | undefined): string {
  if (!value) return '';
  return value.replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export function severityClass(value: string | null | undefined): string {
  switch (value) {
    case 'error':
      return 'sev-error';
    case 'warning':
      return 'sev-warning';
    case 'information':
    case 'info':
      return 'sev-info';
    case 'normal':
      return 'sev-normal';
    default:
      return 'sev-neutral';
  }
}

export function statusClass(value: string | null | undefined): string {
  switch (value) {
    case 'complete':
      return 'status-complete';
    case 'analyzing':
    case 'running':
      return 'status-running';
    case 'queued':
      return 'status-queued';
    case 'error':
    case 'failed':
      return 'status-error';
    case 'validated':
      return 'status-validated';
    default:
      return 'status-neutral';
  }
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function rmsDbToAmplitude(db: number): number {
  return Math.pow(10, db / 20);
}

export function correlationLabel(value: number): string {
  if (value > 0.85) return 'Very correlated / narrow';
  if (value > 0.4) return 'Correlated';
  if (value > -0.1) return 'Wide / partially correlated';
  if (value > -0.5) return 'Out of phase';
  return 'Severe phase cancellation';
}

export function confidencePercent(value: number | null | undefined): number {
  if (value === null || value === undefined) return 0;
  const n = Number(value);
  return Number.isFinite(n) ? Math.round(clamp(n, 0, 1) * 100) : 0;
}

export function makeId(prefix = 'id'): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 9)}`;
}

export function downloadText(text: string, filename: string, mime = 'text/plain') {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export function groupBy<T>(items: T[], key: (item: T) => string): Record<string, T[]> {
  return items.reduce<Record<string, T[]>>((acc, item) => {
    const k = key(item);
    (acc[k] ||= []).push(item);
    return acc;
  }, {});
}

/**
 * Number with unit, or a bare dash when the value is missing — never "— Hz"
 * or "— dBTP" (a unit beside a missing value reads like a measurement).
 */
export function fmtUnit(value: unknown, unit: string, digits = 1): string {
  const text = fmt(value, digits);
  return text === '—' ? '—' : `${text} ${unit}`;
}

/** Sample rate in Hz with thousands separators, or a dash. */
export function fmtHz(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  return `${Number(value).toLocaleString()} Hz`;
}
