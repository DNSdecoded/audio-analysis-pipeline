"""Stereo, mid/side and phase analysis."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .utils import db, merge_regions, regions_from_mask, round_sig


def _window_stats(left: np.ndarray, right: np.ndarray, sr: int, max_points: int = 600) -> dict[str, list[float]]:
    win = max(8, int(round(1.0 * sr)))
    hop = max(1, int(round(0.5 * sr)))
    if left.size < win:
        win = left.size
        hop = max(1, win // 2)
    if win < 4:
        return {"times": [], "correlation": [], "width": [], "mid_db": [], "side_db": []}
    frames_l = np.lib.stride_tricks.sliding_window_view(left.astype(np.float64), win)[::hop]
    frames_r = np.lib.stride_tricks.sliding_window_view(right.astype(np.float64), win)[::hop]
    count = frames_l.shape[0]
    if count == 0:
        return {"times": [], "correlation": [], "width": [], "mid_db": [], "side_db": []}
    corr = np.zeros(count)
    width = np.zeros(count)
    mid_db = np.zeros(count)
    side_db = np.zeros(count)
    block = 128
    for start in range(0, count, block):
        end = min(count, start + block)
        l = frames_l[start:end]
        r = frames_r[start:end]
        mean_l = np.mean(l, axis=1)
        mean_r = np.mean(r, axis=1)
        cov = np.mean(l * r, axis=1) - mean_l * mean_r
        var_l = np.var(l, axis=1)
        var_r = np.var(r, axis=1)
        denom = np.sqrt(np.maximum(var_l * var_r, 1e-20))
        corr[start:end] = np.where((var_l > 1e-12) & (var_r > 1e-12), cov / denom, 0.0)
        mid = (l + r) / 2.0
        side = (l - r) / 2.0
        mid_rms = np.sqrt(np.mean(mid ** 2, axis=1))
        side_rms = np.sqrt(np.mean(side ** 2, axis=1))
        width[start:end] = side_rms / np.maximum(mid_rms, 1e-12)
        mid_db[start:end] = 20.0 * np.log10(np.maximum(mid_rms, 1e-10))
        side_db[start:end] = 20.0 * np.log10(np.maximum(side_rms, 1e-10))
    times = np.arange(count) * hop / sr + win / 2.0 / sr
    if count > max_points:
        idx = np.linspace(0, count - 1, max_points).astype(int)
        times, corr, width, mid_db, side_db = times[idx], corr[idx], width[idx], mid_db[idx], side_db[idx]
    return {
        "times": [round_sig(v, 3) for v in times.tolist()],
        "correlation": [round_sig(v, 4) for v in corr.tolist()],
        "width": [round_sig(v, 4) for v in width.tolist()],
        "mid_db": [round_sig(v, 2) for v in mid_db.tolist()],
        "side_db": [round_sig(v, 2) for v in side_db.tolist()],
    }


def analyze_stereo(data: np.ndarray, sr: int) -> dict[str, Any]:
    data = np.asarray(data, dtype=np.float32)
    if data.ndim == 1:
        data = data[:, None]
    n, channels = data.shape
    if channels == 1:
        mono = data[:, 0].astype(np.float64)
        rms = float(np.sqrt(np.mean(mono ** 2)))
        return {
            "supported": False,
            "mono": True,
            "channel_count": 1,
            "reason": "Mono file: stereo width, correlation and mid/side metrics do not exist. No artificial stereo values are reported.",
            "mono_rms_dbfs": round_sig(db(rms), 2),
            "mono_peak_dbfs": round_sig(db(float(np.max(np.abs(mono)))), 2),
            "mono_compatibility": {
                "applicable": False,
                "note": "A mono file is inherently mono; fold-down compatibility is not applicable.",
            },
            "confidence": "high",
        }
    if channels > 2:
        channel_note = f"{channels} channels detected; stereo metrics use channels 1 and 2 only."
    else:
        channel_note = None
    left = data[:, 0].astype(np.float64)
    right = data[:, 1].astype(np.float64)
    n = min(left.size, right.size)
    left = left[:n]
    right = right[:n]
    rms_l = float(np.sqrt(np.mean(left ** 2)))
    rms_r = float(np.sqrt(np.mean(right ** 2)))
    peak_l = float(np.max(np.abs(left)))
    peak_r = float(np.max(np.abs(right)))
    sum_rms = rms_l + rms_r
    balance_db = 20.0 * math.log10(max(rms_r, 1e-12) / max(rms_l, 1e-12))
    balance_ratio = (rms_r - rms_l) / sum_rms if sum_rms > 0 else 0.0
    if abs(balance_db) < 0.5:
        balance_label = "centred"
    elif balance_db > 0:
        balance_label = f"{abs(balance_db):.1f} dB right"
    else:
        balance_label = f"{abs(balance_db):.1f} dB left"

    # Decimate for correlation and vectorscope; preserves statistical structure.
    step = max(1, n // 2_000_000)
    ld = left[::step]
    rd = right[::step]
    # Pearson correlation is undefined when either channel has no variance
    # (digital silence or a constant); report None rather than a fake 0.0.
    correlation: float | None = None
    if ld.size > 1:
        var_l = float(np.var(ld))
        var_r = float(np.var(rd))
        if var_l > 1e-20 and var_r > 1e-20:
            cov = float(np.mean((ld - np.mean(ld)) * (rd - np.mean(rd))))
            correlation = max(-1.0, min(1.0, cov / math.sqrt(var_l * var_r)))
    corr_value = correlation if correlation is not None else 0.0

    mid = (left + right) / 2.0
    side = (left - right) / 2.0
    mid_rms = float(np.sqrt(np.mean(mid ** 2)))
    side_rms = float(np.sqrt(np.mean(side ** 2)))
    stereo_rms = math.sqrt((np.mean(left ** 2) + np.mean(right ** 2)) / 2.0)
    mono_fold = (left + right) / 2.0
    mono_rms = float(np.sqrt(np.mean(mono_fold ** 2)))
    mono_loss_db = 20.0 * math.log10(max(mono_rms, 1e-12) / max(stereo_rms, 1e-12))
    mono_peak = float(np.max(np.abs(mono_fold)))
    width_ratio = side_rms / max(mid_rms, 1e-12)
    width_percent = 100.0 * side_rms / max(mid_rms + side_rms, 1e-12)

    timeline = _window_stats(ld, rd, sr // step if step else sr, max_points=600)
    corr_values = np.asarray(timeline["correlation"], dtype=np.float64)
    times = np.asarray(timeline["times"], dtype=np.float64)
    phase_regions = []
    if corr_values.size:
        phase_regions = regions_from_mask(times, corr_values < -0.1, gap=0.6)
        for region in phase_regions:
            mask = (times >= region["start"]) & (times <= region["end"])
            region["mean_correlation"] = round_sig(float(np.mean(corr_values[mask])), 4) if np.any(mask) else None
        phase_regions = phase_regions[:50]

    # Vectorscope points, evenly sampled over the file.
    points = min(3000, ld.size)
    if points > 0:
        idx = np.linspace(0, ld.size - 1, points).astype(int)
        scope_l = ld[idx]
        scope_r = rd[idx]
        # Normalise display only; raw amplitude values remain available via peak fields.
        peak_scope = max(float(np.max(np.abs(scope_l))), float(np.max(np.abs(scope_r))), 1e-9)
        scope_l = scope_l / peak_scope
        scope_r = scope_r / peak_scope
    else:
        scope_l = scope_r = np.array([])

    # Left/right RMS envelope for the channel-comparison plot.
    env_points = min(600, n)
    if env_points > 1:
        idx = np.linspace(0, n - 1, env_points).astype(int)
        l_db = 20.0 * np.log10(np.maximum(np.abs(left[idx]), 1e-10))
        r_db = 20.0 * np.log10(np.maximum(np.abs(right[idx]), 1e-10))
        env_times = idx / sr
    else:
        l_db = r_db = np.array([])
        env_times = np.array([])

    issues = []
    if abs(balance_db) > 1.5:
        issues.append({
            "type": "channel_imbalance",
            "severity": "warning",
            "message": f"Right/left RMS difference is {balance_db:+.2f} dB.",
            "measurement": {"left_rms_dbfs": round_sig(db(rms_l), 2), "right_rms_dbfs": round_sig(db(rms_r), 2), "balance_db": round_sig(balance_db, 2)},
            "recommendation": "Check panning, channel routing, and whether one side was recorded or processed at a different level.",
        })
    if min(rms_l, rms_r) < 1e-4 and max(rms_l, rms_r) > 1e-2:
        issues.append({
            "type": "silent_channel",
            "severity": "error",
            "message": "One channel is effectively silent while the other carries signal.",
            "measurement": {"left_rms_dbfs": round_sig(db(rms_l), 2), "right_rms_dbfs": round_sig(db(rms_r), 2)},
            "recommendation": "Inspect the source file and export routing; a silent channel is usually a capture or render error.",
        })
    if correlation is not None and correlation < -0.1:
        issues.append({
            "type": "negative_phase_correlation",
            "severity": "warning",
            "message": f"Stereo correlation is {corr_value:.3f} (negative). Mono fold-down may cause cancellation.",
            "measurement": {"correlation": round_sig(correlation, 4), "mono_loss_db": round_sig(mono_loss_db, 2)},
            "recommendation": "Check microphone polarity, stereo widening, and phase alignment. Audition the mono fold-down before release.",
        })
    if mono_loss_db < -6.0:
        issues.append({
            "type": "mono_compatibility_loss",
            "severity": "warning",
            "message": f"Mono fold-down loses {abs(mono_loss_db):.2f} dB relative to the stereo program.",
            "measurement": {"mono_loss_db": round_sig(mono_loss_db, 2), "correlation": round_sig(correlation, 4)},
            "recommendation": "Check phase relationships and wide stereo effects; ensure the mix remains acceptable in mono.",
        })
    if width_ratio > 2.0:
        issues.append({
            "type": "very_wide_stereo",
            "severity": "info",
            "message": f"Side energy is {width_ratio:.2f}x mid energy (width {width_percent:.1f}%).",
            "measurement": {"side_to_mid_ratio": round_sig(width_ratio, 3), "width_percent": round_sig(width_percent, 2)},
            "recommendation": "Very wide material can lose energy in mono; compare the fold-down and check the intended presentation.",
        })
    if phase_regions:
        issues.append({
            "type": "phase_cancellation_sections",
            "severity": "info",
            "message": f"{len(phase_regions)} time region(s) show negative short-term correlation.",
            "measurement": {"regions": phase_regions[:10]},
            "recommendation": "Inspect these sections for polarity or phase problems; localized negative correlation can also be an intentional wide effect.",
        })

    mono_compatible = (correlation >= -0.1 and mono_loss_db > -6.0) if correlation is not None else None
    return {
        "supported": True,
        "mono": False,
        "channel_count": int(channels),
        "channel_note": channel_note,
        "left": {
            "rms_dbfs": round_sig(db(rms_l), 2),
            "peak_dbfs": round_sig(db(peak_l), 2),
            "rms_linear": round_sig(rms_l, 8),
        },
        "right": {
            "rms_dbfs": round_sig(db(rms_r), 2),
            "peak_dbfs": round_sig(db(peak_r), 2),
            "rms_linear": round_sig(rms_r, 8),
        },
        "balance": {
            "balance_db": round_sig(balance_db, 2),
            "balance_ratio": round_sig(balance_ratio, 4),
            "label": balance_label,
            "method": "20*log10(RMS right / RMS left); positive values favour the right channel.",
        },
        "correlation": {
            "value": round_sig(correlation, 4),
            "phase_correlation": round_sig(correlation, 4),
            "channel_similarity": round_sig(correlation, 4),
            "interpretation": (
                "undefined (a channel has no signal)" if correlation is None
                else "in phase" if correlation > 0.5 else "partially correlated" if correlation > -0.1 else "out of phase"
            ),
        },
        "mid_side": {
            "mid_rms_dbfs": round_sig(db(mid_rms), 2),
            "side_rms_dbfs": round_sig(db(side_rms), 2),
            "mid_linear": round_sig(mid_rms, 8),
            "side_linear": round_sig(side_rms, 8),
            "side_to_mid_ratio": round_sig(width_ratio, 4),
            "stereo_width_percent": round_sig(width_percent, 2),
            "method": "Mid=(L+R)/2, Side=(L-R)/2; width is side RMS relative to mid RMS.",
        },
        "mono_compatibility": {
            "applicable": True,
            "mono_fold_rms_dbfs": round_sig(db(mono_rms), 2),
            "stereo_program_rms_dbfs": round_sig(db(stereo_rms), 2),
            "mono_loss_db": round_sig(mono_loss_db, 2),
            "mono_peak_dbfs": round_sig(db(mono_peak), 2),
            "mono_peak_exceeds_0dbfs": bool(mono_peak > 1.0),
            "compatible": mono_compatible,
            "method": "Level of (L+R)/2 relative to the average channel RMS; 0 dB means no fold-down loss.",
        },
        "timeline": timeline,
        "vectorscope": {
            "left": [round_sig(v, 5) for v in scope_l.tolist()],
            "right": [round_sig(v, 5) for v in scope_r.tolist()],
            "normalized_to": round_sig(peak_scope, 6) if points > 0 else None,
            "point_count": int(points),
            "method": "Evenly sampled L/R pairs, normalized to the largest displayed sample. The Lissajous view uses the same data.",
        },
        "channel_envelope": {
            "times": [round_sig(v, 3) for v in env_times.tolist()],
            "left_db": [round_sig(v, 2) for v in l_db.tolist()],
            "right_db": [round_sig(v, 2) for v in r_db.tolist()],
            "note": "Instantaneous absolute sample values sampled evenly; use the waveform view for peak envelopes.",
        },
        "phase_regions": phase_regions,
        "issues": issues,
        "confidence": "high" if n / max(sr, 1) >= 1.0 else "medium",
        "method": "Full-length Pearson correlation on a decimated copy (preserves correlation), 1 s windowed correlation/width timeline, mid/side energy, and mono fold-down comparison.",
    }
