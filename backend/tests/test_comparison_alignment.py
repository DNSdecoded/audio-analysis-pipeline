"""Comparison and alignment tests."""

from __future__ import annotations

import numpy as np
import pytest

from app.analysis.alignment import align_files
from app.analysis.comparison import PARAMETER_SPECS, compare_analyses
from conftest import sine


def _analyses(wav_factory, analyzer):
    quiet = wav_factory("quiet.wav", sine(frequency=440.0, amplitude=0.05, seconds=3.0))
    loud = wav_factory("loud.wav", sine(frequency=440.0, amplitude=0.6, seconds=3.0))
    analyses = {
        "fil_a": analyzer(quiet, name="quiet.wav"),
        "fil_b": analyzer(loud, name="loud.wav"),
    }
    names = {"fil_a": "quiet.wav", "fil_b": "loud.wav"}
    return analyses, names


def test_comparison_marks_level_differences(wav_factory, analyzer):
    analyses, names = _analyses(wav_factory, analyzer)
    result = compare_analyses(analyses, ["fil_a", "fil_b"], names, target_lufs=-14.0, true_peak_limit=-1.0)

    rows = {row["key"]: row for row in result["rows"]}
    assert "integrated_lufs" in rows
    assert rows["integrated_lufs"]["status"] in {"different", "large_deviation"}
    assert rows["integrated_lufs"]["spread"] > 5
    assert result["summary"]["match"] >= 1
    assert result["gain_preview"]
    assert result["method"]


def test_comparison_supports_a_reference_file(wav_factory, analyzer):
    analyses, names = _analyses(wav_factory, analyzer)
    result = compare_analyses(
        analyses, ["fil_a", "fil_b"], names, reference_file_id="fil_b", target_lufs=-14.0
    )
    row = next(row for row in result["rows"] if row["key"] == "integrated_lufs")

    assert row["reference_file_id"] == "fil_b"
    assert row["deviations"]["fil_b"] == pytest.approx(0.0, abs=0.01)
    assert row["deviations"]["fil_a"] < 0


def test_comparison_reports_unsupported_values_for_mono_stereo_pairs(wav_factory, analyzer):
    mono = wav_factory("mono.wav", sine(frequency=440.0, amplitude=0.3, seconds=3.0))
    stereo_signal = np.stack([
        sine(frequency=440.0, amplitude=0.3, seconds=3.0),
        sine(frequency=660.0, amplitude=0.3, seconds=3.0),
    ], axis=1)
    stereo = wav_factory("stereo.wav", stereo_signal)

    analyses = {
        "fil_mono": analyzer(mono, name="mono.wav"),
        "fil_stereo": analyzer(stereo, name="stereo.wav"),
    }
    names = {"fil_mono": "mono.wav", "fil_stereo": "stereo.wav"}
    result = compare_analyses(analyses, ["fil_mono", "fil_stereo"], names)

    correlation = next(row for row in result["rows"] if row["key"] == "correlation")
    assert correlation["status"] == "unsupported"
    assert correlation["display"]["fil_mono"] in {"—", "n/a", "unsupported"}


def test_parameter_specs_expose_tolerances_and_units():
    for spec in PARAMETER_SPECS:
        assert spec["key"]
        assert spec["label"]
        assert "unit" in spec
        assert spec["kind"] in {"numeric", "categorical", "band"}
        assert spec["tolerance"] >= 0
        assert spec["relative"] >= 0
        if spec["kind"] == "categorical":
            assert spec["tolerance"] == 0


def test_alignment_recovers_a_known_delay(wav_factory):
    sr = 48000
    base = sine(frequency=300.0, amplitude=0.4, seconds=4.0, sample_rate=sr)
    delay = 0.75
    shifted = np.concatenate([np.zeros(int(sr * delay), dtype=np.float32), base])
    path_a = wav_factory("align_a.wav", base)
    path_b = wav_factory("align_b.wav", shifted)

    result = align_files(path_a, path_b, method="auto", max_offset_seconds=5.0)

    assert result["offset_seconds"] is not None
    assert result["offset_seconds"] == pytest.approx(delay, abs=0.08)
    assert result["confidence"] > 0.2
    assert result["does_not_modify_audio"] is True
    assert result["confidence_label"] in {"high", "medium", "low"}


def test_manual_alignment_returns_the_supplied_offset(wav_factory):
    sr = 48000
    base = sine(frequency=300.0, amplitude=0.4, seconds=2.0, sample_rate=sr)
    path_a = wav_factory("manual_a.wav", base)
    path_b = wav_factory("manual_b.wav", base)

    result = align_files(path_a, path_b, manual_offset_seconds=1.25)

    assert result["method"] == "manual"
    assert result["offset_seconds"] == pytest.approx(1.25)
    assert result["confidence"] == 1.0
