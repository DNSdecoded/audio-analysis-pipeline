export interface SettingsDraft {
  name: string;
  target: number;
  limit: number;
  fftSize: number;
  hopLength: number;
}

/**
 * Client-side validation mirroring the API limits (SessionPatch in
 * backend/app/main.py) plus combinations the server would silently clamp.
 */
export function validateSettings(draft: SettingsDraft): Partial<Record<keyof SettingsDraft, string>> {
  const errors: Partial<Record<keyof SettingsDraft, string>> = {};
  if (!draft.name.trim()) errors.name = 'Enter a session name.';
  if (!Number.isFinite(draft.target) || draft.target < -60 || draft.target > 0) {
    errors.target = 'Target loudness must be between −60 and 0 LUFS.';
  }
  if (!Number.isFinite(draft.limit) || draft.limit < -20 || draft.limit > 0) {
    errors.limit = 'True-peak limit must be between −20 and 0 dBTP.';
  }
  if (!Number.isInteger(draft.fftSize) || draft.fftSize < 256 || draft.fftSize > 16384 || draft.fftSize % 2 !== 0) {
    errors.fftSize = 'FFT size must be an even number of samples from 256 to 16384.';
  }
  if (!Number.isInteger(draft.hopLength) || draft.hopLength < 32) {
    errors.hopLength = 'Hop length must be at least 32 samples.';
  } else if (draft.hopLength > draft.fftSize) {
    errors.hopLength = 'Hop length cannot exceed the FFT size (frames would skip audio).';
  }
  return errors;
}
