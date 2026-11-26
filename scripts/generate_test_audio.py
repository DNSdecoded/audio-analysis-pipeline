"""Generate deterministic reference audio for validation and demos.

The generated files have analytically known properties so that measurements
can be checked against expectations:

* ``sine_1khz_mono_48k.wav``  - 1 kHz sine, -6.02 dBFS peak, 10 s
* ``sine_440_stereo.wav``     - 440 Hz sine with a 0.2 rad inter-channel phase offset
* ``click_120bpm.wav``        - 120 BPM click track (8 s)
* ``c_major_chord.wav``       - C major triad (C4/E4/G4) with a decaying envelope
* ``clipped_220.wav``         - hard-clipped 220 Hz sine (clipping must be detected)
* ``tone_with_noise_floor.wav`` - 1 kHz tone over a -60 dBFS noise floor
* ``dc_offset_tone.wav``      - 1 kHz tone with +0.01 DC offset
* ``silence_then_tone.wav``   - 2 s digital silence followed by a tone
* ``out_of_phase_stereo.wav`` - L/R inverted (correlation -1, mono fold-down loss)

Usage::

    python scripts/generate_test_audio.py --out backend/data/test_audio
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 48000


def _t(seconds: float) -> np.ndarray:
    return np.arange(int(SR * seconds)) / SR


def sine(frequency: float, amplitude: float, seconds: float) -> np.ndarray:
    return (amplitude * np.sin(2 * np.pi * frequency * _t(seconds))).astype(np.float32)


def click_track(bpm: float = 120.0, seconds: float = 8.0) -> np.ndarray:
    signal = np.zeros(int(SR * seconds), dtype=np.float32)
    click = np.arange(int(SR * 0.02)) / SR
    burst = 0.9 * np.sin(2 * np.pi * 1800.0 * click) * np.exp(-click * 120.0)
    step = int(SR * 60.0 / bpm)
    for position in range(0, signal.size, step):
        end = min(signal.size, position + burst.size)
        signal[position:end] += burst[: end - position]
    return signal


def major_chord(root: float = 261.63, seconds: float = 6.0) -> np.ndarray:
    t = _t(seconds)
    signal = np.zeros_like(t)
    for ratio, level in ((1.0, 0.45), (1.2599, 0.30), (1.4983, 0.28)):
        signal += level * np.sin(2 * np.pi * root * ratio * t)
    envelope = np.exp(-0.6 * t) + 0.35
    return (signal * envelope / 1.03).astype(np.float32)


def clipped_tone(frequency: float = 220.0, seconds: float = 6.0) -> np.ndarray:
    return np.clip(1.4 * np.sin(2 * np.pi * frequency * _t(seconds)), -1.0, 1.0).astype(np.float32)


def tone_with_noise_floor(frequency: float = 1000.0, amplitude: float = 0.5, seconds: float = 8.0) -> np.ndarray:
    rng = np.random.default_rng(20240517)
    noise = 0.001 * rng.normal(size=int(SR * seconds))
    signal = amplitude * np.sin(2 * np.pi * frequency * _t(seconds)) + noise
    signal[: SR * 2] = noise[: SR * 2]
    return signal.astype(np.float32)


def dc_offset_tone(seconds: float = 6.0) -> np.ndarray:
    return (0.4 * np.sin(2 * np.pi * 1000 * _t(seconds)) + 0.01).astype(np.float32)


def silence_then_tone(seconds: float = 8.0) -> np.ndarray:
    signal = np.zeros(int(SR * seconds), dtype=np.float32)
    signal[int(SR * 2):] = 0.4 * np.sin(2 * np.pi * 440 * _t(seconds - 2.0))
    return signal


def stereo(mono: np.ndarray, phase_radians: float = 0.0, invert_right: bool = False) -> np.ndarray:
    right = np.sin(2 * np.pi * 440.0 * _t(mono.size / SR) + phase_radians) if phase_radians else mono.copy()
    if invert_right:
        right = -right
    return np.stack([mono, right.astype(np.float32)], axis=1).astype(np.float32)


def write(path: Path, data: np.ndarray, subtype: str = "PCM_16") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), data, SR, subtype=subtype)
    print(f"wrote {path} ({path.stat().st_size / 1024:.1f} KiB)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="backend/data/test_audio", help="output directory")
    parser.add_argument(
        "--encodings",
        default="wav,flac,ogg",
        help="comma separated list of encodings to also produce (wav, flac, ogg, mp3)",
    )
    args = parser.parse_args()
    out = Path(args.out)
    encodings = [item.strip().lower() for item in args.encodings.split(",") if item.strip()]

    reference = {
        "sine_1khz_mono_48k.wav": sine(1000.0, 0.5, 10.0),
        "sine_440_stereo.wav": stereo(sine(440.0, 0.4, 10.0), phase_radians=0.2),
        "click_120bpm.wav": click_track(),
        "c_major_chord.wav": major_chord(),
        "clipped_220.wav": clipped_tone(),
        "tone_with_noise_floor.wav": tone_with_noise_floor(),
        "dc_offset_tone.wav": dc_offset_tone(),
        "silence_then_tone.wav": silence_then_tone(),
        "out_of_phase_stereo.wav": stereo(sine(440.0, 0.4, 10.0), invert_right=True),
    }

    for name, data in reference.items():
        write(out / name, data)

    mono_source = reference["sine_1khz_mono_48k.wav"]
    for encoding in encodings:
        if encoding == "wav":
            continue
        subtype = {"flac": "PCM_16", "ogg": "VORBIS", "mp3": "MP3"}.get(encoding)
        if subtype is None:
            print(f"skipping unknown encoding '{encoding}'")
            continue
        try:
            write(out / f"sine_1khz_mono_48k.{encoding}", mono_source, subtype=subtype)
        except Exception as exc:  # pragma: no cover - depends on libsndfile build
            print(f"could not write {encoding}: {exc}")


if __name__ == "__main__":
    main()
