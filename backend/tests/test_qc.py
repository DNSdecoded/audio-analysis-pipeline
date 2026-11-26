"""Quality-control tests: classification, thresholds and reporting fields."""

from __future__ import annotations

import numpy as np
import pytest

from app.analysis.qc import DEFAULT_THRESHOLDS, THRESHOLD_SCHEMA, analyze_qc, merge_thresholds
from conftest import sine


def _clipped(seconds: float = 4.0, sr: int = 48000) -> np.ndarray:
    t = np.arange(int(sr * seconds)) / sr
    signal = 1.4 * np.sin(2 * np.pi * 220 * t)
    return np.clip(signal, -1.0, 1.0).astype(np.float32)


def test_merge_thresholds_keeps_error_thresholds_consistent():
    merged = merge_thresholds({"clipping_percent_warning": 5.0, "clipping_percent_error": 1.0})

    assert merged["clipping_percent_error"] >= merged["clipping_percent_warning"]
    assert merged["true_peak_error_dbtp"] >= merged["true_peak_warning_dbtp"]
    assert merged["silence_percent_error"] >= merged["silence_percent_warning"]
    # Unknown keys are ignored and defaults survive.
    assert "not_a_threshold" not in merged
    assert merged["common_sample_rates"] == DEFAULT_THRESHOLDS["common_sample_rates"]


def test_threshold_schema_matches_the_default_thresholds():
    for field in THRESHOLD_SCHEMA:
        assert field["key"] in DEFAULT_THRESHOLDS
        assert field["min"] <= DEFAULT_THRESHOLDS[field["key"]] <= field["max"]


def test_clean_tone_produces_no_qc_errors(wav_factory, analyzer):
    path = wav_factory("clean.wav", sine(frequency=440.0, amplitude=0.4, seconds=4.0))
    analysis = analyzer(path)
    qc = analysis["qc"]

    assert qc["error_count"] == 0
    assert qc["overall"] in {"normal", "information"}
    assert qc["checks"]
    assert qc["method"]


def test_clipping_is_classified_as_an_error(wav_factory, analyzer):
    path = wav_factory("clipped.wav", _clipped())
    analysis = analyzer(path)
    qc = analysis["qc"]

    clipping = next(check for check in qc["checks"] if check["id"] == "clipping")
    assert clipping["severity"] == "error"
    assert clipping["measured_value"] > 0
    assert clipping["time_positions"]
    assert qc["overall"] == "error"


def test_every_check_contains_explanation_and_recommendation(wav_factory, analyzer):
    path = wav_factory("clean2.wav", sine(frequency=330.0, amplitude=0.4, seconds=3.0))
    analysis = analyzer(path)

    for check in analysis["qc"]["checks"]:
        assert check["severity"] in {"normal", "information", "warning", "error"}
        assert check["explanation"]
        assert check["recommendation"]
        assert check["confidence"] in {"high", "medium", "low", "unavailable"}
        assert isinstance(check["time_positions"], list)


def test_threshold_overrides_reclassify_existing_measurements(wav_factory, analyzer):
    path = wav_factory("tone3.wav", sine(frequency=220.0, amplitude=0.4, seconds=3.0))
    analysis = analyzer(path)

    strict = analyze_qc(analysis, {"true_peak_warning_dbtp": -40.0, "true_peak_error_dbtp": -39.0})
    strict_true_peak = next(check for check in strict["checks"] if check["id"] == "true_peak")
    assert strict_true_peak["severity"] == "error"
    assert strict["error_count"] >= 1

    loose = analyze_qc(analysis, {"true_peak_warning_dbtp": 6.0, "true_peak_error_dbtp": 6.0})
    loose_true_peak = next(check for check in loose["checks"] if check["id"] == "true_peak")
    assert loose_true_peak["severity"] == "normal"


def test_noise_floor_is_information_not_an_error(wav_factory, analyzer):
    path = wav_factory("tone4.wav", sine(frequency=440.0, amplitude=0.4, seconds=4.0))
    analysis = analyzer(path)
    qc = analysis["qc"]

    assert analysis["time_domain"]["noise"]["noise_floor_dbfs"] is None
    assert qc["error_count"] == 0
    assert all(check["severity"] != "error" for check in qc["checks"])
