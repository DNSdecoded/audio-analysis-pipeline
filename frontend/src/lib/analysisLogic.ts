/** Pure, unit-tested logic shared by state and sections. */

export interface CachedAnalysisLike {
  analyzed_at?: string | null;
}

export interface FileRecordLike {
  id: string;
  has_analysis: boolean;
  analyzed_at?: string | null;
}

/**
 * Cached analyses that must be discarded: the file was removed, no longer has
 * an analysis, or was re-analysed (its record carries a newer analyzed_at).
 */
export function staleAnalysisIds(
  files: FileRecordLike[],
  cache: Record<string, CachedAnalysisLike | undefined>,
): string[] {
  const byId = new Map(files.map((file) => [file.id, file]));
  return Object.keys(cache).filter((id) => {
    const record = byId.get(id);
    if (!record || !record.has_analysis) return true;
    const cached = cache[id]?.analyzed_at;
    return Boolean(record.analyzed_at && cached && record.analyzed_at !== cached);
  });
}

export interface GainRow {
  supported: boolean;
  gain: number | null;
  safeGain: number | null;
  expectedTrue: number | null;
  expectedSample: number | null;
  peakControl: number | null;
  status: 'not measurable' | 'true peak unknown' | 'not reachable by gain alone' | 'within limit';
}

/**
 * Gain preview: gain = target − measured integrated loudness.  The true-peak
 * limit caps the gain that can be applied without peak control.
 */
export function gainRow(
  integrated: number | null | undefined,
  truePeak: number | null | undefined,
  samplePeak: number | null | undefined,
  target: number,
  limit: number,
): GainRow {
  const supported = integrated !== null && integrated !== undefined && Number(integrated) > -69.9;
  const gain = supported ? target - Number(integrated) : null;
  const hasTp = truePeak !== null && truePeak !== undefined;
  const expectedTrue = gain !== null && hasTp ? Number(truePeak) + gain : null;
  const expectedSample = gain !== null && samplePeak !== null && samplePeak !== undefined ? Number(samplePeak) + gain : null;
  const maxSafe = hasTp ? limit - Number(truePeak) : null;
  return {
    supported,
    gain,
    safeGain: gain !== null && maxSafe !== null ? Math.min(gain, maxSafe) : null,
    expectedTrue,
    expectedSample,
    peakControl: expectedTrue !== null ? Math.max(0, expectedTrue - limit) : null,
    status: !supported
      ? 'not measurable'
      : expectedTrue === null
        ? 'true peak unknown'
        : expectedTrue > limit
          ? 'not reachable by gain alone'
          : 'within limit',
  };
}

/** Alignment offsets are only applied automatically when the match is reliable. */
export function shouldApplyAlignment(result: { offset_seconds?: number | null; confidence_label?: string | null }): boolean {
  return result.offset_seconds !== null && result.offset_seconds !== undefined && result.confidence_label !== 'low';
}
