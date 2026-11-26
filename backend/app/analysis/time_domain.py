"""Time-domain analysis: levels, envelopes, clipping, silence and dropouts."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy import ndimage

from .loudness import true_peak as compute_true_peak
from .utils import db, downsample_envelope, merge_regions, regions_from_mask, round_sig


_CHUNK_SECONDS = 10.0


def _channel_block_stats(
    data: np.ndarray, sr: int, hop: int, clip_linear: float
) -> dict[str, Any]:
    """Stream every channel once, in bounded chunks, collecting per-hop-block
    statistics.  Memory use is O(blocks) instead of O(samples) in float64.

    Returns per-block sum of squares (summed over channels), per-block max
    |sample| (max over channels), and per-channel totals used by the level,
    DC and clipping measurements.
    """
    n, channels = data.shape
    n_blocks = int(math.ceil(n / hop))
    block_sumsq = np.zeros(n_blocks, dtype=np.float64)
    block_peak = np.zeros(n_blocks, dtype=np.float64)
    clip_any = np.zeros(n, dtype=bool)
    sums = np.zeros(channels, dtype=np.float64)
    sumsq = np.zeros(channels, dtype=np.float64)
    peaks = np.zeros(channels, dtype=np.float64)
    clip_counts = np.zeros(channels, dtype=np.int64)
    flat_top = 0
    blocks_per_chunk = max(1, int(_CHUNK_SECONDS * sr) // hop)
    chunk = blocks_per_chunk * hop
    for ch in range(channels):
        column = data[:, ch]
        previous: float | None = None
        previous_clipped = False
        for start in range(0, n, chunk):
            end = min(n, start + chunk)
            x = column[start:end].astype(np.float64)
            ax = np.abs(x)
            sums[ch] += float(np.sum(x))
            sumsq[ch] += float(np.dot(x, x))
            peaks[ch] = max(peaks[ch], float(np.max(ax)) if ax.size else 0.0)
            clip_mask = ax >= clip_linear
            count = int(np.count_nonzero(clip_mask))
            clip_counts[ch] += count
            clip_any[start:end] |= clip_mask
            if count or previous_clipped:
                # Include the last sample of the previous chunk so runs that
                # straddle a chunk boundary are counted exactly once.
                if previous is not None:
                    xs = np.concatenate([[previous], x])
                    ms = np.concatenate([[previous_clipped], clip_mask])
                else:
                    xs, ms = x, clip_mask
                diffs = np.abs(np.diff(xs))
                at_clip = ms[1:] | ms[:-1]
                flat_top += int(np.count_nonzero((diffs < 1e-6) & at_clip))
            previous = float(x[-1])
            previous_clipped = bool(clip_mask[-1])
            # Per-block aggregation (the final block may be partial).
            first_block = start // hop
            full = (x.size // hop) * hop
            if full:
                sq = (x[:full] ** 2).reshape(-1, hop)
                block_sumsq[first_block:first_block + full // hop] += sq.sum(axis=1)
                pk = ax[:full].reshape(-1, hop).max(axis=1)
                seg = block_peak[first_block:first_block + full // hop]
                np.maximum(seg, pk, out=seg)
            if full < x.size:
                index = first_block + full // hop
                block_sumsq[index] += float(np.dot(x[full:], x[full:]))
                block_peak[index] = max(block_peak[index], float(np.max(ax[full:])))
    return {
        "block_sumsq": block_sumsq,
        "block_peak": block_peak,
        "clip_any": clip_any,
        "sums": sums,
        "sumsq": sumsq,
        "peaks": peaks,
        "clip_counts": clip_counts,
        "flat_top": flat_top,
    }


def _regions_from_sample_mask(mask: np.ndarray, sr: int, gap_seconds: float = 0.02) -> list[dict[str, float]]:
    if not np.any(mask):
        return []
    indices = np.flatnonzero(mask)
    if indices.size == 0:
        return []
    breaks = np.where(np.diff(indices) > 1)[0]
    starts = np.concatenate([[indices[0]], indices[breaks + 1]])
    ends = np.concatenate([indices[breaks], [indices[-1]]])
    regions = [(float(a) / sr, float(b + 1) / sr) for a, b in zip(starts, ends)]
    return merge_regions(regions, gap_seconds)


def _waveform_peaks(x: np.ndarray, sr: int, max_buckets: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = x.size
    if n == 0:
        return np.array([]), np.array([]), np.array([]), np.array([])
    buckets = int(min(max_buckets, max(1, n)))
    edges = np.linspace(0, n, buckets + 1).astype(int)
    mins = np.empty(buckets)
    maxs = np.empty(buckets)
    rms = np.empty(buckets)
    times = np.empty(buckets)
    for i in range(buckets):
        a, b = edges[i], max(edges[i + 1], edges[i] + 1)
        segment = x[a:b]
        mins[i] = float(np.min(segment))
        maxs[i] = float(np.max(segment))
        rms[i] = float(np.sqrt(np.mean(segment.astype(np.float64) ** 2)))
        times[i] = (a + b - 1) / 2.0 / sr
    return times, mins, maxs, rms


def analyze_time_domain(
    data: np.ndarray,
    sr: int,
    true_peak_dbtp: float | None = None,
    max_points: int = 1200,
    max_waveform_buckets: int = 4000,
    silence_threshold_dbfs: float = -60.0,
    clipping_threshold_dbfs: float = -0.1,
) -> dict[str, Any]:
    data = np.asarray(data, dtype=np.float32)
    if data.ndim == 1:
        data = data[:, None]
    n, channels = data.shape
    if n == 0:
        raise ValueError("No audio samples for time-domain analysis")
    duration = n / float(sr)
    clip_linear = 10.0 ** (clipping_threshold_dbfs / 20.0)
    hop = max(1, int(round(0.025 * sr)))
    frame = 2 * hop  # 50 ms frames with a 25 ms hop (two hop blocks per frame)
    stats = _channel_block_stats(data, sr, hop, clip_linear)
    sample_peak = float(np.max(stats["peaks"]))
    sample_peak_dbfs = db(sample_peak)
    if true_peak_dbtp is None:
        true_peak_dbtp, _ = compute_true_peak(data, sr)
    rms = float(math.sqrt(float(np.sum(stats["sumsq"])) / (n * channels)))
    rms_dbfs = db(rms)

    per_channel = []
    dc_values = []
    clipping_counts = [int(v) for v in stats["clip_counts"]]
    clip_any = stats["clip_any"]
    flat_top_count = int(stats["flat_top"])
    for ch in range(channels):
        ch_peak = float(stats["peaks"][ch])
        ch_rms = float(math.sqrt(stats["sumsq"][ch] / n))
        dc = float(stats["sums"][ch] / n)
        dc_values.append(dc)
        count = clipping_counts[ch]
        per_channel.append({
            "channel": ch + 1,
            "label": "Left" if ch == 0 and channels == 2 else "Right" if ch == 1 and channels == 2 else f"Channel {ch + 1}",
            "peak_dbfs": round_sig(db(ch_peak), 2),
            "rms_dbfs": round_sig(db(ch_rms), 2),
            "dc_offset": round_sig(dc, 8),
            "dc_offset_dbfs": round_sig(db(abs(dc)), 2),
            "clipped_samples": count,
            "clipped_percent": round_sig(count / n * 100.0, 4),
        })

    # Clipping is counted per sample (channel-sample), so the percentage uses
    # the same unit in numerator and denominator.  Frames where any channel
    # clips are reported separately.
    clipped_total = int(sum(clipping_counts))
    clipped_frames = int(np.count_nonzero(clip_any))
    clipping_regions = _regions_from_sample_mask(clip_any, sr, gap_seconds=0.01)
    del clip_any
    if len(clipping_regions) > 200:
        clipping_regions = clipping_regions[:200]
    dc_max = max((abs(v) for v in dc_values), default=0.0)

    # 50 ms frame statistics over *all channels* (not the mono fold-down, in
    # which anti-phase content cancels and would read as silence).
    block_sumsq = stats["block_sumsq"]
    block_peak = stats["block_peak"]
    if n >= frame:
        count = (n - frame) // hop + 1
        frame_energy = (block_sumsq[:count] + block_sumsq[1:count + 1]) / (frame * channels)
        peak_frames = np.maximum(block_peak[:count], block_peak[1:count + 1])
    else:
        frame_energy = np.array([float(np.sum(block_sumsq)) / (n * channels)])
        peak_frames = np.array([float(np.max(block_peak))])
    rms_frames = np.sqrt(frame_energy)
    rms_db = 20.0 * np.log10(np.maximum(rms_frames, 1e-10))
    peak_db = 20.0 * np.log10(np.maximum(peak_frames, 1e-10))
    frame_times = np.arange(rms_db.size) * hop / sr + (frame / 2.0) / sr
    frame_times = np.minimum(frame_times, duration)

    silent_mask = rms_db < silence_threshold_dbfs
    silence_regions = regions_from_mask(frame_times, silent_mask, gap=0.1)
    silence_duration = float(sum(r["duration"] for r in silence_regions))
    digital_mask = rms_frames < 1e-10
    digital_regions = regions_from_mask(frame_times, digital_mask, gap=0.1)
    digital_duration = float(sum(r["duration"] for r in digital_regions))

    # Dropouts: short, abrupt dips well below the local level.
    median_db = ndimage.median_filter(rms_db, size=max(3, int(round(2.0 / 0.025))), mode="nearest")
    dropout_mask = (rms_db < -55.0) & (median_db > -40.0) & (rms_db < median_db - 25.0)
    dropout_regions = regions_from_mask(frame_times, dropout_mask, gap=0.05)
    dropout_regions = [
        r for r in dropout_regions
        if 0.02 <= r["duration"] <= 1.0 and r["start"] > 0.25 and r["end"] < duration - 0.25
    ][:20]

    finite_frames = rms_db[np.isfinite(rms_db)]
    if finite_frames.size:
        audible_frames = finite_frames[finite_frames > -100.0]
        if audible_frames.size >= 10:
            noise_candidate = float(np.percentile(audible_frames, 10))
            median_level = float(np.percentile(audible_frames, 50))
            if median_level - noise_candidate >= 6.0:
                noise_floor = noise_candidate
                snr = rms_dbfs - noise_candidate
                noise_confidence = "medium"
                noise_note = "Noise floor is the 10th percentile of audible 50 ms RMS frames; SNR = overall RMS minus noise floor."
            else:
                noise_floor = None
                snr = None
                noise_confidence = "unavailable"
                noise_note = "The file does not contain enough quiet material to separate a noise floor from the signal. No noise-floor value is reported rather than inventing one."
        else:
            noise_floor = None
            snr = None
            noise_confidence = "unavailable"
            noise_note = "Too few audible frames to estimate a noise floor."
        rms_p5 = float(np.percentile(finite_frames, 5))
        rms_p95 = float(np.percentile(finite_frames, 95))
        rms_std = float(np.std(finite_frames))
    else:
        noise_floor = None
        snr = None
        noise_confidence = "unavailable"
        noise_note = "No finite RMS frames."
        rms_p5 = rms_p95 = -160.0
        rms_std = 0.0
    peak_finite = peak_db[np.isfinite(peak_db)]
    peak_p5 = float(np.percentile(peak_finite, 5)) if peak_finite.size else -160.0
    peak_p95 = float(np.percentile(peak_finite, 95)) if peak_finite.size else -160.0

    # Envelopes downsampled for plotting.
    idx = np.linspace(0, rms_db.size - 1, min(max_points, rms_db.size)).astype(int) if rms_db.size else np.array([], dtype=int)
    env_times = frame_times[idx]
    amplitude = rms_frames[idx]
    env = {
        "times": [round_sig(v, 3) for v in env_times.tolist()],
        "rms_db": [round_sig(v, 2) for v in rms_db[idx].tolist()],
        "peak_db": [round_sig(v, 2) for v in peak_db[idx].tolist()],
        "amplitude": [round_sig(v, 6) for v in amplitude.tolist()],
        "short_time_energy_db": [round_sig(v, 2) for v in (10.0 * np.log10(np.maximum(rms_frames[idx] ** 2, 1e-20))).tolist()],
        "frame_seconds": round_sig(frame / sr, 4),
        "hop_seconds": round_sig(hop / sr, 4),
    }

    # Mono fold-down for the display waveform only, built in float32 to avoid a
    # full float64 copy of long files.
    mono = data[:, 0].copy() if channels == 1 else np.mean(data, axis=1, dtype=np.float32)
    wf_times, wf_min, wf_max, wf_rms = _waveform_peaks(mono, sr, max_waveform_buckets)
    del mono
    channel_waveforms = []
    for ch in range(min(channels, 2)):
        t, mn, mx, rm = _waveform_peaks(data[:, ch], sr, max_waveform_buckets)
        channel_waveforms.append({
            "channel": ch + 1,
            "label": "Left" if channels == 2 and ch == 0 else "Right" if channels == 2 else f"Channel {ch + 1}",
            "min": [round_sig(v, 6) for v in mn.tolist()],
            "max": [round_sig(v, 6) for v in mx.tolist()],
            "rms": [round_sig(v, 6) for v in rm.tolist()],
        })
    waveform = {
        "times": [round_sig(v, 3) for v in wf_times.tolist()],
        "channels": channel_waveforms,
        "mono_min": [round_sig(v, 6) for v in wf_min.tolist()],
        "mono_max": [round_sig(v, 6) for v in wf_max.tolist()],
        "mono_rms_db": [round_sig(db(v), 2) for v in wf_rms.tolist()],
        "bucket_count": int(wf_times.size),
        "channel_note": (
            "Waveform peaks for the first two channels are shown; all channels are included in the measurements."
            if channels > 2 else None
        ),
    }

    # Distinguish the two over-full-scale conditions:
    #  * sample clipping: samples reach the clipping threshold (counted above);
    #  * intersample overs: the reconstructed signal exceeds 0 dBTP although no
    #    sample reaches the clipping threshold.
    true_peak_over = bool(true_peak_dbtp is not None and true_peak_dbtp > 0.0)
    intersample_overs = bool(true_peak_over and sample_peak < clip_linear)
    return {
        "duration_seconds": round_sig(duration, 4),
        "sample_count": int(n),
        "channel_count": int(channels),
        "sample_peak": {
            "dbfs": round_sig(sample_peak_dbfs, 2),
            "linear": round_sig(sample_peak, 8),
            "per_channel": per_channel,
        },
        "true_peak_dbtp": round_sig(true_peak_dbtp, 2),
        "rms": {
            "dbfs": round_sig(rms_dbfs, 2),
            "linear": round_sig(rms, 8),
            "per_channel_dbfs": [round_sig(p["rms_dbfs"], 2) for p in per_channel],
        },
        "dc_offset": {
            "per_channel": [round_sig(v, 8) for v in dc_values],
            "max_abs": round_sig(dc_max, 8),
            "max_abs_dbfs": round_sig(db(dc_max), 2),
            "method": "Arithmetic mean of each channel over the full file",
        },
        "clipping": {
            "threshold_dbfs": clipping_threshold_dbfs,
            "threshold_linear": round_sig(clip_linear, 8),
            "clipped_samples": clipped_total,
            "clipped_frames": clipped_frames,
            "clipped_percent": round_sig(clipped_total / (n * channels) * 100.0, 4),
            "flat_top_samples": int(flat_top_count),
            "intersample_overs": intersample_overs,
            "true_peak_over_full_scale": true_peak_over,
            "regions": clipping_regions,
            "per_channel_samples": clipping_counts,
            "method": "Sample-level threshold per channel sample; clipped_percent = clipped channel-samples / (frames x channels). clipped_frames counts sample frames where any channel clips. Flat-top count measures near-zero sample differences inside clipped runs. Intersample overs are flagged only when true peak exceeds 0 dBTP while no sample reaches the clipping threshold; true_peak_over_full_scale is set whenever true peak exceeds 0 dBTP.",
        },
        "silence": {
            "threshold_dbfs": silence_threshold_dbfs,
            "frame_seconds": round_sig(frame / sr, 3),
            "duration_seconds": round_sig(silence_duration, 3),
            "percent": round_sig(silence_duration / duration * 100.0, 2) if duration > 0 else 0.0,
            "regions": silence_regions,
            "digital_silence_duration_seconds": round_sig(digital_duration, 3),
            "digital_silence_regions": digital_regions,
            "method": "50 ms RMS frames (all channels) below the threshold, merged with 100 ms tolerance",
        },
        "noise": {
            "noise_floor_dbfs": round_sig(noise_floor, 2) if noise_floor is not None else None,
            "snr_db": round_sig(snr, 2) if snr is not None else None,
            "method": noise_note,
            "confidence": noise_confidence,
        },
        "dropouts": {
            "count": len(dropout_regions),
            "regions": dropout_regions,
            "method": "Short dips (>25 dB below a 2 s local median and below -55 dBFS) lasting 20-1000 ms, excluding file edges",
        },
        "signal_variation": {
            "rms_std_db": round_sig(rms_std, 2),
            "rms_p5_dbfs": round_sig(rms_p5, 2),
            "rms_p95_dbfs": round_sig(rms_p95, 2),
            "peak_p5_dbfs": round_sig(peak_p5, 2),
            "peak_p95_dbfs": round_sig(peak_p95, 2),
            "rms_range_db": round_sig(rms_p95 - rms_p5, 2),
        },
        "envelopes": env,
        "waveform": waveform,
        "regions": {
            "clipping": clipping_regions,
            "silence": silence_regions,
            "digital_silence": digital_regions,
            "dropouts": dropout_regions,
        },
    }


def compute_waveform_peaks(data: np.ndarray, sr: int, buckets: int = 4000) -> dict[str, Any]:
    """Public waveform peak extractor used by the zoom endpoint."""
    data = np.asarray(data, dtype=np.float32)
    if data.ndim == 1:
        data = data[:, None]
    n, channels = data.shape
    if n == 0:
        return {"times": [], "channels": [], "mono_min": [], "mono_max": [], "mono_rms_db": [], "bucket_count": 0}
    buckets = int(max(50, min(buckets, 8000)))
    mono = np.mean(data, axis=1, dtype=np.float64)
    times, mono_min, mono_max, mono_rms = _waveform_peaks(mono, sr, buckets)
    channel_payload = []
    for ch in range(min(channels, 2)):
        _t, mn, mx, rm = _waveform_peaks(data[:, ch].astype(np.float64), sr, buckets)
        channel_payload.append({
            "channel": ch + 1,
            "label": "Left" if channels == 2 and ch == 0 else "Right" if channels == 2 else f"Channel {ch + 1}",
            "min": [round_sig(v, 6) for v in mn.tolist()],
            "max": [round_sig(v, 6) for v in mx.tolist()],
            "rms": [round_sig(v, 6) for v in rm.tolist()],
        })
    return {
        "times": [round_sig(v, 3) for v in times.tolist()],
        "channels": channel_payload,
        "mono_min": [round_sig(v, 6) for v in mono_min.tolist()],
        "mono_max": [round_sig(v, 6) for v in mono_max.tolist()],
        "mono_rms_db": [round_sig(db(v), 2) for v in mono_rms.tolist()],
        "bucket_count": int(times.size),
    }
