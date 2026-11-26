"""Musical estimation tests: tempo, beats, pitch and key (all estimates)."""

from __future__ import annotations

import numpy as np
import pytest

from app.analysis.musical import analyze_musical
from conftest import click_track, major_chord, sine


def test_tempo_is_estimated_from_a_click_track():
    sr = 48000
    signal = click_track(bpm=120.0, seconds=8.0, sample_rate=sr)
    result = analyze_musical(signal, sr, 8.0)

    assert result["tempo"]["bpm"] is not None
    assert result["tempo"]["bpm"] == pytest.approx(120.0, abs=6.0)
    assert result["tempo"]["beat_count"] >= 10
    assert result["tempo"]["confidence_label"] in {"high", "medium", "low"}


def test_beats_are_aligned_with_the_click_grid():
    sr = 48000
    signal = click_track(bpm=120.0, seconds=8.0, sample_rate=sr)
    result = analyze_musical(signal, sr, 8.0)

    beats = result["tempo"]["beats"]
    assert len(beats) >= 10
    intervals = np.diff(beats)
    assert np.median(intervals) == pytest.approx(0.5, abs=0.05)
    # Every beat must fall on the 0.5 s click grid.
    offsets = np.mod(np.asarray(beats), 0.5)
    offsets = np.minimum(offsets, 0.5 - offsets)
    assert float(np.max(offsets)) < 0.08


def test_pitch_is_estimated_for_a_steady_tone():
    sr = 48000
    signal = sine(frequency=220.0, amplitude=0.4, seconds=4.0, sample_rate=sr)
    result = analyze_musical(signal, sr, 4.0)

    assert result["pitch"]["supported"] is True
    assert result["pitch"]["f0_median_hz"] == pytest.approx(220.0, rel=0.06)
    assert result["pitch"]["voiced_fraction"] > 0.5
    assert result["pitch"]["confidence_label"] in {"high", "medium", "low"}


def test_key_is_estimated_for_a_major_triad(wav_factory, analyzer):
    """The key estimate needs chroma input, so the full pipeline is used here."""
    path = wav_factory("chord.wav", major_chord(root=261.63, seconds=4.0))
    analysis = analyzer(path)
    key = analysis["musical"]["key"]

    assert key["supported"] is True
    assert key["key"] is not None
    assert key["key"].startswith("C")
    assert key["confidence"] is not None
    assert key["method"]


def test_musical_result_declares_estimates_and_limitations():
    sr = 48000
    signal = sine(frequency=440.0, amplitude=0.4, seconds=3.0, sample_rate=sr)
    result = analyze_musical(signal, sr, 3.0)

    assert result["confidence"]["key"] in {"low", "medium", "high"}
    assert result["confidence"]["tempo"] in {"low", "medium", "high"}
    assert result["limitations"]
    assert result["rhythm"]["onset_count"] >= 0
