import type { MetricStatus } from '../components/UI';
import { statusFromSeverity } from '../components/UI';
import type { Analysis } from '../types';

export interface MetricDef {
  key: string;
  label: string;
  value: number | string | null;
  unit?: string;
  digits?: number;
  status: MetricStatus;
  kind: 'measured' | 'estimate';
  confidence?: string | null;
  explanation: string;
  hint?: string;
}

export interface MetricGroup {
  title: string;
  description: string;
  metrics: MetricDef[];
  note?: string;
}

const num = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;

/**
 * Status comes only from the backend QC check that evaluates the metric
 * (by check id).  Metrics without a QC rule get no status, so the UI never
 * shows an invented "pass".
 */
function checkStatus(analysis: Analysis, ...ids: string[]): MetricStatus {
  const checks = analysis.qc?.checks ?? [];
  for (const id of ids) {
    const check = checks.find((item) => item.id === id);
    if (check) return statusFromSeverity(check.severity);
  }
  return 'none';
}

export function buildMetricGroups(analysis: Analysis): MetricGroup[] {
  const a: any = analysis;
  const td = a.time_domain ?? {};
  const loud = a.loudness ?? {};
  const musical = a.musical ?? {};
  const dyn = a.dynamics ?? {};
  const stereo = a.stereo ?? {};
  const meta = a.metadata ?? {};
  const key = musical.key ?? {};
  const tempo = musical.tempo ?? {};
  const pitch = musical.pitch ?? {};
  const clip = td.clipping ?? {};

  const groups: MetricGroup[] = [
    {
      title: 'Audio quality',
      description: 'Signal integrity measured on the decoded audio.',
      metrics: [
        { key: 'snr', label: 'Signal-to-noise ratio', value: num(td.noise?.snr_db), unit: 'dB', status: checkStatus(analysis, 'noise'), kind: 'estimate', confidence: td.noise?.confidence, explanation: 'Overall RMS minus the estimated noise floor. Not reported when the file has too little quiet material to separate noise from signal.' },
        { key: 'noise_floor', label: 'Noise floor', value: num(td.noise?.noise_floor_dbfs), unit: 'dBFS', status: checkStatus(analysis, 'noise'), kind: 'estimate', confidence: td.noise?.confidence, explanation: '10th percentile of audible 50 ms RMS frames, used only when it is at least 6 dB below the median level.' },
        { key: 'sample_peak', label: 'Peak amplitude', value: num(td.sample_peak?.dbfs), unit: 'dBFS', status: 'none', kind: 'measured', explanation: 'Largest absolute sample value across all channels, relative to digital full scale.' },
        { key: 'true_peak', label: 'True peak', value: num(loud.true_peak_dbtp), unit: 'dBTP', status: checkStatus(analysis, 'true_peak'), kind: 'measured', explanation: 'Inter-sample peak level from 4× oversampling (ITU-R BS.1770-4 Annex 2). Above 0 dBTP can clip in playback converters.' },
        { key: 'rms', label: 'RMS level', value: num(td.rms?.dbfs), unit: 'dBFS', status: 'none', kind: 'measured', explanation: 'Root-mean-square level over all channels and the whole file.' },
        { key: 'dc', label: 'DC offset', value: num(td.dc_offset?.max_abs), unit: 'linear', digits: 5, status: checkStatus(analysis, 'dc_offset'), kind: 'measured', explanation: 'Largest per-channel mean value. A non-zero mean wastes headroom and can cause clicks at edits.' },
        { key: 'clipping', label: 'Clipping', value: num(clip.clipped_percent), unit: '%', digits: 4, status: checkStatus(analysis, 'clipping'), kind: 'measured', explanation: 'Share of samples at or above the clipping threshold. Inter-sample overs (true peak above 0 dBTP without clipped samples) are reported separately.', hint: `${num(clip.clipped_samples) ?? 0} clipped samples${clip.intersample_overs ? ' · inter-sample overs detected' : ''}` },
        { key: 'silence', label: 'Silence', value: num(td.silence?.percent), unit: '%', status: checkStatus(analysis, 'silence'), kind: 'measured', explanation: 'Share of the duration where 50 ms frames (all channels) are below the silence threshold.' },
      ],
    },
    {
      title: 'Musical analysis',
      description: 'Algorithmic estimates — confidence is shown with each value.',
      metrics: [
        { key: 'key', label: 'Musical key', value: key.supported === false ? null : key.key ?? null, status: key.confidence_label === 'low' ? 'info' : 'none', kind: 'estimate', confidence: key.confidence_label, explanation: 'Krumhansl–Schmuckler key-profile correlation against the mean chroma. Ambiguous for modal, atonal or percussive material.' },
        { key: 'key_conf', label: 'Key confidence', value: num(key.confidence) !== null ? Math.round((key.confidence as number) * 100) : null, unit: '%', digits: 0, status: 'none', kind: 'estimate', confidence: key.confidence_label, explanation: 'Profile fit combined with separation from the next-best key.' },
        { key: 'tempo', label: 'Tempo', value: num(tempo.bpm), unit: 'BPM', digits: 1, status: tempo.confidence_label === 'low' ? 'info' : 'none', kind: 'estimate', confidence: tempo.confidence_label, explanation: 'Beat-tracker tempo. Confidence reflects how periodic the onset envelope is at that tempo, not just grid regularity.', hint: (tempo.notes ?? [])[0] },
        { key: 'beats', label: 'Beat positions', value: num(tempo.beat_count), unit: 'beats', digits: 0, status: 'none', kind: 'estimate', confidence: tempo.confidence_label, explanation: 'Number of detected beats; positions are drawn on the waveform and tempo plots.' },
        { key: 'stability', label: 'Tempo stability', value: num(tempo.tempo_stability) !== null ? Math.round((tempo.tempo_stability as number) * 100) : null, unit: '%', digits: 0, status: 'none', kind: 'estimate', confidence: tempo.confidence_label, explanation: '1 − coefficient of variation of beat intervals.' },
        { key: 'pitch', label: 'Median pitch (F0)', value: pitch.supported ? num(pitch.f0_median_hz) : null, unit: 'Hz', digits: 1, status: pitch.supported && pitch.reliable_single_pitch === false ? 'warning' : 'none', kind: 'estimate', confidence: pitch.confidence_label, explanation: 'pYIN fundamental frequency of the most energetic segment. Not meaningful for polyphonic material.', hint: pitch.reliable_single_pitch === false ? (pitch.reliability_notes ?? [])[0] : pitch.reason },
      ],
    },
    {
      title: 'Digital audio properties',
      description: 'Read from the file; not modified or resampled.',
      metrics: [
        { key: 'sr', label: 'Sample rate', value: num(meta.sample_rate), unit: 'Hz', digits: 0, status: checkStatus(analysis, 'sample_rate', 'sample_rate_ok'), kind: 'measured', explanation: 'Native sample rate. Analysis runs at this rate.' },
        { key: 'bits', label: 'Bit depth', value: num(meta.bit_depth), unit: 'bits', digits: 0, status: num(meta.bit_depth) !== null ? checkStatus(analysis, 'bit_depth') : 'none', kind: 'measured', explanation: 'Stored PCM bit depth. Lossy codecs have no original PCM bit depth.', hint: num(meta.bit_depth) === null ? (meta.is_lossy ? 'Lossy codec — not applicable' : 'Not determined') : meta.bit_depth_source ?? undefined },
        { key: 'bitrate', label: 'Bit rate', value: num(meta.bitrate_kbps), unit: 'kbps', digits: 0, status: 'none', kind: 'measured', explanation: 'Encoded bit rate from the codec stream (or file size ÷ duration).', hint: meta.bitrate_source },
        { key: 'channels', label: 'Channels', value: meta.channels ? (meta.channels === 1 ? 'Mono' : meta.channels === 2 ? 'Stereo' : `${meta.channels} ch`) : null, status: 'none', kind: 'measured', explanation: 'Channel count and layout reported by the decoder.' },
        { key: 'duration', label: 'Duration', value: num(meta.duration), unit: 's', digits: 2, status: 'none', kind: 'measured', explanation: 'Decoded duration.' },
      ],
    },
    {
      title: 'Loudness',
      description: 'ITU-R BS.1770-4 / EBU R128.',
      metrics: [
        { key: 'integrated', label: 'Integrated loudness', value: num(loud.integrated_lufs), unit: 'LUFS', status: checkStatus(analysis, 'integrated_loudness'), kind: 'measured', explanation: 'Gated loudness of the whole programme (−70 LUFS absolute and −10 LU relative gates). Not defined for silence.' },
        { key: 'momentary', label: 'Momentary max', value: num(loud.momentary_max_lufs), unit: 'LUFS', status: 'none', kind: 'measured', explanation: 'Loudest 400 ms block.' },
        { key: 'short', label: 'Short-term max', value: num(loud.short_term_max_lufs), unit: 'LUFS', status: 'none', kind: 'measured', explanation: 'Loudest 3 s block.' },
        { key: 'lra', label: 'Loudness range', value: num(loud.loudness_range_lu), unit: 'LU', status: checkStatus(analysis, 'loudness_range'), kind: 'measured', explanation: 'EBU Tech 3342: spread between the 10th and 95th percentile of gated short-term loudness.' },
        { key: 'lsp', label: 'Sample peak', value: num(loud.sample_peak_dbfs), unit: 'dBFS', status: 'none', kind: 'measured', explanation: 'Largest sample value.' },
        { key: 'ltp', label: 'True peak', value: num(loud.true_peak_dbtp), unit: 'dBTP', status: checkStatus(analysis, 'true_peak'), kind: 'measured', explanation: '4× oversampled inter-sample peak.' },
      ],
    },
    {
      title: 'Dynamics',
      description: 'Peak, loudness and transient behaviour.',
      metrics: [
        { key: 'dr', label: 'Dynamic range (crest)', value: num(dyn.dynamic_range_db), unit: 'dB', status: 'none', kind: 'measured', explanation: 'Reported as peak-to-RMS crest factor; loudness range is shown under Loudness.' },
        { key: 'crest', label: 'Crest factor', value: num(loud.crest_factor_db), unit: 'dB', status: checkStatus(analysis, 'crest_factor'), kind: 'measured', explanation: 'Sample peak minus RMS. Low values indicate heavy limiting or dense material.' },
        { key: 'plr', label: 'Peak-to-loudness ratio', value: num(loud.peak_to_loudness_ratio_db), unit: 'dB', status: 'none', kind: 'measured', explanation: 'True peak minus integrated loudness.' },
        { key: 'transient', label: 'Transient strength', value: num(dyn.transient_strength?.peak_to_median_ratio), unit: '×', digits: 2, status: 'none', kind: 'estimate', confidence: dyn.transient_strength?.supported ? 'medium' : null, explanation: '95th-percentile onset strength relative to the median onset — higher values mean sharper attacks.', hint: dyn.transient_strength?.supported === false ? dyn.transient_strength?.reason : undefined },
      ],
    },
  ];

  if (stereo.supported) {
    groups.push({
      title: 'Stereo analysis',
      description: 'Correlation, balance and mid/side energy of channels 1 and 2.',
      metrics: [
        { key: 'balance', label: 'Channel balance', value: num(stereo.balance?.balance_db), unit: 'dB', status: checkStatus(analysis, 'channel_imbalance'), kind: 'measured', explanation: 'Right/left RMS ratio in dB; positive favours the right channel.', hint: stereo.balance?.label },
        { key: 'width', label: 'Stereo width', value: num(stereo.mid_side?.stereo_width_percent), unit: '%', status: 'none', kind: 'measured', explanation: 'Side RMS relative to mid + side RMS.' },
        { key: 'corr', label: 'Phase correlation', value: num(stereo.correlation?.value), unit: 'r', digits: 3, status: checkStatus(analysis, 'correlation'), kind: 'measured', explanation: 'Pearson correlation of left and right (+1 in phase, −1 out of phase). Undefined when a channel has no signal.', hint: stereo.correlation?.interpretation },
        { key: 'mid', label: 'Mid energy', value: num(stereo.mid_side?.mid_rms_dbfs), unit: 'dBFS', status: 'none', kind: 'measured', explanation: 'RMS of (L+R)/2.' },
        { key: 'side', label: 'Side energy', value: num(stereo.mid_side?.side_rms_dbfs), unit: 'dBFS', status: 'none', kind: 'measured', explanation: 'RMS of (L−R)/2.' },
        { key: 'mono', label: 'Mono fold-down loss', value: num(stereo.mono_compatibility?.mono_loss_db), unit: 'dB', status: stereo.mono_compatibility?.compatible === false ? 'warning' : stereo.mono_compatibility?.compatible === true ? 'pass' : 'none', kind: 'measured', explanation: 'Level of the mono fold-down relative to the stereo programme; large negative values mean cancellation in mono.' },
      ],
    });
  } else {
    groups.push({
      title: 'Stereo analysis',
      description: 'Not applicable.',
      metrics: [],
      note: stereo.reason ?? 'Mono file: stereo width, correlation and mid/side metrics do not exist, and none are invented.',
    });
  }
  return groups;
}

export function formatMetricValue(metric: MetricDef): string | null {
  if (metric.value === null || metric.value === undefined) return null;
  if (typeof metric.value === 'string') return metric.value;
  const digits = metric.digits ?? (Math.abs(metric.value) >= 100 ? 0 : 2);
  return metric.value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
