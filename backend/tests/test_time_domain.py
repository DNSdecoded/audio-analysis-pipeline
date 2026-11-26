"""Time-domain measurement tests: levels, DC, clipping, silence, noise floor."""

from __future__ import annotations

import numpy as np
import pytest

from app.analysis.time_domain import analyze_time_domain


def test_rms_and_peak_match_analytic_values():
    sr = 48000
    data = (0.5 * np.sin(2 * np.pi * 1000 * np.arange(sr * 2) / sr)).astype(np.float32)
    result = analyze_time_domain(data, sr)

    assert result["sample_peak"]["dbfs"] == pytest.approx(-6.02, abs=0.1)
    assert result["rms"]["dbfs"] == pytest.approx(-9.03, abs=0.1)
    assert result["duration_seconds"] == pytest.approx(2.0, abs=0.01)
    assert result["channel_count"] == 1


def test_dc_offset_is_measured():
    sr = 48000
    data = (0.2 * np.sin(2 * np.pi * 220 * np.arange(sr * 2) / sr) + 0.01).astype(np.float32)
    result = analyze_time_domain(data, sr)

    assert result["dc_offset"]["max_abs"] == pytest.approx(0.01, abs=1e-4)
    assert result["dc_offset"]["per_channel"][0] == pytest.approx(0.01, abs=1e-4)


def test_clipping_is_detected_with_regions():
    sr = 48000
    t = np.arange(sr * 2) / sr
    signal = 1.4 * np.sin(2 * np.pi * 220 * t)
    clipped = np.clip(signal, -1.0, 1.0).astype(np.float32)
    result = analyze_time_domain(clipped, sr)

    assert result["clipping"]["clipped_samples"] > 0
    assert result["clipping"]["clipped_percent"] > 0
    assert len(result["clipping"]["regions"]) >= 1


def test_silence_and_digital_silence_are_detected():
    sr = 48000
    t = np.arange(sr * 3) / sr
    signal = np.zeros_like(t, dtype=np.float32)
    signal[sr:] = 0.4 * np.sin(2 * np.pi * 440 * t[sr:])
    result = analyze_time_domain(signal, sr)

    assert result["silence"]["duration_seconds"] > 0.5
    assert result["silence"]["digital_silence_duration_seconds"] > 0.5
    assert result["silence"]["regions"]


def test_true_peak_is_not_below_sample_peak():
    sr = 48000
    data = (0.7 * np.sin(2 * np.pi * 997 * np.arange(sr) / sr)).astype(np.float32)
    result = analyze_time_domain(data, sr)

    assert result["true_peak_dbtp"] is not None
    assert result["true_peak_dbtp"] >= result["sample_peak"]["dbfs"] - 0.05


def test_noise_floor_is_not_reported_for_a_pure_tone():
    sr = 48000
    data = (0.5 * np.sin(2 * np.pi * 1000 * np.arange(sr * 4) / sr)).astype(np.float32)
    result = analyze_time_domain(data, sr)

    assert result["noise"]["noise_floor_dbfs"] is None
    assert result["noise"]["snr_db"] is None
    assert result["noise"]["confidence"] == "unavailable"
    assert "not" in result["noise"]["method"].lower()


def test_noise_floor_is_reported_when_quiet_material_exists():
    sr = 48000
    t = np.arange(sr * 6) / sr
    noise = 0.001 * np.random.default_rng(7).normal(size=t.size)
    signal = 0.5 * np.sin(2 * np.pi * 1000 * t) + noise
    signal[: sr * 2] = noise[: sr * 2]
    result = analyze_time_domain(signal.astype(np.float32), sr)

    assert result["noise"]["noise_floor_dbfs"] is not None
    assert result["noise"]["noise_floor_dbfs"] < -40
    assert result["noise"]["snr_db"] > 20
    assert result["noise"]["confidence"] in {"medium", "high"}


def test_waveform_buckets_are_bounded():
    sr = 48000
    data = (0.2 * np.sin(2 * np.pi * 440 * np.arange(sr * 5) / sr)).astype(np.float32)
    result = analyze_time_domain(data, sr, max_waveform_buckets=500)

    assert result["waveform"]["bucket_count"] <= 500
    assert len(result["waveform"]["times"]) == result["waveform"]["bucket_count"]
    assert len(result["waveform"]["channels"]) == 1
