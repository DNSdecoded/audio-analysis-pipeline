"""Loudness tests: BS.1770-4 / EBU R128, true peak and the gain preview."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import signal as scipy_signal

from app.analysis.loudness import gain_preview, measure_loudness, true_peak


def _sine(frequency: float, amplitude: float, seconds: float, sr: int) -> np.ndarray:
    t = np.arange(int(sr * seconds)) / sr
    return (amplitude * np.sin(2 * np.pi * frequency * t)).astype(np.float32)


def test_integrated_loudness_matches_analytic_reference():
    """A 1 kHz sine at -6 dBFS peak has K-weighted loudness of about -9.06 LUFS.

    The BS.1770 K-weighting filter has +0.691 dB of gain at 1 kHz, which is
    exactly what the -0.691 constant in the loudness formula compensates for.
    """
    sr = 48000
    data = _sine(1000.0, 0.5, 6.0, sr)
    result = measure_loudness(data, sr)

    k_weight_gain_db = 0.691
    expected = -0.691 + 10 * math.log10(10 ** (k_weight_gain_db / 10) * 0.5 ** 2 / 2)
    assert result["integrated_lufs"] == pytest.approx(expected, abs=0.2)
    assert result["sample_peak_dbfs"] == pytest.approx(-6.02, abs=0.05)
    assert result["crest_factor_db"] == pytest.approx(
        result["sample_peak_dbfs"] - result["rms_dbfs"], abs=0.05
    )
    assert result["method"]["standard"] == "ITU-R BS.1770-4 / EBU R128"


def test_integrated_loudness_matches_pyloudnorm_when_available():
    pyloudnorm = pytest.importorskip("pyloudnorm")
    sr = 48000
    data = _sine(1000.0, 0.25, 5.0, sr)
    meter = pyloudnorm.Meter(sr)
    reference = meter.integrated_loudness(data.astype(np.float64))
    result = measure_loudness(data, sr)

    assert result["integrated_lufs"] == pytest.approx(reference, abs=0.2)


def test_true_peak_agrees_with_independent_oversampling():
    sr = 48000
    t = np.arange(sr) / sr
    # 12 kHz tone sampled at 48 kHz creates intersample peaks below 0 dBFS.
    data = (0.9 * np.sin(2 * np.pi * 12000 * t)).astype(np.float32)
    measured, channels = true_peak(data, sr)

    upsampled = scipy_signal.resample_poly(data.astype(np.float64), 4, 1, window=("kaiser", 5.0))
    reference = 20 * math.log10(float(np.max(np.abs(upsampled))))

    assert measured == pytest.approx(reference, abs=0.3)
    assert len(channels) == 1
    assert measured > 20 * math.log10(float(np.max(np.abs(data))))


def test_gain_preview_computes_linear_gain_and_peak_control():
    preview = gain_preview(-20.0, -6.0, -5.9, -14.0, -1.0)

    assert preview["supported"] is True
    assert preview["gain_db"] == pytest.approx(6.0)
    assert preview["expected_sample_peak_dbfs"] == pytest.approx(0.0, abs=0.01)
    assert preview["expected_true_peak_dbtp"] == pytest.approx(0.1, abs=0.01)
    assert preview["peak_control_required_db"] == pytest.approx(1.1, abs=0.01)
    assert preview["true_peak_status"] == "true_peak_limit_exceeded"
    assert preview["applied"] is False


def test_gain_preview_reports_ok_when_peaks_stay_below_the_limit():
    preview = gain_preview(-23.0, -12.0, -11.5, -14.0, -1.0)

    assert preview["gain_db"] == pytest.approx(9.0)
    assert preview["expected_true_peak_dbtp"] == pytest.approx(-2.5, abs=0.01)
    assert preview["true_peak_status"] == "ok"
    assert preview["peak_control_required_db"] == pytest.approx(0.0)


def test_gain_preview_is_unsupported_below_the_gate():
    preview = gain_preview(-70.0, -60.0, -60.0, -14.0, -1.0)

    assert preview["supported"] is False
    assert "gating" in preview["reason"].lower()


def test_loudness_blocks_have_consistent_lengths():
    sr = 48000
    data = _sine(1000.0, 0.5, 8.0, sr)
    result = measure_loudness(data, sr)

    assert len(result["momentary"]["times"]) == len(result["momentary"]["lufs"])
    assert len(result["short_term"]["times"]) == len(result["short_term"]["lufs"])
    assert result["block_count"] > 0
    assert result["gated_blocks"] <= result["block_count"]
    assert result["confidence"] == "high"
