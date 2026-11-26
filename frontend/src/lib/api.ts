import type {
  AlignmentResult,
  Analysis,
  AppSettings,
  Comparison,
  Job,
  Overview,
  Session,
  WaveformResponse,
} from '../types';
import { filenameFromDisposition } from './inputValidation';

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';
const API_KEY = (import.meta.env.VITE_API_KEY as string | undefined) ?? '';

export class ApiError extends Error {
  status: number;
  detail: any;
  constructor(status: number, detail: any) {
    super(typeof detail === 'string' ? detail : detail?.detail ?? 'Request failed');
    this.status = status;
    this.detail = detail;
  }
}

/** Raised when the user cancels an upload in progress. */
export class UploadCancelledError extends Error {
  constructor() {
    super('Upload cancelled');
    this.name = 'UploadCancelledError';
  }
}

function headers(extra: Record<string, string> = {}): Record<string, string> {
  const h: Record<string, string> = { ...extra };
  if (API_KEY) h['X-API-Key'] = API_KEY;
  return h;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: headers({
      ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(options.headers as Record<string, string> | undefined),
    }),
  });
  if (!response.ok) {
    let detail: any = response.statusText;
    try {
      detail = await response.json();
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  createSession: (name?: string) =>
    request<Session>('/api/sessions', {
      method: 'POST',
      body: JSON.stringify({ name: name ?? 'Audio analysis session' }),
    }),

  getSession: (sessionId: string) => request<Session>(`/api/sessions/${sessionId}`),

  getOverview: (sessionId: string) => request<Overview>(`/api/sessions/${sessionId}/overview`),

  patchSession: (
    sessionId: string,
    body: Partial<{
      name: string;
      target_lufs: number;
      true_peak_limit: number;
      fft_size: number;
      hop_length: number;
      qc_thresholds: Record<string, unknown>;
    }>,
  ) =>
    request<Session>(`/api/sessions/${sessionId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  deleteSession: (sessionId: string) =>
    request<{ deleted: boolean }>(`/api/sessions/${sessionId}`, { method: 'DELETE' }),

  uploadFiles: (
    sessionId: string,
    files: File[],
    onProgress?: (percent: number) => void,
    signal?: AbortSignal,
  ): Promise<{ files: any[]; errors: any[]; session: Session }> =>
    new Promise((resolve, reject) => {
      if (signal?.aborted) {
        reject(new UploadCancelledError());
        return;
      }
      const form = new FormData();
      files.forEach((file) => form.append('files', file, file.name));
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${API_BASE}/api/sessions/${sessionId}/files`);
      if (API_KEY) xhr.setRequestHeader('X-API-Key', API_KEY);
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && onProgress) {
          onProgress(Math.round((event.loaded / event.total) * 100));
        }
      };
      xhr.onload = () => {
        let payload: any = null;
        try {
          payload = JSON.parse(xhr.responseText);
        } catch {
          payload = xhr.responseText;
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(payload);
        } else {
          reject(new ApiError(xhr.status, payload));
        }
      };
      xhr.onerror = () => reject(new ApiError(0, 'Network error during upload'));
      xhr.onabort = () => reject(new UploadCancelledError());
      signal?.addEventListener('abort', () => xhr.abort(), { once: true });
      xhr.send(form);
    }),

  analyze: (
    sessionId: string,
    body: {
      file_ids?: string[];
      force?: boolean;
      target_lufs?: number;
      true_peak_limit?: number;
      fft_size?: number;
      hop_length?: number;
    },
  ) =>
    request<{ jobs: Job[]; skipped: any[]; errors: any[]; session: Session }>(
      `/api/sessions/${sessionId}/analyze`,
      { method: 'POST', body: JSON.stringify(body) },
    ),

  analyzeFile: (sessionId: string, fileId: string) =>
    request<{ job: Job; session: Session }>(
      `/api/sessions/${sessionId}/files/${fileId}/analyze`,
      { method: 'POST' },
    ),

  getJob: (jobId: string) => request<Job>(`/api/jobs/${jobId}`),

  removeFile: (sessionId: string, fileId: string) =>
    request<{ deleted: boolean; session: Session }>(
      `/api/sessions/${sessionId}/files/${fileId}`,
      { method: 'DELETE' },
    ),

  getAnalysis: (sessionId: string, fileId: string) =>
    request<Analysis>(`/api/sessions/${sessionId}/files/${fileId}/analysis`),

  getWaveform: (
    sessionId: string,
    fileId: string,
    params: { start?: number; end?: number; buckets?: number } = {},
  ) => {
    const query = new URLSearchParams();
    if (params.start !== undefined) query.set('start', String(params.start));
    if (params.end !== undefined) query.set('end', String(params.end));
    if (params.buckets !== undefined) query.set('buckets', String(params.buckets));
    return request<WaveformResponse>(
      `/api/sessions/${sessionId}/files/${fileId}/waveform?${query.toString()}`,
    );
  },

  getSpectrum: (
    sessionId: string,
    fileId: string,
    params: {
      start?: number;
      end?: number;
      n_fft?: number;
      hop_length?: number;
    } = {},
  ) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null) query.set(key, String(value));
    });
    return request<any>(
      `/api/sessions/${sessionId}/files/${fileId}/spectrum?${query.toString()}`,
    );
  },

  getSpectrogram: (
    sessionId: string,
    fileId: string,
    params: {
      start?: number;
      end?: number;
      n_fft?: number;
      hop_length?: number;
      max_frames?: number;
    } = {},
  ) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null) query.set(key, String(value));
    });
    return request<any>(
      `/api/sessions/${sessionId}/files/${fileId}/spectrogram?${query.toString()}`,
    );
  },

  segmentAnalysis: (
    sessionId: string,
    fileId: string,
    body: { start: number; end: number; target_lufs?: number; true_peak_limit?: number },
  ) =>
    request<Analysis>(
      `/api/sessions/${sessionId}/files/${fileId}/segment-analysis`,
      { method: 'POST', body: JSON.stringify(body) },
    ),

  compare: (
    sessionId: string,
    body: {
      file_ids: string[];
      parameters?: string[];
      target_lufs?: number;
      true_peak_limit?: number;
      reference_file_id?: string;
      mode?: 'full' | 'segment';
      ranges?: Record<string, { start: number; end: number }>;
    },
  ) =>
    request<Comparison>(`/api/sessions/${sessionId}/compare`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  align: (
    sessionId: string,
    body: {
      file_a: string;
      file_b: string;
      method?: 'auto' | 'envelope' | 'waveform';
      max_offset_seconds?: number;
      manual_offset_seconds?: number;
    },
  ) =>
    request<AlignmentResult>(`/api/sessions/${sessionId}/align`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  recomputeQc: (sessionId: string, thresholds?: Record<string, unknown>) =>
    request<any>(`/api/sessions/${sessionId}/qc/recompute`, {
      method: 'POST',
      body: JSON.stringify({ thresholds: thresholds ?? null }),
    }),

  getAppSettings: () => request<AppSettings>('/api/settings'),

  downloadReport: async (
    sessionId: string,
    body: {
      format: 'pdf' | 'json' | 'csv' | 'qc-csv' | 'comparison-csv';
      file_ids?: string[];
      include_comparison?: boolean;
      parameters?: string[];
      target_lufs?: number;
      true_peak_limit?: number;
      reference_file_id?: string;
    },
  ) => {
    const response = await fetch(`${API_BASE}/api/sessions/${sessionId}/reports`, {
      method: 'POST',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      let detail: any = response.statusText;
      try {
        detail = await response.json();
      } catch {
        /* ignore */
      }
      throw new ApiError(response.status, detail);
    }
    const blob = await response.blob();
    const filename = filenameFromDisposition(response.headers.get('Content-Disposition'), `audio-analysis.${body.format}`);
    downloadBlob(blob, filename);
    return filename;
  },

  downloadPlot: async (
    sessionId: string,
    fileId: string,
    kind: string,
    options: { log?: boolean; width?: number; height?: number; start?: number; end?: number } = {},
  ) => {
    const query = new URLSearchParams();
    if (options.log) query.set('log', 'true');
    if (options.width) query.set('width', String(options.width));
    if (options.height) query.set('height', String(options.height));
    if (options.start !== undefined) query.set('start', String(options.start));
    if (options.end !== undefined) query.set('end', String(options.end));
    const response = await fetch(
      `${API_BASE}/api/sessions/${sessionId}/files/${fileId}/plots/${kind}.png?${query.toString()}`,
      { headers: headers() },
    );
    if (!response.ok) {
      let detail: any = response.statusText;
      try {
        detail = await response.json();
      } catch {
        /* ignore */
      }
      throw new ApiError(response.status, detail);
    }
    const blob = await response.blob();
    // The server names the file after the audio file and plot type; keep it so
    // exports of different files do not all download as "<kind>.png".
    const filename = filenameFromDisposition(response.headers.get('Content-Disposition'), `${kind}.png`);
    downloadBlob(blob, filename);
    return filename;
  },

  audioUrl: (sessionId: string, fileId: string) =>
    `${API_BASE}/api/sessions/${sessionId}/files/${fileId}/audio`,
};

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export function formatError(error: unknown): string {
  if (error instanceof ApiError) {
    if (typeof error.detail === 'string') return error.detail;
    if (error.detail?.detail) {
      if (typeof error.detail.detail === 'string') return error.detail.detail;
      if (Array.isArray(error.detail.detail)) {
        return error.detail.detail.map((d: any) => d.msg ?? JSON.stringify(d)).join('; ');
      }
    }
    return error.message;
  }
  if (error instanceof Error) return error.message;
  return String(error);
}
