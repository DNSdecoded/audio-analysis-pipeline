"""ITU-R BS.1770-4 / EBU R128 loudness measurement.

Implemented directly from the published K-weighting filter and gating
procedure so the application does not depend on an opaque third-party meter.
Reference validation against pyloudnorm is included in the test suite.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy import signal

from .utils import db, round_sig, safe_float

ABSOLUTE_GATE = -70.0
RELATIVE_GATE = -10.0
LRA_RELATIVE_GATE = -20.0

# Default channel order per channel count, following the WAVE_FORMAT_EXTENSIBLE
# / FFmpeg default layouts (this is the order libsndfile and PyAV deliver).
DEFAULT_CHANNEL_NAMES: dict[int, list[str]] = {
    1: ["FC"],
    2: ["FL", "FR"],
    3: ["FL", "FR", "FC"],
    4: ["FL", "FR", "BL", "BR"],
    5: ["FL", "FR", "FC", "BL", "BR"],
    6: ["FL", "FR", "FC", "LFE", "BL", "BR"],
    7: ["FL", "FR", "FC", "LFE", "BC", "SL", "SR"],
    8: ["FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"],
}
# BS.1770-4 Table 3: surround channels +1.5 dB (G = 1.41), LFE excluded.
SURROUND_CHANNELS = {"BL", "BR", "SL", "SR", "BC", "LS", "RS", "LSD", "RSD", "TBL", "TBR"}
EXCLUDED_CHANNELS = {"LFE", "LFE2", "LFE1"}


def channel_weights(channels: int, layout: str | None = None) -> tuple[list[float], list[str], str]:
    """Return (weights, channel names, source) for BS.1770 channel weighting.

    Channels are identified by name, not by position, so the LFE channel is
    excluded and surround channels receive the +1.5 dB weight regardless of
    where the layout places them.
    """
    names: list[str] | None = None
    source = "default order for channel count"
    if layout and channels > 2:
        try:  # PyAV knows the channel order of every FFmpeg layout name
            import av  # noqa: PLC0415

            parsed = [ch.name.upper() for ch in av.AudioLayout(layout).channels]
            if len(parsed) == channels:
                names = parsed
                source = f"decoder layout '{layout}'"
        except Exception:
            names = None
    if names is None:
        names = DEFAULT_CHANNEL_NAMES.get(channels) or [f"CH{i + 1}" for i in range(channels)]
    weights = [
        0.0 if name in EXCLUDED_CHANNELS else 1.41 if name in SURROUND_CHANNELS else 1.0
        for name in names
    ]
    return weights, names, source


# Retained for backwards compatibility with code that imported the table.
CHANNEL_WEIGHTS = {count: channel_weights(count)[0] for count in DEFAULT_CHANNEL_NAMES}


def k_weighting_sos(sample_rate: int) -> np.ndarray:
    """Return second-order sections for the two-stage K-weighting filter."""
    fs = float(sample_rate)
    # Stage 1: high shelf (head-related filter)
    f0 = 1681.974450955533
    gain_db = 3.999843853973347
    q = 0.7071752369554196
    k = math.tan(math.pi * f0 / fs)
    vh = 10.0 ** (gain_db / 20.0)
    vb = vh ** 0.4996667741545416
    a0 = 1.0 + k / q + k * k
    b1 = np.array([
        (vh + vb * k / q + k * k) / a0,
        2.0 * (k * k - vh) / a0,
        (vh - vb * k / q + k * k) / a0,
    ])
    a1 = np.array([
        1.0,
        2.0 * (k * k - 1.0) / a0,
        (1.0 - k / q + k * k) / a0,
    ])
    # Stage 2: RLB high-pass
    f0 = 38.13547087602444
    q = 0.5003270373238773
    k = math.tan(math.pi * f0 / fs)
    a0 = 1.0 + k / q + k * k
    b2 = np.array([1.0 / a0, -2.0 / a0, 1.0 / a0])
    a2 = np.array([
        1.0,
        2.0 * (k * k - 1.0) / a0,
        (1.0 - k / q + k * k) / a0,
    ])
    sos = np.vstack([np.concatenate([b1, a1]), np.concatenate([b2, a2])])
    return sos.astype(np.float64)


def _frame_energies(x: np.ndarray, sample_rate: int, step_samples: int) -> np.ndarray:
    """Mean-square energy of consecutive step-length frames.

    The signal is K-filtered in chunks, so memory use stays bounded even for
    long files.  Each chunk starts on a step boundary.
    """
    sos = k_weighting_sos(sample_rate)
    x = np.asarray(x, dtype=np.float32)
    n = x.size
    usable = (n // step_samples) * step_samples
    if usable <= 0:
        if n == 0:
            return np.zeros(0)
        return np.array([float(np.mean(x.astype(np.float64) ** 2))])
    energies: list[np.ndarray] = []
    zi = np.zeros((sos.shape[0], 2), dtype=np.float64)
    chunk_samples = max(step_samples, int(sample_rate * 10))
    chunk_samples = (chunk_samples // step_samples) * step_samples
    for start in range(0, usable, chunk_samples):
        end = min(usable, start + chunk_samples)
        segment = x[start:end]
        # Drop a partial step at the end of the final chunk.
        count = segment.size // step_samples
        if count <= 0:
            continue
        segment = segment[: count * step_samples]
        filtered, zi = signal.sosfilt(sos, segment.astype(np.float64), zi=zi)
        frame_energy = np.mean(
            filtered.reshape(-1, step_samples) ** 2, axis=1, dtype=np.float64
        )
        energies.append(frame_energy)
    if not energies:
        return np.zeros(0)
    return np.concatenate(energies)


def _sliding_mean(values: np.ndarray, window_frames: int) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    if values.size == 0:
        return values
    if values.size < window_frames:
        return np.array([float(np.mean(values))])
    kernel = np.ones(window_frames, dtype=np.float64) / window_frames
    return np.convolve(values, kernel, mode="valid")


def _weighted_channel_energy(data: np.ndarray, sample_rate: int, weights: list[float]) -> np.ndarray:
    channels = data.shape[1]
    step_samples = max(1, int(round(0.1 * sample_rate)))
    total: np.ndarray | None = None
    for index in range(channels):
        if weights[index] == 0.0:
            continue  # excluded channel (LFE)
        energies = _frame_energies(data[:, index], sample_rate, step_samples)
        weighted = energies * weights[index]
        if total is None:
            total = weighted
        else:
            size = min(total.size, weighted.size)
            total = total[:size] + weighted[:size]
    return total if total is not None else np.zeros(0)


def _loudness_from_energy(energy: np.ndarray) -> np.ndarray:
    """Block loudness in LUFS.  Zero-energy (digital silence) blocks are -inf;
    they are serialised as null rather than replaced by an invented floor."""
    energy = np.asarray(energy, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        values = -0.691 + 10.0 * np.log10(np.maximum(energy, 0.0))
    return values


def _finite(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    return values[np.isfinite(values)]


def _gated_integrated(block_energy: np.ndarray) -> tuple[float | None, np.ndarray, float | None]:
    """BS.1770 gated integration.  Returns (None, mask, None) when no block
    passes the absolute gate: integrated loudness is then undefined."""
    if block_energy.size == 0:
        return None, np.zeros(0, dtype=bool), None
    loudness = _loudness_from_energy(block_energy)
    above_abs = loudness > ABSOLUTE_GATE
    if not np.any(above_abs):
        return None, above_abs, None
    initial = -0.691 + 10.0 * math.log10(float(np.mean(block_energy[above_abs])))
    relative_threshold = initial + RELATIVE_GATE
    gated = above_abs & (loudness > relative_threshold)
    if not np.any(gated):
        gated = above_abs
    integrated = -0.691 + 10.0 * math.log10(float(np.mean(block_energy[gated])))
    return float(integrated), gated, float(relative_threshold)


def _lra(short_term_energy: np.ndarray, integrated: float | None) -> tuple[float | None, float | None, float | None, int]:
    if short_term_energy.size == 0 or integrated is None:
        return None, None, None, 0
    values = _loudness_from_energy(short_term_energy)
    above_abs = values > ABSOLUTE_GATE
    if not np.any(above_abs):
        return None, None, None, 0
    # EBU Tech 3342: the relative gate is -20 LU below the *ungated-by-relative*
    # energy mean of the absolute-gated short-term blocks.
    abs_mean = -0.691 + 10.0 * math.log10(float(np.mean(short_term_energy[above_abs])))
    gated = above_abs & (values > abs_mean + LRA_RELATIVE_GATE)
    selected = values[gated]
    if selected.size < 2:
        selected = values[above_abs]
    low = float(np.percentile(selected, 10))
    high = float(np.percentile(selected, 95))
    return max(0.0, high - low), low, high, int(selected.size)


def true_peak(data: np.ndarray, sample_rate: int, oversample: int = 4) -> tuple[float, list[float]]:
    """True peak in dBTP using 4x oversampling per BS.1770-4 Annex 2."""
    data = np.asarray(data, dtype=np.float32)
    if data.ndim == 1:
        data = data[:, None]
    n, channels = data.shape
    if n == 0:
        return -160.0, [-160.0] * channels
    chunk = max(1, int(round(4.0 * sample_rate)))
    pad = max(1, int(round(0.1 * sample_rate)))
    per_channel: list[float] = []
    for ch in range(channels):
        peak = 0.0
        for start in range(0, n, chunk):
            a = max(0, start - pad)
            b = min(n, start + chunk + pad)
            segment = data[a:b, ch].astype(np.float64)
            if segment.size == 0:
                continue
            try:
                upsampled = signal.resample_poly(segment, oversample, 1, window=("kaiser", 5.0))
            except Exception:
                upsampled = segment
            central_start = (start - a) * oversample
            central_end = min(upsampled.size, (min(n, start + chunk) - a) * oversample)
            if central_end > central_start:
                local = float(np.max(np.abs(upsampled[central_start:central_end])))
            else:
                local = float(np.max(np.abs(upsampled)))
            peak = max(peak, local)
        per_channel.append(20.0 * math.log10(peak) if peak > 0 else -160.0)
    return max(per_channel), [round_sig(v, 3) for v in per_channel]


def gain_preview(
    integrated_lufs: float | None,
    sample_peak_dbfs: float | None,
    true_peak_dbtp: float | None,
    target_lufs: float,
    true_peak_limit: float,
) -> dict[str, Any]:
    target_lufs = float(target_lufs)
    true_peak_limit = float(true_peak_limit)
    if integrated_lufs is None or integrated_lufs <= -69.9:
        return {
            "supported": False,
            "reason": "Integrated loudness is below the gating threshold; gain cannot be calculated reliably.",
            "target_lufs": round_sig(target_lufs, 2),
            "true_peak_limit": round_sig(true_peak_limit, 2),
        }
    # Recommended gain adjustment = target integrated loudness - measured.
    gain = target_lufs - integrated_lufs
    expected_sample = (sample_peak_dbfs + gain) if sample_peak_dbfs is not None else None
    expected_true = (true_peak_dbtp + gain) if true_peak_dbtp is not None else None
    required_reduction = 0.0
    if expected_true is not None and expected_true > true_peak_limit:
        required_reduction = expected_true - true_peak_limit
    # Largest linear gain that keeps the true peak at or below the limit.
    max_safe_gain = (true_peak_limit - true_peak_dbtp) if true_peak_dbtp is not None else None
    status = "ok"
    if expected_true is None:
        status = "true_peak_unknown"
    elif expected_true > true_peak_limit:
        status = "true_peak_limit_exceeded"
    elif expected_sample is not None and expected_sample > 0.0:
        status = "sample_peak_risk"
    reachable = bool(expected_true is not None and expected_true <= true_peak_limit)
    if status == "true_peak_limit_exceeded":
        safe = min(gain, max_safe_gain) if max_safe_gain is not None else None
        explanation = (
            f"The target cannot be reached by gain alone: {gain:+.2f} dB would put the true peak at "
            f"{expected_true:.2f} dBTP, {required_reduction:.2f} dB over the {true_peak_limit:.2f} dBTP limit. "
            f"Gain alone is limited to {safe:+.2f} dB (reaching {integrated_lufs + safe:.2f} LUFS); "
            "the remainder needs peak control such as limiting, which this tool does not apply."
        )
    elif status == "true_peak_unknown":
        safe = None
        explanation = "True peak is unknown, so the gain cannot be checked against the true-peak limit."
    else:
        safe = gain
        explanation = f"A linear gain of {gain:+.2f} dB reaches the target with the true peak at {expected_true:.2f} dBTP."
    return {
        "supported": True,
        "current_lufs": round_sig(integrated_lufs, 2),
        "target_lufs": round_sig(target_lufs, 2),
        "gain_db": round_sig(gain, 2),
        "expected_sample_peak_dbfs": round_sig(expected_sample, 2),
        "expected_true_peak_dbtp": round_sig(expected_true, 2),
        "true_peak_limit": round_sig(true_peak_limit, 2),
        "peak_control_required_db": round_sig(required_reduction, 2),
        "max_gain_within_true_peak_limit_db": round_sig(max_safe_gain, 2),
        "recommended_gain_db": round_sig(safe, 2),
        "loudness_after_recommended_gain_lufs": round_sig(integrated_lufs + safe, 2) if safe is not None else None,
        "target_reachable_with_gain_only": reachable,
        "true_peak_status": status,
        "explanation": explanation,
        "applied": False,
        "note": "Preview only. The original audio is never modified.",
    }


def _channel_levels(data: np.ndarray, chunk: int = 1 << 20) -> tuple[np.ndarray, np.ndarray]:
    """Per-channel sum of squares and peak |x|, streamed in float64 chunks so
    no full-length float64 copy of the signal is ever allocated."""
    n, channels = data.shape
    sumsq = np.zeros(channels, dtype=np.float64)
    peaks = np.zeros(channels, dtype=np.float64)
    for ch in range(channels):
        column = data[:, ch]
        for start in range(0, n, chunk):
            x = column[start:start + chunk].astype(np.float64)
            sumsq[ch] += float(np.dot(x, x))
            if x.size:
                peaks[ch] = max(peaks[ch], float(np.max(np.abs(x))))
    return sumsq, peaks


def measure_loudness(data: np.ndarray, sample_rate: int, channel_layout: str | None = None) -> dict[str, Any]:
    """Full EBU R128 / BS.1770 measurement for decoded audio."""
    data = np.asarray(data, dtype=np.float32)
    if data.ndim == 1:
        data = data[:, None]
    n, channels = data.shape
    if n == 0:
        return {"supported": False, "reason": "No audio samples"}
    sumsq, peaks = _channel_levels(data)
    sample_peak_linear = float(np.max(peaks))
    sample_peak_dbfs = db(sample_peak_linear)
    true_peak_dbtp, true_peak_channels = true_peak(data, sample_rate)
    rms_linear = float(math.sqrt(float(np.sum(sumsq)) / (n * channels)))
    rms_dbfs = db(rms_linear)
    channel_rms = [db(float(math.sqrt(value / n))) for value in sumsq]

    weights, channel_names, weight_source = channel_weights(channels, channel_layout)
    frame_energy = _weighted_channel_energy(data, sample_rate, weights)
    if frame_energy.size == 0:
        return {"supported": False, "reason": "Audio is too short for loudness gating"}
    momentary_energy = _sliding_mean(frame_energy, 4) if frame_energy.size >= 4 else np.array([float(np.mean(frame_energy))])
    short_frames = max(1, int(round(3.0 / 0.1)))
    short_energy = _sliding_mean(frame_energy, short_frames) if frame_energy.size >= short_frames else np.array([float(np.mean(frame_energy))])

    integrated, gated_mask, relative_threshold = _gated_integrated(momentary_energy)
    lra, lra_low, lra_high, lra_count = _lra(short_energy, integrated)

    # Block timestamps (centre of each block).
    def block_times(count: int, window_seconds: float) -> np.ndarray:
        if count <= 1:
            return np.array([min(window_seconds / 2.0, n / sample_rate / 2.0)])
        starts = np.arange(count, dtype=np.float64) * 0.1
        return np.minimum(starts + window_seconds / 2.0, n / sample_rate)

    momentary_times = block_times(momentary_energy.size, 0.4)
    short_times = block_times(short_energy.size, 3.0)
    momentary_lufs = _loudness_from_energy(momentary_energy)
    short_lufs = _loudness_from_energy(short_energy)
    short_finite = _finite(short_lufs)
    momentary_finite = _finite(momentary_lufs)

    def stat(values: np.ndarray, fn) -> float | None:
        return float(fn(values)) if values.size else None

    # Crest factor and PLR are undefined for silence (no RMS / no gated loudness).
    crest = (sample_peak_dbfs - rms_dbfs) if rms_linear > 0 else None
    plr = (true_peak_dbtp - integrated) if integrated is not None else None

    return {
        "supported": True,
        "integrated_lufs": round_sig(integrated, 2),
        "integrated_measurable": integrated is not None,
        "short_term_max_lufs": round_sig(stat(short_finite, np.max), 2),
        "short_term_min_lufs": round_sig(stat(short_finite, np.min), 2),
        "short_term_p95_lufs": round_sig(stat(short_finite, lambda v: np.percentile(v, 95)), 2),
        "short_term_p10_lufs": round_sig(stat(short_finite, lambda v: np.percentile(v, 10)), 2),
        "momentary_max_lufs": round_sig(stat(momentary_finite, np.max), 2),
        "momentary_min_lufs": round_sig(stat(momentary_finite, np.min), 2),
        "loudness_range_lu": round_sig(lra, 2),
        "lra_low_lufs": round_sig(lra_low, 2),
        "lra_high_lufs": round_sig(lra_high, 2),
        "lra_gated_blocks": lra_count,
        "sample_peak_dbfs": round_sig(sample_peak_dbfs, 2),
        "true_peak_dbtp": round_sig(true_peak_dbtp, 2),
        "true_peak_channels_dbtp": true_peak_channels,
        "rms_dbfs": round_sig(rms_dbfs, 2),
        "rms_linear": round_sig(rms_linear, 6),
        "channel_rms_dbfs": [round_sig(v, 2) for v in channel_rms],
        "crest_factor_db": round_sig(crest, 2),
        "peak_to_loudness_ratio_db": round_sig(plr, 2),
        "relative_gate_lufs": round_sig(relative_threshold, 2),
        "channel_names": channel_names,
        "channel_weights": weights,
        "gated_blocks": int(np.count_nonzero(gated_mask)),
        "block_count": int(momentary_energy.size),
        "short_term_block_count": int(short_energy.size),
        "momentary": {
            "times": [round_sig(v, 3) for v in momentary_times.tolist()],
            "lufs": [round_sig(v, 2) for v in momentary_lufs.tolist()],
        },
        "short_term": {
            "times": [round_sig(v, 3) for v in short_times.tolist()],
            "lufs": [round_sig(v, 2) for v in short_lufs.tolist()],
        },
        "method": {
            "standard": "ITU-R BS.1770-4 / EBU R128",
            "k_weighting": "Two-stage high-shelf + RLB high-pass, coefficients derived for the source sample rate",
            "momentary": "400 ms block, 75% overlap, absolute gate -70 LUFS",
            "integrated": "Gated mean of 400 ms blocks; absolute -70 LUFS and relative -10 LU gates",
            "loudness_range": "EBU Tech 3342: 3 s short-term blocks, absolute -70 LUFS and relative -20 LU gates, 10th-95th percentile",
            "true_peak": "4x polyphase oversampling (BS.1770-4 Annex 2)",
        },
        "confidence": "high" if n / sample_rate >= 3.0 else "low",
        "confidence_note": (
            "Full-length measurement"
            if n / sample_rate >= 3.0
            else "File is shorter than the 3 s short-term window; LRA confidence is low"
        ),
        "channel_count": channels,
        "channel_weighting_note": (
            f"BS.1770-4 weights by channel name ({weight_source}): front 1.0, surround 1.41, LFE excluded. "
            f"Channels: {', '.join(f'{name}={weight:g}' for name, weight in zip(channel_names, weights))}."
            if channels > 2 else "Unity channel weights per BS.1770-4"
        ),
        "momentary_note": "Blocks of digital silence have no defined loudness and are reported as null.",
    }
