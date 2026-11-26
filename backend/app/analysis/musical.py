"""Musical analysis: key, tempo, beats, onsets, rhythm and pitch."""

from __future__ import annotations

import math
from typing import Any

import librosa
import numpy as np
from scipy import signal

from .utils import db, downsample_envelope, merge_regions, round_sig

PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
KRUMHANSL_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KRUMHANSL_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    if a.size != b.size or a.size < 2:
        return 0.0
    a = a - np.mean(a)
    b = b - np.mean(b)
    denom = float(np.sqrt(np.sum(a * a) * np.sum(b * b)))
    if denom <= 1e-12:
        return 0.0
    return float(np.sum(a * b) / denom)


def detect_key(chroma_mean: np.ndarray) -> dict[str, Any]:
    chroma = np.asarray(chroma_mean, dtype=np.float64)
    if chroma.size != 12 or float(np.sum(np.abs(chroma))) <= 1e-12:
        return {
            "supported": False,
            "reason": "Chroma energy is insufficient for key estimation",
            "key": None,
            "mode": None,
            "confidence": 0.0,
            "confidence_label": "unsupported",
            "alternatives": [],
        }
    chroma = chroma / float(np.sum(chroma))
    if float(np.std(chroma)) < 1e-6:
        # A perfectly flat profile correlates equally with every key: any
        # "best" key would be an arbitrary tie-break, not an estimate.
        return {
            "supported": False,
            "reason": "The chroma profile is flat (no tonal centre), so no key is reported",
            "key": None,
            "mode": None,
            "confidence": 0.0,
            "confidence_label": "unsupported",
            "alternatives": [],
        }
    candidates = []
    for tonic in range(12):
        for mode, profile in (("major", KRUMHANSL_MAJOR), ("minor", KRUMHANSL_MINOR)):
            rotated = np.roll(profile, tonic)
            candidates.append({
                "tonic": tonic,
                "mode": mode,
                "correlation": _corr(chroma, rotated),
                "key": f"{PITCH_CLASSES[tonic]} {mode}",
            })
    candidates.sort(key=lambda item: item["correlation"], reverse=True)
    scores = np.array([c["correlation"] for c in candidates], dtype=np.float64)
    temperature = 0.08
    exp = np.exp((scores - np.max(scores)) / temperature)
    probs = exp / np.sum(exp)
    best = candidates[0]
    confidence = float(probs[0] * max(0.0, (best["correlation"] + 1.0) / 2.0))
    confidence = max(0.0, min(1.0, confidence))
    if confidence >= 0.65:
        label = "high"
    elif confidence >= 0.4:
        label = "medium"
    else:
        label = "low"
    alternatives = [
        {
            "key": c["key"],
            "mode": c["mode"],
            "correlation": round_sig(c["correlation"], 4),
            "probability": round_sig(float(probs[i]), 4),
        }
        for i, c in enumerate(candidates[1:5])
    ]
    top_notes = [
        {"pitch_class": PITCH_CLASSES[i], "energy": round_sig(float(chroma[i]), 4)}
        for i in np.argsort(chroma)[::-1][:5]
    ]
    return {
        "supported": True,
        "key": best["key"],
        "tonic": PITCH_CLASSES[best["tonic"]],
        "mode": best["mode"],
        "confidence": round_sig(confidence, 3),
        "confidence_label": label,
        "correlation": round_sig(best["correlation"], 4),
        "alternatives": alternatives,
        "harmonic_content": {
            "top_pitch_classes": top_notes,
            "chroma_mean": [round_sig(float(v), 4) for v in chroma.tolist()],
        },
        "method": "Krumhansl-Schmuckler key-profile correlation against the full-file mean chroma; confidence combines profile fit and separation from alternatives.",
        "note": "Key estimation is statistical. Modal music, atonal material, heavy percussion and strongly detuned tracks can produce low-confidence results.",
    }


def _tempo_candidates(tempogram: np.ndarray, sr: int, hop: int, global_tempo: float) -> list[dict[str, Any]]:
    if tempogram.size == 0:
        return []
    aggregate = np.sum(tempogram, axis=1)
    if not np.any(aggregate > 0):
        return []
    lags = np.arange(aggregate.size)
    with np.errstate(divide="ignore"):
        bpms = 60.0 * sr / (hop * lags)
    valid = (lags >= 1) & (bpms >= 30.0) & (bpms <= 300.0)
    if not np.any(valid):
        return []
    indices, props = signal.find_peaks(aggregate, distance=2)
    candidates = []
    maximum = float(np.max(aggregate)) or 1.0
    for i in indices:
        if not valid[i]:
            continue
        candidates.append({
            "bpm": round_sig(float(bpms[i]), 2),
            "strength": round_sig(float(aggregate[i] / maximum), 4),
            "interpretation": (
                "half-time" if global_tempo > 0 and abs(bpms[i] - global_tempo / 2.0) / max(global_tempo / 2.0, 1e-9) < 0.04
                else "double-time" if global_tempo > 0 and abs(bpms[i] - global_tempo * 2.0) / max(global_tempo * 2.0, 1e-9) < 0.04
                else "primary" if global_tempo > 0 and abs(bpms[i] - global_tempo) / max(global_tempo, 1e-9) < 0.04
                else "alternate"
            ),
        })
    candidates.sort(key=lambda c: c["strength"], reverse=True)
    # Keep at most one candidate per 1 BPM region.
    filtered = []
    for c in candidates:
        if all(abs(c["bpm"] - f["bpm"]) > 1.0 for f in filtered):
            filtered.append(c)
    return filtered[:6]


def _local_tempo(tempogram: np.ndarray, sr: int, hop: int, duration: float) -> list[dict[str, Any]]:
    if tempogram.size == 0:
        return []
    n_frames = tempogram.shape[1]
    win = max(8, int(round(8.0 * sr / hop)))
    step = max(1, int(round(4.0 * sr / hop)))
    lags = np.arange(tempogram.shape[0])
    with np.errstate(divide="ignore"):
        bpms = 60.0 * sr / (hop * lags)
    result = []
    for center in range(0, n_frames, step):
        a = max(0, center - win // 2)
        b = min(n_frames, center + win // 2)
        if b - a < max(2, win // 4):
            continue
        column = np.sum(tempogram[:, a:b], axis=1)
        valid = (lags >= 1) & (bpms >= 40.0) & (bpms <= 240.0)
        if not np.any(valid):
            continue
        peak = int(np.argmax(np.where(valid, column, -np.inf)))
        maximum = float(np.max(column)) or 1.0
        strength = float(column[peak] / maximum)
        if strength < 0.15:
            continue
        result.append({
            "time": round_sig(min(duration, center * hop / sr), 3),
            "bpm": round_sig(float(bpms[peak]), 2),
            "strength": round_sig(strength, 4),
        })
    return result


def _polyphony_estimate(segment: np.ndarray, sr: int, max_frames: int = 160) -> dict[str, Any]:
    """Estimate whether energetic frames contain one harmonic series or several
    simultaneous pitches.

    For each analysed frame the strong spectral peaks (within 25 dB of the
    frame maximum, 60 Hz-5 kHz, prominence >= 10 dB) are tested against a
    single harmonic series whose fundamental is the lowest peak or half of it
    (allowing one missing fundamental).  A frame is polyphonic when a peak does
    not fit within 3 % of an integer harmonic.  This is evaluated per frame so
    a melody (one note at a time) is not mistaken for a chord.
    """
    n_fft = 8192 if sr >= 32000 else 4096
    if segment.size < n_fft:
        return {"evaluated_frames": 0, "polyphonic_fraction": None}
    spec = np.abs(librosa.stft(segment.astype(np.float32), n_fft=n_fft, hop_length=n_fft // 2, center=False))
    if spec.size == 0:
        return {"evaluated_frames": 0, "polyphonic_fraction": None}
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    band = (freqs >= 60.0) & (freqs <= 5000.0)
    energy = np.sum(spec[band] ** 2, axis=0)
    if not np.any(energy > 0):
        return {"evaluated_frames": 0, "polyphonic_fraction": None}
    loud = np.flatnonzero(energy >= float(np.max(energy)) * 10 ** (-40 / 10))
    if loud.size > max_frames:
        loud = loud[np.linspace(0, loud.size - 1, max_frames).astype(int)]
    band_idx = np.flatnonzero(band)
    evaluated = 0
    polyphonic = 0
    for column in loud:
        mag_db = 20.0 * np.log10(np.maximum(spec[band_idx, column], 1e-12))
        top = float(np.max(mag_db))
        idx, _props = signal.find_peaks(mag_db, prominence=10.0, height=top - 25.0)
        if idx.size == 0:
            continue
        idx = idx[np.argsort(mag_db[idx])[::-1][:8]]
        peak_freqs = np.sort(freqs[band_idx[idx]])
        evaluated += 1
        if peak_freqs.size < 2:
            continue
        fits = False
        for divisor in (1, 2):
            f0 = peak_freqs[0] / divisor
            ratios = peak_freqs / f0
            if np.all(np.abs(ratios - np.round(ratios)) <= 0.03 * np.round(ratios)):
                fits = True
                break
        if not fits:
            polyphonic += 1
    fraction = polyphonic / evaluated if evaluated else None
    return {"evaluated_frames": int(evaluated), "polyphonic_fraction": round_sig(fraction, 3) if fraction is not None else None}


def _pitch_analysis(mono: np.ndarray, sr: int, duration: float, max_seconds: float = 30.0) -> dict[str, Any]:
    if duration < 0.5:
        return {"supported": False, "reason": "Audio is too short for pitch tracking"}
    window = min(float(max_seconds), duration)
    if window < duration:
        # Pick the most energetic window (1 s RMS).
        hop = max(1, int(round(1.0 * sr)))
        n = mono.size
        energies = []
        starts = list(range(0, max(1, n - hop + 1), hop))
        for start in starts:
            seg = mono[start:start + hop]
            energies.append(float(np.mean(seg.astype(np.float64) ** 2)))
        best = int(np.argmax(energies)) if energies else 0
        center = (starts[best] + hop / 2.0) / sr
        start_s = max(0.0, min(duration - window, center - window / 2.0))
    else:
        start_s = 0.0
    a = int(round(start_s * sr))
    b = min(mono.size, int(round((start_s + window) * sr)))
    segment = np.asarray(mono[a:b], dtype=np.float32)
    if segment.size < int(0.2 * sr):
        return {"supported": False, "reason": "Selected pitch segment is too short"}
    try:
        f0, voiced_flag, voiced_prob = librosa.pyin(
            segment,
            fmin=librosa.note_to_hz("C2"),
            fmax=librosa.note_to_hz("C7"),
            sr=sr,
            frame_length=2048,
            hop_length=512,
            fill_na=np.nan,
            center=True,
        )
    except Exception as exc:
        return {"supported": False, "reason": f"Pitch tracking failed: {exc}"}
    hop = 512
    times = start_s + np.arange(f0.size) * hop / sr
    valid = np.isfinite(f0) & (f0 > 0) & voiced_flag.astype(bool)
    voiced_fraction = float(np.mean(valid)) if valid.size else 0.0
    if not np.any(valid):
        return {
            "supported": False,
            "reason": "No stable pitched content was found in the analysed segment",
            "analyzed_start": round_sig(start_s, 3),
            "analyzed_end": round_sig(start_s + window, 3),
            "voiced_fraction": 0.0,
            "method": "librosa.pyin (probabilistic YIN) on the most energetic segment",
        }
    f0_valid = f0[valid].astype(np.float64)
    midi = librosa.hz_to_midi(f0_valid)
    p5, p50, p95 = np.percentile(f0_valid, [5, 50, 95])
    semitone_range = 12.0 * math.log2(max(p95, 1e-9) / max(p5, 1e-9))
    stability = float(np.std(midi))
    # Dominant notes by voiced-frame duration.
    note_hist: dict[int, int] = {}
    for note in np.round(midi).astype(int):
        note_hist[int(note)] = note_hist.get(int(note), 0) + 1
    dominant_notes = sorted(note_hist.items(), key=lambda item: item[1], reverse=True)[:6]
    note_names = [
        {"note": librosa.midi_to_note(note), "midi": int(note), "frames": int(count),
         "percent": round_sig(count / max(1, len(midi)) * 100.0, 2)}
        for note, count in dominant_notes
    ]
    # Note transitions: count stable note changes.
    rounded = np.round(midi).astype(int)
    transitions = 0
    run_length = 1
    previous = rounded[0]
    for note in rounded[1:]:
        if note == previous:
            run_length += 1
        else:
            if run_length >= 3:
                transitions += 1
            previous = note
            run_length = 1
    if run_length >= 3:
        transitions += 1
    transitions = max(0, transitions - 1)
    # Downsampled contour for plotting.
    max_points = 800
    idx = np.linspace(0, f0.size - 1, min(max_points, f0.size)).astype(int) if f0.size else np.array([], dtype=int)
    contour_times = times[idx]
    contour_f0 = [round_sig(float(f0[i]), 2) if valid[i] else None for i in idx]
    contour_conf = [round_sig(float(voiced_prob[i]), 3) for i in idx]
    contour_voiced = [bool(valid[i]) for i in idx]
    # Pitch histogram in semitones (MIDI 24..96).
    hist, edges = np.histogram(midi, bins=72, range=(24, 96))
    centers = (edges[:-1] + edges[1:]) / 2.0
    mean_conf = float(np.mean(voiced_prob[valid])) if np.any(valid) else 0.0
    confidence = max(0.0, min(1.0, mean_conf * (0.5 + 0.5 * voiced_fraction)))
    if confidence >= 0.65 and voiced_fraction >= 0.5:
        label = "high"
    elif confidence >= 0.35:
        label = "medium"
    else:
        label = "low"
    # Reliability checks: several simultaneous pitches cannot be represented by
    # one F0, and a median F0 pinned to the tracker's lower bound is a classic
    # sub-harmonic (missing-fundamental) error.
    fmin_hz = float(librosa.note_to_hz("C2"))
    polyphony = _polyphony_estimate(segment, sr)
    poly_fraction = polyphony.get("polyphonic_fraction")
    is_polyphonic = poly_fraction is not None and poly_fraction >= 0.5
    at_lower_bound = bool(p50 <= fmin_hz * 1.03)
    reliability_notes = []
    if is_polyphonic:
        reliability_notes.append(
            f"{poly_fraction * 100:.0f}% of analysed frames contain spectral peaks that do not belong to one harmonic series; "
            "the input appears polyphonic, so a single F0 does not describe it."
        )
    if at_lower_bound:
        reliability_notes.append(
            f"The median F0 ({p50:.1f} Hz) sits at the tracker's lower bound ({fmin_hz:.1f} Hz), which usually indicates a sub-harmonic error."
        )
    reliable = not reliability_notes
    if not reliable:
        label = "low"
        confidence = min(confidence, 0.3)
    return {
        "supported": True,
        "reliable_single_pitch": reliable,
        "polyphonic": bool(is_polyphonic),
        "polyphony": polyphony,
        "at_tracker_lower_bound": at_lower_bound,
        "reliability_notes": reliability_notes,
        "analyzed_start": round_sig(start_s, 3),
        "analyzed_end": round_sig(start_s + window, 3),
        "analyzed_duration": round_sig(window, 3),
        "is_segment": window < duration - 0.05,
        "f0_median_hz": round_sig(p50, 2),
        "f0_p5_hz": round_sig(p5, 2),
        "f0_p95_hz": round_sig(p95, 2),
        "f0_min_hz": round_sig(float(np.min(f0_valid)), 2),
        "f0_max_hz": round_sig(float(np.max(f0_valid)), 2),
        "pitch_range_semitones": round_sig(semitone_range, 2),
        "pitch_stability_semitones_std": round_sig(stability, 3),
        "pitch_stability_label": "stable" if stability < 0.5 else "moderate" if stability < 1.5 else "variable",
        "voiced_fraction": round_sig(voiced_fraction, 3),
        "confidence": round_sig(confidence, 3),
        "confidence_label": label,
        "note_transitions": int(transitions),
        "dominant_notes": note_names,
        "pitch_distribution": {
            "midi_centers": [round_sig(float(v), 2) for v in centers.tolist()],
            "counts": [int(v) for v in hist.tolist()],
            "normalized": [round_sig(float(v) / max(1, int(np.sum(hist))), 4) for v in hist.tolist()],
        },
        "contour": {
            "times": [round_sig(v, 3) for v in contour_times.tolist()],
            "f0_hz": contour_f0,
            "confidence": contour_conf,
            "voiced": contour_voiced,
        },
        "method": "librosa.pyin (probabilistic YIN), fmin C2 (65.4 Hz), fmax C7 (2093 Hz), 2048-sample frames, 512-sample hop",
        "limitations": "F0 tracking assumes a predominant monophonic pitch. On dense polyphonic mixes, octave errors and dropouts are expected; use the contour as indicative evidence and check the confidence values.",
    }


def analyze_musical(
    mono: np.ndarray,
    sr: int,
    duration: float,
    chroma_mean: np.ndarray | None = None,
    pitch_seconds: float = 30.0,
) -> dict[str, Any]:
    mono = np.asarray(mono, dtype=np.float32).reshape(-1)
    if mono.size == 0:
        raise ValueError("No audio samples for musical analysis")
    key = detect_key(chroma_mean) if chroma_mean is not None else {"supported": False, "reason": "No chroma data"}

    hop = 512
    try:
        onset_env = librosa.onset.onset_strength(
            y=mono, sr=sr, hop_length=hop, n_fft=2048, aggregate=np.median
        ).astype(np.float32)
    except Exception:
        onset_env = np.zeros(1, dtype=np.float32)
    onset_env = np.nan_to_num(onset_env)
    if onset_env.size and float(np.max(onset_env)) > 0:
        onset_env = onset_env / float(np.max(onset_env))
    onset_times_full = np.arange(onset_env.size) * hop / sr

    def track(start_bpm: float | None = None) -> tuple[float, np.ndarray]:
        kwargs = {"start_bpm": start_bpm} if start_bpm else {}
        try:
            tempo_value, frames = librosa.beat.beat_track(
                onset_envelope=onset_env, sr=sr, hop_length=hop, trim=False, units="frames", **kwargs
            )
            return float(np.atleast_1d(tempo_value)[0]), np.asarray(frames, dtype=int)
        except Exception:
            return 0.0, np.array([], dtype=int)

    tempo, beat_frames = track()
    onset_frames = librosa.onset.onset_detect(
        onset_envelope=onset_env, sr=sr, hop_length=hop, units="frames", backtrack=False
    )
    onset_times_detected = np.asarray(onset_frames, dtype=int) * hop / sr

    # Periodicity evidence: normalised autocorrelation of the onset envelope at
    # the beat lag.  The beat tracker always returns a regular grid, even for
    # noise, so grid regularity alone says nothing about whether a tempo
    # exists.  Measured on references: clicks/music >= 0.75, white noise 0.07.
    centred = onset_env.astype(np.float64) - float(np.mean(onset_env))
    autocorr = signal.fftconvolve(centred, centred[::-1], mode="full")[centred.size - 1:]
    if autocorr.size and autocorr[0] > 0:
        autocorr = autocorr / autocorr[0]

    def periodicity(bpm: float) -> float:
        if bpm <= 0 or autocorr.size < 4:
            return 0.0
        lag = 60.0 * sr / (hop * bpm)
        centre = int(round(lag))
        if centre < 1 or centre + 3 >= autocorr.size:
            return 0.0
        return float(np.max(autocorr[max(1, centre - 2):centre + 3]))

    def half_beat_fraction(times: np.ndarray) -> float:
        if times.size < 3 or onset_times_detected.size == 0:
            return 0.0
        inside = onset_times_detected[(onset_times_detected > times[0]) & (onset_times_detected < times[-1])]
        if inside.size == 0:
            return 0.0
        index = np.clip(np.searchsorted(times, inside), 1, times.size - 1)
        frac = (inside - times[index - 1]) / np.maximum(times[index] - times[index - 1], 1e-9)
        return float(np.mean(np.abs(frac - 0.5) < 0.12))

    # Half-time lock check: if the onset envelope is strongly periodic at half
    # the beat lag and many onsets fall exactly between beats, the tracker has
    # locked to every other beat.  Re-track around the doubled tempo.
    beat_times_initial = beat_frames * hop / sr
    periodicity_beat = periodicity(tempo)
    periodicity_half = periodicity(tempo * 2.0) if tempo > 0 else 0.0
    half_fraction = half_beat_fraction(beat_times_initial)
    tempo_corrected_from = None
    if tempo > 0 and tempo * 2.0 <= 240.0 and periodicity_half >= 0.6 and half_fraction >= 0.4:
        doubled, doubled_frames = track(start_bpm=tempo * 2.0)
        if doubled > 0 and abs(doubled - 2.0 * tempo) / (2.0 * tempo) < 0.05:
            tempo_corrected_from = tempo
            tempo, beat_frames = doubled, doubled_frames
        else:
            # Fall back to inserting the mid-beat positions into the grid.
            mids = (beat_frames[:-1] + beat_frames[1:]) // 2
            tempo_corrected_from = tempo
            tempo, beat_frames = tempo * 2.0, np.sort(np.concatenate([beat_frames, mids]))
        periodicity_beat = periodicity(tempo)
        periodicity_half = periodicity(tempo * 2.0)
    double_time_ambiguous = bool(tempo > 0 and periodicity_half >= 0.5 and tempo_corrected_from is None)

    beat_times = beat_frames * hop / sr
    beat_times = beat_times[(beat_times >= 0) & (beat_times <= duration)]

    beat_intervals = np.diff(beat_times) if beat_times.size > 1 else np.array([])
    if beat_intervals.size:
        interval_mean = float(np.mean(beat_intervals))
        interval_median = float(np.median(beat_intervals))
        interval_std = float(np.std(beat_intervals))
        cv = interval_std / interval_median if interval_median > 0 else 1.0
        consistency = float(np.mean(np.abs(beat_intervals - interval_median) <= 0.1 * interval_median))
        stability_score = max(0.0, min(1.0, 1.0 - cv))
    else:
        interval_mean = interval_median = interval_std = 0.0
        cv = 1.0
        consistency = 0.0
        stability_score = 0.0
    # librosa's global tempo is quantised to integer onset-frame lags (about
    # 1.7 % steps near 175 BPM at hop 512).  For a stable beat grid the mean
    # beat interval is a finer estimate of the same tempo.
    tempo_grid = tempo
    if beat_intervals.size >= 7 and cv <= 0.08 and interval_mean > 0:
        refined = 60.0 / interval_mean
        if abs(refined - tempo) / max(tempo, 1e-9) < 0.04:
            tempo = refined
    if tempo <= 0 or periodicity_beat < 0.3:
        tempo_conf = "low"
    elif beat_times.size >= 8 and cv <= 0.03 and periodicity_beat >= 0.6 and not double_time_ambiguous:
        tempo_conf = "high"
    elif beat_times.size >= 4 and cv <= 0.08:
        tempo_conf = "medium"
    else:
        tempo_conf = "low"
    tempo_confidence_value = max(0.0, min(1.0, max(0.0, periodicity_beat) * (0.6 + 0.4 * stability_score)))
    if double_time_ambiguous:
        tempo_confidence_value = min(tempo_confidence_value, 0.6)
    if tempo_conf == "low":
        tempo_confidence_value = min(tempo_confidence_value, 0.35)
    tempo_notes = []
    if tempo > 0 and periodicity_beat < 0.3:
        tempo_notes.append("The onset envelope shows no clear periodicity at the estimated tempo; the beat grid may be arbitrary.")
    if double_time_ambiguous:
        tempo_notes.append(f"Strong periodicity also exists at {tempo * 2.0:.1f} BPM; the double-time interpretation is plausible.")
    if tempo_corrected_from is not None:
        tempo_notes.append(f"The beat tracker locked to half-time ({tempo_corrected_from:.1f} BPM); onsets between beats indicate {tempo:.1f} BPM.")

    onset_frames = np.asarray(onset_frames, dtype=int)
    onset_times = onset_frames * hop / sr
    onset_strengths = onset_env[onset_frames] if onset_frames.size else np.array([])
    onset_intervals = np.diff(onset_times) if onset_times.size > 1 else np.array([])
    onset_density = float(onset_times.size / duration) if duration > 0 else 0.0
    if onset_intervals.size > 1:
        onset_cv = float(np.std(onset_intervals) / max(np.mean(onset_intervals), 1e-9))
    else:
        onset_cv = 0.0
    off_grid_fraction = 0.0
    if beat_times.size >= 2 and onset_times.size:
        grid = beat_times
        if grid.size >= 2:
            # Position of each onset in beat units relative to the nearest beat.
            indices = np.searchsorted(grid, onset_times)
            indices = np.clip(indices, 1, grid.size - 1)
            left = grid[indices - 1]
            right = grid[indices]
            beat_len = np.maximum(right - left, 1e-9)
            frac = (onset_times - left) / beat_len
            off_grid_fraction = float(np.mean(np.minimum(np.abs(frac), np.abs(1 - frac)) > 0.25))

    # Tempogram for candidate interpretation and local tempo.
    try:
        tempogram = librosa.feature.tempogram(
            onset_envelope=onset_env, sr=sr, hop_length=hop, win_length=384
        )
    except Exception:
        tempogram = np.zeros((1, 1))
    candidates = _tempo_candidates(tempogram, sr, hop, tempo)
    local_tempo = _local_tempo(tempogram, sr, hop, duration)
    tempo_changes = []
    if local_tempo and tempo > 0:
        flagged = []
        for point in local_tempo:
            deviation = abs(point["bpm"] - tempo) / tempo
            if deviation > 0.05 and point["strength"] >= 0.25:
                flagged.append(point)
        if flagged:
            regions = merge_regions(
                [(max(0.0, p["time"] - 2.0), min(duration, p["time"] + 2.0)) for p in flagged],
                gap=1.0,
            )
            tempo_changes = []
            for region in regions:
                in_region = [
                    p["bpm"] for p in flagged
                    if region["start"] - 1e-6 <= p["time"] <= region["end"] + 1e-6
                ]
                if not in_region:
                    continue
                tempo_changes.append({
                    "start": region["start"],
                    "end": region["end"],
                    "bpm_min": round_sig(min(in_region), 2),
                    "bpm_max": round_sig(max(in_region), 2),
                    "note": "Local tempogram peak differs from the global tempo by more than 5%.",
                })
    if not candidates and tempo > 0:
        candidates = [
            {"bpm": round_sig(tempo, 2), "strength": 1.0, "interpretation": "primary"},
            {"bpm": round_sig(tempo / 2.0, 2), "strength": 0.5, "interpretation": "half-time"},
            {"bpm": round_sig(tempo * 2.0, 2), "strength": 0.5, "interpretation": "double-time"},
        ]
    pitch = _pitch_analysis(mono, sr, duration, max_seconds=pitch_seconds)

    onset_plot_idx = np.linspace(0, onset_env.size - 1, min(800, onset_env.size)).astype(int) if onset_env.size else np.array([], dtype=int)
    return {
        "key": key,
        "tempo": {
            "bpm": round_sig(tempo, 2) if tempo > 0 else None,
            "bpm_rounded": int(round(tempo)) if tempo > 0 else None,
            "confidence": round_sig(tempo_confidence_value, 3),
            "confidence_label": tempo_conf,
            "beat_count": int(beat_times.size),
            "beats": [round_sig(v, 3) for v in beat_times.tolist()],
            "beat_intervals_seconds": [round_sig(v, 4) for v in beat_intervals.tolist()],
            "beat_interval_mean_seconds": round_sig(interval_mean, 4),
            "beat_interval_median_seconds": round_sig(interval_median, 4),
            "beat_interval_std_seconds": round_sig(interval_std, 4),
            "beat_interval_cv": round_sig(cv, 4),
            "tempo_stability": round_sig(stability_score, 3),
            "beat_consistency": round_sig(consistency, 3),
            "stability_label": "stable" if cv <= 0.03 else "moderate" if cv <= 0.08 else "variable",
            "candidates": candidates,
            "half_time_bpm": round_sig(tempo / 2.0, 2) if tempo > 0 else None,
            "double_time_bpm": round_sig(tempo * 2.0, 2) if tempo > 0 else None,
            "local_tempo": [
                {"time": p["time"], "bpm": p["bpm"], "strength": p["strength"]} for p in local_tempo
            ],
            "tempo_changes": tempo_changes,
            "tracker_bpm": round_sig(tempo_grid, 2) if tempo_grid > 0 else None,
            "periodicity": round_sig(periodicity_beat, 3),
            "double_time_periodicity": round_sig(periodicity_half, 3),
            "double_time_ambiguous": double_time_ambiguous,
            "half_time_corrected_from_bpm": round_sig(tempo_corrected_from, 2) if tempo_corrected_from else None,
            "notes": tempo_notes,
            "method": "librosa beat tracker on a normalised onset-strength envelope; confidence combines onset-envelope periodicity at the beat lag with beat-interval stability; tempogram provides half/double-time candidates and local tempo.",
        },
        "rhythm": {
            "onset_count": int(onset_times.size),
            "onset_density_per_second": round_sig(onset_density, 3),
            "onsets": [round_sig(v, 3) for v in onset_times.tolist()],
            "onset_strengths": [round_sig(v, 4) for v in onset_strengths.tolist()],
            "onset_intervals_seconds": [round_sig(v, 4) for v in onset_intervals.tolist()],
            "onset_interval_cv": round_sig(onset_cv, 4),
            "off_grid_onset_fraction": round_sig(off_grid_fraction, 3),
            "rhythm_consistency": round_sig(max(0.0, 1.0 - min(1.0, onset_cv)), 3),
            "onset_envelope": {
                "times": [round_sig(v, 3) for v in onset_times_full[onset_plot_idx].tolist()],
                "values": [round_sig(v, 4) for v in onset_env[onset_plot_idx].tolist()],
            },
            "method": "librosa onset detection (spectral flux) and inter-onset interval statistics; beat-grid alignment is measured against detected beats.",
        },
        "pitch": pitch,
        "analysis_settings": {
            "hop_length": hop,
            "onset_fft_size": 2048,
            "pitch_seconds": round_sig(min(pitch_seconds, duration), 3),
        },
        "confidence": {
            "key": key.get("confidence_label", "low"),
            "tempo": tempo_conf,
            "pitch": pitch.get("confidence_label", "low") if pitch.get("supported") else "unsupported",
        },
        "limitations": [
            "Tempo and beat detection are algorithmic estimates and can lock to half-time or double-time, especially with sparse or heavily syncopated material.",
            "Key detection uses chroma profiles and is less reliable for modal, atonal, or strongly detuned music.",
            "Pitch tracking assumes a predominant monophonic pitch; polyphonic mixes require manual verification.",
        ],
    }
