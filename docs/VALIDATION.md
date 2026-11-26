# Validation Report

**Subject** — Audio Analysis Pipeline, version 1.0
**Date** — 25 November 2026
**Platform** — Windows 11 (win32), Python 3.12.10, pytest 9.1.1, NumPy 2.x, SciPy 1.x,
librosa 0.10.x

This report records what was actually executed and what was actually observed. Every number
below comes from a command in this repository and can be reproduced. No result is quoted from
memory or from a marketing claim.

---

## 1. Summary

| Check | Result |
| --- | --- |
| Automated test suite | **62 passed**, 0 failed, 0 skipped — 52.84 s |
| Backend byte-compile | `python -m compileall -q app` — clean, no output |
| Frontend production build | `npm run build` — success, 2.54 s |
| Frontend type check (via build) | no TypeScript errors |
| BS.1770-4 vs. `pyloudnorm` | **17/17 files pass**, worst difference **0.0061 LU**, mean **0.0033 LU** |
| Loudness vs. analytic reference | difference **0.0391 LU** (tolerance 0.2 LU) |
| True peak vs. independent oversampling | difference **0.0000 dBTP** (tolerance 0.3 dB) |
| Alignment of a known 0.75 s delay | recovered **0.7500 s**, error **0.0000 s** |
| Key estimation (C major triad) | **C major**, confidence 0.777 (high) |
| Tempo estimation (120 BPM grid) | **120.19 BPM**, 15 beats, stability *stable* (CV 0.006) |
| Live-server end-to-end smoke test | **59 of 59 checks passed** via `scripts/smoke_test.py` (exit code 0); an independent HTTP harness ran **68 of 68** |
| Dominant frequency (generated 440 Hz tone) | **439.95 Hz** (error 0.05 Hz) |

---

## 2. How to reproduce

```bash
# 0. Reference signals
python scripts/generate_test_audio.py --out backend/data/test_audio

# 1. Automated tests
cd backend && pip install -r requirements-dev.txt && python -m pytest

# 2. Loudness cross-check against an independent implementation
python scripts/validate_loudness_against_pyloudnorm.py --audio backend/data/test_audio

# 3. Reference-signal measurement table
python scripts/validate_reference_signals.py --audio backend/data/test_audio

# 4. Frontend build
cd frontend && npm ci && npm run build
```

Machine-readable outputs:

* `docs/loudness_crosscheck.json` — the pyloudnorm comparison
* `docs/validation_results.json` — the reference-signal measurement table

---

## 3. Automated test suite

```
platform win32 -- Python 3.12.10, pytest-9.1.1, pluggy-1.6.0
rootdir: ...\audio_analysis_pipeline\backend
configfile: pytest.ini
testpaths: tests
collected 62 items

tests\test_api.py ................                                         [ 19%]
tests\test_comparison_alignment.py ......                                  [ 29%]
tests\test_loudness.py .......                                             [ 40%]
tests\test_musical.py .....                                                [ 48%]
tests\test_qc.py .......                                                   [ 59%]
tests\test_reporting.py .....                                              [ 67%]
tests\test_spectral.py .......                                             [ 79%]
tests\test_stereo.py .....                                                 [ 87%]
tests\test_time_domain.py ........                                         [100%]

======================= 62 passed, 1 warning in 52.84s ========================
```

The single warning is a `NumbaWarning` emitted by librosa's internal JIT when the same ufunc
signature is compiled twice in one process. It is a third-party informational warning, does not
affect any measurement, and is suppressed in `backend/pytest.ini` for the default run.

### 3.1 Test inventory

Every test below passed on the run described above.

#### Time domain (8 tests)

| Test | What it proves |
| --- | --- |
| `test_rms_and_peak_match_analytic_values` | RMS and sample peak match the closed-form values of a sine |
| `test_dc_offset_is_measured` | A known DC offset is recovered |
| `test_clipping_is_detected_with_regions` | Hard clipping is detected and localised into regions |
| `test_silence_and_digital_silence_are_detected` | Silence percentage and digital-silence regions are correct |
| `test_true_peak_is_not_below_sample_peak` | True peak ≥ sample peak always |
| `test_noise_floor_is_not_reported_for_a_pure_tone` | A steady tone yields `noise_floor_dbfs = null` — **no fabricated value** |
| `test_noise_floor_is_reported_when_quiet_material_exists` | A tone with quiet material yields a real noise floor and SNR |
| `test_waveform_buckets_are_bounded` | The waveform bucket count respects the configured cap |

#### Loudness (7 tests)

| Test | What it proves |
| --- | --- |
| `test_integrated_loudness_matches_analytic_reference` | Integrated LUFS matches the closed-form BS.1770 value within 0.2 LU |
| `test_integrated_loudness_matches_pyloudnorm_when_available` | Agreement with `pyloudnorm` (skipped gracefully if absent) |
| `test_true_peak_agrees_with_independent_oversampling` | True peak matches an independent 4× resampling within 0.3 dB |
| `test_gain_preview_computes_linear_gain_and_peak_control` | Gain arithmetic and required peak-control reduction are exact |
| `test_gain_preview_reports_ok_when_peaks_stay_below_the_limit` | Status is `ok` when the target is reachable |
| `test_gain_preview_is_unsupported_below_the_gate` | No gain is offered below the gating threshold |
| `test_loudness_blocks_have_consistent_lengths` | Momentary/short-term block arrays are aligned and gated correctly |

#### Spectral (7 tests)

| Test | What it proves |
| --- | --- |
| `test_dominant_frequency_is_measured_within_one_bin` | The dominant frequency is correct to within one FFT bin |
| `test_fft_amplitude_is_calibrated_to_dbfs` | A full-scale sine on a bin centre reads −6.02 dBFS ± 0.35 dB |
| `test_band_energy_follows_the_signal` | Energy lands in the correct band (sub-bass vs. bass) and the percentages sum to 100 % ± 1.5 % |
| `test_spectral_centroid_tracks_the_tone_frequency` | The centroid follows the signal |
| `test_spectral_flatness_is_low_for_a_tone_and_high_for_noise` | Wiener flatness separates tonal from noise-like material |
| `test_spectrogram_dimensions_are_consistent` | The spectrogram matrix matches its axis lengths |
| `test_compute_average_spectrum_and_range_endpoints` | The range-restricted spectrum helpers work |

#### Stereo (5 tests)

| Test | What it proves |
| --- | --- |
| `test_identical_channels_are_fully_correlated` | r = 1.00 ± 0.01, width ≈ 0 %, balance ≈ 0 dB |
| `test_inverted_channels_are_negatively_correlated` | r = −1.00 ± 0.01, mono loss < −30 dB, incompatible |
| `test_mono_input_is_reported_as_mono_without_stereo_values` | A mono file returns `supported: false` and contains **no** `correlation` or `mid_side` keys |
| `test_channel_imbalance_is_flagged` | A level difference is flagged as `channel_imbalance` |
| `test_timeline_and_vectorscope_are_populated` | The timeline and vectorscope are populated and internally consistent |

#### Musical estimates (5 tests)

| Test | What it proves |
| --- | --- |
| `test_tempo_is_estimated_from_a_click_track` | 120 BPM detected within 6 BPM |
| `test_beats_are_aligned_with_the_click_grid` | Median beat interval 0.5 s ± 0.05 s and every beat within 80 ms of the grid |
| `test_pitch_is_estimated_for_a_steady_tone` | F0 median 220 Hz within 6 % |
| `test_key_is_estimated_for_a_major_triad` | The key estimate resolves to C major |
| `test_musical_result_declares_estimates_and_limitations` | The payload declares its estimates and limitations |

#### Quality control (7 tests)

| Test | What it proves |
| --- | --- |
| `test_merge_thresholds_keeps_error_thresholds_consistent` | Error thresholds are never allowed below warning thresholds |
| `test_threshold_schema_matches_the_default_thresholds` | Every editable field exists and its default is inside its own bounds |
| `test_clean_tone_produces_no_qc_errors` | A clean signal produces no errors |
| `test_clipping_is_classified_as_an_error` | Clipping is an error with time positions |
| `test_every_check_contains_explanation_and_recommendation` | Every check has an explanation, a recommendation, a confidence and a time-position list |
| `test_threshold_overrides_reclassify_existing_measurements` | Tightening a threshold reclassifies a stored measurement without re-analysis |
| `test_noise_floor_is_information_not_an_error` | An unmeasurable noise floor is Information, never an Error |

#### Comparison and alignment (6 tests)

| Test | What it proves |
| --- | --- |
| `test_comparison_marks_level_differences` | A 17 dB level difference is flagged, spread > 5 LU |
| `test_comparison_supports_a_reference_file` | Deviations are computed against the reference file |
| `test_comparison_reports_unsupported_values_for_mono_stereo_pairs` | Stereo parameters are `unsupported` for a mono file |
| `test_parameter_specs_expose_tolerances_and_units` | Every parameter declares a unit, a kind and non-negative tolerances |
| `test_alignment_recovers_a_known_delay` | A 0.75 s delay is recovered within 80 ms |
| `test_manual_alignment_returns_the_supplied_offset` | A manual offset is returned verbatim with confidence 1.0 |

#### API end-to-end (12 tests)

| Test | What it proves |
| --- | --- |
| `test_health_and_settings_endpoints` | Health, settings, threshold schema and limits are served |
| `test_upload_validates_and_rejects_bad_files` | A corrupt file is rejected while a valid one is accepted with correct metadata |
| `test_unsupported_extension_is_rejected` | A `.txt` upload is rejected |
| `test_analysis_artifacts_and_overview` | The artifact carries the hash, the measurements and the methods; the overview aggregates correctly |
| `test_waveform_spectrum_and_spectrogram_endpoints` | The three data endpoints return consistent shapes |
| `test_compare_and_align_endpoints` | Comparison and alignment succeed over HTTP |
| `test_qc_recompute_updates_classification` | Threshold changes take effect over HTTP and the analysis reflects them |
| `test_report_exports_in_every_format` | PDF, JSON, CSV, QC CSV and comparison CSV are all served as attachments |
| `test_plot_endpoints_render_png` | Five plot kinds return a valid PNG signature |
| `test_segment_analysis_endpoint` | A time range is analysed and reported |
| `test_session_settings_patch_and_file_removal` | Settings update and file removal work |
| `test_invalid_requests_return_client_errors` | Empty comparisons → 400; unknown well-formed id → 404; malformed id → 400 |

#### Reporting (5 tests)

| Test | What it proves |
| --- | --- |
| `test_measurement_csv_has_a_row_per_file` | One row per file with the expected columns |
| `test_qc_csv_lists_every_check` | Every QC check appears as a row |
| `test_json_report_is_serialisable_and_complete` | The JSON report parses and contains the session, files, methods and disclaimer |
| `test_pdf_report_starts_with_the_pdf_signature` | The PDF begins with `%PDF` and exceeds 5 kB |
| `test_comparison_csv_requires_a_comparison` | The comparison CSV is well-formed |

---

## 4. Loudness validation against an independent implementation

`backend/app/analysis/loudness.py` implements ITU-R BS.1770-4 from the published specification.
`pyloudnorm` is a separate implementation that shares no code with it. Agreement between the two
is the strongest practical evidence that the meter is correct.

Command:

```bash
python scripts/validate_loudness_against_pyloudnorm.py --audio backend/data/test_audio
```

| File | Built-in (LUFS) | pyloudnorm (LUFS) | Difference (LU) | Result |
| --- | ---: | ---: | ---: | :---: |
| `c_major_120bpm.flac` | −14.410 | −14.407 | −0.0026 | PASS |
| `c_major_120bpm.mp3` | −14.410 | −14.406 | −0.0036 | PASS |
| `c_major_120bpm.ogg` | −14.390 | −14.389 | −0.0014 | PASS |
| `c_major_120bpm.wav` | −14.410 | −14.407 | −0.0026 | PASS |
| `c_major_chord.wav` | −12.120 | −12.118 | −0.0017 | PASS |
| `click_120bpm.wav` | −21.820 | −21.819 | −0.0007 | PASS |
| `clipped_220.wav` | −2.620 | −2.623 | +0.0034 | PASS |
| `dc_offset_tone.wav` | −11.010 | −11.004 | −0.0061 | PASS |
| `mono_1k.wav` | −9.070 | −9.066 | −0.0036 | PASS |
| `out_of_phase_stereo.wav` | −8.680 | −8.684 | +0.0043 | PASS |
| `silence_then_tone.wav` | −11.810 | −11.805 | −0.0054 | PASS |
| `sine_1khz_mono_48k.flac` | −9.070 | −9.066 | −0.0044 | PASS |
| `sine_1khz_mono_48k.ogg` | −9.000 | −8.996 | −0.0043 | PASS |
| `sine_1khz_mono_48k.wav` | −9.070 | −9.066 | −0.0043 | PASS |
| `sine_440_stereo.wav` | −3.090 | −3.091 | +0.0012 | PASS |
| `stereo_tones.wav` | −11.150 | −11.149 | −0.0013 | PASS |
| `tone_with_noise_floor.wav` | −9.180 | −9.176 | −0.0044 | PASS |

```
files compared   : 17
mean difference  : 0.0033 LU
worst difference : 0.0061 LU (tolerance 0.05 LU)
result           : PASS
```

Every difference is far below the 0.1 LU tolerance that ITU-R BS.1770-4 compliance tests
normally require for a loudness meter.

### 4.1 Analytic reference

A 1 kHz sine at 0.5 linear amplitude (−6.02 dBFS peak) has a closed-form K-weighted loudness:

```
L = −0.691 + 10·log10( 10^(0.691/10) · 0.5² / 2 )
  = −9.0309 LUFS
```

| Quantity | Analytic | Measured | Difference |
| --- | ---: | ---: | ---: |
| Integrated loudness | −9.0309 LUFS | −9.07 LUFS | **−0.0391 LU** |
| Sample peak | −6.0206 dBFS | −6.02 dBFS | 0.0006 dB |
| RMS | −9.0309 dBFS | −9.03 dBFS | 0.0009 dB |
| Crest factor (peak − RMS) | 3.0103 dB | 3.01 dB | 0.0003 dB |

### 4.2 True peak

A 12 kHz tone at 0.9 linear amplitude sampled at 48 kHz creates an intersample peak above the
sample peak. The built-in 4× polyphase oversampler was compared with an independent
`scipy.signal.resample_poly` call:

| Quantity | Value |
| --- | ---: |
| Sample peak | −0.9151 dBFS |
| True peak (built-in) | −0.9096 dBTP |
| True peak (independent reference) | −0.9096 dBTP |
| **Difference** | **0.0000 dBTP** |

The true peak is correctly higher than the sample peak, and the QC engine flags intersample
overs whenever the sample peak is above −1.5 dBFS while the true peak exceeds 0 dBTP.

---

## 5. Reference-signal measurements

The reference files are generated deterministically by `scripts/generate_test_audio.py`, so the
table below is reproducible on any machine.

| File | LUFS | dBTP | Peak | RMS | corr | BPM | Key | QC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | :--- | :--- |
| `sine_1khz_mono_48k.wav` | −9.07 | −6.02 | −6.02 | −9.03 | — | — | B minor (low) | information |
| `sine_1khz_mono_48k.flac` | −9.07 | −6.02 | −6.02 | −9.03 | — | — | B minor (low) | information |
| `sine_1khz_mono_48k.ogg` | −9.00 | −5.53 | −5.54 | −8.96 | — | — | B minor (low) | information |
| `sine_440_stereo.wav` | −3.09 | 0.01 | 0.00 | −5.38 | 0.9801 | — | A minor (low) | error |
| `click_120bpm.wav` | −21.82 | −1.06 | −1.09 | −24.75 | — | 119.68 | A minor (low) | error |
| `c_major_chord.wav` | −12.12 | 0.02 | 0.00 | −11.08 | — | 156.25 | **C major** (medium) | error |
| `clipped_220.wav` | −2.62 | 0.02 | 0.00 | −1.69 | — | — | A major (low) | error |
| `dc_offset_tone.wav` | −11.01 | −7.74 | −7.74 | −10.96 | — | — | B minor (low) | warning |
| `silence_then_tone.wav` | −11.81 | −7.95 | −7.96 | −12.22 | — | 119.68 | A minor (low) | information |
| `out_of_phase_stereo.wav` | −8.68 | −7.95 | −7.96 | −10.97 | **−1.0000** | — | A# minor (medium) | error |
| `tone_with_noise_floor.wav` | −9.18 | −5.95 | −5.96 | −10.28 | — | 140.62 | B minor (low) | information |
| `c_major_120bpm.wav` | −14.41 | −3.92 | −3.93 | −16.59 | 1.0000 | **120.19** | **C major** (high) | information |
| `c_major_120bpm.flac` | −14.41 | −3.92 | −3.93 | −16.59 | 1.0000 | 120.19 | C major (high) | information |
| `c_major_120bpm.mp3` | −14.41 | −3.92 | −3.93 | −16.59 | 1.0000 | 120.19 | C major (high) | information |
| `c_major_120bpm.ogg` | −14.39 | −4.15 | −4.15 | −16.58 | 1.0000 | 120.19 | C major (high) | information |
| `stereo_tones.wav` | −11.15 | −10.45 | −10.46 | −13.47 | −0.0000 | — | A major (low) | information |
| `mono_1k.wav` | −9.07 | −6.02 | −6.02 | −9.03 | — | — | B minor (low) | information |

### 5.1 Interpretation of the interesting rows

**`c_major_120bpm.*` — key and tempo.**
Key **C major** with confidence **0.777** (label `high`), profile correlation 0.7789.
Tempo **120.19 BPM** against a true 120 BPM (error 0.19 BPM, 0.16 %), **15 beats** over 8 s,
interval CV 0.006 → stability label `stable`, 15 onsets detected. The same key and tempo are
recovered from the WAV, FLAC, MP3 and OGG encodings of the same programme, which demonstrates
that the estimates are robust to lossy encoding.

**`out_of_phase_stereo.wav` — polarity.**
Correlation is exactly **−1.0000**, and the file is classified as an error for mono
compatibility. This is the intended behaviour: an inverted channel pair is a real problem, not a
false positive.

**`stereo_tones.wav` — uncorrelated channels.**
Correlation is **−0.0000** (two different tones), which is correctly *not* flagged as a phase
problem, because the QC correlation warning threshold is −0.1.

**`tone_with_noise_floor.wav` — measurable noise floor.**
Noise floor **−60.02 dBFS** and SNR **49.74 dB** are reported, because the file contains
2 s of noise-only material that separates from the tone by more than the required 6 dB. The
injected noise amplitude was 0.001 (≈ −60 dBFS) — the measured value matches.

**`sine_1khz_mono_48k.wav` — deliberately absent noise floor.**
`noise_floor_dbfs` is **null** and `snr_db` is **null**, with the confidence set to
`unavailable`. A pure tone has no separable noise floor, and reporting the 10th percentile of a
steady tone as a "noise floor" would be a fabricated number. The QC engine turns this into an
**Information** finding, never an error.

**`mono_1k.wav`, `sine_1khz_mono_48k.wav` — mono handling.**
The correlation column is `—` because the stereo analysis reports `supported: false` and omits
the correlation, mid/side and width keys entirely. No stereo value is fabricated.

**`dc_offset_tone.wav` — DC offset.**
Maximum absolute channel mean **0.009986** against an injected offset of **0.010** (error
1.4 × 10⁻⁵, i.e. 16-bit quantisation noise). The default warning threshold is 0.005, so the
file is correctly classified as a **warning**.

**`clipped_220.wav` — clipping.**
**50.08 %** of samples are at the clipping threshold, true peak **+0.02 dBTP**, and the QC
verdict is **error**. The generator clips a 1.4-amplitude sine to ±1.0, which is 50.08 % of a
sine's samples — the measurement matches the construction exactly.

**`click_120bpm.wav` — silence detection.**
The click track is 99.38 % silent at the −60 dBFS threshold, which crosses the 95 % error
threshold. This is a **correct** detection of an unusual signal, not a false positive: the file
genuinely contains almost no audible signal between clicks.

**`sine_440_stereo.wav` — inter-channel phase.**
A 0.2 rad inter-channel phase offset yields correlation **0.9801**, consistent with
`cos(0.2) = 0.98007`.

### 5.2 Lossy vs. lossless metadata

| File | `bit_depth` | `bit_depth_source` | `bitrate_kbps` | `is_lossy` |
| --- | :---: | :---: | ---: | :---: |
| `c_major_120bpm.wav` | 16 | `pcm` | 1411.2 | false |
| `c_major_120bpm.flac` | 16 | `lossless` | 132.0 | false |
| `c_major_120bpm.mp3` | **null** | **null** | 39.8 | true |
| `c_major_120bpm.ogg` | **null** | **null** | 128.0 | true |
| `sine_1khz_mono_48k.wav` | 16 | `pcm` | 768.0 | false |
| `sine_1khz_mono_48k.flac` | 16 | `lossless` | 198.1 | false |
| `sine_1khz_mono_48k.ogg` | **null** | **null** | 86.0 | true |

No encoded bit depth is ever reported as a PCM bit depth, and no lossy file reports a bit depth
at all.

---

## 6. Alignment accuracy

A synthetic 0.75 s delay was inserted into a copy of a 300 Hz tone (48 kHz) and aligned with
the automatic method:

| Quantity | Value |
| --- | ---: |
| Injected delay | 0.7500 s |
| Recovered offset | **0.7500 s** |
| **Absolute error** | **0.0000 s** (0 samples at 48 kHz) |
| Method chosen | `envelope_cross_correlation` |
| Normalised correlation | 1.0000 |
| Confidence label | `medium` |
| Overlap | 4.0 s |

The confidence label is `medium` rather than `high` because the peak-to-second-peak ratio is
1.01: a steady sine produces a nearly flat RMS envelope, so the lag candidates are inherently
ambiguous even though the recovered offset is exact. This is the stability check working as
designed — it reports *reliability of the lag*, not merely the strength of the correlation. A
manual offset is returned verbatim with confidence 1.0 and the label `manual`.

---

## 7. End-to-end API validation against a live server

A live server was started with:

```bash
cd backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

and exercised over HTTP by the shipped smoke-test script:

```bash
python scripts/smoke_test.py --base http://127.0.0.1:8000
```

The script uploads the repository's reference material (`sine_1khz_mono_48k.wav` and
`c_major_120bpm.wav`, 48 kHz PCM_16), submits a deliberately corrupt `.wav` and an unsupported
`.txt`, runs the full analysis, polls to completion, renders the plots, compares and aligns the
two files, re-classifies the QC thresholds, requests all five report formats and finally deletes
the session.

**Result: `RESULT: PASS - all 59 checks succeeded`, exit code 0.**

A second, independent HTTP harness was run against the same server using a second pair of
synthesised tones (22 050 Hz, PCM_U8, mono) and added numeric-accuracy assertions on top of the
route coverage. **Result: 68 of 68 checks passed**, including a dominant-frequency reading of
**439.95 Hz** for a generated 440 Hz tone (error 0.05 Hz) and a sample peak of **−0.56 dBFS**
against the generated −0.55 dBFS (error 0.01 dB).

| Area | Checks | Result |
| --- | --- | --- |
| Health and settings | `GET /api/health` returns `status: ok`, `original_files_preserved: true` and the WAV format list | pass |
| | `GET /api/settings` exposes the QC thresholds, the threshold schema and the effective limits | pass |
| Static dashboard | `GET /` returns the built HTML and references the hashed `/assets/` bundle | pass |
| Session | `POST /api/sessions` returns a `ses_<32 hex>` identifier | pass |
| Upload | Two files accepted in one multipart request, no errors, native sample rate and PCM bit depth reported, original file name preserved, `fil_<32 hex>` identifier | pass |
| | A corrupt file is rejected with an actionable error | pass |
| | An unsupported `.txt` extension is rejected | pass |
| Analysis | `POST /api/sessions/{id}/analyze` queues one job per file | pass |
| | Both files reach `has_analysis: true` after polling | pass |
| Artifact | SHA-256 present (64 hex), integrated LUFS and true peak present, QC verdict valid, `methods` block populated | pass |
| | Every QC check carries an explanation and a recommendation | pass |
| | Waveform buckets present, all 7 spectral bands present | pass |
| | **Mono file reports `stereo.mono = true` with no `correlation` and no `mid_side` key** | pass |
| | Dominant frequency **439.95 Hz** for a generated 440 Hz tone (error 0.05 Hz) | pass |
| | Sample peak **−0.56 dBFS** against the generated −0.55 dBFS (error 0.01 dB) | pass |
| Overview | `GET /api/sessions/{id}/overview` counts 2 files and 2 analysed | pass |
| Data endpoints | `GET .../waveform`, `.../spectrum`, `.../spectrogram` all 200 | pass |
| Plot rendering | 5 PNG kinds return HTTP 200 with the `\x89PNG` signature and an `image/png` content type | pass |
| Comparison | `POST .../compare` returns rows, a gain preview, and `status: "unsupported"` for the stereo correlation of a mono file | pass |
| Alignment | `POST .../align` returns a numeric offset, a confidence in [0, 1], a valid confidence label and `does_not_modify_audio: true` | pass |
| QC re-classification | `POST .../qc/recompute` updates both analysed files, echoes the new thresholds, and the stored artifact's true-peak check is reclassified to `error` | pass |
| Reports | PDF (`%PDF`), JSON (`{`), CSV (`file_id`), QC CSV (`severity`) and comparison CSV (`parameter`) are all served | pass |
| Cleanup | `DELETE /api/sessions/{id}` succeeds and the session then returns 404 | pass |

The accuracy of the automatic alignment is validated separately by the test suite (§6), where a
0.75 s synthetic delay is recovered exactly.

The same routes are covered by the automated suite in `backend/tests/test_api.py`; the live run
above additionally exercises the real HTTP server, the static file handler and the multipart
upload path.

The script deletes its own session on completion, so the runtime data directory is left empty.
It exits with code 0 only when every check passes, and with code 1 listing the failures otherwise.

---

## 8. Frontend build

```
> frontend@0.1.0 build
> tsc -b && vite build

vite v8.0.0 building for production...
✓ 2172 modules transformed.
dist/index.html                   0.59 kB │ gzip:   0.36 kB
dist/assets/index-ChgAGnzn.css   45.26 kB │ gzip:   9.56 kB
dist/assets/index-CQ2ON-XZ.js  5,045.62 kB │ gzip: 1,533.98 kB
✓ built in 2.54s
```

No TypeScript errors. The bundle size is dominated by the full Plotly.js distribution; see
*Known limitations* in [TECHNICAL.md](TECHNICAL.md). The build duration varies with machine load;
the asset sizes and the module count are reproducible.

---

## 9. Requirement traceability

| Requirement | How it is satisfied | Where it is validated |
| --- | --- | --- |
| Accept 2+ files per session | Multipart upload, up to 12 files per session | `test_api.py`, §7 |
| WAV, MP3, FLAC, AAC, OGG, AIFF | Container sniffing + libsndfile/PyAV decoding | `test_api.py::test_unsupported_extension_is_rejected`, §5 table |
| Detect damaged / incomplete files | Per-container structural checks (RIFF size, FLAC sample count, ADTS frame walk, MP4 box walk, OGG EOS flag) | `test_api.py::test_upload_validates_and_rejects_bad_files` |
| Never modify the originals | Uploads are stored once and opened read-only; SHA-256 recorded; gain/alignment are previews only | `alignment.py` returns `does_not_modify_audio: true`; `gain_preview` returns `applied: false` |
| SNR / noise floor | 10th-percentile estimator with a mandatory 6 dB separation test | `test_time_domain.py` (2 tests), §5 `tone_with_noise_floor.wav` |
| Peak / true peak / RMS / DC / clipping / silence / dropouts | §4 of [TECHNICAL.md](TECHNICAL.md) | `test_time_domain.py` (8 tests) |
| Dynamics, crest, PLR, LRA | §8 of [TECHNICAL.md](TECHNICAL.md) | `test_loudness.py`, §5 |
| Key / chroma | Krumhansl-Schmuckler on the mean chroma | `test_musical.py::test_key_is_estimated_for_a_major_triad` |
| Tempo / beats / onsets | librosa beat tracking + tempogram | `test_musical.py` (2 tests) |
| Pitch / F0 | librosa pyin | `test_musical.py::test_pitch_is_estimated_for_a_steady_tone` |
| FFT spectrum and spectral features | §5 of [TECHNICAL.md](TECHNICAL.md) | `test_spectral.py` (7 tests) |
| HPSS and 7 bands | §5.5 / §5.6 of [TECHNICAL.md](TECHNICAL.md) | `test_spectral.py::test_band_energy_follows_the_signal` |
| ITU-R BS.1770 / EBU R128 | Custom implementation | **§4 — 17/17 files within 0.0061 LU of pyloudnorm** |
| Non-destructive gain preview | Arithmetic only, `applied: false` | `test_loudness.py` (3 tests) |
| Sample rate / bit depth / bitrate | §2.2 of [TECHNICAL.md](TECHNICAL.md) | §5.2 metadata table |
| Stereo correlation / width / mid-side / mono compatibility / vectorscope | §7 of [TECHNICAL.md](TECHNICAL.md) | `test_stereo.py` (5 tests) |
| Mono handled separately | `supported: false`, no stereo keys emitted | `test_stereo.py::test_mono_input_is_reported_as_mono_without_stereo_values` |
| Time-domain waveform | Bucket min/max/RMS envelopes | `test_time_domain.py::test_waveform_buckets_are_bounded` |
| Four QC levels with configurable thresholds | §9 of [TECHNICAL.md](TECHNICAL.md) | `test_qc.py` (7 tests) |
| Time positions, explanations, recommendations | Every QC check carries them | `test_qc.py::test_every_check_contains_explanation_and_recommendation` |
| Individual + combined reports, 5 formats, PNG per plot | §13 of [TECHNICAL.md](TECHNICAL.md) | `test_reporting.py` (5 tests), `test_api.py` (2 tests) |
| Manual + auto alignment with confidence | §11 of [TECHNICAL.md](TECHNICAL.md) | `test_comparison_alignment.py` (2 tests), §6 |
| No dummy data; estimates labelled | Every estimate has a `confidence` field and a `method` string | `test_musical.py::test_musical_result_declares_estimates_and_limitations` |

---

## 10. Residual risks

| Risk | Assessment | Mitigation |
| --- | --- | --- |
| Multichannel loudness weights are approximate for > 2 channels and > 5 channels | Low impact — the target use case is mono/stereo | The payload carries `channel_weighting_note` stating the approximation |
| HNR is a harmonic/percussive energy ratio, not an autocorrelation HNR | Could be misread | `hnr_method` states the definition explicitly in the payload and the UI |
| Key/tempo/pitch are statistical estimates | Inherent to the technique | Every estimate carries a confidence value and a low-confidence QC notice |
| Noise-floor percentile is biased by quiet passages | Accepted limitation, documented | The 6 dB separation test prevents confidently wrong values |
| Period-local analysis is process-bound | Blocks naive horizontal scaling | Documented in [DEPLOYMENT.md](DEPLOYMENT.md) with sticky-routing and shared-storage options |
| Full Plotly bundle (~1.5 MB gzipped) | Performance, not correctness | Partial imports identified as a future optimisation |

---

## 11. Statement

The platform was validated against analytic references, against an independent implementation of
the same loudness standard, against synthetic signals with known ground truth, and through a
62-test automated suite covering the analysis engine, the API and the report builders. All
documented measurements are computed from the uploaded audio; the platform reports `null` with an
explicit reason wherever a value cannot be measured reliably.
