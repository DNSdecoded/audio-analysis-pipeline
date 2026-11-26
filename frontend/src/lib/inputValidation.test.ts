import { describe, expect, it } from 'vitest';
import {
  clampSelection,
  filenameFromDisposition,
  FFT_SIZES,
  hasErrors,
  parseNumberInput,
  precheckUploads,
  validateColorRange,
  validateFftHop,
  validateLoudnessTargets,
  validateTimeRange,
} from './inputValidation';
import { fmtHz, fmtUnit } from './format';
import { formatMeasurement } from './qcFindings';

describe('parseNumberInput', () => {
  it('treats an empty field as NaN, not 0 (FE-08)', () => {
    expect(parseNumberInput('')).toBeNaN();
    expect(parseNumberInput('   ')).toBeNaN();
    expect(parseNumberInput('-14.5')).toBe(-14.5);
    expect(parseNumberInput('0')).toBe(0);
  });
});

describe('validateTimeRange (FE-06, FE-07, FE-13)', () => {
  it('accepts empty (full file) and valid ranges', () => {
    expect(validateTimeRange('', '', 10)).toEqual({});
    expect(validateTimeRange('1', '2.5', 10)).toEqual({});
    expect(validateTimeRange('1', '', 10)).toEqual({});
  });
  it('rejects ranges outside the file or reversed', () => {
    expect(validateTimeRange('999', '', 10).start).toMatch(/before the end/);
    expect(validateTimeRange('-1', '2', 10).start).toMatch(/0 s or later/);
    expect(validateTimeRange('0', '11', 10).end).toMatch(/cannot exceed/);
    expect(validateTimeRange('5', '4', 10).end).toMatch(/greater than start/);
    expect(validateTimeRange('', '0', 10).end).toMatch(/greater than 0/);
  });
  it('allows the rounding slack at the end of the file', () => {
    expect(validateTimeRange('0', '10.005', 10)).toEqual({});
  });
});

describe('validateFftHop (FE-07)', () => {
  it('only allows power-of-two FFT sizes and hop ≤ FFT', () => {
    expect(FFT_SIZES.every((v) => (v & (v - 1)) === 0)).toBe(true);
    expect(validateFftHop(4096, 1024)).toEqual({});
    expect(validateFftHop(1000, 256).nFft).toBeTruthy();
    expect(validateFftHop(512, 1024).hop).toMatch(/cannot exceed/);
    expect(validateFftHop(4096, 5000.5).hop).toBeTruthy();
    expect(validateFftHop(4096, 16).hop).toBeTruthy();
  });
});

describe('validateLoudnessTargets (FE-11)', () => {
  it('mirrors the API limits', () => {
    expect(validateLoudnessTargets(-14, -1)).toEqual({});
    expect(validateLoudnessTargets(-60, -20)).toEqual({});
    expect(validateLoudnessTargets(-61, -1).target).toBeTruthy();
    expect(validateLoudnessTargets(1, -1).target).toBeTruthy();
    expect(validateLoudnessTargets(-14, 0.5).limit).toBeTruthy();
    expect(hasErrors(validateLoudnessTargets(Number.NaN, -1))).toBe(true);
  });
});

describe('validateColorRange (FE-07)', () => {
  it('requires ceiling above floor', () => {
    expect(validateColorRange(-100, 0)).toEqual({});
    expect(validateColorRange(-10, -20).ceiling).toMatch(/higher than the floor/);
    expect(validateColorRange(Number.NaN, 0).floor).toBeTruthy();
  });
});

describe('clampSelection', () => {
  it('keeps the selection inside the file with end > start', () => {
    expect(clampSelection(-2, 3, 10)).toEqual({ start: 0, end: 3 });
    expect(clampSelection(2, 50, 10)).toEqual({ start: 2, end: 10 });
    expect(clampSelection(1, 1, 10)).toEqual({ start: 1, end: 1.01 });
    expect(clampSelection(1, 2, 0)).toBeNull();
  });
});

describe('filenameFromDisposition (FE-15)', () => {
  it('prefers the RFC 6266 UTF-8 name and falls back to the ASCII one', () => {
    expect(filenameFromDisposition(`inline; filename="clip_.wav-waveform.png"; filename*=UTF-8''clip%C3%A9.wav-waveform.png`, 'x.png')).toBe('clipé.wav-waveform.png');
    expect(filenameFromDisposition('attachment; filename="report.pdf"', 'x.pdf')).toBe('report.pdf');
    expect(filenameFromDisposition(null, 'waveform.png')).toBe('waveform.png');
  });
});

describe('precheckUploads (FE-28)', () => {
  const existing = [{ original_name: 'a.wav', size_bytes: 100 }];
  it('splits accepted, rejected and duplicate files', () => {
    const result = precheckUploads(
      [
        { name: 'a.wav', size: 100 },
        { name: 'a.wav', size: 101 },
        { name: 'notes.txt', size: 5 },
        { name: 'big.wav', size: 2_000_000 },
        { name: 'empty.flac', size: 0 },
        { name: 'b.WAV', size: 10 },
        { name: 'b.WAV', size: 10 },
      ],
      existing,
      { extensions: ['.wav', '.flac'], maxBytes: 1_000_000 },
    );
    expect(result.accepted.map((f) => `${f.name}:${f.size}`)).toEqual(['a.wav:101', 'b.WAV:10']);
    expect(result.duplicates.map((f) => `${f.name}:${f.size}`)).toEqual(['a.wav:100', 'b.WAV:10']);
    expect(result.rejected.map((f) => f.file_name)).toEqual(['notes.txt', 'big.wav', 'empty.flac']);
  });
});

describe('unit formatting (FE-22)', () => {
  it('never prints a unit beside a missing value', () => {
    expect(fmtUnit(null, 'dBTP')).toBe('—');
    expect(fmtUnit(-1.234, 'dBTP')).toBe('-1.2 dBTP');
    expect(fmtHz(undefined)).toBe('—');
    expect(fmtHz(48000)).toMatch(/48.000 Hz|48,000 Hz/);
  });
});

describe('structured measurements (FE-04)', () => {
  it('formats stereo / dynamics measurement objects without JSON', () => {
    const text = formatMeasurement({ correlation: -1, mono_loss_db: -85.4 });
    expect(text).toBe('Correlation: -1 · Mono loss: -85.4 dB');
    expect(formatMeasurement({ lra_lu: 0 })).toBe('LRA: 0 LU');
    expect(text).not.toMatch(/[{}"]/);
  });
});
