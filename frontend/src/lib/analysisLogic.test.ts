import { describe, expect, it } from 'vitest';
import { gainRow, shouldApplyAlignment, staleAnalysisIds } from './analysisLogic';

describe('staleAnalysisIds (BUG-24)', () => {
  const files = [
    { id: 'a', has_analysis: true, analyzed_at: '2026-11-25T10:00:00+00:00' },
    { id: 'b', has_analysis: true, analyzed_at: '2026-11-25T12:00:00+00:00' },
    { id: 'c', has_analysis: false, analyzed_at: null },
  ];

  it('keeps current analyses', () => {
    expect(staleAnalysisIds(files, { a: { analyzed_at: '2026-11-25T10:00:00+00:00' } })).toEqual([]);
  });

  it('drops re-analysed, removed and analysis-less files', () => {
    const cache = {
      a: { analyzed_at: '2026-11-25T10:00:00+00:00' },
      b: { analyzed_at: '2026-11-25T09:00:00+00:00' }, // superseded
      c: { analyzed_at: '2026-11-25T08:00:00+00:00' }, // no longer analysed
      gone: { analyzed_at: '2026-11-25T08:00:00+00:00' }, // removed
    };
    expect(staleAnalysisIds(files, cache).sort()).toEqual(['b', 'c', 'gone']);
  });
});

describe('gainRow (BUG-22)', () => {
  it('computes gain = target − measured and respects the true-peak limit', () => {
    const row = gainRow(-20, -1.5, -2, -14, -1);
    expect(row.gain).toBeCloseTo(6);
    expect(row.expectedTrue).toBeCloseTo(4.5);
    expect(row.safeGain).toBeCloseTo(0.5);
    expect(row.peakControl).toBeCloseTo(5.5);
    expect(row.status).toBe('not reachable by gain alone');
  });

  it('reports within limit when the target is reachable', () => {
    const row = gainRow(-20, -11.5, -12, -14, -1);
    expect(row.safeGain).toBeCloseTo(6);
    expect(row.peakControl).toBe(0);
    expect(row.status).toBe('within limit');
  });

  it('does not recommend gain for silence', () => {
    const row = gainRow(null, -160, -160, -14, -1);
    expect(row.supported).toBe(false);
    expect(row.gain).toBeNull();
    expect(row.status).toBe('not measurable');
  });
});

describe('shouldApplyAlignment (BUG-26)', () => {
  it('never applies a low-confidence offset', () => {
    expect(shouldApplyAlignment({ offset_seconds: 1.2, confidence_label: 'low' })).toBe(false);
    expect(shouldApplyAlignment({ offset_seconds: null, confidence_label: 'high' })).toBe(false);
    expect(shouldApplyAlignment({ offset_seconds: -1.5, confidence_label: 'high' })).toBe(true);
  });
});
