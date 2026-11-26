export interface FindingLine {
  label: string;
  /** Either per-file values or a single value. */
  values: { name: string; value: string }[];
}

const LABELS: Record<string, string> = {
  sample_rates_hz: 'Sample rate (Hz)',
  bit_depths_bits: 'Bit depth (bits)',
  channels: 'Channels',
  integrated_lufs: 'Integrated loudness (LUFS)',
  difference_lu: 'Difference (LU)',
  durations_seconds: 'Duration (s)',
  difference_seconds: 'Difference (s)',
  keys: 'Estimated key',
  tempo_bpm: 'Tempo (BPM)',
  ratio: 'Rate ratio',
  rates_hz: 'Rates (Hz)',
};

function show(value: unknown): string {
  if (value === null || value === undefined) return 'not available';
  if (typeof value === 'number') return Number.isInteger(value) ? value.toLocaleString('en-US') : value.toFixed(2);
  if (Array.isArray(value)) return value.map(show).join(', ');
  return String(value);
}

/**
 * Turn a cross-file finding's measurement object into labelled rows, mapping
 * internal file IDs (fil_…) to the file names the user knows.
 */
export function describeFindingMeasurement(measurement: Record<string, unknown> | null | undefined, names: Record<string, string>): FindingLine[] {
  if (!measurement || typeof measurement !== 'object') return [];
  return Object.entries(measurement).map(([key, value]) => {
    const label = LABELS[key] ?? key.replace(/_/g, ' ');
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      return {
        label,
        values: Object.entries(value as Record<string, unknown>).map(([fileId, v]) => ({ name: names[fileId] ?? fileId, value: show(v) })),
      };
    }
    return { label, values: [{ name: '', value: show(value) }] };
  });
}

export interface RowLike {
  key: string;
  label: string;
  group: string;
  status: string;
  spread: number | null;
}

export type RowSort = 'group' | 'name' | 'status' | 'spread';
const STATUS_RANK: Record<string, number> = { large_deviation: 0, different: 1, low_confidence: 2, unsupported: 3, match: 4 };

export function filterRows<T extends RowLike>(rows: T[], statuses: string[], query: string): T[] {
  const q = query.trim().toLowerCase();
  return rows.filter(
    (row) => statuses.includes(row.status) && (!q || `${row.label} ${row.group}`.toLowerCase().includes(q)),
  );
}

export function sortRows<T extends RowLike>(rows: T[], sort: RowSort): T[] {
  const copy = rows.slice();
  if (sort === 'name') copy.sort((a, b) => a.label.localeCompare(b.label));
  else if (sort === 'status') copy.sort((a, b) => (STATUS_RANK[a.status] ?? 9) - (STATUS_RANK[b.status] ?? 9) || a.label.localeCompare(b.label));
  else if (sort === 'spread') copy.sort((a, b) => (b.spread ?? -Infinity) - (a.spread ?? -Infinity));
  return copy;
}

export type SortDir = 'asc' | 'desc';

/** Generic column sort that keeps missing values last in both directions. */
export function sortBy<T>(items: T[], value: (item: T) => number | string | null | undefined, dir: SortDir): T[] {
  return items.slice().sort((a, b) => {
    const va = value(a);
    const vb = value(b);
    const aMissing = va === null || va === undefined || (typeof va === 'number' && !Number.isFinite(va));
    const bMissing = vb === null || vb === undefined || (typeof vb === 'number' && !Number.isFinite(vb));
    if (aMissing && bMissing) return 0;
    if (aMissing) return 1;
    if (bMissing) return -1;
    const cmp = typeof va === 'number' && typeof vb === 'number' ? va - vb : String(va).localeCompare(String(vb));
    return dir === 'asc' ? cmp : -cmp;
  });
}
