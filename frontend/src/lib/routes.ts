export type SectionKey =
  | 'dashboard'
  | 'upload'
  | 'files'
  | 'overview'
  | 'waveform'
  | 'spectrum'
  | 'spectrogram'
  | 'musical'
  | 'loudness'
  | 'dynamics'
  | 'stereo'
  | 'comparison'
  | 'qc'
  | 'reports'
  | 'settings';

export const SECTION_LIST: SectionKey[] = [
  'dashboard', 'upload', 'files', 'overview', 'waveform', 'spectrum', 'spectrogram', 'musical',
  'loudness', 'dynamics', 'stereo', 'comparison', 'qc', 'reports', 'settings',
];

export const SECTION_KEYS = new Set<string>(SECTION_LIST);

/** Sections that inspect one file at a time and show the active-file bar. */
export const FILE_SECTIONS = new Set<SectionKey>([
  'overview', 'waveform', 'spectrum', 'spectrogram', 'musical', 'loudness', 'dynamics', 'stereo',
]);

export interface Route {
  section: SectionKey;
  file?: string;
  start?: number;
  end?: number;
}

const FILE_ID = /^fil_[0-9a-f]{32}$/;

/** Parse `#/section?file=fil_…&start=1.5&end=2` defensively (hash is user-editable). */
export function parseRoute(hash: string): Route {
  const clean = hash.replace(/^#\/?/, '');
  const [path, query = ''] = clean.split('?');
  const section = (SECTION_KEYS.has(path) ? path : 'dashboard') as SectionKey;
  const params = new URLSearchParams(query);
  const route: Route = { section };
  const file = params.get('file');
  if (file && FILE_ID.test(file)) route.file = file;
  const start = Number(params.get('start'));
  const end = Number(params.get('end'));
  if (params.has('start') && params.has('end') && Number.isFinite(start) && Number.isFinite(end) && start >= 0 && end > start) {
    route.start = start;
    route.end = end;
  }
  return route;
}

export function routeHref(section: SectionKey, params?: { file?: string; start?: number; end?: number }): string {
  const query = new URLSearchParams();
  if (params?.file) query.set('file', params.file);
  if (params?.file && params.start !== undefined && params.end !== undefined) {
    query.set('start', String(Math.round(params.start * 1000) / 1000));
    query.set('end', String(Math.round(params.end * 1000) / 1000));
  }
  const text = query.toString();
  return `#/${section}${text ? `?${text}` : ''}`;
}
