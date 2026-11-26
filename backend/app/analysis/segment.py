"""Analysis of a user-selected time range for segment comparisons."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..audio_io import decode_segment, probe_audio
from .dynamics import analyze_dynamics
from .loudness import gain_preview, measure_loudness
from .musical import analyze_musical
from .spectral import analyze_spectral
from .stereo import analyze_stereo
from .time_domain import analyze_time_domain
from .utils import round_sig


def analyze_segment(
    path: Path,
    ext: str,
    start: float,
    end: float,
    metadata: dict[str, Any] | None = None,
    target_lufs: float = -14.0,
    true_peak_limit: float = -1.0,
) -> dict[str, Any]:
    start = max(0.0, float(start))
    end = max(start + 0.1, float(end))
    data, sr, warnings = decode_segment(path, ext, start, end)
    duration = data.shape[0] / sr
    mono = np.mean(data, axis=1, dtype=np.float64).astype(np.float32)
    base_meta = dict(metadata or {})
    if not base_meta:
        base_meta = probe_audio(path, ext)
    segment_meta = dict(base_meta)
    segment_meta.update({
        "duration": round_sig(duration, 4),
        "frames": int(data.shape[0]),
        "original_duration": base_meta.get("duration"),
        "segment_start": round_sig(start, 3),
        "segment_end": round_sig(start + duration, 3),
        "analysis_mode": "segment",
    })
    loudness = measure_loudness(data, sr)
    time_domain = analyze_time_domain(
        data, sr, true_peak_dbtp=loudness.get("true_peak_dbtp"),
        max_points=500, max_waveform_buckets=1000,
    )
    spectral = analyze_spectral(
        mono, sr, duration,
        n_fft=4096, hop_length=1024,
        max_spectrogram_frames=250, max_feature_points=500,
        hpss_seconds=min(10.0, duration),
    )
    chroma_mean = np.asarray(spectral.get("chroma", {}).get("mean_energy", []), dtype=np.float64)
    musical = analyze_musical(
        mono, sr, duration, chroma_mean=chroma_mean,
        pitch_seconds=min(10.0, duration),
    )
    stereo = analyze_stereo(data, sr)
    dynamics = analyze_dynamics(loudness, time_domain, duration, musical.get("rhythm"))
    gain = gain_preview(
        loudness.get("integrated_lufs"), loudness.get("sample_peak_dbfs"),
        loudness.get("true_peak_dbtp"), target_lufs, true_peak_limit,
    )
    return {
        "mode": "segment",
        "segment": {"start": round_sig(start, 3), "end": round_sig(start + duration, 3), "duration": round_sig(duration, 3)},
        "metadata": segment_meta,
        "validation": {"ok": True, "errors": [], "warnings": warnings},
        "loudness": loudness,
        "time_domain": time_domain,
        "spectral": spectral,
        "musical": musical,
        "stereo": stereo,
        "dynamics": dynamics,
        "track_gain": gain,
        "analysis_settings": {
            "target_lufs": target_lufs,
            "true_peak_limit": true_peak_limit,
            "segment_start": start,
            "segment_end": end,
        },
    }
