"""Shared pytest fixtures for the audio analysis test suite.

The application data directory is redirected to a temporary folder *before*
the application modules are imported so that tests never touch real session
storage.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pytest

_DATA_DIR = Path(tempfile.mkdtemp(prefix="aap_pytest_data_"))
os.environ["AAP_DATA_DIR"] = str(_DATA_DIR)
os.environ["AAP_FRONTEND_DIST"] = str(_DATA_DIR / "frontend")
os.environ.setdefault("AAP_MAX_CONCURRENT_JOBS", "2")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def pytest_sessionfinish(session, exitstatus):  # pragma: no cover - cleanup helper
    shutil.rmtree(_DATA_DIR, ignore_errors=True)


@pytest.fixture(scope="session")
def client() -> TestClient:
    """A test client without lifespan shutdown so the job executor stays usable."""
    return TestClient(app)


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return _DATA_DIR


# --------------------------------------------------------------------- signals
def sine(
    frequency: float = 1000.0,
    amplitude: float = 0.5,
    seconds: float = 4.0,
    sample_rate: int = 48000,
    phase: float = 0.0,
    offset: float = 0.0,
) -> np.ndarray:
    t = np.arange(int(sample_rate * seconds)) / sample_rate
    return (amplitude * np.sin(2 * np.pi * frequency * t + phase) + offset).astype(np.float32)


def stereo_pair(
    left: np.ndarray,
    right: np.ndarray,
) -> np.ndarray:
    return np.stack([left, right], axis=1).astype(np.float32)


def click_track(bpm: float = 120.0, seconds: float = 8.0, sample_rate: int = 48000) -> np.ndarray:
    """A metronome-like click track with a strong onset every beat."""
    n = int(sample_rate * seconds)
    signal = np.zeros(n, dtype=np.float32)
    interval = 60.0 / bpm
    click_len = int(sample_rate * 0.02)
    t_click = np.arange(click_len) / sample_rate
    burst = 0.9 * np.sin(2 * np.pi * 1800.0 * t_click) * np.exp(-t_click * 120.0)
    position = 0
    while position < n:
        end = min(n, position + click_len)
        signal[position:end] += burst[: end - position]
        position += int(sample_rate * interval)
    return signal


def major_chord(root: float = 261.63, seconds: float = 4.0, sample_rate: int = 48000) -> np.ndarray:
    """A C major triad (C4, E4, G4) with a simple decaying envelope."""
    t = np.arange(int(sample_rate * seconds)) / sample_rate
    signal = np.zeros_like(t, dtype=np.float64)
    for ratio, level in ((1.0, 0.45), (1.2599, 0.30), (1.4983, 0.28)):
        signal += level * np.sin(2 * np.pi * root * ratio * t)
    envelope = np.exp(-0.6 * t) + 0.35
    return (signal * envelope / 1.03).astype(np.float32)


def write_wav(path: Path, data: np.ndarray, sample_rate: int = 48000, subtype: str = "PCM_16") -> Path:
    import soundfile as sf

    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), data, sample_rate, subtype=subtype)
    return path


@pytest.fixture
def wav_factory(tmp_path: Path):
    def _factory(name: str, data: np.ndarray, sample_rate: int = 48000, subtype: str = "PCM_16") -> Path:
        return write_wav(tmp_path / name, data, sample_rate, subtype)

    return _factory


@pytest.fixture
def analyzer(tmp_path: Path):
    """Run the full analysis pipeline over a written WAV file."""
    from app.analysis.pipeline import run_full_analysis

    def _analyze(path: Path, name: str | None = None, **kwargs):
        metadata = {"sample_rate": 48000, "channels": 1, "duration": 4.0}
        return run_full_analysis(
            path=path,
            ext=path.suffix,
            metadata=metadata,
            validation={"ok": True, "errors": [], "warnings": []},
            file_id="fil_test0000000000000000000000000000",
            original_name=name or path.name,
            **kwargs,
        )

    return _analyze
