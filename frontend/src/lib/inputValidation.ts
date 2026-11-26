/**
 * Pure validation helpers shared by every form that sends numeric analysis
 * parameters to the API.  The limits mirror the request models in
 * backend/app/main.py so invalid values are caught beside the field instead
 * of surfacing as a 422 toast after the request.
 */

/** Parse a numeric <input> value: an empty field is NaN, never 0. */
export function parseNumberInput(value: string): number {
  if (value.trim() === '') return Number.NaN;
  return Number(value);
}

/** FFT sizes offered by the analysis engine (powers of two). */
export const FFT_SIZES = [256, 512, 1024, 2048, 4096, 8192, 16384, 32768];
/** Hop lengths offered by the analysis engine. */
export const HOP_SIZES = [32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384];

export interface FieldErrors {
  [field: string]: string | undefined;
}

export function hasErrors(errors: FieldErrors): boolean {
  return Object.values(errors).some(Boolean);
}

/**
 * Optional start/end range in seconds.  Empty strings mean "from the start" /
 * "to the end".  Returns per-field messages.
 */
export function validateTimeRange(start: string, end: string, duration: number): { start?: string; end?: string } {
  const errors: { start?: string; end?: string } = {};
  const s = start.trim() === '' ? undefined : Number(start);
  const e = end.trim() === '' ? undefined : Number(end);
  const max = Number.isFinite(duration) && duration > 0 ? duration : Number.POSITIVE_INFINITY;
  const maxText = Number.isFinite(max) ? `${max.toFixed(2)} s` : 'the file duration';
  if (s !== undefined && (!Number.isFinite(s) || s < 0)) errors.start = 'Start must be 0 s or later.';
  else if (s !== undefined && s >= max) errors.start = `Start must be before the end of the file (${maxText}).`;
  if (e !== undefined && (!Number.isFinite(e) || e <= 0)) errors.end = 'End must be greater than 0 s.';
  else if (e !== undefined && e > max + 0.01) errors.end = `End cannot exceed the file duration (${maxText}).`;
  if (!errors.start && !errors.end && s !== undefined && e !== undefined && e <= s) errors.end = 'End must be greater than start.';
  if (!errors.start && !errors.end && s !== undefined && e === undefined && !Number.isFinite(max)) errors.end = 'Enter an end time.';
  return errors;
}

/** FFT size and hop length for on-demand spectrum / spectrogram computations. */
export function validateFftHop(nFft: number, hop: number): { nFft?: string; hop?: string } {
  const errors: { nFft?: string; hop?: string } = {};
  if (!FFT_SIZES.includes(nFft)) errors.nFft = `FFT size must be a power of two from ${FFT_SIZES[0]} to ${FFT_SIZES.at(-1)}.`;
  if (!Number.isInteger(hop) || hop < 32 || hop > 16384) errors.hop = 'Hop length must be a whole number from 32 to 16384 samples.';
  else if (!errors.nFft && hop > nFft) errors.hop = 'Hop length cannot exceed the FFT size (frames would skip audio).';
  return errors;
}

/** Loudness target and true-peak limit (same limits as Settings and the API). */
export function validateLoudnessTargets(target: number, limit: number): { target?: string; limit?: string } {
  const errors: { target?: string; limit?: string } = {};
  if (!Number.isFinite(target) || target < -60 || target > 0) errors.target = 'Target loudness must be between −60 and 0 LUFS.';
  if (!Number.isFinite(limit) || limit < -20 || limit > 0) errors.limit = 'True-peak limit must be between −20 and 0 dBTP.';
  return errors;
}

/** Spectrogram colour range. */
export function validateColorRange(floor: number, ceiling: number): { floor?: string; ceiling?: string } {
  const errors: { floor?: string; ceiling?: string } = {};
  if (!Number.isFinite(floor) || floor < -160 || floor > 20) errors.floor = 'Floor must be between −160 and 20 dB.';
  if (!Number.isFinite(ceiling) || ceiling < -150 || ceiling > 20) errors.ceiling = 'Ceiling must be between −150 and 20 dB.';
  if (!errors.floor && !errors.ceiling && ceiling <= floor) errors.ceiling = 'Ceiling must be higher than the floor.';
  return errors;
}

/** Clamp a waveform selection to the file and keep end > start. */
export function clampSelection(start: number, end: number, duration: number, minSpan = 0.01): { start: number; end: number } | null {
  if (!Number.isFinite(start) || !Number.isFinite(end) || !(duration > 0)) return null;
  const s = Math.min(Math.max(0, start), Math.max(0, duration - minSpan));
  const e = Math.min(Math.max(s + minSpan, end), duration);
  return e > s ? { start: s, end: e } : null;
}

/** Filename from a Content-Disposition header (RFC 6266 filename* preferred). */
export function filenameFromDisposition(header: string | null | undefined, fallback: string): string {
  if (!header) return fallback;
  const star = /filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/.exec(header);
  if (star) {
    try {
      return decodeURIComponent(star[1].trim().replace(/^"|"$/g, ''));
    } catch {
      /* fall through to the ASCII form */
    }
  }
  const plain = /filename\s*=\s*"([^"]+)"/.exec(header) ?? /filename\s*=\s*([^;]+)/.exec(header);
  return plain ? plain[1].trim() : fallback;
}

export interface UploadCandidate {
  name: string;
  size: number;
}

export interface UploadPrecheck<T extends UploadCandidate> {
  accepted: T[];
  rejected: { file_name: string; errors: string[]; warnings: string[] }[];
  duplicates: T[];
}

/**
 * Checks that need no server round-trip: extension, size and files that are
 * already in the session (same name and byte size).  The server still
 * validates the container signature of everything that is accepted here.
 */
export function precheckUploads<T extends UploadCandidate>(
  candidates: T[],
  existing: { original_name: string; size_bytes?: number | null }[],
  options: { extensions?: string[]; maxBytes?: number } = {},
): UploadPrecheck<T> {
  const result: UploadPrecheck<T> = { accepted: [], rejected: [], duplicates: [] };
  const extensions = (options.extensions ?? []).map((ext) => ext.toLowerCase());
  const seen = new Set(existing.map((file) => `${file.original_name}|${file.size_bytes ?? ''}`));
  const batch = new Set<string>();
  for (const file of candidates) {
    const dot = file.name.lastIndexOf('.');
    const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : '';
    if (extensions.length && !extensions.includes(ext)) {
      result.rejected.push({ file_name: file.name, errors: [`Unsupported file type '${ext || 'none'}'. Supported: ${extensions.join(', ')}.`], warnings: [] });
      continue;
    }
    if (options.maxBytes && file.size > options.maxBytes) {
      result.rejected.push({ file_name: file.name, errors: [`File is larger than the ${Math.round(options.maxBytes / 1024 / 1024)} MB limit.`], warnings: [] });
      continue;
    }
    if (file.size === 0) {
      result.rejected.push({ file_name: file.name, errors: ['File is empty (0 bytes).'], warnings: [] });
      continue;
    }
    const key = `${file.name}|${file.size}`;
    if (seen.has(key) || batch.has(key)) result.duplicates.push(file);
    else result.accepted.push(file);
    batch.add(key);
  }
  return result;
}
