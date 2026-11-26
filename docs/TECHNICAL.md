# Technical Reference

This document specifies exactly how each measurement is computed, what its units and confidence
mean, and where the platform deliberately refuses to produce a number.

Every value in the analysis payload carries a `method` string describing the algorithm, and every
*estimated* result (key, tempo, pitch, noise floor, HNR) carries a confidence field. The rule
applied throughout the codebase is:

> If a quantity cannot be measured reliably from the supplied audio, the field is `null` and the
> reason is stated. A placeholder, an interpolated value or a fabricated stereo metric is never
> emitted.

---

## 1. Architecture

```
                    ┌──────────────────────────────────────┐
 Browser ─────────▶ │ FastAPI (app/main.py)                │
                    │  • middleware: API key, security hdr │
                    │  • routes: /api/sessions/...         │
                    │  • static: frontend/dist (SPA)       │
                    └───────┬──────────────────────┬───────┘
                            │                      │
                  ┌─────────▼─────────┐   ┌────────▼─────────┐
                  │ storage.py        │   │ jobs.py          │
                  │ session.json      │   │ ThreadPoolExecutor│
                  │ files/<id>/orig   │   │ job_<hex> state  │
                  │ files/<id>/an.json│   └────────┬─────────┘
                  └───────────────────┘            │
                                      ┌────────────▼─────────────┐
                                      │ analysis/pipeline.py     │
                                      │  loudness  time_domain   │
                                      │  spectral  musical       │
                                      │  stereo    dynamics      │
                                      │  qc  comparison alignment│
                                      └──────────────────────────┘
```

### 1.1 Module map

| Module | Responsibility |
| --- | --- |
| `app/config.py` | Frozen `Settings` dataclass; every limit is environment-driven |
| `app/storage.py` | Session/file records, atomic JSON writes, SHA-256, session TTL |
| `app/validation.py` | Container sniffing, structural parsing, truncation detection |
| `app/audio_io.py` | Decoding via libsndfile (`soundfile`) and PyAV; metadata probing |
| `app/jobs.py` | Background analysis queue, progress tracking, cancellation |
| `app/analysis/utils.py` | `db()`, `round_sig()`, region merging, envelope downsampling |
| `app/analysis/loudness.py` | ITU-R BS.1770-4 / EBU R128, true peak, gain preview |
| `app/analysis/time_domain.py` | Levels, clipping, silence, dropouts, noise floor, waveforms |
| `app/analysis/spectral.py` | FFT, STFT, Mel, chroma, features, bands, HPSS |
| `app/analysis/musical.py` | Key, chroma-derived, tempo, beats, onsets, F0 |
| `app/analysis/stereo.py` | Correlation, width, balance, mid/side, mono compatibility |
| `app/analysis/dynamics.py` | Crest, LRA, short-term variation, compression indicators |
| `app/analysis/qc.py` | Threshold engine and four-level classification |
| `app/analysis/comparison.py` | Cross-file parameter comparison with tolerances |
| `app/analysis/alignment.py` | Manual and automatic cross-correlation alignment |
| `app/analysis/segment.py` | Bounded re-analysis of a time range |
| `app/analysis/pipeline.py` | Orchestration, progress reporting, recommendations |
| `app/reporting.py` | CSV/JSON/PDF builders and 14 server-side plot renderers |

### 1.2 Data flow

1. **Upload** — the multipart file is streamed to
   `AAP_DATA_DIR/sessions/<ses>/files/<fil>/original.<ext>` in chunks. The bytes are never
   rewritten afterwards.
2. **Validation** — `validation.validate_upload()` sniffs the container signature, compares it to
   the declared extension, parses container headers for truncation and probes the file with both
   decoders. A file with errors is rejected before analysis.
3. **SHA-256** — computed over the stored original and stored in the analysis artifact, so any
   later file can be proven identical to the analysed one.
4. **Analysis** — `POST /api/sessions/{id}/analyze` enqueues one job per file on a
   `ThreadPoolExecutor` (default 2 workers). Progress is reported per stage.
5. **Artifact** — the result is written atomically to `analysis.json` (temp file + `os.replace`).
   A crash mid-write can never leave a half-written artifact.
6. **QC** — `qc.analyze_qc()` runs on the finished measurement payload and can be re-run with
   different thresholds at any time without re-analysing the audio.

### 1.3 Concurrency and resource control

| Control | Value | Effect |
| --- | --- | --- |
| `AAP_MAX_CONCURRENT_JOBS` | 2 | Parallel analysis jobs per process |
| `max_spectrogram_frames` | 320 | Display spectrogram columns; longer files are time-averaged |
| `max_feature_points` | 1200 | Points in feature timelines |
| `max_waveform_buckets` | 4000 | Waveform min/max/RMS buckets |
| `pitch_analysis_seconds` | 30 | F0 tracking window (centre segment of longer files) |
| `hpss_analysis_seconds` | 120 | HPSS window (centre segment of longer files) |
| Mel / chroma | 128 × 300, 12 × 300 | Display matrices |
| Log-frequency view | 160 bins | Interpolated from the linear display grid |

All long-running loops are chunked: loudness filtering runs in 10 s chunks with state carried
between them, and the STFT is processed in 256-frame blocks, so peak memory does not scale with
file length.

---

## 2. Decoding and metadata

### 2.1 Decoders

| Family | Decoder | Notes |
| --- | --- | --- |
| WAV, AIFF, FLAC, OGG, MP3 | libsndfile via `soundfile` | Primary path; reads to float32 |
| AAC (ADTS), M4A/MP4 | PyAV (bundled FFmpeg) | Fallback and primary for MP4 family |
| Any | PyAV fallback | Used when libsndfile refuses the file |

Decoded samples are normalised to `float32` in the range [-1, 1] where the source is integer PCM.
Analysis always operates on the decoded signal; the stored original is never re-encoded.

### 2.2 Reported metadata

| Field | Source | Notes |
| --- | --- | --- |
| `sample_rate` | Container header | The native rate; **no resampling is applied** |
| `channels` | Container header | 1–8 supported |
| `bit_depth` | PCM subtype (libsndfile) or FLAC `STREAMINFO` | **Only for lossless PCM**. `null` for lossy codecs |
| `bit_depth_source` | `pcm` / `lossless` / `null` | Makes the provenance explicit in the UI |
| `bitrate_kbps` | Container metadata | Reported for lossy formats as *encoded* bitrate |
| `is_lossy` | Codec classification | Drives the bit-depth policy above |
| `duration` | Frame count ÷ sample rate | Cross-checked against the container's declared length |
| `sha256` | Stored original | Hex digest of the uploaded bytes |

> **Encoded bit depth is never reported as PCM bit depth.** For MP3/AAC the decoder bit depth is
> meaningless, so `bit_depth` is `null` and a QC information entry states that no original PCM bit
> depth exists.

### 2.3 Structural validation

| Container | Checks |
| --- | --- |
| WAV / RF64 | RIFF size vs. actual size, presence of `fmt ` and `data` chunks, declared `data` length vs. file length |
| AIFF | FORM size vs. file size, presence of `COMM` and `SSND`, `SSND` extent |
| FLAC | `STREAMINFO` parse; declared total samples vs. decoded frames (flags > 1 % or > 4096 samples missing) |
| OGG | End-of-stream page present in the last 64 KiB and its EOS flag set |
| AAC (ADTS) | Frame-by-frame sync-word and length walk; truncated final frame is an error |
| MP4 / M4A | Box walk; missing `ftyp` or `moov` is an error, missing `mdat` is a warning |
| MP3 | ID3 skip, first MPEG frame sync, heuristic CBR size check (skipped for VBR/Xing) |

A file whose declared extension does not match the detected container is rejected with an
actionable message rather than being decoded blindly.

---

## 3. Loudness — ITU-R BS.1770-4 / EBU R128

Implementation: `backend/app/analysis/loudness.py`.

### 3.1 K-weighting

Two second-order sections, designed for the *source* sample rate with the bilinear transform:

| Stage | Type | f₀ | Q | Gain |
| --- | --- | --- | --- | --- |
| 1 | High shelf (head model) | 1681.974450955533 Hz | 0.7071752369554196 | +3.999843853973347 dB |
| 2 | RLB high-pass | 38.13547087602444 Hz | 0.5003270373238773 | 0 dB |

Coefficients are derived per sample rate, so a 44.1 kHz file is filtered with 44.1 kHz
coefficients — not resampled to 48 kHz first.

### 3.2 Block structure

| Quantity | Block | Step | Overlap | Gate |
| --- | --- | --- | --- | --- |
| Momentary (M) | 400 ms | 100 ms | 75 % | — |
| Integrated (I) | 400 ms blocks | 100 ms | 75 % | absolute −70 LUFS + relative −10 LU |
| Short-term (S) | 3 s | 100 ms | 97 % | — |
| Loudness range (LRA) | 3 s short-term | 100 ms | 97 % | absolute −70 LUFS + relative −20 LU |

The energy of each 100 ms step is the mean square of the K-filtered signal; the 400 ms and 3 s
windows are moving averages over that step series.

**Integrated loudness** (BS.1770-4 §5):

```
l = -0.691 + 10·log10( Σ_ch G_ch · mean(z_ch²) )
```

`G_ch` are the channel weights (1.0 for mono and stereo; BS.1770-4 weights for multichannel,
with the caveat noted in `channel_weighting_note`). The `-0.691` constant compensates the
+0.691 dB K-weighting gain at 1 kHz, so a 1 kHz sine at −6.02 dBFS peak reads ≈ **−9.07 LUFS**.

**Loudness range** (EBU Tech 3342): 10th–95th percentile of the gated short-term loudness
distribution.

### 3.3 True peak

BS.1770-4 Annex 2. Each channel is resampled with a polyphase Kaiser-windowed FIR at **4×** the
source rate (`scipy.signal.resample_poly`, window `("kaiser", 5.0)`) and the maximum absolute
sample is taken. The signal is processed in 4 s chunks with 100 ms overlap padding so the filter
state does not corrupt chunk edges.

`true_peak_dbtp` is the maximum across channels; `true_peak_channels_dbtp` keeps the per-channel
values. Sample peak and true peak are reported separately — a file can have a −0.1 dBFS sample
peak and a +0.5 dBTP true peak.

### 3.4 Other loudness fields

| Field | Definition |
| --- | --- |
| `crest_factor_db` | Sample peak (dBFS) − RMS (dBFS) |
| `peak_to_loudness_ratio_db` | True peak (dBTP) − integrated LUFS |
| `relative_gate_lufs` | The computed relative gate (integrated + −10 LU) |
| `gated_blocks` / `block_count` | Blocks surviving the gate and the total block count |
| `confidence` | `high` when duration ≥ 3 s (one full short-term window), otherwise `low` |

### 3.5 Gain preview

`gain_preview()` is **arithmetic only** and never writes audio:

```
gain_db               = target_lufs − integrated_lufs
expected_sample_peak  = sample_peak_dbfs + gain_db
expected_true_peak    = true_peak_dbtp + gain_db
peak_control_required = max(0, expected_true_peak − true_peak_limit)
```

If the expected true peak exceeds the limit, the status is `true_peak_limit_exceeded` and the
required additional reduction is given. If the integrated loudness is below the gate, the preview
returns `supported: false` with an explanation instead of a meaningless number.

---

## 4. Time domain

Implementation: `backend/app/analysis/time_domain.py`.

### 4.1 Levels

| Measurement | Definition |
| --- | --- |
| Sample peak | `max(|x|)` over all channels → dBFS |
| RMS | `sqrt(mean(x²))` over all channels → dBFS, plus per-channel RMS |
| DC offset | Arithmetic mean of each channel over the full file; `max_abs` across channels |
| Duration | Sample count ÷ sample rate |

### 4.2 Clipping

Two independent detectors are combined:

1. **Sample threshold** — samples with `|x| ≥ 10^(T/20)` where `T = −0.1 dBFS` (configurable).
   The percentage is `clipped_samples / (n × channels) × 100`.
2. **Flat-top count** — consecutive samples whose difference is `< 1e-6` inside a clipped run.
   This detects hard clipping even when the ceiling is below the configured threshold.

Regions are built from the sample mask and merged with a 10 ms gap; at most 200 are retained.
`intersample_overs` is `true` when the sample peak is above −1.5 dBFS **and** the true peak
exceeds 0 dBTP.

### 4.3 Silence

50 ms RMS frames with a 25 ms hop (50 % overlap). A frame is silent when its RMS is below
−60 dBFS. Regions are merged with a 100 ms tolerance and reported with start, end and duration.
Digital silence is reported separately (frame RMS `< 1e-10`).

### 4.4 Dropouts

A dropout is a short, abrupt dip:

```
rms_db < −55 dBFS  AND  rms_db < local_median − 25 dB
```

where `local_median` is a 2 s median filter of the frame RMS series. Candidates must last between
20 ms and 1 s and must not touch the first or last 250 ms of the file (which are usually fades).
At most 20 regions are reported.

### 4.5 Noise floor and SNR

The noise floor is the **10th percentile of the audible 50 ms RMS frames**, where "audible" means
frames above −100 dBFS. It is only reported when there is at least **6 dB of separation** from the
median frame level:

```
median_level − noise_candidate ≥ 6 dB  →  report noise_floor_dbfs and snr_db
                                   < 6 dB  →  both are null, confidence = "unavailable"
```

`snr_db = overall RMS (dBFS) − noise floor (dBFS)`.

This rule is the reason a clean sine tone reports `noise_floor_dbfs: null` instead of a
meaningless value: the 10th percentile of a steady tone *is* the tone level. The QC engine turns
the null into an **Information** finding — “A noise floor could not be separated from the
signal” — never an error.

### 4.6 Waveform and envelopes

| Output | Method |
| --- | --- |
| Waveform buckets | Up to 4000 buckets; each stores min, max and RMS of the mono mix |
| Per-channel waveform | Same bucketing for the first two channels |
| Envelopes | 50 ms frames / 25 ms hop; RMS and peak in dB, downsampled to ≤ 1200 points |

---

## 5. Spectral analysis

Implementation: `backend/app/analysis/spectral.py`.

### 5.1 STFT

| Parameter | Value |
| --- | --- |
| Window | Hann, periodic (`sym=False`) |
| FFT size | 4096 (configurable 256–16384) |
| Hop | 1024 (configurable 32–n_fft) |
| Padding | `n_fft // 2`, reflect mode |
| Processing | 256-frame blocks to bound memory |

Amplitude is calibrated as `2·|X(k)| / Σw`, with the DC and Nyquist bins halved. A full-scale
sine therefore reads **0 dBFS** at its peak bin. This calibration is verified by
`tests/test_spectral.py::test_fft_amplitude_is_calibrated_to_dbfs`.

### 5.2 Average spectrum and peaks

The average spectrum is the mean of `|STFT|` across all frames, in dBFS. Peaks are found with
`scipy.signal.find_peaks` (prominence ≥ 6 dB, height ≥ −100 dB) and refined by:

* **Parabolic interpolation** of the log-magnitude peak → sub-bin frequency accuracy.
* **Main-lobe integration** over ±2 bins of the PSD → amplitude is not underestimated by
  rectangular-window leakage.

Each peak is tested against the dominant frequency: if `f_peak / f_0` is within 2.5 % of an
integer ≥ 1, the peak is labelled `harmonic_of_dominant`.

### 5.3 Spectral features

Computed per frame from the magnitude spectrum:

| Feature | Definition |
| --- | --- |
| Centroid | `Σ f·A / Σ A` |
| Bandwidth | `sqrt(Σ (f − centroid)²·A / Σ A)` |
| Roll-off (85 %) | Lowest frequency where the cumulative amplitude reaches 85 % |
| Flatness | `exp(mean(log A)) / mean(A)` — Wiener entropy |
| Flux | RMS of the positive first difference, normalised by the mean amplitude |
| ZCR | Mean of `|Δ sign(x)|` over the raw frame |
| Contrast | `librosa.feature.spectral_contrast` (6 bands, fmin 100 Hz) |
| Energy | `10·log10(Σ PSD)` per frame |
| HNR | Harmonic/percussive energy ratio from HPSS (see §5.6) |

Each feature is summarised as mean, median, p5, p95, min, max, std plus a downsampled timeline.

### 5.4 Spectrogram, Mel and chroma

| View | Resolution | Notes |
| --- | --- | --- |
| Spectrogram (linear) | 256 frequency groups × ≤ 320 time groups | dBFS, floor −140 dB |
| Spectrogram (log) | 160 log-spaced bins | Interpolated from the linear grid |
| Mel | 128 bands × ≤ 300 columns | Slaney-normalised filterbank, 20 Hz–min(20 kHz, Nyquist) |
| Chroma | 12 pitch classes × ≤ 300 columns | `chroma_stft`, L2-normalised per frame |

Long files are time-averaged into the display grid; the *measurements* always use every frame.

### 5.5 Frequency bands

Seven production bands, integrated from the averaged PSD:

| Key | Range |
| --- | --- |
| `sub_bass` | 20–60 Hz |
| `bass` | 60–250 Hz |
| `low_midrange` | 250–500 Hz |
| `midrange` | 500–2000 Hz |
| `upper_midrange` | 2000–4000 Hz |
| `presence` | 4000–6000 Hz |
| `brilliance` | 6000–20000 Hz |

Each band reports absolute power (dB), percentage of the 20 Hz–20 kHz total, frame-to-frame
standard deviation, and p5/p95 frame levels.

### 5.6 HPSS

`librosa.effects.hpss` (median filtering, kernel 31, power 2.0) on a window of up to 120 s taken
from the centre of the file. Reported:

* `harmonic_energy_ratio`, `percussive_energy_ratio`, `residual_energy_ratio`
* `hnr_db = 10·log10(harmonic_energy / percussive_energy)`
* Spectral centroids of the harmonic and percussive components
* RMS envelopes of original, harmonic and percussive signals

This ratio is **not** a classical autocorrelation HNR, and the payload says so in `method`. The
separation is lossy and is computed on a copy; the original file is untouched.

---

## 6. Musical estimates

Implementation: `backend/app/analysis/musical.py`. **Everything in this section is an estimate**,
not a measurement, and carries a confidence field.

### 6.1 Key

Krumhansl-Schmuckler key profiles correlated against the full-file mean chroma vector:

1. Normalise the chroma vector to sum 1.
2. For all 24 (tonic × mode) combinations, rotate the profile to the tonic and compute the
   Pearson correlation with the chroma vector.
3. Convert the top scores to a softmax with temperature 0.08 → probability distribution.
4. `confidence = P(best) × (correlation + 1) / 2`, clamped to [0, 1].

| Confidence | Label |
| --- | --- |
| ≥ 0.65 | high |
| ≥ 0.40 | medium |
| < 0.40 | low |

The four strongest alternatives are returned with their correlation and probability.

### 6.2 Tempo and beats

| Step | Method |
| --- | --- |
| Onset envelope | `librosa.onset.onset_strength`, hop 512, median aggregation |
| Tempo | `librosa.beat.beat_track` with the normalised onset envelope |
| Beats | Frame indices converted to seconds and clipped to the file duration |
| Interval statistics | Mean, median, standard deviation and coefficient of variation of the beat intervals |
| Stability score | `1 − CV`, clamped to [0, 1] |
| Consistency | Fraction of intervals within ±10 % of the median |
| Candidates | Tempogram peaks between 30 and 300 BPM, labelled primary / half-time / double-time / alternate |
| Local tempo | Tempogram peaks over time; a region is flagged when it deviates > 5 % from the global tempo with strength ≥ 0.25 |

Tempo confidence: `high` when ≥ 8 beats and CV ≤ 0.03, `medium` when ≥ 4 beats and CV ≤ 0.08,
otherwise `low`.

### 6.3 Onsets

`librosa.onset.onset_detect` with `backtrack=False`. Reported: onset times, onset strengths,
density (onsets per second), inter-onset interval CV and the fraction of onsets that fall more
than a quarter of a beat away from the beat grid.

### 6.4 Pitch (F0)

`librosa.pyin` (probabilistic YIN):

| Parameter | Value |
| --- | --- |
| Range | fmin C2 = 65.4 Hz, fmax C7 = 2093 Hz |
| Frame | 2048 samples, hop 512 |
| Window | Up to 30 s from the centre of the file |

Reported: median/p5/p95/min/max F0, pitch range in semitones, stability (standard deviation in
semitones), voiced fraction, confidence, note transitions, the six dominant notes and the pitch
histogram.

`confidence = mean(voiced_probability) × (0.5 + 0.5 × voiced_fraction)`.

> pyin assumes a predominant monophonic pitch. On dense polyphonic material, octave errors and
> dropouts are expected — the payload carries this limitation explicitly.

---

## 7. Stereo analysis

Implementation: `backend/app/analysis/stereo.py`.

### 7.1 Mono handling

For a mono file the function returns:

```json
{
  "supported": false,
  "mono": true,
  "reason": "Mono file: stereo width, correlation and mid/side metrics do not exist. No artificial stereo values are reported.",
  "mono_rms_dbfs": -10.97,
  "mono_peak_dbfs": -7.96,
  "mono_compatibility": { "applicable": false, "...": "..." },
  "confidence": "high"
}
```

No `correlation`, `mid_side`, `width` or vectorscope keys are present at all. The QC engine adds
an Information entry (“Mono file: stereo width, correlation, and phase metrics are not
applicable”) and the comparison engine returns `status: "unsupported"` for stereo parameters when
the file set mixes mono and stereo.

### 7.2 Stereo metrics

| Metric | Definition |
| --- | --- |
| Correlation `r` | Pearson correlation of the decimated L/R signals (decimation factor keeps ≤ 2 M samples) |
| Balance | `20·log10(rms_R / rms_L)`, labelled centred / n dB left / n dB right |
| Mid | `(L + R) / 2` |
| Side | `(L − R) / 2` |
| Stereo width | `side_rms / (mid_rms + side_rms) × 100 %` |
| Side-to-mid ratio | `side_rms / mid_rms` |
| Mono fold-down | `(L + R) / 2` |
| Mono loss | `20·log10(mono_rms / stereo_rms)` — negative means the fold-down loses level |
| Mono peak | Peak of the folded-down signal |
| Vectorscope | Up to 3000 evenly sampled L/R pairs, normalised for display only |
| Correlation timeline | Windowed correlation, ≤ 600 points |
| Phase regions | Time regions where the windowed correlation is below −0.1 |

### 7.3 Stereo findings

| Condition | Severity |
| --- | --- |
| \|balance\| > 1.5 dB | warning (`channel_imbalance`) |
| One channel effectively silent (`min rms < 1e-4`, `max rms > 1e-2`) | error (`silent_channel`) |
| Correlation < −0.1 | warning (`negative_phase_correlation`) |
| Mono loss < −6 dB | warning (`mono_compatibility_loss`) |
| Side/mid > 2.0 | info (`very_wide_stereo`) |
| Negative-correlation regions exist | info (`phase_cancellation_sections`) |

A file is considered mono-compatible when `r ≥ −0.1` **and** mono loss > −6 dB.

---

## 8. Dynamics

Implementation: `backend/app/analysis/dynamics.py`.

| Metric | Definition |
| --- | --- |
| `crest_factor_db` | Sample peak − RMS |
| `dynamic_range_db` | The crest factor, with the definition stated in the payload |
| `peak_to_loudness_ratio_db` | True peak − integrated loudness |
| `loudness_range_lu` | EBU Tech 3342 LRA |
| `rms_variation_db` | Standard deviation of the 50 ms RMS frames in dB |
| `short_term_dynamic_variation_lu` | Standard deviation of the 3 s short-term loudness series |
| `short_term_range_lu` | p95 − p5 of the short-term loudness series |
| `crest_factor_median_db` | Median of the per-frame crest series |

**Compression indicators** are observations, not defects: low LRA (< 4 LU), low PLR (< 8 dB), low
crest (< 6 dB), consistent loudness (short-term σ < 1.5 LU) and wide LRA (> 20 LU).

**Reduced-dynamic sections** are located with a sliding 15 s window (5 s step): a section is
flagged when the local LRA is below 2.5 LU or the local crest range is below 5 dB. Adjacent
sections are merged and at most 50 are returned.

---

## 9. Quality control

Implementation: `backend/app/analysis/qc.py`.

### 9.1 Classification

| Level | Condition |
| --- | --- |
| **normal** | The measured value is inside the configured range |
| **information** | A factual observation with no threshold breach (or an unavailable measurement) |
| **warning** | A configured warning threshold was crossed |
| **error** | A configured error threshold was crossed |

The overall verdict is the highest severity present. Findings are sorted by severity, then
category, then title.

### 9.2 Default thresholds

| Key | Default | Unit | Error threshold |
| --- | --- | --- | --- |
| `clipping_percent_warning` | 0.005 | % | `clipping_percent_error` = 0.05 % |
| `true_peak_warning_dbtp` | −1.0 | dBTP | `true_peak_error_dbtp` = 0.0 dBTP |
| `loudness_min_lufs` | −30.0 | LUFS | — (range, warning only) |
| `loudness_max_lufs` | −6.0 | LUFS | — |
| `lra_min_lu` | 2.0 | LU | — (below = information) |
| `lra_max_lu` | 25.0 | LU | — (above = warning) |
| `noise_floor_warning_dbfs` | −55.0 | dBFS | `noise_floor_error_dbfs` = −40.0 dBFS |
| `snr_warning_db` | 30.0 | dB | — |
| `dc_offset_warning` | 0.005 | linear | — |
| `silence_percent_warning` | 30.0 | % | `silence_percent_error` = 95.0 % |
| `correlation_warning` | −0.1 | r | `correlation_error` = −0.5 |
| `channel_imbalance_warning_db` | 1.5 | dB | `channel_imbalance_error_db` = 6.0 dB |
| `dropout_warning_count` | 1 | regions | — |
| `crest_factor_warning_db` | 6.0 | dB | — (below = information) |
| `bit_depth_warning_bits` | 16 | bits | — |
| `common_sample_rates` | 8000 … 192000 | Hz | — (informational if outside) |

`merge_thresholds()` enforces ordering invariants: an error threshold is never allowed to fall
below its warning threshold for clipping, noise floor, silence, channel imbalance and true peak.
Unknown keys are ignored; non-finite values are discarded.

### 9.3 Check list

`integrity`, `clipping`, `true_peak`, `integrated_loudness`, `loudness_range`, `noise`,
`dc_offset`, `silence`, `correlation`, `channel_imbalance`, `stereo_mono` (mono case),
`sample_rate`, `bit_depth`, `bit_depth_lossy`, `dropouts`, `crest_factor`, plus the spectral and
dynamic observations and low-confidence estimate notices.

Every check contains: `measured_value`, `measured_unit`, `threshold_value`, `threshold_unit`,
`message`, `explanation`, `recommendation`, `time_positions`, `confidence` and `standard`
(where a standard applies).

### 9.4 Re-classification

`POST /api/sessions/{id}/qc/recompute` re-runs the QC engine against the stored measurements with
new thresholds. The audio is **not** re-analysed, so a threshold change takes effect in
milliseconds.

---

## 10. Comparison

Implementation: `backend/app/analysis/comparison.py`.

### 10.1 Parameters

40+ parameters across eight groups: File, Loudness, Dynamics, Signal quality, Stereo, Musical,
Spectral and Frequency bands. Each specification carries a `path` into the analysis payload, a
`unit`, a `kind` (`numeric`, `categorical` or `band`), an absolute `tolerance`, an optional
`relative` tolerance and an optional `confidence_path`.

### 10.2 Status

| Status | Meaning |
| --- | --- |
| `match` | Every file is within the tolerance of the reference/spread |
| `different` | The spread exceeds the tolerance but stays within 2× |
| `large_deviation` | The spread exceeds 2× the tolerance |
| `low_confidence` | The value exists but the source measurement is low confidence |
| `unsupported` | The parameter does not apply (for example stereo metrics for a mono file) |

`display` strings show `—` for unsupported values; `deviations` are relative to the reference file
(or to the mean when no reference is chosen).

### 10.3 Other outputs

* `summary.match` — number of parameters that match.
* `gain_preview` — per-file gain to the target LUFS with the resulting true peak and required
  peak control.
* `cross_file_findings` — parameters where the files disagree the most.

---

## 11. Alignment

Implementation: `backend/app/analysis/alignment.py`.

| Method | Detail |
| --- | --- |
| `manual` | The supplied offset is returned verbatim, confidence 1.0, label `manual` |
| `envelope` | 100 Hz RMS envelope, log-compressed (`log1p(env × 1000)`), normalised cross-correlation |
| `waveform` | Mono, resampled to 8 kHz, mean-removed and RMS-normalised, first 120 s |
| `auto` | Both of the above; the candidate with the higher confidence is chosen |

### 11.1 Correlation and confidence

The lag search uses `scipy.signal.fftconvolve` over all lags within ±`max_offset_seconds`.

```
confidence = |peak| / sqrt(Σa² · Σb²)      (normalised correlation, 0…1)
ratio      = |peak| / |best peak outside ±3 bins|
```

| Label | Condition |
| --- | --- |
| `high` | confidence ≥ 0.75 **and** ratio ≥ 1.5 |
| `medium` | confidence ≥ 0.45 |
| `low` | otherwise |

The `ratio` term is a **stability check**: a periodic signal produces a cross-correlation with
many near-equal peaks, so the second-best candidate is almost as strong as the best one. A
perfect correlation (`confidence = 1.0`) with a low ratio is therefore reported as `medium`,
because the lag itself is ambiguous even though the match is exact. For stationary material
(a pure tone) the envelope method is degenerate; use a manual offset or a transient-rich file.

The offset sign convention is explicit in the payload: **positive means file B starts later than
file A**; the shift to apply to B is `−offset`. Alignment is computed on decoded copies — the
stored originals are never modified.

---

## 12. Segment analysis

`backend/app/analysis/segment.py` re-runs the loudness, time-domain and spectral analysis over a
bounded time range (`start`, `end` in seconds, validated against the file duration). The response
reports the segment boundaries, the duration actually analysed and the measurements for that
range. The original file and the full-file analysis artifact are untouched.

---

## 13. Reporting

Implementation: `backend/app/reporting.py`.

### 13.1 Formats

| Format | Builder | Content |
| --- | --- | --- |
| PDF | `build_pdf` | ReportLab: cover, per-file tables, embedded plots, QC findings, comparison tables |
| JSON | `build_json_report` | Session metadata, full analysis payloads, methods, QC, optional comparison, disclaimer |
| CSV | `build_csv` | One row per file with the key measurements |
| QC CSV | `build_qc_csv` | One row per QC check: severity, measured value, threshold, time positions, recommendation |
| Comparison CSV | `build_comparison_csv` | One row per parameter: values, tolerance, spread, status |

### 13.2 Plots

14 server-rendered per-file PNG types using Matplotlib with the `Agg` backend: `waveform`,
`spectrum`, `spectrogram`, `mel`, `chroma`, `loudness`, `rms_peak`, `bands`, `vectorscope`,
`dynamics`, `tempo`, `pitch`, `spectral_features`, `stereo`.

Three further comparison plots are available for a multi-file session: `comparison_bands`,
`comparison_loudness` and `comparison_spectrum`.

For PDF embedding, plots are rasterised to JPEG at quality 86, which keeps the document size
reasonable while preserving readability.

---

## 14. HTTP API

All routes are prefixed `/api`. When `AAP_API_KEY` is set, every route except `/api/health`
requires the `X-API-Key` header.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Liveness, version, supported formats, effective limits |
| GET | `/api/settings` | Defaults, threshold schema, methods, limits |
| GET | `/api/qc/thresholds` | Default thresholds and the editable schema |
| POST | `/api/sessions` | Create a session |
| GET | `/api/sessions/{id}` | Session state, files and jobs |
| GET | `/api/sessions/{id}/overview` | Aggregated dashboard data |
| PATCH | `/api/sessions/{id}` | Rename / update settings |
| DELETE | `/api/sessions/{id}` | Delete a session and its files |
| POST | `/api/sessions/{id}/files` | Upload one or more files (multipart) |
| GET | `/api/sessions/{id}/files/{fid}` | File record |
| DELETE | `/api/sessions/{id}/files/{fid}` | Remove a file |
| GET | `/api/sessions/{id}/files/{fid}/audio` | Stream the original file (read-only) |
| GET | `/api/sessions/{id}/files/{fid}/analysis` | The analysis artifact |
| GET | `/api/sessions/{id}/files/{fid}/waveform` | Waveform buckets (optionally windowed) |
| GET | `/api/sessions/{id}/files/{fid}/spectrum` | Average spectrum (optionally windowed) |
| GET | `/api/sessions/{id}/files/{fid}/spectrogram` | Spectrogram (optionally windowed) |
| POST | `/api/sessions/{id}/files/{fid}/segment-analysis` | Analyse a time range |
| POST | `/api/sessions/{id}/analyze` | Queue analysis for all (or selected) files |
| POST | `/api/sessions/{id}/files/{fid}/analyze` | Queue analysis for one file |
| GET | `/api/jobs/{job_id}` | Job status and progress |
| GET | `/api/sessions/{id}/jobs` | All jobs of a session |
| POST | `/api/sessions/{id}/compare` | Compare files |
| POST | `/api/sessions/{id}/align` | Align two files |
| POST | `/api/sessions/{id}/qc/recompute` | Re-run QC with new thresholds |
| POST | `/api/sessions/{id}/reports` | Generate a report (`pdf`, `csv`, `json`, `qc-csv`, `comparison-csv`) |
| GET | `/api/sessions/{id}/files/{fid}/plots/{kind}.png` | Per-file plot PNG |
| GET | `/api/sessions/{id}/plots/comparison/{kind}.png` | Comparison plot PNG |

Identifiers are `ses_<32 hex>`, `fil_<32 hex>` and `job_<32 hex>`. A malformed identifier returns
**400**; a well-formed but unknown identifier returns **404**.

---

## 15. Frontend

### 15.1 Stack

React 19 + TypeScript + Vite 8, Plotly.js (`plotly.js-dist-min`), `lucide-react` icons and a
hand-written dark CSS theme (no utility framework).

### 15.2 Routing

Hash routing (`/#/dashboard`, `/#/spectrum`, …) so the production build can be served from any
path by the FastAPI static handler without server-side rewrite rules.

### 15.3 State

`src/state/AppContext.tsx` owns the session, the file list, the job polling loop and the
selected files. Analysis progress is polled while any job is active and the poll stops when all
jobs settle. API access goes through `src/lib/api.ts`, which attaches the API key and converts
errors into typed exceptions.

### 15.4 Interaction

* Zoom and pan on every time-domain and spectral plot (Plotly `dragmode: "zoom"` plus explicit
  range buttons).
* Hover tooltips with measured values and units.
* Time selection on the waveform drives the segment analysis.
* Comparison filters by parameter group; unsupported values are rendered as `—`.
* Severity filters in the QC section; check rows expand to show the explanation, the
  recommendation and the time positions.
* Responsive breakpoints at 900 px, 720 px and 520 px; the sidebar collapses to an off-canvas
  drawer on small screens.
* Density and reduced-motion preferences persist in `localStorage`.

---

## 16. Security and privacy

| Measure | Implementation |
| --- | --- |
| API key | `AAP_API_KEY`; validated in middleware for every `/api` route except health |
| Security headers | `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, `Cross-Origin-Resource-Policy` |
| CORS | Restricted to the local Vite origins by default |
| Upload safety | Size limit, extension allow-list, container sniffing, structural validation |
| Original integrity | SHA-256 over the stored file; the file is opened read-only after upload |
| Data locality | All processing happens on the server; no third-party service is contacted |
| Retention | Sessions expire after `AAP_SESSION_TTL_HOURS` and are removed by a cleanup thread |
| Least privilege | The service only needs write access to `AAP_DATA_DIR` |

---

## 17. Known limitations

1. **Multichannel loudness** uses the BS.1770-4 weights for the first five channels; LFE handling
   is approximate and channel order is taken from the decoder.
2. **HNR** is a harmonic/percussive energy ratio, not an autocorrelation-based HNR.
3. **Key, tempo and pitch** are statistical estimates. Modal, atonal or heavily percussive
   material produces low-confidence results — the confidence field says so.
4. **Noise floor** is a percentile statistic, so a file with no quiet material has no noise floor
   value at all.
5. **HPSS and pitch** are computed on a bounded window (120 s / 30 s) from the centre of longer
   files; the payload records `is_segment` and the analysed range.
6. **Session state is process-local.** Horizontal scaling requires sticky routing or a shared
   storage backend (see [DEPLOYMENT.md](DEPLOYMENT.md)).
7. **Plotly's full bundle** is large (~5 MB raw, ~1.5 MB gzipped). Partial imports would reduce it
   but are not implemented yet.
