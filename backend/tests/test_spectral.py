"""Spectral analysis tests: FFT accuracy, band energy and spectral features."""

from __future__ import annotations

import numpy as np
import pytest

from app.analysis.spectral import analyze_spectral, compute_average_spectrum, compute_spectrogram_range


def _tone(frequency: float, seconds: float = 4.0, sr: int = 48000, amplitude: float = 0.5) -> np.ndarray:
    t = np.arange(int(sr * seconds)) / sr
    return (amplitude * np.sin(2 * np.pi * frequency * t)).astype(np.float32)


def test_dominant_frequency_is_measured_within_one_bin():
    sr = 48000
    result = analyze_spectral(_tone(1000.0), sr, 4.0, n_fft=4096, hop_length=1024, max_spectrogram_frames=200)

    dominant = result["fft"]["dominant_frequency_hz"]
    assert dominant is not None
    assert dominant == pytest.approx(1000.0, abs=result["fft"]["bin_width_hz"] * 1.5)


def test_fft_amplitude_is_calibrated_to_dbfs():
    """A full-scale sine placed exactly on an FFT bin must read 0 dBFS."""
    sr = 48000
    n_fft = 4096
    bin_hz = sr / n_fft
    frequency = bin_hz * 85  # exactly on a bin centre
    result = analyze_spectral(_tone(frequency, amplitude=0.5), sr, 4.0, n_fft=n_fft, hop_length=1024, max_spectrogram_frames=200)

    freqs = np.asarray(result["fft"]["frequencies_hz"])
    amplitudes = np.asarray(result["fft"]["average_dbfs"])
    index = int(np.argmin(np.abs(freqs - frequency)))
    assert amplitudes[index] == pytest.approx(-6.02, abs=0.35)


def test_band_energy_follows_the_signal():
    sr = 48000
    low = analyze_spectral(_tone(40.0), sr, 4.0, n_fft=4096, hop_length=1024, max_spectrogram_frames=200)
    bands = {band["key"]: band for band in low["bands"]["bands"]}
    assert bands["sub_bass"]["relative_energy_pct"] > 50.0
    assert bands["sub_bass"]["supported"] is True
    assert sum(b["relative_energy_pct"] for b in bands.values()) == pytest.approx(100.0, abs=1.5)

    upper = analyze_spectral(_tone(100.0), sr, 4.0, n_fft=4096, hop_length=1024, max_spectrogram_frames=200)
    upper_bands = {band["key"]: band for band in upper["bands"]["bands"]}
    assert upper_bands["bass"]["relative_energy_pct"] > 50.0


def test_spectral_centroid_tracks_the_tone_frequency():
    sr = 48000
    result = analyze_spectral(_tone(5000.0), sr, 4.0, n_fft=4096, hop_length=1024, max_spectrogram_frames=200)
    centroid = result["spectral_features"]["centroid_hz"]["mean"]
    assert centroid == pytest.approx(5000.0, rel=0.2)


def test_spectral_flatness_is_low_for_a_tone_and_high_for_noise():
    sr = 48000
    tone = analyze_spectral(_tone(1000.0), sr, 4.0, n_fft=2048, hop_length=512, max_spectrogram_frames=200)
    rng = np.random.default_rng(11)
    noise = rng.normal(0, 0.2, int(sr * 4)).astype(np.float32)
    noisy = analyze_spectral(noise, sr, 4.0, n_fft=2048, hop_length=512, max_spectrogram_frames=200)

    assert tone["spectral_features"]["flatness"]["mean"] < noisy["spectral_features"]["flatness"]["mean"]
    assert tone["spectral_features"]["flatness"]["mean"] < 0.2


def test_spectrogram_dimensions_are_consistent():
    sr = 48000
    result = analyze_spectral(_tone(1000.0), sr, 4.0, n_fft=2048, hop_length=512, max_spectrogram_frames=120)
    spectrogram = result["spectrogram"]

    assert len(spectrogram["magnitude_db"]) == len(spectrogram["frequencies_hz"])
    assert all(len(row) == len(spectrogram["times"]) for row in spectrogram["magnitude_db"])
    assert len(spectrogram["times"]) <= 130


def test_compute_average_spectrum_and_range_endpoints():
    sr = 48000
    mono = _tone(1000.0)
    spectrum = compute_average_spectrum(mono, sr, 2048, 512)
    assert len(spectrum["frequencies_hz"]) == len(spectrum["average_dbfs"])
    assert spectrum["n_fft"] == 2048

    spec = compute_spectrogram_range(mono, sr, 2048, 512, 100)
    assert len(spec["times"]) > 0
    assert len(spec["magnitude_db"]) == len(spec["frequencies_hz"])
