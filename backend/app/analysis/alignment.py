"""Optional audio alignment using envelope or waveform cross-correlation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from scipy import signal

from ..audio_io import decode_audio
from .utils import round_sig


def _envelope(x: np.ndarray, sr: int, rate: int = 100) -> np.ndarray:
    frame = max(1, int(round(sr / rate)))
    n = x.size
    if n < frame:
        return np.array([float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))])
    usable = (n // frame) * frame
    frames = x[:usable].astype(np.float64).reshape(-1, frame)
    env = np.sqrt(np.mean(frames ** 2, axis=1))
    # Log compression makes quiet and loud sections contribute more evenly.
    env = np.log1p(env * 1000.0)
    # Remove the mean: an all-positive envelope correlates strongly with any
    # other positive envelope at every lag, which would make unrelated files
    # look aligned with high confidence.
    env = env - float(np.mean(env))
    return env


def _waveform_mono(x: np.ndarray, sr: int, target_rate: int = 8000, max_seconds: float = 120.0) -> tuple[np.ndarray, int]:
    mono = np.mean(x, axis=1, dtype=np.float64) if x.ndim > 1 else x.astype(np.float64)
    max_samples = int(max_seconds * sr)
    if mono.size > max_samples:
        mono = mono[:max_samples]
    if sr != target_rate:
        gcd = np.gcd(sr, target_rate)
        mono = signal.resample_poly(mono, target_rate // gcd, sr // gcd)
        sr = target_rate
    mono = mono - np.mean(mono)
    norm = float(np.sqrt(np.mean(mono ** 2)))
    if norm > 1e-12:
        mono = mono / norm
    return mono.astype(np.float64), sr


def _best_lag(a: np.ndarray, b: np.ndarray, max_lag: int, signed: bool = True) -> tuple[int, float, float, int]:
    """Return (lag, confidence, peak/second-peak ratio, polarity).

    With signed=True (waveforms) the largest |correlation| wins and polarity
    reports an inverted match; envelopes are non-negative quantities, so only
    positive correlation is meaningful (signed=False).
    """
    if a.size == 0 or b.size == 0:
        return 0, 0.0, 0.0, 1
    correlation = signal.fftconvolve(b, a[::-1], mode="full")
    lags = np.arange(-len(a) + 1, len(b))
    valid = np.abs(lags) <= max_lag
    if not np.any(valid):
        return 0, 0.0, 0.0, 1
    restricted = correlation[valid]
    lag_values = lags[valid]
    scores = np.abs(restricted) if signed else restricted
    peak_index = int(np.argmax(scores))
    peak = float(restricted[peak_index])
    norm = float(np.sqrt(np.sum(a * a) * np.sum(b * b)))
    confidence = max(0.0, (abs(peak) if signed else peak)) / norm if norm > 0 else 0.0
    # Second-best peak outside a small neighbourhood, for a stability check.
    mask = np.ones(restricted.size, dtype=bool)
    lo = max(0, peak_index - 3)
    hi = min(restricted.size, peak_index + 4)
    mask[lo:hi] = False
    second = float(np.max(scores[mask])) / norm if np.any(mask) and norm > 0 else 0.0
    ratio = confidence / second if second > 1e-12 else 99.0
    polarity = -1 if (signed and peak < 0) else 1
    return int(lag_values[peak_index]), min(1.0, confidence), ratio, polarity


def _overlap(duration_a: float, duration_b: float, offset: float) -> float:
    """Overlap in seconds when B's timeline maps to A's as t_a = t_b - offset.

    B then covers [-offset, duration_b - offset] on A's timeline.
    """
    return max(0.0, min(duration_a, duration_b - offset) - max(0.0, -offset))


def align_files(
    path_a: Path,
    path_b: Path,
    method: str = "auto",
    max_offset_seconds: float = 15.0,
    manual_offset_seconds: float | None = None,
) -> dict[str, Any]:
    data_a, sr_a, warn_a = decode_audio(path_a)
    data_b, sr_b, warn_b = decode_audio(path_b)
    duration_a = data_a.shape[0] / sr_a
    duration_b = data_b.shape[0] / sr_b
    base = {
        "file_a_duration": round_sig(duration_a, 3),
        "file_b_duration": round_sig(duration_b, 3),
        "duration_difference_seconds": round_sig(duration_b - duration_a, 3),
        "warnings": warn_a + warn_b,
        "does_not_modify_audio": True,
    }
    if manual_offset_seconds is not None:
        offset = float(manual_offset_seconds)
        return {
            **base,
            "method": "manual",
            "offset_seconds": round_sig(offset, 4),
            "offset_description": "Positive means file B starts later than file A. Shift B by -offset to align with A.",
            "confidence": 1.0,
            "confidence_label": "manual",
            "correlation": None,
            "overlap_seconds": round_sig(_overlap(duration_a, duration_b, offset), 3),
            "note": "Manual offset supplied by the user; no automatic alignment was performed.",
        }
    if duration_a < 0.25 or duration_b < 0.25:
        return {**base, "method": "unsupported", "offset_seconds": None, "confidence": 0.0, "reason": "Files are too short for alignment"}
    max_offset_seconds = max(0.5, min(float(max_offset_seconds), max(duration_a, duration_b)))
    method = (method or "auto").lower()
    envelope_result = None
    waveform_result = None
    if method in {"auto", "envelope"}:
        env_a = _envelope(np.mean(data_a, axis=1) if data_a.ndim > 1 else data_a, sr_a)
        env_b = _envelope(np.mean(data_b, axis=1) if data_b.ndim > 1 else data_b, sr_b)
        rate = 100.0
        max_lag = int(round(max_offset_seconds * rate))
        lag, confidence, ratio, _polarity = _best_lag(env_a, env_b, max_lag, signed=False)
        envelope_result = {
            "offset": lag / rate,
            "confidence": confidence,
            "ratio": ratio,
            "polarity": 1,
            "method_used": "envelope_cross_correlation",
            "detail": "100 Hz RMS envelope, log-compressed, normalised cross-correlation",
        }
    if method in {"auto", "waveform"}:
        mono_a, rate = _waveform_mono(data_a, sr_a)
        mono_b, _ = _waveform_mono(data_b, sr_b, target_rate=rate)
        max_lag = int(round(max_offset_seconds * rate))
        lag, confidence, ratio, polarity = _best_lag(mono_a, mono_b, max_lag, signed=True)
        waveform_result = {
            "offset": lag / rate,
            "confidence": confidence,
            "ratio": ratio,
            "polarity": polarity,
            "method_used": "waveform_cross_correlation",
            "detail": "8 kHz mono waveform, normalised cross-correlation, first 120 s",
        }
    chosen = envelope_result
    if method == "auto":
        candidates = [r for r in (envelope_result, waveform_result) if r is not None]
        chosen = max(candidates, key=lambda r: (r["confidence"], min(r["ratio"], 3.0))) if candidates else None
    elif method == "waveform":
        chosen = waveform_result
    if chosen is None:
        return {**base, "method": "unsupported", "offset_seconds": None, "confidence": 0.0, "reason": "Alignment method not available"}
    offset = chosen["offset"]
    confidence = chosen["confidence"]
    ratio = chosen["ratio"]
    method_used = chosen["method_used"]
    detail = chosen["detail"]
    overlap = _overlap(duration_a, duration_b, offset)
    label = "high" if confidence >= 0.75 and ratio >= 1.5 else "medium" if confidence >= 0.45 and ratio >= 1.15 else "low"
    return {
        **base,
        "method": method_used,
        "method_detail": detail,
        "offset_seconds": round_sig(offset, 4),
        "offset_samples_approx": int(round(offset * sr_a)),
        "offset_samples_reference_rate_hz": int(sr_a),
        "polarity_inverted": bool(chosen.get("polarity", 1) < 0),
        "reliable": label != "low",
        "offset_description": "Positive means file B starts later than file A. Shift B by -offset to align with A.",
        "apply_shift_to_b_seconds": round_sig(-offset, 4),
        "confidence": round_sig(confidence, 4),
        "confidence_label": label,
        "peak_to_second_ratio": round_sig(ratio, 3) if ratio < 99 else None,
        "overlap_seconds": round_sig(overlap, 3),
        "overlap_fraction": round_sig(overlap / max(min(duration_a, duration_b), 1e-9), 3),
        "alternate_method": (
            {"method": envelope_result["method_used"], "offset_seconds": round_sig(envelope_result["offset"], 4), "confidence": round_sig(envelope_result["confidence"], 4)}
            if method == "auto" and envelope_result is not None and chosen is waveform_result
            else {"method": waveform_result["method_used"], "offset_seconds": round_sig(waveform_result["offset"], 4), "confidence": round_sig(waveform_result["confidence"], 4)}
            if method == "auto" and waveform_result is not None and chosen is envelope_result
            else None
        ),
        "note": "Alignment is computed on decoded copies. Original files are untouched. Overlay plots should apply the offset to file B only over the overlapping region.",
    }
