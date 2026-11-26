"""Stereo tests: correlation, width, mono handling and phase observations."""

from __future__ import annotations

import numpy as np
import pytest

from app.analysis.stereo import analyze_stereo
from conftest import sine, stereo_pair


def test_identical_channels_are_fully_correlated():
    sr = 48000
    mono = sine(frequency=440.0, amplitude=0.4, seconds=3.0, sample_rate=sr)
    result = analyze_stereo(stereo_pair(mono, mono), sr)

    assert result["supported"] is True
    assert result["correlation"]["value"] == pytest.approx(1.0, abs=0.01)
    assert result["mid_side"]["stereo_width_percent"] == pytest.approx(0.0, abs=1.0)
    assert result["balance"]["balance_db"] == pytest.approx(0.0, abs=0.01)


def test_inverted_channels_are_negatively_correlated():
    sr = 48000
    mono = sine(frequency=440.0, amplitude=0.4, seconds=3.0, sample_rate=sr)
    result = analyze_stereo(stereo_pair(mono, -mono), sr)

    assert result["correlation"]["value"] == pytest.approx(-1.0, abs=0.01)
    assert result["mono_compatibility"]["mono_loss_db"] < -30
    assert result["mono_compatibility"]["compatible"] is False


def test_mono_input_is_reported_as_mono_without_stereo_values():
    sr = 48000
    mono = sine(frequency=440.0, amplitude=0.4, seconds=2.0, sample_rate=sr)
    result = analyze_stereo(mono, sr)

    assert result["supported"] is False
    assert result["mono"] is True
    assert "mono" in result["reason"].lower()
    assert result["mono_rms_dbfs"] == pytest.approx(-10.97, abs=0.2)
    assert "correlation" not in result
    assert "mid_side" not in result
    assert result["mono_compatibility"]["applicable"] is False


def test_channel_imbalance_is_flagged():
    sr = 48000
    left = sine(frequency=440.0, amplitude=0.4, seconds=2.0, sample_rate=sr)
    right = sine(frequency=440.0, amplitude=0.1, seconds=2.0, sample_rate=sr)
    result = analyze_stereo(stereo_pair(left, right), sr)

    assert result["balance"]["balance_db"] < -10
    assert any(issue["type"] == "channel_imbalance" for issue in result["issues"])


def test_timeline_and_vectorscope_are_populated():
    sr = 48000
    left = sine(frequency=440.0, amplitude=0.4, seconds=3.0, sample_rate=sr)
    right = sine(frequency=660.0, amplitude=0.4, seconds=3.0, sample_rate=sr)
    result = analyze_stereo(stereo_pair(left, right), sr)

    assert result["timeline"]["times"]
    assert len(result["timeline"]["correlation"]) == len(result["timeline"]["times"])
    assert result["vectorscope"]["point_count"] > 0
    assert len(result["vectorscope"]["left"]) == len(result["vectorscope"]["right"])
    assert result["channel_envelope"]["times"]
