export interface AudioMetadata {
  format?: string;
  container?: string;
  codec?: string;
  codec_long_name?: string;
  sample_rate?: number;
  channels?: number;
  channel_layout?: string | null;
  frames?: number;
  duration?: number;
  bit_depth?: number | null;
  bit_depth_source?: string | null;
  bit_depth_note?: string | null;
  bitrate_kbps?: number | null;
  bitrate_source?: string | null;
  size_bytes?: number;
  size_human?: string;
  is_lossy?: boolean;
  subtype?: string | null;
  decoder?: string;
  channels_label?: string;
  [key: string]: unknown;
}

export interface ValidationResult {
  ok: boolean;
  errors: string[];
  warnings: string[];
  metadata?: AudioMetadata;
  [key: string]: unknown;
}

export type FileStatus = 'uploaded' | 'validated' | 'queued' | 'analyzing' | 'complete' | 'error';

export interface FileRecord {
  id: string;
  original_name: string;
  ext: string;
  size_bytes: number;
  uploaded_at: string;
  status: FileStatus;
  progress: number;
  stage: string;
  error?: string | null;
  metadata: AudioMetadata;
  validation?: ValidationResult;
  has_analysis: boolean;
  analysis_summary: AnalysisSummary;
  job_id?: string | null;
  analyzed_at?: string | null;
}

export interface AnalysisSummary {
  format?: string;
  sample_rate?: number;
  bit_depth?: number | null;
  bit_depth_source?: string | null;
  channels?: number;
  duration_seconds?: number;
  integrated_lufs?: number | null;
  true_peak_dbtp?: number | null;
  loudness_range_lu?: number | null;
  crest_factor_db?: number | null;
  key?: string | null;
  tempo_bpm?: number | null;
  correlation?: number | null;
  qc_overall?: string;
  qc_errors?: number;
  qc_warnings?: number;
  [key: string]: unknown;
}

export interface SessionSettings {
  target_lufs: number;
  true_peak_limit: number;
  fft_size: number;
  hop_length: number;
  qc_thresholds?: Record<string, number | number[]>;
  [key: string]: unknown;
}

export interface Job {
  id: string;
  session_id: string;
  file_id: string;
  file_name: string;
  status: 'queued' | 'running' | 'complete' | 'failed';
  progress: number;
  stage: string;
  error?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  result?: AnalysisSummary | null;
}

export interface Session {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  settings: SessionSettings;
  files: FileRecord[];
  jobs: Job[];
}

export interface OverviewFile {
  id: string;
  name: string;
  status: FileStatus;
  metadata: AudioMetadata;
  analysis_summary: AnalysisSummary;
  has_analysis: boolean;
  validation?: ValidationResult;
  quick?: {
    rms_times: number[];
    rms_db: number[];
    short_term_times: number[];
    short_term_lufs: number[];
    bands: { label: string; share: number }[];
    qc: Record<string, number>;
    qc_overall: string;
    key: string | null;
    tempo_bpm: number | null;
    recommendation_count: number;
  };
}

export interface Recommendation {
  file_id?: string;
  file_name?: string;
  id: string;
  category: string;
  priority: 'info' | 'warning' | 'error' | string;
  title: string;
  supporting_measurement?: string | null;
  explanation?: string | null;
  recommendation?: string | null;
  automatic_processing?: boolean;
  time_positions?: TimeRegion[];
}

export interface Overview {
  session: Session;
  files: OverviewFile[];
  recommendations: Recommendation[];
  totals: {
    files: number;
    analysed: number;
    duration_seconds: number;
    errors: number;
    warnings: number;
  };
}

export interface TimeRegion {
  start: number;
  end: number;
  duration?: number;
  [key: string]: unknown;
}

export interface Peak {
  frequency_hz: number;
  amplitude_dbfs: number;
  prominence_db: number;
  bin_amplitude_dbfs?: number;
  harmonic_of_dominant?: number | null;
}

export interface FeatureSummary {
  mean?: number | null;
  median?: number | null;
  p5?: number | null;
  p95?: number | null;
  min?: number | null;
  max?: number | null;
  std?: number | null;
  series?: { times: number[]; values: number[] };
}

export interface Band {
  key: string;
  label: string;
  low_hz: number;
  high_hz: number;
  average_db?: number | null;
  relative_energy_pct?: number | null;
  variation_db?: number | null;
  p5_db?: number | null;
  p95_db?: number | null;
  supported: boolean;
}

export interface Loudness {
  supported: boolean;
  integrated_lufs?: number | null;
  loudness_range_lu?: number | null;
  true_peak_dbtp?: number | null;
  sample_peak_dbfs?: number | null;
  rms_dbfs?: number | null;
  crest_factor_db?: number | null;
  peak_to_loudness_ratio_db?: number | null;
  momentary: { times: number[]; lufs: number[] };
  short_term: { times: number[]; lufs: number[] };
  confidence?: string;
  [key: string]: unknown;
}

export interface TimeDomain {
  duration_seconds: number;
  sample_count: number;
  channel_count: number;
  sample_peak: { dbfs: number; linear: number; per_channel: any[] };
  true_peak_dbtp?: number | null;
  rms: { dbfs: number; linear: number; per_channel_dbfs: number[] };
  dc_offset: { per_channel: number[]; max_abs: number; max_abs_dbfs: number; method: string };
  clipping: {
    threshold_dbfs: number;
    clipped_samples: number;
    clipped_percent: number;
    flat_top_samples: number;
    intersample_overs: boolean;
    regions: TimeRegion[];
    per_channel_samples: number[];
    method: string;
  };
  silence: {
    threshold_dbfs: number;
    duration_seconds: number;
    percent: number;
    regions: TimeRegion[];
    digital_silence_duration_seconds: number;
    digital_silence_regions: TimeRegion[];
    method: string;
  };
  noise: { noise_floor_dbfs?: number | null; snr_db?: number | null; method: string; confidence: string };
  dropouts: { count: number; regions: TimeRegion[]; method: string };
  signal_variation: Record<string, number>;
  envelopes: {
    times: number[];
    rms_db: number[];
    peak_db: number[];
    amplitude: number[];
    short_time_energy_db: number[];
    frame_seconds: number;
    hop_seconds: number;
  };
  waveform: {
    times: number[];
    channels: { channel: number; label: string; min: number[]; max: number[]; rms: number[] }[];
    mono_min: number[];
    mono_max: number[];
    mono_rms_db: number[];
    bucket_count: number;
    channel_note?: string | null;
  };
  regions: Record<string, TimeRegion[]>;
  [key: string]: any;
}

export interface Spectral {
  fft: {
    frequencies_hz: number[];
    average_dbfs: number[];
    average_power_psd: number[];
    peaks: Peak[];
    dominant_frequency_hz?: number | null;
    n_fft: number;
    window: string;
    bin_width_hz: number;
    method: string;
  };
  spectrogram: {
    times: number[];
    frequencies_hz: number[];
    magnitude_db: number[][];
    log_frequencies_hz: number[];
    log_magnitude_db: number[][];
    n_fft: number;
    hop_length: number;
    db_floor: number;
    method: string;
  };
  mel: {
    times: number[];
    frequencies_hz: number[];
    power_db: number[][];
    average_db: number[];
    n_mels: number;
    fmin_hz: number;
    fmax_hz: number;
    method: string;
  };
  chroma: {
    times: number[];
    pitch_classes: string[];
    energy: number[][];
    mean_energy: number[];
    method: string;
  };
  spectral_features: Record<string, any>;
  bands: { bands: Band[]; total_power_20_20k: number; definition: string };
  observations: { type: string; severity: string; message: string; measurement: any; recommendation: string }[];
  hpss: any;
  onset_envelope: { times: number[]; values: number[]; hop_length: number; method: string };
  analysis_settings: Record<string, any>;
  confidence: Record<string, string>;
  [key: string]: any;
}

export interface Musical {
  key: {
    supported: boolean;
    key?: string | null;
    tonic?: string | null;
    mode?: string | null;
    confidence?: number;
    confidence_label?: string;
    correlation?: number;
    alternatives?: { key: string; mode: string; correlation: number; probability: number }[];
    harmonic_content?: { top_pitch_classes: { pitch_class: string; energy: number }[]; chroma_mean: number[] };
    method?: string;
    note?: string;
    reason?: string;
  };
  tempo: {
    bpm?: number | null;
    bpm_rounded?: number | null;
    confidence?: number;
    confidence_label?: string;
    beat_count?: number;
    beats?: number[];
    beat_intervals_seconds?: number[];
    beat_interval_mean_seconds?: number;
    beat_interval_cv?: number;
    tempo_stability?: number;
    beat_consistency?: number;
    stability_label?: string;
    candidates?: { bpm: number; strength: number; interpretation: string }[];
    half_time_bpm?: number | null;
    double_time_bpm?: number | null;
    local_tempo?: { time: number; bpm: number; strength: number }[];
    tempo_changes?: { start: number; end: number; bpm_min: number; bpm_max: number; note: string }[];
    method?: string;
  };
  rhythm: {
    onset_count: number;
    onset_density_per_second: number;
    onsets: number[];
    onset_strengths: number[];
    onset_intervals_seconds: number[];
    onset_interval_cv: number;
    off_grid_onset_fraction: number;
    rhythm_consistency: number;
    onset_envelope: { times: number[]; values: number[] };
    method: string;
  };
  pitch: {
    supported: boolean;
    reason?: string;
    analyzed_start?: number;
    analyzed_end?: number;
    f0_median_hz?: number;
    f0_p5_hz?: number;
    f0_p95_hz?: number;
    pitch_range_semitones?: number;
    pitch_stability_semitones_std?: number;
    pitch_stability_label?: string;
    voiced_fraction?: number;
    confidence?: number;
    confidence_label?: string;
    note_transitions?: number;
    dominant_notes?: { note: string; midi: number; frames: number; percent: number }[];
    pitch_distribution?: { midi_centers: number[]; counts: number[]; normalized: number[] };
    contour?: { times: number[]; f0_hz: (number | null)[]; confidence: number[]; voiced: boolean[] };
    method?: string;
    limitations?: string;
  };
  confidence: Record<string, string>;
  limitations: string[];
  [key: string]: any;
}

export interface Stereo {
  supported: boolean;
  mono: boolean;
  channel_count: number;
  reason?: string;
  channel_note?: string | null;
  left?: { rms_dbfs: number; peak_dbfs: number };
  right?: { rms_dbfs: number; peak_dbfs: number };
  balance?: { balance_db: number; balance_ratio: number; label: string; method: string };
  correlation?: { value: number; phase_correlation: number; channel_similarity: number; interpretation: string };
  mid_side?: {
    mid_rms_dbfs: number;
    side_rms_dbfs: number;
    side_to_mid_ratio: number;
    stereo_width_percent: number;
    method: string;
  };
  mono_compatibility?: {
    applicable: boolean;
    mono_fold_rms_dbfs?: number;
    stereo_program_rms_dbfs?: number;
    mono_loss_db?: number;
    mono_peak_dbfs?: number;
    mono_peak_exceeds_0dbfs?: boolean;
    compatible?: boolean;
    method?: string;
    note?: string;
  };
  timeline?: { times: number[]; correlation: number[]; width: number[]; mid_db: number[]; side_db: number[] };
  vectorscope?: { left: number[]; right: number[]; normalized_to: number; point_count: number; method: string };
  channel_envelope?: { times: number[]; left_db: number[]; right_db: number[]; note: string };
  phase_regions?: TimeRegion[];
  issues?: { type: string; severity: string; message: string; measurement: any; recommendation: string }[];
  confidence?: string;
  method?: string;
  mono_rms_dbfs?: number;
  mono_peak_dbfs?: number;
  [key: string]: any;
}

export interface Dynamics {
  dynamic_range_db?: number;
  crest_factor_db?: number;
  peak_to_loudness_ratio_db?: number;
  loudness_range_lu?: number;
  rms_variation_db?: number;
  rms_range_db?: number;
  short_term_dynamic_variation_lu?: number;
  short_term_range_lu?: number;
  short_term_p5_lufs?: number;
  short_term_p95_lufs?: number;
  crest_factor_median_db?: number;
  transient_strength: any;
  compression_indicators: any[];
  reduced_dynamic_sections: any[];
  timeline: {
    times: number[];
    rms_db: number[];
    peak_db: number[];
    crest_db: number[];
    short_term_lufs: { times: number[]; values: number[] };
  };
  method: string;
  confidence: string;
  [key: string]: any;
}

export interface QCCheck {
  id: string;
  category: string;
  title: string;
  severity: 'normal' | 'information' | 'warning' | 'error';
  status_label: string;
  message: string;
  explanation: string;
  recommendation: string;
  measured_value: any;
  measured_unit?: string | null;
  threshold_value: any;
  threshold_unit?: string | null;
  time_positions: TimeRegion[];
  confidence: string;
  standard?: string | null;
}

export interface QC {
  overall: 'normal' | 'information' | 'warning' | 'error';
  overall_label: string;
  summary: Record<string, number>;
  checks: QCCheck[];
  findings: QCCheck[];
  thresholds: Record<string, number | number[]>;
  threshold_schema: any[];
  method: string;
  error_count: number;
  warning_count: number;
  information_count: number;
  normal_count: number;
}

export interface Analysis {
  schema_version: string;
  file_id: string;
  original_name: string;
  analyzed_at: string;
  sha256: string;
  metadata: AudioMetadata;
  validation: ValidationResult;
  loudness: Loudness;
  time_domain: TimeDomain;
  spectral: Spectral;
  musical: Musical;
  stereo: Stereo;
  dynamics: Dynamics;
  track_gain: any;
  analysis_settings: Record<string, any>;
  methods: Record<string, string>;
  confidence: Record<string, any>;
  recommendations: Recommendation[];
  qc: QC;
  summary: AnalysisSummary;
  analysis_duration_seconds: number;
  mode?: string;
  segment?: { start: number; end: number; duration: number };
  [key: string]: any;
}

export interface ComparisonRow {
  key: string;
  label: string;
  group: string;
  unit: string;
  kind: string;
  values: Record<string, any>;
  display: Record<string, string>;
  status: 'match' | 'different' | 'large_deviation' | 'low_confidence' | 'unsupported';
  deviation_status: string;
  spread: number | null;
  tolerance: number;
  tolerance_note: string;
  low_confidence: boolean;
  confidence: Record<string, string | null>;
  deviations?: Record<string, number | null>;
  reference_file_id?: string;
  reference_value?: any;
  note?: string | null;
}

export interface ComparisonGroup {
  name: string;
  rows: ComparisonRow[];
  summary: Record<string, number>;
}

export interface Comparison {
  mode: string;
  segment_ranges: Record<string, { start: number; end: number }>;
  file_order: string[];
  files: { id: string; name: string }[];
  reference_file_id?: string | null;
  parameters: any[];
  rows: ComparisonRow[];
  groups: ComparisonGroup[];
  summary: Record<string, number>;
  gain_preview: any[];
  findings: { id: string; severity: string; title: string; message: string; recommendation: string; measurement: any }[];
  target_lufs: number;
  true_peak_limit: number;
  method: string;
  notes: string[];
  generated_at?: string;
  [key: string]: any;
}

export interface AlignmentResult {
  method: string;
  method_detail?: string;
  offset_seconds: number | null;
  apply_shift_to_b_seconds?: number;
  offset_description?: string;
  confidence: number;
  confidence_label: string;
  overlap_seconds: number;
  overlap_fraction: number;
  duration_difference_seconds: number;
  file_a_duration: number;
  file_b_duration: number;
  alternate_method?: { method: string; offset_seconds: number; confidence: number } | null;
  note?: string;
  [key: string]: any;
}

export interface AppSettings {
  version: string;
  supported_formats: string[];
  supported_extensions: string[];
  limits: Record<string, number>;
  defaults: Record<string, number>;
  qc_threshold_schema: any[];
  qc_thresholds: Record<string, number | number[]>;
  methods: Record<string, string>;
  notes: string[];
}

export interface WaveformResponse {
  times: number[];
  channels: { channel: number; label: string; min: number[]; max: number[]; rms: number[] }[];
  mono_min: number[];
  mono_max: number[];
  mono_rms_db: number[];
  bucket_count: number;
  sample_rate: number;
  duration: number;
  source: string;
  selection: { start: number; end: number } | null;
  warnings?: string[];
}
