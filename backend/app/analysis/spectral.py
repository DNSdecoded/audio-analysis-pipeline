"""Frequency-domain, spectral-feature and harmonic/percussive analysis."""

from __future__ import annotations

import math
from typing import Any, Callable

import librosa
import numpy as np
from scipy import signal

from .utils import db, downsample_2d, downsample_envelope, merge_regions, round_sig

BANDS = [
    ("sub_bass", "Sub-bass", 20.0, 60.0),
    ("bass", "Bass", 60.0, 250.0),
    ("low_midrange", "Low-midrange", 250.0, 500.0),
    ("midrange", "Midrange", 500.0, 2000.0),
    ("upper_midrange", "Upper-midrange", 2000.0, 4000.0),
    ("presence", "Presence", 4000.0, 6000.0),
    ("brilliance", "Brilliance", 6000.0, 20000.0),
]

PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _group_edges(length: int, groups: int) -> np.ndarray:
    groups = max(1, min(groups, length))
    edges = np.linspace(0, length, groups + 1).astype(int)
    edges = np.unique(edges)
    if edges[0] != 0:
        edges = np.insert(edges, 0, 0)
    if edges[-1] != length:
        edges = np.append(edges, length)
    return edges


def _summarize(values: np.ndarray, times: np.ndarray, max_points: int = 1200) -> dict[str, Any]:
    values = np.asarray(values, dtype=np.float64)
    times = np.asarray(times, dtype=np.float64)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return {"mean": None, "median": None, "p5": None, "p95": None, "min": None, "max": None, "std": None, "series": {"times": [], "values": []}}
    if values.size > max_points:
        edges = _group_edges(values.size, max_points)
        agg = []
        t_agg = []
        for a, b in zip(edges[:-1], edges[1:]):
            agg.append(float(np.nanmean(values[a:b])))
            t_agg.append(float(np.nanmean(times[a:b])))
        values_plot = np.asarray(agg)
        times_plot = np.asarray(t_agg)
    else:
        values_plot = values
        times_plot = times[: values.size]
    return {
        "mean": round_sig(float(np.mean(finite)), 4),
        "median": round_sig(float(np.median(finite)), 4),
        "p5": round_sig(float(np.percentile(finite, 5)), 4),
        "p95": round_sig(float(np.percentile(finite, 95)), 4),
        "min": round_sig(float(np.min(finite)), 4),
        "max": round_sig(float(np.max(finite)), 4),
        "std": round_sig(float(np.std(finite)), 4),
        "series": {
            "times": [round_sig(v, 3) for v in times_plot.tolist()],
            "values": [round_sig(v, 4) for v in values_plot.tolist()],
        },
    }


def _stft_blocks(y: np.ndarray, sr: int, n_fft: int, hop: int, block_frames: int = 256):
    n_fft = int(max(256, min(n_fft, 32768)))
    hop = int(max(32, min(hop, n_fft)))
    window = signal.windows.hann(n_fft, sym=False).astype(np.float64)
    sum_w = float(np.sum(window))
    sum_w2 = float(np.sum(window ** 2))
    pad = n_fft // 2
    padded = np.pad(np.asarray(y, dtype=np.float64), (pad, pad), mode="reflect" if y.size > 1 else "constant")
    frames = np.lib.stride_tricks.sliding_window_view(padded, n_fft)[::hop]
    total_frames = int(frames.shape[0])
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    for start in range(0, total_frames, block_frames):
        end = min(total_frames, start + block_frames)
        raw = frames[start:end]
        spectrum = np.fft.rfft(raw * window, axis=1)
        abs_spec = np.abs(spectrum)
        amplitude = 2.0 * abs_spec / sum_w
        amplitude[:, 0] /= 2.0
        if n_fft % 2 == 0:
            amplitude[:, -1] /= 2.0
        psd = (abs_spec ** 2) / (n_fft * sum_w2)
        psd[:, 1:-1] *= 2.0
        zcr = np.mean(np.abs(np.diff(np.signbit(raw), axis=1)), axis=1)
        yield start, end, amplitude, psd, abs_spec ** 2, zcr, freqs, total_frames


def _peaks(freqs: np.ndarray, avg_amp_db: np.ndarray, avg_psd: np.ndarray, top: int = 16) -> list[dict[str, Any]]:
    try:
        idx, props = signal.find_peaks(
            avg_amp_db, prominence=6.0, distance=max(1, len(freqs) // 2000), height=-100.0
        )
    except Exception:
        return []
    if idx.size == 0:
        return []
    order = np.argsort(avg_amp_db[idx])[::-1][:top]
    prom_by_bin = {int(b): float(p) for b, p in zip(idx, props["prominences"])}
    idx = idx[order]
    peaks = []
    bin_width = float(freqs[1] - freqs[0]) if freqs.size > 1 else 0.0
    for i in idx:
        # Parabolic interpolation of the log-magnitude peak for sub-bin accuracy.
        delta = 0.0
        if 0 < i < len(freqs) - 1:
            y0, y1, y2 = avg_amp_db[i - 1], avg_amp_db[i], avg_amp_db[i + 1]
            denom = y0 - 2.0 * y1 + y2
            if abs(denom) > 1e-9:
                delta = 0.5 * (y0 - y2) / denom
                delta = max(-0.5, min(0.5, delta))
        freq = float(freqs[i]) + delta * bin_width
        # Integrate the main lobe so amplitude is not underestimated by leakage.
        lo = max(0, i - 2)
        hi = min(avg_psd.size, i + 3)
        lobe_power = float(np.sum(avg_psd[lo:hi]))
        peak_amplitude = math.sqrt(max(2.0 * lobe_power, 1e-20))
        peaks.append({
            "frequency_hz": round_sig(freq, 2),
            "amplitude_dbfs": round_sig(20.0 * math.log10(max(peak_amplitude, 1e-10)), 2),
            "bin_amplitude_dbfs": round_sig(float(avg_amp_db[i]), 2),
            "prominence_db": round_sig(prom_by_bin.get(int(i), 0.0), 2),
        })
    strongest = max(peaks, key=lambda p: p["amplitude_dbfs"])
    f0 = strongest["frequency_hz"]
    for peak in peaks:
        if f0 > 20:
            ratio = peak["frequency_hz"] / f0
            nearest = int(round(ratio))
            if nearest >= 1 and abs(peak["frequency_hz"] - nearest * f0) / max(peak["frequency_hz"], 1e-9) < 0.025:
                peak["harmonic_of_dominant"] = nearest
            else:
                peak["harmonic_of_dominant"] = None
        else:
            peak["harmonic_of_dominant"] = None
    return peaks


def _band_analysis(freqs: np.ndarray, avg_psd: np.ndarray, band_psd_frames: dict[str, np.ndarray], times: np.ndarray) -> dict[str, Any]:
    total_power = float(np.sum(avg_psd[(freqs >= 20) & (freqs <= 20000)]))
    bands = []
    for key, label, low, high in BANDS:
        mask = (freqs >= low) & (freqs < high)
        if not np.any(mask):
            bands.append({
                "key": key, "label": label, "low_hz": low, "high_hz": high,
                "average_db": None, "relative_energy_pct": None,
                "variation_db": None, "supported": False,
            })
            continue
        power = float(np.sum(avg_psd[mask]))
        relative = (power / total_power * 100.0) if total_power > 0 else 0.0
        frame_power = band_psd_frames.get(key)
        if frame_power is not None and frame_power.size:
            frame_db = 10.0 * np.log10(np.maximum(frame_power, 1e-20))
            variation = float(np.std(frame_db))
            p5 = float(np.percentile(frame_db, 5))
            p95 = float(np.percentile(frame_db, 95))
        else:
            variation = 0.0
            p5 = p95 = None
        bands.append({
            "key": key,
            "label": label,
            "low_hz": low,
            "high_hz": high,
            "average_db": round_sig(10.0 * math.log10(max(power, 1e-20)), 2),
            "relative_energy_pct": round_sig(relative, 2),
            "variation_db": round_sig(variation, 2),
            "p5_db": round_sig(p5, 2) if p5 is not None else None,
            "p95_db": round_sig(p95, 2) if p95 is not None else None,
            "supported": True,
        })
    return {
        "bands": bands,
        "total_power_20_20k": round_sig(10.0 * math.log10(max(total_power, 1e-20)), 2),
        "definition": "Energy integrated from the Welch-averaged PSD between 20 Hz and 20 kHz; percentages are share of total band energy.",
    }


def _observations(bands: dict[str, Any], peaks: list[dict[str, Any]], centroid_mean: float | None) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    by_key = {b["key"]: b for b in bands["bands"] if b.get("supported")}
    low_share = sum((by_key[k]["relative_energy_pct"] or 0.0) for k in ("sub_bass", "bass") if k in by_key)
    high_share = sum((by_key[k]["relative_energy_pct"] or 0.0) for k in ("presence", "brilliance") if k in by_key)
    if low_share >= 45.0:
        observations.append({
            "type": "low_frequency_dominance",
            "severity": "info",
            "message": f"Low-frequency bands (20-250 Hz) carry {low_share:.1f}% of measured energy.",
            "measurement": {"low_band_share_pct": round_sig(low_share, 2)},
            "recommendation": "Check whether the low-end balance is intentional; compare against a reference track in the same genre.",
        })
    if high_share < 1.0 and centroid_mean is not None and centroid_mean < 1200:
        observations.append({
            "type": "high_frequency_deficit",
            "severity": "info",
            "message": f"Presence/brilliance bands carry only {high_share:.2f}% of energy (spectral centroid {centroid_mean:.0f} Hz).",
            "measurement": {"high_band_share_pct": round_sig(high_share, 2), "centroid_hz": round_sig(centroid_mean, 2)},
            "recommendation": "Audition the track on a full-range system before applying any high-frequency boost.",
        })
    narrow = [p for p in peaks if (p.get("prominence_db") or 0) >= 12.0 and p["frequency_hz"] >= 40]
    if narrow:
        top = sorted(narrow, key=lambda p: p.get("prominence_db") or 0, reverse=True)[:3]
        observations.append({
            "type": "narrow_spectral_peaks",
            "severity": "info",
            "message": "Narrow spectral peaks stand out from their neighbourhood.",
            "measurement": {"peaks": [{"frequency_hz": p["frequency_hz"], "amplitude_dbfs": p["amplitude_dbfs"], "prominence_db": p["prominence_db"]} for p in top]},
            "recommendation": "Inspect these frequencies for resonances, tonal noise, or intended harmonic content.",
        })
    varied = [b for b in bands["bands"] if b.get("variation_db") is not None and b["variation_db"] >= 6.0]
    if varied:
        observations.append({
            "type": "band_energy_variation",
            "severity": "info",
            "message": "Some bands vary substantially over time.",
            "measurement": {"bands": [{"band": b["label"], "variation_db": b["variation_db"]} for b in varied]},
            "recommendation": "Review the arrangement and dynamics in those bands; variation is not inherently a defect.",
        })
    return observations


def analyze_spectral(
    mono: np.ndarray,
    sr: int,
    duration: float,
    n_fft: int = 4096,
    hop_length: int = 1024,
    max_spectrogram_frames: int = 700,
    max_feature_points: int = 1200,
    hpss_seconds: float = 120.0,
    progress: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    mono = np.asarray(mono, dtype=np.float32).reshape(-1)
    if mono.size == 0:
        raise ValueError("No audio samples for spectral analysis")
    n_fft = int(max(256, min(n_fft, 16384)))
    hop_length = int(max(32, min(hop_length, n_fft)))
    max_spectrogram_frames = max(50, int(max_spectrogram_frames))

    # First pass metadata
    pad = n_fft // 2
    total_frames = 1 + (mono.size + 2 * pad - n_fft) // hop_length
    total_frames = max(1, int(total_frames))
    freqs_full = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    freq_edges = _group_edges(freqs_full.size, 256)
    display_freqs = np.array([float(np.mean(freqs_full[a:b])) for a, b in zip(freq_edges[:-1], freq_edges[1:])])
    time_group = max(1, int(math.ceil(total_frames / max_spectrogram_frames)))
    display_time_groups = int(math.ceil(total_frames / time_group))
    display_power = np.zeros((display_freqs.size, display_time_groups), dtype=np.float64)
    display_counts = np.zeros(display_time_groups, dtype=np.int64)

    mel_bands = 128
    mel_freqs = librosa.mel_frequencies(n_mels=mel_bands, fmin=20.0, fmax=min(20000.0, sr / 2.0))
    mel_display_power = np.zeros((mel_bands, min(300, total_frames)), dtype=np.float64)
    mel_display_counts = np.zeros(mel_display_power.shape[1], dtype=np.int64)
    mel_time_group = max(1, int(math.ceil(total_frames / mel_display_power.shape[1])))
    mel_avg = np.zeros(mel_bands, dtype=np.float64)

    chroma_display_power = np.zeros((12, min(300, total_frames)), dtype=np.float64)
    chroma_display_counts = np.zeros(chroma_display_power.shape[1], dtype=np.int64)
    chroma_time_group = max(1, int(math.ceil(total_frames / chroma_display_power.shape[1])))
    chroma_sum = np.zeros(12, dtype=np.float64)

    avg_power = np.zeros(freqs_full.size, dtype=np.float64)
    avg_abs2 = np.zeros(freqs_full.size, dtype=np.float64)
    feature_lists: dict[str, list[np.ndarray]] = {
        "centroid": [], "bandwidth": [], "rolloff": [], "flatness": [], "flux": [],
        "zcr": [], "contrast": [], "energy_db": [],
    }
    band_power_lists: dict[str, list[np.ndarray]] = {key: [] for key, _, _, _ in BANDS}
    onset_parts: list[np.ndarray] = []
    prev_amp: np.ndarray | None = None
    prev_logmel: np.ndarray | None = None
    total_power = 0.0

    band_masks = {}
    for key, _label, low, high in BANDS:
        band_masks[key] = (freqs_full >= low) & (freqs_full < high)

    frame_blocks = 0
    for start, end, amplitude, psd, abs2, zcr, freqs, n_frames in _stft_blocks(mono, sr, n_fft, hop_length):
        # Internally use (frequency, frame) orientation, matching librosa.
        amplitude = amplitude.T
        psd = psd.T
        abs2 = abs2.T
        frames = end - start
        frame_blocks += 1
        avg_power += np.sum(psd, axis=1)
        avg_abs2 += np.sum(abs2, axis=1)
        total_power += float(np.sum(psd))
        # Spectral features from magnitude spectra.
        amp_sum = np.sum(amplitude, axis=0) + 1e-12
        centroid = np.sum(amplitude * freqs[:, None], axis=0) / amp_sum
        bandwidth = np.sqrt(np.sum(amplitude * (freqs[:, None] - centroid[None, :]) ** 2, axis=0) / amp_sum)
        cumulative = np.cumsum(amplitude, axis=0)
        threshold = 0.85 * cumulative[-1, :]
        rolloff_idx = np.argmax(cumulative >= threshold[None, :], axis=0)
        rolloff = freqs[rolloff_idx]
        flatness = np.exp(np.mean(np.log(amplitude + 1e-12), axis=0)) / (np.mean(amplitude, axis=0) + 1e-12)
        if prev_amp is None:
            diff = np.zeros_like(amplitude)
        else:
            diff = np.maximum(0.0, amplitude - np.concatenate([prev_amp[:, None], amplitude[:, :-1]], axis=1))
        flux = np.sqrt(np.mean(diff ** 2, axis=0)) / (np.mean(amplitude, axis=0) + 1e-12)
        prev_amp = amplitude[:, -1].copy()
        try:
            contrast = librosa.feature.spectral_contrast(
                S=amplitude, sr=sr, n_fft=n_fft, hop_length=hop_length, n_bands=6, fmin=100.0
            )
            contrast_mean = np.mean(contrast, axis=0)
        except Exception:
            # Not computable (e.g. Nyquist below the top contrast band):
            # NaN makes the summary report "not available" instead of 0 dB.
            contrast_mean = np.full(frames, np.nan)
        energy_db = 10.0 * np.log10(np.maximum(np.sum(psd, axis=0), 1e-20))
        feature_lists["centroid"].append(centroid.astype(np.float32))
        feature_lists["bandwidth"].append(bandwidth.astype(np.float32))
        feature_lists["rolloff"].append(rolloff.astype(np.float32))
        feature_lists["flatness"].append(flatness.astype(np.float32))
        feature_lists["flux"].append(flux.astype(np.float32))
        feature_lists["zcr"].append(zcr.astype(np.float32))
        feature_lists["contrast"].append(contrast_mean.astype(np.float32))
        feature_lists["energy_db"].append(energy_db.astype(np.float32))
        for key, _label, _low, _high in BANDS:
            band_power_lists[key].append(np.sum(psd[band_masks[key]], axis=0).astype(np.float32))

        # Display spectrogram: aggregate frequency bins then time groups.
        sums = np.add.reduceat(amplitude ** 2, freq_edges[:-1], axis=0)
        counts = np.diff(freq_edges).astype(np.float64)
        block_freq = sums / counts[:, None]
        group_ids = (np.arange(start, end) // time_group)
        for g in np.unique(group_ids):
            mask = group_ids == g
            display_power[:, g] += np.sum(block_freq[:, mask], axis=1)
            display_counts[g] += int(np.sum(mask))

        # Mel and chroma.
        mel_power = librosa.feature.melspectrogram(
            S=psd, sr=sr, n_mels=mel_bands, fmin=20.0, fmax=min(20000.0, sr / 2.0), power=1.0
        )
        mel_avg += np.sum(mel_power, axis=1)
        logmel = 10.0 * np.log10(np.maximum(mel_power, 1e-20))
        if prev_logmel is None:
            mel_diff = np.zeros((mel_bands, frames))
        else:
            mel_diff = np.maximum(0.0, logmel - np.concatenate([prev_logmel[:, None], logmel[:, :-1]], axis=1))
        prev_logmel = logmel[:, -1].copy()
        onset_parts.append(np.mean(mel_diff, axis=0).astype(np.float32))
        mel_ids = np.arange(start, end) // mel_time_group
        for g in np.unique(mel_ids):
            mask = mel_ids == g
            mel_display_power[:, g] += np.sum(mel_power[:, mask], axis=1)
            mel_display_counts[g] += int(np.sum(mask))

        chroma = librosa.feature.chroma_stft(
            S=np.sqrt(psd), sr=sr, n_fft=n_fft, hop_length=hop_length, tuning=0.0, norm=2
        )
        chroma_sum += np.sum(chroma, axis=1)
        chroma_ids = np.arange(start, end) // chroma_time_group
        for g in np.unique(chroma_ids):
            mask = chroma_ids == g
            chroma_display_power[:, g] += np.sum(chroma[:, mask], axis=1)
            chroma_display_counts[g] += int(np.sum(mask))
        if progress:
            progress(0.15 + 0.55 * (end / max(1, total_frames)), "Computing spectral features")

    # Flatten the per-block feature arrays.  The time axis is derived from the
    # concatenated frame count; STFT frames are centred, so frame k is at
    # k * hop / sr seconds.
    flat_features: dict[str, np.ndarray] = {}
    for key, parts in feature_lists.items():
        flat_features[key] = np.concatenate(parts) if parts else np.zeros(1)
    actual_frames = min(len(v) for v in flat_features.values())
    for key in flat_features:
        flat_features[key] = flat_features[key][:actual_frames]
    frame_times = np.arange(actual_frames, dtype=np.float64) * hop_length / sr
    band_psd_frames = {
        key: (np.concatenate(parts)[:actual_frames] if parts else np.zeros(actual_frames))
        for key, parts in band_power_lists.items()
    }
    onset_env = np.concatenate(onset_parts)[:actual_frames] if onset_parts else np.zeros(actual_frames)
    if onset_env.size:
        onset_env = onset_env - float(np.min(onset_env))
        peak = float(np.max(onset_env))
        if peak > 0:
            onset_env = onset_env / peak
    # Downsample values and times with the same bucketing so they stay paired.
    onset_values = downsample_envelope(onset_env, max_feature_points)
    onset_times = downsample_envelope(frame_times, max_feature_points)

    avg_psd = avg_power / max(1, actual_frames)
    avg_amp = 2.0 * np.sqrt(avg_abs2 / max(1, actual_frames)) / float(np.sum(signal.windows.hann(n_fft, sym=False)))
    avg_amp[0] /= 2.0
    if n_fft % 2 == 0:
        avg_amp[-1] /= 2.0
    avg_amp_db = 20.0 * np.log10(np.maximum(avg_amp, 1e-12))
    peaks = _peaks(freqs_full, avg_amp_db, avg_psd)
    bands = _band_analysis(freqs_full, avg_psd, band_psd_frames, frame_times)

    # Display spectrogram dB
    valid = display_counts > 0
    display_db = np.full(display_power.shape, -160.0)
    display_db[:, valid] = 10.0 * np.log10(np.maximum(display_power[:, valid] / display_counts[valid][None, :], 1e-20))
    display_db = np.clip(display_db, -140.0, 20.0)
    disp_times = np.array([
        min(duration, (g * time_group + max(0, time_group - 1) / 2.0) * hop_length / sr)
        for g in range(display_time_groups)
    ])
    valid_t = display_counts > 0
    disp_times = disp_times[valid_t]
    display_db = display_db[:, valid_t]
    log_freqs = np.geomspace(max(20.0, display_freqs[1] if display_freqs.size > 1 else 20.0), min(sr / 2.0, 20000.0), 160)
    log_db = np.empty((log_freqs.size, display_db.shape[1]))
    for col in range(display_db.shape[1]):
        log_db[:, col] = np.interp(log_freqs, display_freqs, display_db[:, col], left=-160.0, right=-160.0)

    mel_valid = mel_display_counts > 0
    mel_db = np.full(mel_display_power.shape, -160.0)
    mel_db[:, mel_valid] = 10.0 * np.log10(np.maximum(mel_display_power[:, mel_valid] / mel_display_counts[mel_valid][None, :], 1e-20))
    mel_times = np.array([
        min(duration, (g * mel_time_group + max(0, mel_time_group - 1) / 2.0) * hop_length / sr)
        for g in range(mel_display_power.shape[1])
    ])[mel_valid]
    mel_db = mel_db[:, mel_valid]
    mel_avg_db = 10.0 * np.log10(np.maximum(mel_avg / max(1, actual_frames), 1e-20))

    chroma_valid = chroma_display_counts > 0
    chroma_matrix = np.zeros((12, chroma_display_power.shape[1]))
    chroma_matrix[:, chroma_valid] = chroma_display_power[:, chroma_valid] / chroma_display_counts[chroma_valid][None, :]
    chroma_times = np.array([
        min(duration, (g * chroma_time_group + max(0, chroma_time_group - 1) / 2.0) * hop_length / sr)
        for g in range(chroma_display_power.shape[1])
    ])[chroma_valid]
    chroma_matrix = chroma_matrix[:, chroma_valid]
    chroma_mean = chroma_sum / max(1, actual_frames)
    chroma_total = float(np.sum(chroma_mean))
    # Silence has no chroma; keep zeros so key detection reports "unsupported"
    # instead of receiving an invented uniform profile.
    chroma_mean = chroma_mean / chroma_total if chroma_total > 0 else np.zeros(12)

    features = {
        "centroid_hz": _summarize(flat_features["centroid"], frame_times, max_feature_points),
        "bandwidth_hz": _summarize(flat_features["bandwidth"], frame_times, max_feature_points),
        "rolloff85_hz": _summarize(flat_features["rolloff"], frame_times, max_feature_points),
        "flux": _summarize(flat_features["flux"], frame_times, max_feature_points),
        "flatness": _summarize(flat_features["flatness"], frame_times, max_feature_points),
        "zero_crossing_rate": _summarize(flat_features["zcr"], frame_times, max_feature_points),
        "spectral_contrast_db": _summarize(flat_features["contrast"], frame_times, max_feature_points),
        "spectral_energy_db": _summarize(flat_features["energy_db"], frame_times, max_feature_points),
    }
    centroid_mean = features["centroid_hz"]["mean"]

    hpss = _hpss_analysis(mono, sr, duration, min(hpss_seconds, duration))
    features["harmonic_to_noise_ratio_db"] = hpss.get("hnr_db")
    features["hnr_method"] = "Harmonic/percussive energy ratio from median-filtering HPSS (not a classical autocorrelation HNR)"
    observations = _observations(bands, peaks, centroid_mean)

    return {
        "fft": {
            "frequencies_hz": [round_sig(v, 3) for v in freqs_full.tolist()],
            "average_dbfs": [round_sig(v, 2) for v in avg_amp_db.tolist()],
            "average_power_psd": [round_sig(v, 12) for v in avg_psd.tolist()],
            "peaks": peaks,
            "dominant_frequency_hz": peaks[0]["frequency_hz"] if peaks else None,
            "n_fft": n_fft,
            "window": "Hann (periodic)",
            "bin_width_hz": round_sig(sr / n_fft, 3),
            "method": "Average of |STFT| across the full file; amplitude calibrated so a full-scale sine reads 0 dBFS at its peak bin.",
        },
        "spectrogram": {
            "times": [round_sig(v, 3) for v in disp_times.tolist()],
            "frequencies_hz": [round_sig(v, 2) for v in display_freqs.tolist()],
            "magnitude_db": [[round_sig(v, 2) for v in row] for row in display_db.tolist()],
            "log_frequencies_hz": [round_sig(v, 2) for v in log_freqs.tolist()],
            "log_magnitude_db": [[round_sig(v, 2) for v in row] for row in log_db.tolist()],
            "n_fft": n_fft,
            "hop_length": hop_length,
            "db_floor": -140.0,
            "method": f"STFT magnitude in dBFS (Hann window, n_fft={n_fft}, hop={hop_length}, {100.0 * (1.0 - hop_length / n_fft):.0f}% overlap)",
        },
        "mel": {
            "times": [round_sig(v, 3) for v in mel_times.tolist()],
            "frequencies_hz": [round_sig(v, 2) for v in mel_freqs.tolist()],
            "power_db": [[round_sig(v, 2) for v in row] for row in mel_db.tolist()],
            "average_db": [round_sig(v, 2) for v in mel_avg_db.tolist()],
            "n_mels": mel_bands,
            "fmin_hz": 20.0,
            "fmax_hz": min(20000.0, sr / 2.0),
            "method": "Slaney-normalised Mel filterbank over the calibrated power spectrogram; dB is relative to 1.0 mean-square.",
        },
        "chroma": {
            "times": [round_sig(v, 3) for v in chroma_times.tolist()],
            "pitch_classes": PITCH_CLASSES,
            "energy": [[round_sig(v, 4) for v in row] for row in chroma_matrix.tolist()],
            "mean_energy": [round_sig(v, 4) for v in chroma_mean.tolist()],
            "method": "Chroma-STFT (L2 normalised per frame), full file.",
        },
        "spectral_features": features,
        "bands": bands,
        "observations": observations,
        "hpss": hpss,
        "onset_envelope": {
            "times": [round_sig(v, 3) for v in onset_times.tolist()],
            "values": [round_sig(v, 4) for v in onset_values.tolist()],
            "hop_length": hop_length,
            "method": "Positive log-Mel spectral flux, normalised to its maximum",
        },
        "analysis_settings": {
            "n_fft": n_fft,
            "hop_length": hop_length,
            "window": "Hann",
            "max_spectrogram_frames": max_spectrogram_frames,
            "frame_count": int(actual_frames),
        },
        "confidence": {
            "spectral_features": "high",
            "fft": "high",
            "spectrogram": "high",
            "key_input_chroma": "medium",
            "hpss": "medium" if duration > hpss_seconds else "high",
        },
    }


def _hpss_analysis(mono: np.ndarray, sr: int, duration: float, window_seconds: float) -> dict[str, Any]:
    if duration <= 0.1:
        return {"supported": False, "reason": "Audio is too short for harmonic/percussive separation"}
    window_seconds = float(max(0.25, min(window_seconds, duration)))
    if window_seconds < duration:
        start = max(0.0, duration / 2.0 - window_seconds / 2.0)
    else:
        start = 0.0
    end = min(duration, start + window_seconds)
    a = int(round(start * sr))
    b = int(round(end * sr))
    segment = mono[a:b]
    try:
        harmonic, percussive = librosa.effects.hpss(segment, kernel_size=31, power=2.0)
    except Exception as exc:
        return {"supported": False, "reason": f"HPSS failed: {exc}"}
    residual = segment - harmonic - percussive
    h_energy = float(np.mean(harmonic.astype(np.float64) ** 2))
    p_energy = float(np.mean(percussive.astype(np.float64) ** 2))
    r_energy = float(np.mean(residual.astype(np.float64) ** 2))
    total = h_energy + p_energy + r_energy
    hnr = 10.0 * math.log10(max(h_energy, 1e-20) / max(p_energy, 1e-20))
    def centroid(x: np.ndarray) -> float | None:
        if x.size < 256:
            return None
        spec = np.abs(librosa.stft(x, n_fft=2048, hop_length=1024))
        freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
        denom = float(np.sum(spec))
        if denom <= 0:
            return None
        return float(np.sum(freqs[:, None] * spec) / denom)
    def envelope(x: np.ndarray, points: int = 600) -> dict[str, list[float]]:
        frame = max(1, int(sr * 0.05))
        hop = max(1, int(sr * 0.025))
        if x.size < frame:
            return {"times": [0.0], "values": [round_sig(db(float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))), 2)]}
        view = np.lib.stride_tricks.sliding_window_view(x.astype(np.float64), frame)[::hop]
        rms = np.sqrt(np.mean(view ** 2, axis=1))
        rms_db = 20.0 * np.log10(np.maximum(rms, 1e-10))
        times = np.arange(rms_db.size) * hop / sr + start
        idx = np.linspace(0, rms_db.size - 1, min(points, rms_db.size)).astype(int)
        return {
            "times": [round_sig(v, 3) for v in times[idx].tolist()],
            "values": [round_sig(v, 2) for v in rms_db[idx].tolist()],
        }
    harmonic_centroid = centroid(harmonic)
    percussive_centroid = centroid(percussive)
    return {
        "supported": True,
        "segment_start": round_sig(start, 3),
        "segment_end": round_sig(end, 3),
        "analyzed_duration": round_sig(end - start, 3),
        "is_segment": end - start < duration - 0.05,
        "harmonic_energy_ratio": round_sig(h_energy / total if total > 0 else 0.0, 4),
        "percussive_energy_ratio": round_sig(p_energy / total if total > 0 else 0.0, 4),
        "residual_energy_ratio": round_sig(r_energy / total if total > 0 else 0.0, 4),
        "hnr_db": round_sig(hnr, 2),
        "harmonic_rms_dbfs": round_sig(db(math.sqrt(max(h_energy, 0.0))), 2),
        "percussive_rms_dbfs": round_sig(db(math.sqrt(max(p_energy, 0.0))), 2),
        "harmonic_centroid_hz": round_sig(harmonic_centroid, 2) if harmonic_centroid is not None else None,
        "percussive_centroid_hz": round_sig(percussive_centroid, 2) if percussive_centroid is not None else None,
        "envelopes": {
            "original": envelope(segment),
            "harmonic": envelope(harmonic),
            "percussive": envelope(percussive),
        },
        "method": "librosa HPSS (median-filtering, kernel 31, power 2.0). Energy ratio is not a perceptual HNR.",
        "confidence": "medium" if end - start < duration - 0.05 else "high",
        "note": "Harmonic/percussive separation is illustrative and lossy; it does not modify the source audio.",
    }


def compute_average_spectrum(
    mono: np.ndarray,
    sr: int,
    n_fft: int = 4096,
    hop_length: int = 1024,
) -> dict[str, Any]:
    """Lightweight average spectrum for a selected time range."""
    mono = np.asarray(mono, dtype=np.float32).reshape(-1)
    n_fft = int(max(256, min(n_fft, 32768)))
    hop_length = int(max(32, min(hop_length, n_fft)))
    if mono.size == 0:
        raise ValueError("No audio samples")
    window = signal.windows.hann(n_fft, sym=False).astype(np.float64)
    sum_w = float(np.sum(window))
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    avg_abs2 = np.zeros(freqs.size, dtype=np.float64)
    count = 0
    for _start, _end, _amp, _psd, abs2, _zcr, _freqs, _total in _stft_blocks(mono, sr, n_fft, hop_length):
        avg_abs2 += np.sum(abs2, axis=0)
        count += abs2.shape[0]
    avg_amp = 2.0 * np.sqrt(avg_abs2 / max(1, count)) / sum_w
    avg_amp[0] /= 2.0
    if n_fft % 2 == 0:
        avg_amp[-1] /= 2.0
    dbfs = 20.0 * np.log10(np.maximum(avg_amp, 1e-12))
    # Approximate PSD for peak-lobe integration.
    avg_psd = (avg_abs2 / max(1, count)) / (n_fft * float(np.sum(window ** 2)))
    if n_fft % 2 == 0:
        avg_psd[1:-1] *= 2.0
    else:
        avg_psd[1:] *= 2.0
    peaks = _peaks(freqs, dbfs, avg_psd)
    return {
        "frequencies_hz": [round_sig(v, 3) for v in freqs.tolist()],
        "average_dbfs": [round_sig(v, 2) for v in dbfs.tolist()],
        "peaks": peaks,
        "n_fft": n_fft,
        "hop_length": hop_length,
        "frame_count": int(count),
        "bin_width_hz": round_sig(sr / n_fft, 3),
    }


def compute_spectrogram_range(
    mono: np.ndarray,
    sr: int,
    n_fft: int = 4096,
    hop_length: int = 1024,
    max_frames: int = 400,
) -> dict[str, Any]:
    """Compute a display spectrogram for a selected segment or custom FFT size."""
    mono = np.asarray(mono, dtype=np.float32).reshape(-1)
    n_fft = int(max(256, min(n_fft, 32768)))
    hop_length = int(max(32, min(hop_length, n_fft)))
    if mono.size == 0:
        raise ValueError("No audio samples")
    max_frames = max(50, min(int(max_frames), 1200))
    pad = n_fft // 2
    total_frames = 1 + (mono.size + 2 * pad - n_fft) // hop_length
    total_frames = max(1, total_frames)
    time_group = max(1, int(math.ceil(total_frames / max_frames)))
    groups = int(math.ceil(total_frames / time_group))
    window = signal.windows.hann(n_fft, sym=False).astype(np.float64)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    freq_edges = _group_edges(freqs.size, 256)
    display_freqs = np.array([float(np.mean(freqs[a:b])) for a, b in zip(freq_edges[:-1], freq_edges[1:])])
    power = np.zeros((display_freqs.size, groups), dtype=np.float64)
    counts = np.zeros(groups, dtype=np.int64)
    for start, end, amplitude, _psd, _abs2, _zcr, _freqs, _total in _stft_blocks(mono, sr, n_fft, hop_length):
        sums = np.add.reduceat(amplitude.T ** 2, freq_edges[:-1], axis=0)
        freq_counts = np.diff(freq_edges).astype(np.float64)
        block = sums / freq_counts[:, None]
        ids = np.arange(start, end) // time_group
        for group in np.unique(ids):
            mask = ids == group
            power[:, group] += np.sum(block[:, mask], axis=1)
            counts[group] += int(np.sum(mask))
    valid = counts > 0
    db = np.full(power.shape, -160.0)
    db[:, valid] = 10.0 * np.log10(np.maximum(power[:, valid] / counts[valid][None, :], 1e-20))
    times = np.array([(g * time_group + (time_group - 1) / 2.0) * hop_length / sr for g in range(groups)])[valid]
    matrix = np.clip(db[:, valid], -140.0, 20.0)
    log_freqs = np.geomspace(max(20.0, display_freqs[1] if display_freqs.size > 1 else 20.0), min(sr / 2.0, 20000.0), 160)
    log_matrix = np.empty((log_freqs.size, matrix.shape[1]))
    for col in range(matrix.shape[1]):
        log_matrix[:, col] = np.interp(log_freqs, display_freqs, matrix[:, col], left=-160.0, right=-160.0)
    return {
        "times": [round_sig(v, 3) for v in times.tolist()],
        "frequencies_hz": [round_sig(v, 2) for v in display_freqs.tolist()],
        "magnitude_db": [[round_sig(v, 2) for v in row] for row in matrix.tolist()],
        "log_frequencies_hz": [round_sig(v, 2) for v in log_freqs.tolist()],
        "log_magnitude_db": [[round_sig(v, 2) for v in row] for row in log_matrix.tolist()],
        "n_fft": n_fft,
        "hop_length": hop_length,
        "frame_count": int(total_frames),
    }
